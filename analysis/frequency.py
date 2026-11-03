"""
How often has daily protocol revenue covered daily issuance?

Joins the DefiLlama daily revenue series (data/raw/daily_metrics.parquet) with
historical NEAR prices from the DefiLlama coins chart endpoint, then counts the
days on which revenue_usd >= supply * cap / 365 * price for the 2.5% cap and
the 1.6% HSP-029 floor. Supply is held at the current figure, a disclosed
approximation of under one percent over the window.

Output: data/model/frequency.json and docs/data/frequency.json

Usage: python analysis/frequency.py
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_IN = ROOT / "data" / "raw" / "daily_metrics.parquet"
OUT = ROOT / "data" / "model" / "frequency.json"
DOCS_OUT = ROOT / "docs" / "data" / "frequency.json"

SUPPLY = 1_309_640_573
CAPS = {"cap25": 0.025, "cap16": 0.016}
CHUNK_DAYS = 350


def fetch_prices(start_ts: int, total_days: int) -> pd.DataFrame:
    rows = []
    for offset in range(0, total_days, CHUNK_DAYS):
        url = (
            "https://coins.llama.fi/chart/coingecko:near"
            f"?start={start_ts + offset * 86400}&span={CHUNK_DAYS}&period=1d"
        )
        with urllib.request.urlopen(url, timeout=30) as r:
            coins = json.load(r)["coins"]
        if "coingecko:near" in coins:
            rows += coins["coingecko:near"]["prices"]
    pr = pd.DataFrame(rows).drop_duplicates("timestamp")
    pr["date"] = pd.to_datetime(pr["timestamp"], unit="s", utc=True).dt.strftime("%Y-%m-%d")
    return pr.groupby("date")["price"].last().reset_index()


def main() -> None:
    df = pd.read_parquet(DATA_IN).sort_values("date")
    df["date"] = df["date"].astype(str)
    start_ts = int(pd.Timestamp(df["date"].iloc[0]).timestamp())
    prices = fetch_prices(start_ts, len(df))
    m = df.merge(prices, on="date", how="inner")

    caps_out = {}
    for key, cap in CAPS.items():
        issuance = SUPPLY * cap / 365 * m["price"]
        covered = m["revenue_usd"] >= issuance
        caps_out[key] = {
            "cap": cap,
            "days_covered": int(covered.sum()),
            "share": round(float(covered.mean()), 4),
            "covered_dates": m.loc[covered, "date"].tolist(),
        }

    best = m.loc[m["revenue_usd"].idxmax()]
    best_iss25 = SUPPLY * 0.025 / 365 * best["price"]

    result = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "question": "days on which daily protocol revenue covered full daily issuance",
            "matched_days": len(m),
            "parquet_days": len(df),
            "supply_assumption": SUPPLY,
            "price_source": "coins.llama.fi chart, coingecko:near, daily closes",
            "caveats": [
                "Supply held at the current total; the approximation error over the window is under one percent",
                "Days without a matched price close are excluded and counted in parquet_days minus matched_days",
            ],
        },
        "coverage": caps_out,
        "best_day": {
            "date": str(best["date"]),
            "revenue_usd": round(float(best["revenue_usd"]), 0),
            "share_of_cap25_issuance": round(float(best["revenue_usd"] / best_iss25), 2),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    DOCS_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT, DOCS_OUT)

    c25, c16 = caps_out["cap25"], caps_out["cap16"]
    print(f"Matched {len(m)} of {len(df)} days with price data")
    print(f"Revenue covered 2.5%-cap issuance on {c25['days_covered']} days ({c25['share']*100:.1f}%)")
    print(f"Revenue covered 1.6%-cap issuance on {c16['days_covered']} days ({c16['share']*100:.1f}%)")
    print(f"Best day {result['best_day']['date']}: {result['best_day']['share_of_cap25_issuance']}x the 2.5%-cap issuance")
    print(f"Wrote {OUT.relative_to(ROOT)} and {DOCS_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
