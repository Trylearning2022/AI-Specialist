"""Giám sát hệ thống: tổng hợp số liệu từ các luồng telemetry (aicommon/telemetry.py) theo khung thời gian.

    GET /monitor/overview?hours=24   chỉ số chính, chuỗi thời gian, theo luồng/tác vụ/dịch vụ, người dùng, tài nguyên
    GET /monitor/logs                nhật ký hệ thống tập trung (lọc mức, dịch vụ, từ khóa; xem trực tiếp)
    GET /monitor/health              tình trạng từng dịch vụ và máy chủ mô hình (độ trễ)

Toàn bộ tính toán trong bộ nhớ trên tối đa TELEMETRY_KEEP bản ghi mỗi luồng – đủ nhanh cho quy mô đơn vị
(hàng chục nghìn lượt/ngày). Không cần cơ sở dữ liệu chuỗi thời gian riêng.
"""
import os
import shutil
import statistics
import time
from collections import Counter, defaultdict

import httpx
from fastapi import APIRouter, Depends

from aicommon.config import get_settings
from aicommon.security import UserCtx, require
from aicommon.telemetry import read, read_last

S = get_settings()
router = APIRouter(prefix="/monitor")


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    v = sorted(vals)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def avg(vals) -> float | None:
    vals = [x for x in vals if x is not None]
    return round(statistics.fmean(vals), 1) if vals else None


def bucketize(rows: list[dict], since: float, until: float, n: int = 24) -> list[dict]:
    """Chia khoảng thời gian thành n ô; trả mỗi ô: thời điểm bắt đầu và danh sách bản ghi."""
    size = (until - since) / n
    out = [{"t": since + i * size, "rows": []} for i in range(n)]
    for r in rows:
        i = min(n - 1, max(0, int((r["ts"] - since) / size)))
        out[i]["rows"].append(r)
    return out


def system_resources() -> dict:
    """CPU, RAM, ổ đĩa của máy chủ chạy dịch vụ giám sát (psutil nếu có; nếu không, đọc /proc trên Linux)."""
    out: dict = {"cpu_count": os.cpu_count()}
    try:
        import psutil
        out["cpu_pct"] = psutil.cpu_percent(interval=0.3)
        vm = psutil.virtual_memory()
        out.update(ram_total_gb=round(vm.total / 2**30, 1), ram_used_gb=round((vm.total - vm.available) / 2**30, 1),
                   ram_pct=vm.percent)
    except Exception:
        try:
            mem = dict(ln.split(":", 1) for ln in open("/proc/meminfo", encoding="utf-8"))
            tot = int(mem["MemTotal"].split()[0]) / 2**20
            av = int(mem["MemAvailable"].split()[0]) / 2**20
            out.update(ram_total_gb=round(tot, 1), ram_used_gb=round(tot - av, 1), ram_pct=round(100 * (tot - av) / tot, 1))
        except Exception:
            pass
    if hasattr(os, "getloadavg"):
        try:
            la = os.getloadavg()
            out["load"] = [round(x, 2) for x in la]
            out.setdefault("cpu_pct", round(min(100.0, 100 * la[0] / (os.cpu_count() or 1)), 1))
        except OSError:
            pass
    try:
        du = shutil.disk_usage(S.data_dir if os.path.exists(S.data_dir) else "/")
        out.update(disk_total_gb=round(du.total / 2**30, 1), disk_used_gb=round(du.used / 2**30, 1),
                   disk_pct=round(100 * du.used / du.total, 1))
    except OSError:
        pass
    return out


@router.get("/overview")
def overview(hours: float = 24, user: UserCtx = Depends(require("admin", "reviewer"))):
    hours = max(0.25, min(hours, 24 * 30))
    until = time.time()
    since = until - hours * 3600
    chat, llm, http, task = (read(s, since, until) for s in ("tel:chat", "tel:llm", "tel:http", "tel:task"))
    ms = [c["ms"] for c in chat if c.get("ms") is not None]
    first = [c["first_ms"] for c in chat if c.get("first_ms")]
    users = Counter(c.get("user", "") for c in chat)

    # ---- chỉ số chính
    kpi = {
        "cau_hoi": len(chat), "nguoi_dung": len([u for u in users if u]),
        "tg_tb_s": round(avg(ms) / 1000, 1) if ms else None, "tg_p95_s": round(pct(ms, .95) / 1000, 1) if ms else None,
        "tg_chu_dau_s": round(avg(first) / 1000, 1) if first else None,
        "ty_le_kiem_chung": round(100 * sum(1 for c in chat if c.get("verified")) / len(chat), 1) if chat else None,
        "ty_le_khong_can_cu": round(100 * sum(1 for c in chat if c.get("refused")) / len(chat), 1) if chat else None,
        "hoi_lai": sum(1 for c in chat if c.get("clarify")), "chan_attt": sum(1 for c in chat if c.get("guard")),
        "goi_mo_hinh": len(llm), "loi_mo_hinh": sum(1 for x in llm if not x.get("ok")),
        "toc_do_sinh": avg(x.get("tps") for x in llm if x.get("tps")),
        "token_vao": sum(x.get("tin") or 0 for x in llm), "token_ra": sum(x.get("tout") or 0 for x in llm),
        "yeu_cau_http": len(http), "loi_5xx": sum(1 for x in http if (x.get("status") or 0) >= 500),
        "tac_vu": len(task), "tac_vu_loi": sum(1 for x in task if x.get("status") == "loi"),
    }

    # ---- chuỗi thời gian (24 ô)
    series = []
    bc, bl, bh = (bucketize(x, since, until) for x in (chat, llm, http))
    for c, l_, h in zip(bc, bl, bh):
        cm = [r["ms"] for r in c["rows"] if r.get("ms") is not None]
        series.append({"t": c["t"], "cau_hoi": len(c["rows"]), "nguoi_dung": len({r.get("user") for r in c["rows"]}),
                       "tg_tb_s": round(avg(cm) / 1000, 1) if cm else None,
                       "tg_p95_s": round(pct(cm, .95) / 1000, 1) if cm else None,
                       "toc_do_sinh": avg(r.get("tps") for r in l_["rows"] if r.get("tps")),
                       "goi_mo_hinh": len(l_["rows"]), "loi": sum(1 for r in h["rows"] if (r.get("status") or 0) >= 500)
                       + sum(1 for r in l_["rows"] if not r.get("ok"))})

    # ---- theo luồng trả lời
    by_route = defaultdict(list)
    for c in chat:
        by_route[c.get("route", "")].append(c)
    routes = [{"route": k, "so_luot": len(v), "tg_tb_s": round(avg([x["ms"] for x in v]) / 1000, 1),
               "tg_p95_s": round(pct([x["ms"] for x in v], .95) / 1000, 1),
               "ty_le_kiem_chung": round(100 * sum(1 for x in v if x.get("verified")) / len(v), 1)}
              for k, v in by_route.items() if v]
    routes.sort(key=lambda x: -x["so_luot"])

    # ---- theo tác vụ mô hình
    by_task = defaultdict(list)
    for x in llm:
        by_task[x.get("task") or "khac"].append(x)
    llm_tasks = [{"task": k, "so_luot": len(v), "tg_tb_s": round(avg([x["ms"] for x in v]) / 1000, 1),
                  "token_vao_tb": round(avg([x.get("tin") or 0 for x in v]) or 0),
                  "token_ra_tb": round(avg([x.get("tout") or 0 for x in v]) or 0),
                  "toc_do_sinh": avg(x.get("tps") for x in v if x.get("tps")), "loi": sum(1 for x in v if not x.get("ok"))}
                 for k, v in by_task.items()]
    llm_tasks.sort(key=lambda x: -x["so_luot"] * (x["tg_tb_s"] or 0))

    # ---- theo dịch vụ
    by_svc = defaultdict(list)
    for x in http:
        by_svc[x.get("service", "")].append(x)
    services = [{"service": k, "so_yeu_cau": len(v), "p95_ms": pct([x["ms"] for x in v], .95),
                 "loi_4xx": sum(1 for x in v if 400 <= (x.get("status") or 0) < 500),
                 "loi_5xx": sum(1 for x in v if (x.get("status") or 0) >= 500)} for k, v in by_svc.items()]
    services.sort(key=lambda x: -x["so_yeu_cau"])

    # ---- người dùng
    per_user = defaultdict(list)
    for c in chat:
        per_user[c.get("user", "")].append(c)
    top_users = [{"user": u, "cau_hoi": len(v), "tg_tb_s": round(avg([x["ms"] for x in v]) / 1000, 1),
                  "lan_cuoi": max(x["ts"] for x in v), "luong": Counter(x.get("route") for x in v).most_common(3),
                  "khong_can_cu": sum(1 for x in v if x.get("refused"))} for u, v in per_user.items() if u]
    top_users.sort(key=lambda x: -x["cau_hoi"])

    # ---- tác vụ dài
    tasks = defaultdict(lambda: {"so_luot": 0, "xong": 0, "loi": 0, "ms": []})
    for x in task:
        d = tasks[x.get("kind", "")]
        d["so_luot"] += 1
        d["xong"] += x.get("status") == "xong"
        d["loi"] += x.get("status") == "loi"
        d["ms"].append(x.get("ms") or 0)
    task_rows = [{"kind": k, "so_luot": v["so_luot"], "xong": v["xong"], "loi": v["loi"],
                  "tg_tb_phut": round(avg(v["ms"]) / 60000, 1) if v["ms"] else None} for k, v in tasks.items()]
    return {"since": since, "until": until, "hours": hours, "kpi": kpi, "series": series, "routes": routes,
            "llm_tasks": llm_tasks, "services": services, "users": top_users[:50], "tasks": task_rows,
            "system": system_resources()}


@router.get("/health")
def health(user: UserCtx = Depends(require("admin", "reviewer"))):
    targets = {"gateway": None, "orchestrator": S.orchestrator_url, "search": S.search_url, "exact": S.exact_url,
               "ingest": S.ingest_url, "summary": S.summary_url, "support": S.support_url, "agent": S.agent_url}
    out = []
    with httpx.Client(timeout=5) as c:
        for name, base in targets.items():
            if not base:
                continue
            t0 = time.perf_counter()
            try:
                ok = c.get(f"{base}/health").status_code == 200
                out.append({"name": name, "ok": ok, "ms": round((time.perf_counter() - t0) * 1000, 1)})
            except httpx.HTTPError as e:
                out.append({"name": name, "ok": False, "error": type(e).__name__})
        t0 = time.perf_counter()
        try:
            r = c.get(f"{S.llm_base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {S.llm_api_key}"})
            out.append({"name": "mo-hinh", "ok": r.status_code == 200, "ms": round((time.perf_counter() - t0) * 1000, 1),
                        "models": [m.get("id") for m in (r.json().get("data") or [])] if r.status_code == 200 else []})
        except Exception as e:
            out.append({"name": "mo-hinh", "ok": False, "error": type(e).__name__})
    return {"services": out, "system": system_resources()}


@router.get("/logs")
def logs(level: str = "", service: str = "", q: str = "", after: str = "", limit: int = 300,
         user: UserCtx = Depends(require("admin"))):
    """Nhật ký hệ thống, mới nhất trước. `after` = mã bản ghi cuối đã có (xem trực tiếp: chỉ lấy bản ghi mới hơn)."""
    rows = read_last("tel:logs", 3000) if not after else [
        r for r in read("tel:logs", int(after.split("-")[0]) / 1000) if r["id"] != after][::-1]
    lv = {x.strip().upper() for x in level.split(",") if x.strip()}
    ql = q.lower()
    out = [r for r in rows if (not lv or r.get("level") in lv) and (not service or r.get("service") == service)
           and (not ql or ql in (r.get("msg", "") + " " + r.get("logger", "") + " " + r.get("event", "")).lower())]
    stats = Counter(r.get("level") for r in rows)
    return {"rows": out[:min(limit, 1000)], "stats": dict(stats),
            "services": sorted({r.get("service", "") for r in rows if r.get("service")})}
