"""
Upload the current FastNEAR events snapshot to the Hugging Face dataset.

Converts events.jsonl to events.parquet (so the HF Dataset Viewer renders it)
and uploads both files to bomankari/near-intents-onchain-events.

Authentication comes from the stored Hugging Face login (hf auth login);
no token appears in this file or in the repository.

Usage: python ingest/hf_upload.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi

ROOT = Path(__file__).parent.parent
EVENTS = ROOT / "data" / "raw" / "fastnear" / "events.jsonl"
PARQUET = ROOT / "data" / "raw" / "fastnear" / "events.parquet"
REPO_ID = "bomankari/near-intents-onchain-events"
UPLOAD_RECORD = ROOT / "data" / "raw" / "fastnear" / "last_upload.json"


def main() -> None:
    if not EVENTS.exists():
        sys.exit(f"events file not found: {EVENTS}")

    rows = []
    with open(EVENTS) as f:
        for line in f:
            e = json.loads(line)
            if isinstance(e.get("data"), (dict, list)):
                e["data"] = json.dumps(e["data"])
            rows.append(e)
    pd.DataFrame(rows).to_parquet(PARQUET, index=False)

    events_bytes = EVENTS.read_bytes()
    digest = hashlib.sha256(events_bytes).hexdigest()

    api = HfApi()
    commit = None
    for path, payload in ((EVENTS, events_bytes), (PARQUET, PARQUET.read_bytes())):
        commit = api.upload_file(
            path_or_fileobj=payload,
            path_in_repo=path.name,
            repo_id=REPO_ID,
            repo_type="dataset",
        )

    UPLOAD_RECORD.write_text(json.dumps({
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lines": len(rows),
        "sha256": digest,
        "bytes": len(events_bytes),
        "repo": REPO_ID,
        "hf_commit": getattr(commit, "oid", None),
    }, indent=1))
    print(f"uploaded {len(rows)} events to {REPO_ID}, commit {getattr(commit, 'oid', 'unknown')}")


if __name__ == "__main__":
    main()
