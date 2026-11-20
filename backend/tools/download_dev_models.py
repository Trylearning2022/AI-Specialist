"""Tải mô hình GGUF cho máy phát triển từ Hugging Face (chạy trên máy có Internet).

    pip install huggingface_hub
    python -m tools.download_dev_models                 # bộ mặc định: Qwen3.5-9B + bge-m3 + bge-reranker-v2-m3
    python -m tools.download_dev_models --chat 4b       # mô hình chính nhỏ hơn (Qwen3.5-4B)
    python -m tools.download_dev_models --dest D:\\models

Tệp lưu vào thư mục models/ của dự án và sinh SHA256SUMS để kiểm tra khi chép sang mạng nội bộ:
    (Linux) sha256sum -c SHA256SUMS    (Windows) Get-FileHash <tệp> -Algorithm SHA256
"""
import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT = {
    "9b": ("unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf"),
    "4b": ("unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf"),
}
EMBED = ("gpustack/bge-m3-GGUF", "bge-m3-Q8_0.gguf")
RERANK = ("gpustack/bge-reranker-v2-m3-GGUF", "bge-reranker-v2-m3-Q8_0.gguf")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", choices=sorted(CHAT), default="9b")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--dest", default=str(ROOT / "models"))
    a = ap.parse_args()
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        sys.exit("Chưa có thư viện huggingface_hub: pip install huggingface_hub")
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    items = [CHAT[a.chat], EMBED] + ([] if a.no_rerank else [RERANK])
    sums = []
    for repo, fname in items:
        target = dest / fname
        if not target.exists():
            print(f"Tải {repo}/{fname} …")
            hf_hub_download(repo_id=repo, filename=fname, local_dir=str(dest))
        digest = sha256(target)
        sums.append(f"{digest}  {fname}")
        print(f"[OK] {fname} {target.stat().st_size / 1e9:.2f} GB sha256={digest[:16]}…")
    (dest / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(f"Hoàn thành. Danh sách mã băm: {dest / 'SHA256SUMS'}")


if __name__ == "__main__":
    main()
