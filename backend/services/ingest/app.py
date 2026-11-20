"""ingest-svc – thu nhận, kiểm duyệt (có con người tham gia), lưu trữ và lập chỉ mục tài liệu."""
import hashlib
from datetime import date
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from aicommon.app import create_app
from aicommon.audit import emit
from aicommon.config import get_settings
from aicommon.db import init_db, session, utcnow
from aicommon.internal import ServiceError, SyncSvc, as_http
from aicommon.markdown import dump_frontmatter, insert_ids, slugify, split_frontmatter
from aicommon.security import UserCtx, can_access, current_user, require

from .cleaning import minhash, minhash_bytes
from .models import (CHO_DUYET, CHO_DUYET_CAP_2, DA_DUYET, LOI, MOI, TU_CHOI, Document, Job)

app = create_app("ingest")
S = get_settings()
ORIG = Path(S.data_dir) / "originals"
DOCS = Path(S.data_dir) / "docs"
search_svc = SyncSvc(S.search_url)
exact_svc = SyncSvc(S.exact_url)
LOAI_PREFIX = {"quyet_dinh": "QD", "thong_tu": "TT", "nghi_dinh": "ND", "quy_dinh": "QyD", "huong_dan": "HD",
               "ke_hoach": "KH", "bao_cao": "BC", "cong_van": "CV", "to_trinh": "TTr", "bien_ban": "BB",
               "su_co": "SC", "tai_lieu_ky_thuat": "TLKT"}


@app.on_event("startup")
def _startup():
    ORIG.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    init_db()


def _enqueue(job_id: str):
    from .worker import process
    process.delay(job_id)


def _job_out(j: Job, full: bool = False) -> dict:
    d = {"id": j.id, "filename": j.filename, "kind": j.kind, "status": j.status, "uploader": j.uploader,
         "size": j.size, "meta": j.meta, "quality": j.quality, "warnings": j.warnings, "duplicates": j.duplicates,
         "target": j.target, "approvals": j.approvals, "doc_id": j.doc_id, "error": j.error,
         "reject_reason": j.reject_reason, "created_at": j.created_at, "updated_at": j.updated_at}
    if full:
        d["markdown"] = j.markdown
    return d


def _check_meta(meta: dict, user: UserCtx):
    dm = int(meta.get("do_mat", 0) or 0)
    if dm > S.system_max_clearance:
        raise HTTPException(422, "Độ mật vượt cấp độ hệ thống được phép xử lý – không được nạp")
    if dm > user.clearance:
        raise HTTPException(403, "Không được nạp tài liệu có độ mật cao hơn quyền của người dùng")


# ---------------- Tác vụ nạp ----------------
@app.post("/jobs")
async def upload(file: UploadFile = File(...), do_mat: int = Form(0), don_vi: str = Form("chung"),
                 loai: str = Form(""), user: UserCtx = Depends(current_user)):
    data = await file.read()
    if len(data) > S.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Tệp vượt quá {S.max_upload_mb} MB")
    if not data:
        raise HTTPException(400, "Tệp rỗng")
    meta = {"do_mat": do_mat, "don_vi": [u.strip() for u in don_vi.split(",") if u.strip()] or ["chung"]}
    if loai:
        meta["loai"] = loai
    _check_meta(meta, user)
    sha = hashlib.sha256(data).hexdigest()
    name = Path(file.filename or "tai-lieu").name[:200]
    with session() as s:
        dup = s.scalars(select(Document).where(Document.sha256 == sha)).first()
        job = Job(filename=name, sha256=sha, size=len(data), uploader=user.username, uploader_units=user.units,
                  meta=meta, warnings=[f"Tệp trùng hoàn toàn với tài liệu đã có: {dup.doc_id}"] if dup else [])
        s.add(job)
        s.flush()
        p = ORIG / f"{job.id}{Path(name).suffix.lower()}"
        p.write_bytes(data)
        job.original_path = str(p)
        jid = job.id
    _enqueue(jid)
    emit(user.username, "ingest.upload", jid, {"filename": name, "sha256": sha, "size": len(data)})
    return {"id": jid, "status": MOI, "sha256": sha}


class MdJob(BaseModel):
    filename: str = "de-xuat.md"
    markdown: str
    meta: dict = Field(default_factory=dict)


@app.post("/jobs/from-markdown")
def from_markdown(req: MdJob, user: UserCtx = Depends(current_user)):
    """Tạo tác vụ từ nội dung Markdown (ví dụ: đề xuất mục tri thức từ phiếu hỗ trợ)."""
    meta = {"do_mat": 0, "don_vi": ["chung"], **req.meta, "_markdown_input": True}
    _check_meta(meta, user)
    with session() as s:
        job = Job(filename=req.filename, sha256=hashlib.sha256(req.markdown.encode()).hexdigest(),
                  size=len(req.markdown), uploader=user.username, uploader_units=user.units,
                  markdown=req.markdown, meta=meta)
        s.add(job)
        s.flush()
        jid = job.id
    _enqueue(jid)
    emit(user.username, "ingest.from_markdown", jid, {})
    return {"id": jid, "status": MOI}


@app.get("/jobs")
def jobs(status: str | None = None, mine: bool = False, user: UserCtx = Depends(current_user)):
    with session() as s:
        q = select(Job).order_by(Job.created_at.desc()).limit(300)
        if status:
            q = q.where(Job.status == status)
        if mine or not user.has("reviewer", "admin"):
            q = q.where(Job.uploader == user.username)
        return [_job_out(j) for j in s.scalars(q)]


def _get_job(s, jid: str, user: UserCtx) -> Job:
    j = s.get(Job, jid)
    if not j or (j.uploader != user.username and not user.has("reviewer", "admin")):
        raise HTTPException(404, "Không tìm thấy tác vụ")
    if user.has("reviewer", "admin") and j.uploader != user.username:
        if not can_access(user, int(j.meta.get("do_mat", 0) or 0), j.meta.get("don_vi")):
            raise HTTPException(403, "Không có quyền với tài liệu này")
    return j


@app.get("/jobs/{jid}")
def job(jid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        return _job_out(_get_job(s, jid, user), full=True)


@app.get("/jobs/{jid}/original")
def original(jid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        j = _get_job(s, jid, user)
        if not j.original_path or not Path(j.original_path).exists():
            raise HTTPException(404, "Không có tệp gốc")
        return FileResponse(j.original_path, filename=j.filename)


class JobEdit(BaseModel):
    markdown: str | None = None
    meta: dict | None = None


@app.put("/jobs/{jid}")
def edit(jid: str, req: JobEdit, user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        j = _get_job(s, jid, user)
        if j.status not in (CHO_DUYET, CHO_DUYET_CAP_2):
            raise HTTPException(409, "Chỉ sửa được tác vụ đang chờ duyệt")
        if req.meta is not None:
            meta = {**j.meta, **req.meta}
            _check_meta(meta, user)
            j.meta = meta
        if req.markdown is not None and req.markdown != j.markdown:
            j.markdown = req.markdown
            if j.approvals:  # nội dung thay đổi sau khi duyệt cấp 1 → phải duyệt lại
                j.approvals, j.status = [], CHO_DUYET
        emit(user.username, "ingest.edit", jid, {})
        return _job_out(j, full=True)


@app.post("/jobs/{jid}/normalize-ids", response_class=PlainTextResponse)
def normalize_ids(jid: str, user: UserCtx = Depends(require("reviewer", "admin"))):
    """Xem trước bản Markdown đã chèn mã định danh mục (phục vụ Luồng B)."""
    with session() as s:
        j = _get_job(s, jid, user)
        return insert_ids(_doc_id_b(j.meta, j.id), j.markdown)


def _doc_id_b(meta: dict, jid: str) -> str:
    if meta.get("id"):
        return slugify(str(meta["id"]))
    so = str(meta.get("so_hieu", "")).split("/")[0].strip()
    year = str(meta.get("ngay_ban_hanh", ""))[:4] or str(date.today().year)
    pre = LOAI_PREFIX.get(meta.get("loai", ""), "VB")
    return slugify(f"{pre}-{so}-{year}") if so else slugify(f"{pre}-{jid[:8]}")


def _doc_id_a(meta: dict, jid: str) -> str:
    base = slugify(str(meta.get("so_hieu") or meta.get("ten") or "TL"))[:40]
    return f"TL-{base}-{jid[:6]}"


class Approve(BaseModel):
    track: str = Field(pattern="^(A|B)$")
    doc_id: str | None = None


def _upsert_document(s, doc_id: str, track: str, meta: dict, j: Job, md: str, commit: str = ""):
    path = DOCS / f"{doc_id}.md"
    path.write_text(md, encoding="utf-8")
    d = s.get(Document, doc_id)
    if d is None:
        d = Document(doc_id=doc_id, track=track, version=0)
        s.add(d)
    d.version += 1
    d.track, d.title, d.so_hieu = track, str(meta.get("ten", doc_id))[:500], str(meta.get("so_hieu", ""))
    d.loai, d.do_mat, d.don_vi = meta.get("loai", "khac"), int(meta.get("do_mat", 0) or 0), meta.get("don_vi") or ["chung"]
    d.ngay_ban_hanh, d.trang_thai = str(meta.get("ngay_ban_hanh", "") or "")[:10], meta.get("trang_thai", "con_hieu_luc")
    d.sha256, d.job_id, d.path, d.commit = j.sha256, j.id, str(path), commit
    d.minhash = minhash_bytes(minhash(md))
    return d


@app.post("/jobs/{jid}/approve")
def approve(jid: str, req: Approve, user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        j = _get_job(s, jid, user)
        if j.status not in (CHO_DUYET, CHO_DUYET_CAP_2):
            raise HTTPException(409, f"Tác vụ ở trạng thái {j.status}, không duyệt được")
        meta = {k: v for k, v in j.meta.items() if not k.startswith("_")}
        if req.track == "A":
            doc_id = req.doc_id or j.doc_id or _doc_id_a(meta, j.id)
            md = dump_frontmatter({"id": doc_id, **meta, "nguoi_duyet": user.username}, split_frontmatter(j.markdown)[1])
            try:
                search_svc.call("POST", "/index", user, json={"doc_id": doc_id, "markdown": md, "title": meta.get("ten", ""),
                                                             "meta": meta, "nguon": "A"})
            except ServiceError as e:
                raise as_http(e)
            _upsert_document(s, doc_id, "A", meta, j, md)
            j.status, j.target, j.doc_id = DA_DUYET, "A", doc_id
            j.approvals = [*j.approvals, {"user": user.username, "at": utcnow().isoformat(), "track": "A"}]
            emit(user.username, "ingest.approve", jid, {"track": "A", "doc_id": doc_id})
            return _job_out(j)

        # Luồng B: bắt buộc duyệt hai cấp bởi hai cán bộ khác nhau
        missing = [k for k in ("so_hieu", "ten") if not meta.get(k)]
        if missing:
            raise HTTPException(422, f"Văn bản chuẩn cần đủ thông tin: {', '.join(missing)}")
        if j.status == CHO_DUYET:
            j.approvals = [{"user": user.username, "at": utcnow().isoformat(), "track": "B"}]
            j.status, j.target = CHO_DUYET_CAP_2, "B"
            j.doc_id = req.doc_id or j.doc_id or _doc_id_b(meta, j.id)
            emit(user.username, "ingest.approve_l1", jid, {"track": "B", "doc_id": j.doc_id})
            return _job_out(j)
        if any(a["user"] == user.username for a in j.approvals):
            raise HTTPException(409, "Duyệt cấp 2 phải do cán bộ khác với người duyệt cấp 1 thực hiện")
        doc_id = j.doc_id or _doc_id_b(meta, j.id)
        fm = {"id": doc_id, "so_hieu": meta.get("so_hieu"), "ten": meta.get("ten"), "loai": meta.get("loai", "khac"),
              "co_quan_ban_hanh": meta.get("co_quan_ban_hanh", ""), "ngay_ban_hanh": meta.get("ngay_ban_hanh", ""),
              "hieu_luc_tu": meta.get("hieu_luc_tu", ""), "trang_thai": meta.get("trang_thai", "con_hieu_luc"),
              "thay_the_boi": meta.get("thay_the_boi"), "do_mat": int(meta.get("do_mat", 0) or 0),
              "don_vi": meta.get("don_vi") or ["chung"], "don_vi_quan_ly": meta.get("don_vi_quan_ly", ""),
              "nguoi_soan": j.approvals[0]["user"], "nguoi_duyet": user.username, "sha256_ban_goc": j.sha256}
        body = insert_ids(doc_id, split_frontmatter(j.markdown)[1])
        md = dump_frontmatter(fm, body)
        try:
            r = exact_svc.call("POST", "/kb/commit", user, json={
                "doc_id": doc_id, "content": md, "author": user.username,
                "message": f"Duyệt văn bản {fm['so_hieu']} – {fm['ten']} (soạn: {fm['nguoi_soan']}, duyệt: {user.username})"})
            search_svc.call("POST", "/index", user, json={"doc_id": doc_id, "markdown": md, "title": fm["ten"],
                                                         "meta": {**meta, **fm}, "nguon": "B"})
        except ServiceError as e:
            raise as_http(e)
        _upsert_document(s, doc_id, "B", {**meta, **fm}, j, md, commit=r["commit"])
        j.status, j.doc_id, j.markdown = DA_DUYET, doc_id, md
        j.approvals = [*j.approvals, {"user": user.username, "at": utcnow().isoformat(), "track": "B"}]
        emit(user.username, "ingest.approve_l2", jid, {"track": "B", "doc_id": doc_id, "commit": r["commit"]})
        return _job_out(j)


class Reject(BaseModel):
    ly_do: str = Field(min_length=3)


@app.post("/jobs/{jid}/reject")
def reject(jid: str, req: Reject, user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        j = _get_job(s, jid, user)
        if j.status == DA_DUYET:
            raise HTTPException(409, "Tác vụ đã duyệt; thu hồi tài liệu tại danh mục tài liệu")
        j.status, j.reject_reason = TU_CHOI, req.ly_do
    emit(user.username, "ingest.reject", jid, {"ly_do": req.ly_do})
    return {"ok": True}


@app.post("/jobs/{jid}/retry")
def retry(jid: str, user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        j = _get_job(s, jid, user)
        if j.status not in (LOI, TU_CHOI, CHO_DUYET):
            raise HTTPException(409, "Không xử lý lại được ở trạng thái hiện tại")
        j.status, j.approvals = MOI, []
    _enqueue(jid)
    return {"ok": True}


# ---------------- Sổ đăng ký tài liệu ----------------
def _doc_visible(d: Document, user: UserCtx) -> bool:
    return can_access(user, d.do_mat, d.don_vi)


@app.get("/documents")
def documents(q: str = "", loai: str = "", track: str = "", user: UserCtx = Depends(current_user)):
    with session() as s:
        stmt = select(Document).order_by(Document.updated_at.desc()).limit(500)
        if loai:
            stmt = stmt.where(Document.loai == loai)
        if track:
            stmt = stmt.where(Document.track == track)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(Document.title.ilike(like) | Document.so_hieu.ilike(like) | Document.doc_id.ilike(like))
        return [{"doc_id": d.doc_id, "track": d.track, "title": d.title, "so_hieu": d.so_hieu, "loai": d.loai,
                 "do_mat": d.do_mat, "don_vi": d.don_vi, "ngay_ban_hanh": d.ngay_ban_hanh,
                 "trang_thai": d.trang_thai, "version": d.version, "commit": d.commit, "updated_at": d.updated_at}
                for d in s.scalars(stmt) if _doc_visible(d, user)]


@app.get("/documents/{doc_id}/markdown", response_class=PlainTextResponse)
def doc_markdown(doc_id: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        d = s.get(Document, doc_id)
        if not d or not _doc_visible(d, user):
            raise HTTPException(404, "Không tìm thấy tài liệu hoặc không có quyền truy cập")
        return Path(d.path).read_text(encoding="utf-8")


@app.delete("/documents/{doc_id}")
def revoke(doc_id: str, user: UserCtx = Depends(require("admin"))):
    """Thu hồi tài liệu đồng bộ ở mọi kho (chỉ mục vector, kho chuẩn, sổ đăng ký)."""
    with session() as s:
        d = s.get(Document, doc_id)
        if not d:
            raise HTTPException(404, "Không tìm thấy tài liệu")
        try:
            search_svc.call("DELETE", f"/docs/{doc_id}", user)
            if d.track == "B":
                exact_svc.call("POST", "/kb/commit", user, json={"doc_id": doc_id, "content": "", "delete": True,
                                                                 "author": user.username,
                                                                 "message": f"Thu hồi văn bản {d.so_hieu or doc_id}"})
        except ServiceError as e:
            raise as_http(e)
        Path(d.path).unlink(missing_ok=True)
        s.delete(d)
    emit(user.username, "document.revoke", doc_id, {})
    return {"deleted": doc_id}


# ---------------- Báo cáo chất lượng dữ liệu ----------------
@app.get("/reports/quality")
def quality_report(user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        by_status = dict(s.execute(select(Job.status, func.count()).group_by(Job.status)).all())
        by_kind = dict(s.execute(select(Job.kind, func.count()).group_by(Job.kind)).all())
        docs_by_loai = dict(s.execute(select(Document.loai, func.count()).group_by(Document.loai)).all())
        docs_by_track = dict(s.execute(select(Document.track, func.count()).group_by(Document.track)).all())
        recent = s.scalars(select(Job).where(Job.quality != None).order_by(Job.created_at.desc()).limit(500)).all()  # noqa: E711
        scores = [j.quality.get("diem") for j in recent if j.quality and j.quality.get("diem") is not None]
        low = [{"id": j.id, "filename": j.filename, "diem": j.quality.get("diem"), "canh_bao": j.warnings}
               for j in recent if j.quality and (j.quality.get("diem") or 100) < 70][:30]
        dups = [{"id": j.id, "filename": j.filename, "trung_voi": j.duplicates} for j in recent if j.duplicates][:30]
        ocr = sum(1 for j in recent if j.quality and j.quality.get("ocr"))
        legacy = sum(1 for j in recent if j.quality and j.quality.get("thong_ke", {}).get("bang_ma"))
        hieu_luc = [{"doc_id": d.doc_id, "so_hieu": d.so_hieu, "trang_thai": d.trang_thai}
                    for d in s.scalars(select(Document).where(Document.trang_thai != "con_hieu_luc"))]
    avg = round(sum(scores) / len(scores), 1) if scores else None
    md = [f"# Báo cáo chất lượng dữ liệu ({date.today().isoformat()})", "",
          "## Thống kê", f"- Tác vụ theo trạng thái: {by_status}", f"- Theo định dạng: {by_kind}",
          f"- Tài liệu theo loại: {docs_by_loai}", f"- Tài liệu theo luồng: {docs_by_track}",
          "", "## Chất lượng", f"- Điểm chất lượng trung bình (500 tác vụ gần nhất): {avg}",
          f"- Số tài liệu dùng OCR: {ocr}", f"- Số tài liệu chuyển mã từ bảng mã cũ: {legacy}",
          f"- Số tài liệu điểm dưới 70: {len(low)}", "", "## Trùng lặp", f"- Số tác vụ có tài liệu gần trùng: {len(dups)}",
          "", "## Hiệu lực", f"- Văn bản không còn hiệu lực trong sổ đăng ký: {len(hieu_luc)}"]
    return {"markdown": "\n".join(md), "by_status": by_status, "by_kind": by_kind, "docs_by_loai": docs_by_loai,
            "docs_by_track": docs_by_track, "avg_score": avg, "low_quality": low, "duplicates": dups,
            "ocr": ocr, "legacy_encoding": legacy, "khong_con_hieu_luc": hieu_luc}
