"""search-svc – Luồng A: lập chỉ mục và tìm kiếm ngữ nghĩa lai.

Đây là phân hệ DUY NHẤT trong hệ thống sử dụng chỉ mục vector.

Quy trình một truy vấn (/search):

    câu hỏi ──► mở rộng thuật ngữ (PKT → Phòng Kỹ thuật)
            ├─► nhánh VECTOR DÀY  (embedding bge-m3, cosine)   ─┐  mỗi nhánh lấy SEARCH_CANDIDATES đoạn
            └─► nhánh BM25 THƯA   (âm tiết + cặp âm tiết,       ├─► hợp nhất RRF (Reciprocal Rank Fusion)
                                   có dấu + không dấu)          ─┘
            ──► XẾP HẠNG LẠI (cross-encoder bge-reranker) ──► lọc ngưỡng tuyệt đối + tương đối
            ──► GỘP THEO MỤC + MỞ RỘNG (cả mục nếu ngắn, hoặc đoạn trúng ± lân cận)
            ──► giới hạn số mục/tài liệu ──► SEARCH_TOP_K mục trả cho orchestrator

Vì sao cần cả hai nhánh: vector bắt được câu hỏi diễn đạt khác tài liệu ("máy không lên mạng" ↔ "mất kết nối
mạng nội bộ"); BM25 bắt chính xác số hiệu, mã lỗi, tên riêng ("ipconfig", "45/BC-PKT") mà vector hay bỏ sót.
Reranker đọc đồng thời câu hỏi và đoạn nên chính xác hơn nhiều so với hai nhánh trên, nhưng chậm → chỉ chạy
trên tập ứng viên nhỏ.

Thay đổi cách tách đoạn hoặc cách tạo vector thưa cần LẬP CHỈ MỤC LẠI: python -m tools.reindex
"""
import asyncio
import logging
import re
import uuid
import zlib
from collections import Counter

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient, models as qm

from aicommon.app import create_app
from aicommon.config import get_settings
from aicommon.embed import Embedder, Reranker
from aicommon.markdown import chunk_markdown
from aicommon.resources import glossary_hits
from aicommon.security import UserCtx, allowed_units, current_user, require, require_service
from aicommon.text import estimate_tokens, tokens, unaccent

log = logging.getLogger("search")
app = create_app("search")
S = get_settings()
NS = uuid.UUID("6f1c2a52-6a8e-4c39-9d7e-3b1f0b8f9a10")  # không gian tên sinh mã điểm ổn định theo doc_id:chunk_no

LOAI_TEN = {"quyet_dinh": "Quyết định", "huong_dan": "Hướng dẫn", "quy_dinh": "Quy định", "bao_cao": "Báo cáo",
            "ke_hoach": "Kế hoạch", "cong_van": "Công văn", "su_co": "Sự cố kỹ thuật",
            "tai_lieu_ky_thuat": "Tài liệu kỹ thuật", "bien_ban": "Biên bản", "to_trinh": "Tờ trình"}


class State:
    qdrant: AsyncQdrantClient | None = None
    embedder: Embedder | None = None
    reranker: Reranker | None = None
    ready: bool = False
    lock = asyncio.Lock()


st = State()


def qdrant() -> AsyncQdrantClient:
    if st.qdrant is None:
        if S.qdrant_url.startswith(":memory:") or S.qdrant_url.startswith("path:"):
            loc = S.qdrant_url
            st.qdrant = AsyncQdrantClient(location=":memory:") if loc == ":memory:" else AsyncQdrantClient(path=loc[5:])
        else:
            st.qdrant = AsyncQdrantClient(url=S.qdrant_url, api_key=S.qdrant_api_key, timeout=60)
    return st.qdrant


async def ensure_collection():
    """Tạo collection (vector dày "dense" + vector thưa "bm25" có IDF) và chỉ mục payload phục vụ lọc quyền."""
    if st.ready:
        return
    async with st.lock:
        if st.ready:
            return
        st.embedder = st.embedder or Embedder()
        st.reranker = st.reranker or Reranker()
        q = qdrant()
        if not await q.collection_exists(S.qdrant_collection):
            dim = await st.embedder.dim()
            await q.create_collection(
                S.qdrant_collection,
                vectors_config={"dense": qm.VectorParams(size=dim, distance=qm.Distance.COSINE)},
                sparse_vectors_config={"bm25": qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
            )
            for field, schema in (("doc_id", qm.PayloadSchemaType.KEYWORD), ("don_vi", qm.PayloadSchemaType.KEYWORD),
                                  ("loai", qm.PayloadSchemaType.KEYWORD), ("do_mat", qm.PayloadSchemaType.INTEGER),
                                  ("trang_thai", qm.PayloadSchemaType.KEYWORD), ("nguon", qm.PayloadSchemaType.KEYWORD),
                                  ("ngay_ban_hanh", qm.PayloadSchemaType.KEYWORD),
                                  ("section_id", qm.PayloadSchemaType.KEYWORD), ("nhom", qm.PayloadSchemaType.KEYWORD)):
                try:
                    await q.create_payload_index(S.qdrant_collection, field, schema)
                except Exception:  # chế độ local không hỗ trợ chỉ mục payload
                    pass
            log.info("Đã tạo collection %s (dim=%s)", S.qdrant_collection, dim)
        st.ready = True


# ---------- Vector thưa kiểu BM25 ----------
# Qdrant tính IDF (modifier=IDF); phần TF chuẩn hóa theo độ dài được tính sẵn ở đây.
# Thuật ngữ gồm: âm tiết có dấu, cặp âm tiết liền kề (bắt cụm "sự cố", "mạng nội bộ"),
# và âm tiết KHÔNG DẤU tiền tố "~" (người dùng gõ thiếu dấu vẫn khớp).
# [TINH CHỈNH] K1 (bão hòa tần suất), B (mức phạt đoạn dài), AVG (số thuật ngữ trung bình mỗi đoạn).
K1, B, AVG = 1.2, 0.75, 450.0
W_UNACCENT = 0.5   # trọng số thuật ngữ không dấu trong truy vấn (thấp hơn để ưu tiên khớp đúng dấu)


def _terms(text: str) -> list[str]:
    t = tokens(text)
    u = [unaccent(x) for x in t]
    return t + [f"{a}_{b}" for a, b in zip(t, t[1:])] + [f"~{x}" for x in u] + [f"~{a}_{b}" for a, b in zip(u, u[1:])]


def _h(term: str) -> int:
    return zlib.crc32(term.encode()) & 0x7FFFFFFF


def sparse_doc(text: str) -> qm.SparseVector:
    terms = _terms(text)
    tf, n = Counter(terms), len(terms) or 1
    val: dict[int, float] = {}
    for term, f in tf.items():
        h = _h(term)
        val[h] = val.get(h, 0) + f * (K1 + 1) / (f + K1 * (1 - B + B * n / AVG))
    keys = sorted(val)
    return qm.SparseVector(indices=keys, values=[val[k] for k in keys])


def sparse_query(text: str) -> qm.SparseVector:
    w: dict[int, float] = {}
    for t in _terms(text):
        h = _h(t)
        w[h] = max(w.get(h, 0), W_UNACCENT if t.startswith("~") else 1.0)
    keys = sorted(w)
    return qm.SparseVector(indices=keys, values=[w[k] for k in keys])


# ---------- Mở rộng truy vấn bằng từ điển thuật ngữ ----------
_ABBR = re.compile(r"^[A-ZĐ0-9\-]{2,10}$")


def expand_query(query: str) -> str:
    """Thêm nghĩa đầy đủ của chữ viết tắt có trong từ điển (glossary/thuat-ngu.md) vào truy vấn.

    Chỉ mở rộng thuật ngữ dạng viết tắt (chữ HOA, ≤ 10 ký tự) để không làm loãng câu hỏi.
    Ví dụ: "PKT kiến nghị gì" → "PKT kiến nghị gì (Phòng Kỹ thuật)".
    """
    if not S.search_expand_glossary:
        return query
    extra = [d for t, d in glossary_hits(query) if _ABBR.match(t.strip()) and unaccent(d).lower() not in
             unaccent(query).lower()]
    return f"{query} ({'; '.join(extra)})" if extra else query


def embed_text(c: dict, title: str, so_hieu: str = "", loai: str = "") -> str:
    """Văn bản dùng để sinh vector / xếp hạng: [loại số hiệu] breadcrumb + nội dung (contextual chunk header)."""
    head = " ".join(x for x in (LOAI_TEN.get(loai, ""), so_hieu) if x)
    crumb = c.get("breadcrumb") or title
    return f"{head + ' – ' if head else ''}{crumb}\n{c['text']}"


# ---------- API ----------
class IndexReq(BaseModel):
    doc_id: str
    markdown: str
    title: str = ""
    meta: dict = Field(default_factory=dict)
    nguon: str = "A"  # A: tài liệu tham khảo; B: bản sao chỉ đọc của kho chuẩn


def _acl_filter(user: UserCtx, f: dict | None = None) -> qm.Filter:
    """Bộ lọc quyền + bộ lọc người dùng chọn. Áp dụng TRƯỚC khi tìm (không lọc sau) – tài liệu ngoài quyền
    không bao giờ vào ứng viên, kể cả khi điểm cao."""
    must = [qm.FieldCondition(key="do_mat", range=qm.Range(lte=user.effective_clearance))]
    units = allowed_units(user)
    if units is not None:
        must.append(qm.FieldCondition(key="don_vi", match=qm.MatchAny(any=units)))
    f = f or {}
    if f.get("loai"):
        loai = f["loai"] if isinstance(f["loai"], list) else [f["loai"]]
        must.append(qm.FieldCondition(key="loai", match=qm.MatchAny(any=loai)))
    if f.get("doc_ids"):
        must.append(qm.FieldCondition(key="doc_id", match=qm.MatchAny(any=f["doc_ids"])))
    if f.get("trang_thai"):
        must.append(qm.FieldCondition(key="trang_thai", match=qm.MatchValue(value=f["trang_thai"])))
    if f.get("nguon"):
        must.append(qm.FieldCondition(key="nguon", match=qm.MatchValue(value=f["nguon"])))
    if f.get("nhom"):  # "van_ban_di": chỉ văn bản đơn vị đã ban hành (tiền lệ tham mưu)
        nhom = f["nhom"] if isinstance(f["nhom"], list) else [f["nhom"]]
        must.append(qm.FieldCondition(key="nhom", match=qm.MatchAny(any=nhom)))
    if f.get("bo_nhom"):  # loại trừ nhóm (ví dụ hỏi đáp thông thường không lấy văn bản đi làm căn cứ)
        bo = f["bo_nhom"] if isinstance(f["bo_nhom"], list) else [f["bo_nhom"]]
        return qm.Filter(must=must, must_not=[qm.FieldCondition(key="nhom", match=qm.MatchAny(any=bo))])
    if f.get("tu_ngay") or f.get("den_ngay"):
        must.append(qm.FieldCondition(key="ngay_ban_hanh", range=qm.DatetimeRange(
            gte=f.get("tu_ngay") or None, lte=f.get("den_ngay") or None)))
    return qm.Filter(must=must)


@app.post("/index")
async def index(req: IndexReq, user: UserCtx = Depends(require("reviewer", "admin")),
                _svc: str = Depends(require_service("ingest", "tools"))):
    """Tách đoạn, sinh vector, ghi đè toàn bộ điểm của tài liệu (lập chỉ mục lại an toàn, idempotent)."""
    await ensure_collection()
    chunks = chunk_markdown(req.doc_id, req.markdown, title=req.title)
    if not chunks:
        raise HTTPException(400, "Tài liệu rỗng sau khi tách đoạn")
    m = req.meta
    texts = [embed_text(c, req.title, m.get("so_hieu", ""), m.get("loai", "")) for c in chunks]
    vecs = await st.embedder.embed(texts)
    don_vi = m.get("don_vi") or ["chung"]
    base = {"doc_id": req.doc_id, "title": req.title, "nguon": req.nguon,
            "do_mat": int(m.get("do_mat", 0) or 0),
            "don_vi": don_vi if isinstance(don_vi, list) else [don_vi],
            "loai": m.get("loai", "khac"), "so_hieu": m.get("so_hieu", ""),
            "ngay_ban_hanh": str(m.get("ngay_ban_hanh") or "") or None,
            "trang_thai": m.get("trang_thai", "con_hieu_luc"), "phien_ban": str(m.get("phien_ban", "1")),
            "nhom": m.get("nhom") or "tai_lieu", "co_quan": str(m.get("co_quan_ban_hanh") or "")}
    if base["ngay_ban_hanh"] and len(base["ngay_ban_hanh"]) == 10:
        base["ngay_ban_hanh"] += "T00:00:00Z"
    points = [qm.PointStruct(id=str(uuid.uuid5(NS, f"{req.doc_id}:{c['chunk_no']}")),
                             vector={"dense": v, "bm25": sparse_doc(t)},
                             payload={**base, **c, "tokens": estimate_tokens(c["text"])})
              for c, v, t in zip(chunks, vecs, texts)]
    q = qdrant()
    await q.delete(S.qdrant_collection, points_selector=qm.FilterSelector(filter=qm.Filter(
        must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=req.doc_id))])))
    for i in range(0, len(points), 64):
        await q.upsert(S.qdrant_collection, points=points[i:i + 64])
    return {"doc_id": req.doc_id, "chunks": len(points)}


@app.delete("/docs/{doc_id}")
async def delete_doc(doc_id: str, user: UserCtx = Depends(require("reviewer", "admin")),
                     _svc: str = Depends(require_service("ingest", "tools"))):
    await ensure_collection()
    await qdrant().delete(S.qdrant_collection, points_selector=qm.FilterSelector(filter=qm.Filter(
        must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))])))
    return {"doc_id": doc_id, "deleted": True}


class SearchReq(BaseModel):
    query: str
    top_k: int | None = None          # số MỤC trả về (mặc định SEARCH_TOP_K)
    filters: dict = Field(default_factory=dict)
    rerank: bool = True
    candidates: int | None = None     # ứng viên mỗi nhánh (mặc định SEARCH_CANDIDATES)
    expand: bool = True               # gộp theo mục + mở rộng đoạn lân cận
    max_per_doc: int | None = None    # số mục tối đa mỗi tài liệu (mặc định SEARCH_MAX_PER_DOC; 0 = không giới hạn)
    explain: bool = False             # trả thêm thứ hạng từng nhánh để chẩn đoán (tools/search_debug.py)


async def _section_chunks(doc_id: str, section_id: str) -> list[dict]:
    """Mọi đoạn của một mục, theo thứ tự trong tài liệu."""
    pts, _ = await qdrant().scroll(S.qdrant_collection, limit=200, with_payload=True, with_vectors=False,
                                   scroll_filter=qm.Filter(must=[
                                       qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id)),
                                       qm.FieldCondition(key="section_id", match=qm.MatchValue(value=section_id))]))
    return sorted((p.payload for p in pts), key=lambda c: c.get("chunk_no", 0))


async def _expand(groups: list[list[dict]]) -> list[dict]:
    """Gộp các đoạn trúng cùng mục thành một nguồn; mở rộng thành cả mục (nếu ngắn) hoặc thêm đoạn lân cận.

    Khắc phục lỗi thường gặp "câu trả lời thiếu": quy trình 8 bước bị tách làm 2 đoạn, chỉ đoạn đầu được chọn.
    """
    out = []
    for hits in groups:
        top = hits[0]
        try:
            allc = await _section_chunks(top["doc_id"], top["section_id"])
        except Exception as e:  # không chặn câu trả lời vì lỗi mở rộng
            log.warning("Không mở rộng được mục %s: %s", top["section_id"], e)
            allc = []
        if not allc:
            allc = sorted(hits, key=lambda c: c.get("chunk_no", 0))
        total = sum(c.get("tokens") or estimate_tokens(c["text"]) for c in allc)
        if total <= S.search_section_max_tokens:
            keep = allc                                           # cả mục
        else:
            hit_nos = {h.get("chunk_no") for h in hits}
            idx = {i for i, c in enumerate(allc) if c.get("chunk_no") in hit_nos}
            win = {j for i in idx for j in range(i - S.search_neighbors, i + S.search_neighbors + 1)
                   if 0 <= j < len(allc)}
            keep = [allc[j] for j in sorted(win)] or hits         # đoạn trúng ± lân cận
        text = "\n\n".join(c["text"] for c in keep)
        out.append({**top, "text": text, "parts": [c.get("chunk_no") for c in keep],
                    "expanded": len(keep) > len(hits), "hit_count": len(hits)})
    return out


@app.post("/search")
async def search(req: SearchReq, user: UserCtx = Depends(current_user)):
    await ensure_collection()
    top_k = req.top_k or S.search_top_k
    n = req.candidates or S.search_candidates
    q_ext = expand_query(req.query)
    qv = (await st.embedder.embed([q_ext]))[0]
    flt = _acl_filter(user, req.filters)
    res = await qdrant().query_points(
        S.qdrant_collection,
        prefetch=[qm.Prefetch(query=qv, using="dense", limit=n, filter=flt),
                  qm.Prefetch(query=sparse_query(q_ext), using="bm25", limit=n, filter=flt)],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF), limit=n,
        query_filter=flt, with_payload=True)
    hits = [{**p.payload, "score": p.score} for p in res.points]
    explain: dict = {}
    if req.explain:  # thứ hạng từng nhánh – chỉ phục vụ chẩn đoán, tốn thêm 2 truy vấn
        d = await qdrant().query_points(S.qdrant_collection, query=qv, using="dense", limit=n, query_filter=flt,
                                        with_payload=["section_id", "chunk_no"])
        sp = await qdrant().query_points(S.qdrant_collection, query=sparse_query(q_ext), using="bm25", limit=n,
                                         query_filter=flt, with_payload=["section_id", "chunk_no"])
        explain = {"query_expanded": q_ext,
                   "dense": [(p.payload["section_id"], p.payload.get("chunk_no"), round(p.score, 4)) for p in d.points],
                   "bm25": [(p.payload["section_id"], p.payload.get("chunk_no"), round(p.score, 3)) for p in sp.points]}

    reranked = False
    if req.rerank and hits:
        docs = [embed_text(h, h.get("title", ""), h.get("so_hieu", ""), h.get("loai", "")) for h in hits]
        scores = await st.reranker.rerank(q_ext, docs)
        if scores:
            reranked = True
            for h, sc in zip(hits, scores):
                h["rerank_score"] = sc
            hits.sort(key=lambda x: -x["rerank_score"])
            if req.explain:
                explain["rerank_all"] = [(h["section_id"], h.get("chunk_no"), round(h["rerank_score"], 3)) for h in hits]
            best = hits[0]["rerank_score"]
            floor = max(S.rerank_threshold, best - S.rerank_margin) if S.rerank_margin > 0 else S.rerank_threshold
            hits = [h for h in hits if h["rerank_score"] >= floor]

    # Gộp theo mục (giữ thứ tự điểm), giới hạn số mục mỗi tài liệu
    groups: dict[tuple, list[dict]] = {}
    per_doc: Counter = Counter()
    cap = S.search_max_per_doc if req.max_per_doc is None else req.max_per_doc
    for h in hits:
        key = (h["doc_id"], h["section_id"])
        if key not in groups:
            if len(groups) >= top_k:
                continue
            if cap and per_doc[h["doc_id"]] >= cap:
                continue
            groups[key] = []
            per_doc[h["doc_id"]] += 1
        groups[key].append(h)
    results = await _expand(list(groups.values())) if req.expand else [g[0] for g in groups.values()]
    out = {"query": req.query, "reranked": reranked, "results": results}
    if req.explain:
        out["explain"] = explain
    return out


@app.post("/documents")
async def find_documents(req: SearchReq, user: UserCtx = Depends(current_user)):
    """Chế độ “Tìm tài liệu”: gom kết quả theo văn bản, không sinh câu trả lời."""
    req.top_k, req.rerank, req.expand, req.max_per_doc = 60, False, False, 0
    r = await search(req, user)
    docs: dict[str, dict] = {}
    for h in r["results"]:
        d = docs.setdefault(h["doc_id"], {"doc_id": h["doc_id"], "title": h["title"], "so_hieu": h.get("so_hieu"),
                                          "loai": h.get("loai"), "nguon": h.get("nguon"), "score": h["score"],
                                          "doan": []})
        if len(d["doan"]) < 3:
            d["doan"].append({"section_id": h["section_id"], "breadcrumb": h["breadcrumb"], "text": h["text"][:400]})
    return {"results": sorted(docs.values(), key=lambda d: -d["score"])[:20]}


@app.get("/stats")
async def stats(user: UserCtx = Depends(require("admin", "reviewer"))):
    await ensure_collection()
    info = await qdrant().get_collection(S.qdrant_collection)
    return {"collection": S.qdrant_collection, "points": info.points_count, "status": str(info.status)}
