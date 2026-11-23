"""Khung thực thi tác vụ dài theo kế hoạch nhiều bước (agent), có tiến trình hiển thị cho người dùng.

Mỗi loại tác vụ (phân tích, soạn thảo, tổng hợp) khai báo KẾ HOẠCH là danh sách bước cố định và hàm chạy:

    def run(ctx: Ctx):
        ctx.plan([("doc", "Tiếp nhận tài liệu"), ("tom_tat", "Tóm tắt"), …])
        with ctx.step("doc") as st:          # bước: cho → dang_chay → xong | loi
            st.detail("Đang chuyển đổi PDF…")
            for i, part in enumerate(parts):
                st.sub(i + 1, len(parts))      # tiến độ con: “phần 3/8” → thanh tiến trình chạy mịn
                out = ctx.llm_json(…)           # tự nhường mô hình cho hỏi đáp trực tiếp (aicommon/priority.py)
        ctx.confirm("dan_y", payload)         # tạm dừng chờ người dùng xác nhận (human-in-the-loop)
        ctx.finish(markdown, artifacts)

Nguyên tắc thiết kế (phù hợp hạ tầng CPU hạn chế):
  - Kế hoạch do CHƯƠNG TRÌNH định nghĩa, không để mô hình tự lập kế hoạch → thời gian chạy dự đoán được,
    mỗi lượt gọi mô hình chỉ làm một việc nhỏ với ngữ cảnh ngắn (mô hình 9B làm việc nhỏ đúng hơn việc lớn).
  - Mọi trạng thái lưu CSDL sau mỗi thay đổi → giao diện thăm dò (poll) thấy tiến trình theo thời gian thực;
    tiến trình nền khởi động lại thì tác vụ chạy tiếp từ bước chưa xong (kết quả trung gian lưu ở task.state).
  - Hủy: người dùng bấm Hủy → status=da_huy; tác vụ kiểm tra tại mỗi bước/lượt gọi mô hình và dừng sạch.
"""
import contextlib
import logging
import time
from datetime import datetime, timezone

from aicommon.config import get_settings
from aicommon.db import session
from aicommon.llm import SyncLLM
from aicommon.priority import wait_idle
from aicommon.security import UserCtx
from aicommon.telemetry import record

from .models import CHO_XAC_NHAN, DA_HUY, DANG_CHAY, LOI, XONG, Task

log = logging.getLogger("agent.runner")
S = get_settings()


class Cancelled(Exception):
    """Người dùng đã hủy tác vụ."""


class Paused(Exception):
    """Tác vụ tạm dừng chờ người dùng xác nhận."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StepHandle:
    def __init__(self, ctx: "Ctx", sid: str):
        self.ctx, self.sid = ctx, sid

    def detail(self, text: str):
        """Mô tả việc đang làm trong bước (hiển thị dưới tên bước)."""
        self.ctx._update_step(self.sid, detail=text[:300])

    def sub(self, i: int, n: int, text: str = ""):
        """Tiến độ con của bước: i/n."""
        kw = {"sub": [i, n]}
        if text:
            kw["detail"] = text[:300]
        self.ctx._update_step(self.sid, **kw)

    def out(self, summary: str):
        """Kết quả tóm tắt của bước (hiển thị khi bước đã xong), ví dụ "12 mục · 5 thời hạn"."""
        self.ctx._update_step(self.sid, out=summary[:300])


class Ctx:
    def __init__(self, task_id: str):
        self.id = task_id
        self.llm = SyncLLM()
        with session() as s:
            t = s.get(Task, task_id)
            self.kind, self.title = t.kind, t.title
            self.user = UserCtx(**t.owner)
            self.input = dict(t.input or {})
            self.state = dict(t.state or {})
            self._plan = list(t.plan or [])
        self.warnings: list[str] = []

    # ------------------------------------------------------------ lưu trạng thái
    def _save(self, **kw):
        with session() as s:
            t = s.get(Task, self.id)
            if t is None or (t.status == DA_HUY and kw.get("status") not in (DA_HUY,)):
                raise Cancelled()  # đã hủy hoặc đã xóa
            for k, v in kw.items():
                setattr(t, k, v)
            t.plan = self._plan
            t.progress = self._progress()

    def _progress(self) -> int:
        if not self._plan:
            return 0
        done = 0.0
        for st in self._plan:
            if st["status"] in ("xong", "bo_qua"):
                done += 1
            elif st["status"] == "dang_chay" and st.get("sub") and st["sub"][1]:
                done += 0.9 * st["sub"][0] / st["sub"][1]
            elif st["status"] == "dang_chay":
                done += 0.05
        return min(100, int(100 * done / len(self._plan)))

    def _step(self, sid: str) -> dict:
        return next(x for x in self._plan if x["id"] == sid)

    def _update_step(self, sid: str, **kw):
        self._step(sid).update(kw)
        self._save()

    def note(self, text: str):
        """Dòng trạng thái tức thời (ví dụ đang nhường mô hình cho hỏi đáp)."""
        self._save(note=text[:300])

    def logline(self, msg: str):
        with session() as s:
            t = s.get(Task, self.id)
            if t is not None:
                t.log = [*(t.log or []), {"t": _now(), "msg": msg[:500]}][-100:]

    def check_cancel(self):
        with session() as s:
            t = s.get(Task, self.id)
            if t is None or t.status == DA_HUY:
                raise Cancelled()

    def save_state(self, **kw):
        """Lưu kết quả trung gian (để chạy tiếp sau khi tạm dừng/khởi động lại)."""
        self.state.update(kw)
        self._save(state=self.state)

    def warn(self, msg: str):
        if msg not in self.warnings:
            self.warnings.append(msg)

    # ------------------------------------------------------------ kế hoạch, bước
    def plan(self, steps: list[tuple[str, str]]):
        """Khai báo kế hoạch. Khi chạy tiếp (sau xác nhận), giữ nguyên trạng thái các bước đã xong."""
        old = {x["id"]: x for x in self._plan}
        self._plan = [old.get(sid) or {"id": sid, "name": name, "status": "cho", "detail": "", "out": ""}
                      for sid, name in steps]
        self._save(status=DANG_CHAY, started_at=datetime.now(timezone.utc), note="")

    def done(self, sid: str) -> bool:
        return self._step(sid)["status"] in ("xong", "bo_qua")

    @contextlib.contextmanager
    def step(self, sid: str, detail: str = ""):
        st = self._step(sid)
        st.update(status="dang_chay", detail=detail, started=_now(), sub=None)
        t0 = time.monotonic()
        self._save(current=sid, note="")
        self.logline(f"Bắt đầu: {st['name']}")
        try:
            yield StepHandle(self, sid)
        except (Cancelled, Paused):
            raise
        except Exception as e:
            st.update(status="loi", detail=str(e)[:300], ended=_now(), ms=int((time.monotonic() - t0) * 1000))
            self._save()
            raise
        st.update(status="xong", ended=_now(), ms=int((time.monotonic() - t0) * 1000), sub=None)
        if st.get("detail", "").startswith("Đang"):
            st["detail"] = ""
        self._save(note="")
        self.logline(f"Xong: {st['name']} ({st['ms'] / 1000:.1f} giây)")

    def skip(self, sid: str, reason: str):
        self._step(sid).update(status="bo_qua", detail=reason[:300])
        self._save()

    def confirm(self, sid: str, payload: dict, message: str):
        """Dừng chờ người dùng xác nhận/điều chỉnh (ví dụ dàn ý). Người dùng gửi lại qua API /tasks/{id}/confirm."""
        st = self._step(sid)
        st.update(status="cho_xac_nhan", detail=message[:300])
        self.state["awaiting"] = sid
        self.state[f"confirm_{sid}"] = payload
        self._save(status=CHO_XAC_NHAN, state=self.state, note=message[:300])
        self.logline(f"Chờ xác nhận: {st['name']}")
        raise Paused()

    def confirmed(self, sid: str) -> dict | None:
        """Dữ liệu người dùng đã xác nhận cho bước sid (None nếu chưa)."""
        return self.state.get(f"confirmed_{sid}")

    # ------------------------------------------------------------ gọi mô hình
    def _before_llm(self):
        self.check_cancel()
        waited = wait_idle(on_wait=lambda s: self.note(
            f"Đang nhường máy chủ mô hình cho hỏi đáp trực tiếp ({int(s)} giây)…"))
        if waited > 1:
            self.note("")

    def llm_json(self, messages, schema: dict, task: str, max_tokens: int = 800, small: bool = False):
        self._before_llm()
        return self.llm.chat_json(messages, schema=schema, model=S.model_small if small else S.model_main,
                                  max_tokens=max_tokens, task=task)

    def llm_text(self, messages, task: str, max_tokens: int = 1200, temperature: float = 0.2) -> str:
        self._before_llm()
        return self.llm.chat(messages, model=S.model_main, max_tokens=max_tokens, temperature=temperature, task=task)

    # ------------------------------------------------------------ kết thúc
    def finish(self, result: str, artifacts: dict):
        self._save(status=XONG, result=result, artifacts=artifacts, warnings=self.warnings, progress=100,
                   current="", note="", finished_at=datetime.now(timezone.utc))
        self.logline("Hoàn thành tác vụ")


def execute(task_id: str, handlers: dict):
    """Chạy (hoặc chạy tiếp) một tác vụ. Gọi từ tiến trình nền (Celery)."""
    t0 = time.monotonic()
    with session() as s:
        t = s.get(Task, task_id)
        if not t or t.status in (XONG, DA_HUY, CHO_XAC_NHAN):
            return
        kind = t.kind
    ctx = Ctx(task_id)
    status = XONG
    try:
        handlers[kind](ctx)
    except Paused:
        status = CHO_XAC_NHAN
    except Cancelled:
        status = DA_HUY
        with session() as s:
            t = s.get(Task, task_id)
            if t is not None:
                t.note, t.finished_at = "Đã hủy theo yêu cầu", datetime.now(timezone.utc)
    except Exception as e:  # lỗi: lưu nguyên nhân để người dùng biết và chạy lại
        status = LOI
        log.exception("Tác vụ %s lỗi", task_id)
        with session() as s:
            t = s.get(Task, task_id)
            if t is not None and t.status != DA_HUY:
                t.status, t.error, t.note = LOI, f"{type(e).__name__}: {e}"[:2000], ""
                t.warnings = ctx.warnings
                t.finished_at = datetime.now(timezone.utc)
    record("tel:task", kind=kind, status=status, ms=round((time.monotonic() - t0) * 1000),
           user=ctx.user.username, task_id=task_id)
