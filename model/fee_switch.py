"""
Difference-in-differences analysis of the Feb 23, 2026 NEAR Intents fee switch.

Design:
  Treatment : NEAR Intents; fee switch activated Feb 23, 2026
  Controls  : 1inch, Paraswap, Jupiter (3 aggregators, all from DefiLlama)
  Window    : 90 days pre / 90 days post the switch date
  Outcome   : log daily volume (multiplicative DiD)

ATT (Average Treatment effect on the Treated):
  ATT_log = log_growth_NEAR - mean(log_growth_controls)
  ATT_ratio = exp(ATT_log)   [multiplicative: 1.0 = no effect]

Permutation (placebo) test; addresses the "only 2 controls" concern:
  Re-run DiD treating each control as the "treatment" unit in turn, using the
  remaining units as controls. Collect the distribution of placebo ATTs.
  If the real NEAR ATT sits outside the central 80% of the placebo distribution,
  it is a statistically unusual result. With 4 units (NEAR + 3 controls) this
  gives 4 permutations; small but standard for this design (Ferman-Pinto 2019).

Bootstrap CI on ATT:
  Resample pre-period and post-period rows for each unit independently,
  1000 draws. Report 95% CI as [2.5th, 97.5th] percentile of bootstrap ATT.

Parallel trends test:
  OLS slope on log-volume vs time in the pre-period for each unit.
  If NEAR and controls have similar pre-period slopes, the parallel trends
  assumption is plausible. Reported as a diagnostic, not a pass/fail gate.

What we do NOT claim:
  - Causality: the DiD identifies relative volume change, not the cause
  - 90-day window coincided with a broader DeFi volume slowdown
  - NEAR was a growing protocol vs mature controls; different baseline dynamics

Inputs:  data/raw/daily_metrics.parquet, DefiLlama API (live fetch)
Outputs: data/model/fee_switch.json
"""

from __future__ import annotations

import json
import time
import numpy as np
import pandas as pd
import urllib.request
from pathlib import Path

ROOT     = Path(__file__).parent.parent
DATA_IN  = ROOT / "data" / "raw" / "daily_metrics.parquet"
DATA_OUT = ROOT / "data" / "model" / "fee_switch.json"

FEE_SWITCH_DATE = pd.Timestamp("2026-02-23")
WINDOW_DAYS     = 90
BOOTSTRAP_N     = 1_000
SEED            = 42

CONTROLS = {
    "1inch":    "https://api.llama.fi/summary/aggregators/1inch?excludeTotalDataChart=false&dataType=dailyVolume",
    "paraswap": "https://api.llama.fi/summary/aggregators/paraswap?excludeTotalDataChart=false&dataType=dailyVolume",
    "jupiter":  "https://api.llama.fi/summary/dexs/jupiter?excludeTotalDataChart=false&dataType=dailyVolume",
}
CACHE_DIR = ROOT / "data" / "raw" / "controls"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def fetch_defillama(url: str, label: str) -> pd.DataFrame:
    """Fetch from DefiLlama with disk cache. Returns cached data if network unavailable."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{label}.parquet"

    try:
        time.sleep(1.2)
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
        rows = data.get("totalDataChart", [])
        df = pd.DataFrame(rows, columns=["ts", "volume_usd"])
        df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_localize(None)
        df["protocol"] = label
        df = df[["date", "volume_usd", "protocol"]].sort_values("date").reset_index(drop=True)
        df.to_parquet(cache_path)
        return df
    except Exception as fetch_err:
        if cache_path.exists():
            df = pd.read_parquet(cache_path)
            df["protocol"] = label
            print(f"  [{label}] network failed, loaded from cache ({len(df)} rows): {fetch_err}")
            return df
        raise


def load_near() -> pd.DataFrame:
    df = pd.read_parquet(DATA_IN)
    df["date"] = pd.to_datetime(df["date"])
    df["protocol"] = "near_intents"
    return df[["date", "volume_usd", "protocol"]].sort_values("date").reset_index(drop=True)


def get_window(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pre_start = FEE_SWITCH_DATE - pd.Timedelta(days=WINDOW_DAYS)
    post_end  = FEE_SWITCH_DATE + pd.Timedelta(days=WINDOW_DAYS)
    pre  = df[(df.date >= pre_start)  & (df.date < FEE_SWITCH_DATE)].copy()
    post = df[(df.date >= FEE_SWITCH_DATE) & (df.date <= post_end)].copy()
    return pre, post


# ---------------------------------------------------------------------------
# Core statistics
# ---------------------------------------------------------------------------

def log_growth(pre: pd.DataFrame, post: pd.DataFrame) -> float | None:
    pre_avg  = pre.volume_usd.mean()
    post_avg = post.volume_usd.mean()
    if pre_avg > 0 and post_avg > 0:
        return float(np.log(post_avg / pre_avg))
    return None


def pre_slope(pre: pd.DataFrame) -> float | None:
    if len(pre) < 7:
        return None
    y = np.log(pre.volume_usd.values.astype(float))
    valid = np.isfinite(y)
    if valid.sum() < 7:
        return None
    x = np.arange(len(y), dtype=float)[valid]
    y = y[valid]
    return float(np.polyfit(x, y, 1)[0])


def att(near_lg: float, ctrl_lgs: list[float]) -> float | None:
    valid = [v for v in ctrl_lgs if v is not None]
    if not valid or near_lg is None:
        return None
    return near_lg - float(np.mean(valid))


# ---------------------------------------------------------------------------
# Permutation test
# ---------------------------------------------------------------------------

def permutation_test(all_lgs: dict[str, float | None]) -> dict:
    """
    For each unit u, treat u as the "treated" unit and compute ATT using
    the remaining units as controls. Collect the distribution of placebo ATTs.
    """
    units = {k: v for k, v in all_lgs.items() if v is not None}
    if len(units) < 3:
        return {"note": "Insufficient units for permutation test", "placebo_atts": {}, "real_rank": None}

    labels  = list(units.keys())
    values  = list(units.values())
    placebo_atts = {}
    for i, label in enumerate(labels):
        controls_lg = [values[j] for j in range(len(labels)) if j != i]
        placebo_atts[label] = float(values[i] - np.mean(controls_lg))

    real_att = placebo_atts.get("near_intents")
    if real_att is None:
        return {"placebo_atts": placebo_atts, "real_rank": None, "note": "NEAR not in units"}

    all_vals = list(placebo_atts.values())
    rank     = sum(1 for v in all_vals if v <= real_att)
    pct_rank = rank / len(all_vals)

    return {
        "placebo_atts": {k: float(v) for k, v in placebo_atts.items()},
        "real_att":     real_att,
        "rank":         rank,
        "percentile":   pct_rank,
        "note": (
            f"NEAR ATT ranks {rank}/{len(all_vals)} among permutations "
            f"(percentile={pct_rank:.0%}). "
            + ("NEAR is an outlier; result is unusual relative to controls."
               if pct_rank > 0.8 or pct_rank < 0.2
               else "NEAR is not an outlier; consistent with no treatment effect.")
        ),
    }


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------

def bootstrap_att_ci(
    near_pre: pd.DataFrame,
    near_post: pd.DataFrame,
    ctrl_pre_post: list[tuple[pd.DataFrame, pd.DataFrame]],
    n: int,
    seed: int,
) -> dict:
    rng  = np.random.default_rng(seed)
    atts = []
    for _ in range(n):
        # Resample pre and post rows for NEAR
        np_pre  = near_pre.volume_usd.values
        np_post = near_post.volume_usd.values
        bs_near_pre  = rng.choice(np_pre,  size=len(np_pre),  replace=True)
        bs_near_post = rng.choice(np_post, size=len(np_post), replace=True)
        near_lg_bs = float(np.log(bs_near_post.mean() / bs_near_pre.mean())) if bs_near_pre.mean() > 0 else None

        # Resample controls
        ctrl_lgs_bs = []
        for cp, cpo in ctrl_pre_post:
            cp_arr  = cp.volume_usd.values
            cpo_arr = cpo.volume_usd.values
            if len(cp_arr) == 0 or len(cpo_arr) == 0:
                continue
            bs_pre  = rng.choice(cp_arr,  size=len(cp_arr),  replace=True)
            bs_post = rng.choice(cpo_arr, size=len(cpo_arr), replace=True)
            if bs_pre.mean() > 0:
                ctrl_lgs_bs.append(float(np.log(bs_post.mean() / bs_pre.mean())))

        a = att(near_lg_bs, ctrl_lgs_bs)
        if a is not None:
            atts.append(a)

    if len(atts) < 10:
        return {
            "att_ratio_lo": None, "att_ratio_hi": None,
            "att_log_lo": None, "att_log_hi": None,
            "n_bootstrap": len(atts),
            "note": f"Insufficient valid bootstrap samples ({len(atts)}); likely control data gaps in window",
        }
    atts_arr = np.array(atts)
    ci_lo = float(np.percentile(atts_arr, 2.5))
    ci_hi = float(np.percentile(atts_arr, 97.5))
    return {
        "att_ratio_lo": float(np.exp(ci_lo)),
        "att_ratio_hi": float(np.exp(ci_hi)),
        "att_log_lo":   ci_lo,
        "att_log_hi":   ci_hi,
        "n_bootstrap":  len(atts),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _interpret_did(att_ratio: float | None, bsci: dict) -> str:
    if not att_ratio:
        return "Insufficient data"
    lo, hi = bsci.get("att_ratio_lo"), bsci.get("att_ratio_hi")
    if lo is None or hi is None:
        return f"NEAR volume changed by {att_ratio:.2f}x relative to controls. Bootstrap CI not available."
    ci_str = f"(95% CI: {lo:.2f}-{hi:.2f}x)"
    incl = lo <= 1.0 <= hi
    return (
        f"NEAR volume changed by {att_ratio:.2f}x {ci_str} relative to aggregator controls "
        f"in the 90 days after the fee switch. "
        + ("CI includes 1.0; no statistically significant volume impact detected."
           if incl
           else f"CI excludes 1.0; suggests {'positive' if att_ratio > 1 else 'negative'} impact at 95% confidence.")
    )


def run() -> dict:
    near_df = load_near()
    near_pre, near_post = get_window(near_df)

    ctrl_data: dict[str, pd.DataFrame] = {}
    ctrl_errors: dict[str, str] = {}
    for label, url in CONTROLS.items():
        try:
            ctrl_data[label] = fetch_defillama(url, label)
        except Exception as e:
            ctrl_errors[label] = str(e)

    # Window stats per unit
    units: dict[str, dict] = {}
    units["near_intents"] = {
        "pre_avg":   float(near_pre.volume_usd.mean()),
        "post_avg":  float(near_post.volume_usd.mean()),
        "pre_days":  len(near_pre),
        "post_days": len(near_post),
        "log_growth": log_growth(near_pre, near_post),
        "growth_ratio": float(near_post.volume_usd.mean() / near_pre.volume_usd.mean()) if near_pre.volume_usd.mean() > 0 else None,
        "pre_slope":  pre_slope(near_pre),
    }

    ctrl_pre_post_pairs = []
    for label, df in ctrl_data.items():
        cp, cpo = get_window(df)
        ctrl_pre_post_pairs.append((cp, cpo))
        units[label] = {
            "pre_avg":    float(cp.volume_usd.mean()) if len(cp) > 0 else None,
            "post_avg":   float(cpo.volume_usd.mean()) if len(cpo) > 0 else None,
            "pre_days":   len(cp),
            "post_days":  len(cpo),
            "log_growth": log_growth(cp, cpo),
            "growth_ratio": float(cpo.volume_usd.mean() / cp.volume_usd.mean()) if len(cp) > 0 and cp.volume_usd.mean() > 0 else None,
            "pre_slope":  pre_slope(cp),
        }

    for label, err in ctrl_errors.items():
        units[label] = {"error": err}

    # ATT point estimate
    near_lg   = units["near_intents"]["log_growth"]
    ctrl_lgs  = [units[k].get("log_growth") for k in ctrl_data]
    att_log   = att(near_lg, ctrl_lgs)
    att_ratio = float(np.exp(att_log)) if att_log is not None else None

    # Permutation test
    all_lgs = {k: units[k].get("log_growth") for k in units if "error" not in units[k]}
    perm    = permutation_test(all_lgs)

    # Bootstrap CI
    bsci = bootstrap_att_ci(near_pre, near_post, ctrl_pre_post_pairs, BOOTSTRAP_N, SEED)

    # Parallel trends
    near_slope = units["near_intents"].get("pre_slope")
    ctrl_slopes = [units[k].get("pre_slope") for k in ctrl_data if "error" not in units.get(k, {})]
    valid_slopes = [s for s in ctrl_slopes if s is not None]
    pt_diff = abs(near_slope - np.mean(valid_slopes)) if near_slope and valid_slopes else None

    # Full history for context
    all_pre  = near_df[near_df.date < FEE_SWITCH_DATE]
    all_post = near_df[near_df.date >= FEE_SWITCH_DATE]

    output = {
        "meta": {
            "fee_switch_date": str(FEE_SWITCH_DATE.date()),
            "window_days":     WINDOW_DAYS,
            "treatment":       "near_intents",
            "controls":        list(CONTROLS.keys()),
            "methodology":     "Difference-in-differences on log daily volume; 90-day symmetric window",
            "caveats": [
                "4 units total (NEAR + 3 controls); permutation distribution has only 4 points; interpret with caution",
                "Controls (1inch, Paraswap, Jupiter) are larger/more mature protocols; different growth dynamics from a young NEAR Intents",
                "90-day window coincided with broader DeFi volume contraction; market cycle not isolated",
                "DiD identifies relative performance vs controls, not absolute causal effect of the fee switch",
                "Bootstrap CI resamples within pre/post periods independently; temporal autocorrelation within periods not preserved",
            ],
        },
        "units": units,
        "did_estimate": {
            "att_log":   float(att_log) if att_log is not None else None,
            "att_ratio": att_ratio,
            "bootstrap_ci_95": bsci,
            "interpretation": _interpret_did(att_ratio, bsci),
        },
        "permutation_test": perm,
        "parallel_trends": {
            "near_slope":          float(near_slope) if near_slope else None,
            "control_slopes":      {k: units[k].get("pre_slope") for k in ctrl_data},
            "mean_control_slope":  float(np.mean(valid_slopes)) if valid_slopes else None,
            "slope_diff_near_vs_controls": float(pt_diff) if pt_diff else None,
            "assessment": (
                "Pre-period slopes similar; parallel trends assumption plausible"
                if pt_diff is not None and pt_diff < 0.005
                else "Pre-period slopes differ; DiD estimate may conflate trends with treatment effect"
            ),
        },
        "full_history_context": {
            "pre_avg_usd":  float(all_pre.volume_usd.mean()),
            "post_avg_usd": float(all_post.volume_usd.mean()),
            "pre_days":     len(all_pre),
            "post_days":    len(all_post),
            "growth_ratio": float(all_post.volume_usd.mean() / all_pre.volume_usd.mean()),
            "note": "Full pre/post split includes NEAR Intents early growth phase (Dec 2024 onward); inflates apparent post-switch growth",
        },
    }

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(output, indent=2))
    return output


if __name__ == "__main__":
    result = run()
    print(f"Fee switch DiD; window ±{result['meta']['window_days']}d around {result['meta']['fee_switch_date']}")
    print()
    print(f"{'Unit':<15} {'Pre avg':>12} {'Post avg':>12} {'Growth':>8} {'Pre slope':>12}")
    print("-" * 65)
    for k, u in result["units"].items():
        if "error" in u:
            print(f"{k:<15} ERROR: {u['error'][:40]}")
            continue
        pre  = f"${u['pre_avg']/1e6:.1f}M" if u.get("pre_avg") else "n/a"
        post = f"${u['post_avg']/1e6:.1f}M" if u.get("post_avg") else "n/a"
        gr   = f"{u['growth_ratio']:.2f}x" if u.get("growth_ratio") else "n/a"
        sl   = f"{u['pre_slope']:.5f}" if u.get("pre_slope") else "n/a"
        print(f"{k:<15} {pre:>12} {post:>12} {gr:>8} {sl:>12}")
    print()
    did = result["did_estimate"]
    att_str = f"{did['att_ratio']:.3f}x" if did['att_ratio'] else "N/A (controls unavailable)"
    print(f"ATT: {att_str}  {did['interpretation']}")
    perm = result["permutation_test"]
    print(f"Permutation: {perm['note']}")
    pt = result["parallel_trends"]
    print(f"Parallel trends: {pt['assessment']}")
    print(f"\nOutput: {DATA_OUT}")
