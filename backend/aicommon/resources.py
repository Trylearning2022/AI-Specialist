"""Tài nguyên dạng Markdown do người quản trị nghiệp vụ tùy biến: chỉ thị, kỹ năng, thuật ngữ."""
import os
import re
from functools import lru_cache
from pathlib import Path

from .config import get_settings
from .markdown import split_frontmatter
from .text import nfc, unaccent


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


@lru_cache(maxsize=64)
def _read(path: str, mtime: float) -> str:
    return nfc(Path(path).read_text(encoding="utf-8"))


def read_md(path: str | Path) -> str:
    p = Path(path)
    return _read(str(p), _mtime(p)) if p.exists() else ""


def prompt(name: str) -> str:
    """Đọc chỉ thị prompts/<name>.md (bỏ frontmatter nếu có)."""
    _, body, _ = split_frontmatter(read_md(Path(get_settings().prompts_dir) / f"{name}.md"))
    return body.strip()


def list_skills() -> list[dict]:
    root = Path(get_settings().skills_dir)
    out = []
    if root.exists():
        for d in sorted(root.iterdir()):
            f = d / "SKILL.md"
            if f.exists():
                meta, body, _ = split_frontmatter(read_md(f))
                out.append({"name": meta.get("name", d.name), "dir": str(d), "meta": meta, "body": body.strip()})
    return out


def get_skill(name: str) -> dict | None:
    return next((s for s in list_skills() if s["name"] == name), None)


def domain_skills() -> list[dict]:
    """Kỹ năng bối cảnh ngành (loai: nganh) – ví dụ skills/nganh-co-yeu. Có thể có nhiều; chỉ lấy loại mac_dinh."""
    return [s for s in list_skills() if s["meta"].get("loai") == "nganh" and s["meta"].get("mac_dinh", True)]


def domain_context() -> str:
    """Phần thân các kỹ năng bối cảnh ngành – nối vào chỉ thị phân tích, soạn thảo, tổng hợp.
    Tắt bằng biến môi trường DOMAIN_CONTEXT=0 (ví dụ khi đo thời gian trên CPU)."""
    if os.getenv("DOMAIN_CONTEXT", "1") in ("0", "false", "off"):
        return ""
    return "\n\n".join(s["body"] for s in domain_skills() if s["body"])


def expired_laws() -> list[dict]:
    """Danh mục văn bản đã hết hiệu lực khai báo trong kỹ năng ngành (frontmatter van_ban_het_hieu_luc)."""
    out = []
    for s in domain_skills():
        for x in s["meta"].get("van_ban_het_hieu_luc") or []:
            if isinstance(x, dict) and x.get("so_hieu"):
                out.append({k: str(v) for k, v in x.items()})
    return out


def skill_template(skill: dict) -> str:
    t = skill["meta"].get("output_template")
    return read_md(Path(skill["dir"]) / t) if t else ""


def glossary_hits(*texts: str, limit: int = 12) -> list[tuple[str, str]]:
    """Các thuật ngữ trong từ điển xuất hiện trong văn bản (so khớp không dấu)."""
    raw = read_md(get_settings().glossary_file)
    hay = " " + unaccent(" ".join(texts)).lower() + " "
    hits = []
    for ln in raw.splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", ln)
        if not m or m.group(1).lower() in ("thuật ngữ", "---") or set(m.group(1)) <= set("-: "):
            continue
        term = m.group(1)
        if re.search(r"(?<![a-z0-9])" + re.escape(unaccent(term).lower()) + r"(?![a-z0-9])", hay):
            hits.append((term, m.group(2)))
        if len(hits) >= limit:
            break
    return hits


def ensure_dirs(*paths: str):
    for p in paths:
        os.makedirs(p, exist_ok=True)
