#!/usr/bin/env bash
# =====================================================================
# CHẠY TẠI TRẠM KIỂM TRA / MÁY CHỦ NỘI BỘ: xác thực chữ ký, đối chiếu băm, nạp ảnh container.
#   scripts/import-bundle.sh /mnt/chuyen-giao/bundle [ca-noibo.crt] [models-dir]
# =====================================================================
set -euo pipefail
B=$(realpath "$1"); CA=${2:-}; MODELS=${3:-}
cd "$(dirname "$0")/.."
if [ -f "$B/SHA256SUMS.p7s" ]; then
  [ -n "$CA" ] || { echo "Gói có chữ ký: cần chứng thư CA để xác thực"; exit 1; }
  openssl cms -verify -binary -inform DER -in "$B/SHA256SUMS.p7s" -content "$B/SHA256SUMS" -CAfile "$CA" -out /dev/null
  echo "Chữ ký hợp lệ."
else
  echo "CẢNH BÁO: gói không có chữ ký số."
fi
(cd "$B" && sha256sum --quiet -c SHA256SUMS) && echo "Toàn vẹn tệp: đạt."
if command -v clamscan >/dev/null; then clamscan -r --infected "$B" || { echo "Phát hiện mã độc – dừng."; exit 1; }; fi
for f in "$B"/images/*.tar; do docker load -i "$f"; done
# Trường hợp có Harbor: gắn thẻ và đẩy lên kho ảnh nội bộ
if [ -n "${HARBOR:-}" ]; then
  while IFS='=' read -r img _; do
    docker tag "$img" "$HARBOR/$img" && docker push "$HARBOR/$img"
  done < "$B/images.lock"
fi
if [ -n "$MODELS" ]; then
  (cd "$MODELS" && sha256sum -c SHA256SUMS) && cp -n "$MODELS"/*.gguf models/ && echo "Đã sao chép mô hình vào models/."
fi
echo "Hoàn thành. Tiếp theo: scripts/init.sh"
