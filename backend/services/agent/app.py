"""agent-svc – tác vụ dài theo hướng tác tử (agent), xử lý nền từng bước, hiển thị tiến trình:

    Phân tích văn bản mới     POST /tasks {kind: "phan_tich"}   tóm tắt + vấn đề liên quan đến ngành, có căn cứ
    Soạn văn bản tham mưu     POST /tasks {kind: "soan_thao"}   dàn ý (chờ xác nhận) → viết từng phần → thể thức
    Tổng hợp báo cáo chung    POST /tasks {kind: "tong_hop"}    từ nhiều báo cáo riêng lẻ (kho và/hoặc tệp tải lên)
    Giám định dữ liệu         /quality/*                        tác tử chạy định kỳ, phát hiện vấn đề dữ liệu

Giao diện thăm dò GET /tasks/{id} (1–2 giây/lần) để vẽ tiến trình. Tác vụ chạy ở agent-worker (hàng đợi "agent").
"""
import asyncio
import contextlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from aicommon.app import create_app
from aicommon.audit import emit
from aicommon.config import get_settings
from aicommon.db import init_db, session
from aicommon.export import ExportError, md_to_docx
from aicommon.internal import ServiceError, SyncSvc
from aicommon.priority import active as interactive_active
from aicommon.resources import list_skills
from aicommon.security import UserCtx, current_user, require

from . import docs as D
from .criteria import criteria_sets, draft_templates, get_draft_template
from .models import (
    ACTIVE,
    CHO,
    CHO_XAC_NHAN,
    DA_HUY,
    DANG_CHAY,
    KINDS,
    LOI,
    XONG,
    QaFinding,
    QaRun,
    Task,
    Upload,
)
from .quality import KIND_LABEL, llm_allowed, start_run

log = logging.getLogger("agent")
S = get_settings()


def _enqueue(task_id: str):
    from .worker import run_task
    run_task.delay(task_id)


def _enqueue_qa(run_id: str):
    from .worker import run_qa
    run_qa.delay(run_id)


# ---------------------------------------------------------------- lịch chạy nền
async def scheduler(stop: asyncio.Event):
    """Vòng lặp định kỳ (mỗi phút): khởi động lượt giám định dữ liệu đến hạn KHI HỆ THỐNG RẢNH
    (không ai đang hỏi đáp, không có tác vụ dài đang chạy); dọn tệp đính kèm quá hạn."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(_tick)
        except Exception as e:
            log.warning("Lịch chạy nền lỗi: %s", e)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=60)


def _tick():
    now = datetime.now(timezone.utc)
    if S.qa_interval_min > 0:
        with session() as s:
            last = s.scalars(select(QaRun).order_by(QaRun.started_at.desc()).limit(1)).first()
            running = s.scalar(select(func.count()).select_from(Task).where(Task.status == DANG_CHAY))
        due = not last or (now - _aware(last.started_at)) >= timedelta(minutes=S.qa_interval_min)
        if due and not running and interactive_active() == 0:
            rid = start_run("lich")
            if rid:
                _enqueue_qa(rid)
                log.info("Khởi động lượt giám định dữ liệu theo lịch %s", rid, extra={"event": "qa.schedule"})
    cutoff = now - timedelta(hours=S.agent_upload_ttl_h)
    with session() as s:
        for u in s.scalars(select(Upload).where(Upload.created_at < cutoff)):
            in_use = s.scalar(select(func.count()).select_from(Task).where(Task.status.in_(ACTIVE + (CHO_XAC_NHAN,))))
            if in_use:
                break  # có tác vụ đang dùng tệp: để lượt sau
            Path(u.path).unlink(missing_ok=True)
            s.delete(u)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@contextlib.asynccontextmanager
async def lifespan(app):
    init_db()
    D.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler(stop))
    yield
    stop.set()
    await task


app = create_app("agent", lifespan=lifespan)


# ---------------------------------------------------------------- danh mục
@app.get("/catalog")
def catalog(user: UserCtx = Depends(current_user)):
    """Bộ tiêu chí phân tích, mẫu văn bản tham mưu, mẫu báo cáo tổng hợp – để giao diện dựng biểu mẫu."""
    return {"kinds": KINDS, "criteria": criteria_sets(), "drafts": draft_templates(),
            "reports": [{"name": s["name"], "description": s["meta"].get("description", ""),
                         "params": s["meta"].get("params", [])} for s in list_skills() if s["meta"].get("loai") == "tong_hop"],
            "gop_y": _gopy_catalog()}


def _gopy_catalog() -> dict:
    from .gopy import config
    try:
        _, cfg = config()
    except ValueError:
        return {"khia_canh": []}
    return {"khia_canh": [{"id": a["id"], "ten": a["ten"]} for a in cfg.get("khia_canh") or [] if a.get("bat", True)],
            "so_thuat_ngu": len(cfg.get("thuat_ngu") or [])}


# ---------------------------------------------------------------- tệp đính kèm
@app.post("/uploads")
async def upload(file: UploadFile = File(...), do_mat: int = Form(0), user: UserCtx = Depends(current_user)):
    if do_mat > S.system_max_clearance:
        raise HTTPException(422, "Độ mật vượt cấp độ hệ thống được phép xử lý")
    if do_mat > user.clearance:
        raise HTTPException(403, "Không được xử lý tài liệu có độ mật cao hơn quyền của người dùng")
    data = await file.read()
    if len(data) > S.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Tệp vượt quá {S.max_upload_mb} MB")
    if not data:
        raise HTTPException(400, "Tệp rỗng")
    path, h = D.save_upload(data, file.filename or "tep")
    with session() as s:
        u = Upload(owner_sub=user.sub, filename=(file.filename or "tep")[:500], size=len(data), sha256=h,
                   do_mat=do_mat, path=path)
        s.add(u)
        s.flush()
        out = {"id": u.id, "filename": u.filename, "size": u.size}
    emit(user.username, "agent.upload", out["id"], {"filename": out["filename"], "size": out["size"]})
    return out


def _uploads(ids: list[str], user: UserCtx) -> list[dict]:
    out = []
    with session() as s:
        for uid in ids:
            u = s.get(Upload, uid)
            if not u or u.owner_sub != user.sub:
                raise HTTPException(404, f"Không tìm thấy tệp đính kèm {uid}")
            out.append({"upload_id": u.id, "filename": u.filename, "path": u.path})
    return out


# ---------------------------------------------------------------- tác vụ
class CreateTask(BaseModel):
    kind: str = Field(pattern="^(phan_tich|soan_thao|gop_y|tong_hop)$")
    title: str = Field("", max_length=300)
    input: dict = Field(default_factory=dict)
    conversation_id: str = ""


def _out(t: Task, full: bool = False) -> dict:
    d = {"id": t.id, "kind": t.kind, "kind_label": KINDS.get(t.kind, t.kind), "title": t.title, "status": t.status,
         "progress": t.progress, "current": t.current, "note": t.note, "plan": t.plan, "error": t.error,
         "warnings": t.warnings, "created_at": t.created_at, "updated_at": t.updated_at, "started_at": t.started_at,
         "finished_at": t.finished_at, "conversation_id": t.conversation_id}
    if full:
        inp = {k: v for k, v in (t.input or {}).items() if k not in ("path", "text")}
        if inp.get("uploads"):
            inp["uploads"] = [{"filename": u["filename"]} for u in inp["uploads"]]
        d.update(input=inp, result=t.result, artifacts=t.artifacts, log=t.log,
                 confirm=(t.state or {}).get(f"confirm_{(t.state or {}).get('awaiting')}") if t.status == CHO_XAC_NHAN else None,
                 awaiting=(t.state or {}).get("awaiting") if t.status == CHO_XAC_NHAN else None)
        d["che_do"] = "gop_y" if is_gopy(t) else (t.input or {}).get("che_do", "")
        if t.status == CHO_XAC_NHAN and t.kind == "soan_thao" and not is_gopy(t):  # căn cứ để gắn/bỏ khi duyệt dàn ý
            d["confirm_sources"] = [{k: x.get(k) for k in ("label", "title", "breadcrumb", "so_hieu", "nguon")}
                                    | {"trich": (x.get("text") or "")[:500]} for x in (t.state or {}).get("sources", [])]
        with session() as s:  # vị trí trong hàng đợi (tác vụ chờ trước nó)
            if t.status == CHO:
                d["queue_pos"] = s.scalar(select(func.count()).select_from(Task).where(
                    Task.status.in_(ACTIVE), Task.created_at < t.created_at)) or 0
    return d


def create_task(req: CreateTask, user: UserCtx) -> dict:
    inp = dict(req.input)
    if req.kind == "gop_y":
        # Bí danh (API 1.4.0, trò chuyện): tham gia ý kiến là một HÌNH THỨC của Công văn trong phân hệ soạn thảo
        req.kind = "soan_thao"
        inp.setdefault("mau", GOPY_SKILL)
        inp["che_do"] = "gop_y"
    if req.kind == "phan_tich":
        if inp.get("upload_id"):
            u = _uploads([inp["upload_id"]], user)[0]
            inp.update(filename=u["filename"], path=u["path"])
            title = req.title or f"Phân tích: {u['filename']}"
        elif inp.get("doc_id"):
            title = req.title or f"Phân tích: {inp['doc_id']}"
        elif len(inp.get("text", "")) >= 80:
            title = req.title or "Phân tích văn bản dán trực tiếp"
        else:
            raise HTTPException(400, "Cần chọn tệp, tài liệu trong kho hoặc dán nội dung văn bản (≥ 80 ký tự)")
    elif req.kind == "soan_thao":
        tpl = get_draft_template(inp.get("mau", ""))
        if not tpl:
            raise HTTPException(400, "Mẫu văn bản không tồn tại")
        has_files = bool(inp.get("upload_id") or inp.get("upload_ids") or inp.get("doc_ids"))
        if not inp.get("che_do") and tpl["gop_y"] and has_files and _RE_GOPY.search(inp.get("chu_de", "")):
            inp["che_do"] = "gop_y"  # công văn + tệp đính kèm + chủ đề "tham gia ý kiến/góp ý" → hình thức tham gia ý kiến
        if inp.get("che_do") == "gop_y":
            if not tpl["gop_y"]:
                raise HTTPException(400, f"Mẫu “{tpl['ten_loai']}” không hỗ trợ hình thức tham gia ý kiến dự thảo")
            title = req.title or _gopy_input(inp, user)
        else:
            inp.pop("che_do", None)
            if len(inp.get("chu_de", "").strip()) < 5:
                raise HTTPException(400, "Cần nêu chủ đề văn bản (ít nhất 5 ký tự)")
            inp["uploads"] = _uploads(inp.pop("upload_ids", []) or [], user)
            title = req.title or f"{tpl['ten_loai']}: {inp['chu_de'][:200]}"
    else:
        if not any(s["name"] == inp.get("skill") and s["meta"].get("loai") == "tong_hop" for s in list_skills()):
            raise HTTPException(400, "Mẫu báo cáo tổng hợp không tồn tại")
        inp["uploads"] = _uploads(inp.pop("upload_ids", []) or [], user)
        if not inp.get("doc_ids") and not inp["uploads"]:
            raise HTTPException(400, "Cần chọn ít nhất một báo cáo đầu vào")
        title = req.title or "Báo cáo tổng hợp"
    with session() as s:
        t = Task(kind=req.kind, title=title[:300], owner_sub=user.sub, owner=user.model_dump(), input=inp,
                 conversation_id=req.conversation_id[:32])
        s.add(t)
        s.flush()
        out = _out(t)
    _enqueue(out["id"])
    emit(user.username, "agent.create", out["id"], {"kind": req.kind, "title": out["title"]})
    log.info("Tạo tác vụ %s (%s) cho %s", out["id"], req.kind, user.username, extra={"event": "agent.create"})
    return out


@app.post("/tasks")
def create(req: CreateTask, user: UserCtx = Depends(current_user)):
    return create_task(req, user)


def _own(s, tid: str, user: UserCtx) -> Task:
    t = s.get(Task, tid)
    if not t or (t.owner_sub != user.sub and not user.has("admin")):
        raise HTTPException(404, "Không tìm thấy tác vụ")
    return t


@app.get("/tasks")
def tasks(kind: str = "", status: str = "", all: bool = False, limit: int = 100, user: UserCtx = Depends(current_user)):
    with session() as s:
        q = select(Task).order_by(Task.created_at.desc()).limit(min(limit, 300))
        if not (all and user.has("admin")):
            q = q.where(Task.owner_sub == user.sub)
        if kind:
            q = q.where(Task.kind == kind)
        if status:
            q = q.where(Task.status.in_(status.split(",")))
        return [_out(t) | ({"owner": t.owner.get("username")} if all else {}) for t in s.scalars(q)]


@app.get("/tasks/{tid}")
def task(tid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        return _out(_own(s, tid, user), full=True)


@app.post("/tasks/{tid}/cancel")
def cancel(tid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        t = _own(s, tid, user)
        if t.status in (XONG, LOI, DA_HUY):
            raise HTTPException(409, "Tác vụ đã kết thúc")
        t.status, t.note = DA_HUY, "Đã hủy theo yêu cầu"
    emit(user.username, "agent.cancel", tid, {})
    return {"ok": True}


class Confirm(BaseModel):
    phan: list[dict] = Field(default_factory=list, max_length=20)   # soạn thảo: dàn ý
    gop_y: dict | None = None                                       # tham gia ý kiến: {y_kien_chung, muc, kien_nghi}


def _clean_gopy(g: dict) -> dict:
    """Chuẩn hóa danh sách ý kiến người dùng đã chọn, sửa (giới hạn độ dài, chỉ giữ trường hợp lệ)."""
    keep = ("id", "khia_canh", "vi_tri", "trich", "nhan_xet", "de_nghi_sua", "can_cu", "muc_do", "boi", "nguon_tra_cuu")
    muc = []
    for m in (g.get("muc") or [])[:80]:
        if not isinstance(m, dict) or not str(m.get("nhan_xet", "")).strip():
            continue
        x = {k: m.get(k) for k in keep if k in m}
        for k in ("vi_tri", "trich", "nhan_xet", "de_nghi_sua", "can_cu"):
            x[k] = str(x.get(k) or "").strip()[:1500]
        x["chon"] = bool(m.get("chon", True))
        x["khia_canh"] = str(x.get("khia_canh") or "khac")
        muc.append(x)
    return {"y_kien_chung": str(g.get("y_kien_chung") or "").strip()[:1500], "muc": muc,
            "kien_nghi": [str(k).strip()[:1000] for k in (g.get("kien_nghi") or []) if str(k).strip()][:6]}


@app.post("/tasks/{tid}/confirm")
def confirm(tid: str, req: Confirm, user: UserCtx = Depends(current_user)):
    """Người dùng xác nhận (có thể đã sửa) dàn ý / danh sách ý kiến → tác vụ chạy tiếp."""
    with session() as s:
        t = _own(s, tid, user)
        if t.status != CHO_XAC_NHAN:
            raise HTTPException(409, "Tác vụ không ở trạng thái chờ xác nhận")
        sid = (t.state or {}).get("awaiting")
        if is_gopy(t):
            if not req.gop_y:
                raise HTTPException(400, "Thiếu danh sách ý kiến")
            data = _clean_gopy(req.gop_y)
            n = sum(1 for m in data["muc"] if m["chon"])
        else:
            phan = [{"tieu_de": str(p.get("tieu_de", "")).strip()[:300], "huong_dan": str(p.get("huong_dan", ""))[:500],
                     "y": [str(y)[:500] for y in p.get("y", []) if str(y).strip()][:8],
                     "nguon": [str(n) for n in p.get("nguon", [])][:6]} for p in req.phan if str(p.get("tieu_de", "")).strip()]
            if not phan:
                raise HTTPException(400, "Dàn ý không có phần nào")
            data, n = {"phan": phan}, len(phan)
        t.state = {**(t.state or {}), f"confirmed_{sid}": data, "awaiting": None}
        t.status, t.note = CHO, "Đã xác nhận, chờ xử lý tiếp"
    emit(user.username, "agent.confirm", tid, {"step": sid, "so_muc": n})
    _enqueue(tid)
    return {"ok": True}


@app.post("/tasks/{tid}/retry")
def retry(tid: str, user: UserCtx = Depends(current_user)):
    """Chạy lại tác vụ lỗi/đã hủy: các bước đã xong được giữ, chạy tiếp từ bước lỗi."""
    with session() as s:
        t = _own(s, tid, user)
        if t.status not in (LOI, DA_HUY):
            raise HTTPException(409, "Chỉ chạy lại tác vụ lỗi hoặc đã hủy")
        t.plan = [{**p, "status": "cho" if p["status"] in ("loi", "dang_chay") else p["status"]} for p in t.plan or []]
        t.status, t.error, t.note = CHO, "", "Chờ chạy lại"
    _enqueue(tid)
    return {"ok": True}


class EditResult(BaseModel):
    result: str
    ban: str = ""  # soạn thảo: "can_cu" để sửa bản kèm căn cứ


@app.put("/tasks/{tid}/result")
def edit_result(tid: str, req: EditResult, user: UserCtx = Depends(current_user)):
    with session() as s:
        t = _own(s, tid, user)
        if req.ban == "can_cu":
            t.artifacts = {**(t.artifacts or {}), "ban_can_cu": req.result}
        else:
            t.result = req.result
            if t.kind in ("soan_thao", "gop_y"):
                t.artifacts = {**(t.artifacts or {}), "ban_sach": req.result}
    return {"ok": True}


GOPY_SKILL = "soan-cong-van-gop-y"
_RE_GOPY = re.compile(r"\b(tham gia ý kiến|góp ý|cho ý kiến)\b", re.I)


def is_gopy(t: Task) -> bool:
    """Tác vụ tham gia ý kiến dự thảo: hình thức gop_y của mẫu Công văn (kind "gop_y" cũ của bản 1.4.0 vẫn nhận)."""
    return t.kind == "gop_y" or (t.kind == "soan_thao" and (t.input or {}).get("che_do") == "gop_y")


def _gopy_input(inp: dict, user: UserCtx) -> str:
    """Dự thảo (bắt buộc) + văn bản đề nghị tham gia ý kiến (tùy chọn). upload_id / cv_upload_id chỉ rõ vai trò;
    upload_ids: hệ thống tự nhận dự thảo (tệp có chữ "dự thảo" hoặc dài hơn). Trả tiêu đề tác vụ."""
    ups = []
    if inp.get("upload_id"):
        ups.append({**_uploads([inp.pop("upload_id")], user)[0], "role": "du_thao"})
    if inp.get("cv_upload_id"):
        ups.append({**_uploads([inp.pop("cv_upload_id")], user)[0], "role": "de_nghi"})
    else:
        inp.pop("cv_upload_id", None)
    ups += _uploads(inp.pop("upload_ids", []) or [], user)
    inp["uploads"] = ups
    if not ups and not inp.get("doc_ids"):
        raise HTTPException(400, "Cần tải lên dự thảo văn bản cần tham gia ý kiến")
    name = inp.get("ten_du_thao") or next((u["filename"] for u in ups if u.get("role") == "du_thao"),
                                          ups[0]["filename"] if ups else inp["doc_ids"][0])
    inp.setdefault("chu_de", f"tham gia ý kiến {name}"[:300])
    return f"Công văn: Tham gia ý kiến {name[:200]}"


class ArchiveReq(BaseModel):
    so_hieu: str = Field("", max_length=60)        # số, ký hiệu văn bản đã ban hành
    ngay_ban_hanh: str = Field("", max_length=10)   # YYYY-MM-DD
    do_mat: int = 0
    don_vi: list[str] = Field(default_factory=lambda: ["chung"])


@app.post("/tasks/{tid}/archive")
def archive(tid: str, req: ArchiveReq, user: UserCtx = Depends(current_user)):
    """Đưa văn bản ĐÃ KÝ BAN HÀNH (bản sạch, sau khi cán bộ chỉnh sửa) vào kho văn bản đơn vị đã ban hành.
    Đi qua hàng chờ kiểm duyệt như mọi tài liệu khác; sau khi duyệt trở thành tiền lệ cho lần tham mưu sau."""
    from .archive import NHOM_DI, clean_for_archive
    with session() as s:
        t = _own(s, tid, user)
        if t.status != XONG or t.kind not in ("soan_thao", "gop_y"):
            raise HTTPException(409, "Chỉ đưa vào kho văn bản soạn thảo, tham gia ý kiến đã hoàn thành")
        md, title, gopy = (t.artifacts or {}).get("ban_sach") or t.result, t.title, is_gopy(t)
        art = dict(t.artifacts or {})
    if art.get("luu_kho"):
        raise HTTPException(409, f"Đã gửi vào kho (tác vụ nạp {art['luu_kho']})")
    meta = {"nhom": NHOM_DI, "ten": title.split(":", 1)[-1].strip()[:250] or title, "loai": "cong_van" if gopy else
            {"Tờ trình": "to_trinh", "Kế hoạch": "ke_hoach", "Báo cáo": "bao_cao", "Công văn": "cong_van"}.get(
                art.get("ten_loai", ""), "khac"), "do_mat": req.do_mat, "don_vi": req.don_vi or ["chung"]}
    if req.so_hieu.strip():
        meta["so_hieu"] = req.so_hieu.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", req.ngay_ban_hanh):
        meta["ngay_ban_hanh"] = req.ngay_ban_hanh
    try:
        j = SyncSvc(S.ingest_url).call("POST", "/jobs/from-markdown", user, json={
            "filename": f"{tid}.md", "markdown": clean_for_archive(md), "meta": meta})
    except ServiceError as e:
        raise HTTPException(e.status, e.detail) from e
    with session() as s:
        t = s.get(Task, tid)
        t.artifacts = {**(t.artifacts or {}), "luu_kho": j["id"]}
    emit(user.username, "agent.archive", tid, {"job": j["id"]})
    return {"ok": True, "job_id": j["id"]}


@app.delete("/tasks/{tid}")
def remove(tid: str, user: UserCtx = Depends(current_user)):
    with session() as s:
        t = _own(s, tid, user)
        if t.status in ACTIVE:
            t.status = DA_HUY  # tiến trình nền sẽ dừng ở bước kế tiếp
        s.delete(t)
    return {"deleted": tid}


@app.get("/tasks/{tid}/docx")
def docx(tid: str, ban: str = "", user: UserCtx = Depends(current_user)):
    with session() as s:
        t = _own(s, tid, user)
        md = (t.artifacts or {}).get("ban_can_cu") if ban == "can_cu" else t.result
        title = t.title
    if not md:
        raise HTTPException(409, "Tác vụ chưa có kết quả")
    try:
        out = md_to_docx(md, title)
    except ExportError as e:
        raise HTTPException(e.status, str(e))
    emit(user.username, "agent.export", tid, {"ban": ban or "chinh"})
    return FileResponse(out, filename=f"{title[:80]}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/queue")
def queue(user: UserCtx = Depends(require("admin", "reviewer"))):
    """Tình trạng hàng đợi tác vụ dài – phục vụ màn hình Giám sát."""
    with session() as s:
        by = dict(s.execute(select(Task.status, func.count()).group_by(Task.status)).all())
        kinds = dict(s.execute(select(Task.kind, func.count()).group_by(Task.kind)).all())
        running = [_out(t) | {"owner": t.owner.get("username")} for t in
                   s.scalars(select(Task).where(Task.status.in_(ACTIVE + (CHO_XAC_NHAN,)))
                             .order_by(Task.created_at).limit(50))]
    return {"by_status": by, "by_kind": kinds, "active": running, "interactive": interactive_active()}


# ---------------------------------------------------------------- giám định dữ liệu
@app.get("/quality/summary")
def quality_summary(user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        open_by = dict(s.execute(select(QaFinding.kind, func.count()).where(QaFinding.status == "moi")
                                 .group_by(QaFinding.kind)).all())
        sev = dict(s.execute(select(QaFinding.severity, func.count()).where(QaFinding.status == "moi")
                             .group_by(QaFinding.severity)).all())
        st = dict(s.execute(select(QaFinding.status, func.count()).group_by(QaFinding.status)).all())
        runs = [{"id": r.id, "trigger": r.trigger, "mode": r.mode, "status": r.status, "stats": r.stats, "plan": r.plan,
                 "error": r.error, "started_at": r.started_at, "finished_at": r.finished_at}
                for r in s.scalars(select(QaRun).order_by(QaRun.started_at.desc()).limit(10))]
    last = runs[0]["started_at"] if runs else None
    nxt = (_aware(last) + timedelta(minutes=S.qa_interval_min)) if (last and S.qa_interval_min) else None
    return {"open_by_kind": open_by, "open_by_severity": sev, "by_status": st, "runs": runs, "labels": KIND_LABEL,
            "schedule": {"interval_min": S.qa_interval_min, "next_due": nxt, "llm_mode": S.qa_llm_mode,
                         "llm_hours": S.qa_llm_hours, "llm_allowed_now": llm_allowed(),
                         "hardware": S.hardware_profile}}


@app.post("/quality/runs")
def quality_run(user: UserCtx = Depends(require("reviewer", "admin"))):
    rid = start_run("thu_cong")
    if not rid:
        raise HTTPException(409, "Đang có lượt giám định chạy")
    _enqueue_qa(rid)
    emit(user.username, "qa.run", rid, {})
    return {"id": rid}


@app.get("/quality/findings")
def findings(kind: str = "", status: str = "moi", severity: str = "", limit: int = 300,
             user: UserCtx = Depends(require("reviewer", "admin"))):
    order = {"cao": 0, "trung_binh": 1, "thap": 2}
    with session() as s:
        q = select(QaFinding).order_by(QaFinding.last_seen.desc()).limit(min(limit, 1000))
        if kind:
            q = q.where(QaFinding.kind == kind)
        if status:
            q = q.where(QaFinding.status == status)
        if severity:
            q = q.where(QaFinding.severity == severity)
        rows = [{"id": f.id, "kind": f.kind, "kind_label": KIND_LABEL.get(f.kind, f.kind), "severity": f.severity,
                 "title": f.title, "detail": f.detail, "doc_ids": f.doc_ids, "data": f.data, "status": f.status,
                 "verified": f.verified, "resolution": f.resolution, "resolved_by": f.resolved_by,
                 "first_seen": f.first_seen, "last_seen": f.last_seen} for f in s.scalars(q)]
    return sorted(rows, key=lambda r: order.get(r["severity"], 3))


class Resolve(BaseModel):
    status: str = Field(pattern="^(moi|da_xu_ly|bo_qua)$")
    resolution: str = ""


@app.post("/quality/findings/{fid}")
def resolve_finding(fid: int, req: Resolve, user: UserCtx = Depends(require("reviewer", "admin"))):
    with session() as s:
        f = s.get(QaFinding, fid)
        if not f:
            raise HTTPException(404, "Không tìm thấy phát hiện")
        f.status, f.resolution, f.resolved_by = req.status, req.resolution[:2000], user.username
    emit(user.username, "qa.resolve", str(fid), {"status": req.status})
    return {"ok": True}


@app.post("/quality/findings/{fid}/apply")
def apply_fix(fid: int, user: UserCtx = Depends(require("reviewer", "admin"))):
    """Áp dụng đề xuất sửa thông tin mô tả (chỉ sổ đăng ký tài liệu tham khảo – Luồng A).
    Văn bản chuẩn (Luồng B) phải sửa qua quy trình nạp – duyệt hai cấp để giữ vết phiên bản."""
    from services.ingest.models import Document
    with session() as s:
        f = s.get(QaFinding, fid)
        if not f or f.kind != "thieu_meta" or not (f.data or {}).get("fix"):
            raise HTTPException(400, "Phát hiện này không có đề xuất sửa tự động")
        if (f.data or {}).get("track") == "B":
            raise HTTPException(409, "Văn bản chuẩn (Luồng B) sửa qua quy trình nạp – duyệt hai cấp")
        d = s.get(Document, f.doc_ids[0])
        if not d:
            raise HTTPException(404, "Tài liệu không còn trong kho")
        fix = f.data["fix"]
        for k in ("so_hieu", "ngay_ban_hanh", "title"):
            if fix.get(k):
                setattr(d, k, str(fix[k])[:500])
        f.status, f.resolution, f.resolved_by = "da_xu_ly", f"Đã áp dụng đề xuất: {fix}", user.username
    emit(user.username, "qa.apply", str(fid), {"doc_id": f.doc_ids[0], "fix": fix})
    return {"ok": True, "applied": fix}


@app.get("/health/deep")
def deep(user: UserCtx = Depends(require("admin"))):
    t0 = time.perf_counter()
    with session() as s:
        s.scalar(select(func.count()).select_from(Task))
    return {"db_ms": round((time.perf_counter() - t0) * 1000, 1)}
