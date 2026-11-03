"""
Async ingestion of intents.near EVENT_JSON logs via FastNEAR neardata API.

Verified facts baked into this script (do not change without re-verification):
  - intents.near is on shard 7 for the entire ingestion window (Oct 11, 2026 onward)
  - shard 3 returns null across this range; no shard-split handling needed
  - logs live at: receipt_execution_outcomes[*].execution_outcome.outcome.logs
  - skip events from failed receipts (race-condition artifacts from competing solvers)
  - nep245 events on intents.near are normal (multi-token registry); not anomalies
  - 22-day window: block 220_784_790 to 222_746_488 (~1.96M blocks)

Outputs:
  events.jsonl       : one JSON line per valid dip4 event
  anomalies.jsonl    : one JSON line per anomaly (for review)
  checkpoint.txt     : last fully processed block height (enables resume)

Usage:
  python3 fastnear_ingest.py                        # start or resume
  python3 fastnear_ingest.py --start 220784790      # override start block
  python3 fastnear_ingest.py --end 222000000        # override end block
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp

NEARDATA_URL = "https://mainnet.neardata.xyz/v0/block/{height}/shard/7"
INTENTS_ACCOUNTS = frozenset({"intents.near", "defuse-alpha.near"})

BLOCK_START_DEFAULT = 222_253_590   # Oct 28, 2026; 5 days before tip
BLOCK_END_DEFAULT   = 222_898_897   # Nov 3, 2026 tip; pass --end to extend further

MAX_CONCURRENT = 1       # rate-limited to 30 blocks/min: concurrency doesn't help
RATE_SLEEP     = 2.1     # 28.6 blocks/min; safely under the 30/min free-tier limit
RETRY_LIMIT    = 4
RETRY_BACKOFF  = [3, 8, 20, 60]  # longer backoffs to let rate-limit window reset
CHECKPOINT_EVERY = 500   # flush checkpoint every N blocks

OUT_DIR = Path(__file__).parent.parent / "data" / "raw" / "fastnear"


def open_outputs(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    events_f   = open(out_dir / "events.jsonl",    "a", buffering=1)
    anomaly_f  = open(out_dir / "anomalies.jsonl", "a", buffering=1)
    return events_f, anomaly_f


def read_checkpoint(out_dir: Path) -> int | None:
    p = out_dir / "checkpoint.txt"
    if p.exists():
        try:
            val = int(p.read_text().strip())
            return val
        except ValueError:
            return None
    return None


def write_checkpoint(out_dir: Path, height: int):
    (out_dir / "checkpoint.txt").write_text(str(height))


def log_anomaly(anomaly_f, block: int, kind: str, detail: str):
    anomaly_f.write(json.dumps({"block": block, "kind": kind, "detail": detail}) + "\n")


async def fetch_shard(session: aiohttp.ClientSession, height: int) -> dict | None:
    url = NEARDATA_URL.format(height=height)
    last_err = "no attempts made"
    for attempt in range(RETRY_LIMIT):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 429:
                    wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)]
                    last_err = f"HTTP 429 (attempt {attempt}, backing off {wait}s)"
                    await asyncio.sleep(wait)
                    continue
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                data = await resp.json(content_type=None)
                return data  # may be None if API returns JSON null
        except asyncio.TimeoutError as e:
            last_err = f"TimeoutError on attempt {attempt}"
            if attempt < RETRY_LIMIT - 1:
                await asyncio.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
        except aiohttp.ClientError as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < RETRY_LIMIT - 1:
                await asyncio.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < RETRY_LIMIT - 1:
                await asyncio.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)])
    return {"_fetch_error": f"exhausted {RETRY_LIMIT} retries: {last_err}"}


def process_block(height: int, data: dict, events_f, anomaly_f) -> dict:
    stats = {"events": 0, "anomalies": 0, "skipped_failures": 0, "skipped_nondip4": 0}
    reos = data.get("receipt_execution_outcomes") or []
    seen_receipt_ids = set()

    for reo in reos:
        receipt    = reo.get("receipt") or {}
        receiver   = receipt.get("receiver_id", "")
        if receiver not in INTENTS_ACCOUNTS:
            continue

        eo      = reo.get("execution_outcome") or {}
        outcome = eo.get("outcome") or {}
        status  = outcome.get("status") or {}
        logs    = outcome.get("logs") or []
        receipt_id = eo.get("id") or receipt.get("receipt_id") or "unknown"

        # Duplicate receipt guard
        if receipt_id in seen_receipt_ids:
            log_anomaly(anomaly_f, height, "duplicate_receipt_id", receipt_id)
            stats["anomalies"] += 1
            continue
        seen_receipt_ids.add(receipt_id)

        # Skip failed executions; logs from failures are race-condition artifacts
        is_failure = "Failure" in status
        if is_failure:
            if logs:
                stats["skipped_failures"] += 1
                log_anomaly(anomaly_f, height, "failed_receipt_with_logs",
                            f"receipt_id={receipt_id} predecessor={receipt.get('predecessor_id')} logs={len(logs)}")
            continue

        predecessor = receipt.get("predecessor_id", "")
        tx_hash = reo.get("tx_hash") or ""

        for log in logs:
            if not log.startswith("EVENT_JSON:"):
                continue
            raw = log[len("EVENT_JSON:"):]
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError as e:
                log_anomaly(anomaly_f, height, "json_parse_error",
                            f"receipt_id={receipt_id} error={e} raw={raw[:120]}")
                stats["anomalies"] += 1
                continue

            std = ev.get("standard", "")
            if std != "dip4":
                # nep245 events on intents.near are expected (multi-token registry); count not panic
                stats["skipped_nondip4"] += 1
                if std not in ("nep245",):
                    log_anomaly(anomaly_f, height, "unexpected_standard",
                                f"standard={std!r} event={ev.get('event')!r} receipt_id={receipt_id}")
                    stats["anomalies"] += 1
                continue

            # Validate required dip4 fields
            event_type = ev.get("event")
            if not event_type:
                log_anomaly(anomaly_f, height, "missing_event_field",
                            f"receipt_id={receipt_id} ev={json.dumps(ev)[:200]}")
                stats["anomalies"] += 1
                continue

            ev_data = ev.get("data")
            if not isinstance(ev_data, list):
                log_anomaly(anomaly_f, height, "data_not_list",
                            f"event={event_type!r} data_type={type(ev_data).__name__} receipt_id={receipt_id}")
                stats["anomalies"] += 1
                continue

            # Event-specific field validation
            for item in ev_data:
                if event_type == "token_diff":
                    if "diff" not in item:
                        log_anomaly(anomaly_f, height, "token_diff_missing_diff",
                                    f"item={json.dumps(item)[:200]}")
                        stats["anomalies"] += 1
                    if "account_id" not in item:
                        log_anomaly(anomaly_f, height, "token_diff_missing_account_id",
                                    f"item={json.dumps(item)[:200]}")
                        stats["anomalies"] += 1

                elif event_type == "intents_executed":
                    for field in ("intent_hash", "account_id", "nonce"):
                        if field not in item:
                            log_anomaly(anomaly_f, height, f"intents_executed_missing_{field}",
                                        f"item={json.dumps(item)[:200]}")
                            stats["anomalies"] += 1

            # Write the event
            record = {
                "block_height":  height,
                "receipt_id":    receipt_id,
                "tx_hash":       tx_hash,
                "predecessor":   predecessor,
                "receiver":      receiver,
                "standard":      std,
                "version":       ev.get("version", ""),
                "event":         event_type,
                "data":          ev_data,
            }
            events_f.write(json.dumps(record) + "\n")
            stats["events"] += 1

    return stats


async def ingest(start: int, end: int, out_dir: Path):
    events_f, anomaly_f = open_outputs(out_dir)

    # Resume from checkpoint
    checkpoint = read_checkpoint(out_dir)
    resume_from = (checkpoint + 1) if checkpoint is not None else start
    if resume_from > start:
        print(f"Resuming from block {resume_from:,} (checkpoint={checkpoint:,})")
    else:
        print(f"Starting from block {start:,}")

    total_blocks  = end - resume_from + 1
    total_events  = 0
    total_anomaly = 0
    t0            = time.time()
    last_report   = t0
    blocks_done   = 0

    semaphore   = asyncio.Semaphore(MAX_CONCURRENT)
    rate_lock   = asyncio.Lock()
    last_send   = [0.0]

    async def fetch_throttled(session, height):
        # Serialize request STARTS to maintain ~3 req/sec globally,
        # but allow up to MAX_CONCURRENT fetches in-flight concurrently.
        async with rate_lock:
            now  = asyncio.get_event_loop().time()
            wait = last_send[0] + RATE_SLEEP - now
            if wait > 0:
                await asyncio.sleep(wait)
            last_send[0] = asyncio.get_event_loop().time()
        async with semaphore:
            return height, await fetch_shard(session, height)

    async with aiohttp.ClientSession() as session:
        # Process in batches to keep memory bounded and write checkpoints
        batch_size = 100
        h = resume_from
        while h <= end:
            batch_end = min(h + batch_size - 1, end)
            tasks = [asyncio.create_task(fetch_throttled(session, bh))
                     for bh in range(h, batch_end + 1)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process in order
            for res in results:
                if isinstance(res, Exception):
                    print(f"  EXCEPTION in batch: {res}", file=sys.stderr)
                    continue
                height, data = res
                if data is None:
                    # null = block not on this shard (normal; skip silently)
                    pass
                elif "_fetch_error" in data:
                    log_anomaly(anomaly_f, height, "fetch_error", data["_fetch_error"])
                    total_anomaly += 1
                else:
                    stats = process_block(height, data, events_f, anomaly_f)
                    total_events  += stats["events"]
                    total_anomaly += stats["anomalies"]
                blocks_done += 1

            # Checkpoint after each batch
            write_checkpoint(out_dir, batch_end)

            # Progress report every 30 seconds
            now = time.time()
            if now - last_report >= 30:
                elapsed  = now - t0
                rate     = blocks_done / elapsed if elapsed > 0 else 0
                pct      = blocks_done / total_blocks * 100
                eta_s    = (total_blocks - blocks_done) / rate if rate > 0 else float("inf")
                eta_h    = eta_s / 3600
                print(f"  {pct:.1f}%  block={batch_end:,}  "
                      f"events={total_events:,}  anomalies={total_anomaly}  "
                      f"rate={rate:.0f} blk/s  ETA={eta_h:.1f}h")
                last_report = now

            h = batch_end + 1

    events_f.close()
    anomaly_f.close()
    elapsed = time.time() - t0
    print(f"\nDone. {blocks_done:,} blocks in {elapsed/3600:.2f}h  "
          f"events={total_events:,}  anomalies={total_anomaly}")
    print(f"Output: {out_dir}/events.jsonl")


def main():
    parser = argparse.ArgumentParser(description="FastNEAR intents.near event ingestion")
    parser.add_argument("--start", type=int, default=BLOCK_START_DEFAULT,
                        help=f"Start block height (default: {BLOCK_START_DEFAULT:,})")
    parser.add_argument("--end",   type=int, default=BLOCK_END_DEFAULT,
                        help=f"End block height (default: {BLOCK_END_DEFAULT:,})")
    parser.add_argument("--out",   type=str, default=str(OUT_DIR),
                        help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out)
    print(f"FastNEAR ingest: blocks {args.start:,} → {args.end:,} "
          f"({args.end - args.start:,} blocks)")
    print(f"Output: {out_dir}")
    blocks = args.end - args.start
    print(f"At {60/RATE_SLEEP:.0f} blocks/min, estimated wall time: {blocks*RATE_SLEEP/3600:.1f} hours ({blocks*RATE_SLEEP/86400:.1f} days)")
    print()

    asyncio.run(ingest(args.start, args.end, out_dir))


if __name__ == "__main__":
    main()
