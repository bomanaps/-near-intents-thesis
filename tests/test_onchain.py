from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.onchain import (
    STABLES,
    entry_fee_bps,
    entry_usd,
    leg_usd,
    pick_solver,
    token_symbol,
)

USDT_ETH = "nep141:eth-0xdac17f958d2ee523a2206206994597c13d831ec7.omft.near"
BTC = "nep141:nbtc.bridge.near"
UNKNOWN = "nep141:something-unlisted.omft.near"
FIXTURE = Path(__file__).parent / "fixtures" / "receipts.jsonl"


class TestValuation:
    def test_stable_leg_usd_uses_decimals(self):
        assert leg_usd(USDT_ETH, 4_927_000, {}) == pytest.approx(4.927)

    def test_major_leg_usd_uses_price(self):
        prices = {"coingecko:bitcoin": 100_000.0}
        assert leg_usd(BTC, 4_536_427, prices) == pytest.approx(4536.427)

    def test_unknown_token_is_unvalued(self):
        assert leg_usd(UNKNOWN, 10**18, {}) is None
        assert token_symbol(UNKNOWN) == "other"

    def test_entry_usd_prefers_stable_leg(self):
        prices = {"coingecko:bitcoin": 100_000.0}
        diff = {BTC: -4_536_427, USDT_ETH: 4_500_000}
        assert entry_usd(diff, prices) == pytest.approx(4.5)

    def test_entry_usd_falls_back_to_major_then_none(self):
        prices = {"coingecko:bitcoin": 100_000.0}
        assert entry_usd({BTC: -4_536_427, UNKNOWN: 5}, prices) == pytest.approx(4536.427)
        assert entry_usd({UNKNOWN: 5}, prices) is None


class TestFeeBps:
    def test_known_arithmetic(self):
        entry = {
            "diff": {USDT_ETH: "-4927000"},
            "fees_collected": {USDT_ETH: "5"},
        }
        [bps] = entry_fee_bps(entry)
        assert bps == pytest.approx(5 / 4_927_000 * 1e4)

    def test_fee_token_absent_from_diff_is_skipped(self):
        entry = {"diff": {USDT_ETH: "-100"}, "fees_collected": {BTC: "5"}}
        assert entry_fee_bps(entry) == []


class TestSolverPick:
    def test_higher_fill_count_wins(self):
        a = {"account_id": "solver.near"}
        b = {"account_id": "user-hex"}
        fills = {"solver.near": 500, "user-hex": 1}
        assert pick_solver(a, b, fills) is a
        assert pick_solver(b, a, fills) is a


class TestFixtureReceipts:
    def load(self):
        from collections import defaultdict
        receipts = defaultdict(list)
        with open(FIXTURE) as f:
            for line in f:
                e = json.loads(line)
                data = json.loads(e["data"]) if isinstance(e["data"], str) else e["data"]
                for entry in data:
                    receipts[e["receipt_id"]].append(entry)
        return receipts

    def test_fixture_has_ten_bilateral_receipts(self):
        receipts = self.load()
        assert len(receipts) == 10
        assert all(len(v) == 2 for v in receipts.values())

    def test_mirror_net_of_fees_identity(self):
        receipts = self.load()
        for rid, (a, b) in receipts.items():
            tokens = set(a["diff"]) | set(b["diff"])
            for tok in tokens:
                total = int(a["diff"].get(tok, 0)) + int(b["diff"].get(tok, 0))
                fees = int((a.get("fees_collected") or {}).get(tok, 0)) + int(
                    (b.get("fees_collected") or {}).get(tok, 0)
                )
                assert total + fees == 0, f"{rid} {tok}: diffs {total} + fees {fees} != 0"

    def test_fee_bps_small_on_real_fills(self):
        receipts = self.load()
        samples = [bps for entries in receipts.values() for en in entries for bps in entry_fee_bps(en)]
        assert len(samples) >= 10
        assert all(0 < bps < 60 for bps in samples)
