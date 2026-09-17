"""quant/backtest 核心测试：PIT 股票池（幸存者偏差）、无未来数据泄漏、
runner 组合数学（手工核算）、与真实引擎的端到端集成。

全部用合成数据（内存 loader），不依赖真实 parquet、不联网。

关键场景：
- PIT：历史退市股（不在当前 stock_list）在 use_stock_list=False 时进入历史排名；
- 无泄漏：未来才有数据的股票绝不提前成交；成交价 = 次一交易日开盘价；
- 停牌：执行日停牌 → 不假装成交；持仓停牌 → ffill 最后可用价估值、无法卖出。
"""

import math
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from quant.backtest.runner import run_backtest
from quant.engine import RankingResult, run_strategy
from quant.strategies.strategy_a import StrategyA

DATES = pd.bdate_range("2024-01-02", periods=10).strftime("%Y%m%d").tolist()
D0, D1 = DATES[0], DATES[1]          # 20240102, 20240103
LAST = DATES[-1]                      # 20240115


class TestLoader:
    """内存数据源：接口与 MarketDataLoader 一致（含 open_adj/vol）。"""

    def __init__(self, market: pd.DataFrame, index: pd.DataFrame = None, names: dict = None):
        self.market = market
        self.index = (index if index is not None
                      else pd.DataFrame(columns=["trade_date", "close"]))
        self.names = names or {}

    def load_market_data(self, start, end, columns=("ts_code", "trade_date", "close_adj", "vol")):
        mask = (self.market["trade_date"] >= start) & (self.market["trade_date"] <= end)
        return self.market.loc[mask, list(columns)].copy()

    def load_index(self, start, end):
        mask = (self.index["trade_date"] >= start) & (self.index["trade_date"] <= end)
        return self.index.loc[mask, ["trade_date", "close"]].copy()

    def stock_names(self):
        return dict(self.names)


def make_rows(codes, dates, close_fn, open_fn=None):
    """构造长表行情：close/open 按索引 i 生成（open 缺省 = close）。"""
    rows = []
    for code in codes:
        for i, d in enumerate(dates):
            rows.append({
                "ts_code": code, "trade_date": d,
                "close_adj": close_fn(code, i),
                "open_adj": (open_fn(code, i) if open_fn else close_fn(code, i)),
                "vol": 1000.0,
            })
    return pd.DataFrame(rows)


def make_index(dates, base=3000.0, step=30.0):
    return pd.DataFrame({
        "trade_date": dates,
        "close": [base + step * i for i in range(len(dates))],
    })


def stub_result(codes, as_of):
    """可控排名的 RankingResult（runner 只读 rank/ts_code/warnings/universe_size）。"""
    ranking = pd.DataFrame({
        "rank": range(1, len(codes) + 1),
        "ts_code": list(codes),
        "name": list(codes),
        "score": [1.0] * len(codes),
        "last_date": [as_of] * len(codes),
    })
    return RankingResult(as_of=as_of, universe_size=len(codes), excluded_count=0,
                         ranking=ranking, weights={}, windows={}, method="zscore")


def scenario_a_market():
    """A：收盘恒 10（d1 开盘 11）；B：收盘恒 20（d1 开盘 20.5）；全区间有行情。"""
    def close(code, i):
        return 10.0 if code == "A" else 20.0

    def open_(code, i):
        if i == 1 and code == "A":
            return 11.0
        if i == 1 and code == "B":
            return 20.5
        return close(code, i)

    return make_rows(["A", "B"], DATES, close, open_)


class TestPITUniverse(unittest.TestCase):
    """幸存者偏差：use_stock_list 开关控制是否用当前股票列表过滤历史股票池。

    DELIST.SZ 在历史区间有行情但不在当前 stock_list（names 不含它）：
    默认模式（实盘页面口径）排除，PIT 模式（回测口径）纳入且排名第 1。
    """

    @classmethod
    def setUpClass(cls):
        d5 = pd.bdate_range("2024-01-02", periods=5).strftime("%Y%m%d").tolist()
        rows = []
        for i, d in enumerate(d5):
            rows.append({"ts_code": "DELIST.SZ", "trade_date": d,
                         "close_adj": 1.01 ** i, "open_adj": 1.01 ** i, "vol": 1000.0})
            for code in ("KEEP1.SZ", "KEEP2.SZ"):
                rows.append({"ts_code": code, "trade_date": d,
                             "close_adj": 1.0, "open_adj": 1.0, "vol": 1000.0})
        cls.loader = TestLoader(
            market=pd.DataFrame(rows),
            index=make_index(d5, base=3000.0, step=3.0),
            names={"KEEP1.SZ": "甲", "KEEP2.SZ": "乙"},   # 当前列表：不含退市股
        )
        cls.as_of = d5[-1]

    def _run(self, use_stock_list: bool) -> RankingResult:
        strategy = StrategyA(
            use_stock_list=use_stock_list,
            windows={"momentum": (2,), "volatility": (2,),
                     "volume_trend": (2, 3), "relative_strength": (2,)})
        return run_strategy(strategy, as_of=self.as_of, loader=self.loader)

    def test_current_list_mode_excludes_delisted(self):
        """默认（实盘口径）：股票池限定当前列表，历史退市股不进入排名。"""
        codes = set(self._run(True).ranking["ts_code"])
        self.assertNotIn("DELIST.SZ", codes)
        self.assertLessEqual(codes, {"KEEP1.SZ", "KEEP2.SZ"})

    def test_pit_mode_includes_delisted(self):
        """PIT（回测口径）：当日有行情即在池，退市股进入排名且（本例）排第 1。"""
        r = self._run(False)
        codes = set(r.ranking["ts_code"])
        self.assertIn("DELIST.SZ", codes)
        self.assertEqual(r.ranking.iloc[0]["ts_code"], "DELIST.SZ")


class TestRunnerMath(unittest.TestCase):
    """runner 组合数学：首两次调仓的现金/份额/净值全部手工核算（成本 0）。"""

    def test_first_two_rebalances_hand_computed(self):
        loader = TestLoader(market=scenario_a_market(),
                            index=make_index(DATES),
                            names={"A": "股票A", "B": "股票B"})
        as_of_log = []

        def fake(strategy, as_of=None, loader=None):
            as_of_log.append(as_of)
            return stub_result(["A", "B"], as_of)

        with mock.patch("quant.backtest.runner.run_strategy", side_effect=fake):
            res = run_backtest(StrategyA(use_stock_list=False),
                               D0, LAST, top_n=2, rebalance_every=1,
                               cost_rate=0.0, loader=loader)

        nav = res.nav.set_index("trade_date")["nav"]
        # d0：全现金，净值 1
        self.assertAlmostEqual(nav[DATES[0]], 1.0)
        # d1：A 45454 股 @11（499,994）+ B 24390 股 @20.5（499,995）+ 现金 11
        self.assertAlmostEqual(nav[DATES[1]], 0.942351)
        # d2~d3：等权再平衡后组合不变（收盘价同执行价）
        self.assertAlmostEqual(nav[DATES[2]], 0.942351)
        self.assertAlmostEqual(nav[DATES[3]], 0.942351)

        trades = res.trades
        first_day = trades[trades["exec_date"] == DATES[1]]
        self.assertEqual(len(first_day), 2)
        a = first_day[first_day["ts_code"] == "A"].iloc[0]
        b = first_day[first_day["ts_code"] == "B"].iloc[0]
        self.assertEqual((a["price"], a["shares"]), (11.0, 45454.0))
        self.assertEqual((b["price"], b["shares"]), (20.5, 24390.0))
        self.assertEqual(a["name"], "股票A")          # 名称映射

        rb = res.rebalances
        self.assertEqual(len(rb), 9)                   # 最后一日无次日 → 跳过
        first = rb.iloc[0]
        self.assertEqual(first["exec_date"], DATES[1])
        self.assertEqual((first["buys"], first["sells"]), (2, 0))
        self.assertAlmostEqual(first["cash"], 11.0)
        self.assertAlmostEqual(first["equity"], 1_000_000.0)   # 成本 0 → 权益不缩水
        second = rb.iloc[1]
        # rebalance_every=1 → 第二次调仓在 DATES[1] 计划、DATES[2] 执行
        self.assertEqual(second["exec_date"], DATES[2])
        self.assertEqual((second["buys"], second["sells"]), (1, 1))   # A 增、B 减
        self.assertAlmostEqual(second["equity"], 942_351.0)

        # 基准：d1 = 3030/3000 = 1.01
        bench = res.nav.set_index("trade_date")["benchmark"]
        self.assertAlmostEqual(bench[DATES[1]], 1.01)

        # 指标一致性：累计 = 末净值 − 1（期初 1）；胜率（所有期收益 ≤ 0）为 0
        self.assertAlmostEqual(res.metrics["portfolio"]["cumulative_return"],
                               nav[LAST] - 1.0)
        self.assertEqual(res.metrics["win_rate"], 0.0)
        self.assertEqual(res.metrics["trading_days"], 10)
        # 参数快照与数据版本（可复现性）
        self.assertEqual(res.params["top_n"], 2)
        self.assertEqual(res.params["cost_rate"], 0.0)
        self.assertIn("data_version", vars(res))


class TestSuspension(unittest.TestCase):
    """持仓停牌：执行日停牌卖出跳过（继续持有）、按最后可用价 ffill 估值、
    因卖出被跳过导致的现金不足买入未成交如实记录。"""

    def _market(self):
        rows = []
        for i, d in enumerate(DATES):
            rows.append({"ts_code": "A", "trade_date": d,
                         "close_adj": 10.0, "open_adj": 10.0, "vol": 1000.0})
            if i < 4:   # S 停牌于 DATES[4] 起（无行情行）
                rows.append({"ts_code": "S", "trade_date": d,
                             "close_adj": 5.0, "open_adj": 5.0, "vol": 1000.0})
        return pd.DataFrame(rows)

    def test_suspended_holding_ffill_never_sold(self):
        # 排名序列：先买 A → 换入 S → S 停牌期间排名转回 A（S 卖不出、A 没钱买）
        targets = [["A"], ["S"], ["S"]] + [["A"]] * 7

        def fake(strategy, as_of=None, loader=None):
            return stub_result(targets.pop(0), as_of)

        with mock.patch("quant.backtest.runner.run_strategy", side_effect=fake):
            res = run_backtest(StrategyA(use_stock_list=False),
                               D0, LAST, top_n=1, rebalance_every=1,
                               cost_rate=0.0,
                               loader=TestLoader(market=self._market(),
                                                 index=make_index(DATES)))

        trades = res.trades
        nav = res.nav.set_index("trade_date")["nav"]

        # 1) S 买入于 DATES[2]（0104），之后从未被卖出（停牌无法卖）
        s_buy = trades[(trades["ts_code"] == "S") & (trades["action"] == "buy")]
        self.assertEqual(len(s_buy), 1)
        self.assertEqual(s_buy.iloc[0]["exec_date"], DATES[2])
        self.assertFalse(((trades["ts_code"] == "S") & (trades["action"] == "sell")).any())

        # 2) 停牌后按最后价 5 ffill 估值：现金 0 + 200,000 股 × 5 = 1,000,000
        self.assertAlmostEqual(nav[DATES[5]], 1.0)
        self.assertAlmostEqual(nav[LAST], 1.0)

        # 3) 调仓记录：执行日 DATES[4]（0108）卖出被跳过、买入未成交
        row = res.rebalances[res.rebalances["exec_date"] == DATES[4]].iloc[0]
        self.assertEqual(row["sell_skipped"], 1)
        self.assertEqual(row["buys"], 0)
        self.assertTrue(any("卖出跳过（继续持有）" in w for w in res.warnings))
        self.assertTrue(any("现金不足" in w for w in res.warnings))


class TestFutureStock(unittest.TestCase):
    """未来才有数据的股票：排名即使选中，也绝不提前成交；首个行情日才可买入。"""

    def _market(self):
        rows = []
        for i, d in enumerate(DATES):
            rows.append({"ts_code": "A", "trade_date": d,
                         "close_adj": 10.0, "open_adj": 10.0, "vol": 1000.0})
            if i >= 6:  # F 自 DATES[6]（0110）才上市
                rows.append({"ts_code": "F", "trade_date": d,
                             "close_adj": 8.0, "open_adj": 8.0, "vol": 1000.0})
        return pd.DataFrame(rows)

    def test_future_stock_never_trades_before_its_first_data_date(self):
        targets = [["A"]] + [["F"]] * 9

        def fake(strategy, as_of=None, loader=None):
            return stub_result(targets.pop(0), as_of)

        with mock.patch("quant.backtest.runner.run_strategy", side_effect=fake):
            res = run_backtest(StrategyA(use_stock_list=False),
                               D0, LAST, top_n=1, rebalance_every=1,
                               cost_rate=0.0,
                               loader=TestLoader(market=self._market(),
                                                 index=make_index(DATES)))

        trades = res.trades
        f_trades = trades[trades["ts_code"] == "F"]
        # F 首个行情日 DATES[6] 才能成交；此前全部被"买入跳过"拦下
        self.assertFalse(f_trades.empty)
        self.assertTrue((f_trades["exec_date"] >= DATES[6]).all())
        self.assertEqual(f_trades.iloc[0]["exec_date"], DATES[6])
        self.assertEqual(f_trades.iloc[0]["shares"], 125_000.0)   # floor(1,000,000/8)
        # 买入跳过期间现金保留：净值恒 1.0
        nav = res.nav.set_index("trade_date")["nav"]
        self.assertAlmostEqual(nav[DATES[5]], 1.0)
        self.assertTrue(any("买入跳过（现金保留）" in w for w in res.warnings))


class TestCosts(unittest.TestCase):
    """交易成本：单边 0.1% 的现金/份额/净值手工核算。"""

    def test_cost_applied_both_sides(self):
        def close(code, i):
            return 10.0 if code == "A" else 20.0

        def open_(code, i):
            if i == 1 and code == "A":
                return 11.0
            return close(code, i)

        market = make_rows(["A", "B"], DATES, close, open_)
        targets = [["A"], ["B"]] + [["B"]] * 8

        def fake(strategy, as_of=None, loader=None):
            return stub_result(targets.pop(0), as_of)

        with mock.patch("quant.backtest.runner.run_strategy", side_effect=fake):
            res = run_backtest(StrategyA(use_stock_list=False),
                               D0, LAST, top_n=1, rebalance_every=1,
                               cost_rate=0.001,
                               loader=TestLoader(market=market, index=make_index(DATES)))

        trades = res.trades
        buy_a = trades[(trades["ts_code"] == "A") & (trades["action"] == "buy")].iloc[0]
        # 目标份额 floor(1e6/11) = 90,909；可支付份额 floor(1e6/(11×1.001)) = 90,818 → 取小
        self.assertEqual(buy_a["shares"], 90_818.0)
        self.assertAlmostEqual(buy_a["cost"], 998_998.0 * 0.001, places=9)

        # d1 净值：现金 3.002 + 90,818 股 × 收盘 10 = 908,183.002
        nav = res.nav.set_index("trade_date")["nav"]
        self.assertAlmostEqual(nav[DATES[1]], 0.908183002, places=9)

        sell_a = trades[(trades["ts_code"] == "A") & (trades["action"] == "sell")].iloc[0]
        self.assertEqual(sell_a["shares"], 90_818.0)
        self.assertAlmostEqual(sell_a["cost"], 908_180.0 * 0.001, places=9)

        buy_b = trades[(trades["ts_code"] == "B") & (trades["action"] == "buy")].iloc[0]
        # 现金 = 3.002 + 908,180×0.999 = 907,274.822 → floor(907,274.822/(20×1.001)) = 45,318
        self.assertEqual(buy_b["shares"], 45_318.0)
        self.assertAlmostEqual(nav[DATES[2]], (45_318 * 20.0 + 8.462) / 1e6, places=6)

        # 首日执行后权益 = 1,000,000 − 买入成本 998.998（成本从权益中消失）
        self.assertAlmostEqual(res.rebalances.iloc[0]["equity"],
                               1_000_000.0 - 998.998, places=3)


class TestNoLookahead(unittest.TestCase):
    """无未来数据泄漏的专门断言（对 runner 全流程）。"""

    def test_trade_dates_strictly_after_rebalance_dates(self):
        loader = TestLoader(market=scenario_a_market(), index=make_index(DATES))
        as_of_log = []

        def fake(strategy, as_of=None, loader=None):
            as_of_log.append(as_of)
            return stub_result(["A", "B"], as_of)

        with mock.patch("quant.backtest.runner.run_strategy", side_effect=fake):
            res = run_backtest(StrategyA(use_stock_list=False),
                               D0, LAST, top_n=2, rebalance_every=1,
                               cost_rate=0.0, loader=loader)

        # 1) 每笔成交的执行日严格晚于其排名日（调仓日）
        self.assertFalse(res.trades.empty)
        for _, t in res.trades.iterrows():
            self.assertLess(t["rebalance_date"], t["exec_date"])
        # 2) 全部排名 as_of 都是回测区间内的交易日（无区间外/未来日期）
        self.assertEqual(as_of_log, DATES)
        # 3) 成交价只来自次一交易日开盘（A 首笔 = d1 开盘 11，而非收盘 10 或更晚）
        first_a = res.trades[res.trades["ts_code"] == "A"].iloc[0]
        self.assertEqual(first_a["exec_date"], DATES[1])
        self.assertEqual(first_a["price"], 11.0)


class TestIntegrationWithEngine(unittest.TestCase):
    """端到端：真实引擎（因子/标准化/排名）+ runner，PIT 股票池。

    三只股票 60 日：UP 每日 +1%、DOWN −1%、FLAT 0%——UP 动量恒最高，
    每次调仓都应选中 UP；DOWN/FLAT 永不成交。
    """

    @classmethod
    def setUpClass(cls):
        d60 = pd.bdate_range("2024-01-02", periods=60).strftime("%Y%m%d").tolist()
        rows = []
        for i, d in enumerate(d60):
            for code, growth in (("UP", 1.01), ("DOWN", 0.99), ("FLAT", 1.0)):
                rows.append({"ts_code": code, "trade_date": d,
                             "close_adj": growth ** i, "open_adj": growth ** i,
                             "vol": 1000.0})
        cls.loader = TestLoader(
            market=pd.DataFrame(rows),
            index=pd.DataFrame({"trade_date": d60,
                                "close": 3000.0 * 1.0005 ** np.arange(60)}),
            names={"UP": "涨", "DOWN": "跌", "FLAT": "平"})
        cls.dates = d60

    def test_top_stock_selected_and_no_lookahead(self):
        strategy = StrategyA(
            use_stock_list=False,
            windows={"momentum": (5,), "volatility": (5,),
                     "volume_trend": (2, 5), "relative_strength": (5,)})
        res = run_backtest(strategy, self.dates[0], self.dates[-1],
                           top_n=1, rebalance_every=5, cost_rate=0.0,
                           loader=self.loader)

        trades = res.trades
        self.assertFalse(trades.empty)
        # 只成交过 UP（动量最高者），DOWN/FLAT 从未进入组合
        self.assertEqual(set(trades["ts_code"]), {"UP"})
        # 首笔成交 = 首个可计算排名的调仓日（第 5 个交易日）的次一交易日
        self.assertEqual(trades.iloc[0]["exec_date"], self.dates[6])
        # 成交价 = 次一交易日开盘价（= 当日收盘，UP 第 6 日 = 1.01^6）
        self.assertAlmostEqual(trades.iloc[0]["price"], 1.01 ** 6)
        # 早期的"股票池为空"警告如实记录
        self.assertTrue(any("股票池为空" in w for w in res.warnings))
        # 参数快照标记 PIT 口径
        self.assertFalse(res.params["use_stock_list"])
        self.assertIn("PIT", res.params["universe"])


class TestValidation(unittest.TestCase):
    def test_invalid_ranges(self):
        loader = TestLoader(market=scenario_a_market())
        with self.assertRaises(ValueError):
            run_backtest(StrategyA(use_stock_list=False), D1, D0, loader=loader)
        with self.assertRaises(ValueError):
            run_backtest(StrategyA(use_stock_list=False), D0, LAST, top_n=0, loader=loader)
        with self.assertRaises(ValueError):
            run_backtest(StrategyA(use_stock_list=False), D0, LAST,
                         cost_rate=-0.1, loader=loader)

    def test_empty_market_raises(self):
        loader = TestLoader(market=pd.DataFrame(columns=["ts_code", "trade_date",
                                                        "close_adj", "open_adj", "vol"]))
        with self.assertRaises(ValueError):
            run_backtest(StrategyA(use_stock_list=False), D0, LAST, loader=loader)


if __name__ == "__main__":
    unittest.main()
