"""Chạy mô hình thật trên máy phát triển bằng llama-server (llama.cpp) – đa nền tảng.

Bật 3 tiến trình llama-server, mỗi tiến trình một mô hình:
    chat   (cổng 8080): mô hình ngôn ngữ chính, ví dụ Qwen3.5-9B-Q4_K_M.gguf
    embed  (cổng 8081): mô hình embedding cho Luồng A, ví dụ bge-m3-Q8_0.gguf
    rerank (cổng 8082): reranker, ví dụ bge-reranker-v2-m3-Q8_0.gguf (tùy chọn)

    python tests/run_models.py --llama-dir C:\\llama.cpp              # dùng tên tệp mặc định trong thư mục models/
    python tests/run_models.py --chat Qwen3.5-4B-Q4_K_M.gguf --no-rerank
    python tests/run_models.py --check                                 # chỉ kiểm tra tệp và llama-server, không chạy

Sau khi báo "Mô hình đã sẵn sàng", chạy hệ thống: python tests/run_stack.py --real --reset
Nhấn Ctrl+C để dừng cả 3 tiến trình.
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
RUN = Path(os.getenv("TEST_RUN_DIR_REAL", str(ROOT / ".test-run-that")))

DEFAULTS = {
    "chat": os.getenv("DEV_CHAT_MODEL", "Qwen3.5-9B-Q4_K_M.gguf"),
    "embed": os.getenv("DEV_EMBED_MODEL", "bge-m3-Q8_0.gguf"),
    "rerank": os.getenv("DEV_RERANK_MODEL", "bge-reranker-v2-m3-Q8_0.gguf"),
}
PORTS = {"chat": 8080, "embed": 8081, "rerank": 8082}


def find_server(llama_dir: str | None) -> str:
    exe = "llama-server.exe" if WIN else "llama-server"
    cands = []
    if llama_dir:
        d = Path(llama_dir)
        cands += [d / exe, d / "bin" / exe, d / "build" / "bin" / exe, d / "build" / "bin" / "Release" / exe]
    if os.getenv("LLAMA_SERVER"):
        cands.insert(0, Path(os.environ["LLAMA_SERVER"]))
    for c in cands:
        if c.is_file():
            return str(c)
    w = shutil.which("llama-server")
    if w:
        return w
    sys.exit("[LỖI] Không tìm thấy llama-server. Chỉ thư mục giải nén llama.cpp bằng --llama-dir "
             "hoặc biến LLAMA_SERVER, hoặc thêm thư mục đó vào PATH.")


def server_help(server: str) -> str:
    try:
        r = subprocess.run([server, "--help"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        return r.stdout + r.stderr
    except Exception as e:
        sys.exit(f"[LỖI] Không chạy được {server}: {e}")


def build_cmds(a, server: str, help_text: str) -> dict[str, list[str]]:
    mdir = Path(a.models_dir)
    common = ["--host", "127.0.0.1"]
    if a.threads:
        common += ["-t", str(a.threads)]
    cmds: dict[str, list[str]] = {}
    chat = [server, "-m", str(mdir / a.chat), "--port", str(PORTS["chat"]), "--alias", "chinh", "--jinja",
            # -c là tổng ngữ cảnh chia đều cho -np luồng: mỗi luồng cần đủ CTX_WINDOW của ứng dụng
            "-c", str(a.ctx * a.parallel), "-np", str(a.parallel), "--top-p", "0.8", "--top-k", "20", *common]
    # Tắt chế độ suy luận (thinking): bản llama.cpp mới dùng --reasoning off; bản cũ dùng --reasoning-budget 0.
    if "--reasoning " in help_text or "--reasoning," in help_text:
        chat += ["--reasoning", "off"]
    elif "--reasoning-budget" in help_text:
        chat += ["--reasoning-budget", "0"]
    if a.gpu_layers is not None:
        chat += ["-ngl", str(a.gpu_layers)]
    cmds["chat"] = chat
    cmds["embed"] = [server, "-m", str(mdir / a.embed), "--port", str(PORTS["embed"]), "--embedding",
                     "--pooling", "cls", "-c", "8192", "-b", "8192", "-ub", "8192", "-np", "1", *common]
    if not a.no_rerank:
        cmds["rerank"] = [server, "-m", str(mdir / a.rerank), "--port", str(PORTS["rerank"]), "--reranking",
                          "-c", "8192", "-b", "8192", "-ub", "8192", "-np", "1", *common]
    return cmds


def check_files(a) -> bool:
    ok = True
    mdir = Path(a.models_dir)
    for role in ("chat", "embed") + (() if a.no_rerank else ("rerank",)):
        p = mdir / getattr(a, role)
        if p.is_file():
            print(f"[ĐẠT ] {role:<6} {p} ({p.stat().st_size / 1e9:.2f} GB)")
        else:
            print(f"[LỖI ] {role:<6} không có tệp {p}")
            ok = False
    return ok


def port_busy(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_health(procs: dict, timeout: int) -> list[str]:
    pending, t0 = set(procs), time.time()
    with httpx.Client(timeout=5) as c:
        while pending and time.time() - t0 < timeout:
            for role in list(pending):
                if procs[role].poll() is not None:
                    return [role]
                try:
                    if c.get(f"http://127.0.0.1:{PORTS[role]}/health").status_code == 200:
                        pending.discard(role)
                        print(f"  {role:<6} sẵn sàng sau {time.time() - t0:.0f} giây")
                except httpx.HTTPError:
                    pass
            time.sleep(2)
    return sorted(pending)


def smoke(no_rerank: bool):
    """Gọi thử từng mô hình một lần để chắc chắn API trả đúng dạng hệ thống cần."""
    with httpx.Client(timeout=600) as c:
        t0 = time.time()
        r = c.post("http://127.0.0.1:8080/v1/chat/completions", json={
            "model": "chinh", "max_tokens": 64, "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": "Trả lời một câu: Thủ đô của Việt Nam là gì?"}]}).json()
        msg = r["choices"][0]["message"]["content"].strip().replace("\n", " ")
        tok = r.get("usage", {}).get("completion_tokens", 0)
        dt = time.time() - t0
        print(f"  chat  : \"{msg[:80]}\" ({tok} token, {dt:.1f} giây, ~{tok / max(dt, 1e-3):.1f} token/giây)")
        e = c.post("http://127.0.0.1:8081/v1/embeddings", json={"input": ["kiểm tra"], "model": "embed"}).json()
        print(f"  embed : vector {len(e['data'][0]['embedding'])} chiều")
        if not no_rerank:
            rr = c.post("http://127.0.0.1:8082/v1/rerank", json={
                "query": "thời hạn sử dụng thiết bị", "top_n": 2,
                "documents": ["Thiết bị được sử dụng tối đa 05 năm.", "Máy in đặt tại tầng 2."]}).json()
            sc = {x["index"]: round(x["relevance_score"], 2) for x in rr["results"]}
            print(f"  rerank: điểm câu liên quan {sc.get(0)}, câu không liên quan {sc.get(1)}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Chạy mô hình thật (llama-server) cho môi trường phát triển")
    ap.add_argument("--llama-dir", help="thư mục chứa llama-server (bản giải nén llama.cpp)")
    ap.add_argument("--models-dir", default=os.getenv("DEV_MODELS_DIR", str(ROOT / "models")))
    ap.add_argument("--chat", default=DEFAULTS["chat"], help="tệp GGUF mô hình chính")
    ap.add_argument("--embed", default=DEFAULTS["embed"], help="tệp GGUF mô hình embedding")
    ap.add_argument("--rerank", default=DEFAULTS["rerank"], help="tệp GGUF reranker")
    ap.add_argument("--no-rerank", action="store_true", help="không chạy reranker (tiết kiệm RAM, CPU)")
    ap.add_argument("--ctx", type=int, default=16384, help="ngữ cảnh mỗi yêu cầu của mô hình chính (mặc định 16384, khớp CTX_WINDOW)")
    ap.add_argument("--parallel", type=int, default=2, help="số yêu cầu đồng thời của mô hình chính")
    ap.add_argument("--threads", type=int, default=0, help="số luồng CPU (0 = llama.cpp tự chọn)")
    ap.add_argument("--gpu-layers", type=int, default=None, help="số lớp đưa lên GPU (bản CUDA/Vulkan), ví dụ 99")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra, không chạy")
    a = ap.parse_args()

    server = find_server(a.llama_dir)
    help_text = server_help(server)
    print(f"llama-server: {server}")
    files_ok = check_files(a)
    cmds = build_cmds(a, server, help_text)
    if a.check or not files_ok:
        for role, cmd in cmds.items():
            print(f"\n[{role}] " + " ".join(f'"{x}"' if " " in x else x for x in cmd))
        sys.exit(0 if files_ok else 1)

    busy = [p for r, p in PORTS.items() if r in cmds and port_busy(p)]
    if busy:
        sys.exit(f"[LỖI] Cổng {busy} đang bị dùng (llama-server cũ còn chạy?).")
    (RUN / "logs").mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
    procs = {}
    print(f"Nạp mô hình… (nhật ký: {RUN / 'logs'}; lần đầu có thể mất 1–3 phút)")
    for role, cmd in cmds.items():
        log = open(RUN / "logs" / f"llm-{role}.log", "w", encoding="utf-8")
        procs[role] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)

    def stop():
        for p in procs.values():
            if p.poll() is None:
                p.send_signal(signal.CTRL_BREAK_EVENT) if WIN else p.terminate()
        for p in procs.values():
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()

    bad = wait_health(procs, timeout=600)
    if bad:
        stop()
        sys.exit(f"[LỖI] Mô hình không khởi động được: {bad}. Xem {RUN / 'logs'}/llm-<tên>.log")
    print("Gọi thử từng mô hình:")
    try:
        smoke(a.no_rerank)
    except Exception as e:
        print(f"[CẢNH BÁO] Gọi thử lỗi: {e}")
    print("Mô hình đã sẵn sàng. Mở terminal khác và chạy: python tests/run_stack.py --real --reset")
    print("Nhấn Ctrl+C để dừng.")

    def _quit(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _quit)
    if WIN:
        signal.signal(signal.SIGBREAK, _quit)
    try:
        while all(p.poll() is None for p in procs.values()):
            time.sleep(1)
        print("[LỖI] Một tiến trình mô hình đã dừng bất thường – xem nhật ký.")
    except KeyboardInterrupt:
        pass
    finally:
        print("Đang dừng mô hình…")
        stop()


if __name__ == "__main__":
    main()
