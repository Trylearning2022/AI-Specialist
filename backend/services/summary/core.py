"""Lõi tổng hợp báo cáo từ nhiều văn bản – dùng chung cho summary-svc và tác vụ "Tổng hợp báo cáo" của agent-svc.

    Map    : mỗi văn bản (chia phần ≤ MAP_BUDGET token) → ý chính + số liệu (JSON)
    Lọc    : chỉ giữ số liệu THỰC SỰ có trong văn bản; loại ý chính chứa số không có trong văn bản
    Tính   : gộp chỉ tiêu cùng tên + đơn vị tính, cộng tổng BẰNG CHƯƠNG TRÌNH (mô hình không tự tính)
    Reduce : viết báo cáo theo mẫu của kỹ năng, mỗi ý ghi nguồn [S#]
    Kiểm   : số liệu trong báo cáo phải có trong bảng tính/bản tóm tắt; nguồn nào chưa dùng → cảnh báo
"""
import re
from collections import defaultdict
from typing import Callable

from aicommon.config import get_settings
from aicommon.resources import domain_context, prompt, skill_template
from aicommon.text import estimate_tokens, nfc, numbers, unaccent

S = get_settings()
MAP_BUDGET = 5000  # [TINH CHỈNH] token cho mỗi phần văn bản ở bước Map (CPU: 3000–5000)

MAP_SCHEMA = {"type": "object", "properties": {
    "y_chinh": {"type": "array", "items": {"type": "string"}},
    "so_lieu": {"type": "array", "items": {"type": "object", "properties": {
        "chi_tieu": {"type": "string"}, "gia_tri": {"type": "string"}, "don_vi_tinh": {"type": "string"},
        "doi_tuong": {"type": "string"}}, "required": ["chi_tieu", "gia_tri"]}}},
    "required": ["y_chinh", "so_lieu"]}


def _parts(text: str) -> list[str]:
    if estimate_tokens(text) <= MAP_BUDGET:
        return [text]
    paras, out, cur = re.split(r"\n\s*\n", text), [], ""
    for p in paras:
        if cur and estimate_tokens(cur + p) > MAP_BUDGET:
            out.append(cur)
            cur = ""
        cur += p + "\n\n"
    return out + ([cur] if cur.strip() else [])


def _num(v: str) -> float | None:
    v = str(v).strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", v):  # 1.234.567,8 kiểu Việt Nam
        v = v.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d+", v):
        v = v.replace(",", ".")
    else:
        v = v.replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def _fmt(x: float) -> str:
    return f"{int(x):,}".replace(",", ".") if x == int(x) else f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")




def map_doc(d: dict, skill: dict, chat_json: Callable, warnings: list[str], on_part: Callable | None = None):
    """Bước Map cho MỘT văn bản. d = {label, ten, so_hieu, body}. Trả (tóm tắt Markdown, các dòng số liệu)."""
    label, body = d["label"], d["body"]
    y_chinh, so_lieu = [], []
    ps = _parts(body)
    for i, part in enumerate(ps):
        if on_part:
            on_part(i + 1, len(ps))
        out = chat_json(
            [{"role": "system", "content": prompt("tong-hop-map") + f"\n\nKỸ NĂNG:\n{skill['body']}"},
             {"role": "user", "content": f"VĂN BẢN ({d.get('so_hieu', '')} – {d.get('ten', '')}):\n{part}"}],
            schema=MAP_SCHEMA, max_tokens=1200, task="tong-hop-map")
        y_chinh += [str(x) for x in out.get("y_chinh", [])]
        so_lieu += out.get("so_lieu", [])
    have = numbers(body)
    rows = []
    for r in so_lieu:  # chỉ giữ số liệu thực sự có trong văn bản
        val = _num(r.get("gia_tri", ""))
        if val is None:
            continue
        if not (numbers(str(r.get("gia_tri"))) & have):
            warnings.append(f"[{label}] Bỏ số liệu không tìm thấy trong văn bản: {r.get('chi_tieu')} = {r.get('gia_tri')}")
            continue
        rows.append({"nguon": label, "chi_tieu": str(r.get("chi_tieu", "")).strip(), "gia_tri": val,
                     "don_vi_tinh": str(r.get("don_vi_tinh", "")).strip(), "doi_tuong": str(r.get("doi_tuong", "")).strip()})
    bad = [y for y in y_chinh if numbers(y) - have]
    if bad:
        warnings.append(f"[{label}] {len(bad)} ý chính chứa số liệu không có trong văn bản – đã loại.")
    y_chinh = [y for y in y_chinh if y not in bad]
    summary = f"[{label}] {d.get('so_hieu', '')} – {d.get('ten', '')}\n" + "\n".join(f"- {y}" for y in y_chinh)
    return summary, rows


def compute_table(rows: list[dict]) -> tuple[list[dict], str]:
    """Gộp chỉ tiêu cùng tên (so khớp không dấu) và đơn vị tính, cộng tổng bằng chương trình."""
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(unaccent(nfc(r["chi_tieu"])).lower(), r["don_vi_tinh"].lower())].append(r)
    table = []
    for _, items in sorted(groups.items()):
        table.append({"chi_tieu": items[0]["chi_tieu"], "don_vi_tinh": items[0]["don_vi_tinh"],
                      "tong": sum(i["gia_tri"] for i in items), "so_nguon": len({i["nguon"] for i in items}),
                      "chi_tiet": [{"nguon": i["nguon"], "doi_tuong": i["doi_tuong"], "gia_tri": i["gia_tri"]} for i in items]})
    tbl_md = "| Chỉ tiêu | Đơn vị tính | Tổng | Chi tiết (nguồn: giá trị) |\n|---|---|---|---|\n" + "\n".join(
        f"| {t['chi_tieu']} | {t['don_vi_tinh']} | {_fmt(t['tong'])} | "
        + "; ".join(f"{c['nguon']}{' ' + c['doi_tuong'] if c['doi_tuong'] else ''}: {_fmt(c['gia_tri'])}" for c in t["chi_tiet"])
        + " |" for t in table) if table else "(Không có số liệu định lượng)"
    return table, tbl_md


def reduce_report(title: str, params: dict, skill: dict, summaries: list[str], tbl_md: str, chat: Callable) -> str:
    tpl = skill_template(skill) or "# Báo cáo tổng hợp\n\n## Nội dung chính\n\n## Số liệu\n\n## Kiến nghị\n"
    ctx_params = "\n".join(f"- {k}: {v}" for k, v in params.items())
    report = chat(
        [{"role": "system", "content": prompt("tong-hop-reduce") + f"\n\nKỸ NĂNG:\n{skill['body']}\n\nMẪU:\n{tpl}"
                                 + (f"\n\n{domain_context()}" if domain_context() else "")},
         {"role": "user", "content": f"TIÊU ĐỀ: {title}\nTHAM SỐ:\n{ctx_params}\n\nBẢN TÓM TẮT:\n" + "\n\n".join(summaries)
          + f"\n\nBẢNG SỐ LIỆU:\n{tbl_md}"}],
        max_tokens=3000, temperature=0.2, task="tong-hop-reduce")
    return re.sub(r"^```(?:markdown)?\s*|\s*```$", "", report.strip())


def check_report(report: str, title: str, params: dict, summaries: list[str], tbl_md: str, sources: list[dict],
                 warnings: list[str]) -> str:
    """Kiểm chứng và gắn phụ lục (bảng số liệu do chương trình tính, danh mục nguồn)."""
    ctx_params = "\n".join(f"- {k}: {v}" for k, v in params.items())
    allowed = numbers(tbl_md) | numbers("\n".join(summaries)) | numbers(title + " " + ctx_params)
    stray = sorted(n for n in numbers(re.sub(r"\[S\d+\]", "", re.sub(r"(?m)^\s*#*\s*\d+(\.\d+)*\.?\s", " ", report)))
                   if n not in allowed)
    if stray:
        warnings.append("Số liệu trong báo cáo không có trong nguồn hoặc bảng tính (cần kiểm tra): " + ", ".join(stray[:15]))
    cited = set(re.findall(r"\[(S\d+)\]", report))
    missing = [s["label"] for s in sources if s["label"] not in cited]
    if missing:
        warnings.append("Các nguồn chưa được sử dụng trong báo cáo: " + ", ".join(missing))
    appendix = "\n\n---\n\n## Phụ lục 1. Bảng số liệu tổng hợp (do chương trình tính)\n\n" + tbl_md + \
               "\n\n## Phụ lục 2. Nguồn\n\n" + "\n".join(
                   f"- [{s['label']}] {s.get('so_hieu', '')} – {s.get('ten', '')} ({s.get('ma', s.get('doc_id', ''))})"
                   for s in sources)
    return report + appendix
