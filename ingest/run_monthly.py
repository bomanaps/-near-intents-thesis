from __future__ import annotations

import argparse
import calendar
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest.from_dune_api import ingest_rows

DUNE_API = "https://api.dune.com/api/v1"
PAGE_SIZE = 1_000
POLL_INTERVAL = 5

_SQL = """\
SELECT
    block_date,
    block_height,
    block_time,
    receipt_id,
    executor_account_id,
    index_in_execution_outcome_logs,
    log
FROM near.logs
WHERE executor_account_id IN ('intents.near', 'defuse-alpha.near')
  AND starts_with(log, 'EVENT_JSON:')
  AND block_date = DATE '{day}'
ORDER BY block_height ASC, index_in_execution_outcome_logs ASC
"""

_TERMINAL_STATES = {
    "QUERY_STATE_COMPLETED",
    "QUERY_STATE_FAILED",
    "QUERY_STATE_CANCELLED",
    "QUERY_STATE_EXPIRED",
}


def _headers(api_key: str) -> dict:
    return {"X-Dune-Api-Key": api_key, "Content-Type": "application/json"}


def _create_query(sql: str, name: str, api_key: str) -> int:
    resp = requests.post(
        f"{DUNE_API}/query",
        headers=_headers(api_key),
        json={"name": name, "query_sql": sql, "is_private": True},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["query_id"]


def _execute_query(query_id: int, api_key: str) -> str:
    resp = requests.post(
        f"{DUNE_API}/query/{query_id}/execute",
        headers=_headers(api_key),
        json={"performance": "medium"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["execution_id"]


def _wait_for_completion(execution_id: str, api_key: str) -> None:
    while True:
        resp = requests.get(
            f"{DUNE_API}/execution/{execution_id}/status",
            headers={"X-Dune-Api-Key": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        state = resp.json()["state"]
        if state == "QUERY_STATE_COMPLETED":
            return
        if state in _TERMINAL_STATES:
            raise RuntimeError(f"Execution {execution_id} ended with state: {state}")
        time.sleep(POLL_INTERVAL)


def _fetch_all_rows(execution_id: str, api_key: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(
            f"{DUNE_API}/execution/{execution_id}/results",
            headers={"X-Dune-Api-Key": api_key},
            params={"limit": PAGE_SIZE, "offset": offset},
            timeout=60,
        )
        resp.raise_for_status()
        batch = resp.json().get("result", {}).get("rows", [])
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def run_day(day: str, out_dir: Path, api_key: str) -> dict[str, int]:
    sql = _SQL.format(day=day)
    name = f"near-intents-logs-{day}"
    query_id = _create_query(sql, name, api_key)
    execution_id = _execute_query(query_id, api_key)
    _wait_for_completion(execution_id, api_key)
    rows = _fetch_all_rows(execution_id, api_key)
    counts = ingest_rows(rows, out_dir)
    return counts


def run_month(month: str, out_dir: Path, api_key: str) -> dict[str, int]:
    year, mon = int(month[:4]), int(month[5:7])
    _, last_day = calendar.monthrange(year, mon)
    totals: dict[str, int] = {}
    for d in range(1, last_day + 1):
        day = f"{year:04d}-{mon:02d}-{d:02d}"
        print(f"[{day}] fetching...", flush=True)
        counts = run_day(day, out_dir, api_key)
        decoded = sum(v for k, v in counts.items() if k != "decode_errors")
        errors = counts.get("decode_errors", 0)
        print(f"[{day}] decoded={decoded:,}  errors={errors:,}", flush=True)
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
    return totals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch NEAR Intents logs from Dune day-by-day, decode, write Parquet."
    )
    parser.add_argument("month", help="YYYY-MM  e.g. 2025-10")
    parser.add_argument("out_dir", help="Directory to write Parquet files")
    parser.add_argument("--api-key", required=True, help="Dune API key")
    args = parser.parse_args()

    counts = run_month(args.month, Path(args.out_dir), args.api_key)
    print(f"\n[{args.month}] totals:")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v:,}")
