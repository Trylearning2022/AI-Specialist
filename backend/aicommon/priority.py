"""Ưu tiên hỏi đáp trực tiếp khi dùng chung một máy chủ mô hình (CPU).

Trên CPU, llama-server thực chất phục vụ hiệu quả một yêu cầu nặng tại một thời điểm. Tác vụ dài
(phân tích tài liệu, soạn thảo, tổng hợp, giám định dữ liệu) chạy nền sẽ làm hỏi đáp của mọi người chậm hẳn.
Cơ chế ở đây đơn giản và an toàn:

    orchestrator:   async with interactive():  …sinh câu trả lời…      (đánh dấu "đang có người hỏi")
    tác vụ nền:     wait_idle(max_s)  trước MỖI lượt gọi mô hình         (chờ tới khi không còn ai hỏi,
                                                                          tối đa max_s giây để không treo)

Đánh dấu là phần tử trong Redis sorted set với hạn dùng (score = thời điểm hết hạn): tiến trình chết
giữa chừng cũng không để lại khóa vĩnh viễn.
"""
import contextlib
import time
import uuid
from functools import lru_cache

import redis
import redis.asyncio as aioredis

from .config import get_settings

KEY = "prio:interactive"
TTL = 600  # một lượt hỏi đáp dài nhất được tính là "đang hỏi" (giây)


@lru_cache
def _sync() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=2)


_async: aioredis.Redis | None = None


def _ar() -> aioredis.Redis:
    global _async
    if _async is None:
        _async = aioredis.Redis.from_url(get_settings().redis_url, socket_timeout=2)
    return _async


@contextlib.asynccontextmanager
async def interactive():
    """Đánh dấu một lượt hỏi đáp trực tiếp đang chạy."""
    m = uuid.uuid4().hex
    try:
        await _ar().zadd(KEY, {m: time.time() + TTL})
    except Exception:
        m = None
    try:
        yield
    finally:
        if m:
            try:
                await _ar().zrem(KEY, m)
            except Exception:
                pass


def active() -> int:
    """Số lượt hỏi đáp trực tiếp đang chạy."""
    try:
        r = _sync()
        r.zremrangebyscore(KEY, 0, time.time())
        return int(r.zcard(KEY))
    except Exception:
        return 0


def wait_idle(max_s: int | None = None, poll: float = 2.0, on_wait=None) -> float:
    """Chờ tới khi không còn hỏi đáp trực tiếp (tối đa max_s giây). Trả về số giây đã chờ.
    on_wait(giây_đã_chờ) được gọi định kỳ để tác vụ cập nhật trạng thái "đang nhường cho hỏi đáp"."""
    max_s = get_settings().agent_yield_max_s if max_s is None else max_s
    t0 = time.monotonic()
    while max_s > 0 and active() > 0 and time.monotonic() - t0 < max_s:
        if on_wait:
            on_wait(time.monotonic() - t0)
        time.sleep(poll)
    return time.monotonic() - t0
