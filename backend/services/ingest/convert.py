"""Chuyển đổi tài liệu sang Markdown.

- PDF, ảnh scan: docling-serve (mã nguồn mở của IBM, chạy dạng dịch vụ riêng) – phân tích bố cục, bảng, OCR.
- DOCX, XLSX, PPTX, HTML: MarkItDown (Microsoft, MIT) chạy trong tiến trình.
- Dự phòng khi docling-serve không khả dụng: MarkItDown (pdfminer) cho PDF có lớp văn bản.
"""
import io
import logging
import zipfile
from pathlib import Path

import httpx

from aicommon.config import get_settings

log = logging.getLogger("ingest.convert")
S = get_settings()

KINDS = {"pdf", "docx", "xlsx", "pptx", "html", "image", "md", "txt", "csv"}


def detect_kind(data: bytes, filename: str) -> str:
    head = data[:16]
    ext = Path(filename).suffix.lower().lstrip(".")
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        return "unknown"
    if head[:8] == b"\x89PNG\r\n\x1a\n" or head[:3] == b"\xff\xd8\xff" or head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image"
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole"  # .doc/.xls cũ – cần chuyển sang định dạng mới
    try:
        text = data[:4096].decode("utf-8")
    except UnicodeDecodeError:
        try:
            data[:4096].decode("cp1258")
            text = ""
        except UnicodeDecodeError:
            return "unknown"
    low = text.lower()
    if "<html" in low or "<!doctype html" in low:
        return "html"
    if ext in ("md", "markdown"):
        return "md"
    if ext == "csv":
        return "csv"
    return "txt"


def _docling(data: bytes, filename: str, ocr: bool) -> str:
    headers = {"X-Api-Key": S.docling_api_key} if S.docling_api_key else {}
    form = [("to_formats", "md"), ("do_ocr", str(ocr).lower()), ("force_ocr", "false"),
            ("ocr_engine", S.docling_ocr_engine), ("image_export_mode", "placeholder"),
            ("table_mode", "accurate"), ("abort_on_error", "false")]
    form += [("ocr_lang", lang.strip()) for lang in S.docling_ocr_lang.split(",") if lang.strip()]
    r = httpx.post(f"{S.docling_url.rstrip('/')}/v1/convert/file", headers=headers, data=form,
                   files={"files": (filename, data)}, timeout=S.docling_timeout)
    r.raise_for_status()
    body = r.json()
    doc = body.get("document") or {}
    md = doc.get("md_content") or ""
    if not md and body.get("errors"):
        raise RuntimeError(f"docling-serve: {body['errors']}")
    return md


def _markitdown(data: bytes, filename: str) -> str:
    from markitdown import MarkItDown
    res = MarkItDown(enable_plugins=False).convert_stream(io.BytesIO(data), file_extension=Path(filename).suffix)
    return res.text_content or ""


def convert(data: bytes, filename: str) -> tuple[str, str, bool, list[str]]:
    """Trả (kind, markdown, có dùng OCR, cảnh báo)."""
    kind = detect_kind(data, filename)
    warns: list[str] = []
    if kind == "ole":
        raise ValueError("Định dạng Office cũ (.doc/.xls) – đề nghị lưu lại thành .docx/.xlsx trước khi nạp")
    if kind == "unknown":
        raise ValueError("Không nhận dạng được định dạng tệp")
    if kind in ("md", "txt", "csv"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            from aicommon.text import detect_legacy
            latin = data.decode("latin-1")
            if detect_legacy(latin) == "tcvn3":  # tệp văn bản 8-bit bảng mã TCVN3 (ABC)
                text = latin
            else:
                text = data.decode("cp1258", errors="replace")
                warns.append("Tệp không phải UTF-8, đã đọc theo bảng mã Windows-1258.")
        if kind == "csv":
            return kind, _markitdown(data, filename), False, warns
        return kind, text, False, warns
    if kind in ("pdf", "image"):
        why = "chưa cấu hình DOCLING_URL"
        if S.docling_url:
            try:
                return kind, _docling(data, filename, ocr=True), True, warns
            except Exception as e:
                log.warning("docling-serve lỗi (%s), dùng phương án dự phòng", e)
                why = f"docling-serve lỗi: {type(e).__name__}: {str(e)[:160]}"
                warns.append(f"docling-serve không khả dụng ({type(e).__name__}); dùng trích xuất văn bản đơn giản.")
        if kind == "image":
            raise ValueError(f"Ảnh scan cần dịch vụ OCR (docling-serve) đang hoạt động ({why})")
        md = _markitdown(data, filename)
        if len(md.strip()) < 50:
            raise ValueError(f"PDF không có lớp văn bản, cần OCR – {why}")
        return kind, md, False, warns
    if kind in ("docx", "xlsx", "pptx", "html"):
        return kind, _markitdown(data, filename), False, warns
    raise ValueError(f"Chưa hỗ trợ định dạng {kind}")
