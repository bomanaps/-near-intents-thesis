"""
Anchor the data manifest hash on NEAR mainnet.

Reads data/manifest.json, computes its SHA-256, and writes a record under the
signing account's key space in NEAR Social DB (social.near):

  {account_id}/thesis_manifest = {sha256, manifest_generated_at, anchored_at, repo}

The record overwrites the same keys each day so storage cost stays flat, while
every historical anchor remains permanently auditable in the account's
transaction history on any NEAR explorer.

Credentials come from the environment and never appear in the repository:
  NEAR_ACCOUNT_ID    the signing account (e.g. bomanaps.near)
  NEAR_PRIVATE_KEY   its ed25519 private key

Usage: python analysis/anchor.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from py_near.account import Account

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "data" / "manifest.json"
SOCIAL_CONTRACT = "social.near"
RPC = "https://rpc.mainnet.near.org"
REPO = "https://github.com/bomanaps/-near-intents-thesis"
GAS = 100_000_000_000_000
FIRST_WRITE_DEPOSIT = int(0.05 * 10**24)


async def anchor() -> None:
    account_id = os.environ.get("NEAR_ACCOUNT_ID")
    private_key = os.environ.get("NEAR_PRIVATE_KEY")
    if not account_id or not private_key:
        sys.exit("NEAR_ACCOUNT_ID and NEAR_PRIVATE_KEY must be set in the environment")
    if not MANIFEST.exists():
        sys.exit("data/manifest.json not found; run the pipeline first")

    manifest_bytes = MANIFEST.read_bytes()
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    generated_at = json.loads(manifest_bytes)["generated_at"]

    record = {
        "data": {
            account_id: {
                "thesis_manifest": {
                    "sha256": digest,
                    "manifest_generated_at": generated_at,
                    "anchored_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "repo": REPO,
                }
            }
        }
    }

    acc = Account(account_id, private_key, rpc_addr=RPC)
    await acc.startup()

    def failure(result) -> str | None:
        status = getattr(result, "status", None)
        if isinstance(status, dict) and "Failure" in status:
            return json.dumps(status["Failure"])
        return None

    result = await acc.function_call(SOCIAL_CONTRACT, "set", record, GAS, 0)
    err = failure(result)
    if err and "storage" in err.lower():
        result = await acc.function_call(SOCIAL_CONTRACT, "set", record, GAS, FIRST_WRITE_DEPOSIT)
        err = failure(result)
    if err:
        sys.exit(f"anchor transaction failed on chain: {err}")

    tx_hash = getattr(result.transaction, "hash", None)
    print(f"anchored manifest sha256 {digest}")
    print(f"account: {account_id}, contract: {SOCIAL_CONTRACT}")
    print(f"transaction: https://nearblocks.io/txns/{tx_hash}")


if __name__ == "__main__":
    asyncio.run(anchor())
