"""Tác vụ PHÂN TÍCH VĂN BẢN MỚI: tóm tắt và chỉ ra các vấn đề liên quan đến ngành, có căn cứ.

Kế hoạch (cố định, chạy nền, hiển thị tiến trình từng bước):

    1 tiep_nhan   Tiếp nhận, chuyển đổi       chương trình  (MarkItDown / OCR docling; kiểm tra dấu độ mật)
    2 cau_truc    Cấu trúc, trích xuất         chương trình  (chia phần; thời hạn, nhiệm vụ, văn bản viện dẫn)
    3 tom_tat     Tóm tắt từng phần, toàn văn  mô hình       (map từng phần → reduce; loại ý có số liệu lạ)
    4 doi_chieu   Đối chiếu cơ sở tri thức      chương trình  (kho văn bản chuẩn: viện dẫn, hiệu lực; tài liệu liên quan)
    5 tieu_chi    Áp bộ tiêu chí ngành          mô hình       (mỗi tiêu chí: tìm đoạn liên quan → nhận định có trích dẫn;
                                                               không có đoạn liên quan → "không đề cập", không gọi mô hình)
    6 bao_cao     Lập báo cáo theo mẫu          chương trình  (khung báo cáo cố định, không để mô hình tự dàn trang)
    7 kiem_chung  Kiểm chứng                   chương trình  (trích dẫn có thật trong văn bản; số liệu có nguồn)

Điểm tinh chỉnh: AGENT_PART_TOKENS, AGENT_MAX_CRITERIA (aicommon/config.py); bộ tiêu chí trong skills/phan-tich-*;
chỉ thị prompts/phan-tich-*.md.
"""
import logging
import re

from aicommon.config import get_settings
from aicommon.guard import stamp_level
from aicommon.internal import ServiceError, SyncSvc
from aicommon.llm import LLMError
from aicommon.resources import domain_context, expired_laws, glossary_hits, prompt
from aicommon.security import DO_MAT
from aicommon.text import nfc, numbers, truncate_tokens

from . import docs as D
from .criteria import get_criteria_set
from .runner import Ctx

log = logging.getLogger("agent.analyze")
S = get_settings()
MUC_DO = {"cao": "Cao", "trung_binh": "Trung bình", "thap": "Thấp"}
# [TINH CHỈNH] Lọc tiêu chí trước khi gọi mô hình (tiết kiệm thời gian trên CPU):
#   - tiêu chí có tu_khoa: văn bản phải chứa ≥ 2 từ khóa khác nhau, hoặc 1 cụm từ khóa nhiều âm tiết ("chứng thư số");
#     so khớp CÓ DẤU, trọn từ (âm tiết đơn không dấu như "mat" trùng quá nhiều từ khác nghĩa);
#   - tiêu chí không có tu_khoa: điểm BM25 của đoạn liên quan nhất ≥ MIN_RELEVANCE.
# Không đạt → "không đề cập", không gọi mô hình. Nới lỏng nếu báo cáo bỏ sót vấn đề; siết lại nếu nhận định gượng ép.
MIN_RELEVANCE = 6.0
MIN_KEYWORD_HITS = 2


def keyword_hits(keywords: list[str], text_lower: str) -> list[str]:
    return [k for k in keywords if re.search(r"(?<![\wÀ-ỹđ])" + re.escape(nfc(k).lower()) + r"(?![\wÀ-ỹđ])", text_lower)]


def relevant(c: dict, doc_lower: str, top: list) -> bool:
    if c["id"] == "yc":
        return True  # câu hỏi riêng của người dùng: luôn trả lời
    if c["tu_khoa"]:
        hits = keyword_hits(c["tu_khoa"], doc_lower)
        return len(hits) >= MIN_KEYWORD_HITS or any(" " in h.strip() for h in hits)
    return bool(top) and top[0][0] >= MIN_RELEVANCE

PLAN = [("tiep_nhan", "Tiếp nhận, chuyển đổi văn bản"), ("cau_truc", "Phân tích cấu trúc, trích xuất thời hạn, nhiệm vụ"),
        ("tom_tat", "Tóm tắt từng phần và toàn văn"), ("doi_chieu", "Đối chiếu cơ sở tri thức của đơn vị"),
        ("tieu_chi", "Áp bộ tiêu chí phân tích của ngành"), ("bao_cao", "Lập báo cáo phân tích"),
        ("kiem_chung", "Kiểm chứng trích dẫn, số liệu")]

PART_SCHEMA = {"type": "object", "properties": {
    "y_chinh": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
    "yeu_cau": {"type": "array", "maxItems": 5, "items": {"type": "string"}}}, "required": ["y_chinh", "yeu_cau"]}
SUM_SCHEMA = {"type": "object", "properties": {
    "tom_tat": {"type": "string"}, "noi_dung_chinh": {"type": "array", "maxItems": 8, "items": {"type": "string"}}},
    "required": ["tom_tat", "noi_dung_chinh"]}
CRIT_SCHEMA = {"type": "object", "properties": {
    "de_cap": {"type": "boolean"}, "nhan_dinh": {"type": "string"},
    "trich_dan": {"type": "array", "maxItems": 2, "items": {"type": "string"}},
    "muc_do": {"type": "string", "enum": ["cao", "trung_binh", "thap"]}, "de_xuat": {"type": "string"}},
    "required": ["de_cap", "nhan_dinh", "trich_dan", "muc_do", "de_xuat"]}


def _clean_numbers(items: list[str], allowed: str, ctx: Ctx, where: str) -> list[str]:
    """Loại ý có số liệu không có trong văn bản (chống bịa số)."""
    have = numbers(allowed)
    keep = [x for x in items if not (numbers(x) - have)]
    if len(keep) < len(items):
        ctx.warn(f"{where}: đã loại {len(items) - len(keep)} ý có số liệu không tìm thấy trong văn bản.")
    return keep


def run(ctx: Ctx):
    ctx.plan(PLAN)
    inp = ctx.input
    st = ctx.state

    # ---------------------------------------------------------------- 1. Tiếp nhận
    if not ctx.done("tiep_nhan"):
        with ctx.step("tiep_nhan", "Đang chuyển đổi văn bản sang dạng có cấu trúc…") as h:
            if inp.get("upload_id"):
                doc = D.load_upload(inp["upload_id"], inp["filename"], inp["path"])
            elif inp.get("doc_id"):
                doc = D.load_registered(ctx.user, inp["doc_id"], "VB")
            else:
                doc = D.Doc("VB", inp.get("ten") or "Văn bản dán trực tiếp", inp.get("text", ""), {})
            if len(doc.markdown.strip()) < 80:
                raise ValueError("Văn bản quá ngắn hoặc không đọc được nội dung để phân tích.")
            lv = stamp_level(doc.markdown[:4000])
            if lv > S.system_max_clearance or lv > ctx.user.clearance:
                raise PermissionError(f"Văn bản mang dấu độ mật “{DO_MAT.get(lv, lv)}” vượt cấp độ được phép xử lý.")
            for w in doc.warnings:
                ctx.warn(w)
            stats = D.doc_stats(doc)
            h.out(f"{stats['so_trang_uoc_tinh']} trang (ước tính) · {stats['token']:,} token".replace(",", "."))
            ctx.save_state(doc={"title": doc.title, "markdown": doc.markdown, "meta": doc.meta}, stats=stats)
    doc = D.Doc("VB", st["doc"]["title"], st["doc"]["markdown"], st["doc"]["meta"])

    # ---------------------------------------------------------------- 2. Cấu trúc, trích xuất (chương trình)
    if not ctx.done("cau_truc"):
        with ctx.step("cau_truc", "Đang chia phần theo cấu trúc văn bản…") as h:
            ps = D.parts(doc)
            dl, asg, refs = D.deadlines(doc), D.assignments(doc), D.references(doc)
            h.out(f"{len(ps)} phần · {len(dl)} mốc thời hạn · {len(asg)} nhiệm vụ · {len(refs)} văn bản viện dẫn")
            ctx.save_state(parts=ps, deadlines=dl, assignments=asg, refs=refs)

    # ---------------------------------------------------------------- 3. Tóm tắt (mô hình)
    if not ctx.done("tom_tat"):
        with ctx.step("tom_tat") as h:
            notes = []
            ps = st["parts"]
            for i, p in enumerate(ps):
                h.sub(i + 1, len(ps), f"Đang đọc phần {i + 1}/{len(ps)}: {p['breadcrumb'][:120]}")
                try:
                    out = ctx.llm_json([{"role": "system", "content": prompt("phan-tich-phan")},
                                        {"role": "user", "content": f"VĂN BẢN: {doc.title}\nVỊ TRÍ: {p['breadcrumb']}\n"
                                                                    f"NỘI DUNG:\n{p['text']}"}],
                                       PART_SCHEMA, task="phan-tich-phan", max_tokens=600)
                except LLMError as e:
                    ctx.warn(f"Không tóm tắt được phần {i + 1} ({e}); phần này chỉ được trích xuất bằng chương trình.")
                    continue
                y = _clean_numbers([str(x) for x in out.get("y_chinh", [])], p["text"], ctx, f"Phần {i + 1}")
                r = _clean_numbers([str(x) for x in out.get("yeu_cau", [])], p["text"], ctx, f"Phần {i + 1}")
                notes.append({"no": p["no"], "breadcrumb": p["breadcrumb"], "y_chinh": y, "yeu_cau": r})
            h.sub(len(ps), len(ps), "Đang tổng hợp tóm tắt toàn văn…")
            joined = "\n".join(f"[Phần {n['no']} – {n['breadcrumb']}]\n" + "\n".join(f"- {y}" for y in n["y_chinh"] + n["yeu_cau"])
                               for n in notes)
            summary = {"tom_tat": "", "noi_dung_chinh": []}
            if notes:
                try:
                    summary = ctx.llm_json([{"role": "system", "content": prompt("phan-tich-tong")},
                                            {"role": "user", "content": f"VĂN BẢN: {doc.title}\n\nGHI CHÉP TỪNG PHẦN:\n{joined}"}],
                                           SUM_SCHEMA, task="phan-tich-tong", max_tokens=900)
                except LLMError as e:
                    ctx.warn(f"Không tổng hợp được tóm tắt toàn văn ({e}); dùng ghi chép từng phần.")
                    summary = {"tom_tat": "", "noi_dung_chinh": [y for n in notes for y in n["y_chinh"]][:8]}
            summary["noi_dung_chinh"] = _clean_numbers([str(x) for x in summary.get("noi_dung_chinh", [])],
                                                       doc.markdown, ctx, "Tóm tắt")
            if numbers(summary.get("tom_tat", "")) - numbers(doc.markdown):
                ctx.warn("Đoạn tóm tắt có số liệu không có trong văn bản – đã thay bằng danh sách nội dung chính.")
                summary["tom_tat"] = ""
            h.out(f"{len(summary['noi_dung_chinh'])} nội dung chính")
            ctx.save_state(notes=notes, summary=summary)

    # ---------------------------------------------------------------- 4. Đối chiếu cơ sở tri thức (chương trình)
    if not ctx.done("doi_chieu"):
        with ctx.step("doi_chieu", "Đang tra kho văn bản chuẩn và tài liệu nội bộ…") as h:
            exact, search = SyncSvc(S.exact_url), SyncSvc(S.search_url)
            refs_out, related = [], []
            try:
                catalog = {re.sub(r"\s+", "", d.get("so_hieu", "")).lower(): d
                           for d in exact.call("GET", "/catalog", ctx.user)["docs"] if d.get("so_hieu")}
            except ServiceError as e:
                catalog = {}
                ctx.warn(f"Không tra được kho văn bản chuẩn: {e.detail}")
            for r in st.get("refs", []):
                d = catalog.get(re.sub(r"\s+", "", r).lower())
                refs_out.append({"so_hieu": r, "co_trong_kho": bool(d), "doc_id": d and d.get("doc_id"),
                                 "ten": d and d.get("ten"), "trang_thai": d and d.get("trang_thai"),
                                 "thay_the_boi": d and d.get("thay_the_boi")})
            q = " ".join([doc.title, *st["summary"].get("noi_dung_chinh", [])[:3]])[:600]
            try:
                hits = search.call("POST", "/search", ctx.user, json={"query": q, "top_k": 6})["results"]
                for x in hits:
                    related.append({"doc_id": x["doc_id"], "title": x.get("title"), "so_hieu": x.get("so_hieu"),
                                    "breadcrumb": x.get("breadcrumb"), "nguon": x.get("nguon"),
                                    "trang_thai": x.get("trang_thai"), "text": x.get("text", "")[:1500]})
            except ServiceError as e:
                ctx.warn(f"Không tra được tài liệu nội bộ: {e.detail}")
            expired = expired_refs(doc.markdown, st.get("refs", []))
            for r in refs_out:
                r["het_hieu_luc"] = expired.pop(_norm_so(r["so_hieu"]), None)
            for x in expired.values():  # nhận diện theo tên (không ghi số hiệu)
                refs_out.append({"so_hieu": x["ten"], "co_trong_kho": False, "doc_id": None, "ten": x["ten"],
                                 "trang_thai": None, "thay_the_boi": None, "het_hieu_luc": x})
            n_exp = sum(1 for r in refs_out if r.get("het_hieu_luc"))
            if n_exp:
                ctx.warn(f"Văn bản viện dẫn {n_exp} căn cứ đã hết hiệu lực – xem mục IV, V của báo cáo.")
            have = sum(1 for r in refs_out if r["co_trong_kho"])
            h.out(f"{have}/{len(refs_out)} văn bản viện dẫn có trong kho · {n_exp} căn cứ hết hiệu lực · "
                  f"{len(related)} tài liệu liên quan")
            ctx.save_state(refs_out=refs_out, related=related)

    # ---------------------------------------------------------------- 5. Áp bộ tiêu chí ngành (mô hình)
    if not ctx.done("tieu_chi"):
        with ctx.step("tieu_chi") as h:
            cs = get_criteria_set(inp.get("bo_tieu_chi"))
            items = list(cs["items"]) if cs else []
            if inp.get("yeu_cau"):  # câu hỏi riêng của người dùng là tiêu chí đầu tiên
                items.insert(0, {"id": "yc", "nhom": "Yêu cầu của người dùng", "hoi": inp["yeu_cau"], "tu_khoa": [],
                                 "muc_do": "trung_binh", "can_cu": ""})
            items = items[:S.agent_max_criteria]
            pas = D.passages(doc)
            doc_lower = nfc(doc.markdown).lower()
            sys_p = prompt("phan-tich-tieu-chi") + (f"\n\nHƯỚNG DẪN CỦA BỘ TIÊU CHÍ:\n{cs['body']}" if cs else "")
            dctx = domain_context()
            if dctx:
                sys_p += "\n\n" + dctx
            terms = glossary_hits(doc.markdown[:6000])
            if terms:
                sys_p += "\n\nTHUẬT NGỮ:\n" + "\n".join(f"- {t}: {d}" for t, d in terms)
            results = []
            for i, c in enumerate(items):
                h.sub(i + 1, len(items), f"Tiêu chí {i + 1}/{len(items)}: {c['hoi'][:140]}")
                q = c["hoi"] + " " + " ".join(c["tu_khoa"])
                top = D.rank(q, pas, k=3)
                if not top or not relevant(c, doc_lower, top):
                    results.append({**c, "de_cap": False, "nhan_dinh": "Văn bản không đề cập.", "trich_dan": [],
                                    "vi_tri": [], "muc_do_kq": "thap", "de_xuat": "", "goi_mo_hinh": False})
                    continue
                kb = [x for _, x in D.rank(q, st.get("related", []), k=2)]
                src = "\n\n".join(f"[D{j + 1}] ({p['breadcrumb']})\n{truncate_tokens(p['text'], 450)}"
                                  for j, (_, p) in enumerate(top))
                kbs = "\n\n".join(f"[K{j + 1}] {x.get('title')} › {x.get('breadcrumb')} ({x.get('so_hieu') or 'tài liệu nội bộ'})\n"
                                  f"{truncate_tokens(x['text'], 300)}" for j, x in enumerate(kb))
                try:
                    out = ctx.llm_json([{"role": "system", "content": sys_p},
                                        {"role": "user", "content": f"TIÊU CHÍ: {c['hoi']}"
                                                                    + (f"\nCĂN CỨ ĐỐI CHIẾU: {c['can_cu']}" if c.get("can_cu") else "")
                                                                    + f"\n\nĐOẠN VĂN BẢN CẦN PHÂN TÍCH:\n{src}"
                                                                    + (f"\n\nCƠ SỞ TRI THỨC CỦA ĐƠN VỊ:\n{kbs}" if kbs else "")
                                                                    + f"\n\nNHẮC LẠI TIÊU CHÍ: {c['hoi']}"}],
                                       CRIT_SCHEMA, task="phan-tich-tieu-chi", max_tokens=600)
                except LLMError as e:
                    ctx.warn(f"Tiêu chí “{c['hoi'][:60]}”: lỗi mô hình ({e}).")
                    continue
                allowed = " ".join(p["text"] for _, p in top) + " " + " ".join(x["text"] for x in kb)
                quotes = [qt for qt in out.get("trich_dan", []) if D.quote_ok(qt, doc.markdown)]
                if len(quotes) < len(out.get("trich_dan", [])):
                    ctx.warn(f"Tiêu chí “{c['hoi'][:60]}”: đã loại trích dẫn không có trong văn bản.")
                nd = str(out.get("nhan_dinh", "")).strip()
                if numbers(nd) - numbers(allowed):
                    ctx.warn(f"Tiêu chí “{c['hoi'][:60]}”: nhận định có số liệu không có trong văn bản – cần kiểm tra.")
                    nd += " *(số liệu cần đối chiếu)*"
                de_cap = bool(out.get("de_cap")) and bool(nd)
                if de_cap and not quotes:  # nhận định không có trích dẫn hợp lệ → hạ mức tin cậy
                    nd += " *(chưa xác định được đoạn trích dẫn – cần đối chiếu văn bản)*"
                results.append({**c, "de_cap": de_cap, "nhan_dinh": nd if de_cap else "Văn bản không đề cập.",
                                "trich_dan": quotes, "vi_tri": [p["breadcrumb"] for _, p in top[:2]] if de_cap else [],
                                "muc_do_kq": out.get("muc_do", "trung_binh") if de_cap else "thap",
                                "de_xuat": str(out.get("de_xuat", "")).strip() if de_cap else "",
                                "kb": [{"title": x.get("title"), "so_hieu": x.get("so_hieu"), "breadcrumb": x.get("breadcrumb")}
                                       for x in kb] if de_cap else [], "goi_mo_hinh": True})
            n_yes = sum(1 for r in results if r["de_cap"])
            n_llm = sum(1 for r in results if r.get("goi_mo_hinh"))
            h.out(f"{n_yes}/{len(results)} tiêu chí có nội dung liên quan · {n_llm} lượt gọi mô hình")
            ctx.save_state(criteria={"name": cs["name"] if cs else "", "description": cs["description"] if cs else ""},
                           results=results)

    # ---------------------------------------------------------------- 6. Lập báo cáo (chương trình)
    with ctx.step("bao_cao", "Đang lập báo cáo theo mẫu…") as h:
        md = build_report(doc, st, ctx.user.name or ctx.user.username)
        h.out(f"{len(md.splitlines())} dòng")

    # ---------------------------------------------------------------- 7. Kiểm chứng
    with ctx.step("kiem_chung", "Đang đối chiếu số liệu trong báo cáo với văn bản…") as h:
        allowed = doc.markdown + " ".join(x["text"] for x in st.get("related", [])) + str(st.get("stats", {}))
        stray = sorted(numbers(re.sub(r"(?m)^\s*(#+\s*)?[IVX\d]+[.)]\s", " ", md)) - numbers(allowed)
                       - {str(i) for i in range(0, 32)})
        if stray:
            ctx.warn("Báo cáo có số liệu không tìm thấy trong văn bản, cần đối chiếu: " + ", ".join(stray[:12]))
        h.out("Đạt" if not stray else f"{len(stray)} số liệu cần đối chiếu")
    ctx.finish(md, {"summary": st.get("summary"), "results": st.get("results"), "deadlines": st.get("deadlines"),
                    "assignments": st.get("assignments"), "refs": st.get("refs_out"), "related": [
                        {k: v for k, v in r.items() if k != "text"} for r in st.get("related", [])],
                    "stats": st.get("stats"), "meta": doc.meta, "criteria": st.get("criteria")})


def _norm_so(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).upper().replace("Đ", "D")


def expired_refs(text: str, refs: list[str]) -> dict[str, dict]:
    """Căn cứ đã hết hiệu lực mà văn bản còn viện dẫn – CHƯƠNG TRÌNH đối chiếu, không dùng mô hình.

    Danh mục lấy từ kỹ năng ngành (skills/nganh-*/SKILL.md, khóa van_ban_het_hieu_luc), cán bộ tự bổ sung.
    Khớp theo số hiệu (refs đã trích bằng biểu thức chính quy) hoặc theo `ten_nhan_dien` nếu văn bản chỉ ghi tên.
    Mục có `chi_khi_kem` chỉ báo khi văn bản cùng viện dẫn số hiệu đó (ví dụ luật sửa đổi nhiều luật).
    Trả {số hiệu chuẩn hóa hoặc "ten:<tên>": mục danh mục}."""
    have = {_norm_so(r) for r in refs}
    low = nfc(text).lower()
    out = {}
    for x in expired_laws():
        k = _norm_so(x["so_hieu"])
        if x.get("chi_khi_kem") and _norm_so(x["chi_khi_kem"]) not in have:
            continue
        if k in have:
            out[k] = x
        elif x.get("ten_nhan_dien") and nfc(x["ten_nhan_dien"]).lower() in low:
            out["ten:" + x["ten_nhan_dien"]] = {**x, "ten": x["ten_nhan_dien"]}
    return out


def _esc(s: str) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def build_report(doc: D.Doc, st: dict, author: str) -> str:
    """Khung báo cáo phân tích do CHƯƠNG TRÌNH dựng (nội dung từng ô lấy từ các bước trước)."""
    m, sm, res = doc.meta, st.get("summary", {}), st.get("results", [])
    loai = {"quyet_dinh": "Quyết định", "ke_hoach": "Kế hoạch", "cong_van": "Công văn", "huong_dan": "Hướng dẫn",
            "bao_cao": "Báo cáo", "thong_tu": "Thông tư", "nghi_dinh": "Nghị định", "to_trinh": "Tờ trình",
            "quy_dinh": "Quy định", "luat": "Luật", "phap_lenh": "Pháp lệnh"}.get(m.get("loai", ""), "Văn bản")
    L = [f"# Báo cáo phân tích văn bản: {doc.title}", "",
         "| Thông tin | Nội dung |", "|---|---|",
         f"| Loại văn bản | {loai} |", f"| Số, ký hiệu | {_esc(m.get('so_hieu') or 'Không xác định')} |",
         f"| Ngày ban hành | {_esc(m.get('ngay_ban_hanh') or 'Không xác định')} |",
         f"| Độ dài | khoảng {st.get('stats', {}).get('so_trang_uoc_tinh', '?')} trang |",
         f"| Bộ tiêu chí áp dụng | {_esc(st.get('criteria', {}).get('description') or st.get('criteria', {}).get('name') or '—')} |",
         "", "## I. Tóm tắt nội dung", ""]
    if sm.get("tom_tat"):
        L += [sm["tom_tat"], ""]
    L += [f"- {x}" for x in sm.get("noi_dung_chinh", [])] or ["- (Chưa tóm tắt được – xem các phần trích xuất bên dưới)"]

    yes = [r for r in res if r["de_cap"]]
    order = {"cao": 0, "trung_binh": 1, "thap": 2}
    yes.sort(key=lambda r: order.get(r["muc_do_kq"], 3))
    L += ["", "## II. Các vấn đề liên quan đến ngành", ""]
    if yes:
        L += ["| TT | Nhóm | Tiêu chí | Mức độ | Nhận định |", "|---|---|---|---|---|"]
        L += [f"| {i} | {_esc(r['nhom'])} | {_esc(r['hoi'])} | {MUC_DO.get(r['muc_do_kq'], '')} | {_esc(r['nhan_dinh'])} |"
              for i, r in enumerate(yes, 1)]
        L += ["", "### Chi tiết và căn cứ", ""]
        for i, r in enumerate(yes, 1):
            L += [f"**{i}. {r['hoi']}** — mức độ: {MUC_DO.get(r['muc_do_kq'], '')}", "", r["nhan_dinh"], ""]
            if r.get("can_cu"):
                L += [f"*Căn cứ đối chiếu:* {r['can_cu']}", ""]
            for q in r["trich_dan"]:
                L.append(f"> “{q.strip()}”")
            if r["vi_tri"]:
                L.append(f"\n*Vị trí trong văn bản:* {'; '.join(r['vi_tri'])}")
            if r.get("kb"):
                L.append("*Liên quan cơ sở tri thức:* " + "; ".join(
                    f"{k.get('so_hieu') or k.get('title')} ({k.get('breadcrumb')})" for k in r["kb"]))
            L.append("")
    else:
        L += ["Không xác định được vấn đề liên quan theo bộ tiêu chí đã áp dụng.", ""]

    L += ["## III. Nhiệm vụ, thời hạn (trích xuất từ văn bản)", ""]
    asg, dl = st.get("assignments", []), st.get("deadlines", [])
    if asg:
        L += ["**Nhiệm vụ được giao:**", ""] + [f"- **{_esc(a['chu_the'])}** {a['hanh_dong']}: {a['cau']} *({a['vi_tri']})*"
                                              for a in asg[:15]] + [""]
    if dl:
        L += ["**Mốc thời gian, thời hạn:**", ""] + [f"- {', '.join(d['moc'])} — {d['cau']} *({d['vi_tri']})*" for d in dl[:15]] + [""]
    if not asg and not dl:
        L += ["Không trích xuất được nhiệm vụ hoặc thời hạn cụ thể.", ""]

    L += ["## IV. Đối chiếu cơ sở tri thức của đơn vị", ""]
    refs = st.get("refs_out", [])
    if refs:
        L += ["| Văn bản viện dẫn | Trong kho văn bản chuẩn | Hiệu lực |", "|---|---|---|"]
        for r in refs:
            hl = "—"
            if r.get("het_hieu_luc"):
                x = r["het_hieu_luc"]
                hl = f"**Hết hiệu lực từ {x.get('het_hieu_luc_tu', '')}** – thay bằng {x.get('thay_the_boi', '')} ({x.get('can_cu', '')})"
            elif r["co_trong_kho"]:
                hl = "Còn hiệu lực" if r["trang_thai"] in (None, "", "con_hieu_luc") else f"**{r['trang_thai']}**" + (
                    f" (thay thế bởi {r['thay_the_boi']})" if r.get("thay_the_boi") else "")
            L.append(f"| {_esc(r['so_hieu'])} | {'Có – ' + _esc(r.get('ten') or '') if r['co_trong_kho'] else 'Chưa có'} | {hl} |")
        L.append("")
    rel = st.get("related", [])
    if rel:
        L += ["**Tài liệu nội bộ liên quan:**", ""] + [
            f"- {x.get('title')} › {x.get('breadcrumb')}" + (f" ({x['so_hieu']})" if x.get("so_hieu") else "") for x in rel[:6]] + [""]
    if not refs and not rel:
        L += ["Không tìm thấy văn bản, tài liệu liên quan trong cơ sở tri thức.", ""]

    L += ["## V. Điểm cần lưu ý", ""]
    notes = [f"{r['hoi']}: {r['nhan_dinh']}" for r in yes if r["muc_do_kq"] == "cao"]
    notes += [f"Căn cứ **{r['so_hieu']}** ({r['het_hieu_luc'].get('ten', '')}) đã hết hiệu lực – đề nghị thay bằng "
              f"{r['het_hieu_luc'].get('thay_the_boi', '')}." for r in refs if r.get("het_hieu_luc")]
    notes += [f"Văn bản viện dẫn **{r['so_hieu']}** chưa có trong kho văn bản chuẩn – đề nghị bổ sung để đối chiếu."
              for r in refs if not r["co_trong_kho"] and not r.get("het_hieu_luc")]
    notes += [f"Văn bản viện dẫn **{r['so_hieu']}** có trạng thái “{r['trang_thai']}” – kiểm tra căn cứ áp dụng."
              for r in refs if r["co_trong_kho"] and not r.get("het_hieu_luc")
              and r["trang_thai"] not in (None, "", "con_hieu_luc")]
    L += [f"- {n}" for n in notes] or ["- Không có điểm cần lưu ý đặc biệt theo các tiêu chí đã áp dụng."]

    props = [(r["hoi"], r["de_xuat"]) for r in yes if r.get("de_xuat")]
    L += ["", "## VI. Đề xuất (ý kiến tham khảo)", ""]
    L += [f"- {d} *(liên quan: {h[:80]})*" for h, d in props] or ["- Chưa có đề xuất."]
    no = [r for r in res if not r["de_cap"]]
    if no:
        L += ["", "## Phụ lục. Tiêu chí văn bản không đề cập", ""] + [f"- {r['nhom']}: {r['hoi']}" for r in no]
    L += ["", "---", f"*Báo cáo do trợ lý AI nội bộ hỗ trợ lập theo yêu cầu của {author}; là tài liệu tham khảo, "
                    "không thay thế ý kiến chuyên môn. Các nhận định cần được cán bộ chuyên môn thẩm định trước khi sử dụng.*"]
    return "\n".join(L)
