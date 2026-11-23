"""Thu thập số liệu giám sát (telemetry) và nhật ký hệ thống tập trung – phục vụ màn hình Giám sát.

Mọi dịch vụ ghi bản ghi nhỏ vào Redis Stream (giới hạn độ dài, tự xoay vòng); audit-svc đọc và tổng hợp
theo khung thời gian (/monitor/*). Không cần thêm thành phần (Prometheus, ELK) trên mạng nội bộ.

    Luồng            Ghi bởi                       Nội dung
    tel:http         middleware mọi dịch vụ        dịch vụ, đường dẫn, mã trạng thái, thời gian (ms)
    tel:llm          AsyncLLM / SyncLLM             tác vụ, mô hình, thời gian, token vào/ra, tốc độ sinh
    tel:chat         orchestrator                   người dùng, luồng, tổng thời gian, thời gian ra chữ đầu,
                                                    kiểm chứng, từ chối, hỏi lại
    tel:task         agent-svc                      tác vụ dài: loại, trạng thái, thời gian
    tel:logs         RedisLogHandler                nhật ký mức WARNING trở lên và sự kiện nghiệp vụ (extra={"event": ...})

Mã bản ghi Redis Stream là thời điểm mili giây → truy vấn theo khoảng thời gian bằng XRANGE, không cần chỉ mục.
Lỗi Redis không bao giờ làm gián đoạn nghiệp vụ (ghi thất bại được bỏ qua, tạm ngừng ghi 30 giây).
"""
import json
import logging
import time
from functools import lru_cache

import redis

from .config import get_settings

STREAMS = ("tel:http", "tel:llm", "tel:chat", "tel:task", "tel:logs")
_pause_until = 0.0


@lru_cache
def _r() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1,
                                decode_responses=True)


def record(stream: str, **fields):
    """Ghi một bản ghi số liệu. Giá trị phức tạp được mã hóa JSON trong trường 'd'."""
    global _pause_until
    s = get_settings()
    if not s.telemetry_enabled or time.time() < _pause_until:
        return
    keep = s.logs_keep if stream == "tel:logs" else s.telemetry_keep
    try:
        _r().xadd(stream, {"d": json.dumps({"service": s.service_name, **fields}, ensure_ascii=False, default=str)},
                  maxlen=keep, approximate=True)
    except Exception:  # Redis không khả dụng: tạm ngừng ghi, không ảnh hưởng xử lý chính
        _pause_until = time.time() + 30


def read(stream: str, since_s: float, until_s: float | None = None, limit: int = 50000) -> list[dict]:
    """Đọc các bản ghi trong khoảng [since_s, until_s] (giây Unix). Mỗi bản ghi có thêm 'ts' (giây)."""
    lo = f"{int(since_s * 1000)}-0"
    hi = f"{int(until_s * 1000)}-0" if until_s else "+"
    out = []
    for mid, f in _r().xrange(stream, min=lo, max=hi, count=limit):
        try:
            d = json.loads(f.get("d", "{}"))
        except json.JSONDecodeError:
            continue
        d["ts"] = int(mid.split("-")[0]) / 1000
        d["id"] = mid
        out.append(d)
    return out


def read_last(stream: str, n: int = 200) -> list[dict]:
    out = []
    for mid, f in _r().xrevrange(stream, count=n):
        try:
            d = json.loads(f.get("d", "{}"))
        except json.JSONDecodeError:
            continue
        d["ts"] = int(mid.split("-")[0]) / 1000
        d["id"] = mid
        out.append(d)
    return out


class RedisLogHandler(logging.Handler):
    """Đẩy nhật ký mức WARNING trở lên, và bản ghi có extra={"event": "..."} (sự kiện nghiệp vụ mức INFO),
    vào luồng tel:logs để xem tập trung trên màn hình Giám sát › Nhật ký hệ thống."""

    def emit(self, r: logging.LogRecord):
        if r.levelno < logging.WARNING and not getattr(r, "event", None):
            return
        if r.name.startswith(("httpx", "httpcore", "urllib3", "redis")):
            return  # tránh vòng lặp và nhiễu từ thư viện mạng
        try:
            d = {"level": r.levelname, "logger": r.name, "msg": r.getMessage()[:2000],
                 "event": getattr(r, "event", ""), "request_id": getattr(r, "request_id", "")}
            if r.exc_info:
                d["exc"] = logging.Formatter().formatException(r.exc_info)[-3000:]
            record("tel:logs", **d)
        except Exception:
            pass


def llm_usage(data: dict, prompt_chars: int, out_text: str) -> tuple[int, int]:
    """Số token vào/ra: lấy từ trường usage của máy chủ mô hình, nếu không có thì ước lượng (ký tự / 3)."""
    u = (data or {}).get("usage") or {}
    pin = int(u.get("prompt_tokens") or 0) or prompt_chars // 3
    pout = int(u.get("completion_tokens") or 0) or len(out_text or "") // 3
    return pin, pout


def record_llm(task: str | None, model: str, started: float, ok: bool, tokens_in: int = 0, tokens_out: int = 0,
               first_token_s: float | None = None, error: str = ""):
    ms = (time.perf_counter() - started) * 1000
    gen_s = (ms / 1000) - (first_token_s or 0)
    record("tel:llm", task=task or "", model=model, ms=round(ms), ok=ok, tin=tokens_in, tout=tokens_out,
           ttft=round(first_token_s * 1000) if first_token_s else None,
           tps=round(tokens_out / gen_s, 2) if tokens_out and gen_s > 0.05 else None, err=error[:200])
