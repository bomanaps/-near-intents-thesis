# NEAR Intents Investment Thesis

A quantitative model that answers one question: at what daily volume do NEAR Intents protocol buybacks cover NEAR token issuance? Built for the NEAR Hackathon 2026, Investment Thesis track.

## Live Site

| Page | Link |
|---|---|
| Landing page | https://bomanaps.github.io/-near-intents-thesis/ |
| Break-Even Explorer (interactive) | https://bomanaps.github.io/-near-intents-thesis/dashboard.html |
| Investment Thesis Memo | https://bomanaps.github.io/-near-intents-thesis/thesis-memo.html |

## Key Findings

| Metric | Value |
|---|---|
| Current daily volume (30d avg) | $127M |
| Current offset ratio | 19.2% |
| Break-even at 2.5% issuance cap | $663M / day |
| Break-even at 1.6% cap (HSP-029 floor) | $424M / day |
| Capture rate (30d trailing) | 5.91 bps |
| HSP-029 activation | Nov 2, 2026 |

HSP-029 cuts the issuance cap from 2.5% to 1.6% over 24 months. At flat volume and current capture rate, this raises the offset ratio from 19.2% today to 30.0% by late 2028. Break-even still requires 3.3x volume growth at the 1.6% floor.

## What It Measures

**Break-even formula:**

```
B = V * r / P        # daily NEAR bought back
I = S * cap / 365    # daily NEAR issued
Offset = B / I       # fraction of issuance covered
Break-even volume = I * P / r
```

Where `V` = daily volume (USD), `r` = capture rate, `P` = NEAR price, `S` = circulating supply, `cap` = annual issuance cap.

## Quantitative Models

**Monte Carlo volume forecast** (`model/forecast.py`): 10,000 simulations over a 3-year horizon using six methods: GBM-Normal (30d / 90d / full history), GBM-StudentT (degrees of freedom ν=2.66, fitted by MLE), and block-bootstrap (recent 180d and full 692d). Probability of crossing the $424M break-even ranges from 17% under the pessimistic scenario to 99% under the full-history upper bound. The range is the answer, not any single number.

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
python model/forecast.py        # Monte Carlo forecast -> data/model/forecast.json
python model/fee_switch.py      # DiD analysis -> data/model/fee_switch.json
```

Open `docs/index.html` locally or visit the live site linked above.

## Files

```
docs/
  index.html          landing page
  dashboard.html      interactive break-even explorer
  thesis-memo.html    written investment thesis

model/
  forecast.py         Monte Carlo volume forecast
  fee_switch.py       difference-in-differences analysis

ingest/
  fastnear_ingest.py  FastNEAR on-chain event ingestion
  watchdog.sh         process monitor with macOS notification

data/
  raw/
    daily_metrics.parquet   692-day DefiLlama history
  model/
    forecast.json           Monte Carlo output
    fee_switch.json         DiD output
```

## Track

NEAR Hackathon 2026, Investment Thesis
Deadline: November 14, 2026
