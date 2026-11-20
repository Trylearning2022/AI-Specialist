"""Trình chạy hệ thống thử nghiệm – đa nền tảng (Windows, Linux, macOS), KHÔNG cần mô hình thật.

Chạy toàn bộ 8 dịch vụ backend + Celery worker + máy chủ mô hình giả lập trên máy phát triển.
PostgreSQL và Redis lấy từ docker-compose.test.yml (hoặc máy chủ sẵn có, khai báo qua biến môi trường).

    python tests/run_stack.py            # chạy và giữ ở cửa sổ hiện tại, Ctrl+C để dừng tất cả
    python tests/run_stack.py --reset    # xóa dữ liệu thử nghiệm cũ trước khi chạy
    python tests/run_stack.py --real --reset   # dùng mô hình thật (chạy tests/run_models.py trước)

Chế độ --real dùng CSDL riêng (tên CSDL thêm hậu tố _that), Redis số 1 và thư mục .test-run-that,
nên không làm lẫn dữ liệu với chế độ mô hình giả lập.

Biến môi trường tùy chọn: TEST_DATABASE_URL, TEST_REDIS_URL, TEST_RUN_DIR.
Sau khi chạy: API http://127.0.0.1:8100/api/docs ; giao diện: cd frontend && npm run dev → http://localhost:5173
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
WIN = os.name == "nt"

DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://ai:ai@127.0.0.1:55432/ai")
REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:56379/0")
RUN = Path(os.getenv("TEST_RUN_DIR", str(ROOT / ".test-run")))

SERVICES = [  # (tên, module, cổng)
    ("mock-llm", "tests.mock_llm:app", 9000),  # bị bỏ qua ở chế độ --real
    ("gateway", "services.gateway.app:app", 8100),
    ("orchestrator", "services.orchestrator.app:app", 8101),
    ("search", "services.search.app:app", 8102),
    ("exact", "services.exact.app:app", 8103),
    ("ingest", "services.ingest.app:app", 8104),
    ("summary", "services.summary.app:app", 8105),
    ("support", "services.support.app:app", 8106),
    ("audit", "services.audit.app:app", 8107),
]


REAL = False
LLM_URL = os.getenv("TEST_LLM_URL", "http://127.0.0.1:8080/v1")
EMBED_URL = os.getenv("TEST_EMBED_URL", "http://127.0.0.1:8081")
RERANK_URL = os.getenv("TEST_RERANK_URL", "http://127.0.0.1:8082")


def remove_tree(path: Path):
    """Xóa thư mục kể cả tệp chỉ đọc (Windows: đối tượng Git là tệp chỉ đọc, rmtree thường bỏ sót)."""
    import stat

    def _retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=_retry)
    if path.exists():
        sys.exit(f"[LỖI] Không xóa hết được {path} (tệp đang bị khóa bởi tiến trình khác hoặc OneDrive?). "
                 "Dừng mọi tiến trình cũ, xóa thư mục này thủ công rồi chạy lại.")


def use_real_models():
    """Chuyển sang mô hình thật: CSDL, Redis, thư mục dữ liệu riêng; bỏ máy chủ giả lập."""
    global REAL, DB_URL, REDIS_URL, RUN, SERVICES
    REAL = True
    base, name = DB_URL.rsplit("/", 1)
    DB_URL = os.getenv("TEST_DATABASE_URL_REAL", f"{base}/{name}_that")
    REDIS_URL = os.getenv("TEST_REDIS_URL_REAL", REDIS_URL.rsplit("/", 1)[0] + "/1")
    RUN = Path(os.getenv("TEST_RUN_DIR_REAL", str(ROOT / ".test-run-that")))
    SERVICES = [s for s in SERVICES if s[0] != "mock-llm"]


DOCLING_URL = os.getenv("TEST_DOCLING_URL", "http://127.0.0.1:5001")
OCR_ON = False


def check_docling():
    """Dịch vụ OCR (docling-serve) là tùy chọn: có thì dùng cho PDF scan, ảnh; không có thì PDF scan bị từ chối."""
    global OCR_ON
    if DOCLING_URL.lower() in ("", "none", "off"):
        OCR_ON = False
    else:
        try:
            OCR_ON = httpx.get(f"{DOCLING_URL}/health", timeout=5).status_code == 200
        except httpx.HTTPError:
            OCR_ON = False
    if OCR_ON:
        print(f"OCR (docling-serve): đang chạy tại {DOCLING_URL} – nạp được PDF scan, ảnh.")
    else:
        print("[CẢNH BÁO] Chưa chạy dịch vụ OCR (docling-serve): PDF scan, ảnh sẽ bị từ chối khi nạp.\n"
              "  → Bật: docker compose -f docker-compose.test.yml --profile ocr up -d  (xem docs/huong-dan-chay-thu.md)")


def check_models():
    """Chế độ --real: các llama-server phải đang chạy trước."""
    targets = {"mô hình chính": LLM_URL.rsplit("/v1", 1)[0], "embedding": EMBED_URL}
    if RERANK_URL:
        targets["reranker"] = RERANK_URL
    for name, base in targets.items():
        try:
            ok = httpx.get(f"{base}/health", timeout=5).status_code == 200
        except httpx.HTTPError:
            ok = False
        if not ok:
            sys.exit(f"[LỖI] Không kết nối được {name} tại {base}.\n"
                     f"  → Chạy trước trong terminal khác: python tests/run_models.py --llama-dir <thư mục llama.cpp>")


def env() -> dict:
    e = dict(os.environ)
    e.update({
        "PYTHONPATH": str(BACKEND), "PYTHONIOENCODING": "utf-8",
        "DATABASE_URL": DB_URL, "REDIS_URL": REDIS_URL, "QDRANT_URL": f"path:{RUN / 'qdrant'}",
        "INTERNAL_SECRET": "test-secret", "AUTH_MODE": "dev", "DEV_AUTH_ALLOWED": "true", "SYSTEM_MAX_CLEARANCE": "1",
        "LLM_BASE_URL": "http://127.0.0.1:9000/v1", "EMBED_URL": "http://127.0.0.1:9000",
        "RERANK_URL": "http://127.0.0.1:9000", "RERANK_THRESHOLD": "-0.5",
        "DOCLING_URL": DOCLING_URL if OCR_ON else "",
        "DOCLING_TIMEOUT": os.getenv("DOCLING_TIMEOUT", "1800"),  # OCR trên CPU laptop chậm
        "DATA_DIR": str(RUN / "data"), "KB_DIR": str(RUN / "kb"),
        "SKILLS_DIR": str(ROOT / "skills"), "PROMPTS_DIR": str(ROOT / "prompts"),
        "GLOSSARY_FILE": str(ROOT / "glossary" / "thuat-ngu.md"), "SUPPORT_DIR": str(ROOT / "support"),
        "DEV_USERS_FILE": str(ROOT / "config" / "users.dev.yaml"),
        "RATE_LIMIT_PER_MIN": "5000", "RATE_LIMIT_CHAT_PER_MIN": "500",
    })
    if REAL:
        e.update({
            "LLM_BASE_URL": LLM_URL, "EMBED_URL": EMBED_URL, "RERANK_URL": RERANK_URL,
            "RERANK_THRESHOLD": os.getenv("RERANK_THRESHOLD", "-2.0"),
            "LLM_DISABLE_THINKING": "true", "LLM_TIMEOUT": os.getenv("LLM_TIMEOUT", "900"),
            "CTX_WINDOW": os.getenv("CTX_WINDOW", "16384"),
            # Hồ sơ CPU (máy dev chỉ có CPU). Mọi giá trị đổi được bằng biến môi trường cùng tên trước khi chạy,
            # ví dụ PowerShell:  $env:ANSWER_MAX_TOKENS="1000"; python tests/run_stack.py --real
            # Ý nghĩa, cách chọn: docs/tinh-chinh-truy-xuat.md
            "CTX_BUDGET_SOURCES": os.getenv("CTX_BUDGET_SOURCES", "4000"),     # token nguồn → thời gian đọc ngữ cảnh
            "ANSWER_MAX_TOKENS": os.getenv("ANSWER_MAX_TOKENS", "800"),        # quá thấp → câu trả lời bị cắt
            "SEARCH_TOP_K": os.getenv("SEARCH_TOP_K", "5"),                    # số mục đưa cho mô hình
            "SEARCH_CANDIDATES": os.getenv("SEARCH_CANDIDATES", "20"),         # ứng viên xếp hạng lại
            "SEARCH_SECTION_MAX_TOKENS": os.getenv("SEARCH_SECTION_MAX_TOKENS", "900"),
            "AGENT_TIMEOUT_S": os.getenv("AGENT_TIMEOUT_S", "600"),
        })
    for name, _, port in SERVICES:
        if name == "mock-llm":
            continue
        e[f"{name.upper()}_URL"] = f"http://127.0.0.1:{port}"
    return e


def check_deps():
    from sqlalchemy import create_engine, text
    import redis

    sys.path.insert(0, str(BACKEND))
    from tests.pgutil import ensure_db
    try:
        ensure_db(DB_URL)
        create_engine(DB_URL).connect().execute(text("SELECT 1"))
    except Exception as e:
        sys.exit(f"[LỖI] Không kết nối được PostgreSQL ({DB_URL}): {e}\n"
                 f"  → Chạy: docker compose -f docker-compose.test.yml up -d --wait   (tại thư mục gốc dự án)")
    try:
        redis.Redis.from_url(REDIS_URL, socket_timeout=3).ping()
    except Exception as e:
        sys.exit(f"[LỖI] Không kết nối được Redis ({REDIS_URL}): {e}\n"
                 f"  → Chạy: docker compose -f docker-compose.test.yml up -d --wait")
    if not shutil.which("git"):
        sys.exit("[LỖI] Chưa cài git (exact-svc dùng git cho kho văn bản chuẩn).")
    if not shutil.which("pandoc"):
        print("[CẢNH BÁO] Chưa cài pandoc: chức năng xuất DOCX trả lỗi 501 (các chức năng khác vẫn chạy).")


def start() -> list[subprocess.Popen]:
    (RUN / "logs").mkdir(parents=True, exist_ok=True)
    e, procs = env(), []
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
    for name, module, port in SERVICES:
        log = open(RUN / "logs" / f"{name}.log", "w", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--port", str(port), "--log-level", "warning"],
                             cwd=BACKEND, env=e, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        procs.append(p)
        if name == "mock-llm":
            time.sleep(1)
    log = open(RUN / "logs" / "worker.log", "w", encoding="utf-8")
    pool = ["-P", "solo"] if WIN else ["-c", "2"]  # Windows không hỗ trợ prefork của Celery
    procs.append(subprocess.Popen([sys.executable, "-m", "celery", "-A", "aicommon.queue", "worker", "-Q",
                                   "ingest,summary", "--loglevel=WARNING", *pool],
                                  cwd=BACKEND, env=e, stdout=log, stderr=subprocess.STDOUT, creationflags=flags))
    return procs


def wait_ready(procs, timeout=90) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        dead = [SERVICES[i][0] if i < len(SERVICES) else "worker" for i, p in enumerate(procs) if p.poll() is not None]
        if dead:
            return {"status": "dead", "dead": dead}
        try:
            r = httpx.get("http://127.0.0.1:8100/api/health", timeout=5).json()
            if r["status"] == "ok":
                return r
        except Exception:
            pass
        time.sleep(1.5)
    return {"status": "timeout"}


def stop(procs):
    for p in procs:
        if p.poll() is None:
            p.send_signal(signal.CTRL_BREAK_EVENT) if WIN else p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def seed():
    """Nạp kb-seed qua đúng quy trình nạp – duyệt (bỏ qua nếu kho văn bản chuẩn đã có dữ liệu)."""
    h = {"Authorization": "Bearer dev-canbo"}
    try:
        docs = httpx.get("http://127.0.0.1:8100/api/exact/catalog", headers=h, timeout=30).json()["docs"]
    except Exception:
        docs = []
    if docs:
        print(f"Kho văn bản chuẩn đã có {len(docs)} văn bản – bỏ qua nạp dữ liệu mẫu.")
        return
    print("Nạp dữ liệu mẫu kb-seed (mô hình thật: có thể mất vài phút)…")
    r = subprocess.run([sys.executable, "-m", "tools.seed", str(ROOT / "kb-seed")], cwd=BACKEND, env=env())
    if r.returncode != 0:
        print("[CẢNH BÁO] Nạp dữ liệu mẫu chưa hoàn tất – xem nhật ký ingest.log, worker.log.")


def main():
    if hasattr(sys.stdout, "reconfigure"):  # terminal Windows không phải UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Chạy hệ thống AI Local ở chế độ thử nghiệm")
    ap.add_argument("--reset", action="store_true", help="xóa dữ liệu thử nghiệm (CSDL, kho, chỉ mục) trước khi chạy")
    ap.add_argument("--real", action="store_true", help="dùng mô hình thật (llama-server) thay mô hình giả lập")
    ap.add_argument("--seed", action="store_true", help="nạp dữ liệu mẫu kb-seed nếu kho còn trống")
    ap.add_argument("--no-rerank", action="store_true", help="chế độ --real: không dùng reranker")
    ap.add_argument("--reindex", action="store_true",
                    help="lập chỉ mục lại toàn bộ tài liệu Luồng A (sau khi đổi cách tách đoạn, mô hình embedding)")
    a = ap.parse_args()
    if a.real:
        global RERANK_URL
        if a.no_rerank or RERANK_URL.lower() in ("", "none", "off"):
            RERANK_URL = ""
        use_real_models()
        check_models()
    if a.reset:
        sys.path.insert(0, str(BACKEND))
        from tests.pgutil import recreate_db
        try:
            recreate_db(DB_URL)
        except Exception as e:
            sys.exit(f"[LỖI] Không tạo lại được CSDL: {e}")
        remove_tree(RUN)
        try:  # xóa hàng đợi Celery, luồng kiểm toán còn sót của lần chạy trước
            import redis
            redis.Redis.from_url(REDIS_URL, socket_timeout=3).flushdb()
        except Exception:
            pass
    check_deps()
    check_docling()
    print(f"Khởi động dịch vụ… (nhật ký: {RUN / 'logs'})")
    procs = start()
    r = wait_ready(procs)
    if r["status"] != "ok":
        stop(procs)
        sys.exit(f"[LỖI] Hệ thống không sẵn sàng: {r}. Xem nhật ký trong {RUN / 'logs'}")
    if a.seed:
        seed()
    if a.reindex:
        print("Lập chỉ mục lại Luồng A (mô hình thật: mỗi tài liệu vài giây đến vài chục giây)…")
        r = subprocess.run([sys.executable, "-m", "tools.reindex"], cwd=BACKEND, env=env())
        print("Đã lập chỉ mục lại." if r.returncode == 0 else "[CẢNH BÁO] Lập chỉ mục lại chưa hoàn tất – xem thông báo ở trên.")
    print("Hệ thống thử nghiệm đã sẵn sàng" + (" (mô hình thật):" if REAL else ":"))
    print("  API Gateway : http://127.0.0.1:8100/api/docs")
    print("  Giao diện   : cd frontend && npm run dev  → http://localhost:5173 (tài khoản thử nghiệm: canbo, kiemduyet1, kiemduyet2, quantri)")
    if REAL:
        print("  Đánh giá    : cd backend && python tests/eval_real.py   (bộ câu hỏi mẫu, đo thời gian)")
    else:
        print("  Kiểm thử    : cd backend && python -m pytest")
    print("Nhấn Ctrl+C để dừng.")

    def _quit(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _quit)
    if WIN:
        signal.signal(signal.SIGBREAK, _quit)
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("[LỖI] Một dịch vụ đã dừng bất thường – xem nhật ký.")
    except KeyboardInterrupt:
        pass
    finally:
        print("Đang dừng các dịch vụ…")
        stop(procs)


if __name__ == "__main__":
    main()
