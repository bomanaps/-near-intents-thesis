"""
Volume forecast for NEAR Intents: probability of sustained break-even crossing.

Model choice. Daily Intents volume is noisy and mean-reverting; its log changes
are not a diffusion. An earlier version of this model used GBM on daily volume
and was rejected for two reasons, stated here deliberately:

  1. Calibration: estimating mu as the mean of log returns and then applying
     drift = mu - 0.5 sigma^2 double-counts the Ito correction. With daily
     sigma near 0.35 that subtracts several percent of drift per day and
     collapses simulated paths toward zero.
  2. Specification: daily sigma near 0.35 compounds to sigma*sqrt(365) ~ 6.8
     over a year, so one-year GBM paths span absurd ranges and any crossing
     probability is an artifact of that dispersion, under either calibration
     convention.

Replacement: an AR(1) process fitted on the log of 30-day-average volume
(residual bootstrap, no normality assumption), plus a 30-day block bootstrap
of daily log returns as a non-parametric comparison. Break-even is defined as
a SUSTAINED crossing: the 30-day average volume reaching the threshold, not a
one-day spike touching it.

Thresholds are computed at run time from the same identity the dashboard uses:
threshold = supply * cap / 365 * price / capture, with the live NEAR price
(fallback to the last recorded price when offline) and the 30-day mean
revenue capture rate from the parquet.

Inputs:  data/raw/daily_metrics.parquet
Output:  data/model/forecast.json
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_IN = ROOT / "data" / "raw" / "daily_metrics.parquet"
DATA_OUT = ROOT / "data" / "model" / "forecast.json"

SUPPLY = 1_309_640_573
CAPS = {"cap25": 0.025, "cap16": 0.016}
FALLBACK_PRICE = 3.85
PRICE_URL = "https://coins.llama.fi/prices/current/coingecko:near"

N_SIMS = 10_000
HORIZON_DAYS = 365 * 3
SEED = 42
SMOOTH_DAYS = 30
BLOCK_SIZE = 30
HORIZON_MONTHS = (12, 24, 36)


def fetch_price() -> tuple[float, str]:
    try:
        with urllib.request.urlopen(PRICE_URL, timeout=15) as r:
            price = json.load(r)["coins"]["coingecko:near"]["price"]
        return float(price), "coins.llama.fi live"
    except Exception:
        return FALLBACK_PRICE, "fallback constant (live fetch unavailable)"


def load_data() -> tuple[np.ndarray, np.ndarray, float, str, float]:
    df = pd.read_parquet(DATA_IN)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    vol = df["volume_usd"].values.astype(float)
    smooth = pd.Series(vol).rolling(SMOOTH_DAYS).mean().dropna().values
    capture_bps = float(df["rev_capture_bps"].tail(30).mean())
    last_dt = str(df["date"].iloc[-1].date())
    return vol, smooth, capture_bps, last_dt, float(smooth[-1])


def fit_rw_drift(log_smooth: np.ndarray) -> dict:
    diffs = np.diff(log_smooth)
    x, y = log_smooth[:-1], log_smooth[1:]
    phi_unconstrained, _ = np.polyfit(x, y, 1)
    drift = float(diffs.mean())
    resid = diffs - drift
    return {
        "drift": drift,
        "resid": resid,
        "sigma_resid": float(resid.std(ddof=1)),
        "phi_unconstrained": float(phi_unconstrained),
        "annualized_drift": float(np.exp(drift * 365) - 1),
    }


def simulate_rw_drift(fit: dict, start_log: float, rng: np.random.Generator) -> np.ndarray:
    eps = rng.choice(fit["resid"], size=(N_SIMS, HORIZON_DAYS))
    steps = fit["drift"] + eps
    logs = start_log + np.cumsum(steps, axis=1)
    logs = np.hstack([np.full((N_SIMS, 1), start_log), logs])
    return np.exp(logs)


def simulate_block_bootstrap(
    log_ret: np.ndarray, start: float, rng: np.random.Generator
) -> np.ndarray:
    n_blocks = len(log_ret) // BLOCK_SIZE
    blocks = log_ret[: n_blocks * BLOCK_SIZE].reshape(n_blocks, BLOCK_SIZE)
    need = HORIZON_DAYS // BLOCK_SIZE + 2
    idx = rng.integers(0, n_blocks, size=(N_SIMS, need))
    rets = blocks[idx].reshape(N_SIMS, -1)[:, :HORIZON_DAYS]
    daily = start * np.exp(np.cumsum(rets, axis=1))
    daily = np.hstack([np.full((N_SIMS, 1), start), daily])
    smooth = np.empty_like(daily)
    csum = np.cumsum(daily, axis=1)
    for t in range(daily.shape[1]):
        lo = max(0, t - SMOOTH_DAYS + 1)
        width = t - lo + 1
        smooth[:, t] = (csum[:, t] - (csum[:, lo - 1] if lo > 0 else 0)) / width
    return smooth


def crossing_probs(smooth_paths: np.ndarray, thresholds: dict) -> dict:
    out = {}
    for key, thr in thresholds.items():
        out[key] = {}
        for months in HORIZON_MONTHS:
            days = int(months * 30.44)
            crossed = (smooth_paths[:, : days + 1] >= thr).any(axis=1)
            out[key][str(months)] = round(float(crossed.mean()), 4)
    return out


def drift_label(annual_growth: float) -> str:
    if annual_growth >= 0.15:
        return "positive drift"
    if annual_growth <= -0.15:
        return "negative drift"
    return "flat drift"


def main() -> None:
    rng = np.random.default_rng(SEED)
    vol, smooth, capture_bps, last_dt, start_smooth = load_data()
    price, price_source = fetch_price()
    rate = capture_bps / 10_000

    thresholds = {
        key: SUPPLY * cap / 365 * price / rate for key, cap in CAPS.items()
    }
    thr_labels = {
        key: f"${thresholds[key]/1e6:.0f}M ({int(CAPS[key]*1000)/10}% cap)"
        for key in thresholds
    }

    log_smooth_180 = np.log(smooth[-180:])
    log_ret = np.diff(np.log(vol))

    scenarios = {}

    log_smooth_365 = np.log(smooth[-365:])
    for key, series, window in (
        ("rw_drift_365d", log_smooth_365, "365d"),
        ("rw_drift_recent_180d", log_smooth_180, "180d"),
    ):
        fit = fit_rw_drift(series)
        paths = simulate_rw_drift(fit, np.log(start_smooth), rng)
        scenarios[key] = {
            "method": "random walk with drift on log 30d-average volume, residual bootstrap",
            "window": window,
            "label": f"Trend {window}",
            "note": f"{drift_label(fit['annualized_drift'])} ({fit['annualized_drift']*100:+.0f}%/yr) · unit root imposed (fitted phi {fit['phi_unconstrained']:.3f})",
            "params": {
                "daily_drift": round(fit["drift"], 6),
                "annualized_drift": round(fit["annualized_drift"], 4),
                "sigma_resid": round(fit["sigma_resid"], 5),
                "phi_unconstrained": round(fit["phi_unconstrained"], 4),
            },
            "crossing_probs": crossing_probs(paths, thresholds),
        }

    for key, rets, window, upper in (
        ("block_bootstrap_recent_180d", log_ret[-180:], "180d", False),
        ("block_bootstrap_full", log_ret, f"{len(log_ret)}d", True),
    ):
        paths = simulate_block_bootstrap(rets, vol[-1], rng)
        mean_ret = float(np.mean(rets)) * 365
        note = f"30d blocks of daily log returns · {drift_label(mean_ret)}"
        if upper:
            note += " · includes early growth phase · upper bound"
        scenarios[key] = {
            "method": "30d block bootstrap of daily log returns",
            "window": window,
            "label": f"Bootstrap {window}",
            "note": note,
            "params": {
                "mean_daily_log_ret": round(float(np.mean(rets)), 5),
                "sigma_daily": round(float(np.std(rets)), 4),
            },
            "crossing_probs": crossing_probs(paths, thresholds),
        }

    result = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_through": last_dt,
            "n_sims": N_SIMS,
            "horizon_days": HORIZON_DAYS,
            "seed": SEED,
            "start_smooth_vol_usd": round(start_smooth, 0),
            "capture_bps_30d": round(capture_bps, 2),
            "near_price": round(price, 4),
            "price_source": price_source,
            "supply": SUPPLY,
            "break_even_thresholds": {
                key: {"usd": round(thresholds[key], 0), "label": thr_labels[key]}
                for key in thresholds
            },
            "crossing_definition": "sustained: 30-day average volume reaches the threshold, not a one-day touch",
            "model_rationale": (
                "GBM on daily volume was tested and rejected: the calibration double-counted "
                "the Ito correction, and daily volatility near 0.35 compounds to a one-year "
                "dispersion that makes any crossing probability an artifact. An unconstrained "
                "AR(1) on the log 30-day average was also tested and rejected: the fitted phi "
                "of roughly 0.998 cannot be distinguished from a unit root, so its implied "
                "stationary level is an unstable extrapolation. The model is therefore a random "
                "walk with drift on the log 30-day average with bootstrapped residuals, plus a "
                "30-day block bootstrap of daily returns as a non-parametric check."
            ),
            "caveats": [
                f"Drift estimated from a trending window extrapolates that trend; {scenarios['rw_drift_365d']['params']['annualized_drift']*100:+.0f}%/yr (365d) and {scenarios['rw_drift_recent_180d']['params']['annualized_drift']*100:+.0f}%/yr (180d) are not sustainable indefinitely, so long-horizon probabilities are upper bounds",
                "A random walk cannot anticipate structural breaks, new integrations, or saturation of the current growth driver",
                "Thresholds move with NEAR price and capture rate; they are recomputed at every run and shown in the header",
                "Residual bootstrap preserves the empirical error distribution but assumes errors are exchangeable over time",
                "The two windows disagree because the regime changed; the disagreement is information, not error",
            ],
        },
        "scenarios": scenarios,
    }

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(result, indent=1))

    print(f"Forecast; {N_SIMS:,} sims, {HORIZON_DAYS}d horizon, sustained-crossing definition")
    print(f"Price ${price:.2f} ({price_source}), capture {capture_bps:.2f} bps")
    for key, lab in thr_labels.items():
        print(f"Threshold {key}: {lab}")
    print(f"{'Scenario':<28}{'P(cap16) 12/24/36mo':<28}{'P(cap25) 12/24/36mo'}")
    for key, s in scenarios.items():
        p16 = s["crossing_probs"]["cap16"]
        p25 = s["crossing_probs"]["cap25"]
        print(f"{key:<28}"
              f"{p16['12']*100:.1f}%/{p16['24']*100:.1f}%/{p16['36']*100:.1f}%     "
              f"{p25['12']*100:.1f}%/{p25['24']*100:.1f}%/{p25['36']*100:.1f}%")
    print(f"Output: {DATA_OUT}")


if __name__ == "__main__":
    main()
