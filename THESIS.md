# THESIS.md

NEAR Intents Investment Thesis. NEAR Hackathon 2026, Investment Thesis track. Figures below are from the committed model outputs with data through November 12, 2026; the [live dashboard](https://bomanaps.github.io/-near-intents-thesis/dashboard.html) recomputes them from current data on every page load, and every figure's code, test, and independent check is listed in [docs/claims.md](docs/claims.md).

## The Claim

NEAR Intents is a real and fast growing revenue engine, but at current scale its buybacks cover only about a fifth of NEAR's token issuance, and the capture rate that the entire case rests on is set by off-chain policy, not by contract code. The thesis becomes investable when two of three conditions are met: daily volume crosses roughly $450M, a contract-enforced fee switch of 5 bps or more activates, or NEAR sustains above $8. The fee switch is the decisive lever because it is the only one in governance's direct control.

## The Evidence For It

1. Revenue is real and the mechanism works. 567 priced days of DefiLlama history show protocol revenue flowing on most days, with a 30 day capture rate of 5.03 bps of volume, and the buyback identity (bought = volume x capture / price; issued = supply x cap / 365) reproduces from raw data with one command.
2. Growth is genuine. Volume roughly doubled in the last year. The sustained-crossing forecast (30 day average must reach the threshold, not a one day spike) puts the 12 month probability of reaching the 1.6% cap break-even between 3% (conservative 365 day trend) and 97% (full-history bootstrap, an upper bound). That spread is not two regimes disagreeing so much as one unstable estimate: the 365 day drift is statistically indistinguishable from zero, and the residual bootstrap understates path dispersion because it resamples differences of a moving average. Treat the forecast as a weak prior, not a result.
3. The fee switch did not visibly break the protocol. Volume continued and revenue began accruing. The difference-in-differences estimate is 1.11x, but this analysis does not claim it shows demand tolerated the fee, for reasons set out in Evidence Against item 8.
4. No sign of the crudest volume inflation. Decoding 20,308 raw settlements finds zero cases of one account settling against itself. This rules out only the most obvious form of wash trading and should not be read as a clean bill of health.
5. HSP-029 structurally improves the ratio. The approved issuance cut from 2.5% to 1.6% lowers the break-even volume by roughly a third once the ramp activates.

## The Evidence Against It

1. The gap is large. At current volume, buybacks offset 19.7% of issuance. Full coverage happened on only 6 of 567 days with matched price data, all spikes, none a trend. Note that 410 of 703 days in the series record zero revenue, mostly before the buyback mechanism existed.
2. Capture is policy, not protocol, and it is unstable. The settlement contract itself collects 0.01 bps per fill side across 51,779 measured sides; the roughly 5 bps the buyback receives is generated off the contract and can change in either direction without a governance vote. It moves accordingly: the 30 day trailing rate has ranged between 1.9 and 6.0 bps over the last four months, and daily capture has a standard deviation of 2.5 bps on a mean of 3.8. Every headline in this thesis is linear in that number. This is the single most important finding in the project and it cuts against the thesis as it stands.
3. Buybacks are too small for a price effect to be detectable. A pre-registered regression of weekly NEAR returns on lagged buyback intensity with BTC and ETH controls finds nothing (t = 0.59, permutation p = 0.67, 38 weeks), and the strong naive correlation (t = 3.5) is reverse causality that disappears under the lag. The null is weak evidence rather than strong: with 38 weeks and buybacks worth roughly 0.005% of market cap per week, this test could not have detected a realistic effect. That is itself the point. A buyback this small is not a price mechanism.
4. Solver concentration is high. The top three solvers fill roughly two thirds of settled volume in the decoded window, which gives them bargaining power against any attempt to raise the protocol take, and makes volume sensitive to a single exit.
5. HSP-029 is not active. The vote passed November 2, but per the proposal text the ramp starts one full quarter after ratification and validators must adopt the upgrade; the realistic floor arrives around 2029, not 2028, and a Security Council veto window runs to November 16.
6. Revenue accounting is definition-dependent. How much of the reported revenue reaches the buyback wallets changes materially with the definition of revenue applied, which confirms how soft the current arrangement is.
7. The evidence base is shrinking. A confidential settlement path received 57%, 63% and 71% of stablecoin value across the three chain days fully decoded so far, counted once per settlement on both sides. That account pays out almost exactly what it receives ($42.0M in against $43.9M out over the window), so it routes rather than captures value, but settlement on that path happens outside the public event stream either way. Everything measurable from public chain data, including the findings above, describes a diminishing share of the protocol, and fee reporting on the private path cannot be independently audited.
8. The fee-switch evidence does not survive its own diagnostic. NEAR's volume fell 19% in the 90 days after the switch; the positive 1.11x estimate exists only because the three controls fell further. NEAR was trending up beforehand (+195%/yr) while the controls trended down (-52%/yr), a violation of the parallel-trends assumption that the model output now flags; carrying that differential across the window gap gives 0.71x, a 29% relative decline. Measuring uncertainty across controls rather than days widens the interval to 0.86 to 1.42, and with four units the permutation test has a floor of p = 0.25. The volume effect of the fee switch is not identified here in either direction, and the Section 8 argument below is weaker for it.

## What Would Change My Mind

1. Bearish: if the 7 day average volume stays below $60M for 60 consecutive days, the base case forecast is rejected and the pessimistic scenario becomes operative. This threshold is committed in the model output.
2. Bearish: if a solver exit removes a top-three account and volume does not recover within a quarter, the organic-demand reading is wrong.
3. Bullish: if governance enacts a contract-enforced take of 5 bps or more, break-even falls to roughly 1.6x current volume at the issuance floor and the thesis flips from conditional to positive. The demand response to such a take is genuinely unknown: the one natural experiment available is not identified, and it tested a contract-level fee several hundred times smaller.
4. Bullish: if the measured capture rate rises and holds above 10 bps for a quarter without a volume decline, the policy-softness objection loses force.
5. Either direction: if the on-chain explicit fee measurement stops matching the published revenue series' implications, the data pipeline itself is flagged by the integrity manifest and the thesis pauses until reconciled.

Five of these conditions are frozen as dated predictions with stated probabilities in [PREDICTIONS.md](PREDICTIONS.md), anchored on NEAR mainnet before any resolution window opened.

## Reproduce It

```bash
pip install pandas pyarrow numpy scipy
python3 run_all.py --no-fetch
pytest tests/
python3 analysis/manifest.py verify
```

Full written analysis: [thesis memo](https://bomanaps.github.io/-near-intents-thesis/thesis-memo.html). Raw decoded events: [Hugging Face dataset](https://huggingface.co/datasets/bomankari/near-intents-onchain-events). Daily integrity anchor on NEAR mainnet: account `bomanaps.near`, key `thesis_manifest`, contract `social.near`.
