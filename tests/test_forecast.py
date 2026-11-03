from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from model import forecast


class TestTrailingMeanSmoothing:
    def test_matches_pandas_rolling_mean(self):
        rng = np.random.default_rng(7)
        daily = np.abs(rng.normal(100, 20, size=120)) + 1
        csum = np.cumsum(daily)
        smooth = np.empty_like(daily)
        for t in range(len(daily)):
            lo = max(0, t - forecast.SMOOTH_DAYS + 1)
            smooth[t] = (csum[t] - (csum[lo - 1] if lo > 0 else 0)) / (t - lo + 1)
        expected = pd.Series(daily).rolling(forecast.SMOOTH_DAYS, min_periods=1).mean().values
        np.testing.assert_allclose(smooth, expected, rtol=1e-12)

    def test_bootstrap_paths_smoothing_matches_pandas(self, monkeypatch):
        monkeypatch.setattr(forecast, "N_SIMS", 2)
        monkeypatch.setattr(forecast, "HORIZON_DAYS", 90)

        class FixedRng:
            def integers(self, low, high, size):
                return np.zeros(size, dtype=int)

        log_ret = np.linspace(-0.05, 0.05, 60)
        smooth = forecast.simulate_block_bootstrap(log_ret, 100.0, FixedRng())
        first_block = log_ret[: forecast.BLOCK_SIZE]
        rets = np.tile(first_block, 4)[:90]
        daily = 100.0 * np.exp(np.cumsum(rets))
        daily = np.hstack([[100.0], daily])
        expected = pd.Series(daily).rolling(forecast.SMOOTH_DAYS, min_periods=1).mean().values
        for i in range(2):
            np.testing.assert_allclose(smooth[i], expected, rtol=1e-10)


class TestThresholdIdentity:
    def test_threshold_formula(self):
        price, cap, rate_bps = 4.0, 0.025, 5.0
        rate = rate_bps / 10_000
        expected = forecast.SUPPLY * cap / 365 * price / rate
        issued_near = forecast.SUPPLY * cap / 365
        assert expected == pytest.approx(issued_near * price / rate)
        assert expected == pytest.approx(717_611_273, rel=1e-6)


class TestSustainedCrossing:
    def test_crossing_on_known_day_detected(self):
        path = np.full((1, 800), 100.0)
        path[0, 380:] = 500.0
        probs = forecast.crossing_probs(path, {"thr": 400.0})
        assert probs["thr"]["12"] == 0.0
        assert probs["thr"]["24"] == 1.0
        assert probs["thr"]["36"] == 1.0

    def test_path_below_threshold_never_crosses(self):
        path = np.full((5, 1096), 100.0)
        probs = forecast.crossing_probs(path, {"thr": 400.0})
        assert all(v == 0.0 for v in probs["thr"].values())

    def test_one_day_raw_spike_does_not_cross_smoothed(self):
        daily = np.full(120, 100.0)
        daily[60] = 2000.0
        smooth = pd.Series(daily).rolling(forecast.SMOOTH_DAYS, min_periods=1).mean().values
        probs = forecast.crossing_probs(smooth[None, :], {"thr": 400.0})
        assert all(v == 0.0 for v in probs["thr"].values())


class TestRwDriftFit:
    def test_recovers_known_drift(self):
        drift = 0.003
        series = np.cumsum(np.full(200, drift)) + 10.0
        fit = forecast.fit_rw_drift(series)
        assert fit["drift"] == pytest.approx(drift, rel=1e-9)
        assert fit["sigma_resid"] == pytest.approx(0.0, abs=1e-12)
        assert fit["annualized_drift"] == pytest.approx(np.exp(drift * 365) - 1, rel=1e-9)

    def test_simulation_is_deterministic_under_seed(self, monkeypatch):
        monkeypatch.setattr(forecast, "N_SIMS", 50)
        monkeypatch.setattr(forecast, "HORIZON_DAYS", 60)
        series = np.log(np.linspace(100, 130, 200))
        fit = forecast.fit_rw_drift(series)
        a = forecast.simulate_rw_drift(fit, np.log(120.0), np.random.default_rng(42))
        b = forecast.simulate_rw_drift(fit, np.log(120.0), np.random.default_rng(42))
        np.testing.assert_array_equal(a, b)
