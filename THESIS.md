# THESIS.md

NEAR Intents Investment Thesis. NEAR Hackathon 2026, Investment Thesis track. Figures below are from the committed model outputs with data through November 3, 2026; the [live dashboard](https://bomanaps.github.io/-near-intents-thesis/dashboard.html) recomputes them from current data on every page load, and every figure's code, test, and independent check is listed in [docs/claims.md](docs/claims.md).

## The Claim

NEAR Intents is a real and fast growing revenue engine, but at current scale its buybacks cover only about a fifth of NEAR's token issuance, and the capture rate that the entire case rests on is set by off-chain policy, not by contract code. The thesis becomes investable when two of three conditions are met: daily volume crosses roughly $450M, a contract-enforced fee switch of 5 bps or more activates, or NEAR sustains above $8. The fee switch is the decisive lever because it is the only one in governance's direct control.

## The Evidence For It

1. Revenue is real and the mechanism works. 557 priced days of DefiLlama history show protocol revenue flowing daily, with a 30 day capture rate near 5 to 6 bps of volume, and the buyback identity (bought = volume x capture / price; issued = supply x cap / 365) reproduces from raw data with one command.
2. Growth is genuine. Volume roughly doubled in the last year. The sustained-crossing forecast (30 day average must reach the threshold, not a one day spike) puts the 12 month probability of reaching the 1.6% cap break-even between 16% (conservative 365 day trend) and 95% (full-history bootstrap, an upper bound). The spread is the honest answer: it depends on whether the recent regime holds.
3. Demand tolerates fees. A difference-in-differences analysis of the February 23, 2026 fee activation against three aggregator controls finds no detectable volume damage (treatment effect 1.10x, 95% CI 0.97 to 1.25).
4. The volume is organic. Decoding 5,977 raw settlements from the intents.near contract finds zero bilateral self-fills and a non-solver round-trip share near 8%, inconsistent with wash trading.
5. HSP-029 structurally improves the ratio. The approved issuance cut from 2.5% to 1.6% lowers the break-even volume by roughly a third once the ramp activates.

## The Evidence Against It

1. The gap is large. At current volume, buybacks offset roughly 20% of issuance. Full coverage happened on only 6 of 557 priced days, all spikes, none a trend.
2. Capture is policy, not protocol. The settlement contract itself collects about 0.01 bps per side; the 5 to 6 bps the buyback receives is generated off the contract and can change in either direction without a governance vote. This is the single most important finding in the project and it cuts against the thesis as it stands.
3. Buybacks do not detectably move the price. A pre-registered regression of weekly NEAR returns on lagged buyback intensity with BTC and ETH controls finds nothing (t = 0.61, permutation p = 0.62, 37 weeks). The strong naive correlation (t = 4.11) is reverse causality and disappears when lagged.
4. Solver concentration is high. The top three solvers fill roughly two thirds of settled volume in the decoded window, which gives them bargaining power against any attempt to raise the protocol take, and makes volume sensitive to a single exit.
5. HSP-029 is not active. The vote passed November 2, but per the proposal text the ramp starts one full quarter after ratification and validators must adopt the upgrade; the realistic floor arrives around 2029, not 2028, and a Security Council veto window runs to November 16.
6. Revenue accounting is definition-dependent. How much of the reported revenue reaches the buyback wallets changes materially with the definition of revenue applied, which confirms how soft the current arrangement is.

## What Would Change My Mind

1. Bearish: if the 7 day average volume stays below $60M for 60 consecutive days, the base case forecast is rejected and the pessimistic scenario becomes operative. This threshold is committed in the model output.
2. Bearish: if a solver exit removes a top-three account and volume does not recover within a quarter, the organic-demand reading is wrong.
3. Bullish: if governance enacts a contract-enforced take of 5 bps or more, break-even falls to roughly 1.6x current volume at the issuance floor and the thesis flips from conditional to positive. The demand side of this is already evidenced by the fee-switch DiD.
4. Bullish: if the measured capture rate rises and holds above 10 bps for a quarter without a volume decline, the policy-softness objection loses force.
5. Either direction: if the on-chain explicit fee measurement stops matching the published revenue series' implications, the data pipeline itself is flagged by the integrity manifest and the thesis pauses until reconciled.

## Reproduce It

```bash
pip install pandas pyarrow numpy scipy
python3 run_all.py --no-fetch
pytest tests/
python3 analysis/manifest.py verify
```

Full written analysis: [thesis memo](https://bomanaps.github.io/-near-intents-thesis/thesis-memo.html). Raw decoded events: [Hugging Face dataset](https://huggingface.co/datasets/bomankari/near-intents-onchain-events). Daily integrity anchor on NEAR mainnet: account `bomanaps.near`, key `thesis_manifest`, contract `social.near`.
