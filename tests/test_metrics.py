"""quant/backtest/metrics 单元测试：指标口径全部手工计算核对。

覆盖：累计/年化收益、最大回撤、胜率、超额收益，以及 NaN/空序列边界。
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from quant.backtest.metrics import (
    annualized_return,
    cumulative_return,
    excess_return,
    max_drawdown,
    win_rate,
)


class TestCumulativeReturn(unittest.TestCase):
    def test_simple(self):
        """[1, 1.1, 0.99] → 0.99/1 − 1 = −0.01。"""
        self.assertAlmostEqual(cumulative_return(pd.Series([1.0, 1.1, 0.99])), -0.01)

    def test_flat(self):
        self.assertEqual(cumulative_return(pd.Series([1.0, 1.0, 1.0])), 0.0)

    def test_len1_is_nan(self):
        self.assertTrue(math.isnan(cumulative_return(pd.Series([1.0]))))

    def test_empty_is_nan(self):
        self.assertTrue(math.isnan(cumulative_return(pd.Series([], dtype="float64"))))

    def test_nan_dropped(self):
        """NaN 值被丢弃后按剩余值计算：[1, NaN, 1.2] → 0.2。"""
        self.assertAlmostEqual(
            cumulative_return(pd.Series([1.0, float("nan"), 1.2])), 0.2)

    def test_zero_start_is_nan(self):
        self.assertTrue(math.isnan(cumulative_return(pd.Series([0.0, 1.0, 2.0]))))

    def test_list_input(self):
        self.assertAlmostEqual(cumulative_return([100.0, 90.0]), -0.1)


class TestAnnualizedReturn(unittest.TestCase):
    def test_known(self):
        """2 个点：[1, 1.1] → 1.1**252 − 1（公式口径核对）。"""
        expected = 1.1 ** 252 - 1.0
        self.assertAlmostEqual(annualized_return(pd.Series([1.0, 1.1])), expected)

    def test_flat(self):
        self.assertEqual(annualized_return(pd.Series([1.0, 1.0, 1.0])), 0.0)

    def test_periods_per_year_override(self):
        """periods_per_year 可覆盖：[1, 1.1] 按 2 期 → 1.1**2 − 1。"""
        self.assertAlmostEqual(
            annualized_return(pd.Series([1.0, 1.1]), periods_per_year=2), 0.21)

    def test_len1_is_nan(self):
        self.assertTrue(math.isnan(annualized_return(pd.Series([1.0]))))

    def test_nonpositive_is_nan(self):
        self.assertTrue(math.isnan(annualized_return(pd.Series([1.0, 0.0]))))


class TestMaxDrawdown(unittest.TestCase):
    def test_known(self):
        """[1, 1.2, 1.0, 1.1]：峰值 1.2，谷值 1.0 → 1 − 1/1.2 = 1/6。"""
        self.assertAlmostEqual(max_drawdown(pd.Series([1.0, 1.2, 1.0, 1.1])), 1.0 / 6.0)

    def test_no_decline(self):
        self.assertEqual(max_drawdown(pd.Series([1.0, 1.1, 1.2])), 0.0)

    def test_short_is_zero(self):
        self.assertEqual(max_drawdown(pd.Series([1.0])), 0.0)

    def test_empty_is_zero(self):
        self.assertEqual(max_drawdown(pd.Series([], dtype="float64")), 0.0)

    def test_returns_positive(self):
        """回撤以正数返回（展示口径）。"""
        self.assertGreater(max_drawdown(pd.Series([1.0, 0.5, 0.8])), 0.0)


class TestWinRate(unittest.TestCase):
    def test_known(self):
        """[0.01, −0.02, 0.03] → 2/3。"""
        self.assertAlmostEqual(win_rate(pd.Series([0.01, -0.02, 0.03])), 2.0 / 3.0)

    def test_zero_not_win(self):
        """收益恰为 0 不算获胜期：[0.0, 0.01] → 0.5。"""
        self.assertAlmostEqual(win_rate(pd.Series([0.0, 0.01])), 0.5)

    def test_all_win(self):
        self.assertEqual(win_rate(pd.Series([0.01, 0.02])), 1.0)

    def test_empty_is_nan(self):
        self.assertTrue(math.isnan(win_rate(pd.Series([], dtype="float64"))))

    def test_nan_dropped(self):
        self.assertEqual(win_rate(pd.Series([0.01, float("nan")])), 1.0)


class TestExcessReturn(unittest.TestCase):
    def test_known(self):
        """组合 +20%、基准 +5% → 超额 +15%。"""
        self.assertAlmostEqual(
            excess_return(pd.Series([1.0, 1.2]), pd.Series([1.0, 1.05])), 0.15)

    def test_underperform(self):
        self.assertAlmostEqual(
            excess_return(pd.Series([1.0, 0.9]), pd.Series([1.0, 1.1])), -0.2)


if __name__ == "__main__":
    unittest.main()
