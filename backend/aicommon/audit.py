"""Phát sự kiện kiểm toán vào Redis Stream; audit-svc ghi vào CSDL theo chuỗi băm."""
import json
import logging
import time
from functools import lru_cache

import redis

from .config import get_settings

log = logging.getLogger("audit")
STREAM = "audit"


@lru_cache
def _redis():
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=2)


def emit(actor: str, action: str, resource: str = "", detail: dict | None = None):
    event = {"ts": time.time(), "actor": actor, "action": action, "resource": resource,
             "service": get_settings().service_name, "detail": detail or {}}
    try:
        _redis().xadd(STREAM, {"data": json.dumps(event, ensure_ascii=False, default=str)}, maxlen=1_000_000)
    except Exception as e:  # không để lỗi kiểm toán làm gián đoạn nghiệp vụ, nhưng ghi nhật ký cảnh báo
        log.error("Không ghi được sự kiện kiểm toán: %s | %s", e, json.dumps(event, ensure_ascii=False, default=str))
