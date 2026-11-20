"""api-gateway – xác thực (OIDC/Keycloak), giới hạn tần suất, chuyển tiếp tới dịch vụ nội bộ
kèm ngữ cảnh người dùng đã ký, ghi nhật ký kiểm toán."""
import logging
import time
from functools import lru_cache

import httpx
import jwt
import redis.asyncio as aioredis
import yaml
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from aicommon.app import create_app
from aicommon.audit import emit
from aicommon.config import get_settings
from aicommon.security import UserCtx, sign_user

log = logging.getLogger("gateway")
S = get_settings()
app = create_app("gateway", docs_url="/api/docs", openapi_url="/api/openapi.json")

if S.auth_mode == "dev" and not S.dev_auth_allowed:
    # Chặn cấu hình nhầm: đăng nhập không mật khẩu không được phép chạy trên hệ thống vận hành
    raise RuntimeError("AUTH_MODE=dev chỉ dùng trên máy phát triển: đặt thêm DEV_AUTH_ALLOWED=true nếu đúng là môi trường thử nghiệm")
if S.auth_mode == "dev":
    log.warning("ĐANG CHẠY CHẾ ĐỘ ĐĂNG NHẬP THỬ NGHIỆM (AUTH_MODE=dev) – KHÔNG DÙNG CHO VẬN HÀNH")
ROUTES = {"chat": S.orchestrator_url, "search": S.search_url, "exact": S.exact_url, "ingest": S.ingest_url,
          "summary": S.summary_url, "support": S.support_url, "audit": S.audit_url}
HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "upgrade", "authorization",
       "x-user", "x-user-ts", "x-internal-sig", "x-service", "x-service-ts", "x-service-sig", "cookie"}
# Chức năng chỉ dành cho gọi nội bộ giữa các dịch vụ: không bao giờ chuyển tiếp từ bên ngoài
INTERNAL_ONLY = {"exact": ("kb/",), "search": ("index", "docs/")}
ROLES = ("user", "reviewer", "admin")
client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))
_jwks: jwt.PyJWKClient | None = None
_redis: aioredis.Redis | None = None


# ---------------- Xác thực ----------------
@lru_cache
def dev_users() -> dict:
    try:
        with open(S.dev_users_file, encoding="utf-8") as f:
            return yaml.safe_load(f).get("users", {})
    except FileNotFoundError:
        return {}


def _from_claims(c: dict) -> UserCtx:
    roles = c.get("realm_access", {}).get("roles", [])
    units = [g.strip("/").split("/")[-1] for g in c.get("groups", []) if g.strip("/").startswith("don-vi/")]
    units = ["*" if u == "tat-ca" else u for u in units]  # nhóm /don-vi/tat-ca: được xem tài liệu mọi đơn vị
    levels = [int(r.split("-")[-1]) for r in roles if r.startswith("cap-do-") and r.split("-")[-1].isdigit()]
    return UserCtx(sub=c["sub"], username=c.get("preferred_username", c["sub"]), name=c.get("name", ""),
                   roles=[r for r in roles if r in ROLES] or ["user"], units=units, clearance=max(levels or [0]))


def authenticate(request: Request) -> UserCtx:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(401, "Chưa đăng nhập")
    if S.auth_mode == "dev":
        u = dev_users().get(token.removeprefix("dev-"))
        if not u:
            raise HTTPException(401, "Tài khoản thử nghiệm không tồn tại")
        return UserCtx(sub=f"dev:{token}", username=token.removeprefix("dev-"), **u)
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(S.oidc_jwks_url, cache_keys=True, lifespan=600)
    try:
        key = _jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256", "ES256", "PS256"], issuer=S.oidc_issuer,
                            options={"verify_aud": False, "require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Phiên đăng nhập không hợp lệ: {e}") from e
    if claims.get("azp") not in S.oidc_allowed_azp.split(","):
        raise HTTPException(401, "Ứng dụng khách không được phép")
    return _from_claims(claims)


async def rate_limit(user: UserCtx, bucket: str, limit: int):
    global _redis
    if _redis is None:
        _redis = aioredis.Redis.from_url(S.redis_url)
    key = f"rl:{bucket}:{user.sub}:{int(time.time() // 60)}"
    try:
        n = await _redis.incr(key)
        if n == 1:
            await _redis.expire(key, 70)
    except Exception as e:  # Redis lỗi: không chặn người dùng, ghi cảnh báo
        log.warning("Không kiểm tra được giới hạn tần suất: %s", e)
        return
    if n > limit:
        raise HTTPException(429, "Vượt giới hạn số yêu cầu mỗi phút, vui lòng thử lại sau")


# ---------------- API ----------------
@app.get("/api/me")
def me(user: UserCtx = Depends(authenticate)):
    return {**user.model_dump(), "effective_clearance": user.effective_clearance,
            "system_max_clearance": S.system_max_clearance}


@app.get("/api/config")
def public_config():
    """Cấu hình công khai cho giao diện (không chứa bí mật)."""
    return {"auth_mode": S.auth_mode, "oidc_issuer": S.oidc_issuer,
            "oidc_client_id": S.oidc_allowed_azp.split(",")[0],
            "dev_users": list(dev_users().keys()) if S.auth_mode == "dev" else []}


@app.get("/api/health")
async def health_all():
    out = {}
    for name, base in ROUTES.items():
        try:
            r = await client.get(f"{base}/health", timeout=5)
            out[name] = "ok" if r.status_code == 200 else f"lỗi {r.status_code}"
        except httpx.HTTPError as e:
            out[name] = f"không kết nối ({type(e).__name__})"
    return {"status": "ok" if all(v == "ok" for v in out.values()) else "degraded", "services": out}


@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(service: str, path: str, request: Request, user: UserCtx = Depends(authenticate)):
    base = ROUTES.get(service)
    if not base:
        raise HTTPException(404, "Dịch vụ không tồn tại")
    if any(path.lstrip("/").startswith(p) for p in INTERNAL_ONLY.get(service, ())) or ".." in path:
        raise HTTPException(404, "Không tìm thấy")
    is_chat = service == "chat" and path == "chat"
    await rate_limit(user, "chat" if is_chat else "api",
                     S.rate_limit_chat_per_min if is_chat else S.rate_limit_per_min)
    clen = int(request.headers.get("content-length") or 0)
    if clen > S.max_upload_mb * 1024 * 1024 + 1_000_000:
        raise HTTPException(413, "Yêu cầu quá lớn")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers.update(sign_user(user))
    headers["x-request-id"] = request.headers.get("x-request-id", "")
    body = await request.body()
    url = f"{base}/{path}"
    req = client.build_request(request.method, url, params=request.query_params, content=body, headers=headers)
    try:
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Dịch vụ {service} không khả dụng") from e
    if request.method != "GET" and service != "chat":
        emit(user.username, f"api.{request.method.lower()}", f"/{service}/{path}", {"status": resp.status_code})
    out_headers = {k: v for k, v in resp.headers.items()
                   if k.lower() in ("content-type", "content-disposition", "cache-control", "x-request-id",
                                    "x-accel-buffering")}
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        async def gen():
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            finally:
                await resp.aclose()
        return StreamingResponse(gen(), status_code=resp.status_code, headers=out_headers)
    content = await resp.aread()
    await resp.aclose()
    return Response(content, status_code=resp.status_code, headers=out_headers)


@app.exception_handler(HTTPException)
async def http_err(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
