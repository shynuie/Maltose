#!/usr/bin/env bash
set -euo pipefail

# Local one-minute monitor for the remote KWS training job.
# Usage:
#   ./dev/features/kws_remote_monitor.sh start
#   ./dev/features/kws_remote_monitor.sh status
#   ./dev/features/kws_remote_monitor.sh once
#   ./dev/features/kws_remote_monitor.sh stop

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="$REPO_ROOT/data/kws/monitor"
LOG_FILE="$STATE_DIR/full50.local.log"
PID_FILE="$STATE_DIR/full50.local.pid"
INTERVAL="${KWS_MONITOR_INTERVAL:-60}"
REMOTE="root@180.127.11.167"
PORT="31416"
CONTAINER_ID="72ac13383679"

mkdir -p "$STATE_DIR"

remote_snapshot() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -p "$PORT" "$REMOTE" \
    "echo NOW; date; echo CONTAINER; docker ps --format '{{.ID}} {{.Status}} {{.Names}}' | grep '^$CONTAINER_ID' || true; echo PROGRESS; grep -E 'Start epoch|Evaluate epoch|Training finished|model txt path|Total Recall:' /root/myagent-kws/data/kws/training/marvin-mini/full50.log | tail -5; echo CHECKPOINTS; find /root/myagent-kws/data/kws/training/marvin-mini/work-3ch-split4-full50 -type f -name '*.pth' 2>/dev/null | wc -l; echo ERRORS; printf 'label_errors='; grep -c 'Label index out of bounds' /root/myagent-kws/data/kws/training/marvin-mini/full50.log; printf 'data_errors='; grep -c -E 'Unsupported audio format|Cannot open input file|Traceback' /root/myagent-kws/data/kws/training/marvin-mini/full50.log"
}

once() {
  {
    echo "=== $(date '+%F %T %Z') local_poll ==="
    remote_snapshot
  } 2>&1 | tee -a "$LOG_FILE"
}

run_loop() {
  trap 'exit 0' INT TERM
  while true; do
    once
    sleep "$INTERVAL"
  done
}

case "${1:-status}" in
  once)
    once
    ;;
  run)
    run_loop
    ;;
  start)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
      echo "KWS monitor already running pid=$(<"$PID_FILE")"
    else
      nohup "$0" run >> "$LOG_FILE" 2>&1 &
      echo $! > "$PID_FILE"
      echo "KWS monitor started pid=$! interval=${INTERVAL}s log=$LOG_FILE"
    fi
    ;;
  stop)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
      kill "$(<"$PID_FILE")"
      rm -f "$PID_FILE"
      echo "KWS monitor stopped"
    else
      rm -f "$PID_FILE"
      echo "KWS monitor is not running"
    fi
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
      echo "KWS monitor running pid=$(<"$PID_FILE") interval=${INTERVAL}s"
    else
      echo "KWS monitor stopped"
    fi
    [[ -f "$LOG_FILE" ]] && tail -35 "$LOG_FILE" || true
    ;;
  *)
    echo "Usage: $0 {start|status|once|stop}" >&2
    exit 2
    ;;
esac
