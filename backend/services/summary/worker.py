"""Tác vụ tổng hợp theo kỹ năng: Map (tóm tắt từng văn bản, trích số liệu) → tính toán bằng mã
→ Reduce (viết báo cáo theo mẫu) → Verifier (kiểm số liệu, nguồn)."""
import logging
import re
from collections import defaultdict

from aicommon.config import get_settings
from aicommon.db import init_db, session
from aicommon.internal import SyncSvc
from aicommon.llm import LLMError, SyncLLM
from aicommon.markdown import split_frontmatter
from aicommon.queue import celery_app
from aicommon.resources import get_skill, prompt, skill_template
from aicommon.security import UserCtx
from aicommon.text import estimate_tokens, nfc, numbers, unaccent

from .models import SummaryJob

log = logging.getLogger("summary.worker")
S = get_settings()
MAP_BUDGET = 5000  # token cho mỗi phần văn bản ở bước Map

MAP_SCHEMA = {"type": "object", "properties": {
    "y_chinh": {"type": "array", "items": {"type": "string"}},
    "so_lieu": {"type": "array", "items": {"type": "object", "properties": {
        "chi_tieu": {"type": "string"}, "gia_tri": {"type": "string"}, "don_vi_tinh": {"type": "string"},
        "doi_tuong": {"type": "string"}}, "required": ["chi_tieu", "gia_tri"]}}},
    "required": ["y_chinh", "so_lieu"]}


def _set(jid: str, **kw):
    with session() as s:
        j = s.get(SummaryJob, jid)
        for k, v in kw.items():
            setattr(j, k, v)


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


def run(jid: str):
    init_db()
    with session() as s:
        j = s.get(SummaryJob, jid)
        user, doc_ids, skill_name, params, title = UserCtx(**j.owner), list(j.doc_ids), j.skill, dict(j.params), j.title
    _set(jid, status="dang_chay", progress="Bắt đầu", error="")
    skill = get_skill(skill_name)
    if not skill:
        _set(jid, status="loi", error=f"Không tìm thấy kỹ năng {skill_name}")
        return
    ingest = SyncSvc(S.ingest_url)
    llm = SyncLLM()
    warnings: list[str] = []
    summaries, rows, sources = [], [], []
    try:
        for k, did in enumerate(doc_ids, 1):
            _set(jid, progress=f"Đang tóm tắt văn bản {k}/{len(doc_ids)}")
            md = ingest.call("GET", f"/documents/{did}/markdown", user)
            meta, body, _ = split_frontmatter(md)
            label = f"S{k}"
            sources.append({"label": label, "doc_id": did, "ten": meta.get("ten", did), "so_hieu": meta.get("so_hieu", ""),
                            "don_vi": meta.get("co_quan_ban_hanh") or meta.get("don_vi_quan_ly", "")})
            y_chinh, so_lieu = [], []
            for part in _parts(body):
                out = llm.chat_json(
                    [{"role": "system", "content": prompt("tong-hop-map") + f"\n\nKỸ NĂNG:\n{skill['body']}"},
                     {"role": "user", "content": f"VĂN BẢN ({meta.get('so_hieu', '')} – {meta.get('ten', did)}):\n{part}"}],
                    schema=MAP_SCHEMA, model=S.model_main, max_tokens=1200, task="tong-hop-map")
                y_chinh += [str(x) for x in out.get("y_chinh", [])]
                so_lieu += out.get("so_lieu", [])
            have = numbers(body)
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
            summaries.append(f"[{label}] {meta.get('so_hieu', '')} – {meta.get('ten', did)}\n" + "\n".join(f"- {y}" for y in y_chinh))

        # ---- Tính toán bằng mã chương trình (không để mô hình tự tính) ----
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

        _set(jid, progress="Đang lập báo cáo tổng hợp")
        tpl = skill_template(skill) or "# Báo cáo tổng hợp\n\n## Nội dung chính\n\n## Số liệu\n\n## Kiến nghị\n"
        ctx_params = "\n".join(f"- {k}: {v}" for k, v in params.items())
        report = llm.chat(
            [{"role": "system", "content": prompt("tong-hop-reduce") + f"\n\nKỸ NĂNG:\n{skill['body']}\n\nMẪU:\n{tpl}"},
             {"role": "user", "content": f"TIÊU ĐỀ: {title}\nTHAM SỐ:\n{ctx_params}\n\nBẢN TÓM TẮT:\n" + "\n\n".join(summaries)
              + f"\n\nBẢNG SỐ LIỆU:\n{tbl_md}"}],
            model=S.model_main, max_tokens=3000, temperature=0.2, task="tong-hop-reduce")
        report = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", report.strip())

        # ---- Verifier: số liệu trong báo cáo phải có trong bảng tính hoặc bản tóm tắt ----
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
                       f"- [{s['label']}] {s['so_hieu']} – {s['ten']} (mã: {s['doc_id']})" for s in sources)
        _set(jid, status="xong", progress="Hoàn thành", result=report + appendix, table=table, sources=sources,
             warnings=warnings)
    except (LLMError, Exception) as e:  # noqa: B014
        log.exception("Lỗi tổng hợp %s", jid)
        _set(jid, status="loi", error=str(e)[:2000], warnings=warnings)


@celery_app.task(name="summary.run")
def run_task(jid: str):
    run(jid)
