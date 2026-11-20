"""Xử lý văn bản tiếng Việt: chuẩn hóa Unicode, bỏ dấu, tách token, chuyển mã TCVN3.

Tiếng Việt được tách theo ÂM TIẾT (khoảng trắng), không dùng bộ tách từ: đơn giản, không phụ thuộc
mô hình ngoài, đủ dùng cho BM25 khi kết hợp cặp âm tiết (bigram) – xem services/search/app.py.
"""
import re
import unicodedata

_VN_RANGE = re.compile(r"[Ạ-ỹơưđăâêôƠƯĐĂÂÊÔ]")
_WORD = re.compile(r"[0-9A-Za-zÀ-ỹđĐ]+", re.U)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def unaccent(text: str) -> str:
    t = unicodedata.normalize("NFD", text or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.replace("đ", "d").replace("Đ", "D")


def tokens(text: str, accent: bool = True) -> list[str]:
    """Danh sách âm tiết viết thường (giữ dấu, hoặc bỏ dấu khi accent=False)."""
    t = nfc(text).lower()
    if not accent:
        t = unaccent(t)
    return _WORD.findall(t)


# Hư từ, từ nối phổ biến – bỏ qua khi đo độ phủ nội dung giữa câu trả lời và nguồn (Verifier).
# Dạng không dấu để so khớp được cả văn bản gõ thiếu dấu. [TINH CHỈNH] bổ sung theo thực tế.
STOPWORDS = set("""
va la cua cac nhung mot nay thi duoc cho voi trong ngoai tren duoi khi neu nen se nhu theo ve hoac hay
tung moi rang boi sau truoc nao gi ra vao len xuong ta phai nham nhieu it rat hon deu lai gom thuoc
""".split())


def content_tokens(text: str, accent: bool = False) -> list[str]:
    """Âm tiết mang nội dung (bỏ hư từ, bỏ chuỗi 1 ký tự) – dùng đo mức bám nguồn.

    accent=True giữ dấu (phân biệt "cố"/"có", "nhân"/"nhận") – chính xác hơn khi cả hai phía đều có dấu."""
    return [t for t in tokens(text, accent=accent) if len(t) > 1 and unaccent(t) not in STOPWORDS]


def estimate_tokens(text: str) -> int:
    """Ước lượng số token (tiếng Việt ~ 1 token / 3 ký tự với tokenizer đa ngôn ngữ)."""
    return max(1, len(text or "") // 3)


def truncate_tokens(text: str, budget: int) -> str:
    limit = budget * 3
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


# ---------- Số liệu (phục vụ Verifier) ----------
_NUM = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?:%|)(?![\w])")


def numbers(text: str) -> set[str]:
    """Tập số xuất hiện trong văn bản, đã chuẩn hóa (bỏ dấu phân cách nghìn, số 0 đầu)."""
    out = set()
    for m in _NUM.findall(nfc(text)):
        raw = m.rstrip("%")
        for cand in {raw.replace(".", "").replace(",", ""), raw.replace(".", "").replace(",", "."),
                     raw.replace(",", "")}:
            try:
                v = float(cand)
                out.add(str(int(v)) if v == int(v) else str(v))
            except ValueError:
                pass
    return out


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", nfc(text)).strip()


# ---------- Bảng mã cũ ----------
TCVN3 = {
    "¸": "á", "µ": "à", "¶": "ả", "·": "ã", "¹": "ạ",
    "¨": "ă", "¾": "ắ", "»": "ằ", "¼": "ẳ", "½": "ẵ", "Æ": "ặ",
    "©": "â", "Ê": "ấ", "Ç": "ầ", "È": "ẩ", "É": "ẫ", "Ë": "ậ",
    "®": "đ",
    "Ð": "é", "Ì": "è", "Î": "ẻ", "Ï": "ẽ", "Ñ": "ẹ",
    "ª": "ê", "Õ": "ế", "Ò": "ề", "Ó": "ể", "Ô": "ễ", "Ö": "ệ",
    "Ý": "í", "×": "ì", "Ø": "ỉ", "Ü": "ĩ", "Þ": "ị",
    "ã": "ó", "ß": "ò", "á": "ỏ", "â": "õ", "ä": "ọ",
    "«": "ô", "è": "ố", "å": "ồ", "æ": "ổ", "ç": "ỗ", "é": "ộ",
    "¬": "ơ", "í": "ớ", "ê": "ờ", "ë": "ở", "ì": "ỡ", "î": "ợ",
    "ó": "ú", "ï": "ù", "ñ": "ủ", "ò": "ũ", "ô": "ụ",
    "\xad": "ư", "ø": "ứ", "õ": "ừ", "ö": "ử", "÷": "ữ", "ù": "ự",
    "ý": "ý", "ú": "ỳ", "û": "ỷ", "ü": "ỹ", "þ": "ỵ",
    "¡": "Ă", "¢": "Â", "§": "Đ", "£": "Ê", "¤": "Ô", "¥": "Ơ", "¦": "Ư",
}
_TCVN3_MARK = set("µ¸¶·¹¨©®ª«¬\xadÆÊÇÕÒÖ×ÝØÜÞß¾»¼½")
_VNI_SEQ = re.compile(r"[aeiouyAEIOUY][øùûõïâêôö]|[oO]ö|ñ")


def detect_legacy(text: str) -> str | None:
    """Trả 'tcvn3' | 'vni' | None."""
    letters = sum(c.isalpha() for c in text) or 1
    vn = len(_VN_RANGE.findall(text))
    if vn / letters > 0.01:
        return None
    marks = sum(1 for c in text if c in _TCVN3_MARK)
    if marks / letters > 0.02:
        return "tcvn3"
    if len(_VNI_SEQ.findall(text)) / letters > 0.03:
        return "vni"
    return None


def tcvn3_to_unicode(text: str) -> str:
    return "".join(TCVN3.get(c, c) for c in text)


def vietnamese_ratio(text: str) -> float:
    """Tỷ lệ ký tự hợp lệ (chữ, số, dấu câu thông dụng) – dùng chấm điểm chất lượng."""
    if not text:
        return 0.0
    ok = sum(1 for c in text if c.isalnum() or c.isspace() or c in ".,;:!?()[]{}-–—_/\\\"'“”‘’%&*+=<>#|@`~^$")
    return ok / len(text)
