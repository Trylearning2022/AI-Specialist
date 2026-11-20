"""Kiểm tra máy phát triển trước khi chạy thử (đa nền tảng, chỉ dùng thư viện chuẩn của Python).

    python backend/tests/check_env.py

Kiểm tra: phiên bản Python, git, docker, node/npm, pandoc; cổng còn trống; kết nối PostgreSQL
(kèm extension pg_trgm) và Redis nếu đã cài thư viện trong .venv. Mã thoát 0 = đạt các mục bắt buộc.
"""
import os
import re
import shutil
import socket
import subprocess
import sys

DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://ai:ai@127.0.0.1:55432/ai")
REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:56379/0")
APP_PORTS = [5173, 8100, 8101, 8102, 8103, 8104, 8105, 8106, 8107, 9000]

fails = 0


def show(ok, item, detail="", required=True):
    global fails
    mark = "ĐẠT " if ok else ("LỖI " if required else "THIẾU")
    if not ok and required:
        fails += 1
    print(f"[{mark}] {item:<34} {detail}")


def version(cmd):
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        out = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0] if out.returncode == 0 else ""
    except Exception:
        return ""


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("== Phần mềm ==")
    py = sys.version_info
    show(py >= (3, 12), "Python >= 3.12", sys.version.split()[0])
    for cmd, name, req in [(["git", "--version"], "Git", True),
                           (["docker", "compose", "version"], "Docker Compose", True),
                           (["node", "--version"], "Node.js >= 20 (giao diện)", False),
                           (["npm", "--version"], "npm (giao diện)", False),
                           (["pandoc", "--version"], "pandoc (xuất DOCX)", False)]:
        v = version(cmd)
        ok = bool(v)
        if ok and cmd[0] == "node":
            m = re.search(r"v(\d+)", v)
            ok = bool(m) and int(m.group(1)) >= 20
        show(ok, name, v or "không tìm thấy trong PATH", req)

    print("== Docker ==")
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], capture_output=True, text=True) \
        if shutil.which("docker") else None
    if out is None or out.returncode != 0:
        show(False, "Docker Engine đang chạy", "chưa chạy – mở Docker Desktop", required=False)
    else:
        show(True, "Docker Engine đang chạy")
        st = dict(line.split("\t", 1) for line in out.stdout.splitlines() if "\t" in line)
        for c in ("ai-test-postgres", "ai-test-redis"):
            show("healthy" in st.get(c, ""), f"Container {c}", st.get(c, "chưa tạo – chạy bước 2"), required=False)

    print("== PostgreSQL / Redis ==")
    try:
        from sqlalchemy import create_engine, text
        with create_engine(DB_URL).connect() as c:
            v = c.execute(text("SHOW server_version")).scalar()
            show(True, "PostgreSQL", f"{v} ({DB_URL.split('@')[-1]})")
            n = c.execute(text("SELECT count(*) FROM pg_available_extensions WHERE name='pg_trgm'")).scalar()
            show(n == 1, "Extension pg_trgm có sẵn")
    except ImportError:
        show(False, "PostgreSQL", "bỏ qua: chưa cài thư viện (bước 1)", required=False)
    except Exception as e:
        show(False, "PostgreSQL", f"không kết nối được: {str(e).splitlines()[0][:80]}")
    try:
        import redis
        show(bool(redis.Redis.from_url(REDIS_URL, socket_timeout=3).ping()), "Redis", REDIS_URL)
    except ImportError:
        show(False, "Redis", "bỏ qua: chưa cài thư viện (bước 1)", required=False)
    except Exception as e:
        show(False, "Redis", f"không kết nối được: {e}")

    print("== OCR (tùy chọn) ==")
    try:
        import httpx
        ok = httpx.get("http://127.0.0.1:5001/health", timeout=3).status_code == 200
    except Exception:
        ok = False
    show(ok, "docling-serve (127.0.0.1:5001)",
         "đang chạy" if ok else "chưa chạy – PDF scan, ảnh sẽ bị từ chối (bật: --profile ocr)", required=False)

    print("== Cổng của hệ thống thử nghiệm ==")
    busy = [p for p in APP_PORTS if port_busy(p)]
    show(not busy, "Cổng 5173, 8100-8107, 9000",
         "còn trống" if not busy else f"đang bị dùng: {busy} (hệ thống đang chạy, hoặc tiến trình cũ chưa tắt)",
         required=False)

    print("\nKết luận:", "ĐẠT – có thể chạy bước 3." if not fails else f"{fails} mục bắt buộc chưa đạt.")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
