"""Context Builder – lắp ráp ngữ cảnh gửi mô hình theo ngân sách token.

Thứ tự trong cửa sổ ngữ cảnh:

    [system]  chính sách cố định → vai trò → kỹ năng → thuật ngữ → tóm tắt hội thoại
    [lịch sử] các lượt hỏi–đáp gần nhất (CTX_BUDGET_MEMORY)
    [user]    CÂU HỎI → NGUỒN [1..n] → NHẮC LẠI CÂU HỎI + yêu cầu trình bày

- Phần system đứng đầu, ít thay đổi → llama.cpp tái sử dụng KV cache tiền tố (--cache-reuse), giảm thời gian.
- Câu hỏi đặt TRƯỚC nguồn để mô hình đọc nguồn "có chủ đích", và NHẮC LẠI SAU nguồn vì mô hình nhỏ dễ
  quên câu hỏi sau vài nghìn token nguồn (hiện tượng trả lời lệch, trả lời thiếu ý).
- Mỗi nguồn mang nhãn [n], tên tài liệu, số hiệu, loại, ngày, hiệu lực → mô hình trích dẫn đúng nguồn.
"""
from aicommon.config import get_settings
from aicommon.resources import glossary_hits, prompt, skill_template
from aicommon.text import estimate_tokens, truncate_tokens

LOAI_TEN = {"quyet_dinh": "quyết định", "huong_dan": "hướng dẫn", "quy_dinh": "quy định", "bao_cao": "báo cáo",
            "ke_hoach": "kế hoạch", "cong_van": "công văn", "su_co": "sự cố kỹ thuật",
            "tai_lieu_ky_thuat": "tài liệu kỹ thuật"}


def format_source(i: int, s: dict) -> str:
    """Một nguồn trong ngữ cảnh:  [i] Tên › Mục (số hiệu, loại, ngày, tính chất) + nội dung."""
    head = s.get("breadcrumb") or s.get("title") or s.get("doc_id", "")
    tag = "văn bản chuẩn" if s.get("nguon") == "B" else "tài liệu tham khảo"
    ngay = (s.get("ngay_ban_hanh") or "")[:10]
    hl = s.get("trang_thai") if s.get("trang_thai") not in (None, "con_hieu_luc") else None
    meta = ", ".join(x for x in (s.get("so_hieu"), LOAI_TEN.get(s.get("loai", "")), ngay and f"ngày {ngay}", tag,
                                 hl and f"trạng thái: {hl}") if x)
    return f"[{i}] {head} ({meta})\n{s['text'].strip()}"


def select_sources(sources: list[dict], budget: int) -> list[dict]:
    """Giữ nguồn theo thứ tự điểm cho tới khi hết ngân sách token (CTX_BUDGET_SOURCES).

    Nguồn không vừa phần còn lại được CẮT BỚT (giữ phần đầu) thay vì bỏ hẳn, nếu còn ≥ 300 token –
    tránh mất trắng một mục liên quan chỉ vì nó dài hơn chỗ trống.
    """
    kept, used = [], 0
    for s in sources:
        t = estimate_tokens(s["text"]) + 30
        if used + t <= budget:
            kept.append(s)
            used += t
            continue
        room = budget - used - 30
        if room >= 300 or not kept:
            kept.append({**s, "text": truncate_tokens(s["text"], max(room, 200)), "cut": True})
        break
    return kept


class ContextBuilder:
    def __init__(self, role: str):
        self.s = get_settings()
        self.role = role

    def system(self, extra: str = "", skill: dict | None = None, question: str = "", sources_text: str = "") -> str:
        parts = [prompt("chinh-sach"), prompt(f"vai-tro/{self.role}")]
        if skill:
            parts.append(f"KỸ NĂNG ({skill['name']}):\n{skill['body']}")
            tpl = skill_template(skill)
            if tpl:
                parts.append(f"MẪU ĐẦU RA:\n{tpl}")
        terms = glossary_hits(question, sources_text)
        if terms:
            parts.append("THUẬT NGỮ CỦA ĐƠN VỊ:\n" + "\n".join(f"- {t}: {d}" for t, d in terms))
        if extra:
            parts.append(extra)
        return "\n\n".join(p for p in parts if p)

    def messages(self, question: str, sources: list[dict], history: list[dict], summary: str = "",
                 skill: dict | None = None) -> list[dict]:
        src_block = "\n\n".join(format_source(i + 1, s) for i, s in enumerate(sources)) or "(không có nguồn)"
        sys = self.system(skill=skill, question=question, sources_text=src_block[:4000])
        if summary:
            sys += f"\n\nTÓM TẮT HỘI THOẠI TRƯỚC:\n{summary}"
        msgs = [{"role": "system", "content": sys}]
        budget = self.s.ctx_budget_memory
        recent: list[dict] = []
        for m in reversed(history):
            t = estimate_tokens(m["content"])
            if t > budget:
                break
            recent.insert(0, {"role": m["role"], "content": m["content"]})
            budget -= t
        msgs.extend(recent)
        msgs.append({"role": "user", "content": (
            f"CÂU HỎI: {question}\n\nNGUỒN:\n{src_block}\n\n"
            f"NHẮC LẠI CÂU HỎI: {question}\n"
            "Trả lời đầy đủ mọi ý được hỏi, chỉ dùng thông tin trong NGUỒN; ghi [n] ngay sau mỗi ý, "
            "n là nguồn CHỨA ý đó.")})
        return msgs
