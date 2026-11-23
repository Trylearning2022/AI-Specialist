"""Các luồng xử lý câu hỏi. Mỗi luồng là async generator phát sự kiện SSE:

    plan    kế hoạch các bước của lượt trả lời       {steps: [{id, name}]}
    step    cập nhật một bước                         {id, name?, status: dang_chay|xong|bo_qua|loi, detail, ms}
    status  dòng trạng thái (tương thích bản cũ)      {text}
    meta    định tuyến, nguồn                          {query, sources | exact_blocks}
    delta   từng phần câu trả lời                      {text}
    final   kết quả đã kiểm chứng                      {answer, sources, verify, warnings, clarify?, task?}

    route() ──► chao_hoi     : câu chào cố định, không gọi mô hình
            ├─► chinh_xac    : luong_b – nguyên văn từ kho Markdown chuẩn (không vector)
            ├─► tra_cuu      : luong_a – RAG lai (search-svc) + Verifier
            ├─► ho_tro       : luong_a trên tài liệu kỹ thuật, trình bày các bước xử lý (vai trò hỗ trợ kỹ thuật)
            ├─► tim_tai_lieu : chỉ liệt kê tài liệu
            ├─► tong_hop     : tạo tác vụ "Tổng hợp báo cáo" (có tệp đính kèm) hoặc gợi ý tài liệu
            ├─► phan_tich    : tạo tác vụ "Phân tích văn bản" (tệp đính kèm / văn bản dán dài)
            ├─► soan_thao    : tạo tác vụ "Soạn văn bản tham mưu" (dàn ý chờ xác nhận)
            └─► tac_tu       : tác tử nhiều bước (công cụ theo vai trò, giới hạn bước/thời gian)

Trước luồng: lớp bảo vệ an toàn thông tin (aicommon/guard.py) và hỏi lại làm rõ (clarify.py).
"""
import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

from aicommon.config import get_settings
from aicommon.internal import AsyncSvc, ServiceError
from aicommon.llm import AsyncLLM, LLMError
from aicommon.resources import prompt
from aicommon.security import UserCtx

from . import clarify
from .context import ContextBuilder, format_source, select_sources
from .tools import exact_svc, run_tool, search_svc, tools_for
from .verifier import REFUSAL, is_refusal, verify_a, verify_b

log = logging.getLogger("orchestrator.pipeline")
S = get_settings()
llm = AsyncLLM()
agent_svc = AsyncSvc(S.agent_url)

INTENTS = ["chinh_xac", "tra_cuu", "ho_tro", "tong_hop", "soan_thao", "chao_hoi"]
# [TINH CHỈNH] Quy tắc định tuyến nhanh (không gọi mô hình). Câu hỏi không khớp quy tắc nào mới hỏi mô hình nhỏ
# (prompts/router.md). Bổ sung từ khóa nghiệp vụ của đơn vị vào các biểu thức dưới nếu hay bị định tuyến sai.
_RE_EXACT = re.compile(r"(\b(điều|khoản|điểm)\s+\d+)|(\d+/(\d{4}/)?[A-ZĐ]{2,}[A-ZĐ\-]*)|nguyên văn|quy định tại|"
                       r"thông số|quy trình chuẩn|trích dẫn", re.I)
_RE_SUPPORT = re.compile(r"\b(lỗi|sự cố|không (vào|kết nối|in|khởi động|đăng nhập|nhận|ký)|hỏng|khắc phục|"
                         r"cài đặt|treo|chậm|mất kết nối|reset|cấu hình máy|bị khóa|sai mã pin|hết hạn)\b", re.I)
_RE_GREET = re.compile(r"^(xin chào|chào|hello|hi|cảm ơn|cám ơn|bạn là ai|bạn làm được gì)\b", re.I)
# Tham gia ý kiến dự thảo: "góp ý dự thảo", "tham gia ý kiến vào dự thảo…" (kèm tệp dự thảo)
_RE_GOPY = re.compile(r"\b(tham gia ý kiến|góp ý|cho ý kiến)\b", re.I)
_RE_SUM = re.compile(r"\b(tổng hợp|lập báo cáo|báo cáo tổng hợp|báo cáo chung)\b", re.I)
_RE_DRAFT = re.compile(r"\b(soạn|dự thảo|xây dựng|viết|lập)\s+(?:giúp\s+|cho\s+tôi\s+|hộ\s+)?(?:một\s+|01\s+)?(?:bản\s+)?"
                       r"(tờ trình|kế hoạch|công văn|báo cáo đề xuất|báo cáo sự cố|báo cáo (?:kết quả )?tự kiểm tra|văn bản đề nghị|văn bản đề xuất|văn bản tham mưu|đề xuất|văn bản góp ý)", re.I)
_RE_ANALYZE = re.compile(r"\b(phân tích|rà soát|góp ý|nhận xét|đánh giá|tóm tắt|đọc)\b", re.I)
# [TINH CHỈNH] Từ khóa → mẫu văn bản tham mưu (skills/soan-*)
# Cụm từ cụ thể đặt TRƯỚC (báo cáo sự cố, tự kiểm tra, đề nghị triển khai SPMM dùng chung mẫu báo cáo / công văn).
DRAFT_MAP = [("báo cáo sự cố", "soan-bao-cao-de-xuat"), ("tự kiểm tra", "soan-bao-cao-de-xuat"),
             ("đề nghị triển khai", "soan-bao-cao-de-xuat"), ("đề nghị trang bị", "soan-bao-cao-de-xuat"),
             ("đề nghị cung cấp sản phẩm mật mã", "soan-bao-cao-de-xuat"),
             ("tờ trình", "soan-to-trinh"), ("kế hoạch", "soan-ke-hoach"), ("góp ý", "soan-cong-van-gop-y"),
             ("công văn", "soan-cong-van-gop-y"), ("đề xuất", "soan-bao-cao-de-xuat"), ("tham mưu", "soan-bao-cao-de-xuat")]


def ev(event: str, **data) -> dict:
    return {"event": event, "data": data}


class Steps:
    """Kế hoạch các bước của một lượt trả lời – giao diện vẽ thành thanh tiến trình từng bước."""

    def __init__(self, steps: list[tuple[str, str]]):
        self.steps, self.t0 = steps, {}
        self.names = dict(steps)

    def plan(self) -> dict:
        return ev("plan", steps=[{"id": i, "name": n} for i, n in self.steps])

    def start(self, sid: str, detail: str = "") -> dict:
        self.t0[sid] = time.monotonic()
        return ev("step", id=sid, name=self.names.get(sid, sid), status="dang_chay", detail=detail)

    def done(self, sid: str, detail: str = "", status: str = "xong") -> dict:
        ms = int((time.monotonic() - self.t0.get(sid, time.monotonic())) * 1000)
        return ev("step", id=sid, name=self.names.get(sid, sid), status=status, detail=detail, ms=ms)

    def skip(self, sid: str, detail: str = "") -> dict:
        return ev("step", id=sid, name=self.names.get(sid, sid), status="bo_qua", detail=detail)


PLAN_A = [("hieu", "Phân tích câu hỏi"), ("tim", "Tìm kiếm tài liệu nội bộ"), ("chon", "Chọn nguồn phù hợp"),
          ("soan", "Soạn câu trả lời"), ("kiem", "Kiểm chứng trích dẫn, số liệu")]
PLAN_SUPPORT = [("hieu", "Xác định thiết bị, triệu chứng"), ("tim", "Tìm hướng dẫn trong tài liệu kỹ thuật"),
                ("chon", "Chọn hướng dẫn phù hợp"), ("soan", "Lập các bước xử lý"), ("kiem", "Kiểm chứng theo tài liệu")]
PLAN_B = [("hieu", "Phân tích câu hỏi"), ("dinh_vi", "Định vị điều, khoản trong kho văn bản chuẩn"),
          ("trich", "Trích nguyên văn"), ("kiem", "Kiểm tra hiệu lực, phiên bản")]


async def gop_y(user: UserCtx, question: str, history, summary, filters, attachments: list | None = None,
                conversation_id: str = "", **_) -> AsyncIterator[dict]:
    """Tham gia ý kiến dự thảo: tệp đính kèm là dự thảo (và văn bản đề nghị, nếu có – hệ thống tự nhận)."""
    steps = Steps([("tao", "Tạo tác vụ tham gia ý kiến dự thảo")])
    yield steps.plan()
    yield steps.start("tao")
    if not attachments:
        yield steps.skip("tao", "Chưa có dự thảo")
        yield ev("final", answer="Để tham gia ý kiến, đồng chí **đính kèm tệp dự thảo** (và công văn đề nghị tham gia ý kiến, "
                                 "nếu có) rồi gửi lại yêu cầu, hoặc vào **Soạn văn bản tham mưu → Công văn → Tham gia ý kiến dự thảo**.",
                 open_module="gop-y", verify={"ok": True}, warnings=[])
        return
    try:
        t = await _create_task(user, "soan_thao", {"mau": "soan-cong-van-gop-y", "che_do": "gop_y", "upload_ids": attachments,
                                                   "yeu_cau_them": question.strip()[:500]},
                               conversation_id)
    except ServiceError as e:
        yield steps.done("tao", e.detail, status="loi")
        yield ev("final", answer=f"Không tạo được tác vụ tham gia ý kiến: {e.detail}", verify={"ok": False}, warnings=[e.detail])
        return
    yield steps.done("tao")
    yield ev("final", **_task_answer(t, "Đã tạo tác vụ **soạn công văn tham gia ý kiến dự thảo**. Hệ thống rà soát thuật ngữ chuyên môn, "
                                        "căn cứ pháp lý, nhiệm vụ của ngành và nội dung kỹ thuật (bảo mật, ký số, xác thực), "
                                        "lập danh sách ý kiến và **dừng chờ đồng chí chọn, sửa** trước khi hoàn thiện công văn "
                                        "(Căn cứ → Nội dung tham gia ý kiến → Đề xuất, kiến nghị)."))


# ---------------- Định tuyến ----------------
async def route(question: str, mode: str, attachments: int = 0) -> str:
    """Định tuyến: quy tắc trước (nhanh, tất định), mô hình nhỏ chỉ khi không khớp quy tắc nào."""
    if mode and mode != "tu_dong":
        return mode
    q = question.strip()
    if attachments:  # có tệp đính kèm: tham gia ý kiến, tổng hợp (nhiều tệp + "tổng hợp") hoặc phân tích
        if _RE_GOPY.search(q):
            return "gop_y"
        return "tong_hop" if (attachments > 1 and _RE_SUM.search(q)) else "phan_tich"
    if _RE_GREET.match(q) and len(q.split()) <= 8:
        return "chao_hoi"
    if _RE_GOPY.search(q) and re.search(r"\bdự thảo\b", q, re.I):
        return "gop_y"  # chưa đính kèm dự thảo: pipeline hướng dẫn đính kèm
    if _RE_DRAFT.search(q):
        return "soan_thao"
    if len(q) >= 1500 and _RE_ANALYZE.search(q[:300]):  # dán nguyên văn bản dài kèm yêu cầu phân tích
        return "phan_tich"
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
                  role: str = "tra-cuu", extra_meta: dict | None = None, steps: Steps | None = None,
                  allow_clarify: bool = True) -> AsyncIterator[dict]:
    own = steps is None
    steps = steps or Steps(PLAN_A)
    if own:
        yield steps.plan()
        yield steps.start("hieu")
    q = await rewrite(question, history)
    yield steps.done("hieu", "Đã viết lại câu hỏi theo ngữ cảnh hội thoại" if q != question else "")
    yield ev("status", text="Đang tìm kiếm trong tài liệu nội bộ…")
    yield steps.start("tim", "Tìm kết hợp ngữ nghĩa và từ khóa, xếp hạng lại")
    try:
        r = await search_svc.call("POST", "/search", user, json={"query": q, "filters": filters})
        hits = r["results"]
    except ServiceError as e:
        yield steps.done("tim", "Dịch vụ tìm kiếm không khả dụng", status="loi")
        yield ev("final", answer=f"Dịch vụ tìm kiếm không khả dụng: {e.detail}", sources=[], verify={"ok": False},
                 warnings=["search-svc lỗi"])
        return
    yield steps.done("tim", f"{len(hits)} mục liên quan từ {len({h['doc_id'] for h in hits})} tài liệu")
    if allow_clarify:
        c = clarify.scattered(hits)
        if c:
            for sid in ("chon", "soan", "kiem"):
                yield steps.skip(sid, "Chờ đồng chí làm rõ câu hỏi")
            yield ev("final", answer=c["question"], clarify={**c, "original": question}, sources=[],
                     verify={"ok": True}, warnings=[], **(extra_meta or {}))
            return
    yield steps.start("chon")
    sources = select_sources(hits, S.ctx_budget_sources)
    pub = [_public_source(i + 1, s) for i, s in enumerate(sources)]
    yield ev("meta", query=q, sources=pub, **(extra_meta or {}))
    yield steps.done("chon", f"{len(sources)} nguồn trong ngân sách ngữ cảnh" if sources else "Không có nguồn phù hợp")
    if not sources:
        yield steps.skip("soan", "Không có căn cứ")
        yield steps.skip("kiem")
        yield ev("final", answer=REFUSAL, sources=[], verify={"ok": True, "warnings": []}, warnings=[],
                 **(extra_meta or {}))
        return
    # Câu viết lại (q) chỉ dùng để TÌM KIẾM; mô hình nhận câu hỏi gốc cùng lịch sử hội thoại
    msgs = ContextBuilder(role).messages(question, sources, history, summary)
    answer, info = "", {}
    yield ev("status", text=f"Đang soạn câu trả lời từ {len(sources)} nguồn…")
    yield steps.start("soan", f"Mô hình đọc {len(sources)} nguồn và soạn câu trả lời")
    try:
        async for d in llm.stream(msgs, model=S.model_main, temperature=S.answer_temperature,
                                  max_tokens=min(S.answer_max_tokens, S.ctx_reserve_output),
                                  task=f"answer-{role}", info=info):
            answer += d
            yield ev("delta", text=d)
    except LLMError as e:
        yield steps.done("soan", "Máy chủ mô hình không khả dụng", status="loi")
        yield ev("final", answer=f"Máy chủ mô hình không khả dụng: {e}", sources=pub, verify={"ok": False},
                 warnings=[str(e)], **(extra_meta or {}))
        return
    truncated = info.get("finish_reason") == "length"
    if truncated:
        answer = trim_to_complete(answer)
    yield steps.done("soan", "Đã rút gọn do chạm giới hạn độ dài" if truncated else "")
    yield ev("status", text="Đang kiểm chứng trích dẫn và số liệu…")
    yield steps.start("kiem")
    final, rep = verify_a(answer, sources, strict=S.verify_strict_a)
    if truncated and not is_refusal(final):
        rep.truncated = True
        final += TRUNCATED_NOTE
        rep.warnings.append(f"Câu trả lời chạm giới hạn {S.answer_max_tokens} token (ANSWER_MAX_TOKENS) và đã được rút gọn.")
    parts = []
    if rep.fixed_citations:
        parts.append(f"sửa {len(rep.fixed_citations)} trích dẫn")
    if rep.unsupported:
        parts.append(f"{len(rep.unsupported)} câu chưa có căn cứ")
    if rep.bad_numbers:
        parts.append(f"{len(rep.bad_numbers)} số liệu cần đối chiếu")
    yield steps.done("kiem", ", ".join(parts) or "Đạt", status="xong")
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


async def luong_b(user: UserCtx, question: str, history: list[dict], summary: str, filters: dict,
                  **_) -> AsyncIterator[dict]:
    steps = Steps(PLAN_B)
    yield steps.plan()
    yield ev("status", text="Đang tra cứu kho văn bản chuẩn…")
    yield steps.start("hieu")
    q = await rewrite(question, history)
    yield steps.done("hieu")
    yield steps.start("dinh_vi", "Theo số hiệu, điều, khoản; tìm toàn văn (không dùng vector)")
    try:
        ids, hits = await _choose_sections(user, q)
        yield steps.done("dinh_vi", f"{len(ids)} mục" if ids else "Không định vị được mục phù hợp")
        yield steps.start("trich")
        blocks = [await exact_svc.call("GET", f"/sections/{sid}", user) for sid in ids]
    except ServiceError as e:
        yield steps.done("dinh_vi", "Dịch vụ tra cứu chính xác không khả dụng", status="loi")
        yield ev("final", answer=f"Dịch vụ tra cứu chính xác không khả dụng: {e.detail}", exact_blocks=[],
                 verify={"ok": False}, warnings=["exact-svc lỗi"])
        return
    blocks = _drop_nested(blocks)
    for b in blocks:
        b["locator"] = locator(b)
    yield ev("meta", query=q, exact_blocks=blocks)
    yield steps.done("trich", "; ".join(f"{b['locator']} {b.get('so_hieu', '')}".strip() for b in blocks)[:200])
    if not blocks:
        yield steps.skip("kiem")
        related = []
        try:
            cat = (await exact_svc.call("GET", "/catalog", user))["docs"]
            related = cat[:5]
        except ServiceError:
            pass
        yield ev("final", answer=REFUSAL + " Có thể chuyển sang chế độ “Tra cứu tài liệu” để tìm thông tin tham khảo.",
                 exact_blocks=[], related_docs=related, verify={"ok": True}, warnings=[])
        return
    yield steps.start("kiem")
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
    yield steps.done("kiem", "Còn hiệu lực" if not rep.warnings else f"{len(rep.warnings)} lưu ý")
    yield ev("final", answer=cau_dan, interpretation=dien_giai, exact_blocks=blocks, verify=rep.dict(),
             warnings=warn + rep.warnings, can_interpret=not dien_giai)


LOAI_VB = {"quyet_dinh": "Quyết định", "thong_tu": "Thông tư", "nghi_dinh": "Nghị định", "quy_dinh": "Quy định",
           "huong_dan": "Hướng dẫn", "ke_hoach": "Kế hoạch", "cong_van": "Công văn", "to_trinh": "Tờ trình",
           "bao_cao": "Báo cáo", "bien_ban": "Biên bản", "luat": "Luật", "phap_lenh": "Pháp lệnh"}
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
    if b.get("loai") in ("luat", "phap_lenh") and b.get("ten") and b.get("so_hieu"):  # "Luật Cơ yếu số 05/2011/QH13"
        return f"{b['ten']} số {b['so_hieu']}"
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


# ---------------- Hỗ trợ kỹ thuật (gộp vào hỏi đáp chung) ----------------
# Từ 1.3.0 không dùng cây xử lý soạn tay theo từng lĩnh vực: các bước xử lý được TRÍCH TỰ ĐỘNG từ tài liệu
# hướng dẫn, sự cố đã nạp (loại su_co, huong_dan, tai_lieu_ky_thuat); câu hỏi chưa rõ thiết bị/triệu chứng được
# hỏi lại trước (clarify.py). Không có tài liệu phù hợp → đề nghị tạo phiếu yêu cầu hỗ trợ ngay trong trò chuyện.
TECH_TYPES = ["su_co", "huong_dan", "tai_lieu_ky_thuat"]
NO_FIX = ("Chưa tìm thấy hướng dẫn xử lý phù hợp trong tài liệu kỹ thuật của đơn vị.\n\n"
          "Đề nghị đồng chí **tạo phiếu yêu cầu hỗ trợ** (nút bên dưới) và mô tả: thiết bị/phần mềm, thông báo lỗi "
          "(nếu có), các thao tác đã thử. Không gửi kèm mã PIN, mật khẩu hoặc tệp khóa bí mật.")


async def ho_tro(user: UserCtx, question: str, history: list[dict], summary: str, filters: dict,
                 **_) -> AsyncIterator[dict]:
    steps = Steps(PLAN_SUPPORT)
    yield steps.plan()
    yield ev("status", text="Đang tìm hướng dẫn xử lý trong tài liệu kỹ thuật…")
    yield steps.start("hieu")
    obj = clarify.detect_object(question)
    meta = {"support": {"doi_tuong": obj["label"] if obj else "", "co_the_tao_phieu": True}}
    final = None
    for flt in ({**filters, "loai": TECH_TYPES}, filters):  # ưu tiên tài liệu kỹ thuật, không có → toàn bộ tài liệu
        final = None
        async for e in luong_a(user, question, history, summary, flt, role="ho-tro", extra_meta=meta, steps=steps,
                               allow_clarify=False):
            if e["event"] == "final":
                final = e["data"]
                break
            yield e
        if final and final.get("sources"):
            break
    final = final or {"answer": REFUSAL, "sources": [], "verify": {"ok": True}, "warnings": [], **meta}
    if is_refusal(final.get("answer", "")):
        final = {**final, "answer": NO_FIX, "verify": {"ok": True, "warnings": []}, "warnings": [], **meta}
    yield ev("final", **final)


# ---------------- Tìm tài liệu, chào hỏi ----------------
async def tim_tai_lieu(user: UserCtx, question: str, history, summary, filters, **_) -> AsyncIterator[dict]:
    steps = Steps([("tim", "Tìm tài liệu liên quan")])
    yield steps.plan()
    yield steps.start("tim")
    r = await search_svc.call("POST", "/documents", user, json={"query": question, "filters": filters})
    n = len(r["results"])
    yield steps.done("tim", f"{n} tài liệu")
    yield ev("final", answer=f"Tìm thấy {n} tài liệu liên quan." if n else "Không tìm thấy tài liệu phù hợp.",
             docs=r["results"], verify={"ok": True}, warnings=[])


GREETING = ("Xin chào! Tôi là trợ lý AI nội bộ, có thể hỗ trợ đồng chí:\n\n"
            "- **Tra cứu tài liệu** nội bộ, câu trả lời có trích dẫn nguồn để đối chiếu.\n"
            "- **Tra cứu chính xác** văn bản chuẩn: trích nguyên văn điều, khoản (ví dụ: \"Điều 5 Quyết định 15/QĐ-ĐVA\").\n"
            "- **Hỗ trợ kỹ thuật**: USB Token, chứng thư số, phần mềm ký số, máy tính, mạng – các bước xử lý theo tài liệu.\n"
            "- **Phân tích văn bản mới**: đính kèm tệp, nhận tóm tắt và các vấn đề liên quan đến ngành.\n"
            "- **Soạn văn bản tham mưu**: tờ trình, kế hoạch, báo cáo đề xuất, công văn góp ý theo mẫu.\n"
            "- **Tổng hợp báo cáo chung** từ nhiều báo cáo riêng lẻ; số liệu do chương trình tính.\n\n"
            "Hãy nhập câu hỏi cụ thể hoặc đính kèm văn bản để bắt đầu.")


async def chao_hoi(user: UserCtx, question: str, history, summary, filters, **_) -> AsyncIterator[dict]:
    # Câu chào hỏi, hỏi chức năng: trả lời dựng sẵn, không gọi mô hình (trên CPU tiết kiệm hàng chục giây)
    yield ev("delta", text=GREETING)
    yield ev("final", answer=GREETING, verify={"ok": True}, warnings=[])


# ---------------- Tác vụ dài: tạo tác vụ ở agent-svc, trả thẻ tiến trình vào trò chuyện ----------------
async def _create_task(user: UserCtx, kind: str, inp: dict, conversation_id: str, title: str = "") -> dict:
    return await agent_svc.call("POST", "/tasks", user, json={"kind": kind, "input": inp, "title": title,
                                                              "conversation_id": conversation_id or ""})


def _task_answer(t: dict, intro: str) -> dict:
    return {"answer": intro, "task": {k: t.get(k) for k in ("id", "kind", "kind_label", "title", "status")},
            "verify": {"ok": True}, "warnings": []}


async def phan_tich(user: UserCtx, question: str, history, summary, filters, attachments: list | None = None,
                    conversation_id: str = "", **_) -> AsyncIterator[dict]:
    steps = Steps([("tao", "Tạo tác vụ phân tích văn bản")])
    yield steps.plan()
    yield steps.start("tao")
    q = question.strip()
    yeu_cau = "" if re.fullmatch(r"(hãy\s+)?(phân tích|tóm tắt|đọc|rà soát)(\s+(giúp|văn bản|tài liệu|này|tệp))*\.?", q, re.I) else q[:500]
    try:
        if attachments:
            t = await _create_task(user, "phan_tich", {"upload_id": attachments[0], "yeu_cau": yeu_cau}, conversation_id)
        elif len(q) >= 1500:
            t = await _create_task(user, "phan_tich", {"text": q, "yeu_cau": ""}, conversation_id)
        else:
            yield steps.skip("tao", "Chưa có văn bản")
            yield ev("final", answer="Để phân tích văn bản mới, đồng chí **đính kèm tệp** (nút kẹp giấy ở ô nhập) rồi gửi "
                                     "kèm yêu cầu, hoặc mở tiện ích **Phân tích văn bản**.", open_module="phan-tich",
                     verify={"ok": True}, warnings=[])
            return
    except ServiceError as e:
        yield steps.done("tao", e.detail, status="loi")
        yield ev("final", answer=f"Không tạo được tác vụ phân tích: {e.detail}", verify={"ok": False}, warnings=[e.detail])
        return
    yield steps.done("tao")
    extra = f" Câu hỏi riêng của đồng chí được đưa thành tiêu chí đầu tiên: “{yeu_cau[:200]}”." if yeu_cau else ""
    yield ev("final", **_task_answer(t, "Đã tiếp nhận văn bản và tạo tác vụ **phân tích** (chạy nền, theo dõi tiến trình "
                                        "bên dưới). Kết quả gồm: tóm tắt, các vấn đề liên quan đến ngành theo bộ tiêu chí, "
                                        "nhiệm vụ – thời hạn, đối chiếu cơ sở tri thức, điểm cần lưu ý." + extra))


async def soan_thao(user: UserCtx, question: str, history, summary, filters, attachments: list | None = None,
                    conversation_id: str = "", **_) -> AsyncIterator[dict]:
    steps = Steps([("tao", "Tạo tác vụ soạn văn bản tham mưu")])
    yield steps.plan()
    yield steps.start("tao")
    low = question.lower()
    mau = next((m for k, m in DRAFT_MAP if k in low), "soan-bao-cao-de-xuat")
    chu_de = re.sub(r"^.*?\b(soạn|dự thảo|xây dựng|viết|lập)\b\s+(?:giúp\s+|cho\s+tôi\s+|hộ\s+)?(?:một\s+|01\s+)?(?:bản\s+)?"
                    r"(tờ trình|kế hoạch|công văn|báo cáo đề xuất|báo cáo sự cố|báo cáo (?:kết quả )?tự kiểm tra|văn bản đề nghị|văn bản đề xuất|văn bản tham mưu|đề xuất|văn bản góp ý)\s*"
                    r"(về\s+việc|về|v/v|đề nghị)?\s*", "", question.strip(), flags=re.I).strip(" .:") or question
    try:
        t = await _create_task(user, "soan_thao", {"mau": mau, "chu_de": chu_de[:300], "muc_dich": question[:1000],
                                                   "upload_ids": attachments or []}, conversation_id)
    except ServiceError as e:
        yield steps.done("tao", e.detail, status="loi")
        yield ev("final", answer=f"Không tạo được tác vụ soạn thảo: {e.detail}", verify={"ok": False}, warnings=[e.detail])
        return
    yield steps.done("tao")
    yield ev("final", **_task_answer(t, f"Đã tạo tác vụ **soạn {t.get('title', '').split(':')[0].lower()}**. Hệ thống sẽ thu thập "
                                        "căn cứ, lập dàn ý và **dừng chờ đồng chí xác nhận dàn ý** trước khi viết từng phần. "
                                        "Có thể bổ sung đơn vị soạn, nơi nhận, người ký ở màn hình tác vụ."))


async def tong_hop(user: UserCtx, question: str, history, summary, filters, attachments: list | None = None,
                   conversation_id: str = "", **_) -> AsyncIterator[dict]:
    steps = Steps([("tim", "Chuẩn bị đầu vào tổng hợp")])
    yield steps.plan()
    yield steps.start("tim")
    if attachments:
        try:
            cat = await agent_svc.call("GET", "/catalog", user)
            skill = next((r["name"] for r in cat["reports"] if r["name"] == "tong-hop-bao-cao-chung"),
                         cat["reports"][0]["name"] if cat["reports"] else "")
            t = await _create_task(user, "tong_hop", {"skill": skill, "upload_ids": attachments, "params": {}},
                                   conversation_id, title=question[:200] if len(question) > 10 else "")
        except (ServiceError, IndexError, KeyError) as e:
            yield steps.done("tim", str(e), status="loi")
            yield ev("final", answer=f"Không tạo được tác vụ tổng hợp: {e}", verify={"ok": False}, warnings=[str(e)])
            return
        yield steps.done("tim", f"{len(attachments)} báo cáo")
        yield ev("final", **_task_answer(t, f"Đã tạo tác vụ **tổng hợp báo cáo chung** từ {len(attachments)} báo cáo "
                                            "đính kèm. Số liệu tổng hợp do chương trình tính; mỗi ý ghi nguồn [S#]."))
        return
    r = await search_svc.call("POST", "/documents", user, json={"query": question, "filters": filters})
    yield steps.done("tim", f"{len(r['results'])} tài liệu có thể đưa vào báo cáo")
    yield ev("final", answer="Yêu cầu tổng hợp nhiều văn bản được thực hiện bằng tác vụ **Tổng hợp báo cáo** "
                             "(chọn báo cáo trong kho hoặc đính kèm tệp, chọn mẫu; số liệu do chương trình tính). "
                             "Dưới đây là các tài liệu có thể đưa vào báo cáo.",
             docs=r["results"], open_module="tong-hop", verify={"ok": True}, warnings=[])


# ---------------- Trợ lý nhiều bước (vòng lặp tác tử có giới hạn) ----------------
async def tac_tu(user: UserCtx, question: str, history: list[dict], summary: str, filters, **_) -> AsyncIterator[dict]:
    tools = [t.openai() for t in tools_for(user)]
    steps = Steps([("lap", "Lập kế hoạch, gọi công cụ"), ("tong", "Tổng hợp câu trả lời")])
    yield steps.plan()
    yield steps.start("lap")
    msgs = [{"role": "system", "content": prompt("chinh-sach") + "\n\n" + prompt("tac-tu")},
            *[{"role": m["role"], "content": m["content"]} for m in history[-4:]],
            {"role": "user", "content": question}]
    sources: list[dict] = []
    t0 = time.monotonic()
    for step in range(S.agent_max_steps):
        yield ev("status", text=f"Bước {step + 1}: đang lập kế hoạch…")
        if time.monotonic() - t0 > S.agent_timeout_s:
            yield ev("step", id=f"t{step}", name="Hết thời gian cho phép, dừng vòng lặp", status="bo_qua")
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
            yield steps.done("lap", f"{step} lượt gọi công cụ, {len(sources)} nguồn")
            yield steps.start("tong")
            final, rep = verify_a(msg.get("content") or "", sources, strict=S.verify_strict_a)
            yield steps.done("tong")
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
            yield ev("step", id=f"t{step + 1}_{name}", name=f"Gọi công cụ {name}", status="xong",
                     detail=f"{len(res) if isinstance(res, list) else 1} kết quả · "
                            + json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False)[:120])
            msgs.append({"role": "tool", "tool_call_id": c.get("id", name),
                         "content": json.dumps(res, ensure_ascii=False)[:6000]})
    final_text = REFUSAL if not sources else "\n\n".join(format_source(i + 1, s) for i, s in enumerate(sources[:3]))
    yield ev("final", answer=("Đã đạt giới hạn số bước. " + (REFUSAL if not sources else "Các căn cứ thu thập được:\n\n"
                                                            + final_text)),
             sources=[_public_source(i + 1, s) for i, s in enumerate(sources)], verify={"ok": False},
             warnings=["Vòng lặp tác tử dừng do giới hạn."])


async def tra_cuu(user: UserCtx, question: str, history: list[dict], summary: str, filters: dict,
                  **_) -> AsyncIterator[dict]:
    async for e in luong_a(user, question, history, summary, filters, allow_clarify=not _.get("clarified")):
        yield e


PIPELINES = {"tra_cuu": tra_cuu, "gop_y": gop_y, "chinh_xac": luong_b, "ho_tro": ho_tro, "tim_tai_lieu": tim_tai_lieu,
             "chao_hoi": chao_hoi, "tong_hop": tong_hop, "phan_tich": phan_tich, "soan_thao": soan_thao,
             "tac_tu": tac_tu}
