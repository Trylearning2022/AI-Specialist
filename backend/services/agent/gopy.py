"""Tác vụ THAM GIA Ý KIẾN DỰ THẢO VĂN BẢN (kind "gop_y").

Kết cấu công văn (theo yêu cầu nghiệp vụ, cấu hình tại skills/soan-cong-van-gop-y, khóa `gop_y`):
    1. Căn cứ                     văn bản đề nghị tham gia ý kiến (cơ quan, số hiệu, ngày) + tên dự thảo – CHƯƠNG TRÌNH ghép
    2. Nội dung tham gia ý kiến   ý kiến chung + ý kiến cụ thể theo từng khía cạnh:
                                    thuật ngữ chuyên môn · căn cứ pháp lý · nhiệm vụ của ngành · kỹ thuật (bảo mật, ký số, xác thực)
                                  mỗi ý: vị trí (điều, khoản) → nhận xét → đề nghị sửa thành → căn cứ
    3. Đề xuất, kiến nghị         chỉ khi có (bỏ nếu không có)
    Phụ lục                       bảng tổng hợp đề xuất chỉnh sửa (vị trí | dự thảo | đề nghị sửa | lý do, căn cứ)

Các bước:
    tiep_nhan   Tiếp nhận dự thảo, văn bản đề nghị     chương trình  chuẩn hóa cấu trúc Điều/Khoản, trích số hiệu, ngày, cơ quan
    thuat_ngu   Rà soát thuật ngữ                      chương trình  (1) danh mục dùng đúng ↔ cần tránh trong kỹ năng;
                                                                     (2) định nghĩa trong dự thảo ↔ định nghĩa trong kho văn bản chuẩn
    can_cu      Rà soát căn cứ pháp lý                 chương trình  hết hiệu lực, trạng thái trong kho, thiếu căn cứ bắt buộc
    nhiem_vu    Rà soát nhiệm vụ của ngành             mô hình       đoạn có chủ thể ngành + điều luật tra được → nhận xét có căn cứ
    ky_thuat    Rà soát nội dung kỹ thuật              mô hình       đoạn bảo mật, ký số, xác thực + quy định, tài liệu kỹ thuật
    tong_hop    Ý kiến chung, kiến nghị                chương trình + mô hình; tiền lệ: ý kiến đơn vị đã tham gia trước đây
                ⏸ CHỜ XÁC NHẬN                          người dùng    chọn, sửa từng ý kiến (bỏ qua nếu auto_confirm)
    hoan_thien  Hoàn thiện công văn                    chương trình  thể thức, phụ lục bảng đề xuất chỉnh sửa; bản sạch + bản kèm nguồn

Nguyên tắc: phần XÁC ĐỊNH ĐƯỢC bằng quy tắc (thuật ngữ, căn cứ) do chương trình làm – không phụ thuộc mô hình, không bịa;
mô hình chỉ nhận xét đoạn đã được chương trình chọn, với điều luật đã tra được; vị trí (điều, khoản) do chương trình xác định.
"""
import logging
import re
from datetime import date
from pathlib import Path

from aicommon.config import get_settings
from aicommon.internal import ServiceError, SyncSvc
from aicommon.llm import LLMError
from aicommon.markdown import normalize_vn_structure
from aicommon.resources import domain_context, get_skill, prompt, read_md
from aicommon.text import content_tokens, nfc, numbers, truncate_tokens, unaccent

from . import archive as AR
from . import docs as D
from .analyze import _norm_so, expired_refs
from .runner import Ctx

log = logging.getLogger("agent.gopy")
S = get_settings()
SKILL = "soan-cong-van-gop-y"
PLAN = [("tiep_nhan", "Tiếp nhận dự thảo, văn bản đề nghị"), ("thuat_ngu", "Rà soát thuật ngữ chuyên môn"),
        ("can_cu", "Rà soát căn cứ pháp lý"), ("nhiem_vu", "Rà soát nhiệm vụ của ngành Cơ yếu"),
        ("ky_thuat", "Rà soát nội dung kỹ thuật (bảo mật, ký số, xác thực)"),
        ("tong_hop", "Lập ý kiến chung, kiến nghị; chờ xác nhận"), ("hoan_thien", "Hoàn thiện công văn, phụ lục")]
ASPECT_SCHEMA = {"type": "object", "properties": {
    "co_van_de": {"type": "boolean"}, "nhan_xet": {"type": "string"}, "de_nghi_sua": {"type": "string"},
    "can_cu": {"type": "string"}, "muc_do": {"type": "string", "enum": ["cao", "trung_binh", "thap"]}},
    "required": ["co_van_de", "nhan_xet", "de_nghi_sua", "can_cu", "muc_do"]}
KN_SCHEMA = {"type": "object", "properties": {"kien_nghi": {"type": "array", "maxItems": 3, "items": {"type": "string"}}},
             "required": ["kien_nghi"]}
DRAFT_NOTE = "DỰ THẢO – do trợ lý AI hỗ trợ soạn, cần cán bộ chuyên môn rà soát, hoàn chỉnh trước khi trình ký"
MUC_DO_ORDER = {"cao": 0, "trung_binh": 1, "thap": 2}


def config(name: str | None = None) -> tuple[dict, dict]:
    """Mẫu Công văn có cấu hình tham gia ý kiến (khóa gop_y). name: mẫu người dùng chọn trong phân hệ soạn thảo."""
    sk = get_skill(name or SKILL)
    if not sk or not isinstance(sk["meta"].get("gop_y"), dict):
        raise ValueError(f"Thiếu cấu hình tham gia ý kiến (skills/{name or SKILL}/SKILL.md, khóa gop_y).")
    return sk, sk["meta"]["gop_y"]


# ============================================================ vị trí trong dự thảo (chương trình)
_DIEU = re.compile(r"^\s*#*\s*\**\s*Điều\s+(\d+[a-zđ]?)\b", re.I)
_KHOAN = re.compile(r"^\s*(\d{1,2})\.\s+\S")
_DIEM = re.compile(r"^\s*([a-zđ])\)\s+\S")
_HEAD = re.compile(r"^\s*#+\s*(.+)$")


def positions(md: str) -> list[tuple[str, str]]:
    """[(vị trí, dòng)] – vị trí dạng "điểm a khoản 2 Điều 5", "khoản 1 Điều 3", "Điều 4", hoặc tên mục."""
    out, dieu, khoan, diem, head = [], "", "", "", ""
    for ln in md.splitlines():
        if not ln.strip():
            continue
        m = _DIEU.match(ln)
        if m:
            dieu, khoan, diem = m.group(1), "", ""
        elif _HEAD.match(ln):
            hx = _HEAD.match(ln).group(1).strip("* ")[:80]
            if re.match(r"(Chương|Mục|Phần|Phụ lục)\s+|[IVXLC]+\.\s", hx, re.I):  # tên văn bản, "DỰ THẢO" không phải mục
                head = hx
            if not dieu:
                khoan = diem = ""
        else:
            mk, md_ = _KHOAN.match(ln), _DIEM.match(ln)
            if mk:
                khoan, diem = mk.group(1), ""
            elif md_ and khoan:
                diem = md_.group(1)
        if dieu:
            loc = " ".join(x for x in (f"điểm {diem}" if diem else "", f"khoản {khoan}" if khoan else "", f"Điều {dieu}") if x)
        elif head:
            loc = f"mục “{head}”"
        else:
            loc = "phần căn cứ" if re.match(r"^\W*Căn cứ\b", ln) else "phần mở đầu"
        out.append((loc[0].upper() + loc[1:], ln.strip()))
    return out


def _norm(s: str) -> str:
    return " ".join(unaccent(nfc(s)).lower().split())


def locate(pos: list[tuple[str, str]], snippet: str) -> str:
    key = _norm(snippet)[:80]
    for loc, ln in pos:
        if key and key[:40] in _norm(ln):
            return loc
    return ""


def _has(text_low: str, phrase: str) -> bool:
    return re.search(rf"(?<![\wÀ-ỹđ]){re.escape(nfc(phrase).lower())}(?![\wÀ-ỹđ])", text_low) is not None


def _strip_md(s: str) -> str:
    return re.sub(r"^[#>*\-+\s]+|\*\*", "", s).strip()


# ============================================================ khía cạnh 1: thuật ngữ (chương trình)
def term_rules(pos: list[tuple[str, str]], rules: list[dict]) -> list[dict]:
    """Dò cách viết cần tránh theo danh mục trong kỹ năng. Mỗi thuật ngữ một ý kiến, gom các vị trí."""
    out = []
    for r in rules:
        pats = [re.compile(r["tranh_regex"])] if r.get("tranh_regex") else \
            [re.compile(rf"(?<![\wÀ-ỹđ]){re.escape(t)}(?![\wÀ-ỹđ])", re.I) for t in r.get("tranh") or []]
        hits: dict[str, list[tuple[str, str]]] = {}
        for loc, ln in pos:
            ln_n = nfc(ln)
            for p in pats:
                for m in p.finditer(ln_n):
                    if re.search(r"(Luật|Pháp lệnh)\s*$", ln_n[:m.start()], re.I):
                        continue  # tên văn bản được viện dẫn ("Luật An toàn thông tin mạng") – xem khía cạnh căn cứ
                    hits.setdefault(m.group(0), []).append((loc, ln))
        for bad, where in hits.items():
            locs = list(dict.fromkeys(w[0] for w in where))
            vt = ", ".join(locs[:4]) + (f" và {len(locs) - 4} vị trí khác" if len(locs) > 4 else "")
            out.append({"khia_canh": "thuat_ngu", "vi_tri": vt, "trich": _strip_md(where[0][1])[:400],
                        "nhan_xet": f"Dự thảo dùng “{bad}”; thuật ngữ theo quy định là “{r['dung']}”"
                                    + (f" ({r['ghi_chu']})" if r.get("ghi_chu") else "") + ".",
                        "de_nghi_sua": f"Đề nghị thay “{bad}” bằng “{r['dung'].split(' / ')[0]}”.",
                        "can_cu": r.get("can_cu", ""), "muc_do": "trung_binh", "nguon_tra_cuu": [], "boi": "chuong_trinh"})
    return out


_DEF = re.compile(r"^\s*(?:\d{1,2}\.|[a-zđ]\))\s*(?:\*\*)?(.{3,80}?)(?:\*\*)?\s+là\s+(.{20,})$")


def draft_definitions(md: str) -> list[tuple[str, str, str]]:
    """Định nghĩa trong điều "Giải thích từ ngữ" của dự thảo: [(vị trí, thuật ngữ, nội dung định nghĩa)]."""
    out, inside, dieu = [], False, ""
    for ln in md.splitlines():
        m = _DIEU.match(ln)
        if m:
            dieu = m.group(1)
            inside = "giai thich tu ngu" in _norm(ln)
            continue
        if inside:
            d = _DEF.match(ln.strip())
            if d:
                k = _KHOAN.match(ln)
                out.append((f"Khoản {k.group(1)} Điều {dieu}" if k else f"Điều {dieu}", d.group(1).strip(" *:"),
                            d.group(2).strip()))
    return out[:40]


def _jaccard(a: str, b: str) -> float:
    x, y = set(content_tokens(a)), set(content_tokens(b))
    return len(x & y) / max(1, len(x | y))


def definition_checks(ctx: Ctx, md: str) -> list[dict]:
    """So định nghĩa của dự thảo với định nghĩa trong luật (kho văn bản chuẩn). Khác nhiều → đề nghị thống nhất,
    kèm NGUYÊN VĂN định nghĩa trong luật (chương trình lấy từ kho, không do mô hình viết)."""
    from services.orchestrator.pipelines import doc_name, locator
    exact, out = SyncSvc(S.exact_url), []
    for loc, term, defi in draft_definitions(md):
        try:
            hits = exact.call("POST", "/search", ctx.user, json={"query": term, "limit": 6})["results"]
        except ServiceError as e:
            ctx.warn(f"Không tra được định nghĩa “{term}” trong kho văn bản chuẩn: {e.detail}")
            break
        pat = re.compile(rf"^\s*\d+\.\s*{re.escape(_norm(term))}\s+la\s+(.+)", re.S)
        for h in hits:
            if not any("giai thich tu ngu" in _norm(p) for p in (h.get("path") or [])):
                continue
            sec = exact.call("GET", f"/sections/{h['section_id']}", ctx.user)
            m = pat.match(_norm(sec["text"]))
            if not m:
                continue
            law_text = re.sub(r"^\s*\d+\.\s*", "", sec["text"].strip())
            sim = _jaccard(defi, law_text)
            if sim < S.agent_gopy_def_similarity:
                lc = locator(sec)
                ref = f"{lc[:1].lower() + lc[1:] if not lc.startswith('Điều') else lc} {doc_name(sec)}"
                out.append({"khia_canh": "thuat_ngu", "vi_tri": loc, "trich": f"{term} là {defi}"[:400],
                            "nhan_xet": f"Định nghĩa “{term}” trong dự thảo chưa thống nhất với định nghĩa tại {ref}.",
                            "de_nghi_sua": f"Đề nghị sử dụng định nghĩa tại {ref}: “{law_text[:500]}” hoặc dẫn chiếu quy định này.",
                            "can_cu": ref, "muc_do": "trung_binh", "boi": "chuong_trinh",
                            "nguon_tra_cuu": [{"title": sec.get("ten"), "so_hieu": sec.get("so_hieu"), "vi_tri": locator(sec)}]})
            break
    return out


# ============================================================ khía cạnh 2: căn cứ pháp lý (chương trình)
def legal_basis_checks(ctx: Ctx, md: str, required: list[dict]) -> tuple[list[dict], list[dict]]:
    """Trả (ý kiến, bảng đối chiếu căn cứ cho phụ lục làm việc)."""
    doc = D.Doc("DT", "", md, {})
    refs = D.references(doc)
    out, table = [], []
    try:
        catalog = {_norm_so(d.get("so_hieu", "")): d for d in SyncSvc(S.exact_url).call("GET", "/catalog", ctx.user)["docs"]
                   if d.get("so_hieu")}
    except ServiceError as e:
        catalog = {}
        ctx.warn(f"Không tra được kho văn bản chuẩn: {e.detail}")
    expired = expired_refs(md, refs)
    pos = positions(md)
    for r in refs:
        d, x = catalog.get(_norm_so(r)), expired.pop(_norm_so(r), None)
        table.append({"so_hieu": r, "trong_kho": bool(d), "trang_thai": (d or {}).get("trang_thai"), "het_hieu_luc": bool(x)})
        line = next((ln for _, ln in pos if r in ln), "")
        loc = locate(pos, line) if line else "Phần căn cứ"
        if x:
            out.append({"khia_canh": "can_cu", "vi_tri": loc, "trich": _strip_md(line)[:400],
                        "nhan_xet": f"Dự thảo viện dẫn {x.get('ten', r)} số {r}, văn bản này đã hết hiệu lực từ "
                                    f"{_vn_date(x.get('het_hieu_luc_tu', ''))}.",
                        "de_nghi_sua": f"Đề nghị thay bằng {x.get('thay_the_boi', '')}.", "can_cu": x.get("can_cu", ""),
                        "muc_do": "cao", "boi": "chuong_trinh", "nguon_tra_cuu": []})
        elif d and d.get("trang_thai") not in (None, "", "con_hieu_luc"):
            out.append({"khia_canh": "can_cu", "vi_tri": loc, "trich": _strip_md(line)[:400],
                        "nhan_xet": f"Văn bản {r} có trạng thái “{d['trang_thai']}” trong kho văn bản chuẩn.",
                        "de_nghi_sua": "Đề nghị rà soát, cập nhật căn cứ còn hiệu lực" +
                                       (f" ({d['thay_the_boi']})." if d.get("thay_the_boi") else "."),
                        "can_cu": "", "muc_do": "cao", "boi": "chuong_trinh", "nguon_tra_cuu": []})
    for x in expired.values():  # viện dẫn theo tên, không ghi số hiệu
        line = next((ln for _, ln in pos if _norm(x["ten"]) in _norm(ln)), "")
        out.append({"khia_canh": "can_cu", "vi_tri": locate(pos, line) or "Phần căn cứ", "trich": _strip_md(line)[:400],
                    "nhan_xet": f"Dự thảo viện dẫn {x['ten']}, văn bản này đã hết hiệu lực từ {_vn_date(x.get('het_hieu_luc_tu', ''))}.",
                    "de_nghi_sua": f"Đề nghị thay bằng {x.get('thay_the_boi', '')}.", "can_cu": x.get("can_cu", ""),
                    "muc_do": "cao", "boi": "chuong_trinh", "nguon_tra_cuu": []})
    low = nfc(md).lower()
    cited = {_norm_so(r) for r in refs}
    for rq in required:
        kws = [k for k in rq.get("khi") or [] if _has(low, k)]
        if not kws:
            continue
        if _norm_so(rq["so_hieu"]) in cited or _has(low, rq["ten"]):
            continue
        if any(rq["so_hieu"] in f["de_nghi_sua"] for f in out):  # đã đề nghị thay căn cứ hết hiệu lực bằng luật này
            continue
        out.append({"khia_canh": "can_cu", "vi_tri": "Phần căn cứ", "trich": "",
                    "nhan_xet": f"Dự thảo có nội dung về {', '.join(kws[:3])} nhưng chưa viện dẫn {rq['ten']}.",
                    "de_nghi_sua": f"Đề nghị bổ sung căn cứ: {rq['ten']} số {rq['so_hieu']}.",
                    "can_cu": "", "muc_do": "trung_binh", "boi": "chuong_trinh", "nguon_tra_cuu": []})
    return out, table


def _vn_date(iso: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else iso


# ============================================================ khía cạnh 3, 4: nhiệm vụ, kỹ thuật (mô hình)
_ACTION = re.compile(r"(chủ trì|trách nhiệm|nhiệm vụ|quản lý|thẩm định|kiểm tra|cung cấp|cấp phát|hướng dẫn|"
                     r"phối hợp|quy định|bảo đảm|triển khai|phê duyệt|chứng nhận)", re.I)


def candidate_passages(pos: list[tuple[str, str]], keywords: list[str], limit: int) -> list[dict]:
    """Đoạn (dòng/khoản) chứa từ khóa của khía cạnh; ưu tiên câu có hành động giao nhiệm vụ, quy định."""
    cands = []
    for i, (loc, ln) in enumerate(pos):
        if _HEAD.match(ln) or len(ln) < 30:
            continue
        low = nfc(ln).lower()
        kws = [k for k in keywords if _has(low, k)]
        if not kws:
            continue
        score = len(kws) + (2 if _ACTION.search(ln) else 0)
        cands.append({"vi_tri": loc, "text": _strip_md(ln), "tu_khoa": kws, "score": score, "i": i})
    # mỗi vị trí một đoạn (gộp dòng cùng khoản), giữ thứ tự trong dự thảo
    best: dict[str, dict] = {}
    for c in cands:
        b = best.get(c["vi_tri"])
        if b:
            b["text"] = (b["text"] + " " + c["text"])[:1500]
            b["score"] += c["score"]
            b["tu_khoa"] = list(dict.fromkeys(b["tu_khoa"] + c["tu_khoa"]))
        else:
            best[c["vi_tri"]] = dict(c)
    top = sorted(best.values(), key=lambda c: -c["score"])[:limit]
    return sorted(top, key=lambda c: c["i"])


def _legal_context(ctx: Ctx, text: str, with_tech: bool) -> list[dict]:
    """Quy định liên quan một đoạn: kho văn bản chuẩn (nguyên văn) + tài liệu kỹ thuật nội bộ (khía cạnh kỹ thuật)."""
    from services.orchestrator.pipelines import doc_name, locator
    out = []
    exact = SyncSvc(S.exact_url)
    try:
        for h in exact.call("POST", "/search", ctx.user, json={"query": text[:400], "limit": 4})["results"][:2]:
            sec = exact.call("GET", f"/sections/{h['section_id']}", ctx.user)
            out.append({"ref": f"{locator(sec)} {doc_name(sec)}".strip(), "text": truncate_tokens(sec["text"], 350),
                        "title": sec.get("ten"), "so_hieu": sec.get("so_hieu"), "vi_tri": locator(sec)})
    except ServiceError as e:
        ctx.warn(f"Không tra được kho văn bản chuẩn: {e.detail}")
    if with_tech:
        try:
            for x in SyncSvc(S.search_url).call("POST", "/search", ctx.user, json={
                    "query": text[:400], "top_k": 2, "filters": {"bo_nhom": [AR.NHOM_DI]}})["results"][:1]:
                out.append({"ref": f"{x.get('title')} › {x.get('breadcrumb')}", "text": truncate_tokens(x.get("text", ""), 300),
                            "title": x.get("title"), "so_hieu": x.get("so_hieu"), "vi_tri": x.get("breadcrumb")})
        except ServiceError as e:
            ctx.warn(f"Không tra được tài liệu kỹ thuật: {e.detail}")
    return out


def review_aspect(ctx: Ctx, h, aspect: dict, pos: list[tuple[str, str]], prec: list[dict]) -> list[dict]:
    cands = candidate_passages(pos, [str(k) for k in aspect.get("tu_khoa") or []], S.agent_gopy_max_passages)
    if not cands:
        return []
    dctx = domain_context()
    sys_p = prompt("gop-y-khia-canh") + (f"\n\nBỐI CẢNH NGÀNH:\n{dctx}" if dctx else "")
    out = []
    for k, c in enumerate(cands, 1):
        h.sub(k, len(cands), f"{aspect['ten']} – {c['vi_tri']} ({k}/{len(cands)})")
        law = _legal_context(ctx, c["text"], with_tech=aspect["id"] == "ky_thuat")
        qb = "\n\n".join(f"[Q{j + 1}] {x['ref']}\n{x['text']}" for j, x in enumerate(law)) or "(không tra được quy định liên quan)"
        pr = [p for s, p in D.rank(c["text"], prec, k=1) if s >= 3.0]
        prb = f"\n\nÝ KIẾN ĐƠN VỊ ĐÃ THAM GIA TRƯỚC ĐÂY ({pr[0].get('so_hieu') or pr[0].get('title')}):\n{truncate_tokens(pr[0]['text'], 200)}" if pr else ""
        try:
            r = ctx.llm_json([{"role": "system", "content": sys_p},
                              {"role": "user", "content": f"KHÍA CẠNH: {aspect['ten']}\n\nĐOẠN DỰ THẢO ({c['vi_tri']}):\n{c['text']}"
                                                          f"\n\nQUY ĐỊNH LIÊN QUAN:\n{qb}{prb}"}],
                             ASPECT_SCHEMA, task="gop-y-khia-canh", max_tokens=500)
        except LLMError as e:
            ctx.warn(f"{aspect['ten']} – {c['vi_tri']}: lỗi mô hình ({e}).")
            continue
        if not r.get("co_van_de") or not str(r.get("nhan_xet", "")).strip():
            continue
        cc = str(r.get("can_cu", "")).strip()
        allowed = " ".join(x["ref"] + " " + x["text"] for x in law) + " " + dctx
        if cc and not _cite_ok(cc, allowed):
            cc += " (cần đối chiếu)"
        dn = str(r.get("de_nghi_sua", "")).strip()
        if numbers(dn) - numbers(c["text"] + " " + allowed):
            dn += " *(số liệu cần đối chiếu)*"
        out.append({"khia_canh": aspect["id"], "vi_tri": c["vi_tri"], "trich": c["text"][:600],
                    "nhan_xet": str(r["nhan_xet"]).strip(), "de_nghi_sua": dn, "can_cu": cc,
                    "muc_do": r.get("muc_do", "trung_binh"), "boi": "mo_hinh",
                    "nguon_tra_cuu": [{k2: x[k2] for k2 in ("title", "so_hieu", "vi_tri")} for x in law]})
    return out


def _duplicate(a: dict, b: dict) -> bool:
    """Cùng vị trí và nhận xét/đề nghị gần giống (một đoạn được nhận xét ở hai khía cạnh với cùng nội dung)."""
    if a.get("vi_tri") != b.get("vi_tri"):
        return False
    return _jaccard(a["nhan_xet"] + " " + a.get("de_nghi_sua", ""), b["nhan_xet"] + " " + b.get("de_nghi_sua", "")) >= 0.7


def _cite_ok(cite: str, allowed: str) -> bool:
    """Căn cứ mô hình nêu phải có trong quy định đã cung cấp: mọi "Điều N" trong căn cứ xuất hiện trong nguồn."""
    nums = re.findall(r"Điều\s+(\d+)", cite, re.I)
    if not nums:
        return False
    return all(re.search(rf"Điều\s+{n}\b", allowed, re.I) for n in nums)


# ============================================================ luồng chính
def run(ctx: Ctx):
    ctx.plan(PLAN)
    inp, st = ctx.input, ctx.state
    sk, cfg = config(inp.get("mau"))
    aspects = {a["id"]: a for a in cfg.get("khia_canh") or [] if a.get("bat", True)}

    if not ctx.done("tiep_nhan"):
        with ctx.step("tiep_nhan", "Đang đọc dự thảo, văn bản đề nghị…") as h:
            dt, cv = _load_inputs(ctx)
            md = normalize_vn_structure(dt.markdown)
            ten = inp.get("ten_du_thao") or _draft_title(dt)
            cvm = {"so_hieu": inp.get("cv_so_hieu") or (cv.meta.get("so_hieu") if cv else ""),
                   "ngay": inp.get("cv_ngay") or (cv.meta.get("ngay_ban_hanh") if cv else ""),
                   "co_quan": inp.get("cv_co_quan") or (cv.meta.get("co_quan_ban_hanh") if cv else ""),
                   "trich_yeu": (cv.title if cv else "")}
            pos = positions(md)
            n_dieu = len({p[0].split("Điều ")[-1] for p in pos if "Điều " in p[0]})
            h.out(f"Dự thảo “{ten[:80]}”: {n_dieu} điều" + (f" · văn bản đề nghị {cvm['so_hieu']}" if cvm["so_hieu"] else ""))
            ctx.save_state(md=md, ten=ten, cv=cvm, findings={})
            if not inp.get("ten_du_thao"):  # tiêu đề tác vụ theo tên dự thảo đọc được (lúc tạo chỉ có tên tệp)
                ctx._save(title=f"Công văn: Tham gia ý kiến {ten}"[:300])
    md, pos = st["md"], positions(st["md"])
    findings: dict = st.get("findings", {})

    if not ctx.done("thuat_ngu"):
        if "thuat_ngu" not in aspects:
            ctx.skip("thuat_ngu", "Khía cạnh đã tắt trong cấu hình")
        else:
            with ctx.step("thuat_ngu", "Đang dò thuật ngữ, đối chiếu định nghĩa với kho văn bản chuẩn…") as h:
                f = term_rules(pos, cfg.get("thuat_ngu") or []) + definition_checks(ctx, md)
                findings["thuat_ngu"] = f
                h.out(f"{len(f)} ý kiến" if f else "Không phát hiện vấn đề")
                ctx.save_state(findings=findings)

    if not ctx.done("can_cu"):
        if "can_cu" not in aspects:
            ctx.skip("can_cu", "Khía cạnh đã tắt trong cấu hình")
        else:
            with ctx.step("can_cu", "Đang đối chiếu căn cứ pháp lý với kho văn bản chuẩn…") as h:
                f, table = legal_basis_checks(ctx, md, cfg.get("can_cu_bat_buoc") or [])
                findings["can_cu"] = f
                h.out(f"{len(table)} văn bản viện dẫn · {len(f)} ý kiến")
                ctx.save_state(findings=findings, refs=table)

    prec = st.get("precedents")
    if prec is None:
        prec = AR.precedents(ctx.user, f"tham gia ý kiến {st['ten']}", k=max(2, S.agent_precedents))
        ctx.save_state(precedents=prec)

    for sid in ("nhiem_vu", "ky_thuat"):
        if ctx.done(sid):
            continue
        if sid not in aspects:
            ctx.skip(sid, "Khía cạnh đã tắt trong cấu hình")
            continue
        with ctx.step(sid) as h:
            f = review_aspect(ctx, h, aspects[sid], pos, prec)
            findings[sid] = f
            h.out(f"{len(f)} ý kiến" if f else "Không phát hiện vấn đề")
            ctx.save_state(findings=findings)

    if not ctx.done("tong_hop"):
        confirmed = ctx.confirmed("tong_hop")
        if confirmed:
            ctx._step("tong_hop").update(status="xong", detail="Đã được người dùng xác nhận")
            ctx.save_state(final=confirmed)
        else:
            with ctx.step("tong_hop", "Đang lập ý kiến chung, kiến nghị…") as h:
                items = []
                for a in cfg.get("khia_canh") or []:
                    for x in sorted(findings.get(a["id"], []), key=lambda x: MUC_DO_ORDER.get(x["muc_do"], 3)):
                        if any(_duplicate(x, y) for y in items):
                            continue
                        items.append({**x, "id": f"y{len(items) + 1}", "chon": True})
                don_vi = inp.get("don_vi") or "Đơn vị"
                ykc = (cfg.get("y_kien_chung_co_gop_y") if items else cfg.get("y_kien_chung_nhat_tri")) or ""
                kn = _recommendations(ctx, st["ten"], items, prec)
                payload = {"y_kien_chung": ykc.format(don_vi=don_vi), "muc": items, "kien_nghi": kn,
                           "tien_le": [{"title": p.get("title"), "so_hieu": p.get("so_hieu"), "trich": p["text"][:500]} for p in prec]}
                h.out(f"{len(items)} ý kiến cụ thể · {len(kn)} kiến nghị")
            if inp.get("auto_confirm"):
                ctx.save_state(final=payload)
            else:
                ctx.save_state(final=payload)
                ctx.confirm("tong_hop", payload, f"Đã lập {len(items)} ý kiến – đề nghị đồng chí chọn, sửa và xác nhận để hoàn thiện công văn.")

    with ctx.step("hoan_thien", "Đang hoàn thiện công văn theo thể thức…") as h:
        ban_sach, ban_kem = compose(inp, sk, cfg, st["ten"], st["cv"], st["final"], st.get("refs", []), prec)
        chosen = [m for m in st["final"]["muc"] if m.get("chon", True)]
        h.out(f"{len(chosen)} ý kiến · {len(ban_sach.split())} từ")
    ctx.finish(ban_sach, {"ban_sach": ban_sach, "ban_can_cu": ban_kem, "muc": st["final"]["muc"], "ten_loai": "Công văn",
                          "ten_du_thao": st["ten"], "van_ban_de_nghi": st["cv"], "refs": st.get("refs", []),
                          "tien_le": [{k: p.get(k) for k in ("title", "so_hieu", "doc_id")} for p in prec]})


def _load_inputs(ctx: Ctx) -> tuple[D.Doc, D.Doc | None]:
    """Dự thảo (bắt buộc) và văn bản đề nghị tham gia ý kiến (tùy chọn). Hai tệp không chỉ rõ vai trò:
    tệp có chữ "dự thảo" ở tên/đầu văn bản (hoặc dài hơn) là dự thảo."""
    inp = ctx.input
    loaded: list[D.Doc] = []
    for u in inp.get("uploads") or []:
        d = D.load_upload(u["upload_id"], u["filename"], u["path"], "")
        d.meta["_role"], d.meta["_fname"] = u.get("role", ""), u["filename"]
        loaded.append(d)
    for did in inp.get("doc_ids") or []:
        loaded.append(D.load_registered(ctx.user, did, ""))
    if not loaded:
        raise ValueError("Chưa có dự thảo văn bản cần tham gia ý kiến.")
    for d in loaded:
        for w in d.warnings:
            ctx.warn(w)
    dt = next((d for d in loaded if d.meta.get("_role") == "du_thao"), None)
    cv = next((d for d in loaded if d.meta.get("_role") == "de_nghi"), None)
    if not dt:
        def _is_draft(d):
            head = _norm(d.meta.get("_fname", "") + " " + d.markdown[:800])
            return ("du thao" in head) * 10_000_000 + len(d.markdown)
        rest = [d for d in loaded if d is not cv]
        dt = max(rest, key=_is_draft)
        if not cv:
            cv = next((d for d in rest if d is not dt), None)
    return dt, cv


def _draft_title(d: D.Doc) -> str:
    """Tên dự thảo: loại văn bản + trích yếu ("Nghị định quy định …"), lấy từ đầu văn bản."""
    lines = [_strip_md(x) for x in d.markdown.splitlines()[:40] if x.strip()]
    for i, ln in enumerate(lines):
        if re.match(r"^(LUẬT|NGHỊ ĐỊNH|THÔNG TƯ|QUYẾT ĐỊNH|QUY ĐỊNH|QUY CHẾ|KẾ HOẠCH|HƯỚNG DẪN|CHỈ THỊ|NGHỊ QUYẾT)\b", ln):
            nxt = lines[i + 1] if i + 1 < len(lines) and not re.match(r"^(Căn cứ|Theo|Điều|Chương)", lines[i + 1]) else ""
            return f"dự thảo {ln.capitalize()} {nxt[0].lower() + nxt[1:] if nxt else ''}".strip()
    return f"dự thảo {d.title}"


def _recommendations(ctx: Ctx, ten: str, items: list[dict], prec: list[dict]) -> list[str]:
    """Kiến nghị (0–3 ý): chỉ những nội dung vượt phạm vi sửa câu chữ. Không có ý kiến mức "cao" → thường để trống."""
    serious = [m for m in items if m["muc_do"] == "cao" or m["khia_canh"] in ("nhiem_vu", "ky_thuat")]
    if not serious:
        return []
    lines = "\n".join(f"- [{m['khia_canh']}] {m['vi_tri']}: {m['nhan_xet']}" for m in serious[:10])
    try:
        r = ctx.llm_json([{"role": "system", "content": prompt("soan-phan") + "\n\n" + AR.style_block(prec, 1)
                           + "\n\nNhiệm vụ: nêu 0–3 kiến nghị đối với cơ quan chủ trì soạn thảo, chỉ khi các ý kiến dưới đây "
                             "cho thấy cần một việc ngoài sửa câu chữ (ví dụ lấy ý kiến Ban Cơ yếu Chính phủ về nội dung mật mã, "
                             "bổ sung quy định về bảo vệ bí mật nhà nước). Không lặp lại từng ý kiến; không có thì trả danh sách rỗng."},
                          {"role": "user", "content": f"DỰ THẢO: {ten}\n\nCÁC Ý KIẾN:\n{lines}"}],
                         KN_SCHEMA, task="gop-y-kien-nghi", max_tokens=400)
        return [str(x).strip() for x in r.get("kien_nghi", []) if str(x).strip()][:3]
    except LLMError as e:
        ctx.warn(f"Không lập được kiến nghị bằng mô hình ({e}); đồng chí bổ sung khi xác nhận.")
        return []


# ============================================================ hoàn thiện công văn (chương trình)
def compose(inp: dict, sk: dict, cfg: dict, ten: str, cv: dict, final: dict, refs: list[dict],
            prec: list[dict]) -> tuple[str, str]:
    """Trả (bản sạch để trình ký, bản kèm nguồn tra cứu để rà soát)."""
    today = date.today()
    don_vi = inp.get("don_vi") or "Đơn vị"
    co_quan_dn = cv.get("co_quan") or inp.get("noi_nhan") or "…"
    vals = {"co_quan_cap_tren": inp.get("co_quan_cap_tren") or "CƠ QUAN CẤP TRÊN", "don_vi": don_vi.upper(),
            "ky_hieu": inp.get("ky_hieu") or "…", "dia_danh": inp.get("dia_danh") or "…", "ngay": f"{today.day:02d}",
            "thang": f"{today.month:02d}", "nam": str(today.year), "ten_loai_hoa": "",
            "trich_yeu": inp.get("trich_yeu") or f"V/v tham gia ý kiến {ten}",
            "noi_nhan": inp.get("noi_nhan") or co_quan_dn}
    head = read_md(Path(sk["dir"]) / sk["meta"].get("the_thuc", "the-thuc.md")) or \
        "**{don_vi}**\n\nSố: …/{ky_hieu}\n\n**{trich_yeu}**\n\nKính gửi: {noi_nhan}."
    head = re.sub(r"(?m)^#\s*\{ten_loai_hoa\}\s*\n?", "", head)  # công văn không có tên loại
    try:
        header = head.format(**vals)
    except (KeyError, IndexError, ValueError):
        header = head
    # 1. Căn cứ
    if cv.get("so_hieu"):
        vb = f"Công văn số {cv['so_hieu']}" + (f" ngày {_vn_date(str(cv['ngay']))}" if cv.get("ngay") else "")
        cau = cfg.get("cau_dan", "").format(co_quan_de_nghi=co_quan_dn, van_ban_de_nghi=vb, ten_du_thao=ten, don_vi=don_vi)
    else:
        cau = cfg.get("cau_dan_khong_cv", "{don_vi} đã nghiên cứu {ten_du_thao} và tham gia ý kiến như sau:").format(
            don_vi=don_vi, ten_du_thao=ten)
    chosen = [m for m in final.get("muc", []) if m.get("chon", True)]
    names = {a["id"]: a["ten"] for a in cfg.get("khia_canh") or []}
    order = [a["id"] for a in cfg.get("khia_canh") or []]
    body = ["## 1. Căn cứ", "", cau, "", "## 2. Nội dung tham gia ý kiến", "",
            f"**2.1. Ý kiến chung:** {final.get('y_kien_chung', '').strip()}", ""]
    work = list(body)
    n = 1
    for aid in order:
        group = [m for m in chosen if m["khia_canh"] == aid]
        if not group:
            continue
        n += 1
        body += [f"**2.{n}. {names.get(aid, aid)}**", ""]
        work += [f"**2.{n}. {names.get(aid, aid)}**", ""]
        for m in group:
            line = f"- {_item_text(m)}"
            body.append(line)
            src = "; ".join(f"{x.get('vi_tri') or ''} {x.get('title') or ''}".strip() for x in m.get("nguon_tra_cuu") or [])
            work.append(line + (f" *[tra cứu: {src}]*" if src else "") + (" *[chương trình phát hiện]*" if m.get("boi") == "chuong_trinh" else ""))
        body.append("")
        work.append("")
    kn = [k for k in final.get("kien_nghi", []) if str(k).strip()]
    if kn:
        sec = ["## 3. Đề xuất, kiến nghị", ""] + [f"- {k.strip().rstrip('.')}." for k in kn] + [""]
        body += sec
        work += sec
    closing = (f"Trên đây là ý kiến tham gia của {don_vi} đối với {ten}, đề nghị {co_quan_dn} tổng hợp, "
               "nghiên cứu, hoàn thiện./.")
    footer = ["", closing, "", "**Nơi nhận:**\n- Như trên;\n- Lưu: VT.", "",
              f"**{inp.get('nguoi_ky') or '(Chức vụ, họ tên người ký)'}**"]
    table = _appendix(chosen)
    note = f"> *{DRAFT_NOTE}.*"
    ban_sach = "\n".join([note, "", header, "", *body, *footer, *table])
    workp = ["", "---", "## Phụ lục nguồn (bản làm việc – không đưa vào văn bản ban hành)", ""]
    if refs:
        workp += ["**Văn bản dự thảo viện dẫn:**", "", "| Số hiệu | Trong kho văn bản chuẩn | Ghi chú |", "|---|---|---|"]
        workp += [f"| {r['so_hieu']} | {'Có' if r['trong_kho'] else 'Chưa có'} | "
                  f"{'Hết hiệu lực' if r['het_hieu_luc'] else (r.get('trang_thai') or '')} |" for r in refs] + [""]
    if prec:
        workp += ["**Văn bản đơn vị đã ban hành có nội dung tương tự (tiền lệ):**", ""] + [
            f"- {p.get('so_hieu') or p.get('title')} – {p.get('title')}" for p in prec] + [""]
    ban_kem = "\n".join([note, "", header, "", *work, *footer, *table, *workp])
    return ban_sach, ban_kem


def _item_text(m: dict) -> str:
    vt = m.get("vi_tri") or ""
    if vt and not vt.startswith("Điều"):  # "Tại khoản 1 Điều 5", "Tại phần căn cứ"
        vt = vt[0].lower() + vt[1:]
    s = f"Tại {vt}: " if vt else ""
    s += m["nhan_xet"].strip().rstrip(".") + "."
    if m.get("de_nghi_sua"):
        s += " " + m["de_nghi_sua"].strip()
        s = s.rstrip() if s.rstrip().endswith((".", "”", "*")) else s.rstrip() + "."
    if m.get("can_cu"):
        s += f" (Căn cứ: {m['can_cu'].strip().rstrip('.')})."
    return s


def _appendix(chosen: list[dict]) -> list[str]:
    rows = [m for m in chosen if m.get("de_nghi_sua")]
    if not rows:
        return []
    esc = lambda x: str(x or "").replace("|", "\\|").replace("\n", " ")  # noqa: E731
    out = ["", "---", "", "### PHỤ LỤC: BẢNG TỔNG HỢP ĐỀ XUẤT CHỈNH SỬA", "*(Kèm theo Công văn tham gia ý kiến)*", "",
           "| TT | Vị trí | Nội dung dự thảo | Đề nghị chỉnh sửa | Lý do, căn cứ |", "|---|---|---|---|---|"]
    for i, m in enumerate(rows, 1):
        out.append(f"| {i} | {esc(m.get('vi_tri'))} | {esc(m.get('trich'))[:300]} | {esc(m['de_nghi_sua'])} | "
                   f"{esc(m['nhan_xet'])}{(' – ' + esc(m['can_cu'])) if m.get('can_cu') else ''} |")
    return out
