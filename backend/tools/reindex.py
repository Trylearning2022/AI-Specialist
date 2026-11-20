"""Lập chỉ mục lại toàn bộ Luồng A từ sổ đăng ký tài liệu (dùng khi đổi mô hình embedding).

    docker compose --profile tools run --rm tools python -m tools.reindex
"""
from pathlib import Path

from sqlalchemy import select

from aicommon.config import get_settings
from aicommon.db import session
from aicommon.internal import SyncSvc
from aicommon.markdown import split_frontmatter
from aicommon.security import SYSTEM_USER
from services.ingest.models import Document

S = get_settings()


def main():
    S.service_name = "tools"  # danh tính dịch vụ khi gọi search/index
    search = SyncSvc(S.search_url)
    with session() as s:
        docs = list(s.scalars(select(Document)))
    for d in docs:
        md = Path(d.path).read_text(encoding="utf-8")
        meta, _, _ = split_frontmatter(md)
        meta = {**meta, "do_mat": d.do_mat, "don_vi": d.don_vi, "loai": d.loai, "trang_thai": d.trang_thai,
                "so_hieu": d.so_hieu, "ngay_ban_hanh": d.ngay_ban_hanh, "phien_ban": d.version}
        r = search.call("POST", "/index", SYSTEM_USER, json={"doc_id": d.doc_id, "markdown": md, "title": d.title,
                                                             "meta": meta, "nguon": d.track})
        print(f"[OK] {d.doc_id}: {r['chunks']} đoạn")
    print(f"Đã lập chỉ mục lại {len(docs)} tài liệu.")


if __name__ == "__main__":
    main()
