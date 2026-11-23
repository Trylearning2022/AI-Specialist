"""Kiểm thử tích hợp 1.3.0: tác vụ dài (agent-svc), giám định dữ liệu, giám sát – mô hình giả lập.

Chạy sau tests/run_stack.py (hoặc run_stack.sh):  python -m pytest -q tests/test_agent_e2e.py
"""
import time

from tests.test_e2e import H, c, seeded, sse, wait_job  # noqa: F401  (seeded: fixture nạp dữ liệu mẫu)

NEW_DOC = """KẾ HOẠCH
Triển khai cấp phát chứng thư số năm 2027

Số: 45/KH-BTM

## I. MỤC ĐÍCH, YÊU CẦU

Bảo đảm cán bộ được cấp chứng thư số đúng đối tượng, đúng quy định.

## II. NỘI DUNG

1. Phòng Kỹ thuật chủ trì rà soát danh sách cán bộ đề nghị cấp chứng thư số, hoàn thành trước ngày 15/01/2027.
2. Các đơn vị phải báo cáo số lượng thiết bị USB Token hư hỏng trong thời hạn 10 ngày làm việc.
3. Thiết bị hư hỏng được thu hồi trong vòng 10 ngày làm việc kể từ ngày phát hiện.

## III. TỔ CHỨC THỰC HIỆN

Văn phòng phối hợp tổng hợp, báo cáo kết quả theo Quyết định 15/QĐ-ĐVA và Hướng dẫn 88/HD-XYZ.
"""


def upload(name: str, text: str, user="canbo") -> str:
    r = c.post("/api/agent/uploads", headers=H(user), files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def wait_task(tid: str, until=("xong", "loi", "cho_xac_nhan", "da_huy"), user="canbo", timeout=180) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = c.get(f"/api/agent/tasks/{tid}", headers=H(user)).json()
        if t["status"] in until:
            return t
        time.sleep(1)
    raise TimeoutError(tid)


def test_analyze_uploaded_document_report_with_verified_quotes():
    uid = upload("ke-hoach-cts.md", NEW_DOC)
    t = c.post("/api/agent/tasks", headers=H("canbo"), json={"kind": "phan_tich", "input": {
        "upload_id": uid, "yeu_cau": "Đơn vị phải làm gì với thiết bị hư hỏng?"}}).json()
    t = wait_task(t["id"])
    assert t["status"] == "xong", t
    assert [p["id"] for p in t["plan"]] == ["tiep_nhan", "cau_truc", "tom_tat", "doi_chieu", "tieu_chi", "bao_cao", "kiem_chung"]
    assert all(p["status"] == "xong" for p in t["plan"]) and t["progress"] == 100
    a = t["artifacts"]
    # trích xuất bằng chương trình: thời hạn, nhiệm vụ, văn bản viện dẫn
    assert any("15/01/2027" in " ".join(d["moc"]) for d in a["deadlines"])
    assert any("Phòng Kỹ thuật" in x["chu_the"] for x in a["assignments"])
    refs = {r["so_hieu"]: r for r in a["refs"]}
    assert refs["15/QĐ-ĐVA"]["co_trong_kho"] and not refs["88/HD-XYZ"]["co_trong_kho"]
    # tiêu chí: trích dẫn bịa của mô hình bị loại, trích dẫn thật được giữ
    yes = [r for r in a["results"] if r["de_cap"]]
    assert yes and all("bịa" not in q for r in yes for q in r["trich_dan"])
    assert a["results"][0]["id"] == "yc"  # câu hỏi riêng của người dùng là tiêu chí đầu tiên
    assert any(not r["goi_mo_hinh"] for r in a["results"])  # tiêu chí không liên quan: không gọi mô hình
    md = t["result"]
    for h in ("## I. Tóm tắt", "## II. Các vấn đề liên quan", "## III. Nhiệm vụ, thời hạn", "## IV. Đối chiếu",
              "## V. Điểm cần lưu ý", "88/HD-XYZ"):
        assert h in md, h
    assert any("trích dẫn không có trong văn bản" in w for w in t["warnings"])
    # chủ sở hữu mới xem được
    assert c.get(f"/api/agent/tasks/{t['id']}", headers=H("kiemduyet1")).status_code == 404


def test_chat_with_attachment_creates_analysis_task():
    uid = upload("van-ban-moi.md", NEW_DOC)
    ev = sse({"message": "Phân tích văn bản này giúp tôi", "attachments": [uid]})
    fin = ev[-1][1]
    assert fin["route"] == "phan_tich" and fin["task"]["kind"] == "phan_tich"
    t = wait_task(fin["task"]["id"])
    assert t["status"] == "xong" and t["conversation_id"] == fin["conversation_id"]


def test_draft_outline_confirm_then_write():
    r = c.post("/api/chat/chat", headers=H("canbo"), json={
        "message": "Soạn tờ trình về việc cấp bổ sung thiết bị lưu khóa bí mật USB Token", "stream": False}).json()
    assert r["route"] == "soan_thao" and r["task"]["kind"] == "soan_thao"
    t = wait_task(r["task"]["id"])
    assert t["status"] == "cho_xac_nhan" and t["awaiting"] == "dan_y"
    phan = t["confirm"]["phan"]
    assert [p["tieu_de"] for p in phan][:2] == ["I. Sự cần thiết", "II. Nội dung đề nghị"]
    phan[0]["y"].append("Bổ sung: căn cứ Quyết định 15/QĐ-ĐVA")
    assert c.post(f"/api/agent/tasks/{t['id']}/confirm", headers=H("canbo"), json={"phan": phan}).json()["ok"]
    t = wait_task(t["id"], until=("xong", "loi"))
    assert t["status"] == "xong", t
    a = t["artifacts"]
    assert "TỜ TRÌNH" in t["result"] and "DỰ THẢO" in t["result"]
    assert "[S" in a["ban_can_cu"] and "[S" not in t["result"]  # bản sạch không có chỉ số căn cứ
    assert "Phụ lục căn cứ" in a["ban_can_cu"]
    assert any(s["nguon"] == "B" for s in a["sources"])  # có căn cứ từ văn bản chuẩn


def test_synthesis_from_uploaded_reports_numbers_by_code():
    u1 = upload("bc-don-vi-1.md", "# Báo cáo tuần Đơn vị 1\n\nTrong tuần xử lý 5 sự cố, cấp phát 12 thiết bị.\n")
    u2 = upload("bc-don-vi-2.md", "# Báo cáo tuần Đơn vị 2\n\nTrong tuần xử lý 3 sự cố, cấp phát 4 thiết bị.\n")
    ev = sse({"message": "Tổng hợp báo cáo chung từ các báo cáo này", "attachments": [u1, u2]})
    fin = ev[-1][1]
    assert fin["route"] == "tong_hop" and fin["task"]["kind"] == "tong_hop"
    t = wait_task(fin["task"]["id"], until=("xong", "loi"))
    assert t["status"] == "xong", t
    tbl = {(r["chi_tieu"], r["don_vi_tinh"]): r["tong"] for r in t["artifacts"]["table"]}
    assert tbl[("Số sự cố", "sự cố")] == 8 and tbl[("Số thiết bị", "thiết bị")] == 16
    assert any("123456" in w for w in t["warnings"])  # số liệu bịa của mô hình bị loại


def test_cancel_and_retry():
    uid = upload("dai.md", NEW_DOC * 3)
    t = c.post("/api/agent/tasks", headers=H("canbo"), json={"kind": "phan_tich", "input": {"upload_id": uid}}).json()
    assert c.post(f"/api/agent/tasks/{t['id']}/cancel", headers=H("canbo")).json()["ok"]
    t2 = wait_task(t["id"], until=("da_huy",))
    assert t2["status"] == "da_huy"
    assert c.post(f"/api/agent/tasks/{t['id']}/retry", headers=H("canbo")).json()["ok"]
    # hàng đợi agent chạy 1 tiến trình: chờ lâu hơn khi các bài kiểm thử trước còn tác vụ trong hàng đợi
    assert wait_task(t["id"], until=("xong", "loi"), timeout=480)["status"] == "xong"


def test_quality_agent_detects_conflict_missing_reference_and_gap():
    code = f"{int(time.time()) % 9000 + 100}/HD-ABC"  # mã viện dẫn chưa có trong kho (khác nhau mỗi lần chạy)
    # tài liệu tham khảo có thời hạn thu hồi khác văn bản chuẩn 15/QĐ-ĐVA (07 ngày làm việc)
    r = c.post("/api/ingest/jobs", headers=H("canbo"), files={"file": ("so-tay-token.md", (
        f"---\nten: \"Sổ tay sử dụng thiết bị lưu khóa\"\nso_hieu: \"{int(time.time())}/ST-PKT\"\nloai: tai_lieu_ky_thuat\n---\n\n# Sổ tay sử dụng thiết bị lưu khóa\n\n"
        "## Thu hồi\n\nThiết bị hư hỏng được thu hồi trong vòng 10 ngày làm việc.\n\n"
        f"Thực hiện theo Hướng dẫn {code}.\n").encode("utf-8"), "text/markdown")}, data={"do_mat": "0", "don_vi": "chung"}).json()
    j = wait_job(r["id"])
    c.post(f"/api/ingest/jobs/{j['id']}/approve", headers=H("kiemduyet1"), json={"track": "A"}).raise_for_status()
    assert wait_job(j["id"])["status"] == "da_duyet"
    # lỗ hổng tri thức: câu hỏi không có căn cứ
    c.post("/api/chat/chat", headers=H("canbo"), json={"message": "KHÔNG TRÍCH quy định về tàu ngầm hạt nhân", "mode": "tra_cuu", "stream": False})
    assert c.post("/api/agent/quality/runs", headers=H("canbo")).status_code == 403
    rid = c.post("/api/agent/quality/runs", headers=H("kiemduyet1")).json()["id"]
    for _ in range(120):
        sm = c.get("/api/agent/quality/summary", headers=H("kiemduyet1")).json()
        run = next(x for x in sm["runs"] if x["id"] == rid)
        if run["status"] != "dang_chay":
            break
        time.sleep(1)
    assert run["status"] == "xong", run
    assert run["mode"] == "llm"  # QA_LLM_MODE=on trong chế độ kiểm thử: tầng 2 kiểm tra chéo
    f = c.get("/api/agent/quality/findings", headers=H("kiemduyet1")).json()
    mt = [x for x in f if x["kind"] == "mau_thuan" and "hu hong thu hoi" in x["data"].get("key", "")]
    assert mt and mt[0]["verified"] == "xac_nhan" and mt[0]["severity"] == "cao"
    assert any(x["kind"] == "vien_dan" and code in x["title"] for x in f)
    assert any(x["kind"] == "lo_hong" for x in f)
    # đánh dấu bỏ qua → lượt sau không mở lại
    assert c.post(f"/api/agent/quality/findings/{mt[0]['id']}", headers=H("kiemduyet1"),
                  json={"status": "bo_qua", "resolution": "Sổ tay cũ, sẽ thu hồi"}).json()["ok"]
    rid2 = c.post("/api/agent/quality/runs", headers=H("kiemduyet1")).json()["id"]
    for _ in range(120):
        run = next(x for x in c.get("/api/agent/quality/summary", headers=H("kiemduyet1")).json()["runs"] if x["id"] == rid2)
        if run["status"] != "dang_chay":
            break
        time.sleep(1)
    again = c.get("/api/agent/quality/findings", headers=H("kiemduyet1"), params={"status": "bo_qua"}).json()
    assert any(x["id"] == mt[0]["id"] for x in again)


def test_monitor_overview_logs_and_queue():
    c.post("/api/chat/chat", headers=H("canbo"), json={"message": "Xin chào", "stream": False})
    assert c.get("/api/audit/monitor/overview", headers=H("canbo")).status_code == 403
    o = c.get("/api/audit/monitor/overview", headers=H("quantri"), params={"hours": 1}).json()
    assert o["kpi"]["cau_hoi"] >= 1 and o["kpi"]["nguoi_dung"] >= 1 and len(o["series"]) == 24
    assert o["kpi"]["goi_mo_hinh"] >= 1 and any(r["route"] == "chao_hoi" for r in o["routes"])
    assert any(t["kind"] == "phan_tich" for t in o["tasks"])
    assert "cpu_count" in o["system"]
    lg = c.get("/api/audit/monitor/logs", headers=H("quantri")).json()
    assert any(r.get("event") == "guard.block" or r.get("event") == "agent.create" for r in lg["rows"])
    h = c.get("/api/audit/monitor/health", headers=H("quantri")).json()
    assert {x["name"] for x in h["services"]} >= {"orchestrator", "agent", "mo-hinh"}
    q = c.get("/api/agent/queue", headers=H("quantri")).json()
    assert "by_status" in q and "interactive" in q


CY_DOC = """HƯỚNG DẪN
Bảo đảm an toàn thông tin trên hệ thống thông tin của đơn vị

Số: 12/HD-CY

Căn cứ Luật Cơ yếu số 05/2011/QH13; Luật An toàn thông tin mạng số 86/2015/QH13.

## I. YÊU CẦU

1. Thông tin bí mật nhà nước truyền đưa trên mạng máy tính phải được mã hóa bằng mật mã cơ yếu.
2. Phòng Kỹ thuật chủ trì đề nghị tổ chức cơ yếu cấp trên triển khai sản phẩm mật mã, hoàn thành trước ngày 30/6/2027.
"""


def test_analyze_co_yeu_criteria_cite_legal_basis_and_flag_expired_law():
    uid = upload("huong-dan-cy.md", CY_DOC)
    t = c.post("/api/agent/tasks", headers=H("canbo"), json={"kind": "phan_tich", "input": {"upload_id": uid}}).json()
    t = wait_task(t["id"])
    assert t["status"] == "xong", t
    a = t["artifacts"]
    assert a["criteria"]["name"] == "phan-tich-co-yeu"
    assert all(r.get("can_cu") for r in a["results"])
    # căn cứ hết hiệu lực: chương trình phát hiện, không cần mô hình
    refs = {r["so_hieu"]: r for r in a["refs"]}
    assert refs["86/2015/QH13"]["het_hieu_luc"] and not refs["05/2011/QH13"].get("het_hieu_luc")
    md = t["result"]
    assert "Hết hiệu lực từ 2026-07-01" in md and "116/2025/QH15" in md
    assert any("hết hiệu lực" in w for w in t["warnings"])


# ================================================================ 1.4.0: kho văn bản đã ban hành, tham gia ý kiến
PREC = """---
ten: "Công văn tham gia ý kiến dự thảo Nghị định về an toàn thông tin cơ quan nhà nước"
so_hieu: "{so}"
loai: cong_van
---

# Tham gia ý kiến dự thảo Nghị định về an toàn thông tin

Đơn vị đề nghị bổ sung quy định thông tin bí mật nhà nước truyền qua mạng phải được mã hóa bằng mật mã cơ yếu;
đề nghị cơ quan chủ trì lấy ý kiến Ban Cơ yếu Chính phủ đối với nội dung về mật mã.
"""


def _archive_precedent() -> str:
    so = f"{int(time.time()) % 9000 + 100}/CV-ĐVA"
    r = c.post("/api/ingest/jobs", headers=H("canbo"), data={"nhom": "van_ban_di"},
               files={"file": ("cv-gop-y-cu.md", PREC.format(so=so).encode(), "text/markdown")}).json()
    j = wait_job(r["id"])
    assert j["meta"]["nhom"] == "van_ban_di", j
    c.post(f"/api/ingest/jobs/{r['id']}/approve", headers=H("kiemduyet1"), json={"track": "A"}).raise_for_status()
    assert wait_job(r["id"])["status"] == "da_duyet"
    return so


def test_ingest_rejects_unknown_group():
    r = c.post("/api/ingest/jobs", headers=H("canbo"), data={"nhom": "linh_tinh"},
               files={"file": ("x.md", b"# X\n\nNoi dung thu nghiem du dai.\n", "text/markdown")})
    assert r.status_code == 422


def test_gop_y_structure_aspects_confirm_and_archive():
    import pathlib
    so_cu = _archive_precedent()
    fx = (pathlib.Path(__file__).parent / "fixtures" / "du-thao-gop-y.md").read_text(encoding="utf-8")
    uid = upload("du-thao-nghi-dinh.md", fx)
    # tham gia ý kiến = hình thức "gop_y" của mẫu Công văn trong phân hệ Soạn văn bản tham mưu
    cat = c.get("/api/agent/catalog", headers=H("canbo")).json()
    cv = next(d for d in cat["drafts"] if d["name"] == "soan-cong-van-gop-y")
    assert [m["id"] for m in cv["che_do"]] == ["tra_loi", "gop_y"]
    assert all(not d["che_do"] for d in cat["drafts"] if d["name"] != "soan-cong-van-gop-y")
    t = c.post("/api/agent/tasks", headers=H("canbo"), json={"kind": "soan_thao", "input": {
        "mau": "soan-cong-van-gop-y", "che_do": "gop_y",
        "upload_id": uid, "cv_co_quan": "Bộ Tư pháp", "cv_so_hieu": "12/CV-BTP", "cv_ngay": "2026-11-02",
        "don_vi": "Ban Cơ yếu Đơn vị A", "nguoi_ky": "TRƯỞNG BAN – Nguyễn Văn A"}}).json()
    assert t["kind"] == "soan_thao" and t["title"].startswith("Công văn: Tham gia ý kiến"), t
    t = wait_task(t["id"])
    assert t["status"] == "cho_xac_nhan" and t["awaiting"] == "tong_hop" and t["che_do"] == "gop_y", t
    assert "confirm_sources" not in t  # không phải màn hình duyệt dàn ý
    assert t["title"] == "Công văn: Tham gia ý kiến dự thảo Nghị định quy định về bảo đảm an toàn thông tin trong cơ quan nhà nước"
    assert [p["id"] for p in t["plan"]] == ["tiep_nhan", "thuat_ngu", "can_cu", "nhiem_vu", "ky_thuat", "tong_hop", "hoan_thien"]
    cf = t["confirm"]
    by = {}
    for m in cf["muc"]:
        by.setdefault(m["khia_canh"], []).append(m)
    # thuật ngữ (chương trình): danh mục cách viết cần tránh
    assert any("sản phẩm mã hóa" in m["nhan_xet"] for m in by["thuat_ngu"])
    # căn cứ (chương trình): hết hiệu lực; thiếu Luật Cơ yếu, Luật Giao dịch điện tử; 15/QĐ-ĐVA có trong kho → không góp ý
    cc = " ".join(m["nhan_xet"] + m["de_nghi_sua"] for m in by["can_cu"])
    assert "86/2015/QH13" in cc and "116/2025/QH15" in cc and "Luật Cơ yếu" in cc and "20/2023/QH15" in cc
    assert "15/QĐ-ĐVA" not in cc
    assert cc.count("116/2025/QH15") == 1  # đề nghị thay căn cứ hết hiệu lực, không lặp "chưa viện dẫn"
    keys = [(m["vi_tri"], m["nhan_xet"]) for m in cf["muc"]]
    assert len(keys) == len(set(keys))  # không trùng ý kiến giữa các khía cạnh
    # nhiệm vụ (mô hình): đúng vị trí; căn cứ không có trong quy định tra được → "(cần đối chiếu)"
    nv = by["nhiem_vu"][0]
    assert nv["vi_tri"] == "Khoản 1 Điều 5" and nv["can_cu"].endswith("(cần đối chiếu)")
    assert any(m["vi_tri"] == "Khoản 2 Điều 5" for m in by["ky_thuat"])
    assert not any(m["vi_tri"] == "Khoản 1 Điều 5" for m in by["ky_thuat"])
    assert cf["kien_nghi"] and cf["y_kien_chung"].startswith("Ban Cơ yếu Đơn vị A cơ bản nhất trí")
    assert any(p["so_hieu"] == so_cu for p in cf["tien_le"])  # ý kiến đơn vị đã tham gia trước đây
    # người dùng bỏ một ý kiến, sửa kiến nghị
    muc = [{**m, "chon": m is not by["thuat_ngu"][0]} for m in cf["muc"]]
    bo = by["thuat_ngu"][0]["nhan_xet"]
    r = c.post(f"/api/agent/tasks/{t['id']}/confirm", headers=H("canbo"), json={"gop_y": {
        "y_kien_chung": cf["y_kien_chung"], "muc": muc, "kien_nghi": ["Đề nghị lấy ý kiến Ban Cơ yếu Chính phủ"]}})
    assert r.status_code == 200, r.text
    t = wait_task(t["id"], until=("xong", "loi"))
    assert t["status"] == "xong", t
    md = t["result"]
    i1, i2, i3 = md.index("## 1. Căn cứ"), md.index("## 2. Nội dung tham gia ý kiến"), md.index("## 3. Đề xuất, kiến nghị")
    assert i1 < i2 < i3
    assert "Thực hiện đề nghị của Bộ Tư pháp tại Công văn số 12/CV-BTP ngày 02/11/2026" in md
    for h in ("Về thuật ngữ chuyên môn", "Về căn cứ pháp lý", "Về nhiệm vụ của ngành Cơ yếu", "Về nội dung kỹ thuật"):
        assert h in md, h
    assert bo not in md and "Tại khoản 1 Điều 5" in md and "BẢNG TỔNG HỢP ĐỀ XUẤT CHỈNH SỬA" in md
    assert "Phụ lục nguồn" in t["artifacts"]["ban_can_cu"] and "Phụ lục nguồn" not in md
    # đưa văn bản đã ban hành vào kho → tác vụ nạp nhóm van_ban_di chờ kiểm duyệt
    r = c.post(f"/api/agent/tasks/{t['id']}/archive", headers=H("canbo"), json={"so_hieu": "99/CV-ĐVA"}).json()
    j = wait_job(r["job_id"], user="canbo")
    assert j["meta"]["nhom"] == "van_ban_di" and j["meta"]["so_hieu"] == "99/CV-ĐVA" and j["status"] == "cho_duyet"
    assert c.post(f"/api/agent/tasks/{t['id']}/archive", headers=H("canbo"), json={}).status_code == 409


def test_chat_gop_y_routes_with_and_without_attachment():
    ev = sse({"message": "Soạn công văn tham gia ý kiến vào dự thảo Thông tư về chữ ký số"})
    fin = ev[-1][1]
    assert fin["route"] == "gop_y" and "đính kèm tệp dự thảo" in fin["answer"]
    uid = upload("du-thao-tt.md", "# DỰ THẢO THÔNG TƯ\n\n### Điều 1. Phạm vi\n\nThông tư quy định về chữ ký số chuyên dùng.\n")
    ev = sse({"message": "Tham gia ý kiến dự thảo này", "attachments": [uid]})
    fin = ev[-1][1]
    assert fin["route"] == "gop_y" and fin["task"]["kind"] == "soan_thao"
    t = c.get(f"/api/agent/tasks/{fin['task']['id']}", headers=H("canbo")).json()
    assert t["che_do"] == "gop_y" and t["input"]["mau"] == "soan-cong-van-gop-y"


def test_gop_y_mode_alias_autodetect_and_validation():
    uid = upload("du-thao-a.md", "# DỰ THẢO QUY CHẾ\n\n### Điều 1. Phạm vi\n\nQuy chế quy định sử dụng chữ ký số.\n")
    # kind "gop_y" của bản 1.4.0 → tác vụ soạn thảo, hình thức gop_y
    t = c.post("/api/agent/tasks", headers=H("canbo"), json={"kind": "gop_y", "input": {"upload_ids": [uid]}}).json()
    assert t["kind"] == "soan_thao"
    assert c.get(f"/api/agent/tasks/{t['id']}", headers=H("canbo")).json()["che_do"] == "gop_y"
    c.post(f"/api/agent/tasks/{t['id']}/cancel", headers=H("canbo"))
    # Công văn + tệp + chủ đề "tham gia ý kiến" → tự chọn hình thức gop_y
    uid = upload("du-thao-b.md", "# DỰ THẢO QUY CHẾ\n\n### Điều 1. Phạm vi\n\nQuy chế quy định sử dụng chữ ký số.\n")
    t = c.post("/api/agent/tasks", headers=H("canbo"), json={"kind": "soan_thao", "input": {
        "mau": "soan-cong-van-gop-y", "chu_de": "Tham gia ý kiến dự thảo Quy chế chữ ký số", "upload_ids": [uid]}}).json()
    assert c.get(f"/api/agent/tasks/{t['id']}", headers=H("canbo")).json()["che_do"] == "gop_y"
    c.post(f"/api/agent/tasks/{t['id']}/cancel", headers=H("canbo"))
    # hình thức gop_y với mẫu không có cấu hình tham gia ý kiến → từ chối; thiếu dự thảo → từ chối
    r = c.post("/api/agent/tasks", headers=H("canbo"), json={"kind": "soan_thao", "input": {
        "mau": "soan-to-trinh", "che_do": "gop_y", "upload_ids": [uid]}})
    assert r.status_code == 400
    r = c.post("/api/agent/tasks", headers=H("canbo"), json={"kind": "soan_thao", "input": {
        "mau": "soan-cong-van-gop-y", "che_do": "gop_y"}})
    assert r.status_code == 400 and "dự thảo" in r.text
