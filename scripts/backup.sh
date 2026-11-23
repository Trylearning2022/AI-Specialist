#!/usr/bin/env bash
# Sao lưu: CSDL PostgreSQL, snapshot Qdrant, kho văn bản chuẩn (Git), dữ liệu tài liệu. Đặt lịch bằng cron.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib-env.sh; load_env .env
D=${1:-./backups}/$(date +%Y%m%d-%H%M%S); mkdir -p "$D"
docker compose exec -T postgres pg_dumpall -U ai | gzip > "$D/postgres.sql.gz"
docker compose exec -T search python - <<PY > "$D/qdrant-snapshot.txt"
import os, httpx
r = httpx.post(f"http://qdrant:6333/collections/tai_lieu/snapshots", headers={"api-key": os.environ["QDRANT_API_KEY"]}, timeout=600)
print(r.text)
PY
docker compose exec -T exact sh -c 'cd /kb && git bundle create - --all' > "$D/kb.bundle"
docker compose run --rm --no-deps -v "$(realpath "$D")":/out ingest sh -c 'tar czf /out/appdata.tgz -C /data .'
(cd "$D" && sha256sum * > SHA256SUMS)
echo "Đã sao lưu vào $D. Snapshot Qdrant nằm trong volume qdrant (xem qdrant-snapshot.txt). Mã hóa, chuyển bản sao lưu ra kho lưu trữ theo quy định."
