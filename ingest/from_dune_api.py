from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from decoder import decode_log_line
from decoder.parse import DecodeError
from ingest.from_dune import _TYPE_KEY, _timestamp_to_ns, _to_row

_COL_EXECUTOR = "executor_account_id"
_COL_LOG = "log"
_COL_BLOCK_HEIGHT = "block_height"
_COL_BLOCK_TIME = "block_time"
_COL_RECEIPT_ID = "receipt_id"


def ingest_rows(
    rows: list[dict],
    out_dir: str | Path,
) -> dict[str, int]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    buckets: dict[str, list[dict]] = {name: [] for name in _TYPE_KEY.values()}
    errors: list[dict] = []

    for row in rows:
        log = row.get(_COL_LOG)
        if not isinstance(log, str):
            continue

        executor_id = str(row.get(_COL_EXECUTOR, ""))

        bh = row.get(_COL_BLOCK_HEIGHT)
        block_height = int(bh) if bh is not None else None

        block_timestamp_ns = _timestamp_to_ns(row.get(_COL_BLOCK_TIME))

        rid = row.get(_COL_RECEIPT_ID)
        receipt_id = str(rid) if rid is not None else None

        try:
            result = decode_log_line(
                log,
                executor_id=executor_id,
                block_height=block_height,
                block_timestamp_ns=block_timestamp_ns,
                tx_hash=None,
                receipt_id=receipt_id,
            )
        except DecodeError as exc:
            errors.append({
                "receipt_id": receipt_id,
                "tx_hash": None,
                "log": log,
                "error": str(exc),
            })
            continue

        if result is None or result == []:
            continue

        for item in result:
            key = _TYPE_KEY.get(type(item))
            if key:
                buckets[key].append(_to_row(item))

    counts: dict[str, int] = {}
    for event_type, decoded_rows in buckets.items():
        if not decoded_rows:
            counts[event_type] = 0
            continue
        table = pa.Table.from_pylist(decoded_rows)
        path = out_dir / f"{event_type}.parquet"
        if path.exists():
            existing = pq.read_table(path)
            table = pa.concat_tables([existing, table])
        pq.write_table(table, path)
        counts[event_type] = len(decoded_rows)

    if errors:
        errors_path = out_dir / "decode_errors.parquet"
        error_table = pa.Table.from_pylist(errors)
        if errors_path.exists():
            existing = pq.read_table(errors_path)
            error_table = pa.concat_tables([existing, error_table])
        pq.write_table(error_table, errors_path)
        counts["decode_errors"] = len(errors)

    return counts
