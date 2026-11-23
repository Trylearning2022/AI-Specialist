#!/usr/bin/env bash
# =====================================================================
# CHẠY TRÊN MÁY TẢI (vùng Internet, đã có Docker): tải bộ cài Docker Engine + Compose dạng .deb
# (kèm thư viện phụ thuộc) cho máy chủ Ubuntu KHÔNG kết nối Internet.
#
#   scripts/download-docker-debs.sh noble  ./bundle/docker-debs     # Ubuntu 24.04
#   scripts/download-docker-debs.sh jammy  ./bundle/docker-debs     # Ubuntu 22.04
#
# Tên phiên bản (codename) phải TRÙNG máy chủ đích: chạy `lsb_release -cs` trên máy chủ để biết.
# Cách làm: dựng container Ubuntu cùng phiên bản, thêm kho chính thức download.docker.com,
# `apt-get install --download-only` để lấy đủ gói và phụ thuộc, sau đó lập SHA256SUMS.
# =====================================================================
set -euo pipefail
CODENAME=${1:?"Thiếu tên phiên bản Ubuntu: noble (24.04) | jammy (22.04)"}
case "$CODENAME" in
  noble) IMG=ubuntu:24.04 ;;
  jammy) IMG=ubuntu:22.04 ;;
  *) echo "Chỉ hỗ trợ noble (24.04), jammy (22.04)"; exit 1 ;;
esac
OUT=$(realpath -m "${2:-./bundle/docker-debs}")/$CODENAME
mkdir -p "$OUT"
rm -f "$OUT"/*.deb

echo "== Tải Docker Engine cho Ubuntu $CODENAME vào $OUT"
docker run --rm -e CODENAME="$CODENAME" -v "$OUT:/out" "$IMG" bash -euc '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl >/dev/null
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  rm -f /var/cache/apt/archives/*.deb
  apt-get install -y -qq --download-only docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  cp /var/cache/apt/archives/*.deb /out/
  cp /etc/apt/keyrings/docker.asc /out/docker-apt-key.asc
'
(cd "$OUT" && sha256sum ./*.deb docker-apt-key.asc > SHA256SUMS)
echo "== Hoàn thành: $(ls "$OUT"/*.deb | wc -l) gói, $(du -sh "$OUT" | cut -f1)"
ls "$OUT" | grep -E '^(docker-ce|docker-ce-cli|containerd.io|docker-compose-plugin|docker-buildx-plugin)_' || true
