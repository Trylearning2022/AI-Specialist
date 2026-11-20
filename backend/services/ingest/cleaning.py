"""Làm sạch, chuẩn hóa Markdown và đánh giá chất lượng dữ liệu."""
import re
from collections import Counter

from datasketch import MinHash

from aicommon.markdown import HEADING, normalize_vn_structure
from aicommon.text import detect_legacy, nfc, tcvn3_to_unicode, tokens, vietnamese_ratio

_PAGE = re.compile(r"^\s*(?:[-–—]\s*)?(?:trang\s+)?\d{1,4}(?:\s*/\s*\d{1,4})?(?:\s*[-–—])?\s*$", re.I)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff]")
_IMG = re.compile(r"^\s*<!--\s*image\s*-->\s*$", re.I)


def clean_markdown(md: str) -> tuple[str, list[str], dict]:
    """Trả (markdown đã làm sạch, cảnh báo, thống kê)."""
    warnings: list[str] = []
    stats: dict = {}
    legacy = detect_legacy(md)
    if legacy == "tcvn3":
        md = tcvn3_to_unicode(md)
        warnings.append("Phát hiện bảng mã TCVN3 (ABC), đã chuyển sang Unicode – cần kiểm tra chữ hoa có dấu.")
        stats["bang_ma"] = "tcvn3"
    elif legacy == "vni":
        warnings.append("Phát hiện văn bản bảng mã VNI – chưa tự chuyển đổi, cần chuyển mã thủ công trước khi duyệt.")
        stats["bang_ma"] = "vni"
    md = nfc(md).replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    md = _CTRL.sub("", md)
    lines = [ln.rstrip() for ln in md.split("\n")]

    # loại dòng số trang, dòng lặp (header/footer), ảnh placeholder
    short = Counter(ln.strip() for ln in lines if 0 < len(ln.strip()) <= 80 and not ln.lstrip().startswith(("|", "#", "-", "*")))
    repeated = {k for k, v in short.items()
                if v >= 4 and len(k) < 60 and not re.match(r"^(\d+[.)]|[a-zđ]\)|Điều|Khoản|Chương|Mục)\s", k)}
    removed = 0
    out = []
    for ln in lines:
        s = ln.strip()
        if _PAGE.match(s) or _IMG.match(s) or s in repeated:
            removed += 1
            continue
        out.append(ln)
    if removed:
        warnings.append(f"Đã loại {removed} dòng số trang, đầu/chân trang lặp lại hoặc ảnh không có nội dung.")
    md = "\n".join(out)
    md = re.sub(r"[ \t]{2,}", " ", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    before = sum(1 for ln in md.split("\n") if HEADING.match(ln))
    md = normalize_vn_structure(md)
    after = sum(1 for ln in md.split("\n") if HEADING.match(ln))
    stats.update(dong_bi_loai=removed, so_tieu_de=after, tieu_de_chuan_hoa=max(0, after - before))
    return md.strip() + "\n", warnings, stats


def quality(md: str, ocr: bool, warnings: list[str]) -> dict:
    text = re.sub(r"[#|*>`\-]", " ", md)
    ratio = vietnamese_ratio(text)
    n_tok = len(tokens(text))
    tables = len(re.findall(r"(?m)^\|.*\|\s*$\n^\|[\s:\-|]+\|\s*$", md))
    single = sum(1 for t in tokens(text) if len(t) == 1 and not t.isdigit())
    garbage = single / max(1, n_tok)
    score = 100.0
    score -= max(0, (0.97 - ratio) * 400)
    score -= max(0, (garbage - 0.08) * 300)
    if n_tok < 30:
        score -= 40
    score -= 5 * len(warnings)
    if ocr:
        score -= 10
    score = round(max(0.0, min(100.0, score)), 1)
    return {"diem": score, "so_tu": n_tok, "ty_le_ky_tu_hop_le": round(ratio, 4), "ty_le_nhieu": round(garbage, 4),
            "so_bang": tables, "ocr": ocr, "can_duyet_bat_buoc": score < 70 or ocr or bool(warnings)}


def minhash(md: str) -> MinHash:
    t = tokens(md)
    m = MinHash(num_perm=128, scheme="affine32")
    for i in range(max(1, len(t) - 4)):
        m.update(" ".join(t[i:i + 5]).encode())
    return m


def minhash_bytes(m: MinHash) -> bytes:
    return m.hashvalues.astype("uint64").tobytes()


def minhash_from(b: bytes) -> MinHash:
    import numpy as np
    return MinHash(num_perm=128, hashvalues=np.frombuffer(b, dtype="uint64"), scheme="affine32")
