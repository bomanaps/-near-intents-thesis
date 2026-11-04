"""
The price question: is NEAR's weekly return related to buyback activity,
after controlling for the crypto market?

Headline specification:
  near_ret_t = a + b1 btc_ret_t + b2 eth_ret_t + b3 intensity_{t-1} + e_t

where intensity is weekly protocol revenue divided by the PRIOR week's NEAR
market cap. The lag avoids reverse causality (price moves volume moves revenue
within the same week), and the lagged denominator keeps the current price out
of the regressor. A contemporaneous specification is reported as a labeled
secondary for comparison with other public work, with that caveat.

Inference: Newey-West (HAC) standard errors, and a permutation test that
reshuffles the intensity series 1,000 times to build the null distribution of
its t-statistic. Robustness: excluding the Sep-Oct 2026 rally weeks, and a
placebo regressor using volume instead of revenue.

Sample: weekly observations since the Feb 23, 2026 fee switch, when buyback
revenue begins. Expectation stated before running: with roughly 36 weekly
observations, a null result is likely and is published regardless.

Inputs:  data/raw/daily_metrics.parquet, coins.llama.fi price history
Output:  data/model/price_link.json and docs/data/price_link.json
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_IN = ROOT / "data" / "raw" / "daily_metrics.parquet"
OUT = ROOT / "data" / "model" / "price_link.json"
DOCS_OUT = ROOT / "docs" / "data" / "price_link.json"

SUPPLY = 1_309_640_573
FEE_SWITCH = "2026-02-23"
RALLY_START = "2026-09-01"
RALLY_END = "2026-10-31"
CHUNK_DAYS = 350
NW_LAGS = 4
N_PERMUTATIONS = 1_000
SEED = 42

COINS = {
    "near": "coingecko:near",
    "btc": "coingecko:bitcoin",
    "eth": "coingecko:ethereum",
}


def fetch_prices(gecko: str, start_ts: int, total_days: int) -> pd.DataFrame:
    rows = []
    for offset in range(0, total_days, CHUNK_DAYS):
        url = (
            f"https://coins.llama.fi/chart/{gecko}"
            f"?start={start_ts + offset * 86400}&span={CHUNK_DAYS}&period=1d"
        )
        with urllib.request.urlopen(url, timeout=30) as r:
            coins = json.load(r)["coins"]
        if gecko in coins:
            rows += coins[gecko]["prices"]
    pr = pd.DataFrame(rows).drop_duplicates("timestamp")
    pr["date"] = pd.to_datetime(pr["timestamp"], unit="s", utc=True).dt.normalize().dt.tz_localize(None)
    return pr.groupby("date")["price"].last().reset_index()


def ols_newey_west(y: np.ndarray, X: np.ndarray, lags: int) -> dict:
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    S = np.zeros((k, k))
    for lag in range(lags + 1):
        weight = 1.0 if lag == 0 else 1.0 - lag / (lags + 1)
        for t in range(lag, n):
            u = (X[t] * resid[t])[:, None] @ (X[t - lag] * resid[t - lag])[None, :]
            S += weight * (u if lag == 0 else u + u.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    return {"beta": beta, "se": se, "t": beta / se, "n": n, "resid": resid}


def weekly_frame() -> pd.DataFrame:
    df = pd.read_parquet(DATA_IN).sort_values("date")
    df["date"] = pd.to_datetime(df["date"])
    start_ts = int(df["date"].iloc[0].timestamp())
    total = (df["date"].iloc[-1] - df["date"].iloc[0]).days + 2
    for name, gecko in COINS.items():
        pr = fetch_prices(gecko, start_ts, total).rename(columns={"price": name})
        df = df.merge(pr, on="date", how="left")
    df = df.dropna(subset=list(COINS)).set_index("date")

    wk = pd.DataFrame({
        "near": df["near"].resample("W-SUN").last(),
        "btc": df["btc"].resample("W-SUN").last(),
        "eth": df["eth"].resample("W-SUN").last(),
        "revenue": df["revenue_usd"].resample("W-SUN").sum(),
        "volume": df["volume_usd"].resample("W-SUN").sum(),
    }).dropna()

    wk["near_ret"] = np.log(wk["near"]).diff()
    wk["btc_ret"] = np.log(wk["btc"]).diff()
    wk["eth_ret"] = np.log(wk["eth"]).diff()
    wk["mcap_lag"] = (wk["near"] * SUPPLY).shift(1)
    wk["intensity"] = wk["revenue"] / wk["mcap_lag"]
    wk["intensity_lag"] = wk["intensity"].shift(1)
    wk["vol_intensity_lag"] = (wk["volume"] / wk["mcap_lag"]).shift(1)
    return wk.dropna()


def run_spec(wk: pd.DataFrame, regressor: str, rng: np.random.Generator | None = None) -> dict:
    y = wk["near_ret"].values
    X = np.column_stack([
        np.ones(len(wk)),
        wk["btc_ret"].values,
        wk["eth_ret"].values,
        wk[regressor].values,
    ])
    fit = ols_newey_west(y, X, NW_LAGS)
    out = {
        "n_weeks": int(fit["n"]),
        "coef_intensity": round(float(fit["beta"][3]), 4),
        "t_intensity": round(float(fit["t"][3]), 3),
        "coef_btc": round(float(fit["beta"][1]), 3),
        "coef_eth": round(float(fit["beta"][2]), 3),
    }
    if rng is not None:
        real_t = abs(fit["t"][3])
        null_ts = []
        x_perm = X.copy()
        values = wk[regressor].values.copy()
        for _ in range(N_PERMUTATIONS):
            x_perm[:, 3] = rng.permutation(values)
            null_ts.append(abs(ols_newey_west(y, x_perm, NW_LAGS)["t"][3]))
        out["permutation_p"] = round(float(np.mean(np.array(null_ts) >= real_t)), 3)
    return out


def main() -> None:
    rng = np.random.default_rng(SEED)
    wk = weekly_frame()
    post = wk[wk.index >= FEE_SWITCH]
    rally_mask = (post.index >= RALLY_START) & (post.index <= RALLY_END)

    weekly_rows = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "near_ret": round(float(r.near_ret), 6),
            "btc_ret": round(float(r.btc_ret), 6),
            "eth_ret": round(float(r.eth_ret), 6),
            "intensity": round(float(r.intensity), 10),
            "intensity_lag": round(float(r.intensity_lag), 10),
            "vol_intensity_lag": round(float(r.vol_intensity_lag), 10),
            "in_rally": bool(RALLY_START <= d.strftime("%Y-%m-%d") <= RALLY_END),
        }
        for d, r in post.iterrows()
    ]

    results = {
        "headline_lagged": run_spec(post, "intensity_lag", rng),
        "contemporaneous_secondary": run_spec(post, "intensity"),
        "excluding_rally": run_spec(post[~rally_mask], "intensity_lag"),
        "placebo_volume": run_spec(post, "vol_intensity_lag"),
    }

    h = results["headline_lagged"]
    detected = h.get("permutation_p", 1.0) < 0.05
    interpretation = (
        f"Lagged buyback intensity shows t = {h['t_intensity']} with permutation p = "
        f"{h.get('permutation_p')}: "
        + ("a detectable association survives the market controls and the permutation test."
           if detected else
           "no detectable price effect of buyback intensity after market controls. "
           "With this sample size that is the expected result, and it is published as found. "
           "The thesis's break-even mechanism does not depend on a short-run price effect.")
    )

    result = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "question": "is NEAR's weekly return related to buyback activity, controlling for BTC and ETH",
            "sample": f"weekly since {FEE_SWITCH} (fee switch, start of buyback revenue)",
            "method": "OLS with Newey-West standard errors (4 lags); 1,000-permutation null for the headline t-stat",
            "headline_regressor": "prior-week revenue / prior-week market cap (both lagged to avoid mechanical and reverse-causality bias)",
            "expectation_preregistered": "null likely at this sample size; published regardless",
            "caveats": [
                "Roughly 36 weekly observations; power to detect modest effects is low",
                "Market cap uses current total supply as a constant; error under one percent over the window",
                "The contemporaneous specification is reported only for comparison; it is exposed to reverse causality",
                "Association, not causation: no instrument exists for buyback timing",
            ],
        },
        "results": results,
        "weekly": weekly_rows,
        "nw_lags": NW_LAGS,
        "interpretation": interpretation,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    DOCS_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT, DOCS_OUT)

    print(f"Price link; {h['n_weeks']} weeks since {FEE_SWITCH}")
    for name, r in results.items():
        p = f", perm p={r['permutation_p']}" if "permutation_p" in r else ""
        print(f"  {name}: coef {r['coef_intensity']}, t {r['t_intensity']}{p} (n={r['n_weeks']})")
    print(interpretation)
    print(f"Wrote {OUT.relative_to(ROOT)} and {DOCS_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
