import sys
import os
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from model.scenarios import (
    ScenarioResult,
    run_all,
    _ISSUANCE_SCENARIOS,
    _VOLUME_SCENARIOS,
    _CAPTURE_SCENARIOS,
    _BUYBACK_SCENARIOS,
)


class TestRunAll:
    def test_returns_correct_number_of_scenarios(self):
        results = run_all()
        expected = (
            len(_ISSUANCE_SCENARIOS)
            * len(_VOLUME_SCENARIOS)
            * len(_CAPTURE_SCENARIOS)
            * len(_BUYBACK_SCENARIOS)
        )
        assert len(results) == expected

    def test_all_results_are_scenario_result_instances(self):
        for r in run_all():
            assert isinstance(r, ScenarioResult)

    def test_all_labels_are_unique(self):
        labels = [r.label for r in run_all()]
        assert len(labels) == len(set(labels))

    def test_no_none_required_fields(self):
        for r in run_all():
            assert r.label is not None
            assert r.issuance_label is not None
            assert r.volume_label is not None
            assert r.capture_label is not None
            assert r.buyback_label is not None
            assert r.near_issued_per_day is not None
            assert r.issuance_usd_per_day is not None
            assert r.near_bought_per_day is not None
            assert r.buyback_usd_per_day is not None
            assert r.offset_ratio is not None
            assert r.break_even_volume_usd is not None
            assert r.times_current_volume is not None

    def test_all_offset_ratios_are_positive(self):
        for r in run_all():
            assert r.offset_ratio > Decimal("0")

    def test_all_offset_ratios_are_below_one_at_current_volume(self):
        for r in run_all():
            assert r.offset_ratio < Decimal("1"), (
                f"Offset ratio {r.offset_ratio} >= 1 for scenario: {r.label}"
            )

    def test_all_break_even_volumes_exceed_current_volume(self):
        for r in run_all():
            assert r.break_even_volume_usd > Decimal("135000000"), (
                f"Break-even volume unexpectedly low for: {r.label}"
            )

    def test_times_current_volume_consistent_with_break_even(self):
        for r in run_all():
            from model.scenarios import _VOLUME_SCENARIOS
            vol_values = [v for _, v in _VOLUME_SCENARIOS]
            if r.near_bought_per_day > 0:
                assert r.times_current_volume > Decimal("1"), (
                    f"times_current_volume should exceed 1x for: {r.label}"
                )

    def test_lower_cap_yields_lower_issued_per_day(self):
        results = run_all()
        high_cap = [r for r in results if "2.5%" in r.issuance_label]
        low_cap = [r for r in results if "1.6%" in r.issuance_label]
        assert all(h.near_issued_per_day > l.near_issued_per_day for h, l in zip(high_cap, low_cap))

    def test_lower_cap_yields_lower_break_even_volume(self):
        results = run_all()
        for r_high in results:
            if "2.5%" not in r_high.issuance_label:
                continue
            matching_low = [
                r for r in results
                if "1.6%" in r.issuance_label
                and r.volume_label == r_high.volume_label
                and r.capture_label == r_high.capture_label
                and r.buyback_label == r_high.buyback_label
            ]
            assert len(matching_low) == 1
            assert matching_low[0].break_even_volume_usd < r_high.break_even_volume_usd

    def test_higher_capture_rate_yields_lower_break_even_volume(self):
        results = run_all()
        defi_llama = [r for r in results if "5.24 bps" in r.capture_label]
        near_keeps = [r for r in results if "3.69 bps" in r.capture_label]
        for d, n in zip(defi_llama, near_keeps):
            assert d.break_even_volume_usd < n.break_even_volume_usd

    def test_known_break_even_volume_at_two_point_five_defi_llama(self):
        results = run_all()
        match = [
            r for r in results
            if "2.5%" in r.issuance_label and "5.91 bps" in r.capture_label
        ]
        assert len(match) > 0
        for r in match:
            assert abs(r.break_even_volume_usd - Decimal("663000000")) < Decimal("5000000")

    def test_known_break_even_volume_at_one_point_six_defi_llama(self):
        results = run_all()
        match = [
            r for r in results
            if "1.6%" in r.issuance_label and "5.91 bps" in r.capture_label
        ]
        assert len(match) > 0
        for r in match:
            assert abs(r.break_even_volume_usd - Decimal("424000000")) < Decimal("5000000")

    def test_break_even_date_is_none_at_current_volume(self):
        results = run_all()
        for r in results:
            assert r.break_even_date is None, (
                f"Expected no break-even date at current volume for: {r.label}"
            )
