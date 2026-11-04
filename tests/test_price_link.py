from __future__ import annotations

import numpy as np
import pytest

from analysis.price_link import ols_newey_west


class TestOlsNeweyWest:
    def test_recovers_known_betas(self):
        rng = np.random.default_rng(3)
        n = 500
        x1 = rng.normal(size=n)
        x2 = rng.normal(size=n)
        y = 1.5 + 2.0 * x1 - 0.7 * x2 + rng.normal(0, 0.01, size=n)
        X = np.column_stack([np.ones(n), x1, x2])
        fit = ols_newey_west(y, X, lags=4)
        np.testing.assert_allclose(fit["beta"], [1.5, 2.0, -0.7], atol=0.01)

    def test_zero_lags_equals_white_errors(self):
        rng = np.random.default_rng(5)
        n = 200
        x = rng.normal(size=n)
        y = 0.5 * x + rng.normal(size=n)
        X = np.column_stack([np.ones(n), x])
        fit = ols_newey_west(y, X, lags=0)
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ beta
        XtX_inv = np.linalg.inv(X.T @ X)
        meat = sum(np.outer(X[t], X[t]) * resid[t] ** 2 for t in range(n))
        white_se = np.sqrt(np.diag(XtX_inv @ meat @ XtX_inv))
        np.testing.assert_allclose(fit["se"], white_se, rtol=1e-10)

    def test_null_regressor_gives_small_t(self):
        rng = np.random.default_rng(11)
        n = 300
        x_real = rng.normal(size=n)
        x_noise = rng.normal(size=n)
        y = 1.0 * x_real + rng.normal(size=n)
        X = np.column_stack([np.ones(n), x_real, x_noise])
        fit = ols_newey_west(y, X, lags=4)
        assert abs(fit["t"][1]) > 5
        assert abs(fit["t"][2]) < 3

    def test_autocorrelated_errors_widen_se(self):
        rng = np.random.default_rng(7)
        n = 400
        x = rng.normal(size=n)
        e = np.zeros(n)
        for t in range(1, n):
            e[t] = 0.8 * e[t - 1] + rng.normal()
        y = 0.5 * x + e
        X = np.column_stack([np.ones(n), x])
        se_hac = ols_newey_west(y, X, lags=8)["se"][1]
        se_iid = ols_newey_west(y, X, lags=0)["se"][1]
        assert se_hac > se_iid * 0.9
