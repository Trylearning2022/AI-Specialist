#!/usr/bin/env bash
# =====================================================================
# CHẠY TRÊN MÁY TẢI (vùng Internet): đóng gói toàn bộ phần mềm để chuyển vào mạng nội bộ.
#   scripts/export-bundle.sh ./bundle [chung-thu.crt khoa.key]
#   UBUNTU_CODENAME=noble scripts/export-bundle.sh ./bundle    # kèm bộ cài Docker .deb cho máy chủ Ubuntu 24.04 không Internet
# Kết quả: bundle/images/*.tar (ảnh container), bundle/images.lock (digest), bundle/wheels (gói Python),
#          bundle/source (mã nguồn hệ thống), manifest.yaml, SHA256SUMS, manifest.yaml.p7s (nếu có khóa ký).
# Mô hình được chuẩn bị riêng bằng scripts/download-models.sh.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=$(realpath -m "${1:-./bundle}"); CERT=${2:-}; KEY=${3:-}
mkdir -p "$OUT/images" "$OUT/scan" "$OUT/sbom"
[ -f .env ] || cp .env.example .env
. scripts/lib-env.sh; load_env .env
# Thẻ ảnh luôn lấy theo .env.example của bản đang đóng gói: .env trên máy tải có thể còn từ lần đóng gói trước
# (thẻ phiên bản cũ) – khi đó ảnh mới bị gắn thẻ cũ, máy chủ sau nâng cấp không tìm thấy ảnh bản mới.
# Biến môi trường của shell được Docker Compose ưu tiên hơn .env.
export IMG_APP=$(awk -F= '/^IMG_APP=/{print $2}' .env.example) IMG_PORTAL=$(awk -F= '/^IMG_PORTAL=/{print $2}' .env.example)
echo "== Phiên bản đóng gói: ${IMG_APP##*:}"

echo "== Xây dựng ảnh của hệ thống"
# LibreOffice trong ảnh để nạp tệp .doc/.xls cũ (kho văn bản đã ban hành); đặt INSTALL_LIBREOFFICE=0 để bỏ (ảnh nhẹ hơn ~400 MB)
export INSTALL_LIBREOFFICE=${INSTALL_LIBREOFFICE:-1}
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

if [ -n "${UBUNTU_CODENAME:-}" ]; then
  echo "== Bộ cài Docker Engine cho Ubuntu $UBUNTU_CODENAME (máy chủ không Internet)"
  scripts/download-docker-debs.sh "$UBUNTU_CODENAME" "$OUT/docker-debs"
fi

echo "== Mã nguồn hệ thống (cây thư mục làm việc hiện tại, không phải commit cũ)"
mkdir -p "$OUT/source"
# Đóng gói đúng mã nguồn đang dùng để build ảnh. Không dùng "git archive HEAD": lệnh đó chỉ lấy
# commit cuối, các thay đổi chưa commit (file mới như prepare-host.sh, upgrade.sh...) sẽ bị bỏ sót.
# Danh sách chặn cứng: tài liệu nội bộ, bí mật, khóa, mô hình, bản sao lưu, môi trường ảo.
LIST="$(mktemp)"; trap 'rm -f "$LIST"' EXIT
deny_re='^(documents|bundle|models|out-models|llama\.cpp|backups|\.venv[^/]*|\.test-run[^/]*|\.git)(/|$)|(^|/)(node_modules|__pycache__|\.pytest_cache|\.ruff_cache)(/|$)|^config/pki/[^/]*\.(crt|key|csr|srl|cnf|pem|p12|pfx)$|^config/prometheus/llm_key$|^frontend/dist(/|$)|^backend/wheels/[^.]'
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # File đã theo dõi + file mới chưa bị .gitignore loại; bỏ file đã xóa khỏi đĩa
  git ls-files -z -co --exclude-standard | while IFS= read -r -d '' f; do
    [ -f "$f" ] && printf '%s\0' "$f"
  done > "$LIST.all"
else
  find . -type f -printf '%P\0' > "$LIST.all"
fi
tr '\0' '\n' < "$LIST.all" \
  | grep -Ev "$deny_re" \
  | grep -Ev '(^|/)\.env($|\.)' > "$LIST.txt" || true
grep -qx '.env.example' "$LIST.txt" || echo ".env.example" >> "$LIST.txt"
tr '\n' '\0' < "$LIST.txt" > "$LIST"
rm -f "$LIST.all" "$LIST.txt"
tar --null -T "$LIST" -czf "$OUT/source/ai-local.tar.gz"

# Kiểm tra gói mã nguồn khớp phiên bản ảnh vừa build
SRC_LIST="$(tar tzf "$OUT/source/ai-local.tar.gz")"
for f in scripts/upgrade.sh scripts/prepare-host.sh scripts/lib-env.sh .env.example docker-compose.yml; do
  echo "$SRC_LIST" | grep -qx "$f" || { echo "LỖI: gói mã nguồn thiếu $f" >&2; exit 1; }
done
if echo "$SRC_LIST" | grep -Eq '^(documents/|\.env$|config/pki/.*\.key$)'; then
  echo "LỖI: gói mã nguồn chứa tài liệu nội bộ hoặc khóa bí mật" >&2; exit 1
fi
SRC_IMG="$(tar xzf "$OUT/source/ai-local.tar.gz" -O .env.example | sed -n 's/^IMG_APP=//p' | tr -d '"'"'"'\r')"
[ "$SRC_IMG" = "$IMG_APP" ] || { echo "LỖI: .env.example trong gói ($SRC_IMG) khác ảnh đã build ($IMG_APP)" >&2; exit 1; }
echo "   $(echo "$SRC_LIST" | wc -l) file, $(du -h "$OUT/source/ai-local.tar.gz" | cut -f1), phiên bản $SRC_IMG"

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
