"""Bộ tiêu chí phân tích ngành và mẫu văn bản tham mưu – lưu dạng kỹ năng Markdown trong skills/.

Cán bộ chuyên môn tự soạn, sửa, không cần lập trình:

    skills/phan-tich-<lĩnh-vực>/SKILL.md     loai: phan_tich   – frontmatter `tieu_chi`: danh sách tiêu chí
    skills/soan-<loại-văn-bản>/SKILL.md      loai: soan_thao   – frontmatter `dan_y`: các phần của văn bản,
                                                                  `the_thuc`: tên tệp mẫu thể thức (tùy chọn)

Một tiêu chí:  {id, nhom, hoi, tu_khoa: [..], muc_do_mac_dinh: cao|trung_binh|thap, can_cu}
    - can_cu:   điều, khoản làm chuẩn đối chiếu (đưa vào chỉ thị cho mô hình và vào báo cáo)
    - hoi:      câu hỏi chuyên gia luôn đặt ra khi đọc văn bản (càng cụ thể, kết quả càng tốt)
    - tu_khoa:  từ khóa để chương trình tìm đoạn liên quan trong văn bản trước khi hỏi mô hình;
                không đoạn nào khớp → ghi "không đề cập" mà KHÔNG gọi mô hình (tiết kiệm thời gian trên CPU)
"""
from pathlib import Path

from aicommon.resources import list_skills, read_md


def criteria_sets() -> list[dict]:
    out = []
    for s in list_skills():
        if s["meta"].get("loai") != "phan_tich":
            continue
        tc = s["meta"].get("tieu_chi") or []
        out.append({"name": s["name"], "description": s["meta"].get("description", ""), "so_tieu_chi": len(tc),
                    "nhom": list(dict.fromkeys(t.get("nhom", "Khác") for t in tc)), "mac_dinh": bool(s["meta"].get("mac_dinh"))})
    return sorted(out, key=lambda x: (not x["mac_dinh"], x["name"]))


def get_criteria_set(name: str | None) -> dict | None:
    sets = [s for s in list_skills() if s["meta"].get("loai") == "phan_tich"]
    if not sets:
        return None
    s = next((x for x in sets if x["name"] == name), None) if name else None
    s = s or next((x for x in sets if x["meta"].get("mac_dinh")), sets[0])
    items = []
    for i, t in enumerate(s["meta"].get("tieu_chi") or []):
        if not isinstance(t, dict) or not t.get("hoi"):
            continue
        items.append({"id": str(t.get("id") or f"tc{i + 1:02d}"), "nhom": t.get("nhom", "Khác"), "hoi": t["hoi"],
                      "tu_khoa": [str(k) for k in t.get("tu_khoa") or []],
                      "muc_do": t.get("muc_do_mac_dinh", "trung_binh"), "can_cu": str(t.get("can_cu") or "")})
    return {"name": s["name"], "description": s["meta"].get("description", ""), "body": s["body"], "items": items}


def draft_templates() -> list[dict]:
    out = []
    for s in list_skills():
        if s["meta"].get("loai") != "soan_thao":
            continue
        out.append({"name": s["name"], "ten_loai": s["meta"].get("ten_loai", s["name"]),
                    "description": s["meta"].get("description", ""),
                    "dan_y": [d.get("tieu_de") for d in s["meta"].get("dan_y") or []],
                    # hình thức (công văn: trả lời / tham gia ý kiến dự thảo); gop_y chỉ có khi mẫu có cấu hình gop_y
                    "che_do": [c for c in s["meta"].get("che_do") or []
                               if isinstance(c, dict) and (c.get("id") != "gop_y" or isinstance(s["meta"].get("gop_y"), dict))]})
    return out


def get_draft_template(name: str) -> dict | None:
    s = next((x for x in list_skills() if x["meta"].get("loai") == "soan_thao" and x["name"] == name), None)
    if not s:
        return None
    the_thuc = ""
    if s["meta"].get("the_thuc"):
        the_thuc = read_md(Path(s["dir"]) / s["meta"]["the_thuc"])
    return {"name": s["name"], "ten_loai": s["meta"].get("ten_loai", s["name"]), "body": s["body"],
            "dan_y": [{"tieu_de": d.get("tieu_de", ""), "huong_dan": d.get("huong_dan", ""),
                       "can_cu": bool(d.get("can_cu", True))} for d in s["meta"].get("dan_y") or []],
            "the_thuc": the_thuc, "trich_yeu_mau": s["meta"].get("trich_yeu_mau", ""),
            "che_do": [str(c.get("id")) for c in s["meta"].get("che_do") or [] if isinstance(c, dict)],
            "gop_y": isinstance(s["meta"].get("gop_y"), dict)}
