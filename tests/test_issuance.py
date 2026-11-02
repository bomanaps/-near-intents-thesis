import sys
import os
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from model.issuance import (
    IssuanceParams,
    RevenueParams,
    DailyResult,
    break_even_volume_usd,
    compute,
    find_break_even_date,
    near_bought_per_day,
    near_issued_per_day,
    offset_ratio,
    project_hsp029_ramp,
    _cap_hsp029,
)


class TestCapHsp029:
    def test_at_t0_is_two_point_five_percent(self):
        assert _cap_hsp029(0) == Decimal("0.025")

    def test_at_t24_is_one_point_six_percent(self):
        assert _cap_hsp029(24) == Decimal("0.016")

    def test_at_t12_is_midpoint(self):
        expected = Decimal("0.025") - Decimal("0.009") * Decimal(12) / Decimal(24)
        assert _cap_hsp029(12) == expected

    def test_clamps_at_t24(self):
        assert _cap_hsp029(24) == _cap_hsp029(30) == _cap_hsp029(100)

    def test_monotonically_decreasing(self):
        caps = [_cap_hsp029(t) for t in range(25)]
        for i in range(len(caps) - 1):
            assert caps[i] >= caps[i + 1]


class TestNearIssuedPerDay:
    def test_known_value_at_two_point_five_percent(self):
        result = near_issued_per_day(
            total_supply_near=Decimal("1309640572.78"),
            annual_cap=Decimal("0.025"),
        )
        assert abs(result - Decimal("89701")) < Decimal("1")

    def test_known_value_at_one_point_six_percent(self):
        result = near_issued_per_day(
            total_supply_near=Decimal("1309640572.78"),
            annual_cap=Decimal("0.016"),
        )
        assert abs(result - Decimal("57409")) < Decimal("1")

    def test_zero_cap_yields_zero(self):
        result = near_issued_per_day(
            total_supply_near=Decimal("1000000000"),
            annual_cap=Decimal("0"),
        )
        assert result == Decimal("0")

    def test_proportional_to_supply(self):
        r1 = near_issued_per_day(Decimal("1000000000"), Decimal("0.025"))
        r2 = near_issued_per_day(Decimal("2000000000"), Decimal("0.025"))
        assert r2 == r1 * 2

    def test_proportional_to_cap(self):
        r1 = near_issued_per_day(Decimal("1000000000"), Decimal("0.025"))
        r2 = near_issued_per_day(Decimal("1000000000"), Decimal("0.050"))
        assert r2 == r1 * 2


class TestNearBoughtPerDay:
    def test_known_value(self):
        result = near_bought_per_day(
            volume_usd_per_day=Decimal("135000000"),
            capture_rate=Decimal("0.000524"),
            near_price_usd=Decimal("4.37"),
        )
        expected_revenue_usd = Decimal("135000000") * Decimal("0.000524")
        expected_near = expected_revenue_usd / Decimal("4.37")
        assert result == expected_near

    def test_higher_price_means_fewer_near_bought(self):
        r_low = near_bought_per_day(Decimal("135000000"), Decimal("0.000524"), Decimal("4.37"))
        r_high = near_bought_per_day(Decimal("135000000"), Decimal("0.000524"), Decimal("8.74"))
        assert abs(r_high - r_low / 2) < Decimal("0.000001")

    def test_higher_volume_means_more_near_bought(self):
        r1 = near_bought_per_day(Decimal("100000000"), Decimal("0.000524"), Decimal("4.37"))
        r2 = near_bought_per_day(Decimal("200000000"), Decimal("0.000524"), Decimal("4.37"))
        assert r2 == r1 * 2

    def test_zero_volume_yields_zero(self):
        result = near_bought_per_day(Decimal("0"), Decimal("0.000524"), Decimal("4.37"))
        assert result == Decimal("0")


class TestOffsetRatio:
    def test_full_offset_when_equal(self):
        assert offset_ratio(Decimal("100"), Decimal("100")) == Decimal("1")

    def test_zero_when_no_buybacks(self):
        assert offset_ratio(Decimal("0"), Decimal("100")) == Decimal("0")

    def test_zero_issued_returns_zero(self):
        assert offset_ratio(Decimal("100"), Decimal("0")) == Decimal("0")

    def test_known_value_at_current_pace(self):
        issued = near_issued_per_day(Decimal("1309640572.78"), Decimal("0.025"))
        bought = near_bought_per_day(
            Decimal("135000000"), Decimal("0.000524"), Decimal("4.37")
        )
        ratio = offset_ratio(bought, issued)
        assert Decimal("0.17") < ratio < Decimal("0.19")

    def test_ratio_above_one_when_buybacks_exceed_issuance(self):
        ratio = offset_ratio(Decimal("200"), Decimal("100"))
        assert ratio == Decimal("2")


class TestBreakEvenVolume:
    def test_known_value_at_two_point_five_percent_defi_llama_rate(self):
        issued = near_issued_per_day(Decimal("1309640572.78"), Decimal("0.025"))
        bev = break_even_volume_usd(issued, Decimal("4.37"), Decimal("0.000524"))
        assert abs(bev - Decimal("748000000")) < Decimal("2000000")

    def test_known_value_at_one_point_six_percent_defi_llama_rate(self):
        issued = near_issued_per_day(Decimal("1309640572.78"), Decimal("0.016"))
        bev = break_even_volume_usd(issued, Decimal("4.37"), Decimal("0.000524"))
        assert abs(bev - Decimal("479000000")) < Decimal("2000000")

    def test_break_even_rises_with_price(self):
        issued = Decimal("89701")
        bev_low = break_even_volume_usd(issued, Decimal("4.37"), Decimal("0.000524"))
        bev_high = break_even_volume_usd(issued, Decimal("8.74"), Decimal("0.000524"))
        assert bev_high == bev_low * 2

    def test_break_even_falls_with_higher_capture_rate(self):
        issued = Decimal("89701")
        bev_low_cap = break_even_volume_usd(issued, Decimal("4.37"), Decimal("0.000524"))
        bev_high_cap = break_even_volume_usd(issued, Decimal("4.37"), Decimal("0.001048"))
        assert bev_high_cap == bev_low_cap / 2

    def test_zero_capture_rate_returns_infinity(self):
        result = break_even_volume_usd(Decimal("89701"), Decimal("4.37"), Decimal("0"))
        assert result == Decimal("Infinity")


class TestCompute:
    def _params(self):
        issuance = IssuanceParams(
            total_supply_near=Decimal("1309640572.78"),
            annual_cap=Decimal("0.025"),
            near_price_usd=Decimal("4.37"),
        )
        revenue = RevenueParams(
            volume_usd_per_day=Decimal("135000000"),
            capture_rate=Decimal("0.000524"),
        )
        return issuance, revenue

    def test_returns_daily_result(self):
        issuance, revenue = self._params()
        result = compute(issuance, revenue)
        assert isinstance(result, DailyResult)

    def test_near_issued_matches_standalone_function(self):
        issuance, revenue = self._params()
        result = compute(issuance, revenue)
        expected = near_issued_per_day(issuance.total_supply_near, issuance.annual_cap)
        assert result.near_issued_per_day == expected

    def test_issuance_usd_equals_issued_times_price(self):
        issuance, revenue = self._params()
        result = compute(issuance, revenue)
        assert result.issuance_usd_per_day == result.near_issued_per_day * issuance.near_price_usd

    def test_offset_ratio_matches_standalone_function(self):
        issuance, revenue = self._params()
        result = compute(issuance, revenue)
        expected = offset_ratio(result.near_bought_per_day, result.near_issued_per_day)
        assert result.offset_ratio == expected

    def test_break_even_volume_matches_standalone_function(self):
        issuance, revenue = self._params()
        result = compute(issuance, revenue)
        expected = break_even_volume_usd(
            result.near_issued_per_day, issuance.near_price_usd, revenue.capture_rate
        )
        assert result.break_even_volume_usd == expected

    def test_known_offset_ratio_at_current_inputs(self):
        issuance, revenue = self._params()
        result = compute(issuance, revenue)
        assert Decimal("0.17") < result.offset_ratio < Decimal("0.19")


class TestProjectHsp029Ramp:
    def test_returns_one_entry_per_day(self):
        results = project_hsp029_ramp(
            activation_date=date(2026, 11, 2),
            total_supply_near=Decimal("1309640572.78"),
            near_price_usd=Decimal("4.37"),
            capture_rate=Decimal("0.000524"),
            volume_usd_per_day=Decimal("135000000"),
            days=30,
        )
        assert len(results) == 30

    def test_first_date_is_activation_date(self):
        activation = date(2026, 11, 2)
        results = project_hsp029_ramp(
            activation_date=activation,
            total_supply_near=Decimal("1309640572.78"),
            near_price_usd=Decimal("4.37"),
            capture_rate=Decimal("0.000524"),
            volume_usd_per_day=Decimal("135000000"),
            days=5,
        )
        assert results[0][0] == activation

    def test_issuance_decreases_over_24_months(self):
        results = project_hsp029_ramp(
            activation_date=date(2026, 11, 2),
            total_supply_near=Decimal("1309640572.78"),
            near_price_usd=Decimal("4.37"),
            capture_rate=Decimal("0.000524"),
            volume_usd_per_day=Decimal("135000000"),
            days=800,
        )
        issued_day0 = results[0][1].near_issued_per_day
        issued_day730 = results[730][1].near_issued_per_day
        assert issued_day730 < issued_day0

    def test_issuance_stabilises_after_24_months(self):
        results = project_hsp029_ramp(
            activation_date=date(2026, 11, 2),
            total_supply_near=Decimal("1309640572.78"),
            near_price_usd=Decimal("4.37"),
            capture_rate=Decimal("0.000524"),
            volume_usd_per_day=Decimal("135000000"),
            days=900,
        )
        issued_day730 = results[730][1].near_issued_per_day
        issued_day800 = results[800][1].near_issued_per_day
        assert issued_day730 == issued_day800

    def test_offset_ratio_improves_as_issuance_falls(self):
        results = project_hsp029_ramp(
            activation_date=date(2026, 11, 2),
            total_supply_near=Decimal("1309640572.78"),
            near_price_usd=Decimal("4.37"),
            capture_rate=Decimal("0.000524"),
            volume_usd_per_day=Decimal("135000000"),
            days=800,
        )
        ratio_day0 = results[0][1].offset_ratio
        ratio_day730 = results[730][1].offset_ratio
        assert ratio_day730 > ratio_day0


class TestFindBreakEvenDate:
    def test_returns_none_when_never_reached(self):
        results = project_hsp029_ramp(
            activation_date=date(2026, 11, 2),
            total_supply_near=Decimal("1309640572.78"),
            near_price_usd=Decimal("4.37"),
            capture_rate=Decimal("0.000524"),
            volume_usd_per_day=Decimal("135000000"),
            days=365 * 3,
        )
        be_date = find_break_even_date(results)
        assert be_date is None

    def test_returns_first_date_when_offset_exceeds_one(self):
        activation = date(2027, 1, 1)
        results = project_hsp029_ramp(
            activation_date=activation,
            total_supply_near=Decimal("1309640572.78"),
            near_price_usd=Decimal("4.37"),
            capture_rate=Decimal("0.000524"),
            volume_usd_per_day=Decimal("10000000000"),
            days=10,
        )
        be_date = find_break_even_date(results)
        assert be_date == activation

    def test_returns_none_for_empty_projection(self):
        assert find_break_even_date([]) is None
