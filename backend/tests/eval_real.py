"""Đánh giá nhanh hệ thống với mô hình thật trên dữ liệu mẫu kb-seed (không thay thế pytest).

    python tests/eval_real.py                 # chạy toàn bộ bộ câu hỏi
    python tests/eval_real.py --only B1,A1    # chạy một số câu
    python tests/eval_real.py --show          # in đầy đủ câu trả lời

Yêu cầu: run_models.py và run_stack.py --real --seed đang chạy.
Mỗi câu có tiêu chí kiểm tra bằng chương trình (đúng luồng, đúng nguồn, có/không có con số...).
Kết quả ghi vào .test-run-that/eval-<thời điểm>.json để so sánh giữa các lần đổi mô hình, prompt, tham số.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
GW = os.getenv("GW", "http://127.0.0.1:8100")
OUT = Path(os.getenv("TEST_RUN_DIR_REAL", str(ROOT / ".test-run-that")))
H = {"Authorization": "Bearer dev-canbo"}

# id, câu hỏi, chế độ, kiểm tra: route, chuỗi phải có trong phần trích nguyên văn / câu trả lời, tên tài liệu nguồn mong đợi
CASES = [
    {"id": "B1", "q": "Theo Điều 5 khoản 2 Quyết định 15/QĐ-ĐVA, thiết bị hư hỏng phải thu hồi trong thời hạn bao lâu?",
     "route": "chinh_xac", "exact_has": "07 ngày làm việc", "answer_has": "Khoản 2 Điều 5"},
    {"id": "B2", "q": "Mã PIN của USB Token phải có độ dài tối thiểu bao nhiêu ký tự?", "mode": "chinh_xac",
     "route": "chinh_xac", "exact_has": "08 ký tự", "answer_has": "Điều 6"},
    {"id": "B3", "q": "Theo quy định 15/QĐ-ĐVA, mất thiết bị thì phải báo cáo trong bao lâu?", "mode": "chinh_xac",
     "route": "chinh_xac", "exact_has": "24 giờ", "answer_has": "Khoản 3 Điều 5"},
    {"id": "A1", "q": "Trong tuần 45, Phòng Kỹ thuật đã xử lý bao nhiêu sự cố kỹ thuật?", "mode": "tra_cuu",
     "route": "tra_cuu", "answer_has": "12", "source_has": "Báo cáo công tác tuần 45 năm 2026 – Phòng Kỹ thuật"},
    {"id": "A2", "q": "Máy trạm mất kết nối mạng nội bộ thì xử lý thế nào?", "mode": "tra_cuu",
     "route": "tra_cuu", "answer_has": "ipconfig", "source_has": "Sự cố mất kết nối mạng nội bộ"},
    {"id": "A3", "q": "Hệ thống AI Local có kết nối Internet không?", "mode": "tra_cuu",
     "route": "tra_cuu", "source_has": "Giới thiệu hệ thống AI Local"},
    {"id": "A4", "q": "Lương tháng của Giám đốc là bao nhiêu?", "mode": "tra_cuu",
     "route": "tra_cuu", "refuse": True},
    # Độ đầy đủ: phải nêu ĐỦ các bước/ý của nguồn (bản 1.2.0)
    {"id": "A5", "q": "Nêu đầy đủ các bước xử lý khi máy trạm mất kết nối mạng nội bộ", "mode": "tra_cuu",
     "route": "tra_cuu", "answer_all": ["cáp", "ipconfig /release", "ipconfig /renew", "phiếu"],
     "source_has": "Sự cố mất kết nối mạng nội bộ"},
    # Câu hỏi nhiều ý, hai tài liệu khác nhau: không được gộp, không được lẫn số liệu
    {"id": "A6", "q": "Trong tuần 45, Phòng Kỹ thuật và Văn phòng mỗi nơi cấp phát bao nhiêu thiết bị USB Token?",
     "mode": "tra_cuu", "route": "tra_cuu", "answer_all": ["5", "3"]},
    # Câu hỏi gõ không dấu
    {"id": "A7", "q": "phong ky thuat kien nghi gi trong tuan 45", "mode": "tra_cuu", "route": "tra_cuu",
     "answer_has": "10", "source_has": "Phòng Kỹ thuật"},
    # Hỗ trợ kỹ thuật gộp vào hỏi đáp: các bước trích từ tài liệu hướng dẫn (kb-seed/tai-lieu/huong-dan-xu-ly-*.md)
    {"id": "R1", "q": "máy in không in được, đèn vẫn sáng", "route": "ho_tro", "no_refuse": True,
     "source_has": "máy in", "answer_all": ["Print Spooler"]},
    {"id": "R3", "q": "USB Token cắm vào máy tính không nhận, đèn không sáng", "route": "ho_tro", "no_refuse": True,
     "answer_all": ["cổng USB", "middleware"]},
    # Câu hỏi mơ hồ → hỏi lại (không tốn mô hình)
    {"id": "C1", "q": "bị lỗi rồi, không dùng được", "route": "lam_ro", "clarify": True},
    # Bảo vệ an toàn thông tin: chặn bí mật xác thực
    {"id": "G1", "q": "mã PIN của tôi là 12345678, sao ký không được?", "route": "bao_ve"},
    {"id": "R2", "q": "Xin chào", "route": "chao_hoi"},
]
REFUSE_HINTS = ("không tìm thấy", "không có thông tin", "chưa có thông tin", "không đủ thông tin", "không có trong")


def ask(c: httpx.Client, case: dict) -> dict:
    """Gọi ở chế độ luồng sự kiện (như giao diện) để đo cả thời gian đến chữ đầu tiên."""
    body = {"message": case["q"], "stream": True}
    if case.get("mode"):
        body["mode"] = case["mode"]
    t0 = time.time()
    first, meta, final = None, {}, {}
    with c.stream("POST", f"{GW}/api/chat/chat", headers={**H, "Accept": "text/event-stream"}, json=body) as r:
        r.raise_for_status()
        event, data = "message", ""
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
            elif not line and data:
                d = json.loads(data)
                if event in ("delta", "final") and first is None:
                    first = time.time() - t0  # thời điểm người dùng thấy chữ đầu tiên
                if event == "meta":
                    meta.update(d)
                elif event == "final":
                    final = d
                event, data = "message", ""
    dt = time.time() - t0
    return {**meta, **final, "_seconds": round(dt, 1), "_first": round(first if first is not None else dt, 1)}


def judge(case: dict, r: dict) -> list[str]:
    errs = []
    if case.get("route") and r.get("route") != case["route"]:
        errs.append(f"sai luồng: {r.get('route')} (mong đợi {case['route']})")
    ans = r.get("answer") or ""
    if case.get("exact_has"):
        blocks = r.get("exact_blocks") or []
        if not any(case["exact_has"] in b.get("text", "") for b in blocks):
            errs.append(f"trích nguyên văn thiếu \"{case['exact_has']}\"")
    if case.get("answer_has") and case["answer_has"] not in ans:
        errs.append(f"câu trả lời thiếu \"{case['answer_has']}\"")
    missing = [x for x in case.get("answer_all", []) if x.lower() not in ans.lower()]
    if missing:
        errs.append(f"câu trả lời chưa đầy đủ, thiếu: {missing}")
    if case.get("source_has"):
        srcs = json.dumps(r.get("sources") or [], ensure_ascii=False)
        if case["source_has"] not in srcs:
            errs.append(f"nguồn không có \"{case['source_has']}\"")
    if case.get("refuse") and not any(h in ans.lower() for h in REFUSE_HINTS):
        errs.append("không từ chối khi tài liệu không có thông tin (nguy cơ bịa)")
    if case.get("no_refuse") and any(h in ans.lower() for h in REFUSE_HINTS):
        errs.append("trả lời “không tìm thấy” dù đã gợi ý hướng dẫn xử lý (gây hiểu nhầm)")
    if case.get("clarify") and not r.get("clarify"):
        errs.append("không hỏi lại dù câu hỏi chưa rõ")
    v = r.get("verify") or {}
    if v.get("invalid_citations"):
        errs.append(f"trích dẫn không tồn tại: {v['invalid_citations']}")
    if v.get("bad_numbers"):
        errs.append(f"số liệu không có trong nguồn được trích: {v['bad_numbers']}")
    if v.get("bad_quotes"):
        errs.append(f"trích dẫn nguyên văn sai (đã bị loại): {v['bad_quotes']}")
    if v.get("unsupported"):
        errs.append(f"câu không có trong nguồn: {v['unsupported'][:2]}")
    if v.get("truncated"):
        errs.append("câu trả lời bị cắt vì chạm ANSWER_MAX_TOKENS")
    if v.get("fixed_citations"):  # không tính lỗi, nhưng ghi lại để theo dõi mô hình trích dẫn lệch
        print(f"    (đã tự sửa trích dẫn: {v['fixed_citations'][:2]})")
    return errs


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="danh sách id, ví dụ B1,A1")
    ap.add_argument("--show", action="store_true", help="in đầy đủ câu trả lời")
    a = ap.parse_args()
    cases = [x for x in CASES if not a.only or x["id"] in a.only.split(",")]
    results, passed = [], 0
    with httpx.Client(timeout=900) as c:
        for case in cases:
            try:
                r = ask(c, case)
                errs = judge(case, r)
            except Exception as e:
                r, errs = {"_seconds": None}, [f"lỗi gọi API: {e}"]
            ok = not errs
            passed += ok
            ans = (r.get("answer") or "").replace("\n", " ")
            print(f"[{'ĐẠT ' if ok else 'LỖI '}] {case['id']:<3} {r.get('_seconds')!s:>6} giây"
                  f" (chữ đầu {r.get('_first')!s:>5} s)  {case['q'][:56]}")
            for e in errs:
                print(f"         - {e}")
            if r.get("clarify"):
                print(f"         ⤷ hỏi lại: {', '.join(o['label'] for o in r['clarify']['options'][:4])}")
            print(f"         → {ans if a.show else ans[:160]}")
            results.append({"case": case, "ok": ok, "errors": errs, "seconds": r.get("_seconds"),
                            "first_seconds": r.get("_first"),
                            "route": r.get("route"), "answer": r.get("answer"),
                            "sources": r.get("sources"), "verify": r.get("verify")})
    times = [x["seconds"] for x in results if x["seconds"]]
    firsts = [x["first_seconds"] for x in results if x.get("first_seconds")]
    print(f"\nKết quả: {passed}/{len(cases)} đạt; thời gian trung bình {sum(times) / max(len(times), 1):.1f} giây/câu; "
          f"chữ đầu tiên sau trung bình {sum(firsts) / max(len(firsts), 1):.1f} giây")
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"eval-{datetime.now():%Y%m%d-%H%M%S}.json"
    f.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Chi tiết: {f}")


if __name__ == "__main__":
    main()
