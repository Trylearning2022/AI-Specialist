"""Kho văn bản đơn vị đã ban hành (nhóm "van_ban_di") – TIỀN LỆ cho công tác tham mưu.

Văn bản cũ của đơn vị (tờ trình, công văn tham gia ý kiến, báo cáo…) được nạp vào Luồng A với nhom=van_ban_di
(tools/import_archive.py, hoặc nút "Đưa vào kho văn bản đã ban hành" sau khi dự thảo được ký). Khi soạn văn bản
hoặc tham gia ý kiến, chương trình tìm văn bản đã ban hành cùng chủ đề để:

    1. giữ NHẤT QUÁN quan điểm: đơn vị đã từng tham gia ý kiến thế nào về nội dung tương tự;
    2. học CÁCH VIẾT của đơn vị: câu dẫn, cách nêu ý kiến, kiến nghị (văn phong đã được ký ban hành);
    3. KHÔNG dùng làm căn cứ pháp lý: tiền lệ chỉ là tham khảo, căn cứ phải là văn bản chuẩn (Luồng B).

Tìm kiếm dùng chung bộ tìm kiếm lai (vector + BM25 + xếp hạng lại) của search-svc, lọc trước theo quyền người dùng.
"""
import logging
import re

from aicommon.config import get_settings
from aicommon.internal import ServiceError, SyncSvc
from aicommon.security import UserCtx
from aicommon.text import truncate_tokens

log = logging.getLogger("agent.archive")
S = get_settings()
NHOM_DI = "van_ban_di"


def precedents(user: UserCtx, query: str, k: int = 3, loai: str | list[str] | None = None,
               max_tokens: int = 450) -> list[dict]:
    """Văn bản đã ban hành gần nhất với truy vấn (mỗi văn bản tối đa 1 đoạn). Lỗi tìm kiếm → danh sách rỗng."""
    if not query.strip():
        return []
    filters: dict = {"nhom": NHOM_DI}
    if loai:
        filters["loai"] = loai
    try:
        hits = SyncSvc(S.search_url).call("POST", "/search", user, json={
            "query": query[:600], "top_k": k, "filters": filters, "max_per_doc": 1})["results"]
    except ServiceError as e:
        log.warning("Không tra được kho văn bản đã ban hành: %s", e.detail)
        return []
    return [{"nguon": "VBD", "title": h.get("title"), "so_hieu": h.get("so_hieu"), "breadcrumb": h.get("breadcrumb"),
             "text": truncate_tokens(h.get("text", ""), max_tokens), "doc_id": h.get("doc_id"),
             "section_id": h.get("section_id"), "ngay_ban_hanh": (h.get("ngay_ban_hanh") or "")[:10]} for h in hits]


def style_block(items: list[dict], max_items: int = 2) -> str:
    """Khối "VĂN BẢN ĐƠN VỊ ĐÃ BAN HÀNH" đưa vào chỉ thị: tham khảo cách viết và quan điểm, không phải căn cứ."""
    if not items:
        return ""
    rows = [f"– {x.get('so_hieu') or x.get('title')} ({x.get('breadcrumb') or ''}):\n{x['text']}" for x in items[:max_items]]
    return ("VĂN BẢN ĐƠN VỊ ĐÃ BAN HÀNH (tham khảo cách viết và quan điểm đơn vị đã nêu; KHÔNG dùng làm căn cứ pháp lý, "
            "không chép số liệu, thời hạn của văn bản cũ):\n" + "\n\n".join(rows))


def clean_for_archive(md: str) -> str:
    """Bỏ dòng ghi chú "DỰ THẢO – do trợ lý AI…" và phụ lục làm việc trước khi đưa bản đã ký vào kho."""
    md = re.sub(r"(?m)^>\s*\*DỰ THẢO[^\n]*\n?", "", md)
    md = md.split("\n---\n## Phụ lục căn cứ")[0]
    md = md.split("\n---\n## Phụ lục nguồn")[0]
    return md.strip() + "\n"
