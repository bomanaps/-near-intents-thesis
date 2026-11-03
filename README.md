# NEAR Intents Investment Thesis

A quantitative model that answers one question: at what daily volume do NEAR Intents protocol buybacks cover NEAR token issuance? Built for the NEAR Hackathon 2026, Investment Thesis track.

## Live Site

| Page | Link |
|---|---|
| Landing page | https://bomanaps.github.io/-near-intents-thesis/ |
| Break-Even Explorer (interactive) | https://bomanaps.github.io/-near-intents-thesis/dashboard.html |
| Investment Thesis Memo | https://bomanaps.github.io/-near-intents-thesis/thesis-memo.html |

## Key Findings

All figures as of November 2, 2026. The live dashboard fetches current data on every page load.

| Metric | Value |
|---|---|
| Current daily volume (30d avg) | $127M |
| Current offset ratio | 19.2% |
| Break-even at 2.5% issuance cap | $663M / day |
| Break-even at 1.6% cap (HSP-029 floor) | $424M / day |
| Capture rate (30d trailing) | 5.91 bps |
| HSP-029 vote passed | Nov 2, 2026 (ramp pending ratification) |
| Days revenue covered full issuance | 6 of 557 priced days (1.1%) |

HSP-029 cuts the issuance cap from 2.5% to 1.6% over 24 months. The Nov 2 vote is not activation: per the proposal, the ramp starts one full quarter after ratification and validator adoption makes it binding, so the base case assumed here is an April 2027 start, putting the 30.0% flat-volume offset ceiling around April 2029. Break-even still requires 3.3x volume growth at the 1.6% floor. The dashboard exposes the ramp start date as an explicit assumption.

## What It Measures

**Break-even formula:**

```
B = V * r / P        # daily NEAR bought back
I = S * cap / 365    # daily NEAR issued
Offset = B / I       # fraction of issuance covered
Break-even volume = I * P / r
```

Where `V` = daily volume (USD), `r` = capture rate, `P` = NEAR price, `S` = total supply, `cap` = annual issuance cap.

## Quantitative Models

**Volume forecast** (`model/forecast.py`): 10,000 simulations over a 3-year horizon. Break-even is defined as a sustained crossing (the 30-day average volume reaching the threshold, not a one-day spike), and thresholds are recomputed at every run from the live NEAR price and current capture rate. Methods: random walk with drift on the log 30-day average (365d and 180d calibration windows, residual bootstrap) plus a 30-day block bootstrap of daily returns as a non-parametric check. An earlier GBM version was tested and rejected (double-counted Ito correction, absurd one-year dispersion), as was an unconstrained AR(1) (fitted phi near 1 makes its stationary level an unstable extrapolation); the rejection rationale ships inside the model output. As of Nov 3, 2026 the 12-month sustained-crossing probability for the 1.6%-cap threshold spans roughly 33% (conservative 365d trend) to 96% (full-history bootstrap, upper bound). The range is the answer, not any single number, and it regenerates daily.

**On-chain evidence** (`analysis/onchain.py`): decodes raw dip4 settlement events from intents.near and measures what aggregates cannot: the explicit contract fee is ~0.01 bps per side vs the 5.91 bps revenue rate implied by DefiLlama (so the capture rate is policy, not protocol), the top 3 solvers fill 86% of volume (HHI 0.33), and the volume screens clean (zero self-fills). Reruns automatically as ingestion grows.

**Fee-switch difference-in-differences** (`model/fee_switch.py`): DiD analysis of the Feb 23, 2026 protocol fee switch using 1inch, Paraswap, and Jupiter as controls. Average treatment effect: 1.10x (95% bootstrap CI: 0.97-1.25x). Permutation rank: 3/4. No statistically significant negative volume impact detected.

## Data Sources

| Source | Coverage | Status |
|---|---|---|
| DefiLlama API (volume, fees, revenue) | 692 days, Nov 2024 to Nov 2026 | Complete |
| FastNEAR neardata (on-chain events) | intents.near, shard 7, dip4 standard. [Download dataset](https://huggingface.co/datasets/bomankari/near-intents-onchain-events) | Ingesting |
| NEAR RPC (supply, block metadata) | rpc.mainnet.near.org | Complete |

On-chain ingestion is ongoing. DefiLlama data is the primary source for all models. FastNEAR data will provide solver concentration (HHI) and token-pair breakdown once ingestion completes.

## How to Run

```bash
pip install pandas pyarrow scipy numpy aiohttp
python run_all.py               # fetch fresh DefiLlama data, run both models, publish JSONs to docs/data/
python run_all.py --no-fetch    # same, but use the committed data instead of fetching
```

Each model can also run standalone: `python model/forecast.py` or `python model/fee_switch.py`.

The dashboard fetches live DefiLlama data in the browser on every page load (volume, revenue, NEAR price) and reads model outputs from `docs/data/*.json`. If the live fetch fails it falls back to the embedded snapshot and says so in the header badge.

Open `docs/index.html` locally or visit the live site linked above.

## Files

```
run_all.py            one-command pipeline: fetch data, run models, publish JSONs

docs/
  index.html          landing page
  dashboard.html      interactive break-even explorer
  thesis-memo.html    written investment thesis
  data/               model JSONs served to the dashboard by GitHub Pages

model/
  forecast.py         sustained-crossing volume forecast
  fee_switch.py       difference-in-differences analysis

analysis/
  onchain.py          on-chain evidence from decoded dip4 events
  frequency.py        days revenue covered issuance, from price-joined history

ingest/
  fastnear_ingest.py  FastNEAR on-chain event ingestion
  watchdog.sh         process monitor with macOS notification

data/
  raw/
    daily_metrics.parquet   692-day DefiLlama history
  model/
    forecast.json           forecast output
    fee_switch.json         DiD output
```

## How This Entry Differs

Several entries in this track model the same break-even identity. This one is distinguished by what it measured rather than assumed: an open dataset of raw decoded dip4 settlement events ([Hugging Face](https://huggingface.co/datasets/bomankari/near-intents-onchain-events)), the finding that the settlement contract collects ~0.01 bps while the effective capture is 5.91 bps (capture is policy, not protocol), measured solver concentration (top 3 fill 86% of volume), a causal fee-switch counterfactual (DiD vs three controls), and the exact count of days revenue ever covered issuance (6 of 557). The combination of the on-chain fee measurement and the DiD result supports a fee-switch argument no aggregate-data analysis can make.

## Track

NEAR Hackathon 2026, Investment Thesis
Deadline: November 14, 2026
