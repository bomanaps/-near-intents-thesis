from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.treasury import (
    BLOCK_SECONDS,
    STABLES,
    TOKEN_IDS,
    build,
    day_range,
    face_value_usd,
    observe_rate,
    seconds_of,
    _rate,
)

USDT_ETH = "nep141:eth-0xdac17f958d2ee523a2206206994597c13d831ec7.omft.near"
USDC_ETH = "nep141:eth-0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48.omft.near"
DAI_ETH = "nep141:eth-0x6b175474e89094c44da98b954eedeac495271d0f.omft.near"
OUTPUT = Path(__file__).parent.parent / "data" / "model" / "treasury.json"


def header(height: int, epoch: float) -> dict:
    return {"height": height, "timestamp": int(epoch * 1e9)}


def day(date: str, height: int, epoch: float, usdt: int) -> dict:
    return {
        "block_height": height,
        "block_epoch": epoch,
        "block_time_utc": f"{date}T00:00:00+00:00",
        "balances": {"USDT.eth": str(usdt)},
        "stable_float_usd": round(usdt / 10**6, 2),
    }


class TestFaceValue:
    def test_six_decimal_stable(self):
        assert face_value_usd({USDT_ETH: 4_927_000}) == pytest.approx(4.927)

    def test_eighteen_decimal_stable(self):
        assert face_value_usd({DAI_ETH: 2 * 10**18}) == pytest.approx(2.0)

    def test_sums_across_tokens(self):
        balances = {USDT_ETH: 1_000_000, USDC_ETH: 2_500_000, DAI_ETH: 10**18}
        assert face_value_usd(balances) == pytest.approx(4.5)

    def test_every_token_id_has_decimals(self):
        assert set(TOKEN_IDS) == set(STABLES)
        assert all(isinstance(STABLES[t][1], int) for t in TOKEN_IDS)


class TestDayRange:
    def test_inclusive_of_both_ends(self):
        assert day_range("2026-02-18", "2026-02-21") == [
            "2026-02-18",
            "2026-02-19",
            "2026-02-20",
            "2026-02-21",
        ]

    def test_single_day(self):
        assert day_range("2026-03-01", "2026-03-01") == ["2026-03-01"]

    def test_crosses_month_boundary(self):
        assert day_range("2026-02-27", "2026-03-02")[-1] == "2026-03-02"


class TestBlockRate:
    def test_seconds_of_converts_nanoseconds(self):
        assert seconds_of(header(1, 1_700_000_000)) == pytest.approx(1_700_000_000)

    def test_short_span_is_ignored(self):
        _rate[0] = BLOCK_SECONDS
        observe_rate(header(100, 0), header(200, 1_000))
        assert _rate[0] == BLOCK_SECONDS

    def test_long_span_sets_observed_rate(self):
        _rate[0] = BLOCK_SECONDS
        observe_rate(header(0, 0), header(80_000, 96_000))
        assert _rate[0] == pytest.approx(1.2)
        _rate[0] = BLOCK_SECONDS

    def test_implausible_rate_is_rejected(self):
        _rate[0] = BLOCK_SECONDS
        observe_rate(header(0, 0), header(80_000, 8_000_000))
        assert _rate[0] == BLOCK_SECONDS


class TestBuild:
    def cache(self) -> dict:
        return {
            "_first_funded": {
                "block_height": 186_126_873,
                "date_utc": "2026-02-18",
                "block_time_utc": "2026-02-18T19:12:58+00:00",
            },
            "2026-02-18": day("2026-02-18", 186_126_873, 1.0, 1_000_000),
            "2026-02-19": day("2026-02-19", 186_205_418, 2.0, 3_000_000),
            "2026-02-20": day("2026-02-20", 186_283_963, 3.0, 2_000_000),
        }

    def test_series_is_dated_and_ordered(self):
        result = build(self.cache())
        assert [r["date_utc"] for r in result["series"]] == [
            "2026-02-18",
            "2026-02-19",
            "2026-02-20",
        ]
        assert result["coverage"]["days"] == 3

    def test_first_change_is_undefined(self):
        result = build(self.cache())
        assert result["series"][0]["change_usd"] is None

    def test_changes_are_first_differences(self):
        result = build(self.cache())
        assert result["series"][1]["change_usd"] == pytest.approx(2.0)
        assert result["series"][2]["change_usd"] == pytest.approx(-1.0)

    def test_summary_statistics(self):
        s = build(self.cache())["summary"]
        assert s["latest_float_usd"] == pytest.approx(2.0)
        assert s["peak_float_usd"] == pytest.approx(3.0)
        assert s["median_float_usd"] == pytest.approx(2.0)
        assert s["mean_abs_daily_change_usd"] == pytest.approx(1.5)
        assert s["largest_daily_increase_usd"] == pytest.approx(2.0)
        assert s["largest_daily_decrease_usd"] == pytest.approx(-1.0)

    def test_peak_date_matches_peak_value(self):
        result = build(self.cache())
        peak = result["summary"]
        row = next(r for r in result["series"] if r["date_utc"] == peak["peak_date_utc"])
        assert row["stable_float_usd"] == peak["peak_float_usd"]

    def test_assumption_is_stated(self):
        source = build(self.cache())["source"]
        assert "face value" in source["assumption"]
        assert "no price series" in source["note"].lower()


@pytest.mark.skipif(not OUTPUT.exists(), reason="treasury.json not built yet")
class TestCommittedOutput:
    def load(self) -> dict:
        return json.loads(OUTPUT.read_text())

    def test_series_covers_every_day_without_gaps(self):
        result = self.load()
        dates = [r["date_utc"] for r in result["series"]]
        assert dates == day_range(dates[0], dates[-1])
        assert len(dates) == result["coverage"]["days"]

    def test_block_heights_increase_with_time(self):
        heights = [r["block_height"] for r in self.load()["series"]]
        assert heights == sorted(heights)
        assert len(set(heights)) == len(heights)

    def test_each_row_reports_its_own_block_time(self):
        for row in self.load()["series"]:
            assert row["block_time_utc"].startswith(row["date_utc"])

    def test_float_matches_balances_on_every_row(self):
        by_symbol = {sym: dec for sym, dec in STABLES.values()}
        for row in self.load()["series"]:
            total = sum(
                int(units) / 10 ** by_symbol[sym]
                for sym, units in row["balances_token_units"].items()
            )
            assert total == pytest.approx(row["stable_float_usd"], abs=0.01)

    def test_changes_match_first_differences(self):
        series = self.load()["series"]
        for previous, current in zip(series, series[1:]):
            gap = current["stable_float_usd"] - previous["stable_float_usd"]
            assert current["change_usd"] == pytest.approx(gap, abs=0.01)
