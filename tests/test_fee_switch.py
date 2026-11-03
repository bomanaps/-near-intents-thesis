from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from model.fee_switch import att, log_growth, permutation_test, pre_slope


def frame(values):
    return pd.DataFrame({"volume_usd": values})


class TestLogGrowth:
    def test_known_ratio(self):
        pre = frame([100.0] * 10)
        post = frame([200.0] * 10)
        assert log_growth(pre, post) == pytest.approx(np.log(2.0))

    def test_zero_pre_average_returns_none(self):
        assert log_growth(frame([0.0] * 10), frame([100.0] * 10)) is None


class TestAtt:
    def test_att_is_treated_minus_control_mean(self):
        assert att(0.5, [0.1, 0.2, 0.3]) == pytest.approx(0.5 - 0.2)

    def test_no_valid_controls_returns_none(self):
        assert att(0.5, [None, None]) is None


class TestPreSlope:
    def test_recovers_known_slope(self):
        slope = 0.01
        y = np.exp(slope * np.arange(30) + 5.0)
        assert pre_slope(frame(y)) == pytest.approx(slope, rel=1e-9)

    def test_too_short_returns_none(self):
        assert pre_slope(frame([1.0] * 5)) is None


class TestPermutation:
    def test_placebo_atts_and_rank(self):
        lgs = {"near_intents": 0.4, "a": 0.1, "b": 0.2, "c": 0.3}
        out = permutation_test(lgs)
        assert out["placebo_atts"]["near_intents"] == pytest.approx(0.4 - np.mean([0.1, 0.2, 0.3]))
        ranks = sorted(out["placebo_atts"].values())
        assert out["placebo_atts"]["near_intents"] == ranks[-1]

    def test_insufficient_units(self):
        out = permutation_test({"near_intents": 0.4, "a": None, "b": None})
        assert out["placebo_atts"] == {}
