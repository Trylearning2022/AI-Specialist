"""Đọc tài liệu đầu vào của tác vụ và các thuật toán xử lý văn bản KHÔNG dùng mô hình:
chia phần theo cấu trúc, xếp hạng đoạn theo từ khóa (BM25 rút gọn), trích thời hạn, nhiệm vụ, số liệu.

Các phép trích bằng chương trình bảo đảm: số liệu, ngày tháng, số hiệu trong báo cáo luôn có thật trong văn bản
(mô hình chỉ diễn đạt, phân loại; không tự tạo số liệu).
"""
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from aicommon.config import get_settings
from aicommon.internal import SyncSvc
from aicommon.markdown import chunk_markdown, split_frontmatter
from aicommon.security import UserCtx
from aicommon.text import content_tokens, estimate_tokens, nfc, unaccent

S = get_settings()
UPLOAD_DIR = Path(S.data_dir) / "agent-uploads"


@dataclass
class Doc:
    label: str                 # nhãn trích dẫn trong báo cáo: S1, S2… (tổng hợp) hoặc "VB" (phân tích)
    title: str
    markdown: str
    meta: dict = field(default_factory=dict)
    source: str = ""           # upload:<id> | doc:<doc_id>
    warnings: list[str] = field(default_factory=list)


def load_upload(upload_id: str, filename: str, path: str, label: str = "VB") -> Doc:
    """Chuyển tệp đính kèm sang Markdown (dùng lại bộ chuyển đổi của phân hệ nạp: MarkItDown, docling OCR)."""
    from services.ingest.cleaning import clean_markdown
    from services.ingest.convert import convert
    from services.ingest.metadata import rule_based

    data = Path(path).read_bytes()
    _, md, ocr, warns = convert(data, filename)
    md, cw, _ = clean_markdown(md)
    meta = rule_based(md)
    if ocr:
        warns.append("Tài liệu được nhận dạng ký tự (OCR): cần đối chiếu số liệu với bản gốc.")
    return Doc(label, meta.get("ten") or Path(filename).stem, md, meta, f"upload:{upload_id}", [*warns, *cw])


def load_registered(user: UserCtx, doc_id: str, label: str) -> Doc:
    """Tài liệu đã có trong kho (qua ingest-svc, kiểm tra quyền truy cập theo người dùng)."""
    md = SyncSvc(S.ingest_url).call("GET", f"/documents/{doc_id}/markdown", user)
    meta, body, _ = split_frontmatter(md)
    return Doc(label, meta.get("ten") or doc_id, body, meta, f"doc:{doc_id}")


def save_upload(data: bytes, filename: str) -> tuple[str, str]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(data).hexdigest()
    ext = (Path(filename).suffix or ".bin")[:10]
    p = UPLOAD_DIR / f"{h[:32]}{ext}"
    if not p.exists():
        p.write_bytes(data)
    return str(p), h


# ---------------------------------------------------------------- chia phần
def parts(doc: Doc, budget: int | None = None) -> list[dict]:
    """Chia tài liệu thành các PHẦN theo cấu trúc (chương, mục, điều), mỗi phần ≤ budget token.
    Trả [{no, breadcrumb, text}] – breadcrumb dùng làm vị trí trích dẫn ("Mục II › 2. Nhiệm vụ")."""
    budget = budget or S.agent_part_tokens
    chunks = chunk_markdown("vb", doc.markdown, doc.title, max_tokens=max(400, budget // 3), min_tokens=80)
    out: list[dict] = []
    for c in chunks:  # gộp các đoạn liền kề tới ngân sách, giữ breadcrumb của đoạn đầu
        if out and estimate_tokens(out[-1]["text"] + c["text"]) <= budget:
            out[-1]["text"] += "\n\n" + c["text"]
            out[-1]["breadcrumbs"].append(c["breadcrumb"])
            continue
        out.append({"text": c["text"], "breadcrumbs": [c["breadcrumb"]]})
    for i, p in enumerate(out):
        p["no"] = i + 1
        bc = list(dict.fromkeys(p.pop("breadcrumbs")))
        p["breadcrumb"] = bc[0] if len(bc) == 1 else f"{bc[0]} … {bc[-1].split(' › ')[-1]}"
    return out or [{"no": 1, "breadcrumb": doc.title, "text": doc.markdown}]


def passages(doc: Doc, size: int = 350) -> list[dict]:
    """Đoạn nhỏ (≈ size token) để xếp hạng theo tiêu chí."""
    return [{"breadcrumb": c["breadcrumb"], "text": c["text"]}
            for c in chunk_markdown("vb", doc.markdown, doc.title, max_tokens=size, min_tokens=60)]


# ---------------------------------------------------------------- xếp hạng đoạn (BM25 rút gọn)
def rank(query: str, items: list[dict], k: int = 3, key: str = "text") -> list[tuple[float, dict]]:
    """Xếp hạng đoạn theo truy vấn bằng BM25 trên âm tiết không dấu. Đủ tốt để tìm đoạn liên quan
    TRONG MỘT tài liệu (vài trăm đoạn) mà không cần vector – nhanh, không tốn mô hình."""
    q = [t for t in content_tokens(query) if len(t) > 1]
    if not q or not items:
        return []
    docs = [content_tokens(it[key] + " " + it.get("breadcrumb", "")) for it in items]
    n, avg = len(docs), (sum(len(d) for d in docs) / len(docs)) or 1
    df = Counter(t for d in docs for t in set(d))
    # thêm cặp âm tiết (bigram) của truy vấn: "chứng thư", "thu hồi" có nghĩa hơn từng âm tiết
    qb = list(zip(q, q[1:]))
    out = []
    for d, it in zip(docs, items):
        tf = Counter(d)
        bg = set(zip(d, d[1:]))
        s = 0.0
        for t in set(q):
            if tf[t]:
                idf = math.log(1 + (n - df[t] + .5) / (df[t] + .5))
                s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
        s += 0.8 * sum(1 for b in qb if b in bg)
        if s > 0:
            out.append((s, it))
    return sorted(out, key=lambda x: -x[0])[:k]


# ---------------------------------------------------------------- trích xuất bằng quy tắc
_DATE = re.compile(r"\b(?:ngày\s+)?(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b|ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
                   re.I)
_DEADLINE_CUE = re.compile(r"(trước\s+ngày|chậm\s+nhất|hạn\s+chót|thời\s+hạn|hoàn\s+thành\s+(?:trước|trong)|"
                           r"trong\s+(?:thời\s+hạn|vòng)|kể\s+từ\s+ngày|định\s+kỳ|hằng\s+(?:tháng|quý|năm)|hàng\s+(?:tháng|quý|năm))",
                           re.I)
_DURATION = re.compile(r"\b(\d{1,3})\s*(ngày(?:\s+làm\s+việc)?|tuần|tháng|năm|giờ)\b", re.I)
_ASSIGN = re.compile(r"(?:^|[\n.;:]\s*)(?:[-*+]\s*|\d+[.)]\s*|[a-zđ][.)]\s*)?((?:Phòng|Ban|Cục|Vụ|Trung tâm|Đơn vị|Bộ phận|Các\s+đơn\s+vị|"
                     r"Cơ\s+quan|Thủ\s+trưởng|Chỉ\s+huy|Tổ|Đội|Văn\s+phòng|Bộ\s+Tham\s+mưu|Cục\s+Cơ\s+yếu)[^.;:\n]{0,60}?)\s+"
                     r"(chủ\s+trì|phối\s+hợp|có\s+trách\s+nhiệm|chịu\s+trách\s+nhiệm|thực\s+hiện|tổ\s+chức|báo\s+cáo|tham\s+mưu|"
                     r"triển\s+khai|bảo\s+đảm|hướng\s+dẫn|kiểm\s+tra)", re.M)
_REF = re.compile(r"(?<![\w/])(\d{1,5}/(?:\d{4}/)?(?:QĐ|TT|NĐ|HD|KH|BC|CV|TTr|BB|QyĐ|CT|NQ|TB|QH|PL)[\w\-Đđ]*)")
_SENT = re.compile(r"(?<=[.;!?])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [s.strip(" -*+") for s in _SENT.split(text) if len(s.strip()) > 8]


def deadlines(doc: Doc, limit: int = 30) -> list[dict]:
    """Câu chứa mốc thời gian/thời hạn: [{cau, moc, vi_tri}]. Dấu hiệu: "trước ngày", "chậm nhất", "trong vòng N ngày"…"""
    out, seen = [], set()
    for p in passages(doc, 500):
        for s in sentences(p["text"]):
            if not _DEADLINE_CUE.search(s):
                continue
            moc = [m.group(0) for m in _DATE.finditer(s)] + [m.group(0) for m in _DURATION.finditer(s)]
            if not moc:
                continue
            key = unaccent(s.lower())[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append({"cau": s[:400], "moc": moc[:3], "vi_tri": p["breadcrumb"]})
            if len(out) >= limit:
                return out
    return out


def assignments(doc: Doc, limit: int = 30) -> list[dict]:
    """Nhiệm vụ được giao: [{chu_the, hanh_dong, cau, vi_tri}] – "Phòng Kỹ thuật chủ trì…", "Các đơn vị báo cáo…"."""
    out, seen = [], set()
    for p in passages(doc, 500):
        for s in sentences(p["text"]):
            m = _ASSIGN.search(s)
            if not m:
                continue
            key = unaccent(s.lower())[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append({"chu_the": m.group(1).strip(), "hanh_dong": m.group(2), "cau": s[:400], "vi_tri": p["breadcrumb"]})
            if len(out) >= limit:
                return out
    return out


def references(doc: Doc) -> list[str]:
    """Số hiệu văn bản được viện dẫn trong tài liệu (để đối chiếu kho văn bản chuẩn)."""
    own = doc.meta.get("so_hieu", "")
    return [r for r in dict.fromkeys(m.group(1) for m in _REF.finditer(doc.markdown)) if r != own][:30]


def doc_stats(doc: Doc) -> dict:
    return {"ky_tu": len(doc.markdown), "token": estimate_tokens(doc.markdown),
            "so_trang_uoc_tinh": max(1, round(len(doc.markdown) / 2800))}


def quote_ok(quote: str, text: str) -> bool:
    """Trích dẫn của mô hình có thật trong văn bản? So khớp không dấu, bỏ khoảng trắng thừa; cho phép
    trích một phần (≥ 70% số âm tiết liên tiếp xuất hiện theo thứ tự)."""
    q = unaccent(nfc(quote)).lower().split()
    if len(q) < 4:
        return False
    hay = " ".join(unaccent(nfc(text)).lower().split())
    if " ".join(q) in hay:
        return True
    n = max(4, int(len(q) * 0.7))
    return any(" ".join(q[i:i + n]) in hay for i in range(0, len(q) - n + 1))
