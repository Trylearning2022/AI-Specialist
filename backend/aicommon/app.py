"""Khung ứng dụng FastAPI dùng chung: nhật ký JSON, /health, /metrics, mã truy vết."""
import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .config import get_settings

REQ = Counter("http_requests_total", "Số yêu cầu", ["service", "method", "path", "status"])
LAT = Histogram("http_request_seconds", "Thời gian xử lý", ["service", "path"])


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(r), "level": r.levelname, "logger": r.name, "msg": r.getMessage(),
             "service": get_settings().service_name}
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, ensure_ascii=False)


def setup_logging():
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
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
        REQ.labels(name, request.method, path, resp.status_code).inc()
        LAT.labels(name, path).observe(time.perf_counter() - t)
        resp.headers["x-request-id"] = rid
        return resp

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "service": name}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
