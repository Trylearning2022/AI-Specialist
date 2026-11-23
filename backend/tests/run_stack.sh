#!/usr/bin/env bash
# Chạy toàn bộ dịch vụ backend trên máy phát triển (không Docker) để kiểm thử tích hợp.
# Yêu cầu: PostgreSQL 16, Redis, Python venv đã cài requirements. Mô hình được thay bằng tests/mock_llm.py.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(cd .. && pwd)
PY=${PY:-/opt/venv/bin/python}
RUN=${RUN:-/tmp/ai-local-test}
mkdir -p "$RUN"/{logs,data,kb} && chmod 777 "$RUN/logs"

# PostgreSQL
if [ ! -d "$RUN/pg" ]; then
  mkdir -p "$RUN/pg" && chown postgres "$RUN/pg"
  su postgres -c "/usr/lib/postgresql/16/bin/initdb -D $RUN/pg -A trust -U ai" >/dev/null
fi
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D $RUN/pg -o '-p 55432 -k /tmp' -l $RUN/logs/pg.log start" >/dev/null || true
sleep 2
psql -h /tmp -p 55432 -U ai -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='ai'" | grep -q 1 || \
  psql -h /tmp -p 55432 -U ai -d postgres -c "CREATE DATABASE ai" >/dev/null
redis-server --port 56379 --daemonize yes --save "" --appendonly no >/dev/null

export DATABASE_URL="postgresql+psycopg://ai@localhost:55432/ai" REDIS_URL="redis://localhost:56379/0"
export QDRANT_URL="path:$RUN/qdrant" INTERNAL_SECRET="test-secret" AUTH_MODE=dev DEV_AUTH_ALLOWED=true
export LLM_BASE_URL="http://localhost:9000/v1" EMBED_URL="http://localhost:9000" RERANK_URL="http://localhost:9000"
export DOCLING_URL="" DATA_DIR="$RUN/data" KB_DIR="$RUN/kb" SKILLS_DIR="$ROOT/skills" PROMPTS_DIR="$ROOT/prompts"
export GLOSSARY_FILE="$ROOT/glossary/thuat-ngu.md" SUPPORT_DIR="$ROOT/support" DEV_USERS_FILE="$ROOT/config/users.dev.yaml"
export ORCHESTRATOR_URL=http://localhost:8101 SEARCH_URL=http://localhost:8102 EXACT_URL=http://localhost:8103
export INGEST_URL=http://localhost:8104 SUMMARY_URL=http://localhost:8105 SUPPORT_URL=http://localhost:8106
export AUDIT_URL=http://localhost:8107 AGENT_URL=http://localhost:8108 QA_INTERVAL_MIN=0 QA_LLM_MODE=on AGENT_YIELD_MAX_S=5
export SYSTEM_MAX_CLEARANCE=1 RERANK_THRESHOLD=-0.5 RATE_LIMIT_CHAT_PER_MIN=500 RATE_LIMIT_PER_MIN=5000

start() { nohup $PY -m uvicorn "$1" --port "$2" --log-level warning ${4:-} > "$RUN/logs/$3.log" 2>&1 & echo $! >> "$RUN/pids"; }
: > "$RUN/pids"
start tests.mock_llm:app 9000 mock
start services.gateway.app:app 8100 gateway
start services.orchestrator.app:app 8101 orchestrator
start services.search.app:app 8102 search
start services.exact.app:app 8103 exact "--workers 2"
start services.ingest.app:app 8104 ingest
start services.summary.app:app 8105 summary
start services.support.app:app 8106 support
start services.audit.app:app 8107 audit
start services.agent.app:app 8108 agent
nohup $PY -m celery -A aicommon.queue worker -Q ingest,summary -c 2 -n main@%h --loglevel=WARNING > "$RUN/logs/worker.log" 2>&1 &
echo $! >> "$RUN/pids"
nohup $PY -m celery -A aicommon.queue worker -Q agent -c 1 -n agent@%h --loglevel=WARNING > "$RUN/logs/agent-worker.log" 2>&1 &
echo $! >> "$RUN/pids"
sleep 6
curl -s localhost:8100/api/health; echo
