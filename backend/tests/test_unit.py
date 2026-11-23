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


# ---------------------------------------------------------------- 1.3.0
def test_guard_secrets_bypass_and_stamps():
    from aicommon.guard import check, stamp_level
    assert check("mã PIN của tôi là 12345678 sao không ký được").kind == "bi_mat"
    assert check("-----BEGIN PRIVATE KEY-----\nMIIE...").kind == "bi_mat"
    assert check("mật khẩu: Abc@12345") .kind == "bi_mat"
    assert check("quên mã PIN thì xử lý thế nào?") is None
    assert check("mã PIN là gì?") is None
    assert check("làm sao bẻ khóa mã PIN của USB Token").kind == "vuot_bao_mat"
    assert check("cách trích xuất khóa bí mật từ USB Token").kind == "vuot_bao_mat"
    assert check("quy định xử lý hành vi vượt qua xác thực là gì") is None  # câu hỏi về quy định: hợp lệ
    assert stamp_level("Tài liệu tối mật được bảo quản thế nào?") == 0
    assert stamp_level("TỐI MẬT\n\nKế hoạch …") == 2 and stamp_level("Độ mật: Mật") == 1
    assert check("TUYỆT MẬT\nnội dung").kind == "do_mat"


def test_clarify_rules():
    from services.orchestrator import clarify as C
    assert C.before_search("bị lỗi rồi", "ho_tro", [])["reason"] == "thieu_doi_tuong"
    r = C.before_search("USB Token bị lỗi", "ho_tro", [])
    assert r["reason"] == "thieu_trieu_chung" and any("PIN" in o["label"] for o in r["options"])
    assert C.before_search("USB Token cắm vào máy tính không nhận, đèn không sáng", "ho_tro", []) is None
    assert C.before_search("hướng dẫn", "tra_cuu", [])["reason"] == "qua_ngan"
    assert C.before_search("thời hạn thu hồi thiết bị hư hỏng", "tra_cuu", []) is None
    assert C.before_search("còn đơn vị kia?", "tra_cuu", [{"role": "user", "content": "x"}]) is None
    hits = [{"doc_id": f"d{i}", "title": f"T{i}", "breadcrumb": "A › B", "rerank_score": -1.0 - i * .3} for i in range(4)]
    assert C.scattered(hits)["reason"] == "phan_tan"
    hits[0]["rerank_score"] = 5.0
    assert C.scattered(hits) is None
    assert C.merge("Máy không nhận?", "USB Token") == "Máy không nhận – USB Token"


def test_quality_algorithms():
    from services.agent.quality import cluster_questions, content_issues, extract_facts, number_conflicts
    f = extract_facts("2. Thiết bị hư hỏng phải được thu hồi trong thời hạn 07 ngày làm việc kể từ ngày phát hiện.")
    assert f and f[0]["key"] == "hu hong thu hoi" and f[0]["val"] == 7 and f[0]["unit"] == "ngay lam viec"
    docs = [{"doc_id": "B1", "track": "B", "title": "QĐ", "text": "Thiết bị hư hỏng phải được thu hồi trong thời hạn 07 ngày làm việc."},
            {"doc_id": "A1", "track": "A", "title": "Sổ tay", "text": "Thiết bị hư hỏng được thu hồi trong vòng 10 ngày làm việc."},
            {"doc_id": "A2", "track": "A", "title": "Khác", "text": "Thiết bị hư hỏng được thu hồi trong vòng 07 ngày làm việc."}]
    cs = number_conflicts(docs)
    assert len(cs) == 1 and cs[0]["b"]["doc_id"] == "A1"
    assert not number_conflicts([d | {"track": "A"} for d in docs])  # chỉ so với văn bản chuẩn
    cl = cluster_questions([{"question": "quy trình cấp chứng thư số"}, {"question": "quy trình cấp chứng thư số mới"},
                            {"question": "máy in hỏng"}])
    assert len(cl[0]) == 2
    assert "nội dung rất ngắn" in content_issues("abc")[0]


def test_agent_docs_extraction_rank_quotes():
    from services.agent import docs as D
    md = ("# Kế hoạch\n\n## II. Nội dung\n\n1. Phòng Kỹ thuật chủ trì rà soát danh sách, hoàn thành trước ngày 15/01/2027.\n"
          "2. Các đơn vị báo cáo kết quả theo Quyết định 15/QĐ-ĐVA trong thời hạn 05 ngày làm việc.\n\n## III. Khác\n\nNội dung khác về mạng.\n")
    d = D.Doc("VB", "Kế hoạch", md, {})
    dl = D.deadlines(d)
    assert any("15/01/2027" in " ".join(x["moc"]) for x in dl) and any("05 ngày làm việc" in x["moc"] for x in dl)
    asg = D.assignments(d)
    assert asg[0]["chu_the"].startswith("Phòng Kỹ thuật") and asg[0]["hanh_dong"] == "chủ trì"
    assert D.references(d) == ["15/QĐ-ĐVA"]
    top = D.rank("báo cáo kết quả thời hạn", D.passages(d), k=1)
    assert "báo cáo" in top[0][1]["text"]
    assert D.quote_ok("Phòng Kỹ thuật chủ trì rà soát danh sách", md)
    assert not D.quote_ok("Phòng Tài chính chủ trì cấp kinh phí bổ sung", md)


def test_draft_compose_clean_and_cited():
    from services.agent.draft import compose
    tpl = {"ten_loai": "Tờ trình", "the_thuc": "# {ten_loai_hoa}\n**{trich_yeu}**", "trich_yeu_mau": "Về việc {chu_de}"}
    outline = [{"tieu_de": "I. Sự cần thiết"}]
    written = {"0": {"text": "Theo quy định, thiết bị dùng tối đa 05 năm [S1]. Ý chưa có căn cứ *(chưa tìm thấy trong nguồn)*"}}
    src = [{"label": "S1", "title": "QĐ 15", "breadcrumb": "Điều 3", "so_hieu": "15/QĐ-ĐVA", "nguon": "B"}]
    cited, clean = compose({"chu_de": "cấp thiết bị"}, tpl, outline, written, src, None)
    assert "[S1]" in cited and "Phụ lục căn cứ" in cited and "Về việc cấp thiết bị" in cited
    assert "[S1]" not in clean and "chưa tìm thấy" not in clean and "DỰ THẢO" in clean


def test_monitor_percentiles_and_buckets():
    from services.audit.monitor import bucketize, pct
    assert pct([1, 2, 3, 4], .5) == 2.5 and pct([], .9) is None
    b = bucketize([{"ts": 5}, {"ts": 95}], 0, 100, n=10)
    assert len(b[0]["rows"]) == 1 and len(b[9]["rows"]) == 1


def _use_repo_resources(monkeypatch):
    """Dùng skills/, glossary/ của mã nguồn (không phụ thuộc biến môi trường của bộ chạy thử)."""
    import pathlib

    from aicommon.config import get_settings
    root = pathlib.Path(__file__).resolve().parents[2]
    monkeypatch.setenv("SKILLS_DIR", str(root / "skills"))
    monkeypatch.setenv("GLOSSARY_FILE", str(root / "glossary" / "thuat-ngu.md"))
    get_settings.cache_clear()
    return get_settings


def test_co_yeu_skills_criteria_and_domain_context(monkeypatch):
    gs = _use_repo_resources(monkeypatch)
    try:
        from aicommon.resources import domain_context, expired_laws
        from services.agent.criteria import criteria_sets, get_criteria_set, get_draft_template
        cs = get_criteria_set(None)  # bộ mặc định
        assert cs["name"] == "phan-tich-co-yeu" and len(cs["items"]) == 20
        assert all(i["can_cu"] and i["tu_khoa"] for i in cs["items"])  # mọi tiêu chí đều có căn cứ đối chiếu
        assert criteria_sets()[0]["mac_dinh"] and "phan-tich-bmtt-cy-cts" not in {s["name"] for s in criteria_sets()}
        ctx = domain_context()
        assert "khoản 3 Điều 22" in ctx and "mật mã dân sự" in ctx and len(ctx.split()) < 800
        assert {x["so_hieu"] for x in expired_laws()} >= {"86/2015/QH13", "24/2018/QH14", "33/2001/PL-UBTVQH10"}
        # bộ kỹ năng THAY THẾ bộ cũ: đúng danh sách kỹ năng cũ (đã viết lại) + bối cảnh ngành, không thêm mẫu mới
        from aicommon.resources import list_skills
        assert {s["name"] for s in list_skills()} == {
            "nganh-co-yeu", "phan-tich-co-yeu", "phan-tich-chung", "soan-to-trinh", "soan-bao-cao-de-xuat",
            "soan-ke-hoach", "soan-cong-van-gop-y", "tom-tat-van-ban", "tong-hop-bao-cao-chung",
            "tong-hop-bao-cao-tuan", "tong-hop-y-kien"}
        for s in list_skills():  # mọi kỹ năng đều đã viết lại theo hai luật
            text = s["body"] + str(s["meta"])
            assert "Luật Cơ yếu" in text or "Điều" in text, s["name"]
        for name in ("soan-to-trinh", "soan-bao-cao-de-xuat", "soan-ke-hoach", "soan-cong-van-gop-y"):
            tpl = get_draft_template(name)
            assert tpl and tpl["the_thuc"] and len(tpl["dan_y"]) >= 3, name
        assert all(i["can_cu"] for i in get_criteria_set("phan-tich-chung")["items"])
        cv = get_draft_template("soan-cong-van-gop-y")
        assert cv["gop_y"] and cv["che_do"] == ["tra_loi", "gop_y"]  # tham gia ý kiến: hình thức của Công văn
        monkeypatch.setenv("DOMAIN_CONTEXT", "0")
        assert domain_context() == ""
    finally:
        monkeypatch.undo()
        gs.cache_clear()


def test_expired_legal_basis_detected_without_model(monkeypatch):
    gs = _use_repo_resources(monkeypatch)
    try:
        from services.agent import docs as D
        from services.agent.analyze import expired_refs
        md = ("Căn cứ Luật Cơ yếu số 05/2011/QH13; Luật An toàn thông tin mạng số 86/2015/QH13; "
              "Luật số 35/2018/QH14 và Luật An ninh mạng số 116/2025/QH15.")
        refs = D.references(D.Doc("X", "X", md, {}))
        assert {"05/2011/QH13", "86/2015/QH13", "35/2018/QH14", "116/2025/QH15"} <= set(refs)
        ex = expired_refs(md, refs)
        assert set(ex) == {"86/2015/QH13", "35/2018/QH14"}  # 35/2018 chỉ báo khi đi kèm 86/2015
        assert ex["86/2015/QH13"]["thay_the_boi"].endswith("116/2025/QH15")
        # chỉ có 35/2018 (sửa nhiều luật) → không báo; ghi tên không số hiệu → nhận diện theo tên
        assert expired_refs("Theo Luật số 35/2018/QH14.", ["35/2018/QH14"]) == {}
        ex2 = expired_refs("Thực hiện Pháp lệnh Cơ yếu, đơn vị …", [])
        assert list(ex2) == ["ten:Pháp lệnh Cơ yếu"]
    finally:
        monkeypatch.undo()
        gs.cache_clear()


def test_draft_routing_co_yeu_templates():
    from services.orchestrator.pipelines import _RE_DRAFT, DRAFT_MAP
    pick = lambda q: next((m for k, m in DRAFT_MAP if k in q.lower()), "soan-bao-cao-de-xuat")  # noqa: E731
    assert _RE_DRAFT.search("Soạn báo cáo sự cố mất USB Token tại Phòng A")
    assert pick("Soạn báo cáo sự cố mất USB Token") == "soan-bao-cao-de-xuat"
    assert pick("Soạn báo cáo kết quả tự kiểm tra an ninh mạng năm 2026") == "soan-bao-cao-de-xuat"
    assert pick("Soạn văn bản đề nghị triển khai sản phẩm mật mã cho Phòng B") == "soan-bao-cao-de-xuat"
    assert pick("Soạn tờ trình mua sắm máy chủ") == "soan-to-trinh"
    assert not _RE_DRAFT.search("Lập báo cáo tổng hợp quý III")  # tổng hợp không bị bắt nhầm sang soạn thảo


def test_exact_resolve_law_by_name_and_lead_in():
    """“Khoản 3 Điều 22 Luật Cơ yếu”: luật được gọi theo TÊN, không ghi số hiệu."""
    import pathlib

    from services.exact.kb import KB, Doc
    from services.orchestrator.pipelines import doc_name
    root = pathlib.Path(__file__).resolve().parents[2] / "kb-nganh" / "van-ban"
    kb = KB.__new__(KB)  # không kết nối PostgreSQL, không cần kho git
    kb.docs, kb.sections = {}, {}
    for f in ("LUAT-CO-YEU-2011.md", "LUAT-AN-NINH-MANG-2025.md"):
        text = insert_ids(f[:-3], (root / f).read_text(encoding="utf-8"))
        from aicommon.markdown import split_frontmatter
        meta, _, _ = split_frontmatter(text)
        secs, lines = parse_sections(meta["id"], text)
        d = Doc(meta["id"], f, meta, secs, lines, {s.id: s for s in secs})
        kb.docs[d.doc_id] = d
        kb.sections.update({s.id: (d, s) for s in secs})
    assert kb.resolve("Nguyên văn khoản 3 Điều 22 Luật Cơ yếu") == ["LUAT-CO-YEU-2011.D22.K3"]
    assert kb.resolve("Điều 11 Luật An ninh mạng") == ["LUAT-AN-NINH-MANG-2025.D11"]
    assert kb.resolve("Điều 5 khoản 2") == []  # nhiều văn bản, không rõ văn bản nào → không đoán
    assert doc_name({"loai": "luat", "ten": "Luật Cơ yếu", "so_hieu": "05/2011/QH13"}) == "Luật Cơ yếu số 05/2011/QH13"


def test_gopy_positions_terms_definitions_and_compose(monkeypatch):
    """Tham gia ý kiến: vị trí điều/khoản, thuật ngữ, định nghĩa, đoạn ứng viên, kết cấu công văn – không cần mô hình."""
    import pathlib

    from aicommon.markdown import normalize_vn_structure
    gs = _use_repo_resources(monkeypatch)
    try:
        from services.agent import gopy as G
        md = normalize_vn_structure((pathlib.Path(__file__).parent / "fixtures" / "du-thao-gop-y.md").read_text(encoding="utf-8"))
        pos = G.positions(md)
        assert any(p == "Khoản 1 Điều 5" and "Bộ Công an" in ln for p, ln in pos)
        assert any(p == "Điểm a khoản 2 Điều 5" for p, _ in pos)
        assert next(p for p, ln in pos if "86/2015/QH13" in ln) == "Phần căn cứ"
        sk, cfg = G.config()
        assert [a["id"] for a in cfg["khia_canh"]] == ["thuat_ngu", "can_cu", "nhiem_vu", "ky_thuat"]
        # 1. thuật ngữ theo danh mục: "sản phẩm mã hóa", "Ban Cơ yếu" (thiếu "Chính phủ"), "an toàn thông tin mạng"
        t = G.term_rules(pos, cfg["thuat_ngu"])
        bad = {x["nhan_xet"].split("“")[1].split("”")[0] for x in t}
        assert {"sản phẩm mã hóa", "Ban Cơ yếu"} <= bad and "An toàn thông tin mạng" not in bad, bad
        assert all(x["vi_tri"] and x["can_cu"] for x in t)
        # định nghĩa trong điều "Giải thích từ ngữ"
        defs = G.draft_definitions(md)
        assert defs[0][:2] == ("Khoản 1 Điều 2", "Mật mã dân sự")
        # 2. đoạn ứng viên khía cạnh nhiệm vụ / kỹ thuật – gom theo vị trí, giữ thứ tự dự thảo
        nv = G.candidate_passages(pos, cfg["khia_canh"][2]["tu_khoa"], 8)
        assert [c["vi_tri"] for c in nv] == ["Khoản 1 Điều 2", "Khoản 1 Điều 5"]  # thứ tự trong dự thảo
        kt = G.candidate_passages(pos, cfg["khia_canh"][3]["tu_khoa"], 8)
        assert any(c["vi_tri"] == "Khoản 2 Điều 5" for c in kt)
        assert G._cite_ok("khoản 3 Điều 22 Luật Cơ yếu", "… Điều 22. Tổ chức …") and not G._cite_ok("Điều 99", "Điều 22")
        # 3. kết cấu công văn: Căn cứ → Nội dung tham gia ý kiến → Đề xuất, kiến nghị; phụ lục bảng đề xuất chỉnh sửa
        final = {"y_kien_chung": "Đơn vị A cơ bản nhất trí.", "kien_nghi": ["Đề nghị lấy ý kiến Ban Cơ yếu Chính phủ"],
                 "muc": [{**t[0], "chon": True}, {**t[1], "chon": False}]}
        cv = {"so_hieu": "12/CV-BTP", "ngay": "2026-11-02", "co_quan": "Bộ Tư pháp"}
        sach, kem = G.compose({"don_vi": "Đơn vị A"}, sk, cfg, "dự thảo Nghị định quy định về X", cv, final, [], [])
        i1, i2, i3 = sach.index("## 1. Căn cứ"), sach.index("## 2. Nội dung tham gia ý kiến"), sach.index("## 3. Đề xuất, kiến nghị")
        assert i1 < i2 < i3
        assert "Thực hiện đề nghị của Bộ Tư pháp tại Công văn số 12/CV-BTP ngày 02/11/2026" in sach
        assert "2.1. Ý kiến chung" in sach and "2.2. Về thuật ngữ chuyên môn" in sach
        assert t[1]["nhan_xet"] not in sach  # ý kiến bị bỏ chọn không đưa vào
        assert "BẢNG TỔNG HỢP ĐỀ XUẤT CHỈNH SỬA" in sach and "Kính gửi: Bộ Tư pháp" in sach
        # không có kiến nghị → bỏ hẳn mục 3
        sach2, _ = G.compose({"don_vi": "Đơn vị A"}, sk, cfg, "dự thảo X", {}, {**final, "kien_nghi": []}, [], [])
        assert "## 3." not in sach2 and "Đơn vị A đã nghiên cứu dự thảo X" in sach2
    finally:
        monkeypatch.undo()
        gs.cache_clear()


def test_precedent_helpers_and_archive_cleaning():
    from services.agent.archive import clean_for_archive, style_block
    md = "> *DỰ THẢO – do trợ lý AI hỗ trợ soạn.*\n\n# CÔNG VĂN\n\nNội dung.\n\n---\n## Phụ lục nguồn (bản làm việc)\n- x\n"
    out = clean_for_archive(md)
    assert "DỰ THẢO" not in out and "Phụ lục nguồn" not in out and "Nội dung." in out
    assert style_block([]) == ""
    assert "KHÔNG dùng làm căn cứ pháp lý" in style_block([{"so_hieu": "5/CV-A", "breadcrumb": "1", "text": "Ý kiến cũ."}])


def test_gopy_no_duplicate_findings(monkeypatch):
    import pathlib

    from aicommon.markdown import normalize_vn_structure
    gs = _use_repo_resources(monkeypatch)
    try:
        from services.agent import gopy as G
        md = normalize_vn_structure((pathlib.Path(__file__).parent / "fixtures" / "du-thao-gop-y.md").read_text(encoding="utf-8"))
        _, cfg = G.config()
        t = G.term_rules(G.positions(md), cfg["thuat_ngu"])
        assert not any("An toàn thông tin mạng" in x["nhan_xet"] for x in t)  # tên luật viện dẫn: để khía cạnh căn cứ
        a = {"vi_tri": "Khoản 1 Điều 5", "nhan_xet": "Giao Bộ Công an kiểm tra chưa đúng thẩm quyền.", "de_nghi_sua": "Sửa thành X."}
        assert G._duplicate(a, dict(a)) and not G._duplicate(a, {**a, "vi_tri": "Khoản 2 Điều 5"})
    finally:
        monkeypatch.undo()
        gs.cache_clear()
