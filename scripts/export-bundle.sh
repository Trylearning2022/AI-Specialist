#!/usr/bin/env bash
# =====================================================================
# CHẠY TRÊN MÁY TẢI (vùng Internet): đóng gói toàn bộ phần mềm để chuyển vào mạng nội bộ.
#   scripts/export-bundle.sh ./bundle [chung-thu.crt khoa.key]
# Kết quả: bundle/images/*.tar (ảnh container), bundle/images.lock (digest), bundle/wheels (gói Python),
#          bundle/source (mã nguồn hệ thống), manifest.yaml, SHA256SUMS, manifest.yaml.p7s (nếu có khóa ký).
# Mô hình được chuẩn bị riêng bằng scripts/download-models.sh.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=$(realpath -m "${1:-./bundle}"); CERT=${2:-}; KEY=${3:-}
mkdir -p "$OUT/images" "$OUT/scan" "$OUT/sbom"
[ -f .env ] || cp .env.example .env
set -a; . ./.env; set +a

echo "== Xây dựng ảnh của hệ thống"
docker compose build gateway portal

echo "== Tải ảnh thành phần mã nguồn mở và ghim digest"
IMAGES="$IMG_POSTGRES $IMG_REDIS $IMG_QDRANT $IMG_KEYCLOAK $IMG_LLAMACPP $IMG_LITELLM $IMG_DOCLING $IMG_NGINX $IMG_GITEA $IMG_PROMETHEUS"
[ "${WITH_GPU:-0}" = "1" ] && IMAGES="$IMAGES $IMG_VLLM ghcr.io/ggml-org/llama.cpp:server-cuda"
: > "$OUT/images.lock"
for img in $IMAGES; do
  docker pull "$img"
  digest=$(docker inspect --format '{{index .RepoDigests 0}}' "$img" 2>/dev/null || echo "$img")
  echo "$img=$digest" >> "$OUT/images.lock"
done
for img in $IMAGES "$IMG_APP" "$IMG_PORTAL"; do
  f="$OUT/images/$(echo "$img" | tr '/:@' '___').tar"
  docker save "$img" -o "$f"
  if command -v trivy >/dev/null; then trivy image --input "$f" --severity HIGH,CRITICAL --format json -o "$OUT/scan/$(basename "$f").json" || true; fi
  if command -v syft >/dev/null; then syft "docker-archive:$f" -o spdx-json > "$OUT/sbom/$(basename "$f").spdx.json" || true; fi
done

echo "== Gói Python (để xây dựng lại ảnh trong mạng nội bộ khi cần)"
pip download -r backend/requirements.txt -d "$OUT/wheels" --only-binary=:all: \
  --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --python-version 3.12 --implementation cp -q

echo "== Mã nguồn hệ thống"
mkdir -p "$OUT/source"
git archive --format=tar.gz -o "$OUT/source/ai-local.tar.gz" HEAD 2>/dev/null || \
  tar --exclude=./bundle --exclude=./models --exclude=node_modules --exclude=.env -czf "$OUT/source/ai-local.tar.gz" .

if command -v clamscan >/dev/null; then clamscan -r --infected --log="$OUT/scan/clamav.log" "$OUT/images" "$OUT/wheels" || true; fi

echo "== Manifest, SHA-256, chữ ký"
{
  echo "dot_chuyen_giao: CG-$(date +%Y%m%d-%H%M)"
  echo "ngay_tai: $(date -I)"
  echo "can_bo_tai: ${USER:-}"
  echo "anh_container:"; sed 's/^/  - /' "$OUT/images.lock"
  echo "so_goi_python: $(ls "$OUT/wheels" | wc -l)"
} > "$OUT/manifest.yaml"
(cd "$OUT" && find . -type f ! -name SHA256SUMS ! -name '*.p7s' -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
if [ -n "$CERT" ] && [ -n "$KEY" ]; then
  openssl cms -sign -binary -in "$OUT/SHA256SUMS" -signer "$CERT" -inkey "$KEY" -outform DER -out "$OUT/SHA256SUMS.p7s"
  echo "Đã ký SHA256SUMS bằng $CERT"
fi
echo "Hoàn thành: $OUT ($(du -sh "$OUT" | cut -f1))"
