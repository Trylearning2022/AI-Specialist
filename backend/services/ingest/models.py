"""Bảng dữ liệu phân hệ nạp: tác vụ nạp (job) và sổ đăng ký tài liệu."""
import uuid

from sqlalchemy import JSON, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aicommon.db import Base, utcnow

# Trạng thái tác vụ nạp. DANG_DUYET: đã bấm duyệt, tiến trình nền đang lập chỉ mục / ghi kho chuẩn (1.3.1).
MOI, DANG_XU_LY, CHO_DUYET, CHO_DUYET_CAP_2, DANG_DUYET, DA_DUYET, TU_CHOI, LOI = (
    "moi", "dang_xu_ly", "cho_duyet", "cho_duyet_cap_2", "dang_duyet", "da_duyet", "tu_choi", "loi")


class Job(Base):
    __tablename__ = "ing_job"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    filename: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(32), default="")
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default=MOI, index=True)
    uploader: Mapped[str] = mapped_column(String(128))
    uploader_units: Mapped[list] = mapped_column(JSON, default=list)
    original_path: Mapped[str] = mapped_column(String(500), default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    duplicates: Mapped[list] = mapped_column(JSON, default=list)
    target: Mapped[str] = mapped_column(String(2), default="")       # A | B
    approvals: Mapped[list] = mapped_column(JSON, default=list)      # [{user, at, track}]
    doc_id: Mapped[str] = mapped_column(String(120), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Document(Base):
    __tablename__ = "ing_document"
    doc_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    track: Mapped[str] = mapped_column(String(2))  # A | B
    title: Mapped[str] = mapped_column(String(500))
    so_hieu: Mapped[str] = mapped_column(String(120), default="", index=True)
    loai: Mapped[str] = mapped_column(String(40), default="khac", index=True)
    do_mat: Mapped[int] = mapped_column(Integer, default=0)
    don_vi: Mapped[list] = mapped_column(JSON, default=list)
    ngay_ban_hanh: Mapped[str] = mapped_column(String(10), default="")
    trang_thai: Mapped[str] = mapped_column(String(24), default="con_hieu_luc")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    job_id: Mapped[str] = mapped_column(String(32), default="")
    path: Mapped[str] = mapped_column(String(500), default="")
    commit: Mapped[str] = mapped_column(String(64), default="")
    minhash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
