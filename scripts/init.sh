#!/usr/bin/env bash
# Khởi tạo lần đầu: sinh khóa bí mật, chứng thư, kiểm tra mô hình, khởi động hệ thống.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
rand() { openssl rand -base64 33 | tr -d '/+=' | cut -c1-32; }
while grep -q "__SINH_TU_DONG__" .env; do
  sed -i "0,/__SINH_TU_DONG__/s//$(rand)/" .env
done
set -a; . ./.env; set +a
[ -f config/pki/server.crt ] || scripts/gen-certs.sh "$AI_HOST"
printf "%s" "$LLM_BACKEND_KEY" > config/prometheus/llm_key && chmod 600 config/prometheus/llm_key

missing=0
for f in "$LLM_MAIN_FILE" "$EMBED_FILE"; do
  [ -f "models/$f" ] || { echo "THIẾU mô hình: models/$f"; missing=1; }
done
if [ -n "${RERANK_URL:-}" ] && [ ! -f "models/$RERANK_FILE" ]; then echo "THIẾU mô hình reranker: models/$RERANK_FILE (hoặc để trống RERANK_URL)"; missing=1; fi
PROFILES=""
if [ "${LLM_SMALL_URL:-}" = "http://llm-small:8080/v1" ]; then
  [ -f "models/$LLM_SMALL_FILE" ] || { echo "THIẾU mô hình nhỏ: models/$LLM_SMALL_FILE"; missing=1; }
  PROFILES="--profile mo-hinh-nho"
fi
[ $missing -eq 0 ] || { echo "Đặt tệp mô hình vào thư mục models/ (xem models/README.md) rồi chạy lại."; exit 1; }

RR=""; [ -z "${RERANK_URL:-}" ] && RR="--scale rerank=0"
docker compose $PROFILES up -d $RR
echo "Đang chờ hệ thống sẵn sàng (lần đầu có thể mất vài phút do nạp mô hình)…"
for i in $(seq 1 120); do
  if docker compose exec -T gateway curl -fsS http://localhost:8000/api/health 2>/dev/null | grep -q '"status":"ok"'; then
    echo "Hệ thống đã sẵn sàng: ${AI_PUBLIC_URL}"
    echo "Tài khoản quản trị ban đầu: quantri / mật khẩu tạm KC_INIT_ADMIN_PASSWORD trong .env (bắt buộc đổi, cài OTP khi đăng nhập lần đầu)."
    echo "Nạp dữ liệu mẫu (tùy chọn): docker compose --profile tools run --rm tools"
    exit 0
  fi
  sleep 5
done
echo "Hết thời gian chờ – kiểm tra: docker compose ps; docker compose logs --tail=50 <dịch vụ>"; exit 1
