"""Trích xuất thông tin mô tả văn bản: quy tắc trước, mô hình nhỏ bổ sung phần còn thiếu."""
import logging
import re

from aicommon.config import get_settings
from aicommon.llm import LLMError, SyncLLM
from aicommon.markdown import HEADING
from aicommon.resources import prompt
from aicommon.text import nfc

log = logging.getLogger("ingest.meta")
S = get_settings()
LOAI = ["quyet_dinh", "thong_tu", "nghi_dinh", "quy_dinh", "huong_dan", "ke_hoach", "bao_cao", "cong_van",
        "to_trinh", "bien_ban", "su_co", "tai_lieu_ky_thuat", "khac"]
_LOAI_KW = [("QUYẾT ĐỊNH", "quyet_dinh"), ("THÔNG TƯ", "thong_tu"), ("NGHỊ ĐỊNH", "nghi_dinh"),
            ("QUY ĐỊNH", "quy_dinh"), ("HƯỚNG DẪN", "huong_dan"), ("KẾ HOẠCH", "ke_hoach"), ("BÁO CÁO", "bao_cao"),
            ("TỜ TRÌNH", "to_trinh"), ("BIÊN BẢN", "bien_ban"), ("CÔNG VĂN", "cong_van"),
            ("LUẬT", "luat"), ("PHÁP LỆNH", "phap_lenh")]  # đặt cuối: "luật" hay xuất hiện trong phần căn cứ
_SO = re.compile(r"Số\s*[:.]?\s*([0-9]{1,5}/(?:[0-9]{4}/)?[A-ZĐ][A-ZĐ0-9\-]*)")
_SO2 = re.compile(r"\b([0-9]{1,5}/(?:[0-9]{4}/)?(?:QĐ|TT|NĐ|HD|KH|BC|CV|TTr|BB|QyĐ|QH|PL)[A-ZĐ0-9\-]*)\b")
_NGAY = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.I)


def rule_based(md: str) -> dict:
    head = nfc(md[:3000])
    out: dict = {}
    m = _SO.search(head) or _SO2.search(head)
    if m:
        out["so_hieu"] = m.group(1)
    m = _NGAY.search(head)
    if m:
        out["ngay_ban_hanh"] = f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    lines = [ln.strip("#* ").strip() for ln in head.split("\n") if ln.strip()]
    for i, ln in enumerate(lines):
        for kw, loai in _LOAI_KW:
            if ln.upper() == ln and ln.startswith(kw):
                out["loai"] = loai
                rest = ln[len(kw):].strip(" :-–")
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                title = rest or nxt
                if title and len(title) < 300:
                    out["ten"] = (kw.capitalize() + " " + title[0].lower() + title[1:]) if title.lower().startswith(("về", "ban hành", "v/v")) else title
                break
        if "loai" in out:
            break
    if "ten" not in out:
        for ln in md.split("\n"):
            h = HEADING.match(ln)
            if h:
                out["ten"] = h.group(2).strip()[:300]
                break
    return out


def extract(md: str, use_llm: bool = True) -> dict:
    meta = rule_based(md)
    if use_llm:
        try:
            r = SyncLLM().chat_json(
                [{"role": "system", "content": prompt("trich-xuat-metadata")},
                 {"role": "user", "content": md[:3500]}],
                schema={"type": "object", "properties": {
                    "ten": {"type": "string"}, "so_hieu": {"type": "string"},
                    "loai": {"type": "string", "enum": LOAI}, "co_quan_ban_hanh": {"type": "string"},
                    "ngay_ban_hanh": {"type": "string"}, "tom_tat": {"type": "string"}},
                    "required": ["ten", "loai", "tom_tat"]},
                model=S.model_small, max_tokens=400, task="metadata")
            for k, v in r.items():
                if v and k not in meta:  # quy tắc được ưu tiên hơn mô hình
                    if k == "ngay_ban_hanh" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
                        continue
                    if k == "so_hieu" and str(v) not in md:  # chống bịa số hiệu
                        continue
                    meta[k] = str(v)[:500]
        except LLMError as e:
            log.warning("Không trích xuất metadata bằng mô hình: %s", e)
    meta.setdefault("loai", "khac")
    meta.setdefault("ten", "Tài liệu chưa đặt tên")
    return meta
