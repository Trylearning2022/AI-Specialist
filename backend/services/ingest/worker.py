"""Tác vụ nền của phân hệ nạp: chuyển đổi → làm sạch → metadata → chất lượng → trùng lặp."""
import logging
from pathlib import Path

from sqlalchemy import select

from aicommon.audit import emit
from aicommon.config import get_settings
from aicommon.db import init_db, session
from aicommon.markdown import split_frontmatter
from aicommon.queue import celery_app

from .cleaning import clean_markdown, minhash, minhash_from, quality
from .convert import convert
from .metadata import extract
from .models import CHO_DUYET, DANG_XU_LY, LOI, TU_CHOI, Document, Job

log = logging.getLogger("ingest.worker")
S = get_settings()
_inited = False


def _init():
    global _inited
    if not _inited:
        init_db()
        _inited = True


def process_job(job_id: str):
    _init()
    with session() as s:
        job = s.get(Job, job_id)
        if not job:
            return
        job.status, job.error = DANG_XU_LY, ""
        path, fname, user_meta = job.original_path, job.filename, dict(job.meta or {})
    try:
        data = Path(path).read_bytes() if path else b""
        if user_meta.pop("_markdown_input", False):
            with session() as s:
                kind, md, ocr, warns = "md", s.get(Job, job_id).markdown, False, []
        else:
            kind, md, ocr, warns = convert(data, fname)
        fm, md, _ = split_frontmatter(md)  # frontmatter có sẵn (tệp .md chuẩn) được giữ làm metadata
        md, w2, stats = clean_markdown(md)
        warns += w2
        meta = extract(md)
        meta.update({k: v for k, v in fm.items() if v not in (None, "", [])})
        meta.update({k: v for k, v in user_meta.items() if v not in (None, "", [])})  # người nạp quyết định độ mật, đơn vị
        meta = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in meta.items()}
        meta["do_mat"] = int(meta.get("do_mat", 0) or 0)
        q = quality(md, ocr, warns)
        q["thong_ke"] = stats
        # phát hiện gần trùng với tài liệu đã có
        mh = minhash(md)
        dups = []
        with session() as s:
            for d in s.scalars(select(Document).where(Document.minhash.is_not(None))):
                sim = mh.jaccard(minhash_from(d.minhash))
                if sim >= 0.8:
                    dups.append({"doc_id": d.doc_id, "title": d.title, "tuong_dong": round(sim, 3)})
        if dups:
            warns.append(f"Phát hiện {len(dups)} tài liệu gần trùng – xem xét liên kết phiên bản thay vì nạp mới.")
        with session() as s:
            job = s.get(Job, job_id)
            job.kind, job.markdown, job.meta, job.quality = kind, md, meta, q
            job.warnings, job.duplicates = warns, sorted(dups, key=lambda x: -x["tuong_dong"])
            if meta["do_mat"] > S.system_max_clearance:
                job.status = TU_CHOI
                job.reject_reason = "Tài liệu có độ mật vượt cấp độ hệ thống được phép xử lý."
            else:
                job.status = CHO_DUYET
        emit("system", "ingest.processed", job_id, {"kind": kind, "diem": q["diem"], "canh_bao": len(warns)})
    except Exception as e:
        log.exception("Lỗi xử lý tác vụ %s", job_id)
        with session() as s:
            job = s.get(Job, job_id)
            job.status, job.error = LOI, str(e)[:2000]


@celery_app.task(name="ingest.process", bind=True, max_retries=2, default_retry_delay=60)
def process(self, job_id: str):
    process_job(job_id)
