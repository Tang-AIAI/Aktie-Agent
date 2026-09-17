"""quant/screener 单元测试：条件求值逻辑（合成指标表）与指标计算（FakeLoader）。

不依赖真实 parquet；求值语义（AND/OR/NOT/指标对比/NaN 排除/容差等）全覆盖。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from quant.screener import compute_indicators, evaluate, get_indicator

# 合成指标表：4 只股票
TABLE = pd.DataFrame({
    "close": [10.0, 25.0, 40.0, 55.0],
    "ma60": [12.0, 20.0, 45.0, 50.0],
    "ret60": [0.05, 0.15, -0.10, np.nan],
    "vol_ratio": [0.8, 1.2, 1.5, 0.9],
}, index=["A", "B", "C", "D"])


def c(left, op, right, negate=False, connector="AND"):
    return {"left": left, "op": op, "right": right, "negate": negate, "connector": connector}


class TestEvaluate(unittest.TestCase):
    def test_single_condition(self):
        """单条件：close > 20 → B/C/D。"""
        m = evaluate(TABLE, [c("close", ">", {"kind": "value", "value": 20})])
        self.assertTrue((m == pd.Series({"A": False, "B": True, "C": True, "D": True})).all())

    def test_and(self):
        """AND：close > 20 且 ret60 > 0 → 只有 B。"""
        m = evaluate(TABLE, [
            c("close", ">", {"kind": "value", "value": 20}),
            c("ret60", ">", {"kind": "value", "value": 0}),
        ])
        self.assertEqual(set(TABLE.index[m]), {"B"})

    def test_or(self):
        """OR：close > 50 或 ret60 < 0 → D（55）和 C（-0.10）。"""
        m = evaluate(TABLE, [
            c("close", ">", {"kind": "value", "value": 50}),
            c("ret60", "<", {"kind": "value", "value": 0}, connector="OR"),
        ])
        self.assertEqual(set(TABLE.index[m]), {"C", "D"})

    def test_left_to_right_no_precedence(self):
        """自左向右组合，无优先级：(close>50 OR ret60>0) AND vol_ratio<1。

        close>50={D}，ret60>0={A,B}，vol_ratio<1={A,D} → ({D}∪{A,B})∩{A,D} = {A,D}。
        """
        m = evaluate(TABLE, [
            c("close", ">", {"kind": "value", "value": 50}),          # D
            c("ret60", ">", {"kind": "value", "value": 0}, connector="OR"),   # A、B
            c("vol_ratio", "<", {"kind": "value", "value": 1.0}),     # A、D
        ])
        self.assertEqual(set(TABLE.index[m]), {"A", "D"})

    def test_not(self):
        """NOT 取反：NOT (close > 20) → A。"""
        m = evaluate(TABLE, [c("close", ">", {"kind": "value", "value": 20}, negate=True)])
        self.assertEqual(set(TABLE.index[m]), {"A"})

    def test_nan_excluded_even_with_not(self):
        """指标为 NaN 时比较保持 NA，NOT 也不放行（避免数据不足股票混入）。

        NOT(ret60>0)：ret60≤0 的 C 通过；A(0.05)、B(0.15) 被排除；D(NaN) 不放行。
        """
        m = evaluate(TABLE, [c("ret60", ">", {"kind": "value", "value": 0}, negate=True)])
        self.assertNotIn("D", set(TABLE.index[m]))
        self.assertEqual(set(TABLE.index[m]), {"C"})

    def test_indicator_vs_indicator(self):
        """指标与指标比较：close > ma60 → B（25>20）、D（55>50）。"""
        m = evaluate(TABLE, [c("close", ">", {"kind": "indicator", "name": "ma60"})])
        self.assertEqual(set(TABLE.index[m]), {"B", "D"})

    def test_all_operators(self):
        """六个运算符逐一验证（= / != 用 1e-9 相对容差）。"""
        self.assertEqual(set(TABLE.index[evaluate(
            TABLE, [c("close", ">=", {"kind": "value", "value": 25.0})])]), {"B", "C", "D"})
        self.assertEqual(set(TABLE.index[evaluate(
            TABLE, [c("close", "<", {"kind": "value", "value": 25.0})])]), {"A"})
        self.assertEqual(set(TABLE.index[evaluate(
            TABLE, [c("close", "<=", {"kind": "value", "value": 25.0})])]), {"A", "B"})
        self.assertEqual(set(TABLE.index[evaluate(
            TABLE, [c("close", "=", {"kind": "value", "value": 25.0})])]), {"B"})
        self.assertEqual(set(TABLE.index[evaluate(
            TABLE, [c("close", "=", {"kind": "value", "value": 25.0 + 1e-11})])]), {"B"})
        self.assertEqual(set(TABLE.index[evaluate(
            TABLE, [c("close", "!=", {"kind": "value", "value": 25.0})])]), {"A", "C", "D"})

    def test_no_results(self):
        m = evaluate(TABLE, [c("close", ">", {"kind": "value", "value": 1e6})])
        self.assertFalse(m.any())

    def test_all_results(self):
        m = evaluate(TABLE, [c("close", ">", {"kind": "value", "value": 0})])
        self.assertTrue(m.all())

    def test_empty_conditions_raises(self):
        with self.assertRaises(ValueError):
            evaluate(TABLE, [])

    def test_unknown_operator_raises(self):
        with self.assertRaises(ValueError):
            evaluate(TABLE, [c("close", "≈", {"kind": "value", "value": 1})])

    def test_unknown_left_raises(self):
        with self.assertRaises(ValueError):
            evaluate(TABLE, [c("nope", ">", {"kind": "value", "value": 1})])

    def test_unknown_connector_raises(self):
        with self.assertRaises(ValueError):
            evaluate(TABLE, [c("close", ">", {"kind": "value", "value": 1}),
                             c("close", ">", {"kind": "value", "value": 1}, connector="XOR")])


# ------------------------------------------------------------------ 指标计算（FakeLoader）
N_DAYS = 130
END = "20260915"


class FakeLoader:
    def __init__(self, market, index, names):
        self.market, self.index, self.names = market, index, names

    def load_market_data(self, start, end, columns=("ts_code", "trade_date", "close_adj", "vol")):
        mask = (self.market["trade_date"] >= start) & (self.market["trade_date"] <= end)
        return self.market.loc[mask, list(columns)].copy()

    def load_index(self, start, end):
        mask = (self.index["trade_date"] >= start) & (self.index["trade_date"] <= end)
        return self.index.loc[mask].copy()

    def latest_trade_date(self):
        return END

    def stock_names(self):
        return self.names


def build_market():
    dates = pd.bdate_range(end="2026-09-15", periods=N_DAYS).strftime("%Y%m%d")
    rows = []
    for i, code in enumerate(["600000.SH", "600001.SH", "600002.SH"]):
        n = N_DAYS if code != "600001.SH" else N_DAYS - 1   # 600001：提前一天停牌
        closes = np.linspace(10 + i, 20 + i * 2, n)         # 线性价格：MA 可手算
        for t in range(n):
            rows.append((code, dates[t], closes[t] * 1.5, closes[t], 1000.0 + t))
    market = pd.DataFrame(rows, columns=["ts_code", "trade_date", "close", "close_adj", "vol"])
    index = pd.DataFrame({"trade_date": dates, "close": np.linspace(3000, 3300, N_DAYS)})
    names = {"600000.SH": "股票A", "600001.SH": "股票B", "600002.SH": "股票C"}
    return FakeLoader(market, index, names)


class TestComputeIndicators(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = build_market()

    def test_table_shape_and_universe(self):
        """股票池 = 有当日行情 ∩ stock_list；600001（停牌）被排除。"""
        res = compute_indicators(loader=self.loader, indicators=("close", "ma5", "ret60"))
        self.assertEqual(res.as_of, END)
        self.assertEqual(list(res.table.index), ["600000.SH", "600002.SH"])
        self.assertIn("close_raw", res.table.columns)
        self.assertIn("name", res.table.columns)

    def test_ma_hand_computed(self):
        """线性价格下 MA5 = 最近 5 日均值，可手算验证。"""
        res = compute_indicators(loader=self.loader, indicators=("ma5",))
        for code in ["600000.SH", "600002.SH"]:
            sub = self.loader.market[self.loader.market["ts_code"] == code].sort_values("trade_date")
            want = sub["close_adj"].tail(5).mean()
            self.assertAlmostEqual(res.table.loc[code, "ma5"], want, places=10)

    def test_close_raw_vs_adj(self):
        """close（指标，前复权）与 close_raw（原始价）按 1.5 倍区分（raw = adj × 1.5）。"""
        res = compute_indicators(loader=self.loader, indicators=("close",))
        for code in res.table.index:
            self.assertAlmostEqual(res.table.loc[code, "close_raw"] / 1.5,
                                   res.table.loc[code, "close"], places=10)

    def test_ret60_matches_momentum(self):
        """ret60 与 quant.factors.momentum 同口径。"""
        from quant.factors import momentum
        res = compute_indicators(loader=self.loader, indicators=("ret60",))
        market = self.loader.load_market_data("20200101", END,
                                              columns=("ts_code", "trade_date", "close_adj", "vol"))
        want = momentum.compute(market, (60,))
        for code in res.table.index:
            self.assertAlmostEqual(res.table.loc[code, "ret60"], want[code], places=10)

    def test_rs_hs300_raw_value(self):
        """rs_hs300 = 个股60日收益 − 指数60日收益（原始值）。"""
        res = compute_indicators(loader=self.loader, indicators=("ret60", "rs_hs300"))
        idx = self.loader.load_index("20200101", END).sort_values("trade_date")
        idx_ret = idx["close"].iloc[-1] / idx["close"].shift(60).iloc[-1] - 1
        for code in res.table.index:
            self.assertAlmostEqual(res.table.loc[code, "rs_hs300"],
                                   res.table.loc[code, "ret60"] - idx_ret, places=10)

    def test_unknown_indicator_raises(self):
        with self.assertRaises(KeyError):
            compute_indicators(loader=self.loader, indicators=("magic",))

    def test_all_registered_indicators_compute(self):
        """全部 12 个注册指标都能在合成数据上计算（不抛异常）。"""
        from quant.screener import INDICATORS
        res = compute_indicators(loader=self.loader, indicators=tuple(INDICATORS))
        self.assertEqual(len(res.table), 2)


if __name__ == "__main__":
    unittest.main()
