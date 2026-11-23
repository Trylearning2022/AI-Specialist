"""Hỏi lại để làm rõ câu hỏi (clarification) – trước khi tốn thời gian tìm kiếm, sinh câu trả lời trên CPU.

Thuật toán heuristic (không gọi mô hình, chạy trong vài mili giây):

  1. Câu hỏi quá ngắn, chung chung ("bị lỗi rồi", "hướng dẫn tôi")    → hỏi lại nhóm nội dung cần hỗ trợ
  2. Sự cố kỹ thuật chưa nêu thiết bị/hệ thống                          → hỏi thiết bị: USB Token, chứng thư số…
  3. Đã nêu thiết bị nhưng triệu chứng mơ hồ ("không dùng được")       → hỏi triệu chứng điển hình của thiết bị đó
  4. Kết quả tìm kiếm phân tán: điểm cao nhất thấp, ≥ 3 tài liệu khác nhau
     có điểm sát nhau (CLARIFY_MAX_SCORE, CLARIFY_SPREAD)              → hỏi người dùng muốn hỏi về tài liệu nào
  5. (Tùy chọn, CLARIFY_LLM=true) mô hình nhỏ đánh giá câu hỏi mơ hồ

Danh mục thiết bị, triệu chứng dưới đây theo nghiệp vụ bảo mật thông tin, cơ yếu, chứng thực số;
[TINH CHỈNH] bổ sung theo thực tế đơn vị. Mỗi chuỗi câu hỏi chỉ hỏi lại tối đa 01 lần (không lặp).
"""
import re

from aicommon.config import get_settings
from aicommon.text import content_tokens, nfc, unaccent

S = get_settings()

# [TINH CHỈNH] Từ chung chung không mang nội dung tìm kiếm (không dấu)
_GENERIC = set("""huong dan giup toi minh xin hoi cho biet ve van de loi bi khong duoc nhu the nao sao the
can ho tro xu ly cach lam gi nay kia do dung su co hong roi oi a nhe voi muon""".split())

# [TINH CHỈNH] Thiết bị/hệ thống thường gặp và triệu chứng điển hình
OBJECTS = [
    {"id": "token", "label": "USB Token (thiết bị lưu khóa bí mật)",
     "kw": ["usb token", "token", "thiet bi luu khoa", "khoa bi mat", "etoken", "bit4id"],
     "symptoms": ["Máy tính không nhận thiết bị USB Token", "Báo sai mã PIN hoặc thiết bị bị khóa",
                  "Không ký được văn bản bằng thiết bị", "Cần cấp mới, thay thế hoặc thu hồi thiết bị"]},
    {"id": "cts", "label": "Chứng thư số, chữ ký số",
     "kw": ["chung thu", "chu ky so", "ky so", "cts", "cks", "certificate", "ocsp", "crl", "tsa", "dau thoi gian"],
     "symptoms": ["Chứng thư số hết hạn hoặc sắp hết hạn", "Báo lỗi chứng thư không hợp lệ, bị thu hồi khi ký",
                  "Kiểm tra chữ ký số trên văn bản báo lỗi", "Đề nghị cấp mới, gia hạn, thu hồi chứng thư số"]},
    {"id": "phan_mem", "label": "Phần mềm ký số, middleware",
     "kw": ["middleware", "phan mem ky", "plugin", "trinh ky", "cong cu ky", "driver"],
     "symptoms": ["Cài đặt phần mềm ký số, middleware", "Phần mềm không nhận chứng thư trong thiết bị",
                  "Lỗi khi ký trên trình duyệt hoặc phần mềm văn phòng"]},
    {"id": "may", "label": "Máy tính, máy in, thiết bị ngoại vi",
     "kw": ["may tinh", "may in", "may tram", "may scan", "may quet", "man hinh", "ban phim", "chuot"],
     "symptoms": ["Máy in không in được", "Máy tính chậm, treo, không khởi động", "Thiết bị ngoại vi không nhận"]},
    {"id": "mang", "label": "Mạng nội bộ, kết nối",
     "kw": ["mang", "ket noi", "vpn", "lan", "wifi", "ip", "duong truyen"],
     "symptoms": ["Máy trạm mất kết nối mạng nội bộ", "Không truy cập được hệ thống nghiệp vụ", "Kết nối chậm, chập chờn"]},
    {"id": "tai_khoan", "label": "Tài khoản, đăng nhập hệ thống",
     "kw": ["dang nhap", "tai khoan", "mat khau", "xac thuc", "phan quyen"],
     "symptoms": ["Quên mật khẩu hoặc tài khoản bị khóa", "Không đăng nhập được hệ thống", "Cần cấp quyền truy cập"]},
]
_SPECIFIC = re.compile(r"[“\"'][^“\"']{4,}[”\"']|\b(0x[0-9a-f]+|lỗi\s+\d{2,}|error|code|mã\s+lỗi)\b|\d{3,}", re.I)
_VAGUE = re.compile(r"\b(bị\s+lỗi|lỗi\s+rồi|không\s+dùng\s+được|không\s+được|có\s+vấn\s+đề|trục\s+trặc|hỏng\s+rồi|"
                    r"không\s+hoạt\s+động)\b", re.I)


def meaningful_tokens(q: str) -> list[str]:
    return [t for t in content_tokens(q) if t not in _GENERIC]


def detect_object(q: str) -> dict | None:
    hay = " " + unaccent(nfc(q)).lower() + " "
    best = None
    for o in OBJECTS:
        hits = sum(1 for k in o["kw"] if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", hay))
        if hits and (best is None or hits > best[0]):
            best = (hits, o)
    return best[1] if best else None


def _opt(label: str, value: str | None = None) -> dict:
    return {"label": label, "value": value or label}


def before_search(question: str, route: str, history: list[dict]) -> dict | None:
    """Quy tắc 1–3. Trả {question, options, reason} hoặc None (đủ rõ)."""
    if not S.clarify_enabled or route not in ("tra_cuu", "ho_tro"):
        return None
    q = question.strip()
    mt = meaningful_tokens(q)
    if history and len(mt) >= 1:
        return None  # câu nối tiếp hội thoại: ngữ cảnh đã có ở lượt trước
    obj = detect_object(q)
    if len(mt) < S.clarify_min_tokens and not obj:
        if route == "ho_tro" or _VAGUE.search(q):
            return {"reason": "thieu_doi_tuong", "question": "Đồng chí đang gặp sự cố với thiết bị, hệ thống nào?",
                    "options": [_opt(o["label"]) for o in OBJECTS]}
        return {"reason": "qua_ngan", "question": "Đồng chí cần tra cứu nội dung gì? Đề nghị nêu cụ thể hơn, ví dụ:",
                "options": [_opt("Quy định, văn bản chuẩn (trích nguyên văn điều, khoản)", "về quy định, văn bản chuẩn"),
                            _opt("Thông tin trong tài liệu, báo cáo nội bộ", "về thông tin trong tài liệu nội bộ"),
                            _opt("Xử lý sự cố kỹ thuật", "về xử lý sự cố kỹ thuật")]}
    if route == "ho_tro":
        if not obj:
            return {"reason": "thieu_doi_tuong", "question": "Sự cố xảy ra với thiết bị, hệ thống nào?",
                    "options": [_opt(o["label"]) for o in OBJECTS]}
        if _VAGUE.search(q) and not _SPECIFIC.search(q) and len(mt) < 5:
            return {"reason": "thieu_trieu_chung", "question": f"{obj['label']}: biểu hiện cụ thể của sự cố là gì?",
                    "options": [_opt(s) for s in obj["symptoms"]]}
    return None


def scattered(hits: list[dict]) -> dict | None:
    """Quy tắc 4 (sau tìm kiếm): kết quả phân tán, không có tài liệu nổi trội → hỏi chọn chủ đề."""
    if not S.clarify_enabled or len(hits) < 3:
        return None
    sc = [h.get("rerank_score") for h in hits]
    if any(x is None for x in sc[:3]):
        return None  # không có reranker: không đủ căn cứ đánh giá
    top = sc[0]
    if top >= S.clarify_max_score:
        return None
    docs, opts = [], []
    for h in hits:
        if h["doc_id"] in docs or h["rerank_score"] < top - S.clarify_spread:
            continue
        docs.append(h["doc_id"])
        opts.append(_opt(f"{h.get('title')}" + (f" › {h['breadcrumb'].split(' › ')[-1]}" if h.get("breadcrumb") else ""),
                         f"theo tài liệu “{h.get('title')}”"))
    if len(docs) < 3:
        return None
    return {"reason": "phan_tan", "question": "Câu hỏi có thể liên quan tới nhiều tài liệu khác nhau. "
                                              "Đồng chí muốn hỏi theo tài liệu nào?",
            "options": opts[:4] + [_opt("Không thuộc các tài liệu trên – tìm trên toàn bộ", "")]}


def merge(original: str, answer: str) -> str:
    """Ghép câu hỏi gốc với câu trả lời làm rõ thành câu hỏi đầy đủ để tìm kiếm."""
    a = answer.strip().rstrip(".")
    if not a:
        return original
    return f"{original.rstrip(' ?.')} – {a}"
