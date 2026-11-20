"""Bảng dữ liệu của orchestrator: hội thoại, tin nhắn, phản hồi người dùng."""
import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aicommon.db import Base, utcnow


def _id() -> str:
    return uuid.uuid4().hex


class Conversation(Base):
    __tablename__ = "orc_conversation"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_sub: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(300), default="Hội thoại mới")
    summary: Mapped[str] = mapped_column(Text, default="")
    summarized_upto: Mapped[int] = mapped_column(Integer, default=0)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "orc_message"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("orc_conversation.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(String(32), default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # nguồn, khối nguyên văn, kết quả kiểm chứng
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)


class Feedback(Base):
    __tablename__ = "orc_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("orc_message.id", ondelete="CASCADE"), index=True)
    user_sub: Mapped[str] = mapped_column(String(128))
    username: Mapped[str] = mapped_column(String(128), default="")
    rating: Mapped[int] = mapped_column(Integer)  # 1 đúng, -1 sai
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="moi")  # moi | da_xu_ly
    resolution: Mapped[str] = mapped_column(Text, default="")
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
