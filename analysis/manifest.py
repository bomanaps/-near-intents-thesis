"""
Data integrity manifest: every number traces to a hashed input.

write:  compute SHA-256 and byte size of every raw input and model output,
        embed the latest Hugging Face upload record (exact bytes hashed at
        upload time, pinned to the HF commit id), and write data/manifest.json.
verify: recompute every hash and compare against the committed manifest,
        check the HF upload record is present and well formed, print PASS or
        FAIL per file, and exit nonzero on any mismatch.

The manifest never includes itself. The live events.jsonl is deliberately not
hashed here because it grows continuously; its integrity record is the pinned
HF revision written by ingest/hf_upload.py, which anyone can re-download and
hash against the recorded digest.

Usage:
  python analysis/manifest.py write
  python analysis/manifest.py verify
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "data" / "manifest.json"
UPLOAD_RECORD = ROOT / "data" / "raw" / "fastnear" / "last_upload.json"

TRACKED = [
    "data/raw/daily_metrics.parquet",
    "data/model/forecast.json",
    "data/model/fee_switch.json",
    "data/model/onchain.json",
    "data/model/frequency.json",
    "data/model/price_link.json",
    "docs/data/forecast.json",
    "docs/data/fee_switch.json",
    "docs/data/onchain.json",
    "docs/data/frequency.json",
    "docs/data/price_link.json",
]

SOURCES = {
    "volume_fees_revenue": "https://api.llama.fi/summary/{dexs,fees}/near-intents",
    "near_price": "https://coins.llama.fi/prices/current/coingecko:near",
    "onchain_events": "https://huggingface.co/datasets/bomankari/near-intents-onchain-events",
    "controls": "https://api.llama.fi/summary/{aggregators,dexs}/{1inch,paraswap,jupiter}",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_upload_record() -> dict | None:
    if UPLOAD_RECORD.exists():
        return json.loads(UPLOAD_RECORD.read_text())
    return None


def write() -> None:
    files = {}
    for rel in TRACKED:
        p = ROOT / rel
        if not p.exists():
            sys.exit(f"FAIL: tracked file missing: {rel}")
        files[rel] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}

    manifest = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "SHA-256 of every raw input and model output; the manifest excludes itself",
        "sources": SOURCES,
        "files": files,
        "events_snapshot": load_upload_record(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    print(f"wrote {MANIFEST.relative_to(ROOT)}: {len(files)} files hashed")
    if manifest["events_snapshot"]:
        es = manifest["events_snapshot"]
        print(f"events snapshot pinned: {es.get('lines')} lines, HF commit {str(es.get('hf_commit'))[:12]}")
    else:
        print("events snapshot record absent (no HF upload has run on this machine)")


def verify() -> None:
    if not MANIFEST.exists():
        sys.exit("FAIL: data/manifest.json not found; run write first")
    manifest = json.loads(MANIFEST.read_text())
    failures = 0

    for rel, rec in manifest["files"].items():
        p = ROOT / rel
        if not p.exists():
            print(f"FAIL  {rel}: file missing")
            failures += 1
            continue
        actual = sha256_file(p)
        if actual != rec["sha256"]:
            print(f"FAIL  {rel}: hash mismatch")
            failures += 1
        else:
            print(f"PASS  {rel}")

    es = manifest.get("events_snapshot")
    if es is None:
        print("WARN  events_snapshot: no pinned HF upload record in manifest")
    elif not all(k in es for k in ("sha256", "lines", "hf_commit", "uploaded_at")):
        print("FAIL  events_snapshot: record malformed")
        failures += 1
    else:
        print(f"PASS  events_snapshot pinned to HF commit {str(es['hf_commit'])[:12]} ({es['lines']} lines)")

    if failures:
        sys.exit(f"{failures} integrity check(s) failed")
    print("All integrity checks passed")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "write":
        write()
    elif mode == "verify":
        verify()
    else:
        sys.exit("usage: python analysis/manifest.py [write|verify]")


if __name__ == "__main__":
    main()
