"""orchestrator – lớp điều phối (harness): định tuyến, lắp ráp ngữ cảnh, gọi luồng xử lý,
kiểm chứng đầu ra, lưu hội thoại, phản hồi người dùng, danh mục công cụ (API + MCP)."""
import contextlib
import json
import logging
import os
import time

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from aicommon.app import create_app
from aicommon.audit import emit
from aicommon.guard import check as guard_check
from aicommon.priority import interactive
from aicommon.telemetry import record
from aicommon.config import get_settings
from aicommon.db import init_db, session
from aicommon.llm import LLMError
from aicommon.resources import list_skills, prompt
from aicommon.security import UserCtx, current_user, require, verify_user
from aicommon.text import estimate_tokens

from . import clarify
from .models import Conversation, Feedback, Message
from .pipelines import PIPELINES, Steps, ev, interpret, llm, route
from .verifier import verify_b
from .tools import REGISTRY, run_tool, tools_for

log = logging.getLogger("orchestrator")
S = get_settings()
MODES = ["tu_dong", *PIPELINES.keys()]
ROUTE_LABEL = {"tra_cuu": "Tra cứu tài liệu", "chinh_xac": "Tra cứu chính xác", "ho_tro": "Hỗ trợ kỹ thuật",
               "tim_tai_lieu": "Tìm tài liệu", "chao_hoi": "Trò chuyện", "tong_hop": "Tổng hợp báo cáo",
               "phan_tich": "Phân tích văn bản", "soan_thao": "Soạn văn bản tham mưu", "tac_tu": "Trợ lý nhiều bước",
               "bao_ve": "Bảo vệ an toàn thông tin", "lam_ro": "Làm rõ câu hỏi"}

# ---------- Máy chủ MCP (công bố cùng danh mục công cụ) ----------
mcp_server = None
if os.getenv("ENABLE_MCP", "true").lower() == "true":
    try:
        from mcp.server.mcpserver import Context, MCPServer

        mcp_server = MCPServer(name="ai-local-tools", instructions="Công cụ tra cứu tài liệu nội bộ (chỉ đọc).")

        def _mk(tool_name: str):
            async def handler(ctx: Context, args: dict | None = None) -> str:
                h = {k.lower(): v for k, v in (ctx.headers or {}).items()}
                user = verify_user(h.get("x-user"), h.get("x-user-ts"), h.get("x-internal-sig"))
                res = await run_tool(user, tool_name, args or {})
                return json.dumps(res, ensure_ascii=False)
            handler.__name__ = tool_name
            return handler

        for _t in REGISTRY.values():
            mcp_server.add_tool(_mk(_t.name), name=_t.name,
                                description=_t.description + " Tham số truyền trong 'args': "
                                + json.dumps(_t.parameters, ensure_ascii=False))
    except Exception as e:  # MCP là tùy chọn, không làm hỏng dịch vụ chính
        log.warning("Không khởi tạo được máy chủ MCP: %s", e)
        mcp_server = None


@contextlib.asynccontextmanager
async def lifespan(app):
    init_db()
    if mcp_server is not None:
        async with mcp_server.session_manager.run():
            yield
    else:
        yield


app = create_app("orchestrator", lifespan=lifespan)
if mcp_server is not None:
    app.mount("/mcp", mcp_server.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                                      json_response=True))


# ---------- Hội thoại ----------
class ClarifyAnswer(BaseModel):
    original: str = Field(min_length=1, max_length=8000)  # câu hỏi gốc đã được hỏi lại
    answer: str = Field("", max_length=1000)               # lựa chọn / nội dung người dùng bổ sung


class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=60000)  # văn bản dán dài (phân tích) tới ~20 trang
    conversation_id: str | None = None
    mode: str = "tu_dong"
    filters: dict = Field(default_factory=dict)
    stream: bool = True
    attachments: list[str] = Field(default_factory=list, max_length=20)  # mã tệp đã tải lên agent-svc /uploads
    clarify: ClarifyAnswer | None = None


def _own_conv(s, cid: str, user: UserCtx) -> Conversation:
    c = s.get(Conversation, cid)
    if not c or c.user_sub != user.sub:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return c


async def _update_memory(cid: str):
    """Tóm tắt các lượt cũ khi lịch sử vượt ngân sách (bộ nhớ phiên, không chia sẻ giữa người dùng)."""
    with session() as s:
        c = s.get(Conversation, cid)
        msgs = s.scalars(select(Message).where(Message.conversation_id == cid, Message.id > c.summarized_upto)
                         .order_by(Message.id)).all()
        total = sum(estimate_tokens(m.content) for m in msgs)
        if total <= S.ctx_budget_memory * 2 or len(msgs) <= 4:
            return
        old, summary, upto = msgs[:-4], c.summary, msgs[-5].id
    text = (f"TÓM TẮT CŨ: {summary}\n\n" if summary else "") + "\n".join(
        f"{'Người dùng' if m.role == 'user' else 'Trợ lý'}: {m.content[:800]}" for m in old)
    try:
        r = await llm.chat_json([{"role": "system", "content": prompt("tom-tat-hoi-thoai")},
                                 {"role": "user", "content": text}],
                                schema={"type": "object", "properties": {"tom_tat": {"type": "string"}},
                                        "required": ["tom_tat"]},
                                model=S.model_small, max_tokens=300, task="tom-tat-hoi-thoai")
    except LLMError:
        return
    with session() as s:
        c = s.get(Conversation, cid)
        c.summary, c.summarized_upto = str(r.get("tom_tat", ""))[:2000], upto


@app.post("/chat")
async def chat(req: ChatReq, user: UserCtx = Depends(current_user)):
    """Một lượt hỏi đáp:  bảo vệ ATTT → (ghép câu trả lời làm rõ) → định tuyến → hỏi lại nếu chưa rõ → luồng xử lý
    → lưu → số liệu giám sát. Phát SSE: start, plan, step, status, meta, delta, final."""
    if req.mode not in MODES:
        raise HTTPException(400, f"Chế độ không hợp lệ. Hợp lệ: {', '.join(MODES)}")
    if req.mode == "tac_tu" and not os.getenv("ENABLE_AGENT", "true").lower() == "true":
        raise HTTPException(403, "Chế độ trợ lý nhiều bước đang tắt")
    if len(req.message) > 8000 and not req.attachments and req.mode not in ("tu_dong", "phan_tich"):
        raise HTTPException(422, "Câu hỏi quá dài (tối đa 8.000 ký tự); văn bản dài hãy dùng chức năng phân tích")
    hit = guard_check(req.message)
    question = req.message
    clarified = req.clarify is not None
    if clarified:
        question = clarify.merge(req.clarify.original, req.clarify.answer or req.message)
    stored = req.message if not hit else f"[Nội dung đã được ẩn – {hit.kind}]"  # không lưu bí mật vào CSDL
    with session() as s:
        if req.conversation_id:
            conv = _own_conv(s, req.conversation_id, user)
        else:
            conv = Conversation(user_sub=user.sub, title=(stored if not hit else "Câu hỏi bị chặn")[:120])
            s.add(conv)
            s.flush()
        cid, summary = conv.id, conv.summary
        hist = s.scalars(select(Message).where(Message.conversation_id == cid, Message.id > conv.summarized_upto)
                         .order_by(Message.id.desc()).limit(8)).all()
        history = [{"role": m.role, "content": m.content} for m in reversed(hist)]
        s.add(Message(conversation_id=cid, role="user", content=stored[:20000],
                      data={"attachments": req.attachments} if req.attachments else {}))

    if hit:
        r, pipe = "bao_ve", None
        emit(user.username, "guard.block", cid, {"kind": hit.kind})
        log.warning("Chặn câu hỏi (%s) của %s", hit.kind, user.username, extra={"event": "guard.block"})
    else:
        r = await route(question, req.mode, len(req.attachments))
        pipe = PIPELINES[r]
    pre = None if (hit or clarified or req.mode != "tu_dong") else clarify.before_search(question, r, history)

    async def run():
        final, t0, first = None, time.perf_counter(), None
        trace: dict = {"steps": []}
        yield {"event": "start", "data": {"conversation_id": cid, "route": r if not pre else "lam_ro",
                                          "route_label": ROUTE_LABEL.get(r if not pre else "lam_ro", r)}}
        try:
            if hit:
                final = {"answer": hit.message, "verify": {"ok": True}, "warnings": [], "guard": hit.kind}
                yield ev("delta", text=hit.message)
            elif pre:
                st = Steps([("hieu", "Phân tích câu hỏi")])
                for e in (st.plan(), st.done("hieu", "Câu hỏi cần làm rõ thêm")):
                    trace["steps"].append({**e["data"]} if e["event"] == "step" else None)
                    yield e
                final = {"answer": pre["question"], "clarify": {**pre, "original": question}, "verify": {"ok": True},
                         "warnings": []}
            else:
                async with interactive():  # tác vụ nền nhường máy chủ mô hình cho lượt hỏi đáp này
                    async for e in pipe(user, question, history, summary, req.filters, attachments=req.attachments,
                                        conversation_id=cid, clarified=clarified):
                        if e["event"] == "final":
                            final = e["data"]
                            continue
                        if e["event"] == "delta" and first is None:
                            first = time.perf_counter() - t0
                        if e["event"] == "plan":
                            trace = {"steps": [dict(x, status="cho") for x in e["data"]["steps"]]}
                        elif e["event"] == "step":
                            _trace_step(trace, e["data"])
                        yield e
        except Exception as ex:
            log.exception("Lỗi luồng %s", r)
            final = {"answer": f"Đã xảy ra lỗi khi xử lý: {ex}", "verify": {"ok": False}, "warnings": [str(ex)]}
        final = final or {"answer": "", "verify": {"ok": False}, "warnings": ["Không có kết quả"]}
        trace["steps"] = [x for x in trace.get("steps", []) if x]
        total = time.perf_counter() - t0
        rr = "lam_ro" if (pre or final.get("clarify")) else r
        with session() as s:
            m = Message(conversation_id=cid, role="assistant", content=final.get("answer", ""), route=rr,
                        data={**{k: v for k, v in final.items() if k != "answer"}, "trace": trace,
                              "timing": {"total_ms": round(total * 1000), "first_ms": round(first * 1000) if first else None}},
                        verified=bool(final.get("verify", {}).get("ok", True)))
            s.add(m)
            s.flush()
            mid = m.id
        emit(user.username, "chat.answer", cid, {
            "route": rr, "message_id": mid, "question": stored[:2000],
            "sources": [x.get("section_id") for x in final.get("sources", []) or []],
            "exact": [(b["section_id"], b.get("commit")) for b in final.get("exact_blocks", []) or []],
            "verified": final.get("verify", {}).get("ok"), "task": (final.get("task") or {}).get("id")})
        v = final.get("verify") or {}
        record("tel:chat", user=user.username, route=rr, ms=round(total * 1000),
               first_ms=round(first * 1000) if first else None, verified=bool(v.get("ok", True)),
               refused="Không tìm thấy căn cứ" in (final.get("answer") or ""), clarify=bool(final.get("clarify")),
               unsupported=len(v.get("unsupported") or []), sources=len(final.get("sources") or []),
               guard=final.get("guard", ""), task=(final.get("task") or {}).get("kind", ""))
        yield {"event": "final", "data": {**final, "message_id": mid, "conversation_id": cid, "route": rr,
                                          "route_label": ROUTE_LABEL.get(rr, rr), "trace": trace,
                                          "timing": {"total_ms": round(total * 1000)}}}
        if not hit:
            await _update_memory(cid)

    if not req.stream:
        meta, out = {}, {}
        async for e in run():
            if e["event"] == "meta":
                meta.update(e["data"])  # ví dụ: truy vấn đã viết lại, nguồn
            elif e["event"] == "final":
                out = e["data"]
        return {**meta, **out}

    async def sse():
        async for e in run():
            yield f"event: {e['event']}\ndata: {json.dumps(e['data'], ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _trace_step(trace: dict, d: dict):
    """Lưu vết các bước (để xem lại tiến trình khi mở lại hội thoại)."""
    for x in trace["steps"]:
        if x and x.get("id") == d.get("id"):
            x.update({k: v for k, v in d.items() if v not in (None, "")})
            return
    trace["steps"].append(dict(d))


@app.get("/conversations")
def conversations(user: UserCtx = Depends(current_user)):
    with session() as s:
        rows = s.scalars(select(Conversation).where(Conversation.user_sub == user.sub)
                         .order_by(Conversation.updated_at.desc()).limit(100)).all()
        return [{"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in rows]


@app.get("/conversations/{cid}")
def conversation(cid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        c = _own_conv(s, cid, user)
        msgs = s.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.id)).all()
        return {"id": c.id, "title": c.title, "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "route": m.route, "data": m.data,
             "verified": m.verified, "created_at": m.created_at} for m in msgs]}


@app.delete("/conversations/{cid}")
def delete_conversation(cid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        _own_conv(s, cid, user)
        s.execute(delete(Message).where(Message.conversation_id == cid))
        s.execute(delete(Conversation).where(Conversation.id == cid))
    return {"deleted": True}


class RenameReq(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@app.patch("/conversations/{cid}")
def rename_conversation(cid: str, req: RenameReq, user: UserCtx = Depends(current_user)):
    with session() as s:
        c = _own_conv(s, cid, user)
        c.title = req.title.strip()
    return {"ok": True}


@app.post("/messages/{mid}/interpret")
async def interpret_message(mid: int, user: UserCtx = Depends(current_user)):
    """Diễn giải theo yêu cầu cho câu trả lời Luồng B (nguyên văn): mô hình chỉ chạy khi người dùng cần."""
    with session() as s:
        m = s.get(Message, mid)
        if not m or m.role != "assistant" or s.get(Conversation, m.conversation_id).user_sub != user.sub:
            raise HTTPException(404, "Không tìm thấy câu trả lời")
        data = dict(m.data or {})
        blocks = data.get("exact_blocks") or []
        if not blocks:
            raise HTTPException(400, "Câu trả lời không có nội dung nguyên văn để diễn giải")
        if data.get("interpretation"):
            return {"interpretation": data["interpretation"], "warnings": [], "ok": True}
        q = s.scalars(select(Message).where(Message.conversation_id == m.conversation_id, Message.id < m.id,
                                            Message.role == "user").order_by(Message.id.desc()).limit(1)).first()
        question = q.content if q else ""
    verbatim = "\n\n".join(b["text"] for b in blocks)
    try:
        dg = await interpret(verbatim, blocks, question)
    except LLMError as e:
        raise HTTPException(503, f"Máy chủ mô hình không khả dụng: {e}")
    _, dg, rep = verify_b("", dg, verbatim)
    with session() as s:
        m = s.get(Message, mid)
        m.data = {**(m.data or {}), "interpretation": dg, "can_interpret": False,
                  "interpret_warnings": rep.warnings}
    emit(user.username, "chat.interpret", str(mid), {"ok": rep.ok})
    return {"interpretation": dg, "warnings": rep.warnings, "ok": rep.ok}


# ---------- Phản hồi người dùng (vòng “bánh cóc”) ----------
class FeedbackReq(BaseModel):
    message_id: int
    rating: int = Field(ge=-1, le=1)
    comment: str = ""


@app.post("/feedback")
def feedback(req: FeedbackReq, user: UserCtx = Depends(current_user)):
    with session() as s:
        m = s.get(Message, req.message_id)
        if not m or s.get(Conversation, m.conversation_id).user_sub != user.sub:
            raise HTTPException(404, "Không tìm thấy câu trả lời")
        s.add(Feedback(message_id=m.id, user_sub=user.sub, username=user.username, rating=req.rating,
                       comment=req.comment[:2000]))
    emit(user.username, "chat.feedback", str(req.message_id), {"rating": req.rating})
    return {"ok": True}


@app.get("/feedback")
def list_feedback(status: str = "moi", user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        rows = s.execute(select(Feedback, Message).join(Message, Feedback.message_id == Message.id)
                         .where(Feedback.status == status).order_by(Feedback.id.desc()).limit(200)).all()
        out = []
        for f, m in rows:
            q = s.scalars(select(Message).where(Message.conversation_id == m.conversation_id, Message.id < m.id,
                                                Message.role == "user").order_by(Message.id.desc()).limit(1)).first()
            out.append({"id": f.id, "rating": f.rating, "comment": f.comment, "username": f.username,
                        "created_at": f.created_at, "question": q.content if q else "", "answer": m.content,
                        "route": m.route, "data": m.data, "status": f.status, "resolution": f.resolution})
        return out


class ResolveReq(BaseModel):
    resolution: str


@app.post("/feedback/{fid}/resolve")
def resolve_feedback(fid: int, req: ResolveReq, user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        f = s.get(Feedback, fid)
        if not f:
            raise HTTPException(404, "Không tìm thấy phản hồi")
        f.status, f.resolution = "da_xu_ly", req.resolution
    emit(user.username, "feedback.resolve", str(fid), {"resolution": req.resolution[:500]})
    return {"ok": True}


@app.get("/stats")
def stats(user: UserCtx = Depends(require("admin", "reviewer"))):
    with session() as s:
        by_route = dict(s.execute(select(Message.route, func.count()).where(Message.role == "assistant")
                                  .group_by(Message.route)).all())
        unverified = s.scalar(select(func.count()).select_from(Message).where(Message.role == "assistant",
                                                                               Message.verified.is_(False)))
        neg = s.scalar(select(func.count()).select_from(Feedback).where(Feedback.rating < 0))
        pos = s.scalar(select(func.count()).select_from(Feedback).where(Feedback.rating > 0))
        refusals = s.scalar(select(func.count()).select_from(Message).where(
            Message.role == "assistant", Message.content.like("%Không tìm thấy căn cứ%")))
    return {"Câu trả lời theo luồng": {ROUTE_LABEL.get(k, k): v for k, v in by_route.items()},
            "Câu trả lời chưa đạt kiểm chứng": unverified, "Phản hồi “Đúng”": pos, "Phản hồi “Sai”": neg,
            "Câu trả lời “không tìm thấy căn cứ”": refusals}


# ---------- Danh mục công cụ, kỹ năng ----------
@app.get("/tools")
def list_tools(user: UserCtx = Depends(current_user)):
    return [{"name": t.name, "description": t.description, "parameters": t.parameters, "writes": t.writes}
            for t in tools_for(user)]


@app.post("/tools/{name}")
async def call_tool(name: str, args: dict, user: UserCtx = Depends(current_user)):
    try:
        res = await run_tool(user, name, args)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    emit(user.username, "tool.call", name, {"args": args})
    return {"result": res}


@app.get("/skills")
def skills(user: UserCtx = Depends(current_user)):
    return [{"name": s["name"], "description": s["meta"].get("description", ""),
             "tools": s["meta"].get("tools", []), "body": s["body"]} for s in list_skills()]


@app.get("/models")
async def models(user: UserCtx = Depends(require("admin"))):
    try:
        return {"models": await llm.models()}
    except Exception as e:
        raise HTTPException(502, f"Không lấy được danh sách mô hình: {e}")
