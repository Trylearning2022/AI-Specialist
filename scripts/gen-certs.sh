#!/usr/bin/env bash
# Sinh CA nội bộ và chứng thư máy chủ cho Nginx (dùng khi chưa có chứng thư do CA của đơn vị cấp).
# Khuyến nghị vận hành: thay bằng chứng thư do hạ tầng PKI của đơn vị cấp (đặt server.crt, server.key, ca.crt vào config/pki).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${1:-$(grep -E '^AI_HOST=' .env 2>/dev/null | cut -d= -f2 || echo ai.noibo.local)}
D=config/pki
mkdir -p "$D"
if [ ! -f "$D/ca.key" ]; then
  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes -keyout "$D/ca.key" -out "$D/ca.crt" \
    -subj "/C=VN/O=Don vi/CN=AI Local Internal CA"
fi
openssl req -newkey rsa:3072 -sha256 -nodes -keyout "$D/server.key" -out "$D/server.csr" -subj "/C=VN/O=Don vi/CN=$HOST"
printf "subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature,keyEncipherment\n" "$HOST" > "$D/ext.cnf"
openssl x509 -req -in "$D/server.csr" -CA "$D/ca.crt" -CAkey "$D/ca.key" -CAcreateserial -days 825 -sha256 \
  -extfile "$D/ext.cnf" -out "$D/server.crt"
rm -f "$D/server.csr" "$D/ext.cnf"
chmod 600 "$D"/*.key
echo "Đã sinh chứng thư cho $HOST. Cài $D/ca.crt vào kho tin cậy của máy trạm."
