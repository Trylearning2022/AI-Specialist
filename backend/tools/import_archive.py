"""Nạp HÀNG LOẠT kho văn bản đơn vị đã ban hành (tờ trình, công văn tham gia ý kiến, báo cáo…) vào Luồng A,
gắn nhóm "van_ban_di" để AI Local dùng làm TIỀN LỆ khi soạn văn bản, tham gia ý kiến dự thảo.

    python -m tools.import_archive /du-lieu/van-ban-di                    # mọi tệp .doc .docx .pdf .md .txt (đệ quy)
    python -m tools.import_archive /du-lieu/van-ban-di --don-vi PKT --do-mat 0 --duyet
    python -m tools.import_archive /du-lieu/van-ban-di --thu                # chỉ liệt kê, không nạp

Mặc định tài liệu được đưa vào hàng chờ kiểm duyệt (cán bộ duyệt trên giao diện "Kiểm duyệt").
Tùy chọn --duyet: duyệt Luồng A ngay bằng tài khoản hệ thống (chỉ dùng khi kho đã được rà soát trước, ghi vết đầy đủ).

Lưu ý an toàn:
- Chỉ nạp văn bản có độ mật trong phạm vi hệ thống được phép xử lý (SYSTEM_MAX_CLEARANCE); --do-mat phải khai đúng,
  tài liệu độ mật cao hơn bị phân hệ nạp từ chối.
- Tệp trùng hoàn toàn với tài liệu đã có được bỏ qua (so mã băm), chạy lại nhiều lần an toàn.
"""
import argparse
import hashlib
import sys
import time
from pathlib import Path

from aicommon.internal import ServiceError
from tools.seed import R1, ingest, wait, wait_approved

EXT = {".doc", ".docx", ".pdf", ".md", ".txt", ".odt", ".rtf"}


def _known_hashes() -> set[str]:
    """Mã băm các tệp đã nạp (qua danh sách tác vụ nạp) – để bỏ qua tệp trùng."""
    try:
        return {j.get("sha256") for j in ingest.call("GET", "/jobs", R1) if j.get("sha256")}
    except ServiceError:
        return set()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nạp kho văn bản đơn vị đã ban hành (nhóm van_ban_di)")
    ap.add_argument("thu_muc")
    ap.add_argument("--don-vi", default="chung", help="đơn vị được xem (phân cách dấu phẩy), mặc định: chung")
    ap.add_argument("--do-mat", type=int, default=0, help="độ mật khai báo cho cả lô (0 = thường)")
    ap.add_argument("--nhom", default="van_ban_di", choices=["van_ban_di", "van_ban_den", "tai_lieu"])
    ap.add_argument("--duyet", action="store_true", help="duyệt Luồng A ngay bằng tài khoản hệ thống")
    ap.add_argument("--thu", action="store_true", help="chỉ liệt kê tệp sẽ nạp")
    a = ap.parse_args(argv)

    root = Path(a.thu_muc)
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in EXT and not p.name.startswith("~$"))
    print(f"Tìm thấy {len(files)} tệp trong {root}")
    if a.thu:
        for p in files:
            print(" -", p.relative_to(root))
        return 0
    known = _known_hashes()
    ok = skip = err = 0
    t0 = time.time()
    for i, p in enumerate(files, 1):
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() in known:
            skip += 1
            continue
        try:
            r = ingest.call("POST", "/jobs", R1, files={"file": (p.name, data)},
                            data={"do_mat": str(a.do_mat), "don_vi": a.don_vi, "nhom": a.nhom})
            j = wait(r["id"])
            if j["status"] != "cho_duyet":
                err += 1
                print(f"[{i}/{len(files)}] [BỎ QUA] {p.name}: {j['status']} {j.get('error') or j.get('reject_reason') or ''}")
                continue
            if any(str(w).startswith("Tệp trùng hoàn toàn") for w in j.get("warnings") or []):
                ingest.call("POST", f"/jobs/{j['id']}/reject", R1, json={"ly_do": "Trùng hoàn toàn với tài liệu đã có (nạp hàng loạt)"})
                skip += 1
                continue
            if a.duyet:
                ingest.call("POST", f"/jobs/{j['id']}/approve", R1, json={"track": "A"})
                done = wait_approved(j["id"])
                if done["status"] != "da_duyet":
                    err += 1
                    print(f"[{i}/{len(files)}] [LỖI] {p.name}: {done.get('error') or done['status']}")
                    continue
            ok += 1
            print(f"[{i}/{len(files)}] [OK] {p.name}" + (" → đã duyệt" if a.duyet else " → chờ kiểm duyệt"))
        except ServiceError as e:
            err += 1
            print(f"[{i}/{len(files)}] [LỖI] {p.name}: {e.detail}")
    print(f"Hoàn thành sau {int(time.time() - t0)} giây: nạp {ok}, bỏ qua (trùng) {skip}, lỗi/từ chối {err}.")
    return 0 if not err else 1


if __name__ == "__main__":
    sys.exit(main())
