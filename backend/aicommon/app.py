"""Khung ứng dụng FastAPI dùng chung: nhật ký JSON (stdout + luồng tập trung), /health, /metrics,
mã truy vết, số liệu giám sát từng yêu cầu (aicommon/telemetry.py)."""
import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .config import get_settings
from .telemetry import RedisLogHandler, record

REQ = Counter("http_requests_total", "Số yêu cầu", ["service", "method", "path", "status"])
LAT = Histogram("http_request_seconds", "Thời gian xử lý", ["service", "path"])


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(r), "level": r.levelname, "logger": r.name, "msg": r.getMessage(),
             "service": get_settings().service_name}
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, ensure_ascii=False)


class _PeerResetFilter(logging.Filter):
    """Bỏ thông báo nhiễu của asyncio trên Windows (ProactorEventLoop):
        Exception in callback _ProactorBasePipeTransport._call_connection_lost() … ConnectionResetError [WinError 10054]
    Xuất hiện khi phía kia (trình duyệt, cổng API, dịch vụ gọi) đóng kết nối trước – ví dụ hủy yêu cầu, hết thời gian
    chờ, đóng kết nối giữ sống. Bản thân thông báo không phải lỗi nghiệp vụ; lỗi thật (nếu có) được ghi riêng ở dịch vụ
    đã gọi. Chỉ lọc đúng trường hợp này, các lỗi asyncio khác vẫn ghi bình thường."""

    def filter(self, r: logging.LogRecord) -> bool:
        exc = r.exc_info[1] if r.exc_info else None
        return not (isinstance(exc, (ConnectionResetError, ConnectionAbortedError))
                    and "_call_connection_lost" in r.getMessage())


def setup_logging():
    logging.getLogger("asyncio").addFilter(_PeerResetFilter())
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    rh = RedisLogHandler(level=logging.INFO)  # nhật ký tập trung cho màn hình Giám sát (WARNING+ và sự kiện nghiệp vụ)
    root.handlers[:] = [h, rh]
    root.setLevel(get_settings().log_level)


def create_app(name: str, **kw) -> FastAPI:
    s = get_settings()
    s.service_name = name
    setup_logging()
    app = FastAPI(title=f"AI Local – {name}", **kw)

    @app.middleware("http")
    async def mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        t = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:
            logging.getLogger(name).exception("Lỗi không xử lý được: %s %s", request.method, request.url.path)
            resp = JSONResponse({"detail": "Lỗi nội bộ dịch vụ"}, status_code=500)
        route = request.scope.get("route")
        path = getattr(route, "path", "khac")
        dt = time.perf_counter() - t
        REQ.labels(name, request.method, path, resp.status_code).inc()
        LAT.labels(name, path).observe(dt)
        if path not in ("/health", "/metrics", "khac"):
            # Luồng SSE: thời gian ở đây là thời gian tới khi bắt đầu trả luồng (tổng thời gian ghi ở tel:chat)
            record("tel:http", path=path, method=request.method, status=resp.status_code, ms=round(dt * 1000))
        resp.headers["x-request-id"] = rid
        return resp

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "service": name}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
