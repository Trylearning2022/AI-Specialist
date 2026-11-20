"""Client cho máy chủ embedding và reranker (llama-server --embedding / --reranking).

- Embedding (mặc định bge-m3): biến văn bản thành vector 1024 chiều; vector được chuẩn hóa L2 để dùng cosine.
  Đổi mô hình embedding ⇒ phải lập chỉ mục lại toàn bộ (python tests/run_stack.py --real --reindex
  hoặc python -m tools.reindex).
- Reranker (mặc định bge-reranker-v2-m3, cross-encoder): chấm điểm từng cặp (câu hỏi, đoạn); điểm là logit
  chưa chuẩn hóa (khoảng −11…+11), ngưỡng lọc ở RERANK_THRESHOLD, RERANK_MARGIN.
  Không có reranker (RERANK_URL rỗng) hệ thống vẫn chạy, dùng thứ tự RRF – chất lượng giảm rõ.
[TINH CHỈNH] EMBED_BATCH: số đoạn gửi mỗi lần khi lập chỉ mục (CPU: 8–16; GPU: 32–64).
"""
import logging
import math

import httpx

from .config import get_settings

log = logging.getLogger(__name__)


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Embedder:
    def __init__(self):
        s = get_settings()
        self.url = s.embed_url.rstrip("/")
        self.batch = s.embed_batch
        self.headers = {"Authorization": f"Bearer {s.embed_api_key}"} if s.embed_api_key else {}
        self.client = httpx.AsyncClient(timeout=120)
        self._dim = s.embed_dim or None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            chunk = texts[i:i + self.batch]
            r = await self.client.post(f"{self.url}/v1/embeddings", json={"input": chunk, "model": "embed"},
                                       headers=self.headers)
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend(_norm(d["embedding"]) for d in data)
        return out

    async def dim(self) -> int:
        if not self._dim:
            self._dim = len((await self.embed(["kiểm tra"]))[0])
        return self._dim


class Reranker:
    def __init__(self):
        s = get_settings()
        self.url = (s.rerank_url or "").rstrip("/")
        self.headers = {"Authorization": f"Bearer {s.embed_api_key}"} if s.embed_api_key else {}
        self.client = httpx.AsyncClient(timeout=120)

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    async def rerank(self, query: str, docs: list[str]) -> list[float] | None:
        """Trả điểm theo đúng thứ tự docs; None nếu reranker không khả dụng."""
        if not self.enabled or not docs:
            return None
        try:
            r = await self.client.post(f"{self.url}/v1/rerank",
                                       json={"query": query, "documents": docs, "top_n": len(docs)}, headers=self.headers)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("Reranker không khả dụng, giữ thứ tự gốc: %s", e)
            return None
        scores = [float("-inf")] * len(docs)
        for item in r.json().get("results", []):
            scores[item["index"]] = float(item.get("relevance_score", item.get("score", 0.0)))
        return scores
