"""Chỉ mục tìm kiếm toàn văn của Luồng B trên PostgreSQL (tsvector + GIN, pg_trgm dự phòng).

Nguyên tắc:
- Kho Git Markdown vẫn là NGUỒN DUY NHẤT; bảng PostgreSQL chỉ là chỉ mục dựng lại được, không dùng vector.
- Chuẩn hóa tiếng Việt (NFC, bỏ dấu, chữ thường, tách token) thực hiện ở ứng dụng cho cả lúc lập chỉ mục
  và lúc truy vấn → không phụ thuộc extension unaccent (vốn không IMMUTABLE nên không dùng trực tiếp
  trong cột sinh/biểu thức chỉ mục được).
- Cấu hình 'simple' (không stemming, không stop-word) phù hợp tiếng Việt – ngôn ngữ đơn lập.
- Trọng số: A = số hiệu, tên văn bản, đường dẫn tiêu đề; B = nội dung riêng của mục.
"""
import contextlib
import logging
import re
import zlib

from sqlalchemy import Computed, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from aicommon.db import Base, engine, init_db, session
from aicommon.markdown import Section, section_text
from aicommon.text import nfc, tokens, unaccent

log = logging.getLogger("exact.pgindex")
LOCK_KEY = zlib.crc32(b"ai-local:exact-index")
GIT_LOCK_KEY = zlib.crc32(b"ai-local:exact-git")


@contextlib.contextmanager
def pg_lock(key: int):
    """Khóa advisory của PostgreSQL – dùng chung giữa mọi tiến trình, mọi container của exact-svc."""
    with engine().connect() as c:
        c.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
        try:
            yield
        finally:
            c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            c.commit()


def norm_tokens(text_: str) -> list[str]:
    """Token chuẩn hóa dùng chung cho lập chỉ mục và truy vấn (không dấu, chữ thường, chữ-số)."""
    return tokens(unaccent(nfc(text_)).lower())


def norm(text_: str) -> str:
    return " ".join(norm_tokens(text_))


class ExactSection(Base):
    __tablename__ = "exact_section"
    section_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(120), index=True)
    heading: Mapped[str] = mapped_column(Text)
    path: Mapped[list] = mapped_column(ARRAY(Text))
    kind: Mapped[str] = mapped_column(String(16))
    level: Mapped[int] = mapped_column(Integer)
    head_norm: Mapped[str] = mapped_column(Text)
    body_norm: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)  # nội dung riêng của mục (để trích đoạn hiển thị)
    tsv = mapped_column(TSVECTOR, Computed(
        "setweight(to_tsvector('simple'::regconfig, head_norm), 'A') || "
        "setweight(to_tsvector('simple'::regconfig, body_norm), 'B')", persisted=True))
    __table_args__ = (Index("ix_exact_section_tsv", "tsv", postgresql_using="gin"),)


class ExactIndexState(Base):
    __tablename__ = "exact_index_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)


class PgIndex:
    def __init__(self):
        self.trgm = False

    # ---------- khởi tạo ----------
    def init(self):
        eng = engine()
        if eng.dialect.name != "postgresql":
            raise RuntimeError("exact-svc yêu cầu PostgreSQL (DATABASE_URL=postgresql+psycopg://...)")
        init_db(tables=[ExactSection.__table__, ExactIndexState.__table__])
        with eng.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
            try:
                c.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                c.execute(text("CREATE INDEX IF NOT EXISTS ix_exact_section_trgm "
                               "ON exact_section USING gin (body_norm gin_trgm_ops)"))
            except Exception as e:  # không có quyền tạo extension: vẫn chạy, chỉ tắt tìm gần đúng
                log.warning("Không bật được pg_trgm (tìm gần đúng bị tắt): %s", e)
        with eng.connect() as c:
            self.trgm = bool(c.execute(text("SELECT 1 FROM pg_extension WHERE extname='pg_trgm'")).first())

    # ---------- đồng bộ từ kho Git ----------
    @staticmethod
    def _rows(doc) -> list[dict]:
        m = doc.meta
        title = f"{m.get('so_hieu', '')} {m.get('ten', '')}"
        heads = [s for s in doc.sections if s.kind == "heading"]
        rows = []
        for s in doc.sections:
            own_end = s.end
            for t in heads:  # chỉ lấy nội dung riêng của mục (không gồm mục con)
                if s.start < t.start < own_end:
                    own_end = t.start
                    break
            body = section_text(doc.lines, Section(s.id, s.level, s.heading, s.start, own_end, s.explicit))
            rows.append({"section_id": s.id, "doc_id": doc.doc_id, "heading": s.heading, "path": s.path,
                         "kind": s.kind, "level": s.level, "head_norm": norm(title + " " + " ".join(s.path)),
                         "body_norm": norm(body), "body": body})
        return rows

    def indexed_commit(self) -> str | None:
        with session() as s:
            st = s.get(ExactIndexState, "commit")
            return st.value.get("commit") if st else None

    def sync(self, docs: dict, commit: str, only: set[str] | None = None, force: bool = False) -> bool:
        """Đồng bộ chỉ mục với kho. only: chỉ các văn bản thay đổi; None: toàn bộ. Trả True nếu có ghi."""
        with session() as s:
            s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})  # một bộ ghi tại một thời điểm
            st = s.get(ExactIndexState, "commit")
            if not force and only is None and st and st.value.get("commit") == commit and commit:
                return False
            if only is None:
                s.execute(text("DELETE FROM exact_section"))
                targets = list(docs.values())
            else:
                s.execute(text("DELETE FROM exact_section WHERE doc_id = ANY(:ids)"), {"ids": list(only)})
                targets = [docs[d] for d in only if d in docs]
            rows = [r for d in targets for r in self._rows(d)]
            if rows:
                s.execute(ExactSection.__table__.insert(), rows)
            if st:
                st.value = {"commit": commit}
            else:
                s.add(ExactIndexState(key="commit", value={"commit": commit}))
        log.info("Đã đồng bộ chỉ mục PostgreSQL: %s văn bản, %d mục, commit %s",
                 "toàn bộ" if only is None else len(only), len(rows), commit[:10])
        return True

    # ---------- truy vấn ----------
    def search(self, query: str, limit: int, doc_ids: set[str] | None) -> list[dict]:
        if doc_ids is not None and not doc_ids:
            return []
        words = [w for w in norm_tokens(query) if len(w) > 1 or w.isdigit()]
        phrases = [norm(p) for p in re.findall(r'"([^"]+)"', query) if norm(p)]
        if not words and not phrases:
            return []
        # token đã chuẩn hóa chỉ gồm chữ-số ASCII → ghép biểu thức tsquery an toàn; vẫn truyền bằng tham số
        plans: list[tuple[str, str, str]] = []
        if phrases:
            plans.append(("phrase", " & ".join("(" + " <-> ".join(p.split()) + ")" for p in phrases), "fts"))
        plans.append(("and", " & ".join(words), "fts"))
        if len(words) > 1:
            plans.append(("or", " | ".join(words), "fts"))
        if self.trgm:
            plans.append(("gan_dung", " ".join(words), "trgm"))
        filt = "" if doc_ids is None else " AND doc_id = ANY(:docs)"
        params = {"n": limit * 2, "docs": list(doc_ids or [])}
        out, seen = [], set()
        with engine().connect() as c:
            for name, expr, kind in plans:
                if kind == "fts":
                    sql = ("SELECT section_id, doc_id, heading, path, body, "
                           "ts_rank_cd(tsv, q, 1) AS r FROM exact_section, to_tsquery('simple', :q) q "
                           f"WHERE tsv @@ q{filt} ORDER BY r DESC, length(body) ASC LIMIT :n")
                else:
                    c.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = 0.3"))
                    sql = ("SELECT section_id, doc_id, heading, path, body, "
                           "word_similarity(:q, body_norm) AS r FROM exact_section "
                           f"WHERE :q <% body_norm{filt} ORDER BY r DESC LIMIT :n")
                for row in c.execute(text(sql), {**params, "q": expr}):
                    if row.section_id in seen:
                        continue
                    seen.add(row.section_id)
                    out.append({"section_id": row.section_id, "doc_id": row.doc_id, "heading": row.heading,
                                "path": list(row.path), "score": float(row.r),
                                "snippet": " ".join(row.body.split())[:280],
                                "match": name})
                if len(out) >= limit:
                    break
        return out[:limit]
