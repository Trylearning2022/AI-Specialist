"""Tác vụ TỔNG HỢP BÁO CÁO CHUNG từ nhiều báo cáo riêng lẻ (tài liệu trong kho và/hoặc tệp tải lên).

    1 doc_vao    Đọc các báo cáo          chương trình  (tệp tải lên: chuyển đổi; tài liệu trong kho: kiểm quyền)
    2 map        Tóm tắt, trích số liệu    mô hình       (từng báo cáo; số liệu không có trong văn bản bị loại)
    3 tinh       Tính bảng số liệu         chương trình  (cộng tổng theo chỉ tiêu – mô hình KHÔNG tự tính)
    4 reduce     Viết báo cáo theo mẫu     mô hình       (kỹ năng loai: tong_hop trong skills/)
    5 kiem_chung Kiểm chứng, phụ lục       chương trình  (số liệu có nguồn; nguồn chưa dùng; bảng số liệu, danh mục nguồn)

Thuật toán dùng chung với summary-svc: services/summary/core.py.
"""
from aicommon.resources import get_skill

from services.summary.core import check_report, compute_table, map_doc, reduce_report

from . import docs as D
from .runner import Ctx

PLAN = [("doc_vao", "Đọc các báo cáo đầu vào"), ("map", "Tóm tắt, trích số liệu từng báo cáo"),
        ("tinh", "Tính bảng số liệu tổng hợp"), ("reduce", "Viết báo cáo tổng hợp theo mẫu"),
        ("kiem_chung", "Kiểm chứng số liệu, nguồn; lập phụ lục")]


def run(ctx: Ctx):
    ctx.plan(PLAN)
    inp, st = ctx.input, ctx.state
    skill = get_skill(inp.get("skill") or "")
    if not skill:
        raise ValueError(f"Không tìm thấy mẫu báo cáo (kỹ năng) “{inp.get('skill')}”.")
    title, params = ctx.title, dict(inp.get("params") or {})

    if not ctx.done("doc_vao"):
        with ctx.step("doc_vao") as h:
            items = [("doc", d) for d in inp.get("doc_ids") or []] + [("up", u) for u in inp.get("uploads") or []]
            if not items:
                raise ValueError("Chưa chọn báo cáo đầu vào.")
            docs = []
            for k, (typ, x) in enumerate(items, 1):
                h.sub(k, len(items), f"Đang đọc báo cáo {k}/{len(items)}")
                d = D.load_registered(ctx.user, x, f"S{k}") if typ == "doc" else \
                    D.load_upload(x["upload_id"], x["filename"], x["path"], f"S{k}")
                for w in d.warnings:
                    ctx.warn(f"[S{k}] {w}")
                docs.append({"label": f"S{k}", "ten": d.title, "so_hieu": d.meta.get("so_hieu", ""),
                             "ma": x if typ == "doc" else x["filename"], "doc_id": x if typ == "doc" else "",
                             "don_vi": d.meta.get("co_quan_ban_hanh") or d.meta.get("don_vi_quan_ly", ""), "body": d.markdown})
            h.out(f"{len(docs)} báo cáo")
            ctx.save_state(docs=docs)
    docs = st["docs"]

    if not ctx.done("map"):
        with ctx.step("map") as h:
            sums, rows, warns = st.get("summaries", {}), st.get("rows", {}), []
            for k, d in enumerate(docs):
                if d["label"] in sums:
                    continue
                h.sub(k + 1, len(docs), f"Đang đọc {d['label']}: {d['ten'][:100]}")
                sm, rr = map_doc(d, skill, lambda m, **kw: ctx.llm_json(m, kw.pop("schema"), **kw), warns,
                                 on_part=lambda i, n, d=d, k=k: h.sub(k + 1, len(docs), f"{d['label']}: phần {i}/{n}"))
                sums[d["label"]], rows[d["label"]] = sm, rr
                ctx.save_state(summaries=sums, rows=rows)
            for w in warns:
                ctx.warn(w)
            h.out(f"{sum(len(r) for r in rows.values())} số liệu hợp lệ")

    summaries = [st["summaries"][d["label"]] for d in docs]
    rows = [r for d in docs for r in st["rows"][d["label"]]]
    with ctx.step("tinh", "Đang cộng tổng theo chỉ tiêu…") as h:
        table, tbl_md = compute_table(rows)
        h.out(f"{len(table)} chỉ tiêu")

    if not ctx.done("reduce"):
        with ctx.step("reduce", "Đang viết báo cáo tổng hợp…") as h:
            report = reduce_report(title, params, skill, summaries, tbl_md,
                                   lambda m, **kw: ctx.llm_text(m, kw.pop("task"), kw.pop("max_tokens", 3000),
                                                                kw.pop("temperature", 0.2)))
            ctx.save_state(report=report)
            h.out(f"{len(report.split())} từ")

    with ctx.step("kiem_chung", "Đang kiểm chứng số liệu, nguồn…") as h:
        warns: list[str] = []
        sources = [{k: v for k, v in d.items() if k != "body"} for d in docs]
        result = check_report(st["report"], title, params, summaries, tbl_md, sources, warns)
        for w in warns:
            ctx.warn(w)
        h.out("Đạt" if not warns else f"{len(warns)} cảnh báo")
    ctx.finish(result, {"table": table, "sources": sources, "skill": skill["name"]})
