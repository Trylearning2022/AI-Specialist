"""Kiểm thử tích hợp end-to-end qua API Gateway (AUTH_MODE=dev, mô hình giả lập).

Chạy: tests/run_stack.sh && python -m pytest -q tests/test_e2e.py
"""
import io
import json
import os
import shutil
import time

import httpx
import pytest

GW = os.getenv("GW", "http://127.0.0.1:8100")
for _k, _v in {"INGEST_URL": "http://127.0.0.1:8104", "INTERNAL_SECRET": "test-secret",
               "SYSTEM_MAX_CLEARANCE": "1"}.items():
    os.environ.setdefault(_k, _v)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
c = httpx.Client(base_url=GW, timeout=120)


def H(u):
    return {"Authorization": f"Bearer dev-{u}"}


def wait_job(jid, user="kiemduyet1"):
    for _ in range(120):
        j = c.get(f"/api/ingest/jobs/{jid}", headers=H(user)).json()
        if j["status"] not in ("moi", "dang_xu_ly"):
            return j
        time.sleep(1)
    raise TimeoutError(jid)


def sse(payload, user="canbo"):
    events = []
    with c.stream("POST", "/api/chat/chat", headers=H(user), json=payload) as r:
        assert r.status_code == 200, r.read()
        ev = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                events.append((ev, json.loads(line[5:])))
    return events


@pytest.fixture(scope="session", autouse=True)
def seeded():
    from tools.seed import main
    if not c.get("/api/exact/catalog", headers=H("canbo")).json()["docs"]:
        main(os.path.join(ROOT, "kb-seed"))
    return True


def test_auth():
    assert c.get("/api/me").status_code == 401
    me = c.get("/api/me", headers=H("canbo")).json()
    assert me["username"] == "canbo" and me["units"] == ["phong-ky-thuat"]
    assert c.get("/api/audit/logs", headers=H("canbo")).status_code == 403


def test_catalog_and_versions():
    cat = c.get("/api/exact/catalog", headers=H("canbo")).json()
    ids = {d["doc_id"] for d in cat["docs"]}
    assert {"QD-15-2026", "HD-03-2026"} <= ids
    v = c.get("/api/exact/docs/QD-15-2026/versions", headers=H("canbo")).json()["versions"]
    assert v and v[0]["tac_gia"] == "khoi-tao-2"  # người duyệt cấp 2 là tác giả commit


def test_luong_b_direct_reference():
    r = c.post("/api/chat/chat", headers=H("canbo"), json={
        "message": "Theo Điều 5 khoản 2 Quyết định 15/QĐ-ĐVA thiết bị hư hỏng thu hồi trong bao lâu?", "stream": False}).json()
    assert r["route"] == "chinh_xac"
    blk = r["exact_blocks"][0]
    assert blk["section_id"] == "QD-15-2026.D5.K2"
    assert "07 ngày làm việc" in blk["text"] and blk["commit"]
    # câu dẫn theo khuôn mẫu: vị trí lấy từ cấu trúc văn bản, không gọi mô hình
    assert r["answer"] == "Nội dung này được quy định tại Khoản 2 Điều 5 Quyết định số 15/QĐ-ĐVA như sau:"
    assert blk["locator"] == "Khoản 2 Điều 5"
    assert r["verify"]["ok"] is True and r["interpretation"] == "" and r["can_interpret"] is True
    # diễn giải theo yêu cầu, được kiểm chứng với nguyên văn và lưu lại
    d = c.post(f"/api/chat/messages/{r['message_id']}/interpret", headers=H("canbo")).json()
    assert d["ok"] is True and "07" in d["interpretation"]
    conv = c.get(f"/api/chat/conversations/{r['conversation_id']}", headers=H("canbo")).json()
    assert conv["messages"][-1]["data"]["interpretation"] == d["interpretation"]
    assert c.post(f"/api/chat/messages/{r['message_id']}/interpret", headers=H("kiemduyet1")).status_code == 404


def test_luong_b_fts_and_verifier_drops_invented_numbers():
    r = c.post("/api/chat/chat", headers=H("canbo"), json={
        "message": "mã PIN có độ dài tối thiểu bao nhiêu ký tự BỊA SỐ", "mode": "chinh_xac", "stream": False}).json()
    assert r["exact_blocks"] and "08 ký tự" in r["exact_blocks"][0]["text"]
    d = c.post(f"/api/chat/messages/{r['message_id']}/interpret", headers=H("canbo")).json()
    assert d["interpretation"] == "" and d["ok"] is False  # diễn giải chứa số bịa → bị loại


def test_luong_a_stream_citations():
    ev = sse({"message": "Trong tuần 45 Phòng Kỹ thuật đã xử lý bao nhiêu sự cố kỹ thuật?", "mode": "tra_cuu"})
    kinds = [e for e, _ in ev]
    assert kinds[0] == "start" and "meta" in kinds and "delta" in kinds and kinds[-1] == "final"
    final = ev[-1][1]
    assert final["sources"] and "[1]" in final["answer"] and "[7]" not in final["answer"]
    assert 7 in final["verify"]["invalid_citations"]


def test_router_and_support_tree():
    r = c.post("/api/chat/chat", headers=H("canbo"), json={"message": "máy in không in được", "stream": False}).json()
    assert r["route"] == "ho_tro"
    assert r["trees"] and r["trees"][0]["id"] == "may-in-khong-in"
    # có cây xử lý sự cố thì không trả lời "không tìm thấy căn cứ"
    assert "Không tìm thấy căn cứ" not in r["answer"]
    s = c.post("/api/support/sessions", headers=H("canbo"), json={"tree_id": "may-in-khong-in"}).json()
    sid = s["session_id"]
    a = c.post(f"/api/support/sessions/{sid}/answer", headers=H("canbo"), json={"text": "có, đèn xanh"}).json()
    assert a["step"]["id"] == "b2"
    a = c.post(f"/api/support/sessions/{sid}/answer", headers=H("canbo"), json={"lua_chon": 1}).json()
    a = c.post(f"/api/support/sessions/{sid}/answer", headers=H("canbo"), json={"lua_chon": 1, "mo_ta_them": "Máy in tầng 2"}).json()
    assert a["status"] == "tao_phieu" and a["ticket"]["id"]
    tid = a["ticket"]["id"]
    assert c.patch(f"/api/support/tickets/{tid}", headers=H("canbo"), json={"status": "da_xong"}).status_code == 403
    c.patch(f"/api/support/tickets/{tid}", headers=H("kiemduyet1"), json={"status": "da_xong", "result": "Thay cáp USB máy in."})
    p = c.post(f"/api/support/tickets/{tid}/propose-kb", headers=H("kiemduyet1")).json()
    j = wait_job(p["job_id"])
    assert j["status"] == "cho_duyet" and j["meta"]["loai"] == "su_co"


def test_summary_job_numbers_computed_by_code():
    docs = c.get("/api/ingest/documents", headers=H("canbo"), params={"loai": "bao_cao"}).json()
    ids = [d["doc_id"] for d in docs]
    assert len(ids) == 2
    tpl = c.get("/api/summary/templates", headers=H("canbo")).json()
    assert any(t["name"] == "tong-hop-bao-cao-tuan" for t in tpl)
    jid = c.post("/api/summary/jobs", headers=H("canbo"), json={
        "title": "Tổng hợp tuần 45", "skill": "tong-hop-bao-cao-tuan", "doc_ids": ids}).json()["id"]
    for _ in range(60):
        j = c.get(f"/api/summary/jobs/{jid}", headers=H("canbo")).json()
        if j["status"] in ("xong", "loi"):
            break
        time.sleep(1)
    assert j["status"] == "xong", j
    su_co = next(t for t in j["table"] if t["chi_tieu"].lower() == "số sự cố")
    # mô hình giả lập trích 12, 9 (PKT) và 7 (VP); tổng do chương trình tính
    assert su_co["tong"] == 28 == sum(x["gia_tri"] for x in su_co["chi_tiet"])
    assert any("123456" in w for w in j["warnings"])  # số bịa ở bước Map bị loại
    assert "Phụ lục 1" in j["result"]
    d = c.get(f"/api/summary/jobs/{jid}/docx", headers=H("canbo"))
    if shutil.which("pandoc"):
        assert d.status_code == 200 and d.content[:2] == b"PK"
    else:  # máy chưa cài pandoc: dịch vụ báo rõ lỗi 501
        assert d.status_code == 501
    assert c.get(f"/api/summary/jobs/{jid}", headers=H("kiemduyet1")).status_code == 404  # chỉ chủ sở hữu


def test_ingest_docx_tcvn3_and_acl():
    from docx import Document as D
    doc = D()
    doc.add_paragraph("QUYẾT ĐỊNH")
    doc.add_paragraph("Về việc ban hành quy chế thử nghiệm")
    doc.add_paragraph("Điều 1. Phạm vi")
    doc.add_paragraph("Quy chế này áp dụng cho Văn phòng, mã nội bộ VP-KIEMTHU-ACL.")
    buf = io.BytesIO()
    doc.save(buf)
    r = c.post("/api/ingest/jobs", headers=H("kiemduyet2"), files={"file": ("qc.docx", buf.getvalue())},
               data={"do_mat": "0", "don_vi": "van-phong"}).json()
    j = wait_job(r["id"], "kiemduyet2")
    assert j["status"] == "cho_duyet" and j["kind"] == "docx"
    assert "### Điều 1. Phạm vi" in j["markdown"] and j["meta"]["loai"] == "quyet_dinh"
    c.post(f"/api/ingest/jobs/{r['id']}/approve", headers=H("kiemduyet2"), json={"track": "A"}).raise_for_status()
    q = {"message": "VP-KIEMTHU-ACL quy chế áp dụng cho ai", "mode": "tim_tai_lieu", "stream": False}
    seen_vp = c.post("/api/chat/chat", headers=H("kiemduyet2"), json=q).json()["docs"]
    seen_kt = c.post("/api/chat/chat", headers=H("canbo"), json=q).json()["docs"]
    assert any(d["doc_id"] == j["doc_id"] or "qc" in d["title"].lower() or "quy chế" in d["title"].lower() for d in seen_vp)
    assert all(d["doc_id"] != j["doc_id"] for d in seen_kt)  # cán bộ đơn vị khác không thấy

    tcvn = "QUY §ÞNH\nNéi dung vÒ viÖc qu¶n lý thiÕt bÞ l­u khãa bÝ mËt cña ®¬n vÞ.\n".encode("latin-1")
    r = c.post("/api/ingest/jobs", headers=H("canbo"), files={"file": ("cu.txt", tcvn)}).json()
    j = wait_job(r["id"])
    assert "thiết bị lưu khóa bí mật của đơn vị" in j["markdown"]
    assert any("TCVN3" in w for w in j["warnings"])
    # độ mật vượt quyền người nạp
    r = c.post("/api/ingest/jobs", headers=H("canbo"), files={"file": ("m.txt", b"noi dung")}, data={"do_mat": "1"})
    assert r.status_code == 403


def test_internal_endpoints_not_reachable_through_gateway():
    """Một người kiểm duyệt không được ghi thẳng vào kho chuẩn hoặc chỉ mục (bỏ qua duyệt hai cấp)."""
    md = "---\nid: QD-98-2026\nso_hieu: \"98/QĐ-ĐVA\"\nten: \"Thử\"\nnguoi_duyet: kiemduyet1\n---\n\n# Thử\n"
    r = c.post("/api/exact/kb/commit", headers=H("kiemduyet1"),
               json={"doc_id": "QD-98-2026", "content": md, "message": "x", "author": "kiemduyet1"})
    assert r.status_code == 404
    assert c.post("/api/search/index", headers=H("quantri"), json={"doc_id": "X", "markdown": "# x"}).status_code == 404
    assert c.delete("/api/search/docs/X", headers=H("quantri")).status_code == 404
    # gọi thẳng vào dịch vụ với chữ ký người dùng hợp lệ nhưng không có danh tính dịch vụ: vẫn bị chặn
    from aicommon.security import UserCtx, sign_user
    u = UserCtx(sub="t", username="kiemduyet1", roles=["reviewer"], units=["*"], clearance=1)
    r = httpx.post("http://127.0.0.1:8103/kb/commit", headers=sign_user(u),
                   json={"doc_id": "QD-98-2026", "content": md, "message": "x", "author": "kiemduyet1"})
    assert r.status_code == 403
    assert "QD-98-2026" not in {d["doc_id"] for d in c.get("/api/exact/catalog", headers=H("canbo")).json()["docs"]}


def test_luong_b_requires_two_distinct_reviewers():
    md = ("---\nso_hieu: \"20/QĐ-ĐVA\"\nten: \"Quy định thử nghiệm hai cấp\"\nloai: quyet_dinh\nngay_ban_hanh: 2026-10-01\n---\n\n"
          "# Quy định thử nghiệm\n\n## Chương I. CHUNG\n\n### Điều 1. Thời hạn\n\n1. Thời hạn lưu trữ là 10 năm.\n2. Hết thời hạn thì tiêu hủy.\n")
    r = c.post("/api/ingest/jobs", headers=H("kiemduyet1"), files={"file": ("qd20.md", md.encode())}).json()
    wait_job(r["id"])
    a1 = c.post(f"/api/ingest/jobs/{r['id']}/approve", headers=H("kiemduyet1"), json={"track": "B"}).json()
    assert a1["status"] == "cho_duyet_cap_2" and a1["doc_id"] == "QD-20-2026"
    assert c.post(f"/api/ingest/jobs/{r['id']}/approve", headers=H("kiemduyet1"), json={"track": "B"}).status_code == 409
    a2 = c.post(f"/api/ingest/jobs/{r['id']}/approve", headers=H("kiemduyet2"), json={"track": "B"}).json()
    assert a2["status"] == "da_duyet"
    sec = c.get("/api/exact/sections/QD-20-2026.D1.K1", headers=H("canbo")).json()
    assert sec["text"] == "1. Thời hạn lưu trữ là 10 năm." and sec["explicit_id"]


def test_agent_mode_and_tools():
    tools = c.get("/api/chat/tools", headers=H("canbo")).json()
    assert {"search_docs", "get_section"} <= {t["name"] for t in tools}
    r = c.post("/api/chat/chat", headers=H("canbo"), json={"message": "sao lưu tăng dần", "mode": "tac_tu", "stream": False}).json()
    assert r["route"] == "tac_tu" and r["sources"] and "[1]" in r["answer"]


def test_mcp_endpoint():
    h = {**H("canbo"), "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
    r = c.post("/api/chat/mcp/", headers=h, json=init)
    assert r.status_code == 200, r.text
    r = c.post("/api/chat/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert r.status_code == 200 and "search_docs" in r.text, r.text
    r = c.post("/api/chat/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "get_section", "arguments": {"args": {"section_id": "QD-15-2026.D6.K2"}}}})
    assert "08 ký tự" in r.text, r.text


def test_feedback_conversation_and_audit():
    r = c.post("/api/chat/chat", headers=H("canbo"), json={"message": "Xin chào", "stream": False}).json()
    assert r["route"] == "chao_hoi"
    conv = r["conversation_id"]
    r2 = c.post("/api/chat/chat", headers=H("canbo"), json={"message": "lịch sao lưu đầy đủ", "conversation_id": conv,
                                                         "mode": "tra_cuu", "stream": False}).json()
    c.post("/api/chat/feedback", headers=H("canbo"), json={"message_id": r2["message_id"], "rating": -1,
                                                          "comment": "Thiếu thời gian lưu giữ"}).raise_for_status()
    fb = c.get("/api/chat/feedback", headers=H("kiemduyet1")).json()
    assert fb and fb[0]["comment"] == "Thiếu thời gian lưu giữ" and fb[0]["question"] == "lịch sao lưu đầy đủ"
    assert c.get(f"/api/chat/conversations/{conv}", headers=H("kiemduyet1")).status_code == 404
    time.sleep(3)
    logs = c.get("/api/audit/logs", headers=H("quantri")).json()
    assert any(x["action"] == "chat.answer" for x in logs)
    v = c.get("/api/audit/verify", headers=H("quantri")).json()
    assert v["ok"] and v["checked"] > 10
    q = c.get("/api/ingest/reports/quality", headers=H("kiemduyet1")).json()
    assert "Báo cáo chất lượng dữ liệu" in q["markdown"]


# ---------------- Truy xuất, kiểm chứng (bản 1.2.0) ----------------
def test_search_unaccented_query_returns_whole_section():
    r = c.post("/api/search/search", headers=H("canbo"),
               json={"query": "cach xu ly mat ket noi mang may tram", "explain": True, "rerank": False}).json()
    # nhánh BM25 khớp câu hỏi gõ không dấu (vector giả lập không hiểu tiếng Việt không dấu, bge-m3 thật thì có)
    assert "SU-CO-MAT-KET-NOI" in r["explain"]["bm25"][0][0]
    # mục "Cách xử lý" được trả đủ 3 bước (không bị cắt ở đoạn trúng)
    hit = next(x for x in r["results"] if "Cách xử lý" in x["breadcrumb"])
    assert "ipconfig /renew" in hit["text"] and "phiếu yêu cầu hỗ trợ" in hit["text"]
    assert {"dense", "bm25", "query_expanded"} <= set(r["explain"])


def test_search_expands_glossary_abbreviation():
    r = c.post("/api/search/search", headers=H("canbo"), json={"query": "PKT kiến nghị gì", "explain": True}).json()
    assert "Phòng Kỹ thuật" in r["explain"]["query_expanded"]


def test_truncated_answer_is_trimmed_and_flagged():
    r = c.post("/api/chat/chat", headers=H("canbo"),
               json={"message": "CẮT CỤT cách xử lý mất kết nối mạng", "mode": "tra_cuu", "stream": False}).json()
    assert r["verify"]["truncated"] is True and "rút gọn" in r["answer"]
    assert not r["answer"].split("*(")[0].rstrip().endswith("gồm")  # phần viết dở đã bị cắt
    assert any("ANSWER_MAX_TOKENS" in w for w in r["warnings"])


def test_answer_grounding_flags_content_not_in_sources():
    r = c.post("/api/chat/chat", headers=H("canbo"),
               json={"message": "LỆCH NGUỒN cách xử lý mất kết nối mạng", "mode": "tra_cuu", "stream": False}).json()
    assert "tàu ngầm" in r["answer"] and "(chưa tìm thấy trong nguồn)" in r["answer"]
    assert r["verify"]["unsupported"] and r["verify"]["ok"] is False
