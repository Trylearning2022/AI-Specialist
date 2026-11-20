"""Verifier – kiểm chứng đầu ra bằng mã chương trình (không dùng LLM cho kiểm tra cứng).

Luồng A (verify_a) kiểm tra theo thứ tự:
  1. Chỉ số trích dẫn [n] phải tồn tại trong danh sách nguồn (loại chỉ số bịa).
  2. BÁM NGUỒN THEO TỪNG CÂU (ground_sentences): đo tỷ lệ âm tiết mang nội dung của câu có mặt trong nguồn.
       - Câu ghi [n] nhưng nội dung nằm ở nguồn khác → sửa chỉ số trích dẫn (lỗi "lệch trích dẫn").
       - Câu không ghi trích dẫn nhưng khớp rõ một nguồn → bổ sung trích dẫn.
       - Câu không khớp nguồn nào → đánh dấu "chưa tìm thấy trong nguồn", cảnh báo người dùng.
     Đây là phép đo từ vựng (heuristic): diễn đạt lại quá nhiều có thể bị đánh dấu nhầm; ngưỡng ở cấu hình
     VERIFY_SUPPORT_* (docs/tinh-chinh-truy-xuat.md).
  3. Câu trích nguyên văn trong ngoặc kép phải có trong nguồn.
  4. Mọi con số phải xuất hiện trong nguồn được trích (chống số liệu tự tính, tự bịa).
  5. Không có trích dẫn hợp lệ nào → thay bằng câu từ chối (VERIFY_STRICT_A).
Luồng B (verify_b): phần do mô hình viết không được chứa trích dẫn/số liệu ngoài nguyên văn.
"""
import re
from dataclasses import dataclass, field

from aicommon.config import get_settings
from aicommon.text import content_tokens, norm_ws, numbers, unaccent

CITE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
QUOTE = re.compile(r"[“\"]([^”\"]{8,})[”\"]")
REFUSAL = "Không tìm thấy căn cứ trong tài liệu được cung cấp."
UNSUPPORTED_MARK = " *(chưa tìm thấy trong nguồn)*"
MIN_TOKENS = 6   # [TINH CHỈNH] câu có ít âm tiết nội dung hơn ngưỡng này không bị đối chiếu (tránh báo nhầm)

# Từ ngữ "khung" của câu trả lời, không mang nội dung cần đối chiếu
_META = {"nguon", "tai", "lieu", "xem", "chi", "tiet", "noi", "dung", "neu", "tren", "sau", "day", "can", "cu",
         "duoc", "quy", "dinh", "cung", "cap", "cau", "hoi", "tra", "loi"}


@dataclass
class Report:
    ok: bool = True
    cited: set[int] = field(default_factory=set)
    invalid_citations: list[int] = field(default_factory=list)
    bad_quotes: list[str] = field(default_factory=list)
    bad_numbers: list[str] = field(default_factory=list)
    fixed_citations: list[str] = field(default_factory=list)   # "câu … : [1] → [3]"
    unsupported: list[str] = field(default_factory=list)       # câu không tìm thấy trong nguồn
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def dict(self):
        return {"ok": self.ok, "cited": sorted(self.cited), "invalid_citations": self.invalid_citations,
                "bad_quotes": self.bad_quotes, "bad_numbers": self.bad_numbers,
                "fixed_citations": self.fixed_citations, "unsupported": self.unsupported,
                "truncated": self.truncated, "warnings": self.warnings}


def is_refusal(text: str) -> bool:
    t = norm_ws(text).lower()
    return "không tìm thấy căn cứ" in t or "khong tim thay can cu" in t


def _cite_ids(text: str) -> list[int]:
    return [int(x) for g in CITE.findall(text) for x in re.split(r"\s*[,;]\s*", g)]


def check_citations(answer: str, n_sources: int) -> tuple[str, Report]:
    """Loại chỉ số trích dẫn không tồn tại; ghi nhận các nguồn được trích."""
    rep = Report()

    def fix(m: re.Match) -> str:
        keep = []
        for x in re.split(r"\s*[,;]\s*", m.group(1)):
            i = int(x)
            if 1 <= i <= n_sources:
                if i not in keep:
                    keep.append(i)
                rep.cited.add(i)
            else:
                rep.invalid_citations.append(i)
        return "[" + ", ".join(map(str, keep)) + "]" if keep else ""

    cleaned = CITE.sub(fix, answer)
    if rep.invalid_citations:
        rep.warnings.append(f"Đã loại {len(rep.invalid_citations)} trích dẫn không tồn tại.")
    return cleaned, rep


# Tách câu: sau . ! ? (không tách khi ngay sau là chỉ số trích dẫn, ví dụ "… xong. [2]")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?!\[)")


def _feats(text: str) -> tuple[set[str], set[str]]:
    """Đặc trưng để đo bám nguồn: tập âm tiết nội dung (giữ dấu) và tập cặp âm tiết liền kề."""
    t = [x for x in content_tokens(text, accent=True) if unaccent(x) not in _META]
    return set(t), {f"{a} {b}" for a, b in zip(t, t[1:])}


def _support(sent: tuple[set[str], set[str]], src: tuple[set[str], set[str]]) -> float:
    """Độ phủ = ½ (tỷ lệ âm tiết của câu có trong nguồn) + ½ (tỷ lệ cặp âm tiết có trong nguồn).

    Cặp âm tiết phân biệt mạnh hơn âm tiết đơn: câu bịa thường vẫn trùng vài âm tiết phổ biến ("hệ", "thống")
    nhưng hầu như không trùng cụm ("tàu ngầm"). Câu diễn đạt lại sát nguồn thường đạt ≥ 0,5; câu bịa < 0,25."""
    (u, b), (su, sb) = sent, src
    uni = len(u & su) / len(u) if u else 1.0
    bi = len(b & sb) / len(b) if b else uni
    return 0.5 * uni + 0.5 * bi


def ground_sentences(answer: str, sources: list[dict], rep: Report) -> str:
    """Đối chiếu từng câu với nguồn; sửa/bổ sung chỉ số trích dẫn; đánh dấu câu không có căn cứ."""
    s = get_settings()
    src_tok = [_feats(f"{x.get('breadcrumb', '')} {x.get('title', '')}\n{x['text']}") for x in sources]
    out_lines = []
    for line in answer.split("\n"):
        if not line.strip() or line.lstrip().startswith(("#", "|", "```")):
            out_lines.append(line)  # tiêu đề, bảng, mã: không đối chiếu từng câu
            continue
        sents = _SENT_SPLIT.split(line)
        new = []
        for sent in sents:
            toks = _feats(CITE.sub(" ", sent))
            if len(toks[0]) < MIN_TOKENS:  # câu quá ngắn/chung chung (nối ý, tiêu đề mục) – không đủ để đối chiếu
                new.append(sent)
                continue
            sup = [_support(toks, st) for st in src_tok]
            best_i = max(range(len(sup)), key=lambda i: sup[i])
            best = sup[best_i]
            cites = [i for i in _cite_ids(sent) if 1 <= i <= len(sources)]
            short = norm_ws(CITE.sub("", sent))[:90]
            if cites:
                cited_sup = max(sup[i - 1] for i in cites)
                if cited_sup < s.verify_support_low and best >= s.verify_support_fix and best - cited_sup >= 0.25:
                    sent = CITE.sub("", sent).rstrip()
                    sent = _attach(sent, best_i + 1)
                    rep.fixed_citations.append(f"“{short}”: {cites} → [{best_i + 1}]")
                elif best < s.verify_support_min:
                    rep.unsupported.append(short)
                    sent = _mark(sent)
            else:
                if best >= s.verify_support_fix:
                    sent = _attach(sent, best_i + 1)
                elif best < s.verify_support_min:
                    rep.unsupported.append(short)
                    sent = _mark(sent)
            new.append(sent)
        out_lines.append(" ".join(new))
    if rep.fixed_citations:
        rep.warnings.append(f"Đã điều chỉnh {len(rep.fixed_citations)} chỉ số trích dẫn cho khớp nguồn chứa nội dung.")
    if rep.unsupported:
        rep.warnings.append(f"Có {len(rep.unsupported)} câu chưa tìm thấy nội dung tương ứng trong nguồn – "
                            "cần đối chiếu trước khi sử dụng.")
    return "\n".join(out_lines)


def _attach(sent: str, n: int) -> str:
    """Gắn [n] vào cuối câu, trước dấu chấm câu cuối nếu có."""
    m = re.match(r"^(.*?)([.!?;:]?)\s*$", sent, re.S)
    return f"{m.group(1).rstrip()} [{n}]{m.group(2)}"


def _mark(sent: str) -> str:
    """Gắn nhãn ngay sau câu để người đọc thấy câu nào chưa đối chiếu được (hiển thị nghiêng trên giao diện)."""
    return sent.rstrip() + UNSUPPORTED_MARK


def check_quotes(text: str, sources: list[str]) -> list[str]:
    hay = norm_ws(" ".join(sources))
    return [q for q in QUOTE.findall(text) if norm_ws(q) not in hay]


# Số hiệu văn bản (03/HD-PKT, 15/QĐ-ĐVA, 12/2025/NĐ-CP): con số trong đó không phải số liệu
_DOC_CODE = re.compile(r"(?<![\w/])\d{1,5}/(?:\d{4}/)?[A-ZĐ][\wĐđ\-]*")


def check_numbers(text: str, allowed: str, ignore: set[str] | None = None) -> list[str]:
    """Số trong text không xuất hiện trong allowed (bỏ qua số trích dẫn [n], số mục 1., 2. và số hiệu văn bản).

    Số hiệu văn bản được loại khỏi cả hai phía: số "3" do mô hình tự tính không được coi là có căn cứ
    chỉ vì nguồn có "03/HD-PKT"."""
    t = CITE.sub(" ", text)
    t = re.sub(r"(?m)^\s*\d+\.\s", " ", t)
    t = _DOC_CODE.sub(" ", t)
    have = numbers(_DOC_CODE.sub(" ", allowed)) | (ignore or set())
    return sorted(n for n in numbers(t) if n not in have)


def verify_a(answer: str, sources: list[dict], strict: bool = True) -> tuple[str, Report]:
    """Luồng A: trích dẫn hợp lệ, bám nguồn theo câu, trích nguyên văn đúng, số liệu có trong nguồn được trích."""
    cleaned, rep = check_citations(answer, len(sources))
    if is_refusal(cleaned):
        return cleaned, rep
    if get_settings().verify_grounding and sources:
        cleaned = ground_sentences(cleaned, sources, rep)
        rep.cited = {i for i in _cite_ids(cleaned) if 1 <= i <= len(sources)}
    texts = [s["text"] for s in sources]
    rep.bad_quotes = check_quotes(cleaned, texts)
    if rep.bad_quotes:
        rep.warnings.append("Có đoạn trích dẫn nguyên văn không khớp nguồn – cần đối chiếu.")
    cited_text = " ".join(sources[i - 1]["text"] + " " + sources[i - 1].get("breadcrumb", "") for i in rep.cited)
    rep.bad_numbers = check_numbers(cleaned, cited_text or " ".join(texts))
    if rep.bad_numbers:
        rep.warnings.append("Có số liệu không tìm thấy trong nguồn được trích: " + ", ".join(rep.bad_numbers[:8]))
    if not rep.cited:
        rep.ok = False
        rep.warnings.append("Câu trả lời không có trích dẫn nguồn hợp lệ.")
        if strict:
            return REFUSAL, rep
    rep.ok = rep.ok and not rep.bad_quotes and not rep.bad_numbers and not rep.unsupported
    return cleaned, rep


def verify_b(cau_dan: str, dien_giai: str, verbatim: str) -> tuple[str, str, Report]:
    """Luồng B: phần do mô hình viết không được chứa trích dẫn/số liệu ngoài nguyên văn."""
    rep = Report()
    if check_numbers(cau_dan, verbatim) or check_quotes(cau_dan, [verbatim]):
        rep.warnings.append("Câu dẫn chứa nội dung không khớp nguyên văn – đã thay bằng câu dẫn mặc định.")
        cau_dan = "Nội dung được quy định như sau:"
    rep.bad_quotes = check_quotes(dien_giai, [verbatim])
    rep.bad_numbers = check_numbers(dien_giai, verbatim)
    if rep.bad_quotes or rep.bad_numbers:
        rep.ok = False
        rep.warnings.append("Phần diễn giải không khớp nguyên văn – đã loại bỏ, chỉ hiển thị nguyên văn.")
        dien_giai = ""
    return cau_dan, dien_giai, rep
