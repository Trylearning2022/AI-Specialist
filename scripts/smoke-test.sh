#!/usr/bin/env bash
# Kiểm tra nhanh sau triển khai: tình trạng dịch vụ và một lượt gọi mô hình qua LiteLLM.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
echo "== Tình trạng dịch vụ"; docker compose exec -T gateway curl -fsS http://localhost:8000/api/health; echo
echo "== Gọi mô hình chính qua LiteLLM"
docker compose exec -T orchestrator python - <<'PY'
import asyncio
from aicommon.llm import AsyncLLM
async def main():
    llm = AsyncLLM()
    print("Mô hình:", await llm.models())
    print("Trả lời:", await llm.chat([{"role": "user", "content": "Trả lời đúng một từ: Xin chào"}], max_tokens=20))
asyncio.run(main())
PY
echo "== Embedding"
docker compose exec -T search python -c "
import asyncio; from aicommon.embed import Embedder
print('Số chiều vector:', asyncio.run(Embedder().dim()))"
