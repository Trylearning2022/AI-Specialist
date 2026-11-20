"""exact-svc – Luồng B: tra cứu chính xác trên kho Markdown chuẩn (không dùng vector)."""
from fastapi import Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from aicommon.app import create_app
from aicommon.audit import emit
from aicommon.config import get_settings
from aicommon.markdown import parse_sections, split_frontmatter
from aicommon.security import UserCtx, can_access, current_user, require, require_service

from .kb import DOC_DIR, KB

app = create_app("exact")
S = get_settings()
kb = KB(S.kb_dir)


@app.on_event("startup")
def _startup():
    kb.index.init()
    kb.load()  # chỉ dựng lại chỉ mục khi commit của kho khác commit đã lập chỉ mục


@app.middleware("http")
async def _fresh(request, call_next):
    # nhiều tiến trình dùng chung kho Git: nạp lại bộ nhớ nếu tiến trình khác vừa ghi commit mới
    if request.url.path not in ("/health", "/metrics"):
        kb.refresh_if_changed()
    return await call_next(request)


def _visible(user: UserCtx) -> set[str]:
    return {d.doc_id for d in kb.docs.values()
            if can_access(user, kb.doc_summary(d)["do_mat"], kb.doc_summary(d)["don_vi"])}


def _doc(doc_id: str, user: UserCtx):
    d = kb.docs.get(doc_id)
    if not d or doc_id not in _visible(user):
        raise HTTPException(404, "Không tìm thấy văn bản hoặc không có quyền truy cập")
    return d


@app.get("/catalog")
def catalog(user: UserCtx = Depends(current_user)):
    vis = _visible(user)
    return {"commit": kb.commit, "docs": [kb.doc_summary(d) for d in kb.docs.values() if d.doc_id in vis]}


@app.get("/docs/{doc_id}")
def doc(doc_id: str, user: UserCtx = Depends(current_user)):
    d = _doc(doc_id, user)
    return {**kb.doc_summary(d), "commit": kb.commit, "toc": kb.toc(d)}


@app.get("/docs/{doc_id}/raw", response_class=PlainTextResponse)
def raw(doc_id: str, user: UserCtx = Depends(current_user)):
    return "".join(_doc(doc_id, user).lines)


@app.get("/docs/{doc_id}/versions")
def versions(doc_id: str, user: UserCtx = Depends(current_user)):
    return {"versions": kb.versions(_doc(doc_id, user))}


@app.get("/docs/{doc_id}/diff", response_class=PlainTextResponse)
def diff(doc_id: str, a: str, b: str, user: UserCtx = Depends(current_user)):
    try:
        return kb.diff(_doc(doc_id, user), a, b)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/sections/{section_id}")
def section(section_id: str, user: UserCtx = Depends(current_user)):
    sec = kb.section(section_id)
    if not sec or sec["doc_id"] not in _visible(user):
        raise HTTPException(404, "Không tìm thấy mục hoặc không có quyền truy cập")
    emit(user.username, "exact.section", section_id, {"commit": kb.commit})
    return sec


class Query(BaseModel):
    query: str
    limit: int = 10
    doc_ids: list[str] | None = None


@app.post("/search")
def search(q: Query, user: UserCtx = Depends(current_user)):
    vis = _visible(user)
    if q.doc_ids:
        vis &= set(q.doc_ids)
    return {"commit": kb.commit, "results": kb.search(q.query, q.limit, vis)}


@app.post("/resolve")
def resolve(q: Query, user: UserCtx = Depends(current_user)):
    vis = _visible(user)
    return {"section_ids": [s for s in kb.resolve(q.query, vis) if kb.sections[s][0].doc_id in vis]}


class TocReq(BaseModel):
    doc_ids: list[str]


@app.post("/toc-text", response_class=PlainTextResponse)
def toc_text(req: TocReq, user: UserCtx = Depends(current_user)):
    vis = _visible(user)
    return kb.toc_text([d for d in req.doc_ids if d in vis])


@app.get("/index-md", response_class=PlainTextResponse)
def index_md(user: UserCtx = Depends(current_user)):
    return kb.index_md()


class CommitReq(BaseModel):
    doc_id: str
    content: str
    message: str
    author: str
    author_email: str = ""
    delete: bool = False


@app.post("/kb/commit")
def commit(req: CommitReq, user: UserCtx = Depends(require("reviewer", "admin")),
           _svc: str = Depends(require_service("ingest"))):
    """Ghi văn bản chuẩn vào kho (được gọi từ ingest-svc sau khi duyệt đủ hai cấp)."""
    if not req.delete:
        meta, body, _ = split_frontmatter(req.content)
        missing = [k for k in ("id", "so_hieu", "ten", "trang_thai", "nguoi_duyet") if not meta.get(k)]
        if missing:
            raise HTTPException(422, f"Frontmatter thiếu trường bắt buộc: {', '.join(missing)}")
        if str(meta["id"]) != req.doc_id:
            raise HTTPException(422, "Mã văn bản trong frontmatter không khớp")
        secs, _ = parse_sections(req.doc_id, req.content)
        ids = [s.id for s in secs if s.explicit]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "Trùng mã định danh mục trong văn bản")
    rel = f"{DOC_DIR}/{req.doc_id}.md"
    try:
        c = kb.commit_file(rel, req.content, req.message, req.author, req.author_email or f"{req.author}@noibo.local",
                           delete=req.delete)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if S.kb_git_remote:
        kb.push(S.kb_git_remote)
    emit(user.username, "exact.commit", req.doc_id, {"commit": c, "delete": req.delete})
    return {"commit": c, "file": rel}


@app.post("/reload")
def reload(force: bool = False, user: UserCtx = Depends(require("admin"))):
    """Nạp lại kho; force=true: dựng lại toàn bộ chỉ mục PostgreSQL."""
    kb.load(force_index=force)
    return {"commit": kb.commit, "docs": len(kb.docs), "indexed_commit": kb.index.indexed_commit(),
            "tim_gan_dung": kb.index.trgm}
