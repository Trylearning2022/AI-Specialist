"""orchestrator – lớp điều phối (harness): định tuyến, lắp ráp ngữ cảnh, gọi luồng xử lý,
kiểm chứng đầu ra, lưu hội thoại, phản hồi người dùng, danh mục công cụ (API + MCP)."""
import contextlib
import json
import logging
import os

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from aicommon.app import create_app
from aicommon.audit import emit
from aicommon.config import get_settings
from aicommon.db import init_db, session
from aicommon.llm import LLMError
from aicommon.resources import list_skills, prompt
from aicommon.security import UserCtx, current_user, require, verify_user
from aicommon.text import estimate_tokens

from .models import Conversation, Feedback, Message
from .pipelines import PIPELINES, interpret, llm, route
from .verifier import verify_b
from .tools import REGISTRY, run_tool, tools_for

log = logging.getLogger("orchestrator")
S = get_settings()
MODES = ["tu_dong", *PIPELINES.keys()]
ROUTE_LABEL = {"tra_cuu": "Tra cứu tài liệu", "chinh_xac": "Tra cứu chính xác", "ho_tro": "Hỗ trợ kỹ thuật",
               "tim_tai_lieu": "Tìm tài liệu", "chao_hoi": "Trò chuyện", "tong_hop": "Tổng hợp",
               "tac_tu": "Trợ lý nhiều bước"}

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
class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    mode: str = "tu_dong"
    filters: dict = Field(default_factory=dict)
    stream: bool = True


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
    if req.mode not in MODES:
        raise HTTPException(400, f"Chế độ không hợp lệ. Hợp lệ: {', '.join(MODES)}")
    if req.mode == "tac_tu" and not os.getenv("ENABLE_AGENT", "true").lower() == "true":
        raise HTTPException(403, "Chế độ trợ lý nhiều bước đang tắt")
    with session() as s:
        if req.conversation_id:
            conv = _own_conv(s, req.conversation_id, user)
        else:
            conv = Conversation(user_sub=user.sub, title=req.message[:120])
            s.add(conv)
            s.flush()
        cid, summary = conv.id, conv.summary
        hist = s.scalars(select(Message).where(Message.conversation_id == cid, Message.id > conv.summarized_upto)
                         .order_by(Message.id.desc()).limit(8)).all()
        history = [{"role": m.role, "content": m.content} for m in reversed(hist)]
        um = Message(conversation_id=cid, role="user", content=req.message)
        s.add(um)

    r = await route(req.message, req.mode)
    pipe = PIPELINES[r]

    async def run():
        final = None
        yield {"event": "start", "data": {"conversation_id": cid, "route": r, "route_label": ROUTE_LABEL.get(r, r)}}
        try:
            async for e in pipe(user, req.message, history, summary, req.filters):
                if e["event"] == "final":
                    final = e["data"]
                    continue
                yield e
        except Exception as ex:
            log.exception("Lỗi luồng %s", r)
            final = {"answer": f"Đã xảy ra lỗi khi xử lý: {ex}", "verify": {"ok": False}, "warnings": [str(ex)]}
        final = final or {"answer": "", "verify": {"ok": False}, "warnings": ["Không có kết quả"]}
        with session() as s:
            m = Message(conversation_id=cid, role="assistant", content=final.get("answer", ""), route=r,
                        data={k: v for k, v in final.items() if k != "answer"},
                        verified=bool(final.get("verify", {}).get("ok", True)))
            s.add(m)
            s.flush()
            mid = m.id
        emit(user.username, "chat.answer", cid, {
            "route": r, "message_id": mid, "question": req.message[:2000],
            "sources": [x.get("section_id") for x in final.get("sources", []) or []],
            "exact": [(b["section_id"], b.get("commit")) for b in final.get("exact_blocks", []) or []],
            "verified": final.get("verify", {}).get("ok")})
        yield {"event": "final", "data": {**final, "message_id": mid, "conversation_id": cid, "route": r,
                                          "route_label": ROUTE_LABEL.get(r, r)}}
        await _update_memory(cid)

    if not req.stream:
        meta, out = {}, {}
        async for e in run():
            if e["event"] == "meta":
                meta.update(e["data"])  # ví dụ: cây xử lý sự cố được gợi ý, truy vấn đã viết lại
            elif e["event"] == "final":
                out = e["data"]
        return {**meta, **out}

    async def sse():
        async for e in run():
            yield f"event: {e['event']}\ndata: {json.dumps(e['data'], ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
