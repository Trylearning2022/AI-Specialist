"""Tiến trình nền của agent-svc (Celery, hàng đợi "agent").

Chạy 01 tiến trình (-c 1) trên máy chủ CPU: các tác vụ dài lần lượt dùng mô hình, đồng thời nhường cho
hỏi đáp trực tiếp (aicommon/priority.py). Trên GPU có thể tăng số tiến trình.
"""
import logging

from aicommon.app import setup_logging
from aicommon.config import get_settings
from aicommon.db import init_db
from aicommon.queue import celery_app

from . import analyze, draft, gopy, quality, synth
from .runner import execute

log = logging.getLogger("agent.worker")
HANDLERS = {"phan_tich": analyze.run, "soan_thao": draft.run, "gop_y": gopy.run, "tong_hop": synth.run}
_inited = False


def _init():
    global _inited
    if not _inited:
        get_settings().service_name = "agent-worker"
        setup_logging()
        init_db()
        _inited = True


@celery_app.task(name="agent.run")
def run_task(task_id: str):
    _init()
    execute(task_id, HANDLERS)


@celery_app.task(name="agent.qa")
def run_qa(run_id: str):
    _init()
    quality.run(run_id)
