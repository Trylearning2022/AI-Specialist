"""Bảng dữ liệu của agent-svc: tác vụ dài (agent), tệp đính kèm tạm, lượt và kết quả giám định dữ liệu."""
import uuid

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aicommon.db import Base, utcnow

# Trạng thái tác vụ
CHO, DANG_CHAY, CHO_XAC_NHAN, XONG, LOI, DA_HUY = "cho", "dang_chay", "cho_xac_nhan", "xong", "loi", "da_huy"
ACTIVE = (CHO, DANG_CHAY)
# gop_y: tác vụ bản 1.4.0 – nay "tham gia ý kiến dự thảo" là hình thức của Công văn trong phân hệ soạn thảo
KINDS = {"phan_tich": "Phân tích văn bản", "soan_thao": "Soạn văn bản tham mưu", "gop_y": "Soạn văn bản tham mưu",
         "tong_hop": "Tổng hợp báo cáo"}


def _id() -> str:
    return uuid.uuid4().hex


class Task(Base):
    """Một tác vụ dài, xử lý theo kế hoạch nhiều bước; tiến trình từng bước hiển thị cho người dùng."""
    __tablename__ = "agt_task"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    kind: Mapped[str] = mapped_column(String(24), index=True)          # phan_tich | soan_thao | tong_hop
    title: Mapped[str] = mapped_column(String(300))
    owner_sub: Mapped[str] = mapped_column(String(128), index=True)
    owner: Mapped[dict] = mapped_column(JSON, default=dict)            # UserCtx: tác vụ nền gọi dịch vụ với đúng quyền
    status: Mapped[str] = mapped_column(String(16), default=CHO, index=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    # Kế hoạch: [{id, name, status, detail, sub: [i, n], started, ended, ms}]
    plan: Mapped[list] = mapped_column(JSON, default=list)
    current: Mapped[str] = mapped_column(String(40), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)          # 0–100
    note: Mapped[str] = mapped_column(String(300), default="")         # dòng trạng thái tức thời
    state: Mapped[dict] = mapped_column(JSON, default=dict)            # kết quả trung gian, phục vụ chạy tiếp sau xác nhận
    result: Mapped[str] = mapped_column(Text, default="")              # Markdown kết quả cuối
    artifacts: Mapped[dict] = mapped_column(JSON, default=dict)        # kết quả có cấu trúc (phát hiện, dàn ý, bảng số liệu…)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    log: Mapped[list] = mapped_column(JSON, default=list)              # [{t, msg}] – nhật ký ngắn của tác vụ
    error: Mapped[str] = mapped_column(Text, default="")
    conversation_id: Mapped[str] = mapped_column(String(32), default="")
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)


class Upload(Base):
    """Tệp người dùng đính kèm để phân tích/tổng hợp. Không nạp vào kho tri thức; tự xóa sau AGENT_UPLOAD_TTL_H."""
    __tablename__ = "agt_upload"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    owner_sub: Mapped[str] = mapped_column(String(128), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    do_mat: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(500))
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class QaRun(Base):
    """Một lượt giám định chất lượng dữ liệu."""
    __tablename__ = "qa_run"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    trigger: Mapped[str] = mapped_column(String(16), default="lich")   # lich | thu_cong
    mode: Mapped[str] = mapped_column(String(16), default="heuristic")  # heuristic | llm
    status: Mapped[str] = mapped_column(String(16), default=DANG_CHAY)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)


class QaFinding(Base):
    """Một phát hiện về chất lượng dữ liệu. fingerprint giúp không tạo trùng giữa các lượt chạy."""
    __tablename__ = "qa_finding"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(12), default="trung_binh")  # cao | trung_binh | thap
    title: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str] = mapped_column(Text, default="")
    doc_ids: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)     # bằng chứng, đề xuất sửa (fix)
    status: Mapped[str] = mapped_column(String(16), default="moi", index=True)  # moi | da_xu_ly | bo_qua
    verified: Mapped[str] = mapped_column(String(16), default="")  # "" | xac_nhan | bac_bo (kết quả kiểm tra chéo bằng mô hình)
    resolution: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[str] = mapped_column(String(128), default="")
    run_id: Mapped[str] = mapped_column(String(32), default="")
    first_seen = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
