"""
Upload the current FastNEAR events snapshot to the Hugging Face dataset.

Converts events.jsonl to events.parquet (so the HF Dataset Viewer renders it)
and uploads both files to bomankari/near-intents-onchain-events.

Authentication comes from the stored Hugging Face login (hf auth login);
no token appears in this file or in the repository.

Usage: python ingest/hf_upload.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi

ROOT = Path(__file__).parent.parent
EVENTS = ROOT / "data" / "raw" / "fastnear" / "events.jsonl"
PARQUET = ROOT / "data" / "raw" / "fastnear" / "events.parquet"
REPO_ID = "bomankari/near-intents-onchain-events"


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

    api = HfApi()
    for path in (EVENTS, PARQUET):
        api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo=path.name,
            repo_id=REPO_ID,
            repo_type="dataset",
        )
    print(f"uploaded {len(rows)} events to {REPO_ID}")


if __name__ == "__main__":
    main()
