"""summary-svc – tổng hợp nhiều văn bản theo mẫu báo cáo (kỹ năng Markdown), xuất DOCX."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from aicommon.app import create_app
from aicommon.audit import emit
from aicommon.config import get_settings
from aicommon.db import init_db, session
from aicommon.resources import list_skills, skill_template
from aicommon.security import UserCtx, current_user

from .models import SummaryJob

app = create_app("summary")
S = get_settings()


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/templates")
def templates(user: UserCtx = Depends(current_user)):
    return [{"name": s["name"], "description": s["meta"].get("description", ""), "template": skill_template(s),
             "params": s["meta"].get("params", [])} for s in list_skills() if s["meta"].get("loai") == "tong_hop"]


class CreateJob(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    skill: str
    doc_ids: list[str] = Field(min_length=1, max_length=50)
    params: dict = Field(default_factory=dict)


def _out(j: SummaryJob, full=False):
    d = {"id": j.id, "title": j.title, "skill": j.skill, "doc_ids": j.doc_ids, "params": j.params, "status": j.status,
         "progress": j.progress, "warnings": j.warnings, "error": j.error, "created_at": j.created_at,
         "updated_at": j.updated_at}
    if full:
        d.update(result=j.result, table=j.table, sources=j.sources)
    return d


@app.post("/jobs")
def create(req: CreateJob, user: UserCtx = Depends(current_user)):
    if req.skill not in {s["name"] for s in list_skills()}:
        raise HTTPException(400, "Kỹ năng (mẫu báo cáo) không tồn tại")
    with session() as s:
        j = SummaryJob(title=req.title, skill=req.skill, doc_ids=req.doc_ids, params=req.params, owner_sub=user.sub,
                       owner=user.model_dump())
        s.add(j)
        s.flush()
        jid = j.id
    from .worker import run_task
    run_task.delay(jid)
    emit(user.username, "summary.create", jid, {"skill": req.skill, "doc_ids": req.doc_ids})
    return {"id": jid}


def _own(s, jid: str, user: UserCtx) -> SummaryJob:
    j = s.get(SummaryJob, jid)
    if not j or j.owner_sub != user.sub:
        raise HTTPException(404, "Không tìm thấy tác vụ tổng hợp")
    return j


@app.get("/jobs")
def jobs(user: UserCtx = Depends(current_user)):
    with session() as s:
        return [_out(j) for j in s.scalars(select(SummaryJob).where(SummaryJob.owner_sub == user.sub)
                                           .order_by(SummaryJob.created_at.desc()).limit(100))]


@app.get("/jobs/{jid}")
def job(jid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        return _out(_own(s, jid, user), full=True)


class Edit(BaseModel):
    result: str


@app.put("/jobs/{jid}/result")
def edit(jid: str, req: Edit, user: UserCtx = Depends(current_user)):
    with session() as s:
        j = _own(s, jid, user)
        j.result = req.result
    return {"ok": True}


@app.delete("/jobs/{jid}")
def remove(jid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        s.delete(_own(s, jid, user))
    return {"deleted": jid}


@app.get("/jobs/{jid}/docx")
def docx(jid: str, user: UserCtx = Depends(current_user)):
    """Xuất DOCX bằng pandoc; dùng tệp mẫu thể thức skills/reference.docx nếu có."""
    with session() as s:
        j = _own(s, jid, user)
        md, title = j.result, j.title
    if not md:
        raise HTTPException(409, "Báo cáo chưa có nội dung")
    tmp = Path(tempfile.mkdtemp())
    src, out = tmp / "bao-cao.md", tmp / "bao-cao.docx"
    src.write_text(md, encoding="utf-8")
    cmd = ["pandoc", str(src), "-f", "gfm", "-o", str(out), "--metadata", f"title={title}"]
    ref = Path(S.skills_dir) / "reference.docx"
    if ref.exists():
        cmd += ["--reference-doc", str(ref)]
    if not shutil.which("pandoc"):
        raise HTTPException(501, "Máy chủ chưa cài pandoc – không xuất được DOCX")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if r.returncode != 0:
        raise HTTPException(500, f"Lỗi xuất DOCX: {r.stderr[:300]}")
    emit(user.username, "summary.export", jid, {})
    return FileResponse(out, filename=f"{title[:80]}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
