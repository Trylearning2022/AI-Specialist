"""Sổ đăng ký tài liệu đã duyệt (ing_document) và bản Markdown lưu trên đĩa – dùng chung cho API và tiến trình nền."""
from pathlib import Path

from aicommon.config import get_settings

from .cleaning import minhash, minhash_bytes
from .models import Document, Job

S = get_settings()
DOCS = Path(S.data_dir) / "docs"


def upsert_document(s, doc_id: str, track: str, meta: dict, j: Job, md: str, commit: str = ""):
    path = DOCS / f"{doc_id}.md"
    path.write_text(md, encoding="utf-8")
    d = s.get(Document, doc_id)
    if d is None:
        d = Document(doc_id=doc_id, track=track, version=0)
        s.add(d)
    d.version += 1
    d.track, d.title, d.so_hieu = track, str(meta.get("ten", doc_id))[:500], str(meta.get("so_hieu", ""))
    d.loai, d.do_mat, d.don_vi = meta.get("loai", "khac"), int(meta.get("do_mat", 0) or 0), meta.get("don_vi") or ["chung"]
    d.ngay_ban_hanh, d.trang_thai = str(meta.get("ngay_ban_hanh", "") or "")[:10], meta.get("trang_thai", "con_hieu_luc")
    d.sha256, d.job_id, d.path, d.commit = j.sha256, j.id, str(path), commit
    d.minhash = minhash_bytes(minhash(md))
    return d
