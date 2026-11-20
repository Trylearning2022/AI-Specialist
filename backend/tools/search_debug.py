"""Chẩn đoán tìm kiếm Luồng A: xem vì sao một đoạn được hoặc không được chọn làm nguồn.

    python -m tools.search_debug "Máy trạm mất kết nối mạng thì xử lý thế nào?"
    python -m tools.search_debug "PKT kiến nghị gì" --user canbo --no-rerank

In ra theo từng tầng của quy trình tìm kiếm:
  1. Truy vấn sau khi mở rộng thuật ngữ.
  2. Thứ hạng nhánh vector (dense) và nhánh từ khóa (BM25) – mục nào xuất hiện ở nhánh nào.
  3. Điểm xếp hạng lại (reranker) của mọi ứng viên; dấu ✗ = bị loại do dưới ngưỡng.
  4. Các mục cuối cùng đưa cho mô hình (sau gộp theo mục, mở rộng đoạn lân cận) và độ dài.
Cách đọc kết quả, cách chỉnh tham số: docs/tinh-chinh-truy-xuat.md (mục 4).
Yêu cầu: hệ thống đang chạy (run_stack.py hoặc docker compose), chế độ xác thực dev.
"""
import argparse
import os
import sys

import httpx

GW = os.getenv("GW", "http://127.0.0.1:8100")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("query")
    ap.add_argument("--user", default="canbo")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--top-k", type=int)
    ap.add_argument("--candidates", type=int)
    a = ap.parse_args()
    body = {"query": a.query, "explain": True, "rerank": not a.no_rerank}
    if a.top_k:
        body["top_k"] = a.top_k
    if a.candidates:
        body["candidates"] = a.candidates
    r = httpx.post(f"{GW}/api/search/search", json=body, headers={"Authorization": f"Bearer dev-{a.user}"}, timeout=300)
    r.raise_for_status()
    d = r.json()
    e = d.get("explain", {})
    print(f"Truy vấn       : {d['query']}")
    print(f"Sau mở rộng    : {e.get('query_expanded')}")
    print("\n== Nhánh vector (dense) – thứ hạng, mục, đoạn, điểm cosine ==")
    for i, (sid, no, sc) in enumerate(e.get("dense", [])[:10], 1):
        print(f"  {i:>2}. {sc:>7}  {sid}  #{no}")
    print("\n== Nhánh từ khóa (BM25) – thứ hạng, mục, đoạn, điểm ==")
    for i, (sid, no, sc) in enumerate(e.get("bm25", [])[:10], 1):
        print(f"  {i:>2}. {sc:>7}  {sid}  #{no}")
    if e.get("rerank_all"):
        kept = {(x["section_id"]) for x in d["results"]}
        print("\n== Xếp hạng lại (reranker, logit) – ✓ được chọn, ✗ bị loại/trùng mục ==")
        for sid, no, sc in e["rerank_all"]:
            print(f"  {'✓' if sid in kept else '✗'} {sc:>7}  {sid}  #{no}")
    print(f"\n== Nguồn đưa cho mô hình ({len(d['results'])} mục; reranked={d['reranked']}) ==")
    for i, x in enumerate(d["results"], 1):
        sc = x.get("rerank_score", x.get("score"))
        print(f"  [{i}] {x['breadcrumb']}")
        print(f"      điểm {sc:.3f} · đoạn {x.get('parts')} · {'mở rộng' if x.get('expanded') else 'nguyên đoạn trúng'}"
              f" · ~{len(x['text']) // 3} token")
        print("      " + x["text"][:160].replace("\n", " ") + ("…" if len(x["text"]) > 160 else ""))


if __name__ == "__main__":
    main()
