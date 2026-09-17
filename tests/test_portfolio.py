"""quant/backtest/portfolio 单元测试：账本数学（成本/现金约束/停牌估值/成交记录）。

全部为合成数据手工计算核对，不依赖真实 parquet。
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant.backtest.portfolio import Portfolio, Trade

D = "20240102"


class TestBuy(unittest.TestCase):
    def test_buy_math_with_cost(self):
        """买入 50 股 @10，费率 0.001：现金 −(500+0.5)，持仓 +50，成本 0.5。"""
        p = Portfolio(cash=1000.0, cost_rate=0.001)
        t = p.buy(D, "A", 10.0, 50)
        self.assertIsInstance(t, Trade)
        self.assertAlmostEqual(p.cash, 1000.0 - 500.0 - 0.5)
        self.assertEqual(p.holdings["A"], 50.0)
        self.assertAlmostEqual(t.cost, 0.5)
        self.assertAlmostEqual(t.value, 500.0)
        self.assertEqual(t.action, "buy")

    def test_buy_zero_cost_rate(self):
        """费率 0：现金恰减成交额。"""
        p = Portfolio(cash=100.0, cost_rate=0.0)
        p.buy(D, "A", 10.0, 10)
        self.assertEqual(p.cash, 0.0)

    def test_buy_clamped_by_cash(self):
        """现金不足：自动缩减到可支付整数份额（100/(10×1.001) → 9 股）。"""
        p = Portfolio(cash=100.0, cost_rate=0.001)
        t = p.buy(D, "A", 10.0, 100)   # 想要 100 股（需 1001），只有 100
        self.assertEqual(t.shares, 9.0)
        self.assertAlmostEqual(p.cash, 100.0 - 9 * 10.0 * 1.001)

    def test_buy_floor_to_int(self):
        """份额向下取整为整数股。"""
        p = Portfolio(cash=1000.0)
        t = p.buy(D, "A", 10.0, 50.9)
        self.assertEqual(t.shares, 50.0)

    def test_buy_no_trade(self):
        """非正份额 / 非正价格 / NaN 价格 → 不成交。"""
        p = Portfolio(cash=100.0)
        self.assertIsNone(p.buy(D, "A", 10.0, 0))
        self.assertIsNone(p.buy(D, "A", 10.0, -1))
        self.assertIsNone(p.buy(D, "A", 0.0, 10))
        self.assertIsNone(p.buy(D, "A", -10.0, 10))
        self.assertIsNone(p.buy(D, "A", float("nan"), 10))
        self.assertEqual(len(p.trades), 0)

    def test_buy_records_last_price(self):
        p = Portfolio(cash=100.0)
        p.buy(D, "A", 10.0, 5)
        self.assertEqual(p.last_prices["A"], 10.0)
        self.assertAlmostEqual(p.value(), 100.0)


class TestSell(unittest.TestCase):
    def test_sell_math_with_cost(self):
        """持有 50 股，卖 50 股 @12，费率 0.001：现金 +600×0.999，持仓清空。"""
        p = Portfolio(cash=1000.0, cost_rate=0.001)
        p.buy(D, "A", 10.0, 50)
        t = p.sell(D, "A", 12.0, 50)
        self.assertAlmostEqual(p.cash, 1000.0 - 500.5 + 600.0 * 0.999)
        self.assertNotIn("A", p.holdings)
        self.assertAlmostEqual(t.cost, 0.6)
        self.assertAlmostEqual(t.value, 600.0)
        self.assertEqual(t.action, "sell")

    def test_sell_clamped_by_holdings(self):
        """卖出超过持仓 → 只卖持有的部分。"""
        p = Portfolio(cash=1000.0)
        p.buy(D, "A", 10.0, 50)
        t = p.sell(D, "A", 12.0, 100)
        self.assertEqual(t.shares, 50.0)
        self.assertNotIn("A", p.holdings)

    def test_sell_nothing_held(self):
        p = Portfolio(cash=1000.0)
        self.assertIsNone(p.sell(D, "A", 12.0, 10))
        self.assertEqual(len(p.trades), 0)

    def test_partial_sell(self):
        p = Portfolio(cash=1000.0)
        p.buy(D, "A", 10.0, 50)
        p.sell(D, "A", 12.0, 20)
        self.assertEqual(p.holdings["A"], 30.0)


class TestValuation(unittest.TestCase):
    def test_mark_ffill(self):
        """停牌日无价格 → mark 不更新 → 估值沿用最后可用价。"""
        p = Portfolio(cash=100.0)
        p.buy(D, "A", 10.0, 10)          # 现金归零，持仓 10 股，权益 100
        p.mark({"A": 11.0})
        self.assertAlmostEqual(p.value(), 110.0)
        p.mark({})                        # 停牌：无价格
        self.assertAlmostEqual(p.value(), 110.0)   # ffill 到 11
        p.mark({"A": float("nan")})       # NaN 视同无价格
        self.assertAlmostEqual(p.value(), 110.0)
        p.mark({"A": 9.0})
        self.assertAlmostEqual(p.value(), 90.0)

    def test_value_includes_cash(self):
        p = Portfolio(cash=500.0)
        p.buy(D, "A", 10.0, 10)   # 花 100
        self.assertAlmostEqual(p.value(), 500.0)

    def test_trades_recorded_in_order(self):
        p = Portfolio(cash=1000.0)
        p.buy(D, "A", 10.0, 10)
        p.sell(D, "A", 11.0, 10)
        self.assertEqual([t.action for t in p.trades], ["buy", "sell"])
        self.assertEqual([t.date for t in p.trades], [D, D])


if __name__ == "__main__":
    unittest.main()
