"""Tác tử GIÁM ĐỊNH CHẤT LƯỢNG DỮ LIỆU – chạy định kỳ, liên tục phát hiện vấn đề của cơ sở tri thức.

Thiết kế hai tầng để phù hợp tài nguyên:
  - Tầng 1 (luôn chạy, KHÔNG dùng mô hình): thuật toán quy tắc, thống kê, MinHash – nhanh, chạy được trên CPU yếu.
  - Tầng 2 (chỉ khi tài nguyên cho phép, QA_LLM_MODE): mô hình kiểm tra chéo các NGHI VẤN của tầng 1
    (ví dụ hai câu có vẻ mâu thuẫn) để xác nhận/bác bỏ. Khung đã sẵn sàng; bật khi có GPU hoặc chạy giờ rảnh.

    Kiểm tra             Mã             Phát hiện
    1 Gần trùng          trung_lap      hai tài liệu có nội dung gần như nhau (MinHash LSH, Jaccard ≥ QA_DUP_THRESHOLD)
    2 Hiệu lực           hieu_luc       văn bản A ghi "thay thế/bãi bỏ" văn bản B nhưng B vẫn "còn hiệu lực" trong kho
    3 Mâu thuẫn          mau_thuan      cùng một nội dung (thời hạn, số lượng) có giá trị khác nhau giữa văn bản chuẩn
                                        và tài liệu khác; tầng 2 xác nhận bằng mô hình
    4 Viện dẫn thiếu     vien_dan       văn bản được viện dẫn nhưng chưa có trong kho
    5 Thông tin mô tả    thieu_meta     thiếu số hiệu, ngày ban hành… (kèm đề xuất sửa trích từ nội dung – áp dụng 1 chạm)
    6 Tài liệu cũ        tai_lieu_cu    báo cáo, kế hoạch quá QA_STALE_MONTHS tháng
    7 Chất lượng nội dung noi_dung      nội dung quá ngắn, nhiều ký tự lỗi, tỷ lệ tiếng Việt thấp (OCR kém)
    8 Lỗ hổng tri thức   lo_hong        câu hỏi người dùng hệ thống không tìm được căn cứ, bị đánh giá "Sai" (gom nhóm)
    9 Bám nguồn kém      bam_nguon      câu trả lời có câu không tìm thấy trong nguồn (theo tài liệu được trích)

Mỗi phát hiện có fingerprint ổn định → không tạo trùng giữa các lượt; phát hiện không còn xuất hiện được TỰ ĐÓNG;
phát hiện đã "Bỏ qua" không mở lại. Mọi thay đổi dữ liệu thật (áp dụng đề xuất sửa) đều cần người có thẩm quyền bấm.
"""
import hashlib
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from aicommon.config import get_settings
from aicommon.db import session
from aicommon.llm import LLMError, SyncLLM
from aicommon.priority import active as interactive_active
from aicommon.priority import wait_idle
from aicommon.resources import prompt
from aicommon.telemetry import record
from aicommon.text import content_tokens, nfc, unaccent, vietnamese_ratio

from .models import DANG_CHAY, LOI, XONG, QaFinding, QaRun

log = logging.getLogger("agent.quality")
S = get_settings()
KIND_LABEL = {"trung_lap": "Tài liệu gần trùng", "hieu_luc": "Hiệu lực chưa cập nhật", "mau_thuan": "Nghi vấn mâu thuẫn",
              "vien_dan": "Văn bản viện dẫn chưa có trong kho", "thieu_meta": "Thiếu thông tin mô tả",
              "tai_lieu_cu": "Tài liệu cần rà soát (cũ)", "noi_dung": "Chất lượng nội dung thấp",
              "lo_hong": "Lỗ hổng tri thức", "bam_nguon": "Câu trả lời bám nguồn kém"}
PLAN = [("nap", "Đọc sổ đăng ký tài liệu"), ("trung_lap", "Phát hiện tài liệu gần trùng"),
        ("hieu_luc", "Kiểm tra hiệu lực, viện dẫn"), ("mau_thuan", "Phát hiện nghi vấn mâu thuẫn"),
        ("meta", "Kiểm tra thông tin mô tả, nội dung"), ("su_dung", "Phân tích câu hỏi chưa trả lời được"),
        ("kiem_cheo", "Kiểm tra chéo bằng mô hình"), ("luu", "Cập nhật danh sách phát hiện")]

_CODE = re.compile(r"(?<![\w/])(\d{1,5}/(?:\d{4}/)?(?:QĐ|TT|NĐ|HD|KH|BC|CV|TTr|BB|QyĐ|CT|NQ|TB|QH|PL)[\w\-Đđ]*)")
_REPLACE = re.compile(r"(thay\s+thế|bãi\s+bỏ|hết\s+hiệu\s+lực|hủy\s+bỏ|huỷ\s+bỏ)", re.I)
# [TINH CHỈNH] Mẫu "cụm nội dung + giá trị": "thu hồi trong thời hạn 07 ngày làm việc", "tối đa 02 thiết bị"
_FACT = re.compile(r"(?<![\wÀ-ỹđĐ])((?:[\wÀ-ỹđĐ]+\s+){2,7}?)(?:trong\s+vòng|trong\s+thời\s+hạn|thời\s+hạn|tối\s+đa|không\s+quá|"
                   r"chậm\s+nhất|tối\s+thiểu|ít\s+nhất|là|trong)?\s*(\d{1,4})\s*"
                   r"(ngày\s+làm\s+việc|ngày|tháng|năm|giờ|lần|thiết\s+bị|người|%)", re.I)
_CUE = {"trong", "vong", "thoi", "han", "toi", "da", "khong", "qua", "cham", "nhat", "thieu", "it", "la", "co", "duoc",
        "phai", "cua", "va", "cac", "nhung", "mot", "sau", "truoc", "ngay", "thang", "nam"}
FORMAL = ("quyet_dinh", "thong_tu", "nghi_dinh", "quy_dinh", "huong_dan", "ke_hoach", "cong_van", "to_trinh")


def fp(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:40]


def llm_allowed(now: datetime | None = None) -> bool:
    """Tầng 2 có được dùng mô hình không: on | off | auto (GPU, hoặc trong khung giờ rảnh và không ai đang hỏi)."""
    mode = S.qa_llm_mode.lower()
    if mode == "off":
        return False
    if mode == "on":
        return True
    if S.hardware_profile.lower() == "gpu":
        return True
    h = (now or datetime.now()).hour
    try:
        a, b = (int(x) for x in S.qa_llm_hours.split("-"))
    except ValueError:
        return False
    in_window = (a <= h < b) if a < b else (h >= a or h < b)
    return in_window and interactive_active() == 0


# ---------------------------------------------------------------- các thuật toán (hàm thuần, kiểm thử được)
def fact_key(prefix: str) -> str:
    toks = [t for t in content_tokens(prefix) if t not in _CUE and not t.isdigit()]
    return " ".join(toks[-4:]) if len(toks) >= 2 else ""


def extract_facts(text: str) -> list[dict]:
    """Cặp (cụm nội dung, giá trị, đơn vị) trong văn bản – phục vụ phát hiện mâu thuẫn số liệu."""
    out = []
    for sent in re.split(r"(?<=[.;!?])\s+|\n+", nfc(text)):
        for m in _FACT.finditer(sent):
            key = fact_key(m.group(1))
            if key:
                out.append({"key": key, "val": int(m.group(2)), "unit": unaccent(m.group(3).lower()).replace("  ", " "),
                            "sent": sent.strip()[:400]})
    return out


def number_conflicts(docs: list[dict]) -> list[dict]:
    """Nghi vấn mâu thuẫn: cùng (cụm nội dung, đơn vị) nhưng giá trị khác nhau ở hai tài liệu khác nhau,
    trong đó ít nhất một bên là văn bản chuẩn (Luồng B). docs = [{doc_id, track, title, text}]."""
    by: dict[tuple, list] = defaultdict(list)
    for d in docs:
        for f in extract_facts(d["text"]):
            by[(f["key"], f["unit"])].append({**f, "doc_id": d["doc_id"], "track": d["track"], "title": d["title"]})
    out = []
    for (key, unit), items in by.items():
        b_items = [i for i in items if i["track"] == "B"]
        for b in b_items:
            for o in items:
                if o["doc_id"] == b["doc_id"] or o["val"] == b["val"]:
                    continue
                if any(c["a"]["doc_id"] == b["doc_id"] and c["b"]["doc_id"] == o["doc_id"] and c["key"] == key for c in out):
                    continue
                out.append({"key": key, "unit": unit, "a": b, "b": o})
    return out


def near_duplicates(docs: list[dict], threshold: float) -> list[tuple[str, str, float]]:
    """Cặp tài liệu gần trùng (MinHash LSH). docs = [{doc_id, minhash(bytes)}]."""
    from datasketch import MinHashLSH

    from services.ingest.cleaning import minhash_from
    mh = {}
    for d in docs:
        if d.get("minhash"):
            try:
                mh[d["doc_id"]] = minhash_from(d["minhash"])
            except Exception:
                continue
    if len(mh) < 2:
        return []
    perm = len(next(iter(mh.values())).hashvalues)
    lsh = MinHashLSH(threshold=threshold, num_perm=perm)
    for k, m in mh.items():
        lsh.insert(k, m)
    pairs = set()
    for k, m in mh.items():
        for o in lsh.query(m):
            if o != k:
                a, b = sorted((k, o))
                pairs.add((a, b, round(mh[a].jaccard(mh[b]), 3)))
    return sorted(p for p in pairs if p[2] >= threshold)


def cluster_questions(qs: list[dict], sim: float = 0.5) -> list[list[dict]]:
    """Gom câu hỏi tương tự (Jaccard trên âm tiết nội dung không dấu) – tham lam, đủ cho vài nghìn câu."""
    clusters: list[tuple[set, list]] = []
    for q in qs:
        toks = set(content_tokens(q["question"]))
        if not toks:
            continue
        for ts, members in clusters:
            if len(toks & ts) / max(1, len(toks | ts)) >= sim:
                members.append(q)
                ts |= toks
                break
        else:
            clusters.append((toks, [q]))
    return sorted((m for _, m in clusters), key=lambda m: -len(m))


def content_issues(md: str) -> list[str]:
    body = re.sub(r"^---.*?---\s*", "", md, flags=re.S)
    issues = []
    if len(body.strip()) < 300:
        issues.append("nội dung rất ngắn (dưới 300 ký tự)")
    bad = body.count("�")
    if bad >= 5:
        issues.append(f"{bad} ký tự lỗi mã (�)")
    letters = re.findall(r"[A-Za-zÀ-ỹđĐ]", body)
    if len(letters) > 200 and vietnamese_ratio(body) < 0.02 and not re.search(r"[a-z]{4,}\s+[a-z]{4,}", body):
        issues.append("tỷ lệ chữ tiếng Việt thấp – nghi nhận dạng ký tự (OCR) kém")
    sym = len(re.findall(r"[^\w\s.,;:()/%\-–—\"'“”|#*>\[\]!?]", body))
    if len(body) > 500 and sym / len(body) > 0.08:
        issues.append("nhiều ký hiệu lạ – nghi lỗi chuyển đổi")
    return issues


# ---------------------------------------------------------------- lượt chạy
class _Run:
    def __init__(self, run_id: str):
        self.id = run_id
        self.plan = [{"id": i, "name": n, "status": "cho", "out": ""} for i, n in PLAN]

    def save(self, **kw):
        with session() as s:
            r = s.get(QaRun, self.id)
            r.plan = [dict(x) for x in self.plan]
            for k, v in kw.items():
                setattr(r, k, v)

    def step(self, sid: str, status: str, out: str = ""):
        st = next(x for x in self.plan if x["id"] == sid)
        st["status"] = status
        if out:
            st["out"] = out
        self.save()


def run(run_id: str):
    """Thực hiện một lượt giám định (gọi từ tiến trình nền)."""
    from services.ingest.models import Document
    from services.orchestrator.models import Feedback, Message

    R = _Run(run_id)
    findings: list[dict] = []
    stats: dict = {}
    t0 = datetime.now(timezone.utc)
    try:
        # 1. Sổ đăng ký
        R.step("nap", "dang_chay")
        with session() as s:
            rows = s.scalars(select(Document)).all()
            docs = [{"doc_id": d.doc_id, "track": d.track, "title": d.title, "so_hieu": d.so_hieu or "", "loai": d.loai,
                     "ngay": d.ngay_ban_hanh or "", "trang_thai": d.trang_thai, "minhash": d.minhash, "path": d.path}
                    for d in rows]
        for d in docs:
            try:
                d["text"] = Path(d["path"]).read_text(encoding="utf-8") if d["path"] else ""
            except OSError:
                d["text"] = ""
        stats["tai_lieu"] = len(docs)
        R.step("nap", "xong", f"{len(docs)} tài liệu")

        # 2. Gần trùng
        R.step("trung_lap", "dang_chay")
        by_id = {d["doc_id"]: d for d in docs}
        dups = near_duplicates(docs, S.qa_dup_threshold)
        for a, b, j in dups:
            findings.append({"kind": "trung_lap", "severity": "trung_binh", "fp": fp("dup", a, b), "doc_ids": [a, b],
                             "title": f"“{by_id[a]['title']}” và “{by_id[b]['title']}” gần trùng nội dung ({j:.0%})",
                             "detail": "Hai tài liệu có nội dung gần như nhau làm câu trả lời lặp nguồn hoặc lẫn phiên bản. "
                                       "Đề nghị giữ bản đúng, thu hồi bản còn lại.", "data": {"jaccard": j}})
        R.step("trung_lap", "xong", f"{len(dups)} cặp")

        # 3. Hiệu lực, viện dẫn
        R.step("hieu_luc", "dang_chay")
        codes = {re.sub(r"\s+", "", d["so_hieu"]).lower(): d for d in docs if d["so_hieu"]}
        missing: dict[str, list] = defaultdict(list)
        n_hl = 0
        for d in docs:
            for sent in re.split(r"(?<=[.;])\s+|\n+", d["text"]):
                refs = [m.group(1) for m in _CODE.finditer(sent)]
                for r in refs:
                    tgt = codes.get(re.sub(r"\s+", "", r).lower())
                    if not tgt:
                        if r != d["so_hieu"]:
                            missing[r].append(d["doc_id"])
                        continue
                    if tgt["doc_id"] != d["doc_id"] and _REPLACE.search(sent) and tgt["trang_thai"] == "con_hieu_luc":
                        n_hl += 1
                        findings.append({
                            "kind": "hieu_luc", "severity": "cao", "fp": fp("hl", d["doc_id"], tgt["doc_id"]),
                            "doc_ids": [tgt["doc_id"], d["doc_id"]],
                            "title": f"{tgt['so_hieu']} có thể đã hết hiệu lực nhưng kho vẫn ghi “còn hiệu lực”",
                            "detail": f"Tài liệu “{d['title']}” ghi: “{sent.strip()[:300]}”. Đề nghị kiểm tra và cập nhật "
                                      "trạng thái hiệu lực (văn bản chuẩn: qua quy trình duyệt hai cấp).",
                            "data": {"cau": sent.strip()[:500]}})
        for code, by_docs in missing.items():
            findings.append({"kind": "vien_dan", "severity": "thap", "fp": fp("vd", code),
                             "doc_ids": sorted(set(by_docs))[:10],
                             "title": f"Văn bản {code} được viện dẫn {len(by_docs)} lần nhưng chưa có trong kho",
                             "detail": "Bổ sung văn bản này giúp trả lời và đối chiếu căn cứ đầy đủ hơn.",
                             "data": {"so_hieu": code, "so_lan": len(by_docs)}})
        R.step("hieu_luc", "xong", f"{n_hl} hiệu lực · {len(missing)} viện dẫn thiếu")

        # 4. Mâu thuẫn số liệu
        R.step("mau_thuan", "dang_chay")
        conflicts = number_conflicts([d for d in docs if d["text"]])
        for c in conflicts[:200]:
            a, b = c["a"], c["b"]
            findings.append({
                "kind": "mau_thuan", "severity": "trung_binh",
                "fp": fp("mt", a["doc_id"], b["doc_id"], c["key"], c["unit"], a["val"], b["val"]),
                "doc_ids": [a["doc_id"], b["doc_id"]],
                "title": f"“{c['key']}”: {a['val']} {c['unit']} ({a['title']}) ≠ {b['val']} {c['unit']} ({b['title']})",
                "detail": "Cùng một nội dung có giá trị khác nhau giữa văn bản chuẩn và tài liệu khác. Đề nghị xác minh: "
                          "tài liệu có thể đã cũ, hoặc hai câu nói về hai đối tượng khác nhau.",
                "data": {"a": a["sent"], "b": b["sent"], "key": c["key"]}})
        R.step("mau_thuan", "xong", f"{len(conflicts)} nghi vấn")

        # 5. Thông tin mô tả, nội dung
        R.step("meta", "dang_chay")
        from services.ingest.metadata import rule_based
        now = datetime.now()
        n_meta = n_old = n_ct = 0
        for d in docs:
            miss = []
            if d["loai"] in FORMAL and not d["so_hieu"]:
                miss.append("số hiệu")
            if d["loai"] in FORMAL and not d["ngay"]:
                miss.append("ngày ban hành")
            if d["title"] in ("", "Tài liệu chưa đặt tên"):
                miss.append("tên tài liệu")
            if miss:
                n_meta += 1
                guess = rule_based(d["text"]) if d["text"] else {}
                fix = {k: v for k, v in {"so_hieu": guess.get("so_hieu"), "ngay_ban_hanh": guess.get("ngay_ban_hanh"),
                                         "title": guess.get("ten")}.items()
                       if v and ((k == "so_hieu" and "số hiệu" in miss) or (k == "ngay_ban_hanh" and "ngày ban hành" in miss)
                                 or (k == "title" and "tên tài liệu" in miss))}
                findings.append({"kind": "thieu_meta", "severity": "thap", "fp": fp("meta", d["doc_id"], *miss),
                                 "doc_ids": [d["doc_id"]], "title": f"“{d['title']}” thiếu {', '.join(miss)}",
                                 "detail": "Thông tin mô tả đầy đủ giúp lọc, trích dẫn và kiểm tra hiệu lực chính xác."
                                           + (" Đã trích được đề xuất từ nội dung, có thể áp dụng." if fix else ""),
                                 "data": {"thieu": miss, "fix": fix, "track": d["track"]}})
            if d["loai"] in ("bao_cao", "ke_hoach") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["ngay"] or ""):
                age = (now - datetime.strptime(d["ngay"], "%Y-%m-%d")).days / 30.4
                if age > S.qa_stale_months:
                    n_old += 1
                    findings.append({"kind": "tai_lieu_cu", "severity": "thap", "fp": fp("cu", d["doc_id"]),
                                     "doc_ids": [d["doc_id"]], "title": f"“{d['title']}” ban hành đã {int(age)} tháng",
                                     "detail": "Báo cáo, kế hoạch cũ có thể làm câu trả lời dùng số liệu lỗi thời. "
                                               "Đề nghị rà soát: thu hồi hoặc đánh dấu tài liệu lịch sử.", "data": {"thang": int(age)}})
            ci = content_issues(d["text"]) if d["text"] else ["không đọc được nội dung tệp"]
            if ci:
                n_ct += 1
                findings.append({"kind": "noi_dung", "severity": "trung_binh", "fp": fp("nd", d["doc_id"], *ci),
                                 "doc_ids": [d["doc_id"]], "title": f"“{d['title']}”: {'; '.join(ci)}",
                                 "detail": "Nội dung kém chất lượng làm giảm độ chính xác tìm kiếm. Đề nghị nạp lại bản gốc tốt hơn "
                                           "hoặc chạy lại nhận dạng ký tự.", "data": {"van_de": ci}})
        R.step("meta", "xong", f"{n_meta} thiếu mô tả · {n_old} cũ · {n_ct} nội dung kém")

        # 6. Lỗ hổng tri thức, bám nguồn
        R.step("su_dung", "dang_chay")
        since = datetime.now(timezone.utc) - timedelta(days=S.qa_gap_days)
        gaps, weak = [], defaultdict(list)
        with session() as s:
            msgs = s.scalars(select(Message).where(Message.role == "assistant", Message.created_at >= since)
                             .order_by(Message.id.desc()).limit(3000)).all()
            neg = {f.message_id: f.comment for f in s.scalars(select(Feedback).where(Feedback.rating < 0,
                                                                                     Feedback.created_at >= since))}
            for m in msgs:
                data = m.data or {}
                refused = "Không tìm thấy căn cứ" in (m.content or "")
                if refused or m.id in neg:
                    q = s.scalars(select(Message).where(Message.conversation_id == m.conversation_id, Message.id < m.id,
                                                        Message.role == "user").order_by(Message.id.desc()).limit(1)).first()
                    if q:
                        gaps.append({"question": q.content[:500], "message_id": m.id, "ly_do": "sai" if m.id in neg else "khong_can_cu",
                                     "gop_y": neg.get(m.id, "")})
                uns = (data.get("verify") or {}).get("unsupported") or []
                if uns:
                    for src in data.get("sources") or []:
                        if src.get("doc_id"):
                            weak[src["doc_id"]].append(m.id)
        for cl in cluster_questions(gaps)[:50]:
            rep = cl[0]["question"]
            sev = "cao" if len(cl) >= 3 else "trung_binh"
            findings.append({"kind": "lo_hong", "severity": sev, "fp": fp("gap", " ".join(sorted(set(content_tokens(rep))))[:200]),
                             "doc_ids": [], "title": f"{len(cl)} câu hỏi chưa có căn cứ trả lời: “{rep[:160]}”",
                             "detail": "Người dùng hỏi nhưng hệ thống không tìm được căn cứ hoặc trả lời bị đánh giá sai. "
                                       "Đề nghị bổ sung tài liệu, thuật ngữ hoặc điều chỉnh truy xuất.",
                             "data": {"cau_hoi": [{"q": c["question"], "ly_do": c["ly_do"], "gop_y": c["gop_y"]} for c in cl[:10]]}})
        for did, mids in sorted(weak.items(), key=lambda x: -len(x[1]))[:20]:
            if len(mids) < 2:
                continue
            findings.append({"kind": "bam_nguon", "severity": "thap", "fp": fp("bn", did), "doc_ids": [did],
                             "title": f"“{by_id.get(did, {}).get('title', did)}”: {len(mids)} câu trả lời có câu không tìm thấy trong nguồn",
                             "detail": "Tài liệu thường được trích nhưng câu trả lời không bám sát – có thể do cách chia đoạn, bảng "
                                       "biểu phức tạp hoặc tiêu đề mục không rõ. Đề nghị kiểm tra cấu trúc tài liệu.",
                             "data": {"message_ids": mids[:20]}})
        stats.update(cau_hoi_chua_tra_loi=len(gaps), tai_lieu_bam_nguon_kem=len(weak))
        R.step("su_dung", "xong", f"{len(gaps)} câu hỏi chưa có căn cứ")

        # 7. Kiểm tra chéo bằng mô hình (tầng 2)
        mode = "heuristic"
        cands = [f for f in findings if f["kind"] == "mau_thuan"]
        if cands and llm_allowed():
            mode = "llm"
            R.step("kiem_cheo", "dang_chay")
            llm = SyncLLM()
            n = 0
            for f in cands[:S.qa_llm_max_checks]:
                if wait_idle(max_s=60) > 55:
                    break  # có người đang hỏi đáp: dừng tầng 2, lượt sau làm tiếp
                try:
                    out = llm.chat_json([{"role": "system", "content": prompt("giam-dinh-mau-thuan")},
                                         {"role": "user", "content": f"CÂU A (văn bản chuẩn): {f['data']['a']}\n\n"
                                                                     f"CÂU B: {f['data']['b']}"}],
                                        schema={"type": "object", "properties": {
                                            "mau_thuan": {"type": "boolean"}, "giai_thich": {"type": "string"}},
                                            "required": ["mau_thuan", "giai_thich"]},
                                        model=S.model_small, max_tokens=200, task="giam-dinh-mau-thuan")
                except LLMError:
                    continue
                n += 1
                f["verified"] = "xac_nhan" if out.get("mau_thuan") else "bac_bo"
                f["data"]["giai_thich"] = str(out.get("giai_thich", ""))[:500]
                f["severity"] = "cao" if out.get("mau_thuan") else "thap"
            R.step("kiem_cheo", "xong", f"{n} nghi vấn đã kiểm tra")
        else:
            R.step("kiem_cheo", "bo_qua", "Tài nguyên chưa cho phép (chỉ chạy tầng thuật toán)" if cands else "Không có nghi vấn")

        # 8. Lưu
        R.step("luu", "dang_chay")
        opened, closed = upsert(findings, run_id)
        stats.update(phat_hien=len(findings), moi=opened, tu_dong=closed,
                     theo_loai={k: sum(1 for f in findings if f["kind"] == k) for k in KIND_LABEL})
        R.step("luu", "xong", f"{opened} mới · {closed} tự đóng")
        R.save(status=XONG, mode=mode, stats=stats, finished_at=datetime.now(timezone.utc))
        log.info("Giám định dữ liệu xong: %s", stats, extra={"event": "qa.run"})
    except Exception as e:
        log.exception("Giám định dữ liệu lỗi")
        R.save(status=LOI, error=str(e)[:2000], stats=stats, finished_at=datetime.now(timezone.utc))
    record("tel:task", kind="giam_dinh", status="xong", ms=int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
           user="system", task_id=run_id)


def upsert(findings: list[dict], run_id: str) -> tuple[int, int]:
    """Ghi phát hiện theo fingerprint. Trả (số phát hiện mới, số phát hiện tự đóng)."""
    now = datetime.now(timezone.utc)
    seen, opened = set(), 0
    with session() as s:
        for f in findings:
            if f["fp"] in seen:
                continue
            seen.add(f["fp"])
            row = s.scalars(select(QaFinding).where(QaFinding.fingerprint == f["fp"])).first()
            if row is None:
                s.add(QaFinding(fingerprint=f["fp"], kind=f["kind"], severity=f["severity"], title=f["title"][:500],
                                detail=f["detail"], doc_ids=f["doc_ids"], data=f["data"], run_id=run_id,
                                verified=f.get("verified", "")))
                opened += 1
                continue
            row.last_seen, row.run_id, row.title, row.detail, row.data = now, run_id, f["title"][:500], f["detail"], f["data"]
            if f.get("verified"):
                row.verified, row.severity = f["verified"], f["severity"]
            if row.status == "da_xu_ly":  # đã đánh dấu xử lý nhưng vẫn phát hiện → mở lại
                row.status, row.resolution = "moi", (row.resolution + " | Phát hiện lại ở lượt giám định sau.")[:2000]
                opened += 1
        # phát hiện cũ (chưa xử lý) không còn xuất hiện → tự đóng
        closed = 0
        for row in s.scalars(select(QaFinding).where(QaFinding.status == "moi")):
            if row.fingerprint not in seen:
                row.status, row.resolution, row.resolved_by = "da_xu_ly", f"Tự đóng: không còn phát hiện ở lượt {run_id[:8]}.", "he-thong"
                closed += 1
    return opened, closed


def start_run(trigger: str) -> str | None:
    """Tạo lượt giám định mới (None nếu đang có lượt chạy)."""
    with session() as s:
        busy = s.scalars(select(QaRun).where(QaRun.status == DANG_CHAY)).first()
        if busy and busy.started_at and (datetime.now(timezone.utc) - busy.started_at.replace(
                tzinfo=busy.started_at.tzinfo or timezone.utc)) < timedelta(hours=3):
            return None
        if busy:  # lượt treo quá 3 giờ (tiến trình chết) → đánh dấu lỗi
            busy.status, busy.error = LOI, "Quá thời gian, tiến trình nền có thể đã dừng."
        r = QaRun(trigger=trigger, plan=[{"id": i, "name": n, "status": "cho", "out": ""} for i, n in PLAN])
        s.add(r)
        s.flush()
        return r.id
