#!/usr/bin/env bash
# Dừng các tiến trình do run_stack.sh khởi chạy; RESET=1 để xóa dữ liệu kiểm thử.
RUN=${RUN:-/tmp/ai-local-test}
[ -f "$RUN/pids" ] && xargs -r kill < "$RUN/pids" 2>/dev/null
sleep 1
redis-cli -p 56379 shutdown nosave >/dev/null 2>&1 || true
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D $RUN/pg stop -m fast" >/dev/null 2>&1 || true
[ "${RESET:-0}" = "1" ] && rm -rf "$RUN"
exit 0
