"""Nạp dữ liệu mẫu/ban đầu qua đúng quy trình nạp – duyệt của hệ thống.

    python -m tools.seed /seed            # thư mục chứa van-ban/ (Luồng B) và tai-lieu/ (Luồng A)

Chạy bên trong mạng nội bộ của hệ thống (ví dụ: docker compose run --rm tools python -m tools.seed /seed).
Tài liệu Luồng B được duyệt hai cấp bởi hai tài khoản hệ thống khác nhau và ghi vết đầy đủ.
"""
import sys
import time
from pathlib import Path

from aicommon.config import get_settings
from aicommon.internal import ServiceError, SyncSvc
from aicommon.security import UserCtx

S = get_settings()
R1 = UserCtx(sub="seed-1", username="khoi-tao-1", name="Khởi tạo dữ liệu (cấp 1)", roles=["user", "reviewer", "admin"],
             units=["*"], clearance=S.system_max_clearance)
R2 = UserCtx(sub="seed-2", username="khoi-tao-2", name="Khởi tạo dữ liệu (cấp 2)", roles=["user", "reviewer", "admin"],
             units=["*"], clearance=S.system_max_clearance)
ingest = SyncSvc(S.ingest_url)


def wait(jid: str, timeout: int = 900) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = ingest.call("GET", f"/jobs/{jid}", R1)
        if j["status"] not in ("moi", "dang_xu_ly"):
            return j
        time.sleep(2)
    raise TimeoutError(jid)


def upload(path: Path) -> dict:
    with path.open("rb") as f:
        r = ingest.call("POST", "/jobs", R1, files={"file": (path.name, f)}, data={"do_mat": "0", "don_vi": "chung"})
    return wait(r["id"])


def main(root: str):
    root_p = Path(root)
    ok = 0
    for track, sub in (("B", "van-ban"), ("A", "tai-lieu")):
        for p in sorted((root_p / sub).glob("*")):
            if p.is_dir():
                continue
            j = upload(p)
            if j["status"] != "cho_duyet":
                print(f"[BỎ QUA] {p.name}: {j['status']} {j.get('error') or j.get('reject_reason')}")
                continue
            try:
                ingest.call("POST", f"/jobs/{j['id']}/approve", R1, json={"track": track})
                if track == "B":
                    ingest.call("POST", f"/jobs/{j['id']}/approve", R2, json={"track": "B"})
                ok += 1
                print(f"[OK] {p.name} → Luồng {track}")
            except ServiceError as e:
                print(f"[LỖI] {p.name}: {e.detail}")
    print(f"Hoàn thành: {ok} tài liệu.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/seed")
