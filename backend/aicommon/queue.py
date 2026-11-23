"""Hàng đợi tác vụ nền (Celery + Redis).

    Hàng đợi   Tiến trình            Nội dung
    ingest     ingest-worker         nạp dữ liệu (chuyển đổi, OCR, chấm điểm)
    summary    summary-worker        tổng hợp báo cáo (giao diện cũ, API giữ tương thích)
    agent      agent-worker (-c 1)   tác vụ dài: phân tích văn bản, soạn thảo, tổng hợp; giám định dữ liệu
"""
from celery import Celery

from .config import get_settings

_s = get_settings()
celery_app = Celery("ai_local", broker=_s.redis_url, backend=_s.redis_url,
                    include=["services.ingest.worker", "services.summary.worker", "services.agent.worker"])
celery_app.conf.update(
    task_routes={"ingest.*": {"queue": "ingest"}, "summary.*": {"queue": "summary"}, "agent.*": {"queue": "agent"}},
    task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True,
    result_expires=86400, broker_connection_retry_on_startup=True,
    task_time_limit=3 * 3600, task_soft_time_limit=3 * 3600 - 60,
    # Không chuyển stdout thành nhật ký mức WARNING (tránh nhân đôi nhật ký JSON vào luồng nhật ký tập trung)
    worker_redirect_stdouts=False,
)
