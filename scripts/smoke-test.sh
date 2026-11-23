#!/usr/bin/env bash
# Kiểm tra nhanh sau triển khai: tình trạng dịch vụ và một lượt gọi mô hình qua LiteLLM.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib-env.sh; load_env .env
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
echo "== Đo tốc độ mô hình chính (llama.cpp, gọi trực tiếp trong mạng mô hình)"
# prompt ~1 500 token (đo tốc độ xử lý ngữ cảnh – quyết định thời gian chờ khi hỏi đáp có nhiều nguồn)
# + sinh 128 token (đo tốc độ sinh). Không dùng bộ đệm prompt để số liệu phản ánh lượt hỏi mới.
docker compose exec -T -e CTX_BUDGET_SOURCES="${CTX_BUDGET_SOURCES:-6000}" litellm python - <<'PY'
import json, os, time, urllib.request
base = os.environ.get("LLM_MAIN_URL", "http://llm-main:8080/v1").rsplit("/v1", 1)[0]
txt = ("Điều 9. Thông tin bí mật nhà nước khi truyền đưa, lưu giữ trên phương tiện điện tử phải được mã hóa "
       "bằng mật mã cơ yếu. ") * 45
body = {"prompt": f"Tóm tắt đoạn sau trong ba câu:\n{txt}\nTóm tắt:", "n_predict": 128, "cache_prompt": False,
        "temperature": 0.1}
req = urllib.request.Request(base + "/completion", data=json.dumps(body).encode(), method="POST",
                             headers={"Content-Type": "application/json",
                                      "Authorization": "Bearer " + os.environ.get("LLM_BACKEND_KEY", "")})
t0 = time.time()
r = json.load(urllib.request.urlopen(req, timeout=900))
t = r.get("timings", {})
print(f"Xử lý ngữ cảnh: {t.get('prompt_n', 0)} token, {t.get('prompt_per_second', 0):.1f} token/giây")
print(f"Sinh văn bản : {t.get('predicted_n', 0)} token, {t.get('predicted_per_second', 0):.1f} token/giây")
print(f"Tổng thời gian: {time.time() - t0:.1f} giây")
pp = t.get("prompt_per_second", 0) or 1
print(f"Ước tính chờ trước khi trả lời với CTX_BUDGET_SOURCES={os.environ.get('CTX_BUDGET_SOURCES', '?')}: "
      f"~{int((int(os.environ.get('CTX_BUDGET_SOURCES', '6000')) + 1500) / pp)} giây")
PY
