"""Các luồng xử lý câu hỏi. Mỗi luồng là async generator phát sự kiện:
status (tiến trình), meta (định tuyến, nguồn), delta (từng phần câu trả lời), step (bước tác tử),
final (kết quả đã kiểm chứng).

    route() ──► chao_hoi     : câu chào cố định, không gọi mô hình
            ├─► chinh_xac    : luong_b – nguyên văn từ kho Markdown chuẩn (không vector)
            ├─► tra_cuu      : luong_a – RAG lai (search-svc) + Verifier
            ├─► ho_tro       : cây xử lý sự cố + luong_a (vai trò hỗ trợ kỹ thuật)
            ├─► tim_tai_lieu : chỉ liệt kê tài liệu
            ├─► tong_hop     : gợi ý tài liệu, chuyển sang phân hệ Tổng hợp
            └─► tac_tu       : tác tử nhiều bước (công cụ theo vai trò, giới hạn bước/thời gian)
"""
import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

from aicommon.config import get_settings
from aicommon.internal import ServiceError
from aicommon.llm import AsyncLLM, LLMError
from aicommon.resources import prompt
from aicommon.security import UserCtx

from .context import ContextBuilder, format_source, select_sources
from .tools import exact_svc, run_tool, search_svc, support_svc, tools_for
from .verifier import REFUSAL, is_refusal, verify_a, verify_b

log = logging.getLogger("orchestrator.pipeline")
S = get_settings()
llm = AsyncLLM()

INTENTS = ["chinh_xac", "tra_cuu", "ho_tro", "tong_hop", "chao_hoi"]
# [TINH CHỈNH] Quy tắc định tuyến nhanh (không gọi mô hình). Câu hỏi không khớp quy tắc nào mới hỏi mô hình nhỏ
# (prompts/router.md). Bổ sung từ khóa nghiệp vụ của đơn vị vào các biểu thức dưới nếu hay bị định tuyến sai.
_RE_EXACT = re.compile(r"(\b(điều|khoản|điểm)\s+\d+)|(\d+/(\d{4}/)?[A-ZĐ]{2,}[A-ZĐ\-]*)|nguyên văn|quy định tại|"
                       r"thông số|quy trình chuẩn|trích dẫn", re.I)
_RE_SUPPORT = re.compile(r"\b(lỗi|sự cố|không (vào|kết nối|in|khởi động|đăng nhập|nhận)|hỏng|khắc phục|"
                         r"cài đặt|treo|chậm|mất kết nối|reset|cấu hình máy)\b", re.I)
_RE_GREET = re.compile(r"^(xin chào|chào|hello|hi|cảm ơn|cám ơn|bạn là ai|bạn làm được gì)\b", re.I)
_RE_SUM = re.compile(r"\b(tổng hợp|lập báo cáo|báo cáo tổng hợp)\b", re.I)


def ev(event: str, **data) -> dict:
    return {"event": event, "data": data}


# ---------------- Định tuyến ----------------
async def route(question: str, mode: str) -> str:
    if mode and mode != "tu_dong":
        return mode
    q = question.strip()
    if _RE_GREET.match(q) and len(q.split()) <= 8:
        return "chao_hoi"
    if _RE_EXACT.search(q):
        return "chinh_xac"
    if _RE_SUPPORT.search(q):
        return "ho_tro"
    if _RE_SUM.search(q):
        return "tong_hop"
    try:
        r = await llm.chat_json([{"role": "system", "content": prompt("router")}, {"role": "user", "content": q}],
                                schema={"type": "object", "properties": {"intent": {"type": "string", "enum": INTENTS}},
                                        "required": ["intent"]},
                                model=S.model_small, max_tokens=50, task="router")
        if r.get("intent") in INTENTS:
            return r["intent"]
    except LLMError as e:
        log.warning("Bộ định tuyến LLM lỗi, dùng mặc định: %s", e)
    return "tra_cuu"


async def rewrite(question: str, history: list[dict]) -> str:
    """Viết lại câu hỏi nối tiếp ("còn đơn vị kia thì sao?") thành câu độc lập để tìm kiếm đúng.
    Chỉ chạy khi có lịch sử hội thoại; dùng mô hình nhỏ (prompts/viet-lai-cau-hoi.md)."""
    if not history:
        return question
    convo = "\n".join(f"{'Người dùng' if m['role'] == 'user' else 'Trợ lý'}: {m['content'][:500]}" for m in history[-4:])
    try:
        r = await llm.chat_json([{"role": "system", "content": prompt("viet-lai-cau-hoi")},
                                 {"role": "user", "content": f"LỊCH SỬ:\n{convo}\n\nCÂU HỎI CUỐI: {question}"}],
                                schema={"type": "object", "properties": {"cau_hoi": {"type": "string"}},
                                        "required": ["cau_hoi"]},
                                model=S.model_small, max_tokens=200, task="rewrite")
        return (r.get("cau_hoi") or question).strip() or question
    except LLMError:
        return question


def _public_source(i: int, s: dict) -> dict:
    """Thông tin nguồn gửi giao diện (ngăn Nguồn). Văn bản dài được rút gọn để giảm dung lượng."""
    return {"n": i, "doc_id": s.get("doc_id"), "section_id": s.get("section_id"), "title": s.get("title"),
            "breadcrumb": s.get("breadcrumb"), "so_hieu": s.get("so_hieu"), "nguon": s.get("nguon"),
            "trang_thai": s.get("trang_thai"), "text": s.get("text", "")[:3000],
            "score": s.get("rerank_score", s.get("score")), "expanded": s.get("expanded", False)}


# ---------------- Luồng A: tra cứu ngữ nghĩa (RAG lai) ----------------
# Các bước: viết lại câu hỏi (nếu hội thoại nhiều lượt) → search-svc (lai + rerank + mở rộng mục)
# → chọn nguồn theo ngân sách token → mô hình chính sinh câu trả lời (luồng) → Verifier.
# Điểm tinh chỉnh: SEARCH_*, RERANK_*, CTX_BUDGET_SOURCES, ANSWER_MAX_TOKENS, ANSWER_TEMPERATURE, VERIFY_*
# (aicommon/config.py, docs/tinh-chinh-truy-xuat.md).
TRUNCATED_NOTE = ("\n\n*(Câu trả lời dài vượt giới hạn và đã được rút gọn đến ý trọn vẹn cuối cùng. "
                  "Hỏi tiếp “nêu các nội dung còn lại” hoặc thu hẹp câu hỏi.)*")


def trim_to_complete(text: str) -> str:
    """Cắt câu trả lời bị dừng giữa chừng (hết max_tokens) về dòng/câu trọn vẹn cuối cùng."""
    t = text.rstrip()
    cut = max(t.rfind("\n"), t.rfind(". "), t.rfind(".\n"), t.rfind("]."))
    if t.endswith((".", "]", "!", "?", "|")):
        return t
    return t[:cut + 1].rstrip() if cut > len(t) * 0.3 else t + " …"


async def luong_a(user: UserCtx, question: str, history: list[dict], summary: str, filters: dict,
                  role: str = "tra-cuu", extra_meta: dict | None = None) -> AsyncIterator[dict]:
    yield ev("status", text="Đang tìm kiếm trong tài liệu nội bộ…")
    q = await rewrite(question, history)
    try:
        r = await search_svc.call("POST", "/search", user, json={"query": q, "filters": filters})
        hits = r["results"]
    except ServiceError as e:
        yield ev("final", answer=f"Dịch vụ tìm kiếm không khả dụng: {e.detail}", sources=[], verify={"ok": False},
                 warnings=["search-svc lỗi"])
        return
    sources = select_sources(hits, S.ctx_budget_sources)
    pub = [_public_source(i + 1, s) for i, s in enumerate(sources)]
    yield ev("meta", query=q, sources=pub, **(extra_meta or {}))
    if not sources:
        yield ev("final", answer=REFUSAL, sources=[], verify={"ok": True, "warnings": []}, warnings=[],
                 **(extra_meta or {}))
        return
    # Câu viết lại (q) chỉ dùng để TÌM KIẾM; mô hình nhận câu hỏi gốc cùng lịch sử hội thoại
    msgs = ContextBuilder(role).messages(question, sources, history, summary)
    answer, info = "", {}
    yield ev("status", text=f"Đang soạn câu trả lời từ {len(sources)} nguồn…")
    try:
        async for d in llm.stream(msgs, model=S.model_main, temperature=S.answer_temperature,
                                  max_tokens=min(S.answer_max_tokens, S.ctx_reserve_output),
                                  task=f"answer-{role}", info=info):
            answer += d
            yield ev("delta", text=d)
    except LLMError as e:
        yield ev("final", answer=f"Máy chủ mô hình không khả dụng: {e}", sources=pub, verify={"ok": False},
                 warnings=[str(e)], **(extra_meta or {}))
        return
    truncated = info.get("finish_reason") == "length"
    if truncated:
        answer = trim_to_complete(answer)
    yield ev("status", text="Đang kiểm chứng trích dẫn và số liệu…")
    final, rep = verify_a(answer, sources, strict=S.verify_strict_a)
    if truncated and not is_refusal(final):
        rep.truncated = True
        final += TRUNCATED_NOTE
        rep.warnings.append(f"Câu trả lời chạm giới hạn {S.answer_max_tokens} token (ANSWER_MAX_TOKENS) và đã được rút gọn.")
    yield ev("final", answer=final, sources=pub, verify=rep.dict(), warnings=rep.warnings,
             replaced=final != answer, **(extra_meta or {}))


# ---------------- Luồng B: tra cứu chính xác (Markdown nguyên văn) ----------------
async def _choose_sections(user: UserCtx, q: str) -> tuple[list[str], list[dict]]:
    r = await exact_svc.call("POST", "/resolve", user, json={"query": q})
    if r["section_ids"]:
        return r["section_ids"][:3], []
    hits = (await exact_svc.call("POST", "/search", user, json={"query": q, "limit": 8}))["results"]
    if not hits:
        return [], []
    ids = [h["section_id"] for h in hits]
    if len(hits) == 1:
        return ids, hits
    cand = "\n".join(f"[{h['section_id']}] {' › '.join(h['path'])}: {h['snippet'][:240]}" for h in hits)
    try:
        out = await llm.chat_json(
            [{"role": "system", "content": prompt("chon-muc")},
             {"role": "user", "content": f"CÂU HỎI: {q}\n\nỨNG VIÊN:\n{cand}"}],
            schema={"type": "object", "properties": {"section_ids": {"type": "array", "maxItems": 3,
                                                                      "items": {"type": "string", "enum": ids}}},
                    "required": ["section_ids"]},
            model=S.model_small, max_tokens=120, task="chon-muc")
        chosen = [s for s in out.get("section_ids", []) if s in ids][:3]
    except LLMError:
        chosen = []
    if not chosen:  # dự phòng: các mục khớp đủ mọi từ khóa có điểm cao nhất
        chosen = [h["section_id"] for h in hits if h["match"] in ("phrase", "and")][:2] or ids[:1]
    return chosen, hits


def _drop_nested(blocks: list[dict]) -> list[dict]:
    ids = {b["section_id"] for b in blocks}
    out = []
    for b in blocks:  # bỏ mục con khi mục cha đã được chọn
        if any(b["section_id"].startswith(p + ".") for p in ids if p != b["section_id"]):
            continue
        out.append(b)
    return out


async def luong_b(user: UserCtx, question: str, history: list[dict], summary: str, filters: dict) -> AsyncIterator[dict]:
    yield ev("status", text="Đang tra cứu kho văn bản chuẩn…")
    q = await rewrite(question, history)
    try:
        ids, hits = await _choose_sections(user, q)
        blocks = [await exact_svc.call("GET", f"/sections/{sid}", user) for sid in ids]
    except ServiceError as e:
        yield ev("final", answer=f"Dịch vụ tra cứu chính xác không khả dụng: {e.detail}", exact_blocks=[],
                 verify={"ok": False}, warnings=["exact-svc lỗi"])
        return
    blocks = _drop_nested(blocks)
    for b in blocks:
        b["locator"] = locator(b)
    yield ev("meta", query=q, exact_blocks=blocks)
    if not blocks:
        related = []
        try:
            cat = (await exact_svc.call("GET", "/catalog", user))["docs"]
            related = cat[:5]
        except ServiceError:
            pass
        yield ev("final", answer=REFUSAL + " Có thể chuyển sang chế độ “Tra cứu tài liệu” để tìm thông tin tham khảo.",
                 exact_blocks=[], related_docs=related, verify={"ok": True}, warnings=[])
        return
    for b in blocks:
        b["locator"] = locator(b)
    verbatim = "\n\n".join(b["text"] for b in blocks)
    cau_dan, dien_giai, warn = lead_in(blocks), "", []
    if S.exact_llm_interpret:
        yield ev("status", text="Đang soạn diễn giải…")
        try:
            dien_giai = await interpret(verbatim, blocks, question)
        except LLMError as e:
            warn.append(f"Không sinh được diễn giải ({e}); hiển thị nguyên văn.")
    _, dien_giai, rep = verify_b("", dien_giai, verbatim)  # câu dẫn do khuôn mẫu sinh, chỉ kiểm diễn giải
    for b in blocks:
        if b.get("trang_thai") and b["trang_thai"] != "con_hieu_luc":
            rep.warnings.append(f"Văn bản {b['so_hieu']} có trạng thái “{b['trang_thai']}”"
                                + (f", được thay thế bởi {b['thay_the_boi']}" if b.get("thay_the_boi") else "") + ".")
        if not b.get("explicit_id"):
            rep.warnings.append(f"Mục {b['section_id']} chưa có mã định danh tường minh.")
    yield ev("final", answer=cau_dan, interpretation=dien_giai, exact_blocks=blocks, verify=rep.dict(),
             warnings=warn + rep.warnings, can_interpret=not dien_giai)


LOAI_VB = {"quyet_dinh": "Quyết định", "thong_tu": "Thông tư", "nghi_dinh": "Nghị định", "quy_dinh": "Quy định",
           "huong_dan": "Hướng dẫn", "ke_hoach": "Kế hoạch", "cong_van": "Công văn", "to_trinh": "Tờ trình",
           "bao_cao": "Báo cáo", "bien_ban": "Biên bản"}
_RE_DIEU = re.compile(r"^(Điều\s+\d+[a-zđ]?)", re.I)
_RE_KHOAN = re.compile(r"^(Khoản\s+\d+|Điểm\s+[a-zđ])", re.I)
_RE_CHUONG = re.compile(r"^((Chương|Mục|Phần)\s+[IVXLC\d]+)", re.I)


def locator(b: dict) -> str:
    """Vị trí trích dẫn lấy từ cấu trúc văn bản (không do mô hình viết): "Khoản 2 Điều 5", "Điều 1"..."""
    parts = []
    for h in [*(b.get("path") or [])[1:], b.get("heading", "")]:
        h = str(h).strip()
        m = _RE_KHOAN.match(h) or _RE_DIEU.match(h)
        if m and m.group(1) not in parts:
            parts.append(m.group(1))
    if not parts:
        for h in (b.get("path") or [])[1:]:
            m = _RE_CHUONG.match(str(h).strip())
            if m:
                parts.append(m.group(1))
    if not parts:
        return f"mục “{b.get('heading', '')}”" if b.get("heading") else ""
    parts = [p[0].upper() + p[1:] if i == len(parts) - 1 else p[0].lower() + p[1:]
             for i, p in enumerate(reversed(parts))]
    loc = " ".join(parts)
    return loc[0].upper() + loc[1:]


def doc_name(b: dict) -> str:
    loai = LOAI_VB.get(b.get("loai", ""), "văn bản")
    return f"{loai} số {b['so_hieu']}" if b.get("so_hieu") else f"{loai} “{b.get('ten', b.get('doc_id', ''))}”"


def lead_in(blocks: list[dict]) -> str:
    """Câu dẫn Luồng B theo khuôn mẫu: nhanh (không gọi mô hình) và vị trí luôn đúng."""
    if len(blocks) == 1:
        b = blocks[0]
        loc = b.get("locator") or locator(b)
        return f"Nội dung này được quy định tại {loc} {doc_name(b)} như sau:" if loc else \
            f"Nội dung này được quy định tại {doc_name(b)} như sau:"
    docs = list(dict.fromkeys(doc_name(b) for b in blocks))
    locs = "; ".join(f"{b.get('locator') or locator(b)}" for b in blocks)
    if len(docs) == 1:
        return f"Nội dung liên quan được quy định tại {locs} {docs[0]} như sau:"
    return "Nội dung liên quan được quy định tại các căn cứ sau:"


async def interpret(verbatim: str, blocks: list[dict], question: str) -> str:
    """Diễn giải ngắn (tham khảo) cho phần nguyên văn; kết quả luôn qua verify_b trước khi hiển thị."""
    labels = "; ".join(f"{b.get('locator') or locator(b)} {doc_name(b)}" for b in blocks)
    out = await llm.chat_json(
        [{"role": "system", "content": prompt("chinh-sach") + "\n\n" + prompt("vai-tro/chinh-xac")},
         {"role": "user", "content": f"CĂN CỨ: {labels}\n\nNGUYÊN VĂN:\n{verbatim}\n\nCÂU HỎI: {question}"}],
        schema={"type": "object", "properties": {"dien_giai": {"type": "string"}}, "required": ["dien_giai"]},
        model=S.model_main, max_tokens=250, task="dien-giai")
    return str(out.get("dien_giai", "")).strip()


# ---------------- Hỗ trợ kỹ thuật ----------------
def tree_answer(trees: list[dict]) -> str:
    t = trees[0]
    more = ""
    if len(trees) > 1:
        more = "\n\nCác hướng dẫn khác có thể phù hợp: " + ", ".join(f"**{x['ten']}**" for x in trees[1:3]) + "."
    return (f"Có hướng dẫn xử lý từng bước cho tình huống này: **{t['ten']}**. "
            "Bấm **Bắt đầu xử lý** bên dưới và trả lời từng câu hỏi; nếu không khắc phục được, "
            "hệ thống sẽ tạo phiếu yêu cầu hỗ trợ kèm các bước đã thực hiện." + more)


async def ho_tro(user: UserCtx, question: str, history: list[dict], summary: str, filters: dict) -> AsyncIterator[dict]:
    yield ev("status", text="Đang tìm hướng dẫn xử lý sự cố…")
    trees = []
    try:
        trees = await support_svc.call("GET", "/trees/suggest", user, params={"q": question})
    except ServiceError:
        pass
    f = {**filters, "loai": ["su_co", "huong_dan", "tai_lieu_ky_thuat"]}
    meta = {"trees": trees}

    async def run(flt):
        async for e in luong_a(user, question, history, summary, flt, role="ho-tro", extra_meta=meta):
            yield e

    final = None
    async for e in run(f):
        if e["event"] == "final":
            final = e["data"]
            break
        yield e
    if final is not None and not final.get("sources"):
        # không có tài liệu kỹ thuật phù hợp → tìm trên toàn bộ tài liệu
        final = None
        async for e in run(filters):
            if e["event"] == "final":
                final = e["data"]
                break
            yield e
    final = final or {"answer": REFUSAL, "sources": [], "verify": {"ok": True}, "warnings": [], **meta}
    if trees and is_refusal(final.get("answer", "")):
        # Tài liệu không có lời giải nhưng có cây xử lý sự cố: hướng người dùng vào cây, không trả lời "không có căn cứ"
        final = {**final, "answer": tree_answer(trees), "verify": {"ok": True, "warnings": []}, "warnings": []}
    yield ev("final", **final)


# ---------------- Tìm tài liệu, chào hỏi, tổng hợp ----------------
async def tim_tai_lieu(user: UserCtx, question: str, history, summary, filters) -> AsyncIterator[dict]:
    r = await search_svc.call("POST", "/documents", user, json={"query": question, "filters": filters})
    n = len(r["results"])
    yield ev("final", answer=f"Tìm thấy {n} tài liệu liên quan." if n else "Không tìm thấy tài liệu phù hợp.",
             docs=r["results"], verify={"ok": True}, warnings=[])


GREETING = ("Xin chào! Tôi là trợ lý AI nội bộ, có thể hỗ trợ:\n\n"
            "- **Tra cứu tài liệu** nội bộ, câu trả lời có trích dẫn nguồn để đối chiếu.\n"
            "- **Tra cứu chính xác** văn bản chuẩn: trích nguyên văn điều, khoản (ví dụ: \"Điều 5 Quyết định 15/QĐ-ĐVA\").\n"
            "- **Tổng hợp báo cáo** theo mẫu từ nhiều tài liệu.\n"
            "- **Hỗ trợ kỹ thuật** theo hướng dẫn xử lý sự cố từng bước.\n\n"
            "Hãy nhập câu hỏi cụ thể để bắt đầu.")


async def chao_hoi(user: UserCtx, question: str, history, summary, filters) -> AsyncIterator[dict]:
    # Câu chào hỏi, hỏi chức năng: trả lời dựng sẵn, không gọi mô hình (trên CPU tiết kiệm hàng chục giây)
    yield ev("delta", text=GREETING)
    yield ev("final", answer=GREETING, verify={"ok": True}, warnings=[])


async def tong_hop(user: UserCtx, question: str, history, summary, filters) -> AsyncIterator[dict]:
    r = await search_svc.call("POST", "/documents", user, json={"query": question, "filters": filters})
    yield ev("final", answer="Yêu cầu tổng hợp nhiều văn bản được thực hiện tại chức năng **Tổng hợp** "
                             "(chọn văn bản, chọn mẫu báo cáo; số liệu do chương trình tính). "
                             "Dưới đây là các tài liệu có thể đưa vào báo cáo.",
             docs=r["results"], open_module="tong-hop", verify={"ok": True}, warnings=[])


# ---------------- Trợ lý nhiều bước (vòng lặp tác tử có giới hạn) ----------------
async def tac_tu(user: UserCtx, question: str, history: list[dict], summary: str, filters) -> AsyncIterator[dict]:
    tools = [t.openai() for t in tools_for(user)]
    msgs = [{"role": "system", "content": prompt("chinh-sach") + "\n\n" + prompt("tac-tu")},
            *[{"role": m["role"], "content": m["content"]} for m in history[-4:]],
            {"role": "user", "content": question}]
    sources: list[dict] = []
    t0 = time.monotonic()
    for step in range(S.agent_max_steps):
        yield ev("status", text=f"Bước {step + 1}: đang lập kế hoạch…")
        if time.monotonic() - t0 > S.agent_timeout_s:
            yield ev("step", n=step, note="Hết thời gian cho phép, dừng vòng lặp.")
            break
        try:
            data = await llm.chat_raw(msgs, model=S.model_main, tools=tools, max_tokens=800, task="tac-tu")
        except LLMError as e:
            yield ev("final", answer=f"Máy chủ mô hình không khả dụng: {e}", sources=[], verify={"ok": False},
                     warnings=[str(e)])
            return
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            final, rep = verify_a(msg.get("content") or "", sources, strict=S.verify_strict_a)
            yield ev("final", answer=final, sources=[_public_source(i + 1, s) for i, s in enumerate(sources)],
                     verify=rep.dict(), warnings=rep.warnings, steps=step)
            return
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
                res = await asyncio.wait_for(run_tool(user, name, args), timeout=60)
            except Exception as e:  # lỗi công cụ được trả lại cho mô hình để tự điều chỉnh
                res = {"loi": str(e)}
            if isinstance(res, list):  # đánh số nguồn để mô hình trích dẫn
                for item in res:
                    if isinstance(item, dict) and item.get("text"):
                        sources.append(item)
                        item["n"] = len(sources)
            elif isinstance(res, dict) and res.get("text"):
                sources.append(res)
                res["n"] = len(sources)
            yield ev("step", n=step + 1, tool=name, args=args if isinstance(args, dict) else {},
                     result_count=len(res) if isinstance(res, list) else 1)
            msgs.append({"role": "tool", "tool_call_id": c.get("id", name),
                         "content": json.dumps(res, ensure_ascii=False)[:6000]})
    final_text = REFUSAL if not sources else "\n\n".join(format_source(i + 1, s) for i, s in enumerate(sources[:3]))
    yield ev("final", answer=("Đã đạt giới hạn số bước. " + (REFUSAL if not sources else "Các căn cứ thu thập được:\n\n"
                                                            + final_text)),
             sources=[_public_source(i + 1, s) for i, s in enumerate(sources)], verify={"ok": False},
             warnings=["Vòng lặp tác tử dừng do giới hạn."])


PIPELINES = {"tra_cuu": luong_a, "chinh_xac": luong_b, "ho_tro": ho_tro, "tim_tai_lieu": tim_tai_lieu,
             "chao_hoi": chao_hoi, "tong_hop": tong_hop, "tac_tu": tac_tu}
