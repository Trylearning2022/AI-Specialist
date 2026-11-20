"""Kiểm thử chỉ mục Luồng B trên PostgreSQL (cần PostgreSQL; dùng CSDL riêng ai_exact_test).

    EXACT_TEST_DB=postgresql+psycopg://ai:ai@127.0.0.1:55432/ai_exact_test python -m pytest -q tests/test_exact_pg.py
"""
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

DB = os.getenv("EXACT_TEST_DB") or os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://ai:ai@127.0.0.1:55432/ai").rsplit("/", 1)[0] + "/ai_exact_test"
SEED = Path(__file__).resolve().parents[2] / "kb-seed" / "van-ban"


@pytest.fixture(scope="module")
def kb():
    from tests.pgutil import recreate_db
    try:
        recreate_db(DB)
    except Exception as e:
        pytest.skip(f"Không có PostgreSQL kiểm thử: {e}")
    os.environ["DATABASE_URL"] = DB
    from aicommon.config import get_settings
    from aicommon.db import engine
    get_settings.cache_clear()
    engine.cache_clear()
    from services.exact.kb import KB
    root = Path(tempfile.mkdtemp())
    (root / "van-ban").mkdir()
    for f in SEED.glob("*.md"):
        shutil.copy(f, root / "van-ban" / f.name)
    k = KB(str(root))
    k.index.init()
    k.load()
    yield k
    shutil.rmtree(root, ignore_errors=True)


def ids(rows):
    return [r["section_id"] for r in rows]


def test_accent_insensitive_and_ranking(kb):
    a = kb.search("thiết bị hư hỏng thu hồi", 3)
    b = kb.search("thiet bi hu hong thu hoi", 3)
    assert ids(a) == ids(b) and ids(a)[0] == "QD-15-2026.D5.K2"
    assert a[0]["match"] == "and" and "07 ngày làm việc" in a[0]["snippet"]


def test_phrase_and_identifier_tokens(kb):
    r = kb.search('"mã PIN mặc định"', 3)
    assert r[0]["section_id"] == "QD-15-2026.D6.K2" and r[0]["match"] == "phrase"
    r = kb.search("15/QĐ-ĐVA thời hạn sử dụng", 5)  # số hiệu được tách token giống lúc lập chỉ mục
    assert "QD-15-2026.D5" in ids(r)


def test_or_and_fuzzy_fallback(kb):
    r = kb.search("chứng thư bảo mật xyzkhongco", 5)
    assert r and r[0]["match"] == "or"
    if kb.index.trgm:
        r = kb.search("khoi phuc du lieu may chu du phong", 3)
        assert r and r[0]["doc_id"] == "HD-03-2026"
        r = kb.search("saoo luuu tangg", 3)  # mọi từ đều gõ sai: chỉ tìm gần đúng (pg_trgm) mới thấy
        assert r and r[0]["match"] == "gan_dung" and r[0]["doc_id"] == "HD-03-2026"


def test_doc_filter(kb):
    assert kb.search("sao lưu", 5, doc_ids={"QD-15-2026"}) == [] or \
        all(x["doc_id"] == "QD-15-2026" for x in kb.search("sao lưu", 5, doc_ids={"QD-15-2026"}))
    assert kb.search("thiết bị", 5, doc_ids=set()) == []


def test_restart_skips_rebuild_and_incremental_commit(kb):
    assert kb.index.indexed_commit() == kb.commit
    assert kb.index.sync(kb.docs, kb.commit) is False  # khởi động lại: không dựng lại khi commit không đổi
    md = ("---\nid: QD-30-2026\nso_hieu: \"30/QĐ-ĐVA\"\nten: \"Quy định thử nghiệm PostgreSQL\"\n"
          "trang_thai: con_hieu_luc\nnguoi_duyet: kiem.duyet\n---\n\n# Quy định thử nghiệm\n\n### Điều 1. Lưu trữ\n"
          "<!-- id: QD-30-2026.D1 -->\n\nNhật ký truy cập được lưu trữ tối thiểu 12 tháng.\n")
    t0 = time.time()
    c = kb.commit_file("van-ban/QD-30-2026.md", md, "Thêm QĐ 30", "kiem.duyet", "kd@noibo.local")
    assert time.time() - t0 < 5 and kb.index.indexed_commit() == c
    r = kb.search("nhật ký truy cập lưu trữ tối thiểu", 3)
    assert r[0]["section_id"] == "QD-30-2026.D1"
    assert "30/QĐ-ĐVA" in (kb.root / "INDEX.md").read_text(encoding="utf-8")
    kb.commit_file("van-ban/QD-30-2026.md", "", "Thu hồi QĐ 30", "kiem.duyet", "kd@noibo.local", delete=True)
    assert "QD-30-2026.D1" not in ids(kb.search("nhật ký truy cập lưu trữ tối thiểu", 5))


def test_broken_git_dir_is_rejected(tmp_path):
    """.git còn sót nhưng hỏng (xóa dở trên Windows) phải báo lỗi rõ, không âm thầm chạy với kho rỗng."""
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="không hợp lệ"):
        from services.exact.kb import KB
        KB(str(tmp_path)).ensure_repo()
