# PREDICTIONS.md

Five dated, falsifiable predictions, frozen before their resolution windows open. The SHA-256 of this exact file is anchored on NEAR mainnet (contract `social.near`, account `bomanaps.near`, key `thesis_predictions`) before any window opens; the anchoring transaction is cited in the README. This file is never edited after anchoring. Each prediction names its resolution source and date, and a stated probability. Probabilities are honest credences, not certainties; being wrong on a well-calibrated bet is informative, not embarrassing.

Frozen: November 10, 2026.

## P1. Volume stays on trend

The 30-day average of NEAR Intents daily volume on December 31, 2026 is at or above $100M.

Probability: 0.80. Resolution: DefiLlama dexs series for near-intents, 30-day mean of the daily values ending December 31, 2026, read any time during the first week of January 2027.

## P2. The HSP-029 ramp does not start early

No NEAR protocol upgrade carrying an issuance cap below 2.5% is adopted by validators with the ramp active on or before February 16, 2027.

Probability: 0.90. Resolution: NEAR protocol version and issuance parameters readable from any mainnet RPC, checked February 17, 2027. The date is the earliest possible ramp start under the proposal's own mechanics (veto window close November 16, 2026 plus one full quarter of grace).

## P3. The explicit contract fee stays near zero

The median explicit fee per fill side on public intents.near settlements, measured by rerunning `analysis/onchain.py` on events decoded during the final week of December 2026, remains below 0.1 bps.

Probability: 0.85. Resolution: the committed script on a fresh ingestion window, first week of January 2027. This is the structural core of the capture-is-policy finding: contract-level fees staying near zero while reported revenue continues means the revenue arrangement remains off-contract.

## P4. The confidential path stays dominant

Stablecoin value entering the confidential treasury exceeds stablecoin value settled in public bilateral fills over any seven consecutive chain days ingested during December 2026.

Probability: 0.85. Resolution: `analysis/onchain.py` confidential flow block on a December ingestion window, read in the first week of January 2027. If public intents wind down entirely, the measured share approaches 100% and the prediction resolves true; if the private path is reversed, it resolves false.

## P5. Buybacks continue through year end

The buyback wallets receive inflows in every calendar week from November 10 through December 31, 2026.

Probability: 0.90. Resolution: weekly revenue values in the DefiLlama series for near-intents, each week nonzero, read in the first week of January 2027.

## What resolution means

Each prediction tests one load-bearing part of the thesis: P1 the growth assumption behind the forecast, P2 the governance timeline correction, P3 the capture-is-policy finding, P4 the visibility risk, P5 the revenue engine itself. A miss on any of them is reported as a miss, with the thesis updated accordingly, in the same repository.
