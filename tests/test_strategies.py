"""策略库单元测试：Strategy B~F 的因子口径 / 排名方向 / NaN 处理 /
PIT / 注册表 / 引擎接入 / 回测兼容性（全部合成数据，不依赖真实 parquet）。

覆盖（用户要求的最小集）：
- 因子计算（short_term_reversal / trend 手工核算）
- 排名方向（反转选跌幅最大、低波动选波动最小、趋势选均线最强）
- NaN 处理（数据不足排除）
- PIT / no-lookahead（未来股票不进排名；退市股 PIT 池可进）
- 策略注册（6 个都在注册表；B/C 标记数据不足）
- 引擎接入（D/E/F 与 Strategy A 走同一 run_strategy 流程；B/C 拒绝运行）
- 回测兼容（run_backtest 直接接受 D/E/F）
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from quant.backtest.runner import run_backtest
from quant.engine import run_strategy
from quant.factors.registry import get_factor
from quant.strategies import all_strategies, get_strategy
from quant.strategies.strategy_a import StrategyA
from quant.strategies.strategy_d import StrategyD
from quant.strategies.strategy_e import StrategyE
from quant.strategies.strategy_f import StrategyF

from tests.test_backtest import TestLoader


def make_dates(n, end="2024-06-28"):
    return pd.bdate_range(end=end, periods=n).strftime("%Y%m%d").tolist()


def make_market(closes_by_code: dict, vol: float = 1000.0):
    """closes_by_code: {code: [len(n) 收盘价序列]}，open=close。"""
    n = len(next(iter(closes_by_code.values())))
    dates = make_dates(n)
    rows = []
    for code, closes in closes_by_code.items():
        for d, c in zip(dates, closes):
            rows.append({"ts_code": code, "trade_date": d,
                         "close_adj": float(c), "open_adj": float(c), "vol": vol})
    return pd.DataFrame(rows)


class TestRegistry(unittest.TestCase):
    def test_all_six_registered(self):
        names = sorted(s.__name__ for s in all_strategies())
        self.assertEqual(names, ["StrategyA", "StrategyB", "StrategyC",
                                 "StrategyD", "StrategyE", "StrategyF"])

    def test_bc_unavailable(self):
        for name in ("strategy_b", "strategy_c"):
            s = get_strategy(name)()
            self.assertFalse(s.data_available)
            self.assertTrue(s.unavailable_reason)
            self.assertEqual(s.weights, {})
        for name in ("strategy_a", "strategy_d", "strategy_e", "strategy_f"):
            self.assertTrue(get_strategy(name)().data_available)

    def test_new_factors_registered(self):
        r = get_factor("short_term_reversal")
        self.assertEqual(r.direction, "lower_better")
        self.assertEqual(r.default_windows, (5,))
        t = get_factor("trend")
        self.assertEqual(t.direction, "higher_better")
        self.assertEqual(t.default_windows, (20, 60))
        # 趋势因子窗口约束
        with self.assertRaises(ValueError):
            t.check_windows((60, 20))


class TestShortTermReversalFactor(unittest.TestCase):
    def test_5day_return_hand_computed(self):
        """close_adj 1..6：5 日收益 = 6/1 − 1 = 5.0（与 momentum 同一计算函数）。"""
        from quant.factors.registry import get_compute
        market = make_market({"A": [1, 2, 3, 4, 5, 6]})
        out = get_compute("short_term_reversal")(market, (5,))
        self.assertAlmostEqual(out["A"], 5.0)

    def test_insufficient_rows_nan(self):
        from quant.factors.registry import get_compute
        market = make_market({"A": [1, 2, 3, 4]})
        out = get_compute("short_term_reversal")(market, (5,))
        self.assertTrue(pd.isna(out["A"]))

    def test_same_value_as_momentum(self):
        """与 momentum 同口径：同一市场下两个因子原始值完全一致（方向相反）。"""
        from quant.factors.registry import get_compute
        market = make_market({"A": [1, 2, 3, 4, 5, 6], "B": [6, 5, 4, 3, 2, 1]})
        rev = get_compute("short_term_reversal")(market, (5,))
        mom = get_compute("momentum")(market, (5,))
        pd.testing.assert_series_equal(rev, mom)


class TestTrendFactor(unittest.TestCase):
    def test_ma_ratio_hand_computed(self):
        """窗口 (2,3)：closes [1,1,1,1,2,3] → 最后一日 MA2=(2+3)/2=2.5，
        MA3=(1+2+3)/3=2.0 → ratio = 2.5/2.0 − 1 = 0.25。"""
        from quant.factors.registry import get_compute
        market = make_market({"A": [1, 1, 1, 1, 2, 3]})
        out = get_compute("trend")(market, (2, 3))
        self.assertAlmostEqual(out["A"], 0.25)

    def test_insufficient_rows_nan(self):
        """2 行数据 < 长窗口 3 → NaN。"""
        from quant.factors.registry import get_compute
        market = make_market({"A": [1, 1]})
        out = get_compute("trend")(market, (2, 3))
        self.assertTrue(pd.isna(out["A"]))


class TestEngineDirections(unittest.TestCase):
    """排名方向（各策略用独立的手工核算场景）：反转选跌幅最大、
    低波动选波动最小、趋势选均线最强。"""

    def _run(self, strategy, market, names=None) -> pd.DataFrame:
        loader = TestLoader(market=market,
                            index=pd.DataFrame(columns=["trade_date", "close"]),
                            names=names or {})
        as_of = market["trade_date"].iloc[-1]
        return run_strategy(strategy, as_of=as_of, loader=loader).ranking

    def test_strategy_d_reversal_ranks_biggest_loser_first(self):
        """5 日收益：DOWN = 0.91/0.96−1 < 0 最负 → 反转第 1；UP = +0.048 最末。"""
        market = make_market({"UP": [1 + 0.01 * i for i in range(10)],
                              "DOWN": [1 - 0.01 * i for i in range(10)]})
        r = self._run(StrategyD(use_stock_list=False), market)
        self.assertEqual(r.iloc[0]["ts_code"], "DOWN")
        self.assertEqual(r.iloc[-1]["ts_code"], "UP")

    def test_strategy_e_low_vol_ranks_flat_first(self):
        """波动率：FLAT=0 < MILD(±0.5%) < CHOPPY(±2%) → FLAT 第 1、CHOPPY 最末。"""
        n = 25
        flat = [1.0] * n
        mild, choppy = [1.0], [1.0]
        for i in range(1, n):
            mild.append(mild[-1] * (1 + (0.005 if i % 2 else -0.005)))
            choppy.append(choppy[-1] * (1 + (0.02 if i % 2 else -0.02)))
        market = make_market({"FLAT": flat, "MILD": mild, "CHOPPY": choppy})
        r = self._run(StrategyE(use_stock_list=False), market)
        self.assertEqual(r.iloc[0]["ts_code"], "FLAT")
        self.assertEqual(r.iloc[-1]["ts_code"], "CHOPPY")

    def test_strategy_f_trend_ranks_uptrend_first(self):
        """MA20/MA60−1：UP > 0（多头排列）第 1；DOWN < 0 最末；FLAT = 0 居中。"""
        n = 70
        market = make_market({"UP": [1 + 0.01 * i for i in range(n)],
                              "DOWN": [1 - 0.01 * i for i in range(n)],
                              "FLAT": [1.0] * n})
        r = self._run(StrategyF(use_stock_list=False), market)
        self.assertEqual(r.iloc[0]["ts_code"], "UP")
        self.assertEqual(r.iloc[-1]["ts_code"], "DOWN")

    def test_insufficient_history_excluded(self):
        """只有 10 天行情的股票不满足 60 日趋势窗口 → NaN → 排除出排名。"""
        n = 70
        market = pd.concat([
            make_market({"UP": [1 + 0.01 * i for i in range(n)]}),
            make_market({"NEW": [1.0] * 10}),
        ], ignore_index=True)
        r = self._run(StrategyF(use_stock_list=False), market)
        self.assertNotIn("NEW", set(r["ts_code"]))

    def test_pit_universe_switch_works_for_new_strategies(self):
        """PIT 开关对 D 同样生效：不在 stock_list（退市股）可进 PIT 排名。"""
        market = make_market({"UP": [1 + 0.01 * i for i in range(10)],
                              "DOWN": [1 - 0.01 * i for i in range(10)]})
        r_default = self._run(StrategyD(), market, names={"UP": "涨"})   # 当前列表不含 DOWN
        r_pit = self._run(StrategyD(use_stock_list=False), market,
                          names={"UP": "涨"})
        self.assertNotIn("DOWN", set(r_default["ts_code"]))
        self.assertIn("DOWN", set(r_pit["ts_code"]))

    def test_no_index_needed_for_def(self):
        """D/E/F 不依赖指数：指数数据为空也能正常运行（engine needs_index 判定）。"""
        n = 70
        market = make_market({"UP": [1 + 0.01 * i for i in range(n)],
                              "DOWN": [1 - 0.01 * i for i in range(n)],
                              "FLAT": [1.0] * n})
        loader = TestLoader(market=market,
                            index=pd.DataFrame(columns=["trade_date", "close"]))
        as_of = market["trade_date"].iloc[-1]
        r = run_strategy(StrategyF(use_stock_list=False), as_of=as_of, loader=loader)
        self.assertEqual(len(r.ranking), 3)
        # 对照：Strategy A 含相对强度（needs_index）→ 指数为空必须报错
        with self.assertRaises(ValueError):
            run_strategy(StrategyA(), as_of=as_of, loader=loader)


class TestUnavailableStrategies(unittest.TestCase):
    def test_engine_refuses_bc(self):
        """B/C：引擎拒绝运行并给出原因（不产出虚假排名）。"""
        loader = TestLoader(market=make_market({"A": [1.0] * 5}))
        for name in ("strategy_b", "strategy_c"):
            with self.assertRaises(ValueError) as ctx:
                run_strategy(get_strategy(name)(), as_of=make_dates(5)[-1],
                             loader=loader)
            self.assertIn("暂不能可靠实现", str(ctx.exception))

    def test_backtest_refuses_bc_with_warning_not_crash(self):
        """回测遇到不可用策略：单次调仓失败记录警告，回测不崩溃。"""
        d5 = make_dates(5)
        loader = TestLoader(market=make_market({"A": [1.0] * 5}))
        res = run_backtest(get_strategy("strategy_b")(), d5[0], d5[-1],
                           top_n=1, rebalance_every=1, cost_rate=0.0, loader=loader)
        self.assertEqual(len(res.rebalances), 0)
        self.assertTrue(res.trades.empty)
        self.assertTrue(any("排名计算失败" in w for w in res.warnings))


class TestBacktestCompatibility(unittest.TestCase):
    """新增策略直接接入现有 Backtest MVP（与 Strategy A 同一流程）。"""

    def test_run_backtest_with_strategy_f_real_engine(self):
        n = 70
        market = make_market({
            "UP": [1.0 + 0.01 * i for i in range(n)],
            "DOWN": [1.0 - 0.01 * i for i in range(n)],
            "FLAT": [1.0] * n,
        })
        loader = TestLoader(market=market,
                            index=pd.DataFrame(columns=["trade_date", "close"]))
        res = run_backtest(StrategyF(use_stock_list=False),
                           make_dates(n)[0], make_dates(n)[-1],
                           top_n=1, rebalance_every=5, cost_rate=0.0, loader=loader)
        self.assertEqual(res.params["strategy"], "strategy_f")
        # 趋势最强者 UP 恒被选中；DOWN/FLAT 永不成交
        self.assertEqual(set(res.trades["ts_code"]), {"UP"})
        # 无基准数据 → 明确警告而非报错
        self.assertNotIn("benchmark", res.nav.columns)
        self.assertTrue(any("基准" in w for w in res.warnings))


if __name__ == "__main__":
    unittest.main()
