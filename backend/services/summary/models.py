import uuid

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aicommon.db import Base, utcnow


class SummaryJob(Base):
    __tablename__ = "sum_job"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    title: Mapped[str] = mapped_column(String(300))
    skill: Mapped[str] = mapped_column(String(100))
    doc_ids: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    owner_sub: Mapped[str] = mapped_column(String(128), index=True)
    owner: Mapped[dict] = mapped_column(JSON, default=dict)  # ngữ cảnh người dùng để tác vụ nền gọi dịch vụ với đúng quyền
    status: Mapped[str] = mapped_column(String(16), default="cho")  # cho | dang_chay | xong | loi
    progress: Mapped[str] = mapped_column(String(300), default="")
    result: Mapped[str] = mapped_column(Text, default="")
    table: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
