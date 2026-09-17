"""quant/engine 端到端单元测试：Strategy A 全流程（合成数据 + FakeLoader，不依赖真实 parquet）。

覆盖：权重合成、横截面标准化 + 方向反转、缺失数据排除、停牌排除、
权重/窗口参数调整后结果变化、权重与窗口校验、as_of 兜底。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from quant.cross_section import zscore
from quant.engine import run_strategy
from quant.factors.registry import get_factor
from quant.strategies.strategy_a import StrategyA

N_DAYS = 130
END = "20260915"   # 与引擎内部的 YYYYMMDD 口径一致


class FakeLoader:
    """内存版数据源，接口与 MarketDataLoader 一致。"""

    def __init__(self, market, index, names, latest=None):
        self.market = market
        self.index = index
        self.names = names
        self.latest = latest or str(market["trade_date"].max())

    def load_market_data(self, start, end, columns=("ts_code", "trade_date", "close_adj", "vol")):
        mask = (self.market["trade_date"] >= start) & (self.market["trade_date"] <= end)
        return self.market.loc[mask, list(columns)].copy()

    def load_index(self, start, end):
        mask = (self.index["trade_date"] >= start) & (self.index["trade_date"] <= end)
        return self.index.loc[mask].copy()

    def latest_trade_date(self):
        return self.latest

    def stock_names(self):
        return self.names


def build_fake_market():
    """8 只股票 × 130 个交易日：A~F 正常，G 只有 30 天（因子不可算），H 停牌 2 天（无当日行情）。"""
    dates = pd.bdate_range(end="2026-09-15", periods=N_DAYS).strftime("%Y%m%d")
    codes = [f"60000{i}.SH" for i in range(8)]
    rng = np.random.default_rng(42)
    rows = []
    for i, code in enumerate(codes):
        if code == "600006.SH":
            t_start, t_end = N_DAYS - 30, N_DAYS        # G：只上市 30 天（截至计算日）
        elif code == "600007.SH":
            t_start, t_end = 0, N_DAYS - 2              # H：最后 2 天停牌
        else:
            t_start, t_end = 0, N_DAYS
        n = t_end - t_start
        drift = 0.0005 + 0.0004 * i
        rets = drift + 0.02 * np.sin(np.arange(n) / 10 + i * 0.9) + rng.normal(0, 0.004, n)
        closes = 100 * np.cumprod(1 + rets)
        vol_trend = 0.3 + 0.08 * i                                  # 量能趋势差异化
        vols = 1e6 * (1 + vol_trend * np.sin(np.arange(n) / 7 + i) + 0.4 * np.arange(n) / N_DAYS)
        for t in range(n):
            rows.append((code, dates[t_start + t], closes[t], vols[t]))
    market = pd.DataFrame(rows, columns=["ts_code", "trade_date", "close_adj", "vol"])

    idx_rets = 0.0003 + 0.005 * np.sin(np.arange(N_DAYS) / 20)
    index = pd.DataFrame({"trade_date": dates, "close": 100 * np.cumprod(1 + idx_rets)})

    names = {code: f"股票{code}" for code in codes}
    return FakeLoader(market, index, names)


class TestEnginePipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = build_fake_market()

    def test_full_pipeline_and_score_composition(self):
        res = run_strategy(StrategyA(), loader=self.loader)
        r = res.ranking
        self.assertEqual(res.as_of, END)
        self.assertEqual(res.universe_size, 6)     # 排除 G（数据不足）与 H（停牌）
        self.assertEqual(res.excluded_count, 2)
        self.assertEqual(list(r["rank"]), list(range(1, 7)))
        self.assertTrue((r["score"].diff().dropna() <= 0).all())   # 按得分降序
        self.assertNotIn("600006.SH", set(r["ts_code"]))
        self.assertNotIn("600007.SH", set(r["ts_code"]))
        # 权重合成：score = Σ(标准化因子 × 方向符号 × 权重)，权重归一化和为 1
        expected = sum(res.weights[f] * r[f"{f}_score"] for f in StrategyA.factor_names)
        pd.testing.assert_series_equal(r["score"], expected, check_names=False)
        self.assertAlmostEqual(sum(res.weights.values()), 1.0)
        self.assertEqual(res.windows, StrategyA.default_windows)

    def test_scores_match_independent_standardization(self):
        """每一列 *_score 都等于在最终股票池内重算的 z-score × 方向符号。"""
        res = run_strategy(StrategyA(), loader=self.loader)
        r = res.ranking
        for fname in StrategyA.factor_names:
            spec = get_factor(fname)
            sign = 1.0 if spec.direction == "higher_better" else -1.0
            expected = zscore(r[f"{fname}_raw"]) * sign
            pd.testing.assert_series_equal(
                r[f"{fname}_score"], expected.reset_index(drop=True),
                check_names=False, check_exact=False, rtol=1e-12, atol=1e-12)

    def test_volatility_direction_reversed(self):
        """波动率越低越好：原始值高于横截面均值 → 得分为负。"""
        res = run_strategy(StrategyA(), loader=self.loader)
        r = res.ranking
        mean_vol = r["volatility_raw"].mean()
        high = r[r["volatility_raw"] > mean_vol]
        low = r[r["volatility_raw"] < mean_vol]
        self.assertTrue((high["volatility_score"] < 0).all())
        self.assertTrue((low["volatility_score"] > 0).all())

    def test_weight_change_changes_result(self):
        """权重调整后排名确实变化：momentum 权重 100% 时 score == momentum_score。"""
        default = run_strategy(StrategyA(), loader=self.loader)
        w = {"momentum": 1.0, "volatility": 0.0, "volume_trend": 0.0, "relative_strength": 0.0}
        res = run_strategy(StrategyA(weights=w), loader=self.loader)
        pd.testing.assert_series_equal(res.ranking["score"], res.ranking["momentum_score"],
                                       check_names=False)
        self.assertNotEqual(list(default.ranking["ts_code"]), list(res.ranking["ts_code"]))

    def test_window_change_changes_result(self):
        """窗口参数调整后排名确实变化：momentum 60 日 → 10 日。"""
        default = run_strategy(StrategyA(), loader=self.loader)
        res = run_strategy(StrategyA(windows={"momentum": (10,)}), loader=self.loader)
        self.assertEqual(res.windows["momentum"], (10,))
        self.assertNotEqual(list(default.ranking["ts_code"]), list(res.ranking["ts_code"]))

    def test_rank_standardize_method(self):
        s = StrategyA()
        s.standardize_method = "rank"
        res = run_strategy(s, loader=self.loader)
        self.assertTrue(((res.ranking["score"] >= -1) & (res.ranking["score"] <= 1)).all())

    def test_as_of_defaults_to_latest(self):
        res = run_strategy(StrategyA(), loader=self.loader)
        self.assertEqual(res.as_of, END)

    def test_as_of_falls_back_to_data_max(self):
        """所选日期晚于数据最新日期时回退到数据最新日期并给出警告。"""
        res = run_strategy(StrategyA(), as_of="20260930", loader=self.loader)
        self.assertEqual(res.as_of, END)
        self.assertTrue(any("改用" in w for w in res.warnings))


class TestStrategyValidation(unittest.TestCase):
    def test_negative_weight_raises(self):
        with self.assertRaises(ValueError):
            StrategyA(weights={"momentum": -0.1})

    def test_zero_total_weight_raises(self):
        with self.assertRaises(ValueError):
            StrategyA(weights={"momentum": 0.0, "volatility": 0.0,
                              "volume_trend": 0.0, "relative_strength": 0.0})

    def test_unknown_factor_raises(self):
        with self.assertRaises(ValueError):
            StrategyA(weights={"magic_factor": 0.1})

    def test_partial_weights_merge_with_defaults(self):
        s = StrategyA(weights={"momentum": 0.5})
        self.assertAlmostEqual(s.weights["momentum"], 0.5 / (0.5 + 0.25 * 3))

    def test_weights_normalized_to_one(self):
        s = StrategyA(weights={"momentum": 0.2, "volatility": 0.2,
                               "volume_trend": 0.2, "relative_strength": 0.2})
        self.assertAlmostEqual(sum(s.weights.values()), 1.0)
        self.assertAlmostEqual(s.weights["momentum"], 0.25)

    def test_wrong_window_count_raises(self):
        with self.assertRaises(ValueError):
            StrategyA(windows={"momentum": (60, 20)})

    def test_invalid_volume_trend_windows_raise(self):
        with self.assertRaises(ValueError):
            StrategyA(windows={"volume_trend": (60, 20)})


if __name__ == "__main__":
    unittest.main()
