#!/usr/bin/env bash
# =====================================================================
# CHUẨN BỊ MÁY CHỦ UBUNTU (Desktop/Server) chạy AI Local, không cần Internet.
#
#   scripts/prepare-host.sh                      # chỉ KIỂM TRA, in khuyến nghị (không cần root, không thay đổi gì)
#   sudo scripts/prepare-host.sh --ap-dung       # kiểm tra + TINH CHỈNH hệ điều hành
#   scripts/prepare-host.sh --env .env           # ghi tham số CPU/RAM khuyến nghị vào .env (giữ bản sao .env.bak)
#
# Tinh chỉnh (--ap-dung): tắt ngủ/ngủ đông (máy Desktop mặc định tự ngủ khi không thao tác), tắt cập nhật tự động
# (không có mạng, gây treo khóa apt), tham số nhân hệ điều hành cho Redis/Qdrant, chế độ CPU hiệu năng.
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")/.."
APPLY=0; ENVF=""
while [ $# -gt 0 ]; do
  case "$1" in --ap-dung) APPLY=1 ;; --env) ENVF=${2:?}; shift ;; *) echo "Tham số không hợp lệ: $1"; exit 2 ;; esac
  shift
done
ok() { echo "  [ĐẠT]  $*"; }; warn() { echo "  [LƯU Ý] $*"; }; bad() { echo "  [KHÔNG ĐẠT] $*"; FAIL=1; }
FAIL=0

echo "== 1. Phần cứng, hệ điều hành"
. /etc/os-release 2>/dev/null || true
echo "  Hệ điều hành: ${PRETTY_NAME:-?} (${VERSION_CODENAME:-?}), nhân $(uname -r)"
[ "$(uname -m)" = x86_64 ] && ok "Kiến trúc x86_64" || bad "Kiến trúc $(uname -m) – ảnh container đóng gói cho x86_64"
LOGICAL=$(nproc --all)
PHYS=$(lscpu -p=Core,Socket 2>/dev/null | grep -v '^#' | sort -u | wc -l); [ "$PHYS" -gt 0 ] || PHYS=$LOGICAL
SOCKETS=$(lscpu -p=Socket 2>/dev/null | grep -v '^#' | sort -u | wc -l)
NUMA=$(lscpu 2>/dev/null | awk -F: '/^NUMA node\(s\)/{gsub(/ /,"",$2);print $2}'); NUMA=${NUMA:-1}
MODEL=$(lscpu 2>/dev/null | awk -F: '/^Model name/{sub(/^ +/,"",$2);print $2;exit}')
echo "  CPU: ${MODEL:-?} – ${SOCKETS} socket, ${PHYS} nhân vật lý, ${LOGICAL} luồng, ${NUMA} vùng NUMA"
grep -qw avx2 /proc/cpuinfo && ok "Hỗ trợ AVX2 (llama.cpp chạy hiệu quả)" || bad "CPU không có AVX2 – mô hình chạy rất chậm"
grep -qw avx512f /proc/cpuinfo && ok "Hỗ trợ AVX-512" || true
RAM_GB=$(awk '/MemTotal/{printf "%d", $2/1024/1024}' /proc/meminfo)
[ "$RAM_GB" -ge 60 ] && ok "RAM ${RAM_GB} GB" || bad "RAM ${RAM_GB} GB – cần tối thiểu 64 GB"
SWAP_GB=$(awk '/SwapTotal/{printf "%d", $2/1024/1024}' /proc/meminfo)
[ "$SWAP_GB" -ge 4 ] && ok "Swap ${SWAP_GB} GB" || warn "Swap ${SWAP_GB} GB – nên có 8–16 GB phòng khi thiếu bộ nhớ tạm thời"
DROOT=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null | grep '^/' | tail -1); DROOT=${DROOT:-/var/lib/docker}
for d in "$DROOT" "$PWD"; do
  p=$d; while [ ! -e "$p" ]; do p=$(dirname "$p"); done
  free=$(df -BG --output=avail "$p" | tail -1 | tr -dc 0-9)
  [ "$free" -ge 150 ] && ok "Dung lượng trống tại $d: ${free} GB" || warn "Dung lượng trống tại $d: ${free} GB – nên ≥ 150 GB (ảnh ~25 GB, mô hình ~30 GB, dữ liệu, sao lưu)"
done

echo "== 2. Phần mềm"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null | tail -1) · Compose $(docker compose version --short 2>/dev/null | tail -1)"
else
  bad "Chưa có Docker Engine + Compose – cài bằng scripts/install-docker-offline.sh"
fi
if snap list docker >/dev/null 2>&1; then bad "Docker bản snap – gỡ (sudo snap remove docker), cài bản .deb"; fi
command -v openssl >/dev/null && ok "openssl" || bad "Thiếu openssl (cần cho init.sh, gen-certs.sh)"
timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes && ok "Đồng bộ thời gian" || \
  warn "Chưa đồng bộ thời gian – đặt máy chủ NTP nội bộ (/etc/systemd/timesyncd.conf: NTP=<ip>); lệch giờ làm hỏng đăng nhập (Keycloak), xác thực chứng thư"

echo "== 3. Trạng thái hệ điều hành"
if systemctl is-enabled sleep.target 2>/dev/null | grep -q masked; then ok "Đã tắt ngủ/ngủ đông"
else warn "Máy có thể tự ngủ khi không thao tác (Ubuntu Desktop) – chạy --ap-dung để tắt"; fi
if systemctl is-enabled unattended-upgrades 2>/dev/null | grep -q enabled; then warn "Cập nhật tự động đang bật – chạy --ap-dung để tắt"; else ok "Cập nhật tự động đã tắt"; fi
oc=$(sysctl -n vm.overcommit_memory 2>/dev/null); [ "$oc" = 1 ] && ok "vm.overcommit_memory=1 (Redis)" || warn "vm.overcommit_memory=$oc – nên đặt 1 (Redis)"
[ "$(systemctl get-default 2>/dev/null)" = graphical.target ] && warn "Đang khởi động vào giao diện đồ họa (tốn ~1–2 GB RAM, CPU nền) – tùy chọn: sudo systemctl set-default multi-user.target"

# ---------------------------------------------------------------- khuyến nghị tham số
# Giải mã token trên CPU bị giới hạn bởi băng thông bộ nhớ, xử lý prompt bị giới hạn bởi số nhân:
# dùng số NHÂN VẬT LÝ (không tính siêu phân luồng); embedding/reranker chạy xen kẽ với mô hình chính trong một
# lượt hỏi đáp nên dành cho chúng một phần nhỏ, không cộng dồn thành quá tải.
MAIN_T=$(( PHYS > 8 ? PHYS - 4 : PHYS ))
AUX_T=$(( PHYS >= 16 ? 4 : 2 ))
if [ "$RAM_GB" -ge 96 ]; then
  MAIN_FILE=qwen3.6-35b-a3b-Q4_K_M.gguf; CTX=65536; PAR=3; SRC=6000; ANS=1000
elif [ "$RAM_GB" -ge 60 ]; then
  MAIN_FILE=qwen3.6-35b-a3b-Q4_K_M.gguf; CTX=32768; PAR=2; SRC=5000; ANS=900
else
  MAIN_FILE=qwen3.5-9b-Q4_K_M.gguf; CTX=16384; PAR=2; SRC=4000; ANS=800
fi
EXTRA="--reasoning-budget 0"; [ "${NUMA:-1}" -gt 1 ] && EXTRA="$EXTRA --numa distribute"
echo "== 4. Tham số khuyến nghị cho .env (${PHYS} nhân vật lý, ${RAM_GB} GB RAM)"
REC=$(cat <<EOF
LLM_MAIN_FILE=$MAIN_FILE
LLM_MAIN_THREADS=$MAIN_T
LLM_MAIN_CTX=$CTX
LLM_MAIN_PARALLEL=$PAR
LLM_MAIN_EXTRA=$EXTRA
LLM_SMALL_URL=http://llm-main:8080/v1
EMBED_THREADS=$AUX_T
RERANK_THREADS=$AUX_T
CTX_BUDGET_SOURCES=$SRC
ANSWER_MAX_TOKENS=$ANS
SEARCH_TOP_K=5
AGENT_YIELD_MAX_S=180
AGENT_WORKERS=1
HARDWARE_PROFILE=cpu
QA_LLM_MODE=auto
EOF
)
echo "$REC" | sed 's/^/  /'
echo "  (Mô hình 35B-A3B là MoE, mỗi token chỉ kích hoạt ~3B tham số: trên CPU sinh nhanh hơn mô hình 9B dày đặc,"
echo "   nên KHÔNG chạy thêm mô hình nhỏ riêng – LLM_SMALL_URL trỏ về mô hình chính.)"

if [ -n "$ENVF" ]; then
  [ -f "$ENVF" ] || { echo "Không thấy $ENVF"; exit 1; }
  cp "$ENVF" "$ENVF.bak"
  while IFS='=' read -r k v; do
    [ -n "$k" ] || continue
    if grep -q "^$k=" "$ENVF"; then
      python3 - "$ENVF" "$k" "$v" <<'PY'
import sys
p, k, v = sys.argv[1:]
lines = open(p, encoding="utf-8").read().split("\n")
val = f'"{v}"' if " " in v else v  # giá trị có dấu cách phải đặt trong ngoặc kép
lines = [f"{k}={val}" if l.startswith(k + "=") else l for l in lines]
open(p, "w", encoding="utf-8").write("\n".join(lines))
PY
    else
      case "$v" in *" "*) echo "$k=\"$v\"" >> "$ENVF" ;; *) echo "$k=$v" >> "$ENVF" ;; esac
    fi
  done <<< "$REC"
  echo "  Đã ghi vào $ENVF (bản cũ: $ENVF.bak)"
fi

if [ "$APPLY" = 1 ]; then
  [ "$(id -u)" = 0 ] || { echo "--ap-dung cần sudo"; exit 1; }
  echo "== 5. Tinh chỉnh hệ điều hành"
  systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null && ok "Tắt ngủ/ngủ đông"
  # Không có mạng: tác vụ cập nhật nền chỉ gây treo khóa apt và nhật ký lỗi
  systemctl disable --now unattended-upgrades apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1; ok "Tắt cập nhật tự động"
  cat > /etc/sysctl.d/90-ai-local.conf <<'EOF'
# AI Local: Redis cần overcommit; Qdrant/Postgres mở nhiều tệp ánh xạ; giảm đẩy bộ nhớ mô hình ra swap
vm.overcommit_memory = 1
vm.max_map_count = 262144
vm.swappiness = 10
net.core.somaxconn = 1024
fs.inotify.max_user_watches = 524288
EOF
  sysctl --system >/dev/null && ok "Tham số nhân hệ điều hành (/etc/sysctl.d/90-ai-local.conf)"
  if [ -d /sys/devices/system/cpu/cpu0/cpufreq ]; then
    cat > /etc/systemd/system/ai-local-cpu-performance.service <<'EOF'
[Unit]
Description=AI Local - CPU governor performance
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > $g 2>/dev/null || true; done'
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload && systemctl enable --now ai-local-cpu-performance.service >/dev/null 2>&1 && ok "CPU chế độ hiệu năng"
  fi
  # Ubuntu Desktop: tắt khóa màn hình tự ngủ ở tầng GNOME cho phiên đăng nhập (nếu có)
  if [ -n "${SUDO_USER:-}" ] && command -v gsettings >/dev/null; then
    sudo -u "$SUDO_USER" dbus-launch gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null && ok "GNOME: không tự ngủ khi cắm điện" || true
  fi
fi
echo
[ "$FAIL" = 0 ] && echo "KẾT LUẬN: máy chủ đáp ứng yêu cầu cơ bản." || echo "KẾT LUẬN: còn mục KHÔNG ĐẠT – xử lý trước khi triển khai."
exit $FAIL
