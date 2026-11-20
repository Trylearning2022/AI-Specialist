"""Kho văn bản chuẩn (Luồng B): kho Git các tệp Markdown đã duyệt.

Không dùng vector. Định vị nội dung bằng mã định danh, mục lục và tìm kiếm toàn văn trên
PostgreSQL (pgindex.py). Kho Git là nguồn duy nhất; nguyên văn luôn đọc từ tệp trong kho.
"""
import hashlib
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from aicommon.markdown import Section, parse_sections, section_text, split_frontmatter
from aicommon.text import nfc, unaccent

from .pgindex import GIT_LOCK_KEY, PgIndex, pg_lock

log = logging.getLogger("exact.kb")
DOC_DIR = "van-ban"


@dataclass
class Doc:
    doc_id: str
    path: str
    meta: dict
    sections: list[Section]
    lines: list[str]
    sec_by_id: dict[str, Section] = field(default_factory=dict)


def git(kb: Path, *args: str, check: bool = True, env: dict | None = None) -> str:
    e = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8", **(env or {})}
    r = subprocess.run(["git", "-C", str(kb), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


class KB:
    def __init__(self, root: str):
        self.root = Path(root)
        self.docs: dict[str, Doc] = {}
        self.sections: dict[str, tuple[Doc, Section]] = {}
        self.commit = ""
        self.lock = threading.RLock()
        self.index = PgIndex()

    # ---------- khởi tạo, nạp ----------
    def ensure_repo(self):
        gitdir = self.root / ".git"
        if gitdir.exists():
            if not (gitdir / "HEAD").is_file():
                # .git còn sót nhưng hỏng (ví dụ xóa dở trên Windows): dừng rõ ràng, không ghi đè kho chuẩn
                raise RuntimeError(f"Kho văn bản chuẩn không hợp lệ: {gitdir} thiếu tệp HEAD. "
                                   "Khôi phục từ bản sao lưu; nếu là môi trường thử nghiệm thì xóa thư mục kho rồi chạy lại.")
            return
        with pg_lock(GIT_LOCK_KEY):
            self._init_repo()

    def _init_repo(self):
        (self.root / DOC_DIR).mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            git(self.root, "init", "-q", "-b", "main")
            git(self.root, "config", "user.name", "AI Local")
            git(self.root, "config", "user.email", "ai-local@noibo.local")
            (self.root / "README.md").write_text("# Kho văn bản chuẩn (Luồng B)\n", encoding="utf-8")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-q", "-m", "Khởi tạo kho văn bản chuẩn")

    def load(self, only: set[str] | None = None, force_index: bool = False, sync: bool = True):
        """Nạp kho vào bộ nhớ và đồng bộ chỉ mục PostgreSQL (only: chỉ đồng bộ các văn bản thay đổi)."""
        with self.lock:
            self.ensure_repo()
            docs, secs = {}, {}
            for p in sorted((self.root / DOC_DIR).rglob("*.md")):
                text = nfc(p.read_text(encoding="utf-8"))
                meta, _, _ = split_frontmatter(text)
                doc_id = str(meta.get("id") or p.stem)
                sections, lines = parse_sections(doc_id, text)
                d = Doc(doc_id, str(p.relative_to(self.root)), meta, sections, lines,
                        {s.id: s for s in sections})
                docs[doc_id] = d
                for s in sections:
                    secs[s.id] = (d, s)
            self.docs, self.sections = docs, secs
            try:
                self.commit = git(self.root, "rev-parse", "HEAD").strip()
            except RuntimeError:
                self.commit = ""
            if sync:
                self.index.sync(docs, self.commit, only=only, force=force_index)
            log.info("Đã nạp %d văn bản, %d mục, commit %s", len(docs), len(secs), self.commit[:10])

    def head(self) -> str:
        """Đọc nhanh commit HEAD của kho (không gọi tiến trình git)."""
        try:
            ref = (self.root / ".git" / "HEAD").read_text().strip()
            if ref.startswith("ref: "):
                p = self.root / ".git" / ref[5:]
                if p.exists():
                    return p.read_text().strip()
                return git(self.root, "rev-parse", "HEAD").strip()
            return ref
        except (OSError, RuntimeError):
            return self.commit

    def refresh_if_changed(self):
        """Nhiều tiến trình dùng chung kho: tiến trình khác vừa ghi commit mới → nạp lại bộ nhớ.
        Chỉ mục PostgreSQL đã được tiến trình ghi đồng bộ nên không dựng lại."""
        if self.head() != self.commit:
            with self.lock:
                if self.head() != self.commit:
                    self.load(sync=False)

    # ---------- truy vấn ----------
    def doc_summary(self, d: Doc) -> dict:
        m = d.meta
        return {"doc_id": d.doc_id, "so_hieu": m.get("so_hieu", ""), "ten": m.get("ten", d.doc_id),
                "loai": m.get("loai", ""), "ngay_ban_hanh": str(m.get("ngay_ban_hanh", "") or ""),
                "trang_thai": m.get("trang_thai", "con_hieu_luc"), "thay_the_boi": m.get("thay_the_boi"),
                "do_mat": _do_mat(m),
                "don_vi": _units(m), "path": d.path}

    def toc(self, d: Doc) -> list[dict]:
        return [{"id": s.id, "level": s.level, "heading": s.heading, "kind": s.kind, "explicit": s.explicit,
                 "parent": s.parent} for s in d.sections]

    def section(self, sid: str) -> dict | None:
        hit = self.sections.get(sid)
        if not hit:
            return None
        d, s = hit
        text = section_text(d.lines, s)
        return {"section_id": s.id, "doc_id": d.doc_id, "heading": s.heading, "path": s.path,
                "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "commit": self.commit, "explicit_id": s.explicit, "file": d.path,
                "lines": [s.start + 1, s.end], **{k: v for k, v in self.doc_summary(d).items() if k != "path"}}

    def search(self, query: str, limit: int = 10, doc_ids: set[str] | None = None) -> list[dict]:
        return self.index.search(query, limit, doc_ids)

    def resolve(self, query: str, doc_ids: set[str] | None = None) -> list[str]:
        """Phân giải tham chiếu trực tiếp: “Điều 5 khoản 2 Quyết định 123/QĐ-XXX”, mã mục…"""
        q = unaccent(nfc(query)).lower()
        found = [sid for sid in self.sections if sid.lower() in q]
        if found:
            return found
        cands = list(self.docs.values())
        by_so_hieu = [d for d in cands if d.meta.get("so_hieu")
                      and unaccent(str(d.meta["so_hieu"])).lower() in q]
        if by_so_hieu:
            cands = by_so_hieu
        elif len(cands) > 1:
            return []
        if doc_ids is not None:
            cands = [d for d in cands if d.doc_id in doc_ids]
        m_dieu = re.search(r"dieu\s+(\d+[a-z]?)", q)
        m_khoan = re.search(r"khoan\s+(\d+)", q)
        if not m_dieu:
            return []
        out = []
        for d in cands:
            for s in d.sections:
                h = unaccent(s.heading).lower()
                if re.match(rf"dieu\s+{m_dieu.group(1)}\b", h):
                    target = s
                    if m_khoan:
                        for b in d.sections:
                            if b.kind == "block" and b.parent == s.id and b.heading == f"Khoản {m_khoan.group(1)}":
                                target = b
                    out.append(target.id)
        return out

    def toc_text(self, doc_ids: list[str], max_items: int = 300) -> str:
        lines = []
        for did in doc_ids:
            d = self.docs.get(did)
            if not d:
                continue
            lines.append(f"# {d.meta.get('so_hieu', '')} – {d.meta.get('ten', did)}")
            for s in d.sections:
                if len(lines) >= max_items:
                    break
                lines.append(f"{'  ' * max(0, s.level - 2)}- [{s.id}] {s.heading}")
        return "\n".join(lines)

    def index_md(self) -> str:
        out = ["# Mục lục kho văn bản chuẩn", "", "| Số hiệu | Tên văn bản | Loại | Ngày ban hành | Trạng thái | Tệp |",
               "|---|---|---|---|---|---|"]
        for d in sorted(self.docs.values(), key=lambda x: str(x.meta.get("ngay_ban_hanh", "")), reverse=True):
            s = self.doc_summary(d)
            out.append(f"| {s['so_hieu']} | {s['ten']} | {s['loai']} | {s['ngay_ban_hanh']} | {s['trang_thai']} | {d.path} |")
        return "\n".join(out) + "\n"

    # ---------- ghi (qua quy trình duyệt) ----------
    def commit_file(self, rel: str, content: str, message: str, author: str, email: str, delete: bool = False) -> str:
        with self.lock, pg_lock(GIT_LOCK_KEY):  # một bộ ghi Git tại một thời điểm (mọi tiến trình, container)
            self.refresh_if_changed()
            p = (self.root / rel).resolve()
            if not str(p).startswith(str((self.root / DOC_DIR).resolve())):
                raise ValueError("Đường dẫn ngoài thư mục văn bản chuẩn")
            if delete:
                if p.exists():
                    git(self.root, "rm", "-q", str(p))
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                git(self.root, "add", str(p))
            doc_id = Path(rel).stem
            self.load(sync=False)  # cập nhật danh mục trong bộ nhớ trước khi sinh INDEX.md
            (self.root / "INDEX.md").write_text(self.index_md(), encoding="utf-8")
            git(self.root, "add", "INDEX.md")
            env = {"GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": email,
                   "GIT_COMMITTER_NAME": "AI Local", "GIT_COMMITTER_EMAIL": "ai-local@noibo.local"}
            if not git(self.root, "status", "--porcelain").strip():
                return self.commit
            git(self.root, "commit", "-q", "-m", message, env=env)
            self.commit = git(self.root, "rev-parse", "HEAD").strip()
            self.index.sync(self.docs, self.commit, only={doc_id})  # chỉ đồng bộ văn bản vừa thay đổi
            return self.commit

    def push(self, remote: str):
        try:
            git(self.root, "push", "-q", remote, "HEAD:main")
        except RuntimeError as e:
            log.warning("Không đẩy được lên kho Gitea: %s", e)

    def versions(self, d: Doc) -> list[dict]:
        out = git(self.root, "log", "--format=%H|%an|%aI|%s", "--", d.path, check=False)
        return [dict(zip(("commit", "tac_gia", "thoi_gian", "noi_dung"), ln.split("|", 3)))
                for ln in out.splitlines() if ln]

    def diff(self, d: Doc, a: str, b: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{7,40}", a) or not re.fullmatch(r"[0-9a-f]{7,40}", b):
            raise ValueError("Mã commit không hợp lệ")
        return git(self.root, "diff", "--no-color", a, b, "--", d.path, check=False)


def _norm(text: str) -> str:
    """Chuẩn hóa cho FTS: chữ thường, bỏ dấu (tìm được cả khi gõ không dấu)."""
    return unaccent(nfc(text)).lower()


def _units(m: dict) -> list[str]:
    u = m.get("don_vi") or ["chung"]
    return u if isinstance(u, list) else [u]


_DM = {"thuong": 0, "mat": 1, "toi_mat": 2, "tuyet_mat": 3}


def _do_mat(m: dict) -> int:
    v = m.get("do_mat", 0)
    if isinstance(v, int) or str(v).isdigit():
        return int(v)
    return _DM.get(str(v).lower(), 0)
