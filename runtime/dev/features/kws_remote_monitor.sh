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
JOB_KEY="${KWS_JOB_KEY:-raw-clean35-speed}"
LOG_FILE="$STATE_DIR/${JOB_KEY}.local.log"
PID_FILE="$STATE_DIR/${JOB_KEY}.local.pid"
ALERT_FILE="$STATE_DIR/${JOB_KEY}.alerted"
INTERVAL="${KWS_MONITOR_INTERVAL:-60}"
REMOTE="root@180.127.11.167"
PORT="31416"
REMOTE_LOG="/root/myagent-kws/data/kws/training/marvin-mini/real-tts1000-raw-clean35-speed.log"
REMOTE_WORK="/root/myagent-kws/data/kws/training/marvin-mini/work-3ch-split4-real-tts1000-raw-clean35-speed"

mkdir -p "$STATE_DIR"

remote_snapshot() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -p "$PORT" "$REMOTE" \
    "log='$REMOTE_LOG'; work='$REMOTE_WORK'; active=\$(docker ps --format '{{.ID}} {{.Status}}' | head -1 || true); finished=\$(grep -c 'Training finished' \"\$log\" 2>/dev/null || true); label_errors=\$(grep -c 'Label index out of bounds' \"\$log\" 2>/dev/null || true); data_errors=\$(grep -c -E 'Unsupported audio format|Cannot open input file|Traceback|Segmentation fault' \"\$log\" 2>/dev/null || true); age=\$(test -f \"\$log\" && expr \$(date +%s) - \$(stat -c %Y \"\$log\") || echo 999999); echo NOW; date; echo ACTIVE_CONTAINER=\${active:-none}; echo LOG_AGE_SECONDS=\$age; echo TRAINING_FINISHED=\$finished; echo LABEL_ERRORS=\$label_errors; echo DATA_ERRORS=\$data_errors; echo CHECKPOINTS=\$(find \"\$work\" -type f -name '*.pth' 2>/dev/null | wc -l); echo PROGRESS; grep -E 'Start epoch|Epoch:|Evaluate epoch|Save model|Training finished' \"\$log\" 2>/dev/null | tail -5 || true"
}

once() {
  snapshot="$(remote_snapshot 2>&1)" || snapshot="SSH_CHECK_FAILED\n$snapshot"
  {
    echo "=== $(date '+%F %T %Z') local_poll ==="
    echo "$snapshot"
  } | tee -a "$LOG_FILE"

  issue=0
  if grep -q 'SSH_CHECK_FAILED' <<<"$snapshot" && ! grep -q 'TRAINING_FINISHED=1' <<<"$snapshot"; then
    issue=1
  fi
  if grep -q 'LOG_AGE_SECONDS=' <<<"$snapshot" && ! grep -q 'TRAINING_FINISHED=1' <<<"$snapshot"; then
    log_age="$(sed -n 's/^LOG_AGE_SECONDS=//p' <<<"$snapshot" | tail -1)"
    if [[ "$log_age" =~ ^[0-9]+$ ]] && (( log_age > 600 )); then
      issue=1
    fi
  fi
  if grep -q 'LABEL_ERRORS=[1-9]\|DATA_ERRORS=[1-9]' <<<"$snapshot"; then
    issue=1
  fi
  if (( issue )); then
    if [[ ! -f "$ALERT_FILE" ]]; then
      touch "$ALERT_FILE"
      /usr/bin/afplay /System/Library/Sounds/Glass.aiff >/dev/null 2>&1 || true
      /usr/bin/osascript -e 'display notification "KWS training requires attention" with title "MyAgent KWS monitor"' >/dev/null 2>&1 || true
      echo "KWS monitor alert: $JOB_KEY requires attention" | tee -a "$LOG_FILE"
    fi
  else
    rm -f "$ALERT_FILE"
  fi
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
