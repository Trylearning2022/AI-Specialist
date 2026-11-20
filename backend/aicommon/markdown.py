"""Phân tích tài liệu Markdown chuẩn: frontmatter, cây tiêu đề, mã định danh mục,
trích nguyên văn, tách đoạn cho Luồng A và chuẩn hóa cấu trúc văn bản hành chính."""
import re
from dataclasses import dataclass, field

import yaml

from .text import estimate_tokens, nfc, unaccent

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
ID_COMMENT = re.compile(r"^\s*<!--\s*id:\s*([\w.\-#]+)\s*-->\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
ITEM = re.compile(r"^(\d{1,3})\.\s+\S")

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_to_int(s: str) -> int | None:
    s = s.upper()
    if s.isdigit():
        return int(s)
    if not s or any(c not in ROMAN for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = ROMAN[c]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


# ---------------- Frontmatter ----------------
def split_frontmatter(text: str) -> tuple[dict, str, int]:
    """Trả (metadata, phần thân, số dòng của frontmatter)."""
    text = text.lstrip("﻿")
    if text.startswith("---"):
        lines = text.splitlines(keepends=True)
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                meta = yaml.safe_load("".join(lines[1:i])) or {}
                return (meta if isinstance(meta, dict) else {}), "".join(lines[i + 1:]), i + 1
    return {}, text, 0


def dump_frontmatter(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()
    return f"---\n{fm}\n---\n\n{body.lstrip()}"


# ---------------- Cây mục ----------------
@dataclass
class Section:
    id: str
    level: int
    heading: str
    start: int          # chỉ số dòng bắt đầu (trong toàn tệp)
    end: int            # chỉ số dòng kết thúc (không bao gồm)
    explicit: bool      # có mã định danh tường minh hay tự sinh
    kind: str = "heading"   # heading | block
    path: list[str] = field(default_factory=list)
    parent: str | None = None


def _auto_suffix(heading: str, idx: int) -> str:
    h = unaccent(heading).strip()
    for pat, pre in ((r"^Chuong\s+([IVXLC\d]+)", "C"), (r"^Muc\s+(\d+)", "M"), (r"^Dieu\s+(\d+[a-z]?)", "D"),
                     (r"^Phu luc\s*([IVXLC\d]*)", "PL"), (r"^Phan\s+([IVXLC\d]+)", "P")):
        m = re.match(pat, h, re.I)
        if m:
            val = m.group(1)
            n = roman_to_int(val) if pre in ("C", "P", "PL") and val else None
            return f"{pre}{n if n else val}"
    return f"H{idx}"


def parse_sections(doc_id: str, text: str) -> tuple[list[Section], list[str]]:
    """Phân tích mục của tệp Markdown. Trả (danh sách mục, các dòng của tệp)."""
    lines = text.splitlines(keepends=True)
    _, _, fm_lines = split_frontmatter(text)
    in_fence = False
    heads: list[tuple[int, int, str]] = []
    ids: list[tuple[int, str]] = []
    for i in range(fm_lines, len(lines)):
        ln = lines[i].rstrip("\n")
        if FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = ID_COMMENT.match(ln)
        if m:
            ids.append((i, m.group(1)))
            continue
        m = HEADING.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))

    sections: list[Section] = []
    head_by_line: dict[int, Section] = {}
    used: set[str] = set()
    for k, (i, lvl, txt) in enumerate(heads):
        end = len(lines)
        for j, lvl2, _ in heads[k + 1:]:
            if lvl2 <= lvl:
                end = j
                break
        sec = Section(id="", level=lvl, heading=txt, start=i, end=end, explicit=False)
        sections.append(sec)
        head_by_line[i] = sec

    def prev_nonblank(i: int) -> int:
        j = i - 1
        while j >= fm_lines and not lines[j].strip():
            j -= 1
        return j

    blocks: list[Section] = []
    for line_no, sid in ids:
        p = prev_nonblank(line_no)
        if p < fm_lines:
            continue
        if p in head_by_line:
            head_by_line[p].id = sid
            head_by_line[p].explicit = True
            used.add(sid)
            continue
        start = p
        while start - 1 >= fm_lines and lines[start - 1].strip() and not ID_COMMENT.match(lines[start - 1]) \
                and not HEADING.match(lines[start - 1].rstrip("\n")):
            start -= 1
        first = lines[start].strip()
        m = ITEM.match(first)
        name = f"Khoản {m.group(1)}" if m else (first[:60] + ("…" if len(first) > 60 else ""))
        blocks.append(Section(id=sid, level=7, heading=name, start=start, end=line_no, explicit=True, kind="block"))
        used.add(sid)

    # mã tự sinh cho tiêu đề không có mã tường minh
    stack: list[Section] = []
    for idx, sec in enumerate(sections):
        while stack and stack[-1].level >= sec.level:
            stack.pop()
        if not sec.id:
            base = (stack[-1].id if stack else doc_id) + "." + _auto_suffix(sec.heading, idx)
            sid, n = base, 2
            while sid in used:
                sid, n = f"{base}-{n}", n + 1
            sec.id = sid
            used.add(sid)
        sec.parent = stack[-1].id if stack else None
        sec.path = [s.heading for s in stack] + [sec.heading]
        stack.append(sec)

    # gắn khối (khoản) vào tiêu đề chứa nó
    for b in blocks:
        owner = None
        for s in sections:
            if s.start < b.start < s.end and (owner is None or s.level > owner.level):
                owner = s
        if owner:
            b.parent, b.path, b.level = owner.id, owner.path + [b.heading], owner.level + 1
        else:
            b.path = [b.heading]
    allsec = sorted(sections + blocks, key=lambda s: (s.start, s.level))
    return allsec, lines


def section_text(lines: list[str], sec: Section, strip_ids: bool = True) -> str:
    seg = lines[sec.start:sec.end]
    if strip_ids:
        seg = [ln for ln in seg if not ID_COMMENT.match(ln)]
    return "".join(seg).strip("\n")


# ---------------- Tách đoạn cho Luồng A ----------------
# Nguyên tắc (phương án mục 6.2.1):
#   1. Đơn vị gốc là MỤC (tiêu đề Markdown): một đoạn không vượt qua ranh giới mục, nên trích dẫn luôn
#      chỉ đúng một mục và nút "Xem nguyên văn" mở đúng chỗ.
#   2. Mục dài được cắt theo đoạn văn (dòng trống), có chồng lấn một dòng cuối để không mất câu nối.
#   3. Bảng Markdown dài được cắt theo dòng và LẶP LẠI dòng tiêu đề ở mỗi phần – mô hình luôn biết cột nào là gì.
#   4. Mỗi đoạn mang "breadcrumb" (Tên tài liệu › Chương › Điều …) – được ghép vào trước nội dung khi sinh
#      vector và khi xếp hạng lại (contextual chunk header), giúp đoạn ngắn vẫn mang đủ ngữ cảnh.
#   5. Đoạn quá ngắn (thường chỉ có tiêu đề) được gộp với đoạn kế tiếp cùng mục cha.
# Khi truy xuất, search-svc còn MỞ RỘNG đoạn trúng thành cả mục hoặc đoạn lân cận (search_section_max_tokens).
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}")


def _own_ranges(sections: list[Section], total: int, body_start: int):
    """Duyệt (mục, dòng bắt đầu, dòng kết thúc) của phần nội dung RIÊNG mỗi tiêu đề (không gồm mục con)."""
    heads = [s for s in sections if s.kind == "heading"]
    starts = [s.start for s in heads]
    if not heads or heads[0].start > body_start:
        yield None, body_start, (heads[0].start if heads else total)
    for k, s in enumerate(heads):
        nxt = starts[k + 1] if k + 1 < len(starts) else total
        yield s, s.start, nxt


def _split_table(block: str, max_tokens: int) -> list[str]:
    """Cắt bảng Markdown dài theo nhóm dòng, mỗi phần giữ dòng tiêu đề và dòng phân cách."""
    rows = block.split("\n")
    if len(rows) < 3 or not _TABLE_SEP.match(rows[1]):
        return [block]
    head, body = rows[:2], rows[2:]
    parts, cur = [], []
    for r in body:
        if cur and estimate_tokens("\n".join(head + cur + [r])) > max_tokens:
            parts.append("\n".join(head + cur))
            cur = []
        cur.append(r)
    if cur:
        parts.append("\n".join(head + cur))
    return parts


def _split_paragraphs(text: str, max_tokens: int) -> list[str]:
    """Cắt nội dung một mục thành các đoạn ≤ max_tokens theo ranh giới đoạn văn."""
    paras: list[str] = []
    for p in re.split(r"\n\s*\n", text):
        lines = p.strip().split("\n")
        is_table = len(lines) >= 3 and all(_TABLE_ROW.match(x) or _TABLE_SEP.match(x) for x in lines)
        paras.extend(_split_table(p.strip(), max_tokens) if is_table and estimate_tokens(p) > max_tokens else [p])
    cur, out = "", []
    for p in paras:
        if cur and estimate_tokens(cur + p) > max_tokens:
            out.append(cur.strip())
            tail = cur.strip().split("\n")[-1]  # chồng lấn: mang theo dòng cuối của đoạn trước
            if _TABLE_ROW.match(tail):
                tail = ""                        # không chồng lấn dòng bảng (đã có tiêu đề bảng lặp lại)
            cur = (tail + "\n\n" if tail and estimate_tokens(tail) < max_tokens // 6 else "") + p + "\n\n"
        else:
            cur += p + "\n\n"
    if cur.strip():
        out.append(cur.strip())
    final = []
    for c in out:  # đoạn đơn quá dài (không có dòng trống) → cắt cứng, chồng lấn 200 ký tự
        while estimate_tokens(c) > max_tokens * 1.5:
            cut = max_tokens * 3
            final.append(c[:cut])
            c = c[cut - 200:]
        final.append(c)
    return final


def _common_path(a: list[str], b: list[str]) -> list[str]:
    out = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return out


def chunk_markdown(doc_id: str, text: str, title: str = "", max_tokens: int | None = None,
                   min_tokens: int | None = None) -> list[dict]:
    """Tách tài liệu Markdown thành các đoạn để lập chỉ mục Luồng A.

    Trả danh sách dict: section_id (mục chứa đoạn), heading, breadcrumb, text, chunk_no (thứ tự trong tài liệu),
    part (thứ tự phần trong cùng mục). Kích thước mặc định lấy từ cấu hình CHUNK_MAX_TOKENS, CHUNK_MIN_TOKENS.
    """
    from .config import get_settings
    s = get_settings()
    max_tokens = max_tokens or s.chunk_max_tokens
    min_tokens = s.chunk_min_tokens if min_tokens is None else min_tokens
    sections, lines = parse_sections(doc_id, text)
    _, _, fm = split_frontmatter(text)
    raw: list[dict] = []
    for sec, a, b in _own_ranges(sections, len(lines), fm):
        body = "".join(ln for ln in lines[a:b] if not ID_COMMENT.match(ln)).strip()
        if not body or (sec and "\n" not in body and HEADING.match(body)):
            continue  # mục chỉ có dòng tiêu đề: tên mục đã nằm trong breadcrumb của các đoạn con
        path = sec.path if sec else []
        same = bool(path) and title and unaccent(path[0]).lower().strip() == unaccent(title).lower().strip()
        full = path if (same or not title) else [title] + path
        for k, part in enumerate(_split_paragraphs(body, max_tokens)):
            raw.append({"section_id": sec.id if sec else f"{doc_id}.dau",
                        "heading": sec.heading if sec else (title or doc_id),
                        "path": full or [title or doc_id], "text": part, "part": k,
                        "parent": sec.parent if sec else None})
    merged: list[dict] = []
    for c in raw:  # gộp đoạn quá ngắn liền kề cùng mục cha
        if merged and estimate_tokens(merged[-1]["text"]) < min_tokens \
                and merged[-1]["parent"] == c["parent"] \
                and estimate_tokens(merged[-1]["text"] + c["text"]) <= max_tokens:
            m = merged[-1]
            m["text"] += "\n\n" + c["text"]
            m["path"] = _common_path(m["path"], c["path"]) or m["path"][:1]  # breadcrumb chung cho đoạn gộp
            continue
        merged.append(dict(c))
    for i, c in enumerate(merged):
        c["chunk_no"] = i
        c["breadcrumb"] = " › ".join(c.pop("path"))
        c.pop("parent", None)
    return merged


# ---------------- Chuẩn hóa cấu trúc văn bản hành chính ----------------
_P_CHUONG = re.compile(r"^(?:#{1,6}\s+)?\**\s*(Chương|CHƯƠNG)\s+([IVXLC\d]+)\b\.?\s*(.*?)\**\s*$")
_P_MUC = re.compile(r"^(?:#{1,6}\s+)?\**\s*(Mục|MỤC)\s+(\d+)\b\.?\s*(.*?)\**\s*$")
_P_DIEU = re.compile(r"^(?:#{1,6}\s+)?\**\s*(Điều|ĐIỀU)\s+(\d+[a-z]?)\s*[.:]\s*(.*?)\**\s*$")


def normalize_vn_structure(md: str) -> str:
    """Đưa Chương/Mục/Điều về đúng cấp tiêu đề Markdown."""
    md = nfc(md)
    lines = md.split("\n")
    has_muc = any(_P_MUC.match(ln.strip()) for ln in lines)
    out, i = [], 0
    while i < len(lines):
        ln = lines[i].strip()
        m = _P_CHUONG.match(ln)
        if m:
            title = m.group(3).strip(" .*")
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            nxt = lines[j].strip().strip("*# ") if j < len(lines) else ""
            if not title and nxt and nxt.upper() == nxt and len(nxt) < 120 and not _P_DIEU.match(nxt):
                title, i = nxt, j
            out.append(f"## Chương {m.group(2)}" + (f". {title}" if title else ""))
            i += 1
            continue
        m = _P_MUC.match(ln)
        if m and (ln.startswith("#") or ln.startswith("**") or ln.isupper() or m.group(1) == "MỤC"):
            title = m.group(3).strip(" .*")
            out.append(f"### Mục {m.group(2)}" + (f". {title}" if title else ""))
            i += 1
            continue
        m = _P_DIEU.match(ln)
        if m:
            out.append(f"{'####' if has_muc else '###'} Điều {m.group(2)}. {m.group(3).strip(' *')}".rstrip(". "))
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def insert_ids(doc_id: str, md: str) -> str:
    """Chèn mã định danh ổn định cho Chương/Mục/Điều/Khoản (chỉ chèn nơi chưa có)."""
    meta, body, _ = split_frontmatter(md)
    lines = body.split("\n")
    out: list[str] = []
    cur = {"C": None, "M": None, "D": None}
    i = 0

    def has_id_next(k: int) -> bool:
        j = k + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        return j < len(lines) and bool(ID_COMMENT.match(lines[j]))

    while i < len(lines):
        ln = lines[i]
        h = HEADING.match(ln)
        if h:
            txt = unaccent(h.group(2))
            m = re.match(r"Chuong\s+([IVXLC\d]+)", txt, re.I)
            if m:
                cur = {"C": f"C{roman_to_int(m.group(1)) or m.group(1)}", "M": None, "D": None}
                sid = f"{doc_id}.{cur['C']}"
            elif (m := re.match(r"Muc\s+(\d+)", txt, re.I)):
                cur["M"], cur["D"] = f"M{m.group(1)}", None
                sid = f"{doc_id}.{cur['C'] + '.' if cur['C'] else ''}{cur['M']}"
            elif (m := re.match(r"Dieu\s+(\d+[a-z]?)", txt, re.I)):
                cur["D"] = f"D{m.group(1)}"
                sid = f"{doc_id}.{cur['D']}"  # số Điều là duy nhất trong văn bản
            else:
                cur["D"] = None
                sid = None
            out.append(ln)
            if sid and not has_id_next(i):
                out.append(f"<!-- id: {sid} -->")
            i += 1
            continue
        it = ITEM.match(ln)
        if it and cur["D"]:
            j = i + 1
            while j < len(lines) and lines[j].strip() and not ITEM.match(lines[j]) \
                    and not HEADING.match(lines[j]) and not ID_COMMENT.match(lines[j]):
                j += 1
            out.extend(lines[i:j])
            if not (j < len(lines) and ID_COMMENT.match(lines[j])):
                out.append(f"<!-- id: {doc_id}.{cur['D']}.K{it.group(1)} -->")
            i = j
            continue
        out.append(ln)
        i += 1
    body2 = "\n".join(out)
    return dump_frontmatter(meta, body2) if meta else body2


def slugify(text: str) -> str:
    s = unaccent(text).upper()
    s = re.sub(r"[^A-Z0-9]+", "-", s).strip("-")
    return s[:60] or "TL"
