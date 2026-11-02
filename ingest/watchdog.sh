#!/usr/bin/env bash
set -euo pipefail

INGEST_PID=99275
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/../data/raw/fastnear/watchdog.log"

notify() {
  osascript -e "display notification \"$1\" with title \"NEAR Ingestion\" sound name \"Basso\""
}

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"
}

log "Watchdog started — monitoring PID $INGEST_PID"
notify "Watchdog started — monitoring PID $INGEST_PID"

# Prevent system sleep for as long as this watchdog runs
# (caffeinate exits when its child or the -w PID exits)
# Run caffeinate in the background tied to the ingest PID
caffeinate -i -w "$INGEST_PID" &
CAFF_PID=$!
log "caffeinate started (PID $CAFF_PID) — system will not sleep while ingestion runs"

HF_DATASET="bomankari/near-intents-onchain-events"
UPLOAD_INTERVAL=5  # upload every 5 polls (every 25 minutes)
poll_count=0

# Poll loop
while true; do
  if kill -0 "$INGEST_PID" 2>/dev/null; then
    CHECKPOINT=$(cat "$SCRIPT_DIR/../data/raw/fastnear/checkpoint.txt" 2>/dev/null || echo "unknown")
    EVENTS=$(wc -l < "$SCRIPT_DIR/../data/raw/fastnear/events.jsonl" 2>/dev/null || echo "0")
    log "alive — block $CHECKPOINT — $EVENTS events"
    poll_count=$((poll_count + 1))
    if [ $((poll_count % UPLOAD_INTERVAL)) -eq 0 ]; then
      log "uploading snapshot to Hugging Face — block $CHECKPOINT, $EVENTS events"
      huggingface-cli upload "$HF_DATASET" \
        "$SCRIPT_DIR/../data/raw/fastnear/events.jsonl" \
        events.jsonl \
        --repo-type dataset \
        --commit-message "Snapshot: block $CHECKPOINT, $EVENTS events" >> "$LOG" 2>&1 \
        && log "upload complete" || log "upload failed"
    fi
    sleep 300
  else
    log "PROCESS DIED — PID $INGEST_PID no longer running"
    notify "Ingestion stopped at block $(cat $SCRIPT_DIR/../data/raw/fastnear/checkpoint.txt 2>/dev/null || echo unknown) — restart manually"
    # Clean up caffeinate
    kill "$CAFF_PID" 2>/dev/null || true
    exit 1
  fi
done
