"""
Monte Carlo volume forecast and break-even probability for NEAR Intents.

Three simulation methods — results compared, not cherry-picked:

  1. GBM-Normal   : standard Geometric Brownian Motion, Z ~ N(0,1)
  2. GBM-StudentT : GBM with Student-t residuals, df estimated by MLE (ν=2.66)
                    Directly models the fat tails confirmed by Shapiro-Wilk p≈0.
  3. Block-Bootstrap: resample 30-day historical blocks with replacement.
                    Preserves autocorrelation and regime structure without distributional
                    assumptions. No parametric model needed.

Parameters for GBM variants derived from three windows — all data-driven:
  30d  (recent):    mu=-0.01385/day, sigma=0.3423/day  [pessimistic]
  90d  (mid-term):  mu=+0.00138/day, sigma=0.3525/day  [base case]
  full (692d hist): mu=+0.01133/day, sigma=0.6192/day  [optimistic — includes early growth phase]

Student-t degrees-of-freedom estimated by MLE on full log-return series: ν=2.66
  ν < 4 means variance is theoretically infinite — extreme tail events are plausible.
  GBM-Normal systematically underestimates these tails.

Falsification threshold (stated up front):
  If the realised 7-day average volume 12 months from now is below $60M
  (less than half today's $125M), the base-case (90d) scenario is rejected.
  At that point the pessimistic (30d) scenario becomes the operative model.

Inputs:  data/raw/daily_metrics.parquet
Outputs: data/model/forecast.json
"""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats as spstats

ROOT     = Path(__file__).parent.parent
DATA_IN  = ROOT / "data" / "raw" / "daily_metrics.parquet"
DATA_OUT = ROOT / "data" / "model" / "forecast.json"

N_SIMS       = 10_000
HORIZON_DAYS = 365 * 3
BLOCK_SIZE   = 30        # days per block in block-bootstrap
SEED         = 42

BE_HSP029 = 424e6
BE_25PCT  = 663e6

PERCENTILES  = [5, 25, 50, 75, 95]
CHECK_MONTHS = [12, 24, 36]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> tuple[np.ndarray, np.ndarray, float, str]:
    df = pd.read_parquet(DATA_IN)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    vol      = df["volume_usd"].values.astype(float)
    log_ret  = np.diff(np.log(vol))
    start    = float(df["volume_usd"].tail(7).mean())
    last_dt  = str(df["date"].iloc[-1].date())
    return vol, log_ret, start, last_dt


# ---------------------------------------------------------------------------
# Simulation engines
# ---------------------------------------------------------------------------

def _gbm_paths(
    start: float,
    mu: float,
    sigma: float,
    n: int,
    horizon: int,
    rng: np.random.Generator,
    t_df: float | None = None,
) -> np.ndarray:
    """
    GBM simulation. If t_df is given, draws residuals from Student-t(t_df)
    scaled to unit variance (only valid for t_df > 2).
    """
    paths = np.empty((n, horizon + 1))
    paths[:, 0] = start
    drift = mu - 0.5 * sigma ** 2
    for t in range(1, horizon + 1):
        if t_df is not None and t_df > 2:
            # Scale t-draws to unit variance: std(t(df)) = sqrt(df/(df-2))
            scale = np.sqrt((t_df - 2.0) / t_df)
            z = rng.standard_t(t_df, size=n) * scale
        else:
            z = rng.standard_normal(n)
        paths[:, t] = paths[:, t - 1] * np.exp(drift + sigma * z)
    return paths


def _bootstrap_paths(
    log_ret: np.ndarray,
    start: float,
    n: int,
    horizon: int,
    block_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Block bootstrap: resample 30-day blocks of historical log returns with
    replacement. Preserves autocorrelation and any regime structure present
    in the data without distributional assumptions.
    """
    n_blocks_needed = (horizon // block_size) + 2
    # Build array of non-overlapping blocks
    n_full_blocks = len(log_ret) // block_size
    blocks = log_ret[: n_full_blocks * block_size].reshape(n_full_blocks, block_size)

    paths = np.empty((n, horizon + 1))
    paths[:, 0] = start
    for i in range(n):
        idx     = rng.integers(0, n_full_blocks, size=n_blocks_needed)
        sampled = blocks[idx].ravel()[:horizon]
        paths[i, 1:] = start * np.exp(np.cumsum(sampled))
    return paths


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def crossing_probs(paths: np.ndarray, threshold: float) -> dict[str, float]:
    result = {}
    days_per_month = 365.25 / 12
    for m in CHECK_MONTHS:
        day = min(int(m * days_per_month), paths.shape[1] - 1)
        ever = (paths[:, 1: day + 1] >= threshold).any(axis=1)
        result[str(m)] = float(ever.mean())
    return result


def pct_paths(paths: np.ndarray, step_weeks: int = 4) -> dict[str, list[float]]:
    week_days = list(range(0, paths.shape[1], step_weeks * 7))
    out = {}
    for p in PERCENTILES:
        out[str(p)] = [float(np.percentile(paths[:, d], p)) for d in week_days]
    out["week_indices"] = week_days
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> dict:
    vol, log_ret, start, last_dt = load_data()

    # Fit Student-t by MLE — do not hand-pick df
    t_df, t_loc, t_scale = spstats.t.fit(log_ret)
    # Rescale sigma to match empirical std when using t residuals
    t_sigma_adj = float(np.std(log_ret))  # use same sigma, different tail shape

    rng = np.random.default_rng(SEED)

    scenarios: dict[str, dict] = {}

    # --- GBM-Normal, three parameter windows ---
    for label, window in [("30d", 30), ("90d", 90), ("full", len(log_ret))]:
        r   = log_ret[-window:]
        mu  = float(r.mean())
        sig = float(r.std())
        paths = _gbm_paths(start, mu, sig, N_SIMS, HORIZON_DAYS, rng)
        scenarios[f"gbm_normal_{label}"] = {
            "method": "GBM-Normal",
            "window": label,
            "params": {"mu": mu, "sigma": sig, "t_df": None},
            "crossing_probs": {
                "hsp029_424M": crossing_probs(paths, BE_HSP029),
                "cap25_663M":  crossing_probs(paths, BE_25PCT),
            },
            "percentile_paths": pct_paths(paths),
        }

    # --- GBM-StudentT, 90d params (base case with fat tails) ---
    r90  = log_ret[-90:]
    mu90 = float(r90.mean())
    sig90 = float(r90.std())
    paths_t = _gbm_paths(start, mu90, sig90, N_SIMS, HORIZON_DAYS, rng, t_df=t_df)
    scenarios["gbm_t_90d"] = {
        "method": "GBM-StudentT",
        "window": "90d",
        "params": {"mu": mu90, "sigma": sig90, "t_df": float(t_df)},
        "note": f"Student-t df={t_df:.2f} estimated by MLE; ν<3 means variance theoretically unbounded",
        "crossing_probs": {
            "hsp029_424M": crossing_probs(paths_t, BE_HSP029),
            "cap25_663M":  crossing_probs(paths_t, BE_25PCT),
        },
        "percentile_paths": pct_paths(paths_t),
    }

    # --- Block Bootstrap: two windows ---
    # Full history (692d): includes early explosive growth phase — optimistic upper bound
    # Recent 180d: excludes early phase — more conservative, closer to current regime
    for bb_label, bb_window in [("recent_180d", 180), ("full_692d", len(log_ret))]:
        ret_slice = log_ret[-bb_window:]
        paths_bb = _bootstrap_paths(ret_slice, start, N_SIMS, HORIZON_DAYS, BLOCK_SIZE, rng)
        note = (
            "Recent 180d only — excludes early protocol growth phase; representative of current regime"
            if bb_window == 180
            else "Full 692d history — includes early explosive growth phase (Dec 2024–mid 2025); upper bound estimate"
        )
        scenarios[f"block_bootstrap_{bb_label}"] = {
            "method": "Block-Bootstrap",
            "window": f"{bb_label} ({len(ret_slice)}d returns, {BLOCK_SIZE}d blocks)",
            "params": {"block_size": BLOCK_SIZE, "n_blocks": len(ret_slice) // BLOCK_SIZE, "window_days": bb_window},
            "note": note,
            "crossing_probs": {
                "hsp029_424M": crossing_probs(paths_bb, BE_HSP029),
                "cap25_663M":  crossing_probs(paths_bb, BE_25PCT),
            },
            "percentile_paths": pct_paths(paths_bb),
        }

    output = {
        "meta": {
            "start_vol_usd": start,
            "start_date": last_dt,
            "n_sims": N_SIMS,
            "horizon_days": HORIZON_DAYS,
            "seed": SEED,
            "break_even_thresholds": {"hsp029_424M": BE_HSP029, "cap25_663M": BE_25PCT},
            "student_t_fit": {"df": float(t_df), "loc": float(t_loc), "scale": float(t_scale)},
            "falsification_threshold": {
                "description": "Model base case rejected if",
                "condition": "7-day average volume < $60M sustained for 60+ days (less than half current $125M)",
                "action": "Switch to pessimistic (30d) scenario as operative model",
            },
            "caveats": [
                f"Student-t df={t_df:.2f}: variance theoretically infinite (ν<3); extreme events underestimated even by t-GBM",
                "GBM variants assume price-independent volume; NEAR price correlation not modelled",
                "Block-bootstrap captures historical regime structure but cannot model structural breaks",
                "Break-even thresholds fixed at current NEAR price ($4.37); use dashboard sliders for price sensitivity",
                "Probabilities equal across time horizons: high daily vol means paths either spike early or drift permanently below threshold",
            ],
        },
        "scenarios": scenarios,
    }

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(output, indent=2))
    return output


if __name__ == "__main__":
    result = run()
    meta = result["meta"]
    print(f"Forecast — {meta['n_sims']:,} sims, {meta['horizon_days']}d horizon")
    print(f"Start: ${meta['start_vol_usd']/1e6:.1f}M  Date: {meta['start_date']}")
    print(f"Student-t fit: df={meta['student_t_fit']['df']:.2f}")
    print()
    print(f"{'Scenario':<25} {'Method':<18} {'P($424M) 12/24/36mo':<28} {'P($663M) 12/24/36mo'}")
    print("-" * 95)
    for k, sc in result["scenarios"].items():
        cp_h = sc["crossing_probs"]["hsp029_424M"]
        cp_c = sc["crossing_probs"]["cap25_663M"]
        h = f"{cp_h['12']:.1%}/{cp_h['24']:.1%}/{cp_h['36']:.1%}"
        c = f"{cp_c['12']:.1%}/{cp_c['24']:.1%}/{cp_c['36']:.1%}"
        print(f"{k:<25} {sc['method']:<18} {h:<28} {c}")
    print()
    print(f"Falsification: {meta['falsification_threshold']['condition']}")
    print(f"Output: {DATA_OUT}")
