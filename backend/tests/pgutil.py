"""Tiện ích kiểm thử: tạo lại CSDL PostgreSQL bằng SQLAlchemy (không cần lệnh psql – chạy được trên Windows)."""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def recreate_db(url: str):
    u = make_url(url)
    eng = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{u.database}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{u.database}"'))
    eng.dispose()


def ensure_db(url: str):
    u = make_url(url)
    eng = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": u.database}).first():
            c.execute(text(f'CREATE DATABASE "{u.database}"'))
    eng.dispose()
