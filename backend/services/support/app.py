"""support-svc – hỗ trợ kỹ thuật: cây xử lý sự cố (thực thi tất định), phiếu yêu cầu, đề xuất tri thức."""
import logging
import uuid
from pathlib import Path

import httpx
import yaml
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from aicommon.app import create_app
from aicommon.audit import emit
from aicommon.config import get_settings
from aicommon.db import Base, init_db, session, utcnow
from aicommon.internal import AsyncSvc, ServiceError, as_http
from aicommon.llm import AsyncLLM, LLMError
from aicommon.resources import prompt
from aicommon.security import UserCtx, current_user, require
from aicommon.text import nfc, unaccent

log = logging.getLogger("support")
app = create_app("support")
S = get_settings()
llm = AsyncLLM()
ingest = AsyncSvc(S.ingest_url)


class TreeSession(Base):
    __tablename__ = "sup_session"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tree_id: Mapped[str] = mapped_column(String(100))
    user_sub: Mapped[str] = mapped_column(String(128), index=True)
    current: Mapped[str] = mapped_column(String(100))
    path: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="dang_xu_ly")  # dang_xu_ly | xong | tao_phieu
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)


class Ticket(Base):
    __tablename__ = "sup_ticket"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex[:10].upper())
    user_sub: Mapped[str] = mapped_column(String(128), index=True)
    username: Mapped[str] = mapped_column(String(128))
    units: Mapped[list] = mapped_column(JSON, default=list)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    tree_path: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="moi")  # moi | dang_xu_ly | da_xong
    assignee: Mapped[str] = mapped_column(String(128), default="")
    result: Mapped[str] = mapped_column(Text, default="")
    kb_job: Mapped[str] = mapped_column(String(32), default="")
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


@app.on_event("startup")
def _startup():
    init_db()


# ---------------- Cây xử lý sự cố ----------------
def load_trees() -> dict[str, dict]:
    out = {}
    root = Path(S.support_dir) / "trees"
    for p in sorted(root.glob("*.y*ml")) if root.exists() else []:
        try:
            t = yaml.safe_load(nfc(p.read_text(encoding="utf-8")))
            if t.get("bat_dau") not in t.get("buoc", {}):
                raise ValueError("bước bắt đầu không tồn tại")
            for sid, st in t["buoc"].items():
                for opt in st.get("lua_chon", []):
                    if opt["den"] not in t["buoc"]:
                        raise ValueError(f"bước {sid} trỏ tới bước không tồn tại {opt['den']}")
            out[t["id"]] = t
        except Exception as e:
            log.error("Cây xử lý %s không hợp lệ: %s", p.name, e)
    return out


def _step_out(tree: dict, sid: str) -> dict:
    st = tree["buoc"][sid]
    return {"id": sid, "hoi": st.get("hoi", ""), "huong_dan": st.get("huong_dan", ""),
            "lua_chon": [o["nhan"] for o in st.get("lua_chon", [])], "ket_thuc": bool(st.get("ket_thuc")),
            "thong_bao": st.get("thong_bao", ""), "tao_phieu": bool(st.get("tao_phieu"))}


@app.get("/trees")
def trees(user: UserCtx = Depends(current_user)):
    return [{"id": t["id"], "ten": t["ten"], "mo_ta": t.get("mo_ta", ""), "tu_khoa": t.get("tu_khoa", [])}
            for t in load_trees().values()]


@app.get("/trees/suggest")
def suggest(q: str, user: UserCtx = Depends(current_user)):
    qn = unaccent(nfc(q)).lower()
    scored = []
    for t in load_trees().values():
        kws = [unaccent(k).lower() for k in t.get("tu_khoa", [])] + [unaccent(t["ten"]).lower()]
        score = sum(1 for k in kws if k and k in qn)
        if score:
            scored.append((score, {"id": t["id"], "ten": t["ten"], "mo_ta": t.get("mo_ta", "")}))
    return [x for _, x in sorted(scored, key=lambda z: -z[0])[:3]]


class StartReq(BaseModel):
    tree_id: str


@app.post("/sessions")
def start(req: StartReq, user: UserCtx = Depends(current_user)):
    t = load_trees().get(req.tree_id)
    if not t:
        raise HTTPException(404, "Không tìm thấy cây xử lý")
    with session() as s:
        ss = TreeSession(tree_id=t["id"], user_sub=user.sub, current=t["bat_dau"], path=[])
        s.add(ss)
        s.flush()
        sid = ss.id
    return {"session_id": sid, "tree": {"id": t["id"], "ten": t["ten"]}, "step": _step_out(t, t["bat_dau"])}


class Answer(BaseModel):
    lua_chon: int | None = None
    text: str | None = None
    mo_ta_them: str = ""


@app.post("/sessions/{sid}/answer")
async def answer(sid: str, req: Answer, user: UserCtx = Depends(current_user)):
    with session() as s:
        ss = s.get(TreeSession, sid)
        if not ss or ss.user_sub != user.sub:
            raise HTTPException(404, "Không tìm thấy phiên xử lý")
        if ss.status != "dang_xu_ly":
            raise HTTPException(409, "Phiên xử lý đã kết thúc")
        tree_id, cur, path = ss.tree_id, ss.current, list(ss.path)
    t = load_trees().get(tree_id)
    st = t["buoc"][cur]
    opts = st.get("lua_chon", [])
    idx = req.lua_chon
    if idx is None and req.text:
        # mô hình chỉ ánh xạ câu trả lời tự do vào lựa chọn có sẵn; luồng xử lý do cây quyết định
        try:
            r = await llm.chat_json(
                [{"role": "system", "content": prompt("ho-tro-chon-nhanh")},
                 {"role": "user", "content": f"BƯỚC: {st.get('hoi') or st.get('huong_dan')}\nLỰA CHỌN:\n"
                  + "\n".join(f"{i}. {o['nhan']}" for i, o in enumerate(opts)) + f"\nTRẢ LỜI: {req.text}"}],
                schema={"type": "object", "properties": {"lua_chon": {"type": "integer", "minimum": -1,
                                                                      "maximum": len(opts) - 1}},
                        "required": ["lua_chon"]}, model=S.model_small, max_tokens=30, task="ho-tro-chon")
            idx = int(r.get("lua_chon", -1))
        except (LLMError, ValueError, TypeError):
            idx = -1
        if idx < 0:
            return {"session_id": sid, "step": _step_out(t, cur), "can_lam_ro": True,
                    "thong_bao": "Chưa xác định được lựa chọn, vui lòng chọn một phương án."}
    if idx is None or not 0 <= idx < len(opts):
        raise HTTPException(400, "Lựa chọn không hợp lệ")
    nxt = opts[idx]["den"]
    path.append({"buoc": cur, "hoi": st.get("hoi") or st.get("huong_dan", ""), "chon": opts[idx]["nhan"]})
    nst = t["buoc"][nxt]
    status = "xong" if nst.get("ket_thuc") else ("tao_phieu" if nst.get("tao_phieu") else "dang_xu_ly")
    ticket = None
    if status == "tao_phieu":
        desc = "\n".join(f"- {p['hoi']} → {p['chon']}" for p in path) + (f"\n\nMô tả thêm: {req.mo_ta_them}" if req.mo_ta_them else "")
        ticket = _create_ticket(user, f"[{t['ten']}] cần hỗ trợ trực tiếp", desc, path)
    with session() as s:
        ss = s.get(TreeSession, sid)
        ss.current, ss.path, ss.status = nxt, path, status
    return {"session_id": sid, "step": _step_out(t, nxt), "status": status, "ticket": ticket}


# ---------------- Phiếu yêu cầu ----------------
def _ticket_out(tk: Ticket) -> dict:
    return {"id": tk.id, "title": tk.title, "description": tk.description, "status": tk.status, "username": tk.username,
            "assignee": tk.assignee, "result": tk.result, "kb_job": tk.kb_job, "tree_path": tk.tree_path,
            "created_at": tk.created_at, "updated_at": tk.updated_at}


def _create_ticket(user: UserCtx, title: str, desc: str, path: list | None = None) -> dict:
    with session() as s:
        tk = Ticket(user_sub=user.sub, username=user.username, units=user.units, title=title[:300],
                    description=desc, tree_path=path or [])
        s.add(tk)
        s.flush()
        out = _ticket_out(tk)
    emit(user.username, "support.ticket", out["id"], {"title": title})
    if S.ticket_webhook_url:  # tích hợp hệ thống quản lý yêu cầu nội bộ (nếu có)
        try:
            httpx.post(S.ticket_webhook_url, json=out | {"created_at": str(out["created_at"])}, timeout=10)
        except httpx.HTTPError as e:
            log.warning("Không gửi được phiếu sang hệ thống ngoài: %s", e)
    return out


class TicketReq(BaseModel):
    title: str = Field(min_length=5, max_length=300)
    description: str = Field(min_length=5)


@app.post("/tickets")
def new_ticket(req: TicketReq, user: UserCtx = Depends(current_user)):
    return _create_ticket(user, req.title, req.description)


@app.get("/tickets")
def tickets(all: bool = False, user: UserCtx = Depends(current_user)):
    with session() as s:
        q = select(Ticket).order_by(Ticket.created_at.desc()).limit(300)
        if not (all and user.has("reviewer", "admin")):
            q = q.where(Ticket.user_sub == user.sub)
        return [_ticket_out(t) for t in s.scalars(q)]


class TicketUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(moi|dang_xu_ly|da_xong)$")
    result: str | None = None
    assignee: str | None = None


@app.patch("/tickets/{tid}")
def update_ticket(tid: str, req: TicketUpdate, user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        tk = s.get(Ticket, tid)
        if not tk:
            raise HTTPException(404, "Không tìm thấy phiếu")
        for k, v in req.model_dump(exclude_none=True).items():
            setattr(tk, k, v)
        out = _ticket_out(tk)
    emit(user.username, "support.ticket_update", tid, req.model_dump(exclude_none=True))
    return out


@app.post("/tickets/{tid}/propose-kb")
async def propose_kb(tid: str, user: UserCtx = Depends(require("reviewer", "admin"))):
    """Soạn đề xuất mục tri thức từ phiếu đã xử lý; chuyển vào hàng đợi kiểm duyệt."""
    with session() as s:
        tk = s.get(Ticket, tid)
        if not tk or tk.status != "da_xong" or not tk.result:
            raise HTTPException(409, "Chỉ đề xuất tri thức từ phiếu đã xử lý xong và có kết quả")
        text = f"TIÊU ĐỀ: {tk.title}\nMÔ TẢ:\n{tk.description}\nKẾT QUẢ XỬ LÝ:\n{tk.result}"
    try:
        r = await llm.chat_json([{"role": "system", "content": prompt("de-xuat-tri-thuc")},
                                 {"role": "user", "content": text}],
                                schema={"type": "object", "properties": {"tieu_de": {"type": "string"},
                                                                         "noi_dung": {"type": "string"}},
                                        "required": ["tieu_de", "noi_dung"]},
                                model=S.model_main, max_tokens=1200, task="de-xuat-tri-thuc")
    except LLMError as e:
        raise HTTPException(502, str(e))
    md = f"# {r['tieu_de']}\n\n{r['noi_dung']}\n"
    try:
        job = await ingest.call("POST", "/jobs/from-markdown", user, json={
            "filename": f"su-co-{tid}.md", "markdown": md,
            "meta": {"loai": "su_co", "ten": r["tieu_de"], "nguon_phieu": tid}})
    except ServiceError as e:
        raise as_http(e)
    with session() as s:
        s.get(Ticket, tid).kb_job = job["id"]
    return {"job_id": job["id"], "markdown": md}
