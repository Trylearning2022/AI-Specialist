"""Kiểm thử đơn vị các thành phần lõi (không cần dịch vụ chạy)."""
from aicommon.markdown import chunk_markdown, insert_ids, normalize_vn_structure, parse_sections, section_text
from aicommon.text import detect_legacy, numbers, tcvn3_to_unicode, unaccent
from services.orchestrator.verifier import REFUSAL, check_citations, verify_a, verify_b

DOC = """---
id: QD-1-2026
so_hieu: "1/QĐ-X"
ten: "Thử"
---

# Thử

## Chương I. CHUNG
<!-- id: QD-1-2026.C1 -->

### Điều 1. Thời hạn
<!-- id: QD-1-2026.D1 -->

1. Thời hạn là 05 năm.
<!-- id: QD-1-2026.D1.K1 -->
2. Gia hạn tối đa 01 lần.
<!-- id: QD-1-2026.D1.K2 -->
"""


def test_sections_verbatim():
    secs, lines = parse_sections("QD-1-2026", DOC)
    by = {s.id: s for s in secs}
    assert section_text(lines, by["QD-1-2026.D1.K2"]) == "2. Gia hạn tối đa 01 lần."
    assert "<!--" not in section_text(lines, by["QD-1-2026.D1"])
    assert by["QD-1-2026.D1.K1"].parent == "QD-1-2026.D1"


def test_normalize_and_insert_ids():
    md = "QUYẾT ĐỊNH\n\nChương II\nTỔ CHỨC THỰC HIỆN\n\n**Điều 7. Trách nhiệm**\n\n1. Phòng A chủ trì.\n2. Phòng B phối hợp.\n"
    n = normalize_vn_structure(md)
    assert "## Chương II. TỔ CHỨC THỰC HIỆN" in n and "### Điều 7. Trách nhiệm" in n
    out = insert_ids("QD-9-2026", n)
    assert "<!-- id: QD-9-2026.C2 -->" in out and "<!-- id: QD-9-2026.D7.K2 -->" in out
    assert insert_ids("QD-9-2026", out) == out  # chèn lặp lại không thay đổi


def test_chunking_breadcrumb():
    chunks = chunk_markdown("QD-1-2026", DOC, title="Thử")
    assert chunks and all(c["breadcrumb"].startswith("Thử") for c in chunks)
    assert not any("<!--" in c["text"] for c in chunks)


def test_text_utils():
    assert unaccent("Đơn vị Kỹ thuật") == "Don vi Ky thuat"
    assert {"5", "1234.5", "7"} <= numbers("05 năm, 1.234,5 đồng và 7%")
    legacy = "Néi dung vÒ viÖc qu¶n lý thiÕt bÞ cña ®¬n vÞ"
    assert detect_legacy(legacy) == "tcvn3"
    assert tcvn3_to_unicode(legacy) == "Nội dung về việc quản lý thiết bị của đơn vị"
    assert detect_legacy("Nội dung tiếng Việt chuẩn Unicode") is None


def test_verifier():
    src = [{"text": "Thiết bị dùng tối đa 05 năm.", "breadcrumb": "QĐ 1"}]
    txt, rep = check_citations("Dùng 5 năm [1][3].", 1)
    assert txt == "Dùng 5 năm [1]." and rep.invalid_citations == [3]
    ans, rep = verify_a("Thiết bị dùng 05 năm [1].", src)
    assert rep.ok and ans.endswith("[1].")
    ans, rep = verify_a("Thiết bị dùng 10 năm [1].", src)
    assert not rep.ok and "10" in rep.bad_numbers
    ans, rep = verify_a("Không có trích dẫn.", src, strict=True)
    assert ans == REFUSAL
    cd, dg, rep = verify_b("Theo quy định:", "Thời hạn là 06 năm.", "1. Thời hạn là 05 năm.")
    assert dg == "" and not rep.ok
    cd, dg, rep = verify_b("Theo quy định:", "Thời hạn là 05 năm.", "1. Thời hạn là 05 năm.")
    assert dg and rep.ok


def test_numbers_inside_document_codes_are_not_evidence():
    """Trường hợp thực tế: mô hình tự tính 12 - 9 = 3; nguồn chỉ có "03" trong số hiệu 03/HD-PKT."""
    from services.orchestrator.verifier import check_numbers
    src = "Trong tuần đã xử lý 12 sự cố kỹ thuật, trong đó 9 sự cố về mạng nội bộ. Sao lưu theo Hướng dẫn 03/HD-PKT."
    assert check_numbers("Đã xử lý 12 sự cố, trong đó 9 sự cố mạng và 3 sự cố máy in [1].", src) == ["3"]
    assert check_numbers("Đã xử lý 12 sự cố; căn cứ Hướng dẫn 03/HD-PKT [1].", src) == []


# ---------------- Truy xuất, kiểm chứng (bản 1.2.0) ----------------
def test_chunk_table_keeps_header_in_every_part():
    rows = "".join(f"| Thiết bị số {i} cần kiểm tra định kỳ | {i * 7} |\n" for i in range(80))
    md = f"# Danh mục\n\n## Bảng thiết bị\n\n| Thiết bị | Số lượng |\n|---|---|\n{rows}"
    parts = [c for c in chunk_markdown("T", md, title="Danh mục", max_tokens=200) if "|" in c["text"]]
    assert len(parts) > 2
    for p in parts:
        lines = [ln for ln in p["text"].split("\n") if ln.startswith("|")]
        assert lines[0] == "| Thiết bị | Số lượng |"  # tiêu đề bảng lặp lại ở mọi phần


def test_heading_only_section_is_not_a_chunk():
    md = "# Quy định\n\n## Chương I\n\n### Điều 1. Phạm vi\n\nNội dung điều 1 áp dụng cho toàn đơn vị.\n"
    cs = chunk_markdown("Q", md, title="Quy định")
    assert len(cs) == 1 and "Chương I" in cs[0]["breadcrumb"] and "Nội dung điều 1" in cs[0]["text"]


def test_sparse_vector_matches_without_diacritics():
    from services.search.app import sparse_doc, sparse_query
    d = set(sparse_doc("Sự cố mất kết nối mạng nội bộ").indices)
    q = set(sparse_query("mat ket noi mang").indices)
    assert len(d & q) >= 4  # khớp qua thuật ngữ không dấu "~mat", "~ket"…


def test_grounding_fixes_wrong_citation_and_flags_unsupported():
    from services.orchestrator.verifier import UNSUPPORTED_MARK
    srcs = [{"text": "Phòng Văn phòng tiếp nhận và xử lý bảy sự cố máy in, máy tính văn phòng trong tuần.",
             "breadcrumb": "Báo cáo tuần Văn phòng"},
            {"text": "Thiết bị hư hỏng phải được thu hồi, bàn giao cho Phòng Kỹ thuật trong thời hạn quy định.",
             "breadcrumb": "Quy định quản lý thiết bị"}]
    ans = ("Thiết bị hư hỏng phải được thu hồi, bàn giao cho Phòng Kỹ thuật trong thời hạn quy định [1].\n"
           "Văn phòng tiếp nhận, xử lý bảy sự cố máy in, máy tính văn phòng.\n"
           "Đơn vị được trang bị thêm tàu ngầm hạt nhân phục vụ huấn luyện diễn tập dài ngày [2].")
    out, rep = verify_a(ans, srcs)
    lines = out.split("\n")
    assert lines[0].endswith("[2].") and rep.fixed_citations          # [1] → [2]: nội dung nằm ở nguồn 2
    assert lines[1].endswith("[1].")                                  # câu thiếu trích dẫn được bổ sung
    assert lines[2].endswith(UNSUPPORTED_MARK) and rep.unsupported    # câu không có trong nguồn bị đánh dấu
    assert rep.ok is False


def test_trim_truncated_answer_and_select_sources():
    from services.orchestrator.context import select_sources
    from services.orchestrator.pipelines import trim_to_complete
    assert trim_to_complete("Ý thứ nhất [1].\nÝ thứ hai đang viết dở thì") == "Ý thứ nhất [1]."
    long = {"text": "x " * 6000}
    kept = select_sources([{"text": "a " * 300}, long], budget=1500)
    assert len(kept) == 2 and kept[1]["cut"] is True                 # nguồn dài bị cắt bớt, không bị bỏ hẳn
