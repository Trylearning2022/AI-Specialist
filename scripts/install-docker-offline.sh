#!/usr/bin/env bash
# =====================================================================
# CHẠY TRÊN MÁY CHỦ UBUNTU (không Internet), quyền root:
#   sudo scripts/install-docker-offline.sh /duong-dan/bundle/docker-debs/noble [/data/docker]
#
#   - Kiểm tra SHA-256 bộ cài (do scripts/download-docker-debs.sh tạo).
#   - Chỉ cài gói CHƯA có hoặc cũ hơn (không hạ cấp gói hệ điều hành đã cập nhật).
#   - Cấu hình Docker: xoay vòng nhật ký, live-restore; tùy chọn đặt thư mục dữ liệu (tham số 2) trên ổ lớn.
#   - Thêm người dùng gọi sudo vào nhóm docker.
# =====================================================================
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Chạy với sudo"; exit 1; }
DEBS=$(realpath "${1:?Thiếu thư mục bộ cài .deb}"); DATA_ROOT=${2:-}

. /etc/os-release
if [ "$(basename "$DEBS")" != "${VERSION_CODENAME:-}" ]; then
  echo "CẢNH BÁO: bộ cài dành cho '$(basename "$DEBS")', máy chủ là '${VERSION_CODENAME:-?}' ($PRETTY_NAME)."
  read -r -p "Tiếp tục? [y/N] " a; [ "$a" = y ] || exit 1
fi
if snap list docker >/dev/null 2>&1; then
  echo "Phát hiện Docker cài qua snap – gỡ trước để tránh xung đột: sudo snap remove docker"; exit 1
fi

echo "== Kiểm tra toàn vẹn"
(cd "$DEBS" && sha256sum --quiet -c SHA256SUMS) && echo "Đạt."

echo "== Chọn gói cần cài"
sel=()
for f in "$DEBS"/*.deb; do
  p=$(dpkg-deb -f "$f" Package); v=$(dpkg-deb -f "$f" Version)
  if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed"; then
    iv=$(dpkg-query -W -f='${Version}' "$p")
    if dpkg --compare-versions "$iv" ge "$v"; then continue; fi
  fi
  sel+=("$f")
done
echo "Cài ${#sel[@]} gói."
if [ ${#sel[@]} -gt 0 ]; then
  # --no-download: không thử truy cập kho mạng; mọi phụ thuộc lấy từ các tệp .deb đã chọn
  apt-get install -y --no-download "${sel[@]}" || dpkg -i "${sel[@]}"
fi

echo "== Cấu hình Docker"
mkdir -p /etc/docker
python3 - "$DATA_ROOT" <<'EOF'
import json, os, sys
p = "/etc/docker/daemon.json"
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg.setdefault("log-driver", "json-file")
cfg.setdefault("log-opts", {"max-size": "50m", "max-file": "5"})
cfg["live-restore"] = True
if sys.argv[1]:
    cfg["data-root"] = sys.argv[1]
json.dump(cfg, open(p, "w"), indent=2)
print(open(p).read())
EOF
[ -n "$DATA_ROOT" ] && mkdir -p "$DATA_ROOT"
systemctl enable --now containerd docker
systemctl restart docker
if [ -n "${SUDO_USER:-}" ]; then usermod -aG docker "$SUDO_USER" && echo "Đã thêm $SUDO_USER vào nhóm docker (đăng xuất, đăng nhập lại để có hiệu lực)."; fi
docker version --format 'Docker Engine {{.Server.Version}}'
docker compose version
echo "Hoàn thành."
