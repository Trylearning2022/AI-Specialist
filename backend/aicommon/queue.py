"""Hàng đợi tác vụ nền (Celery + Redis): nạp dữ liệu, tổng hợp báo cáo."""
from celery import Celery

from .config import get_settings

_s = get_settings()
celery_app = Celery("ai_local", broker=_s.redis_url, backend=_s.redis_url,
                    include=["services.ingest.worker", "services.summary.worker"])
celery_app.conf.update(
    task_routes={"ingest.*": {"queue": "ingest"}, "summary.*": {"queue": "summary"}},
    task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True,
    result_expires=86400, broker_connection_retry_on_startup=True,
    task_time_limit=3 * 3600, task_soft_time_limit=3 * 3600 - 60,
)
