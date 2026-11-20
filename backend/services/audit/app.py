"""audit-svc – ghi nhật ký kiểm toán chỉ-ghi-thêm, liên kết chuỗi băm chống sửa đổi.

Chạy 01 bản (single writer) để bảo đảm thứ tự chuỗi băm.
"""
import asyncio
import contextlib
import hashlib
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import Depends
from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from aicommon.app import create_app
from aicommon.audit import STREAM
from aicommon.config import get_settings
from aicommon.db import Base, init_db, session
from aicommon.security import UserCtx, require

log = logging.getLogger("audit")
S = get_settings()
GROUP, CONSUMER = "audit-writer", "audit-1"


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts = mapped_column(DateTime(timezone=True), index=True)
    ts_us: Mapped[int] = mapped_column(BigInteger)  # thời điểm (micro giây) dùng trong băm
    actor: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource: Mapped[str] = mapped_column(String(300), default="")
    service: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


def _canon(e: dict, prev: str) -> str:
    body = json.dumps({k: e[k] for k in ("ts_us", "actor", "action", "resource", "service", "detail")},
                      ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def write(events: list[dict]):
    with session() as s:
        last = s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(1).with_for_update()).first()
        prev = last.hash if last else "0" * 64
        for e in events:
            e = {"ts_us": int(float(e.get("ts", 0)) * 1_000_000), "actor": str(e.get("actor", ""))[:128], "action": str(e.get("action", ""))[:64],
                 "resource": str(e.get("resource", ""))[:300], "service": str(e.get("service", ""))[:40],
                 "detail": e.get("detail") or {}}
            h = _canon(e, prev)
            s.add(AuditLog(ts=datetime.fromtimestamp(e["ts_us"] / 1e6, timezone.utc), ts_us=e["ts_us"], actor=e["actor"], action=e["action"],
                           resource=e["resource"], service=e["service"], detail=e["detail"], prev_hash=prev, hash=h))
            prev = h


async def consume(stop: asyncio.Event):
    r = aioredis.Redis.from_url(S.redis_url)
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception:
        pass
    while not stop.is_set():
        try:
            resp = await r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=200, block=2000)
            for _, msgs in resp or []:
                events = [json.loads(m[b"data"]) for _, m in msgs]
                await asyncio.to_thread(write, events)
                await r.xack(STREAM, GROUP, *[mid for mid, _ in msgs])
        except Exception as e:
            log.error("Lỗi ghi nhật ký kiểm toán: %s", e)
            await asyncio.sleep(3)
    await r.aclose()


@contextlib.asynccontextmanager
async def lifespan(app):
    init_db()
    stop = asyncio.Event()
    task = asyncio.create_task(consume(stop))
    yield
    stop.set()
    await task


app = create_app("audit", lifespan=lifespan)


@app.get("/logs")
def logs(actor: str = "", action: str = "", resource: str = "", limit: int = 200,
         user: UserCtx = Depends(require("admin"))):
    with session() as s:
        q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
        if actor:
            q = q.where(AuditLog.actor == actor)
        if action:
            q = q.where(AuditLog.action.like(f"{action}%"))
        if resource:
            q = q.where(AuditLog.resource == resource)
        return [{"id": a.id, "ts": a.ts, "actor": a.actor, "action": a.action, "resource": a.resource,
                 "service": a.service, "detail": a.detail, "hash": a.hash} for a in s.scalars(q)]


@app.get("/verify")
def verify(user: UserCtx = Depends(require("admin"))):
    """Kiểm tra toàn vẹn chuỗi băm của nhật ký kiểm toán."""
    prev, n = "0" * 64, 0
    with session() as s:
        for a in s.scalars(select(AuditLog).order_by(AuditLog.id).execution_options(yield_per=1000)):
            e = {"ts_us": a.ts_us, "actor": a.actor, "action": a.action, "resource": a.resource,
                 "service": a.service, "detail": a.detail}
            if a.prev_hash != prev or _canon(e, prev) != a.hash:
                return {"ok": False, "broken_at": a.id, "checked": n}
            prev, n = a.hash, n + 1
    return {"ok": True, "checked": n}
