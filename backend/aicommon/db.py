"""Kết nối CSDL quan hệ (PostgreSQL; SQLite cho kiểm thử)."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache
def engine():
    url = get_settings().database_url
    kw = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    else:
        kw.update(pool_size=10, max_overflow=10)
    return create_engine(url, **kw)


@lru_cache
def _factory():
    return sessionmaker(bind=engine(), expire_on_commit=False)


DDL_LOCK = 7_310_420_260  # khóa advisory: tránh nhiều tiến trình cùng tạo bảng khi khởi động


def init_db(tables=None):
    eng = engine()
    if eng.dialect.name != "postgresql":
        Base.metadata.create_all(eng, tables=tables)
        return
    with eng.begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": DDL_LOCK})
        Base.metadata.create_all(c, tables=tables)


@contextmanager
def session():
    s = _factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
