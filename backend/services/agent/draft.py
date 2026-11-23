"""Tác vụ SOẠN VĂN BẢN THAM MƯU (tờ trình, báo cáo đề xuất, kế hoạch, công văn góp ý…) theo mẫu của đơn vị.

    1 can_cu     Thu thập căn cứ        chương trình  kho văn bản chuẩn (nguyên văn) + tài liệu nội bộ + tài liệu người dùng chọn
    2 dan_y      Lập dàn ý              mô hình       mỗi phần của mẫu: các ý chính + căn cứ dự kiến dùng
                 ⏸ CHỜ XÁC NHẬN         người dùng    sửa, duyệt dàn ý trước khi viết (bỏ qua nếu auto_confirm)
    3 viet       Viết từng phần         mô hình       mỗi phần CHỈ dùng căn cứ đã gắn → ngữ cảnh ngắn, ít bịa
    4 kiem_chung Kiểm chứng             chương trình  trích dẫn hợp lệ, câu không có căn cứ được đánh dấu, số liệu có nguồn
    5 hoan_thien Hoàn thiện thể thức    chương trình  ghép phần, khối thể thức, nơi nhận; bản sạch + bản kèm căn cứ

Dự thảo luôn được ghi rõ là bản do AI hỗ trợ soạn; người ký duyệt chịu trách nhiệm nội dung.
"""
import logging
import re
from datetime import date

from aicommon.config import get_settings
from aicommon.internal import ServiceError, SyncSvc
from aicommon.llm import LLMError
from aicommon.resources import domain_context, glossary_hits, prompt
from aicommon.text import estimate_tokens, numbers, truncate_tokens

from services.orchestrator.verifier import verify_a

from . import archive as AR
from . import docs as D
from .criteria import get_draft_template
from .runner import Ctx

log = logging.getLogger("agent.draft")
S = get_settings()
PLAN = [("can_cu", "Thu thập căn cứ"), ("dan_y", "Lập dàn ý, gắn căn cứ cho từng phần"),
        ("viet", "Viết từng phần văn bản"), ("kiem_chung", "Kiểm chứng căn cứ, số liệu"),
        ("hoan_thien", "Hoàn thiện thể thức văn bản")]
OUTLINE_SCHEMA = {"type": "object", "properties": {"phan": {"type": "array", "items": {"type": "object", "properties": {
    "so": {"type": "integer"}, "y": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
    "nguon": {"type": "array", "maxItems": 4, "items": {"type": "string"}}}, "required": ["so", "y", "nguon"]}}},
    "required": ["phan"]}
DRAFT_NOTE = "DỰ THẢO – do trợ lý AI hỗ trợ soạn, cần cán bộ chuyên môn rà soát, hoàn chỉnh trước khi trình ký"


def _sources(ctx: Ctx) -> list[dict]:
    """Căn cứ: Luồng B (nguyên văn quy định) trước, Luồng A, rồi tài liệu người dùng chỉ định. Nhãn S1, S2…"""
    inp = ctx.input
    q = " ".join(x for x in (inp.get("chu_de", ""), inp.get("muc_dich", "")) if x)[:600]
    exact, search = SyncSvc(S.exact_url), SyncSvc(S.search_url)
    out: list[dict] = []
    try:
        hits = exact.call("POST", "/search", ctx.user, json={"query": q, "limit": 4})["results"]
        for hh in hits[:3]:
            sec = exact.call("GET", f"/sections/{hh['section_id']}", ctx.user)
            out.append({"nguon": "B", "title": sec.get("ten") or sec.get("doc_id"), "so_hieu": sec.get("so_hieu"),
                        "breadcrumb": " › ".join(hh.get("path") or []) or sec.get("heading"), "text": sec["text"],
                        "doc_id": sec.get("doc_id"), "section_id": sec.get("section_id")})
    except ServiceError as e:
        ctx.warn(f"Không tra được kho văn bản chuẩn: {e.detail}")
    try:
        for x in search.call("POST", "/search", ctx.user, json={"query": q, "top_k": 5,
                                                                  "filters": {"bo_nhom": [AR.NHOM_DI]}})["results"]:
            if any(o.get("section_id") == x.get("section_id") for o in out):
                continue
            out.append({"nguon": x.get("nguon") or "A", "title": x.get("title"), "so_hieu": x.get("so_hieu"),
                        "breadcrumb": x.get("breadcrumb"), "text": x.get("text", ""), "doc_id": x.get("doc_id"),
                        "section_id": x.get("section_id")})
    except ServiceError as e:
        ctx.warn(f"Không tra được tài liệu nội bộ: {e.detail}")
    # Tiền lệ: văn bản đơn vị đã ban hành cùng chủ đề (tham khảo cách viết, quan điểm – không phải căn cứ pháp lý)
    for x in AR.precedents(ctx.user, q, k=S.agent_precedents):
        if not any(o.get("section_id") == x.get("section_id") for o in out):
            out.append(x)
    for did in inp.get("doc_ids") or []:
        try:
            d = D.load_registered(ctx.user, did, "")
        except ServiceError as e:
            ctx.warn(f"Không đọc được tài liệu {did}: {e.detail}")
            continue
        for _, p in D.rank(q, D.passages(d, 450), k=3):
            out.append({"nguon": "VB", "title": d.title, "so_hieu": d.meta.get("so_hieu"), "breadcrumb": p["breadcrumb"],
                        "text": p["text"], "doc_id": did})
    for u in inp.get("uploads") or []:
        try:
            d = D.load_upload(u["upload_id"], u["filename"], u["path"], "")
        except Exception as e:
            ctx.warn(f"Không đọc được tệp {u.get('filename')}: {e}")
            continue
        for _, p in D.rank(q, D.passages(d, 450), k=3):
            out.append({"nguon": "VB", "title": d.title, "so_hieu": d.meta.get("so_hieu"), "breadcrumb": p["breadcrumb"],
                        "text": p["text"]})
    for i, s in enumerate(out):
        s["label"] = f"S{i + 1}"
        s["text"] = truncate_tokens(s["text"], 900)
    return out


def _fallback_outline(tpl: dict, sources: list[dict]) -> list[dict]:
    """Dàn ý dự phòng (khi mô hình lỗi): gắn căn cứ cho từng phần bằng xếp hạng từ khóa."""
    out = []
    for i, sec in enumerate(tpl["dan_y"]):
        top = D.rank(sec["tieu_de"] + " " + sec["huong_dan"], sources, k=3) if sec["can_cu"] else []
        out.append({"tieu_de": sec["tieu_de"], "huong_dan": sec["huong_dan"], "y": [],
                    "nguon": [s["label"] for _, s in top]})
    return out


def run(ctx: Ctx):
    if ctx.input.get("che_do") == "gop_y":
        # Công văn – hình thức tham gia ý kiến dự thảo: quy trình rà soát dự thảo theo khía cạnh (agent/gopy.py)
        from . import gopy
        return gopy.run(ctx)
    ctx.plan(PLAN)
    inp, st = ctx.input, ctx.state
    tpl = get_draft_template(inp.get("mau"))
    if not tpl:
        raise ValueError(f"Không tìm thấy mẫu văn bản “{inp.get('mau')}” (skills/soan-*).")

    if not ctx.done("can_cu"):
        with ctx.step("can_cu", "Đang tìm căn cứ pháp lý, tài liệu liên quan…") as h:
            src = _sources(ctx)
            nb = sum(1 for s in src if s["nguon"] == "B")
            nd = sum(1 for s in src if s["nguon"] == "VBD")
            h.out(f"{len(src)} căn cứ ({nb} từ văn bản chuẩn" + (f", {nd} văn bản đơn vị đã ban hành" if nd else "") + ")")
            ctx.save_state(sources=src)
    sources = st["sources"]

    if not ctx.done("dan_y"):
        confirmed = ctx.confirmed("dan_y")
        if confirmed:
            ctx._step("dan_y").update(status="xong", detail="Đã được người dùng xác nhận")
            ctx.save_state(outline=confirmed["phan"])
        else:
            with ctx.step("dan_y", "Đang lập dàn ý theo mẫu…") as h:
                sec_list = "\n".join(f"{i + 1}. {s['tieu_de']} – {s['huong_dan']}" for i, s in enumerate(tpl["dan_y"]))
                src_list = "\n".join(f"[{s['label']}] {s['title']} › {s['breadcrumb']}: {truncate_tokens(s['text'], 120)}"
                                     for s in sources)
                outline = _fallback_outline(tpl, sources)
                try:
                    out = ctx.llm_json([{"role": "system", "content": prompt("soan-dan-y") + "\n\n" + tpl["body"]
                                         + ("\n\n" + domain_context() if domain_context() else "")},
                                        {"role": "user", "content": _brief(inp, tpl) + f"\n\nCÁC PHẦN CỦA MẪU:\n{sec_list}"
                                                                    f"\n\nCĂN CỨ:\n{src_list or '(không có)'}"}],
                                       OUTLINE_SCHEMA, task="soan-dan-y", max_tokens=900)
                    labels = {s["label"] for s in sources}
                    for p in out.get("phan", []):
                        k = int(p.get("so", 0)) - 1
                        if 0 <= k < len(outline):
                            outline[k]["y"] = [str(y) for y in p.get("y", [])][:5]
                            ok = [x for x in p.get("nguon", []) if x in labels]
                            if ok:
                                outline[k]["nguon"] = ok
                except LLMError as e:
                    ctx.warn(f"Không lập được dàn ý bằng mô hình ({e}); dùng dàn ý theo mẫu, căn cứ gắn theo từ khóa.")
                h.out(f"{len(outline)} phần")
            if inp.get("auto_confirm"):
                ctx.save_state(outline=outline)
            else:
                ctx.save_state(outline=outline)
                ctx.confirm("dan_y", {"phan": outline}, "Dàn ý đã lập – đề nghị đồng chí rà soát, chỉnh sửa và xác nhận để viết.")
    outline = st["outline"]

    if not ctx.done("viet"):
        with ctx.step("viet") as h:
            by = {s["label"]: s for s in sources}
            written = st.get("written", {})
            sys_p = prompt("chinh-sach") + "\n\n" + prompt("soan-phan") + "\n\n" + tpl["body"]
            if domain_context():
                sys_p += "\n\n" + domain_context()
            terms = glossary_hits(inp.get("chu_de", ""), inp.get("muc_dich", ""))
            if terms:
                sys_p += "\n\nTHUẬT NGỮ:\n" + "\n".join(f"- {t}: {d}" for t, d in terms)
            for i, sec in enumerate(outline):
                if str(i) in written:
                    continue
                h.sub(i + 1, len(outline), f"Đang viết phần {i + 1}/{len(outline)}: {sec['tieu_de']}")
                local, used = [], 0
                for lb in sec.get("nguon", []):
                    s = by.get(lb)
                    if s and used + estimate_tokens(s["text"]) <= S.agent_draft_ctx:
                        local.append(s)
                        used += estimate_tokens(s["text"])
                src_block = "\n\n".join(f"[{j + 1}] " + ("(VĂN BẢN ĐƠN VỊ ĐÃ BAN HÀNH – tham khảo) " if s["nguon"] == "VBD" else "")
                                        + f"{s['title']} › {s['breadcrumb']}"
                                        + (f" ({s['so_hieu']})" if s.get("so_hieu") else "") + f"\n{s['text']}"
                                        for j, s in enumerate(local)) or "(không có căn cứ – chỉ viết khung, để trống số liệu)"
                ys = "\n".join(f"- {y}" for y in sec.get("y", [])) or "(tự xác định theo hướng dẫn)"
                try:
                    text = ctx.llm_text([{"role": "system", "content": sys_p},
                                         {"role": "user", "content": _brief(inp, tpl) + f"\n\nPHẦN CẦN VIẾT: {sec['tieu_de']}\n"
                                                                     f"HƯỚNG DẪN: {sec.get('huong_dan', '')}\nCÁC Ý CHÍNH:\n{ys}"
                                                                     f"\n\nNGUỒN:\n{src_block}\n\nNHẮC LẠI: viết phần “{sec['tieu_de']}”, "
                                                                     "ghi [n] sau mỗi ý lấy từ nguồn."}],
                                        task="soan-phan", max_tokens=900, temperature=0.2)
                except LLMError as e:
                    ctx.warn(f"Phần “{sec['tieu_de']}”: lỗi mô hình ({e}); để trống cho cán bộ bổ sung.")
                    text = "*(Chưa soạn được nội dung phần này – đề nghị bổ sung.)*"
                text = re.sub(r"^#+\s.*\n?", "", text.strip(), flags=re.M).strip()
                rep = None
                if local:
                    text, rep = verify_a(text, local, strict=False)
                # đổi chỉ số trích dẫn cục bộ [n] → nhãn toàn văn bản [S#]
                def _relabel(m, local=local):
                    labs = [local[int(n) - 1]["label"] for n in re.split(r"\s*[,;]\s*", m.group(1))
                            if n.isdigit() and 0 < int(n) <= len(local)]
                    return f"[{', '.join(labs)}]" if labs else ""
                text = re.sub(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]", _relabel, text)
                written[str(i)] = {"text": text, "unsupported": len(rep.unsupported) if rep else 0,
                                   "bad_numbers": rep.bad_numbers if rep else sorted(numbers(text))}
                ctx.save_state(written=written)
            h.out(f"{len(written)} phần")

    with ctx.step("kiem_chung", "Đang kiểm tra căn cứ từng phần…") as h:
        written = st["written"]
        uns = sum(w["unsupported"] for w in written.values())
        bad = sorted({n for w in written.values() for n in w["bad_numbers"]})
        if uns:
            ctx.warn(f"Có {uns} câu chưa tìm thấy căn cứ trong nguồn (đã đánh dấu trong bản kèm căn cứ).")
        if bad:
            ctx.warn("Số liệu chưa đối chiếu được với nguồn: " + ", ".join(bad[:12]))
        h.out("Đạt" if not uns and not bad else f"{uns} câu, {len(bad)} số liệu cần rà soát")

    with ctx.step("hoan_thien", "Đang ghép văn bản theo thể thức…") as h:
        ban_can_cu, ban_sach = compose(inp, tpl, outline, st["written"], sources, ctx.user)
        h.out(f"{len(ban_sach.split())} từ")
    ctx.finish(ban_sach, {"ban_can_cu": ban_can_cu, "ban_sach": ban_sach, "outline": outline,
                          "sources": [{k: v for k, v in s.items() if k != "text"} | {"trich": s["text"][:600]}
                                      for s in sources], "mau": tpl["name"], "ten_loai": tpl["ten_loai"]})


def _brief(inp: dict, tpl: dict) -> str:
    return (f"LOẠI VĂN BẢN: {tpl['ten_loai']}\nCHỦ ĐỀ: {inp.get('chu_de', '')}\nMỤC ĐÍCH: {inp.get('muc_dich', '')}\n"
            f"ĐƠN VỊ SOẠN: {inp.get('don_vi', '')}\nNƠI NHẬN: {inp.get('noi_nhan', '')}\n"
            f"YÊU CẦU THÊM: {inp.get('yeu_cau_them', '') or 'không'}")


def compose(inp: dict, tpl: dict, outline: list[dict], written: dict, sources: list[dict], user) -> tuple[str, str]:
    """Ghép các phần theo thể thức. Trả (bản kèm căn cứ [S#], bản sạch không có chỉ số căn cứ)."""
    today = date.today()
    head = tpl.get("the_thuc") or "**{co_quan_cap_tren}**\n**{don_vi}**\n\nSố: …/{ky_hieu}\n\n" \
                                  "*{dia_danh}, ngày {ngay} tháng {thang} năm {nam}*\n\n# {ten_loai_hoa}\n\n**{trich_yeu}**\n"
    vals = {"co_quan_cap_tren": inp.get("co_quan_cap_tren") or "CƠ QUAN CẤP TRÊN", "don_vi": (inp.get("don_vi") or "ĐƠN VỊ").upper(),
            "ky_hieu": inp.get("ky_hieu") or "…", "dia_danh": inp.get("dia_danh") or "…", "ngay": f"{today.day:02d}",
            "thang": f"{today.month:02d}", "nam": str(today.year), "ten_loai_hoa": tpl["ten_loai"].upper(),
            "trich_yeu": inp.get("trich_yeu") or (tpl.get("trich_yeu_mau") or "Về {chu_de}").format(chu_de=inp.get("chu_de", "")),
            "noi_nhan": inp.get("noi_nhan") or "…", "nguoi_ky": inp.get("nguoi_ky") or "(Chức vụ, họ tên người ký)"}
    try:
        header = head.format(**vals)
    except (KeyError, IndexError, ValueError):
        header = head
    body = []
    for i, sec in enumerate(outline):
        body += [f"## {sec['tieu_de']}", "", written.get(str(i), {}).get("text", "*(chưa có nội dung)*"), ""]
    footer = [f"**Nơi nhận:**\n- {vals['noi_nhan']};\n- Lưu: VT.", "", f"**{vals['nguoi_ky']}**"]
    note = f"> *{DRAFT_NOTE}.*"
    full = "\n".join([note, "", header, "", *body, *footer])
    refs = ["", "---", "## Phụ lục căn cứ (bản làm việc – không đưa vào văn bản ban hành)", ""] + [
        f"- [{s['label']}] {s['title']} › {s['breadcrumb']}" + (f" ({s['so_hieu']})" if s.get("so_hieu") else "")
        + {"B": " – văn bản chuẩn", "VB": " – tài liệu người dùng cung cấp",
           "VBD": " – văn bản đơn vị đã ban hành (tiền lệ, không phải căn cứ pháp lý)"}.get(s["nguon"], " – tài liệu nội bộ")
        for s in sources]
    ban_can_cu = full + "\n".join(refs)
    ban_sach = re.sub(r"\s*\[S\d+(?:\s*,\s*S\d+)*\]", "", full)
    ban_sach = ban_sach.replace(" *(chưa tìm thấy trong nguồn)*", "")
    return ban_can_cu, ban_sach
