"""quant/factors 单元测试：四个因子的计算口径与缺失数据处理（合成数据，不依赖真实 parquet）。"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from quant.factors import momentum, relative_strength, volatility, volume_trend
from quant.factors.registry import get_factor


def make_dates(n, end="2026-09-15"):
    return pd.bdate_range(end=end, periods=n).strftime("%Y%m%d")


def make_market(rows):
    """rows: [(ts_code, trade_date, close_adj, vol), ...]，刻意不排序以验证因子内部排序。"""
    return pd.DataFrame(rows, columns=["ts_code", "trade_date", "close_adj", "vol"])


class TestMomentum(unittest.TestCase):
    def test_60d_return(self):
        """60 日收益率：close_T / close_{T-60} - 1 = 65/5 - 1 = 12。"""
        dates = make_dates(65)
        rows = [("A", d, float(i + 1), 1.0) for i, d in enumerate(dates)]
        ret = momentum.compute(make_market(rows), (60,))
        self.assertAlmostEqual(ret["A"], 12.0)

    def test_window_change_changes_value(self):
        """窗口参数 60 → 5，收益率随之变化：65/60 - 1 ≈ 0.0833。"""
        dates = make_dates(65)
        rows = [("A", d, float(i + 1), 1.0) for i, d in enumerate(dates)]
        ret = momentum.compute(make_market(rows), (5,))
        self.assertAlmostEqual(ret["A"], 65 / 60 - 1.0)

    def test_interleaved_stocks_no_leakage(self):
        """两只股票行交错存储，分组计算互不串扰。"""
        dates = make_dates(65)
        rows = []
        for i, d in enumerate(dates):
            rows.append(("A", d, float(i + 1), 1.0))   # 1..65 → 60日收益 12
            rows.append(("B", d, 10.0, 1.0))           # 恒定 → 0
        ret = momentum.compute(make_market(rows), (60,))
        self.assertAlmostEqual(ret["A"], 12.0)
        self.assertAlmostEqual(ret["B"], 0.0)

    def test_insufficient_history_is_nan(self):
        """不足 61 根 K 线无法计算 60 日收益率 → NaN。"""
        dates = make_dates(30)
        rows = [("A", d, float(i + 1), 1.0) for i, d in enumerate(dates)]
        ret = momentum.compute(make_market(rows), (60,))
        self.assertTrue(pd.isna(ret["A"]))


class TestVolatility(unittest.TestCase):
    def test_20d_std_of_daily_returns(self):
        """20 个日收益率交替 +1%/-1%，样本标准差 ddof=1 = sqrt(0.002/19)。"""
        dates = make_dates(21)
        closes = [100.0]
        for i in range(20):
            closes.append(closes[-1] * (1.01 if i % 2 == 0 else 0.99))
        rows = [(("A", d, c, 1.0)) for d, c in zip(dates, closes)]
        vol = volatility.compute(make_market(rows), (20,))
        self.assertAlmostEqual(vol["A"], math.sqrt(0.002 / 19), places=6)

    def test_constant_price_zero_vol(self):
        dates = make_dates(25)
        rows = [(("A", d, 10.0, 1.0)) for d in dates]
        vol = volatility.compute(make_market(rows), (20,))
        self.assertAlmostEqual(vol["A"], 0.0)

    def test_insufficient_history_is_nan(self):
        """只有 20 根 K 线（19 个收益率）→ 20 日波动率 NaN。"""
        dates = make_dates(20)
        rows = [("A", d, float(i + 1), 1.0) for i, d in enumerate(dates)]
        vol = volatility.compute(make_market(rows), (20,))
        self.assertTrue(pd.isna(vol["A"]))


class TestVolumeTrend(unittest.TestCase):
    def test_20_60_ratio(self):
        """前 60 日 vol=10、后 20 日 vol=20：20日均=20，60日均=13.33，比=1.5。"""
        dates = make_dates(80)
        rows = [("A", d, 10.0, 20.0 if i >= 60 else 10.0) for i, d in enumerate(dates)]
        ratio = volume_trend.compute(make_market(rows), (20, 60))
        self.assertAlmostEqual(ratio["A"], 1.5, places=6)

    def test_insufficient_history_is_nan(self):
        """30 根 K 线不足长窗口 60 → NaN。"""
        dates = make_dates(30)
        rows = [("A", d, float(i + 1), 1.0) for i, d in enumerate(dates)]
        ratio = volume_trend.compute(make_market(rows), (20, 60))
        self.assertTrue(pd.isna(ratio["A"]))

    def test_short_must_be_less_than_long(self):
        """短窗口 ≥ 长窗口时窗口校验报错。"""
        with self.assertRaises(ValueError):
            get_factor("volume_trend").check_windows((60, 20))


class TestRelativeStrength(unittest.TestCase):
    def test_rs_against_flat_index(self):
        """个股 60 日收益 60.0，指数收益 0 → RS = 60.0。"""
        dates = make_dates(61)
        rows = [("A", d, float(i + 1), 1.0) for i, d in enumerate(dates)]
        index = pd.DataFrame({"trade_date": dates, "close": 10.0})
        rs = relative_strength.compute(make_market(rows), (60,), index=index, as_of=dates[-1])
        self.assertAlmostEqual(rs["A"], 60.0)

    def test_rs_subtracts_index_return(self):
        """指数同期上涨 30%（10 → 13）→ RS = 60.0 - 0.3 = 59.7。"""
        dates = make_dates(61)
        rows = [("A", d, float(i + 1), 1.0) for i, d in enumerate(dates)]
        index = pd.DataFrame({"trade_date": dates,
                              "close": np.linspace(10.0, 13.0, 61)})
        rs = relative_strength.compute(make_market(rows), (60,), index=index, as_of=dates[-1])
        self.assertAlmostEqual(rs["A"], 59.7)

    def test_missing_index_raises(self):
        """指数数据缺失时明确报错，而不是静默产生全 NaN。"""
        dates = make_dates(61)
        rows = [("A", d, float(i + 1), 1.0) for i, d in enumerate(dates)]
        with self.assertRaises(ValueError):
            relative_strength.compute(make_market(rows), (60,), index=None, as_of=dates[-1])

    def test_insufficient_stock_history_is_nan(self):
        dates = make_dates(61)
        rows = [(("A", d, float(i + 1), 1.0)) for i, d in enumerate(dates[:30])]
        index = pd.DataFrame({"trade_date": dates, "close": 10.0})
        rs = relative_strength.compute(make_market(rows), (60,), index=index, as_of=dates[-1])
        self.assertTrue(pd.isna(rs["A"]))


if __name__ == "__main__":
    unittest.main()
