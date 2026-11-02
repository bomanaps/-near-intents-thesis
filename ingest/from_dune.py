from __future__ import annotations

import json
import sys
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent.parent))

from decoder import (
    FeeChangedItem,
    FeeCollectorChangedItem,
    FtWithdrawItem,
    IntentsExecutedItem,
    MtWithdrawItem,
    NativeWithdrawItem,
    TokenDiffItem,
    TransferItem,
    decode_log_line,
)
from decoder.parse import DecodeError

COLUMN_DEFAULTS = {
    "block_height": "block_height",
    "block_timestamp": "block_time",
    "tx_hash": "tx_hash",
    "receipt_id": "receipt_id",
    "executor_id": "executor_account_id",
    "log": "log",
}

_TYPE_KEY = {
    TokenDiffItem: "token_diff",
    IntentsExecutedItem: "intents_executed",
    TransferItem: "transfer",
    FtWithdrawItem: "ft_withdraw",
    MtWithdrawItem: "mt_withdraw",
    NativeWithdrawItem: "native_withdraw",
    FeeChangedItem: "fee_changed",
    FeeCollectorChangedItem: "fee_collector_changed",
}

_DICT_FIELDS = frozenset({"diff", "fees_collected", "tokens"})
_LIST_FIELDS = frozenset({"token_ids", "amounts"})


def _to_row(item) -> dict:
    row = asdict(item)
    for field in _DICT_FIELDS:
        if field in row and isinstance(row[field], dict):
            row[field] = json.dumps(row[field])
    for field in _LIST_FIELDS:
        if field in row and isinstance(row[field], list):
            row[field] = json.dumps(row[field])
    return row


def _timestamp_to_ns(val) -> Optional[int]:
    if pd.isna(val):
        return None
    ts = pd.Timestamp(val)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.value)


def ingest_csv(
    csv_path: str | Path,
    out_dir: str | Path,
    column_map: Optional[dict[str, str]] = None,
) -> dict[str, int]:
    cols = {**COLUMN_DEFAULTS, **(column_map or {})}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path, low_memory=False)

    missing = [v for v in cols.values() if v not in df.columns]
    if missing:
        raise ValueError(
            f"Columns not found in CSV: {missing}. "
            f"Available columns: {list(df.columns)}. "
            f"Pass column_map to override defaults."
        )

    buckets: dict[str, list[dict]] = {name: [] for name in _TYPE_KEY.values()}
    errors: list[dict] = []

    for _, row in df.iterrows():
        log = row[cols["log"]]
        if not isinstance(log, str):
            continue

        executor_id = str(row[cols["executor_id"]])
        block_height_raw = row[cols["block_height"]]
        block_height = int(block_height_raw) if pd.notna(block_height_raw) else None
        block_timestamp_ns = _timestamp_to_ns(row[cols["block_timestamp"]])
        tx_hash = str(row[cols["tx_hash"]]) if pd.notna(row[cols["tx_hash"]]) else None
        receipt_id = str(row[cols["receipt_id"]]) if pd.notna(row[cols["receipt_id"]]) else None

        try:
            result = decode_log_line(
                log,
                executor_id=executor_id,
                block_height=block_height,
                block_timestamp_ns=block_timestamp_ns,
                tx_hash=tx_hash,
                receipt_id=receipt_id,
            )
        except DecodeError as exc:
            errors.append({
                "receipt_id": receipt_id,
                "tx_hash": tx_hash,
                "log": log,
                "error": str(exc),
            })
            continue

        if result is None or result == []:
            continue

        items = result if isinstance(result, list) else [result]
        for item in items:
            key = _TYPE_KEY.get(type(item))
            if key:
                buckets[key].append(_to_row(item))

    counts: dict[str, int] = {}
    for event_type, rows in buckets.items():
        if not rows:
            counts[event_type] = 0
            continue
        table = pa.Table.from_pylist(rows)
        path = out_dir / f"{event_type}.parquet"
        if path.exists():
            existing = pq.read_table(path)
            table = pa.concat_tables([existing, table])
        pq.write_table(table, path)
        counts[event_type] = len(rows)

    if errors:
        errors_path = out_dir / "decode_errors.parquet"
        error_table = pa.Table.from_pylist(errors)
        if errors_path.exists():
            existing = pq.read_table(errors_path)
            error_table = pa.concat_tables([existing, error_table])
        pq.write_table(error_table, errors_path)
        counts["decode_errors"] = len(errors)

    return counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("out_dir")
    parser.add_argument("--col-executor", default=COLUMN_DEFAULTS["executor_id"])
    parser.add_argument("--col-timestamp", default=COLUMN_DEFAULTS["block_timestamp"])
    args = parser.parse_args()

    column_map = {
        "executor_id": args.col_executor,
        "block_timestamp": args.col_timestamp,
    }

    counts = ingest_csv(args.csv_path, args.out_dir, column_map=column_map)
    for event_type, n in sorted(counts.items()):
        print(f"{event_type}: {n}")
