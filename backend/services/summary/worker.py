"""Tác vụ tổng hợp theo kỹ năng (summary-svc). Thuật toán dùng chung ở services/summary/core.py:
Map (tóm tắt từng văn bản, trích số liệu) → tính toán bằng mã → Reduce (viết báo cáo theo mẫu) → Verifier."""
import logging

from aicommon.config import get_settings
from aicommon.db import init_db, session
from aicommon.internal import SyncSvc
from aicommon.llm import LLMError, SyncLLM
from aicommon.markdown import split_frontmatter
from aicommon.queue import celery_app
from aicommon.resources import get_skill
from aicommon.security import UserCtx

from .core import check_report, compute_table, map_doc, reduce_report
from .models import SummaryJob

log = logging.getLogger("summary.worker")
S = get_settings()


def _set(jid: str, **kw):
    with session() as s:
        j = s.get(SummaryJob, jid)
        for k, v in kw.items():
            setattr(j, k, v)


def run(jid: str):
    init_db()
    with session() as s:
        j = s.get(SummaryJob, jid)
        user, doc_ids, skill_name, params, title = UserCtx(**j.owner), list(j.doc_ids), j.skill, dict(j.params), j.title
    _set(jid, status="dang_chay", progress="Bắt đầu", error="")
    skill = get_skill(skill_name)
    if not skill:
        _set(jid, status="loi", error=f"Không tìm thấy kỹ năng {skill_name}")
        return
    ingest = SyncSvc(S.ingest_url)
    llm = SyncLLM()
    chat_json = lambda m, **kw: llm.chat_json(m, model=S.model_main, **kw)  # noqa: E731
    chat = lambda m, **kw: llm.chat(m, model=S.model_main, **kw)  # noqa: E731
    warnings: list[str] = []
    summaries, rows, sources = [], [], []
    try:
        for k, did in enumerate(doc_ids, 1):
            _set(jid, progress=f"Đang tóm tắt văn bản {k}/{len(doc_ids)}")
            md = ingest.call("GET", f"/documents/{did}/markdown", user)
            meta, body, _ = split_frontmatter(md)
            d = {"label": f"S{k}", "doc_id": did, "ten": meta.get("ten", did), "so_hieu": meta.get("so_hieu", ""),
                 "don_vi": meta.get("co_quan_ban_hanh") or meta.get("don_vi_quan_ly", ""), "body": body}
            sources.append({k2: v for k2, v in d.items() if k2 != "body"})
            sm, rr = map_doc(d, skill, chat_json, warnings)
            summaries.append(sm)
            rows += rr
        table, tbl_md = compute_table(rows)
        _set(jid, progress="Đang lập báo cáo tổng hợp")
        report = reduce_report(title, params, skill, summaries, tbl_md, chat)
        result = check_report(report, title, params, summaries, tbl_md, sources, warnings)
        _set(jid, status="xong", progress="Hoàn thành", result=result, table=table, sources=sources, warnings=warnings)
    except (LLMError, Exception) as e:  # noqa: B014
        log.exception("Lỗi tổng hợp %s", jid)
        _set(jid, status="loi", error=str(e)[:2000], warnings=warnings)


@celery_app.task(name="summary.run")
def run_task(jid: str):
    run(jid)
