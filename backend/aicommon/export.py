"""Xuất Markdown sang DOCX bằng pandoc (dùng tệp mẫu thể thức skills/reference.docx nếu có)."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import get_settings


class ExportError(RuntimeError):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def md_to_docx(md: str, title: str) -> Path:
    if not shutil.which("pandoc"):
        raise ExportError(501, "Máy chủ chưa cài pandoc – không xuất được DOCX")
    tmp = Path(tempfile.mkdtemp())
    src, out = tmp / "van-ban.md", tmp / "van-ban.docx"
    src.write_text(md, encoding="utf-8")
    cmd = ["pandoc", str(src), "-f", "gfm", "-o", str(out), "--metadata", f"title={title}"]
    ref = Path(get_settings().skills_dir) / "reference.docx"
    if ref.exists():
        cmd += ["--reference-doc", str(ref)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if r.returncode != 0:
        raise ExportError(500, f"Lỗi xuất DOCX: {r.stderr[:300]}")
    return out
