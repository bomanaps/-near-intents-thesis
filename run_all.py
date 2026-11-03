"""
Reproduce the full NEAR Intents Investment Thesis pipeline with one command.

  python run_all.py            fetch fresh DefiLlama data, then run both models
  python run_all.py --no-fetch skip the fetch, use the committed parquet as-is

Steps:
  1. Fetch daily volume, fees, and revenue for near-intents from DefiLlama
     and rebuild data/raw/daily_metrics.parquet
  2. Run model/forecast.py   (Monte Carlo volume forecast)
  3. Run model/fee_switch.py (fee switch difference-in-differences)
  4. Copy both model JSONs into docs/data/ so the GitHub Pages dashboard
     serves them (Pages only publishes the docs/ folder)

On-chain FastNEAR ingestion runs separately (ingest/fastnear_ingest.py) and is
not required for the models; DefiLlama is the primary data source.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA_OUT = ROOT / "data" / "raw" / "daily_metrics.parquet"

ENDPOINTS = {
    "volume_usd": "https://api.llama.fi/summary/dexs/near-intents?excludeTotalDataChart=false&dataType=dailyVolume",
    "fees_usd": "https://api.llama.fi/summary/fees/near-intents?excludeTotalDataChart=false&dataType=dailyFees",
    "revenue_usd": "https://api.llama.fi/summary/fees/near-intents?excludeTotalDataChart=false&dataType=dailyRevenue",
}


def fetch_series(url: str, col: str) -> pd.DataFrame:
    with urllib.request.urlopen(url, timeout=30) as r:
        chart = json.load(r)["totalDataChart"]
    df = pd.DataFrame(chart, columns=["ts", col])
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.strftime("%Y-%m-%d")
    return df[["date", col]]


def fetch_daily_metrics() -> None:
    print("[1/4] Fetching DefiLlama data for near-intents")
    frames = []
    for col, url in ENDPOINTS.items():
        df = fetch_series(url, col)
        print(f"      {col}: {len(df)} days")
        frames.append(df)

    merged = frames[0]
    for df in frames[1:]:
        merged = merged.merge(df, on="date", how="left")
    merged = merged.fillna(0.0).sort_values("date").reset_index(drop=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    merged = merged[merged["date"] < today].reset_index(drop=True)

    vol = merged["volume_usd"].replace(0, pd.NA)
    merged["capture_rate_bps"] = (merged["fees_usd"] / vol * 10_000).fillna(0.0)
    merged["rev_capture_bps"] = (merged["revenue_usd"] / vol * 10_000).fillna(0.0)
    merged["volume_usd"] = merged["volume_usd"].astype("int64")
    merged["source"] = "defillama"

    cols = ["date", "fees_usd", "volume_usd", "revenue_usd",
            "capture_rate_bps", "rev_capture_bps", "source"]
    merged[cols].to_parquet(DATA_OUT, index=False)
    print(f"      wrote {len(merged)} rows to {DATA_OUT.relative_to(ROOT)}")
    print(f"      range: {merged['date'].iloc[0]} to {merged['date'].iloc[-1]}")


def run_step(label: str, script: str) -> None:
    print(f"\n{label} Running {script}")
    result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"FAILED: {script} exited with code {result.returncode}")


def main() -> None:
    if "--no-fetch" in sys.argv:
        print("[1/4] Skipping fetch (--no-fetch); using committed parquet")
    else:
        try:
            fetch_daily_metrics()
        except Exception as e:
            if DATA_OUT.exists():
                print(f"      fetch failed ({e}); falling back to committed parquet")
            else:
                sys.exit(f"FAILED: fetch failed and no cached parquet exists: {e}")

    run_step("[2/4]", "model/forecast.py")
    run_step("[3/4]", "model/fee_switch.py")

    docs_data = ROOT / "docs" / "data"
    docs_data.mkdir(parents=True, exist_ok=True)
    for name in ("forecast.json", "fee_switch.json"):
        shutil.copy2(ROOT / "data" / "model" / name, docs_data / name)
    print(f"\n[4/4] Published both JSONs to {docs_data.relative_to(ROOT)}/")

    print("\nDone. Outputs: data/model/*.json and docs/data/*.json")
    print("On-chain FastNEAR ingestion is a separate ongoing process and is not required here.")


if __name__ == "__main__":
    main()
