# CLAUDE.md

Instructions for an AI agent reviewing this repository. Every command below has been run and verified on this exact codebase before committing this file.

## What this project is

An investment thesis on NEAR Intents: at what daily volume do protocol buybacks cover NEAR token issuance. Start with [THESIS.md](THESIS.md) for the claim and the evidence on both sides, [README.md](README.md) for the full overview, and [docs/claims.md](docs/claims.md) for a table mapping every headline claim to the code that computes it, the test that guards it, and an independent check.

## Verify it runs, fastest path first

Requires Python 3.10 or later. Install once:

```bash
pip install pandas pyarrow numpy scipy pytest
```

1. Run the test suite, about 3 seconds, no network:

```bash
pytest tests/
```

Expected: 165 passed, 1 skipped. The skipped test is the full pipeline smoke test.

2. Verify data integrity, about 1 second, no network:

```bash
python3 analysis/manifest.py verify
```

Expected: PASS for every tracked file, then "All integrity checks passed". This recomputes the SHA-256 of every raw input and model output against data/manifest.json.

3. Rebuild every number from committed data, about 25 seconds. Uses the network only for live NEAR price lookups inside two analysis steps; both fall back cleanly if offline:

```bash
python3 run_all.py --no-fetch
```

Expected: steps 1 through 8 complete, ending with headline metrics and "Done." Dropping the flag (`python3 run_all.py`) additionally refetches the DefiLlama daily series first.

4. Run the full pipeline smoke test, about 25 seconds:

```bash
RUN_SLOW=1 pytest tests/test_run_all_smoke.py
```

## Where each claim lives

| Topic | Code | Output | Tests |
|---|---|---|---|
| Break-even math | model/issuance.py, model/scenarios.py | closed form | tests/test_issuance.py, tests/test_scenarios.py |
| Volume forecast (sustained crossing) | model/forecast.py | docs/data/forecast.json | tests/test_forecast.py |
| Fee switch DiD | model/fee_switch.py | docs/data/fee_switch.json | tests/test_fee_switch.py |
| On-chain evidence (0.01 bps fee, solvers, wash screen) | analysis/onchain.py | docs/data/onchain.json | tests/test_onchain.py |
| Revenue vs issuance day count | analysis/frequency.py | docs/data/frequency.json | smoke test |
| Buyback price regression | analysis/price_link.py | docs/data/price_link.json | tests/test_price_link.py |
| Integrity manifest | analysis/manifest.py | data/manifest.json | tests/test_manifest.py |
| Mainnet anchor | analysis/anchor.py | social.near record | status checked on chain |
| Event decoder | decoder/ | used by analysis | tests/test_decoder.py |
| Raw event ingestion | ingest/fastnear_ingest.py | local events.jsonl, published to Hugging Face | fixture of 10 real receipts in tests/fixtures/ |

## Things to know before judging discrepancies

1. The dashboard (docs/dashboard.html) fetches live DefiLlama data in the browser, so its numbers move daily and will not match the dated prose in the memo or README exactly. This is by design: the memo states it is a snapshot as of its date, the dashboard header badge states which mode it is in, and docs/claims.md explains the split.
2. The raw events file (data/raw/fastnear/events.jsonl) is not in the repository because it grows continuously. It is published with hash-pinned revisions at https://huggingface.co/datasets/bomankari/near-intents-onchain-events, and the manifest records each upload's SHA-256 and Hugging Face commit id. analysis/onchain.py needs this file locally; run_all.py skips that step cleanly when it is absent and keeps the committed output.
3. The daily GitHub Action (.github/workflows/refresh-data.yml) refetches data, reruns the models, verifies the manifest, anchors its hash on NEAR mainnet, and commits only if verification passes. Recent bot commits named "refresh data" are that automation.
4. analysis/anchor.py requires NEAR credentials from the environment and is not runnable from the repo alone; its on-chain record is independently checkable at account `bomanaps.near`, key `thesis_manifest`, on the `social.near` contract, with transaction history at https://nearblocks.io/address/bomanaps.near.
5. The forecast seed is fixed (42): rerunning model/forecast.py on unchanged data reproduces the committed probabilities exactly. The price regression in the browser (dashboard spec explorer) reruns the identical Newey-West math on the 37 committed weekly rows and only displays itself after matching the Python output at load.
6. ingest/from_dune.py, ingest/from_dune_api.py, and queries/ are an abandoned alternative data path kept for reference; nothing depends on them.
