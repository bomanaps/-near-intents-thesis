#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/../data/raw/fastnear/watchdog.log"

INGEST_PID="${1:-$(pgrep -f 'fastnear_ingest.py' | head -1)}"
if [ -z "$INGEST_PID" ]; then
  echo "no fastnear_ingest.py process found; start ingestion first" >&2
  exit 1
fi

notify() {
  osascript -e "display notification \"$1\" with title \"NEAR Ingestion\" sound name \"Basso\"" 2>/dev/null || true
}

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"
}

log "Watchdog started; monitoring PID $INGEST_PID"
notify "Watchdog started; monitoring PID $INGEST_PID"

caffeinate -i -w "$INGEST_PID" &
CAFF_PID=$!
log "caffeinate started (PID $CAFF_PID); system will not sleep while ingestion runs"

POLL=0
while true; do
  if kill -0 "$INGEST_PID" 2>/dev/null; then
    CHECKPOINT=$(cat "$SCRIPT_DIR/../data/raw/fastnear/checkpoint.txt" 2>/dev/null || echo "unknown")
    EVENTS=$(wc -l < "$SCRIPT_DIR/../data/raw/fastnear/events.jsonl" 2>/dev/null || echo "0")
    log "alive; block $CHECKPOINT; $EVENTS events"
    POLL=$((POLL + 1))
    if [ $((POLL % 5)) -eq 0 ]; then
      if python3 "$SCRIPT_DIR/hf_upload.py" >> "$LOG" 2>&1; then
        log "HF snapshot uploaded"
      else
        log "HF upload failed; will retry next cycle"
      fi
    fi
    sleep 300
  else
    log "PROCESS DIED; PID $INGEST_PID no longer running"
    notify "Ingestion stopped at block $(cat "$SCRIPT_DIR/../data/raw/fastnear/checkpoint.txt" 2>/dev/null || echo unknown); restart manually"
    kill "$CAFF_PID" 2>/dev/null || true
    exit 1
  fi
done
