"""data.adj_data 单元测试：前复权公式正确性（p_adj = p × F_current / F_last）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from data.adj_data import build_forward_adjusted


class TestBuildForwardAdjusted(unittest.TestCase):
    def test_simple_two_stocks(self):
        """正确公式：p_adj = p × 当日因子 / 最新因子。"""
        raw = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "open": 10, "high": 11,
             "low": 9, "close": 10, "vol": 100},
            {"ts_code": "A", "trade_date": "20260102", "open": 10, "high": 11,
             "low": 9, "close": 12, "vol": 100},
            {"ts_code": "B", "trade_date": "20260101", "open": 5, "high": 6,
             "low": 4, "close": 5, "vol": 50},
        ])
        fct = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "adj_factor": 1.0},
            {"ts_code": "A", "trade_date": "20260102", "adj_factor": 2.0},  # 除权，因子翻倍
            {"ts_code": "B", "trade_date": "20260101", "adj_factor": 2.0},
        ])
        df = build_forward_adjusted(raw, fct)

        a1 = df[(df["ts_code"] == "A") & (df["trade_date"] == "20260101")]
        # A 最新因子 2.0：10 × 1.0 / 2.0 = 5（历史价格按除权比例向下折算）
        self.assertAlmostEqual(a1["close_adj"].iloc[0], 5.0)
        a2 = df[(df["ts_code"] == "A") & (df["trade_date"] == "20260102")]
        # 12 × 2.0 / 2.0 = 12（最新一天复权价 = 原价）
        self.assertAlmostEqual(a2["close_adj"].iloc[0], 12.0)
        b1 = df[(df["ts_code"] == "B") & (df["trade_date"] == "20260101")]
        # 5 × 2.0 / 2.0 = 5
        self.assertAlmostEqual(b1["close_adj"].iloc[0], 5.0)

    def test_missing_factor_ffilled(self):
        """某日无因子记录时用前一日因子（ffill），不报错。"""
        raw = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "open": 1, "high": 1,
             "low": 1, "close": 10, "vol": 1},
            {"ts_code": "A", "trade_date": "20260102", "open": 1, "high": 1,
             "low": 1, "close": 20, "vol": 1},
        ])
        fct = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "adj_factor": 1.0},
        ])
        df = build_forward_adjusted(raw, fct)
        # 两天因子均为 1.0，最新=当日 → 价格不变
        self.assertAlmostEqual(df.iloc[0]["close_adj"], 10.0)
        self.assertAlmostEqual(df.iloc[1]["close_adj"], 20.0)

    def test_no_factor_at_all(self):
        """完全没有因子数据时退化为原价（fillna(1)）。"""
        raw = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "open": 1, "high": 1,
             "low": 1, "close": 7, "vol": 1},
        ])
        fct = pd.DataFrame([{"ts_code": "A", "trade_date": "20260101", "adj_factor": 1.0}])
        fct = fct.iloc[0:0]  # 空
        df = build_forward_adjusted(raw, fct)
        self.assertAlmostEqual(df.iloc[0]["close_adj"], 7.0)

    def test_source_column_dropped(self):
        """因子表的 source 列不进入复权结果表。"""
        raw = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "open": 1, "high": 1,
             "low": 1, "close": 10, "vol": 1},
        ])
        fct = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "adj_factor": 1.0, "source": "sina"},
        ])
        df = build_forward_adjusted(raw, fct)
        self.assertNotIn("source", df.columns)


if __name__ == "__main__":
    unittest.main()
