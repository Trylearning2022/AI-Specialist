#!/usr/bin/env bash
# =====================================================================
# NÂNG CẤP AI LOCAL TRÊN MÁY CHỦ (không Internet), chạy tại thư mục cài đặt hiện tại (/opt/ai-local):
#
#   scripts/upgrade.sh ~/chuyen-giao/bundle                       # gói phần mềm mới (không ký)
#   scripts/upgrade.sh ~/chuyen-giao/bundle ca-noibo.crt          # gói có ký số
#   scripts/upgrade.sh ~/chuyen-giao/bundle "" ~/chuyen-giao/gguf # kèm mô hình mới
#   KHONG_SAO_LUU=1 scripts/upgrade.sh …                          # bỏ bước sao lưu (KHÔNG khuyến nghị)
#
# Trình tự: (1) kiểm tra gói → (2) sao lưu dữ liệu + lưu bản mã nguồn cũ → (3) cập nhật mã nguồn, GIỮ NGUYÊN .env,
# config/pki, models, backups → (4) bổ sung tham số mới vào .env, chuyển thẻ ảnh sang bản mới → (5) nạp ảnh, mô hình
# → (6) khởi động lại, chờ sẵn sàng → (7) kiểm tra nhanh. Lỗi ở bước nào thì dừng ở bước đó; cách quay lại bản cũ
# được in ra cuối script (và trong docs/trien-khai-ubuntu-offline.md, mục 6).
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
B=$(realpath "${1:?Thiếu thư mục gói (bundle)}"); CA=${2:-}; MODELS=${3:-}
STAMP=$(date +%Y%m%d-%H%M%S)
[ -f .env ] || { echo "Không thấy .env – đây không phải thư mục đã cài đặt. Cài mới: xem docs/trien-khai-ubuntu-offline.md"; exit 1; }
[ -f "$B/source/ai-local.tar.gz" ] || { echo "Gói không có source/ai-local.tar.gz"; exit 1; }
. scripts/lib-env.sh; load_env .env
OLD_APP=$IMG_APP; OLD_PORTAL=$IMG_PORTAL
NEW_APP=$( (tar xzf "$B/source/ai-local.tar.gz" -O ./.env.example 2>/dev/null || tar xzf "$B/source/ai-local.tar.gz" -O .env.example 2>/dev/null) \
  | awk -F= '/^IMG_APP=/{print $2}' || true)
echo "== Nâng cấp: ${OLD_APP##*:} → ${NEW_APP##*:}"

echo "== 1. Kiểm tra gói (chữ ký, mã băm)"
if [ -f "$B/SHA256SUMS.p7s" ]; then
  [ -n "$CA" ] || { echo "Gói có chữ ký: cần chứng thư CA (tham số 2)"; exit 1; }
  openssl cms -verify -binary -inform DER -in "$B/SHA256SUMS.p7s" -content "$B/SHA256SUMS" -CAfile "$CA" -out /dev/null
  echo "Chữ ký hợp lệ."
else
  echo "CẢNH BÁO: gói không có chữ ký số."
fi
(cd "$B" && sha256sum --quiet -c SHA256SUMS) && echo "Mã băm: đạt."

echo "== 2. Sao lưu"
mkdir -p ../ai-local-ban-cu
SRC_BAK=$(realpath ../ai-local-ban-cu)/ai-local-${OLD_APP##*:}-$STAMP.tgz
tar --exclude=./models --exclude=./backups -czf "$SRC_BAK" .          # mã nguồn + .env + chứng thư hiện tại
echo "Bản mã nguồn cũ: $SRC_BAK"
if [ "${KHONG_SAO_LUU:-0}" != 1 ]; then
  # cần hệ thống đang chạy (sao lưu qua các container); nếu hệ thống đang dừng: khởi động lại trước, hoặc KHONG_SAO_LUU=1
  scripts/backup.sh ./backups
else
  echo "Bỏ qua sao lưu dữ liệu (KHONG_SAO_LUU=1)."
fi

echo "== 3. Cập nhật mã nguồn (giữ .env, config/pki, models, backups)"
# Mục giữ nguyên của máy chủ. --anchored + hai dạng tên ("./x" của tar, "x" của git archive) để chỉ loại đúng thư mục gốc
KEEP=(.env config/pki models backups config/prometheus/llm_key)
EXC=(); for k in "${KEEP[@]}"; do EXC+=(--exclude="./$k" --exclude="$k"); done
tar xzf "$B/source/ai-local.tar.gz" -C "$ROOT" --anchored "${EXC[@]}"
find scripts -name '*.sh' -exec sed -i 's/\r$//' {} + && chmod +x scripts/*.sh   # phòng tệp xuống dòng kiểu Windows

echo "== 4. Bổ sung tham số mới vào .env, chuyển thẻ ảnh sang bản mới"
cp .env ".env.truoc-nang-cap-$STAMP"
python3 - .env .env.example <<'PY'
import re, sys
env_p, ex_p = sys.argv[1], sys.argv[2]
cur = open(env_p, encoding="utf-8").read().split("\n")
keys = {m.group(1) for l in cur if (m := re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", l))}
out, added = [], []
for l in cur:  # giá trị có dấu cách mà thiếu ngoặc kép (lỗi bản ≤ 1.4.1) → thêm ngoặc kép
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", l)
    if m and " " in m.group(2).split(" #")[0].strip() and not m.group(2).startswith(('"', "'")):
        l = f'{m.group(1)}="{m.group(2).strip()}"'
    if m and m.group(1) in ("IMG_APP", "IMG_PORTAL"):
        new = next((x for x in open(ex_p, encoding="utf-8") if x.startswith(m.group(1) + "=")), None)
        if new:
            l = new.rstrip("\n")
    out.append(l)
for l in open(ex_p, encoding="utf-8").read().split("\n"):
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", l)
    if m and m.group(1) not in keys:
        added.append(l)
if added:
    out += ["", "# ---- Bổ sung khi nâng cấp (giá trị mặc định của bản mới) ----"] + added
open(env_p, "w", encoding="utf-8").write("\n".join(out))
print("Tham số mới:", ", ".join(a.split("=")[0] for a in added) or "(không có)")
PY
echo "Bản .env trước nâng cấp: .env.truoc-nang-cap-$STAMP"

echo "== 5. Nạp ảnh container, mô hình"
scripts/import-bundle.sh "$B" "$CA" "$MODELS"

echo "== 6. Khởi động lại theo bản mới"
scripts/init.sh   # sinh khóa cho tham số bí mật mới (nếu có), kiểm tra mô hình, khởi động, chờ sẵn sàng

echo "== 7. Kiểm tra nhanh"
scripts/smoke-test.sh || echo "CẢNH BÁO: kiểm tra nhanh chưa đạt – xem nhật ký trước khi bàn giao."
docker compose ps

load_env .env
cat <<EOF

Hoàn thành nâng cấp lên ${IMG_APP##*:}.
Nếu cần QUAY LẠI bản ${OLD_APP##*:}:
  cd $ROOT && docker compose down
  tar xzf $SRC_BAK -C $ROOT            # khôi phục mã nguồn, .env, chứng thư của bản cũ
  docker compose up -d                  # ảnh bản cũ ($OLD_APP) vẫn còn trên máy
  # Chỉ khi dữ liệu bị ảnh hưởng: khôi phục CSDL từ bản sao lưu mới nhất trong ./backups (mục 6.4 tài liệu triển khai)
Sau khi vận hành ổn định vài ngày, xóa ảnh bản cũ để giải phóng dung lượng: docker image rm $OLD_APP $OLD_PORTAL
EOF
