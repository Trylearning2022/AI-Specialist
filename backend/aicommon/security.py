"""Ngữ cảnh người dùng và xác thực nội bộ giữa các dịch vụ.

API Gateway xác thực người dùng (OIDC/Keycloak), sau đó chuyển ngữ cảnh người dùng
cho các dịch vụ phía sau qua header X-User (base64 JSON) kèm chữ ký HMAC-SHA256
X-Internal-Sig. Dịch vụ nội bộ chỉ tin ngữ cảnh có chữ ký hợp lệ.
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings

ROLE_USER, ROLE_REVIEWER, ROLE_ADMIN = "user", "reviewer", "admin"
DO_MAT = {0: "Thường", 1: "Mật", 2: "Tối mật", 3: "Tuyệt mật"}
SIG_TTL = 300  # giây


class UserCtx(BaseModel):
    sub: str
    username: str
    name: str = ""
    roles: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    clearance: int = 0

    def has(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles)

    @property
    def effective_clearance(self) -> int:
        return min(self.clearance, get_settings().system_max_clearance)


SYSTEM_USER = UserCtx(sub="system", username="system", name="Hệ thống",
                      roles=[ROLE_ADMIN, ROLE_REVIEWER, ROLE_USER], units=["*"], clearance=3)


def _sig(payload: str, ts: str) -> str:
    key = get_settings().internal_secret.encode()
    return hmac.new(key, f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()


def sign_user(user: UserCtx) -> dict[str, str]:
    payload = base64.urlsafe_b64encode(json.dumps(user.model_dump(), ensure_ascii=False).encode()).decode()
    ts = str(int(time.time()))
    return {"X-User": payload, "X-User-Ts": ts, "X-Internal-Sig": _sig(payload, ts)}


def verify_user(x_user: str | None, ts: str | None, sig: str | None) -> UserCtx:
    if not (x_user and ts and sig):
        raise HTTPException(401, "Thiếu ngữ cảnh người dùng")
    if not hmac.compare_digest(_sig(x_user, ts), sig):
        raise HTTPException(401, "Chữ ký nội bộ không hợp lệ")
    if abs(time.time() - int(ts)) > SIG_TTL:
        raise HTTPException(401, "Chữ ký nội bộ đã hết hạn")
    return UserCtx(**json.loads(base64.urlsafe_b64decode(x_user.encode())))


def sign_service() -> dict[str, str]:
    """Danh tính dịch vụ gọi (ingest, tools…) – gateway không bao giờ tạo/chuyển tiếp các header này."""
    name = get_settings().service_name or "tools"
    ts = str(int(time.time()))
    return {"x-service": name, "x-service-ts": ts, "x-service-sig": _sig(f"svc:{name}", ts)}


def require_service(*names: str):
    """Chỉ cho phép dịch vụ nội bộ có tên trong names gọi (chặn gọi trực tiếp qua API Gateway)."""
    def dep(x_service: str | None = Header(None), x_service_ts: str | None = Header(None),
            x_service_sig: str | None = Header(None)) -> str:
        if not (x_service and x_service_ts and x_service_sig) \
                or not hmac.compare_digest(_sig(f"svc:{x_service}", x_service_ts), x_service_sig):
            raise HTTPException(403, "Chức năng chỉ dành cho dịch vụ nội bộ")
        if abs(time.time() - int(x_service_ts)) > SIG_TTL or x_service not in names:
            raise HTTPException(403, "Chức năng chỉ dành cho dịch vụ nội bộ")
        return x_service
    return dep


def current_user(
    x_user: str | None = Header(None),
    x_user_ts: str | None = Header(None),
    x_internal_sig: str | None = Header(None),
) -> UserCtx:
    return verify_user(x_user, x_user_ts, x_internal_sig)


def require(*roles: str):
    def dep(user: UserCtx = Depends(current_user)) -> UserCtx:
        if not user.has(*roles):
            raise HTTPException(403, "Không đủ quyền thực hiện")
        return user
    return dep


# ---------- Kiểm soát truy cập theo độ mật, đơn vị ----------
def can_access(user: UserCtx, do_mat: int, don_vi: list[str] | None) -> bool:
    if int(do_mat or 0) > user.effective_clearance:
        return False
    units = don_vi or ["chung"]
    if "chung" in units or "*" in user.units:
        return True
    return bool(set(units) & set(user.units))


def allowed_units(user: UserCtx) -> list[str] | None:
    """None = không giới hạn đơn vị."""
    return None if "*" in user.units else ["chung", *user.units]
