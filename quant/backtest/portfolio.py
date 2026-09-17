"""回测持仓账本：现金 + 持仓 + 交易成本 + 停牌估值。

口径：
- 交易成本按"单边费率"计：买入多付 cost_rate×成交额，卖出少收 cost_rate×成交额；
- 停牌/无价格时由调用方保证"不成交"（本类对无价格估值自动用最后可用价 ffill）；
- 买入受现金约束（自动缩减到可支付份额），卖出受持仓约束；
- 份额向下取整为整数股（A 股 100 股整手规则 MVP 不模拟，舍入误差 ≤ 1 股/次）。
"""

import math
from dataclasses import dataclass


@dataclass
class Trade:
    """单笔成交记录。cost 为该笔交易成本金额，value 为成交金额（不含成本）。"""
    date: str
    ts_code: str
    action: str      # "buy" / "sell"
    shares: float
    price: float
    cost: float
    value: float


class Portfolio:
    def __init__(self, cash: float = 1_000_000.0, cost_rate: float = 0.0):
        self.initial_cash = float(cash)
        self.cash = float(cash)
        self.cost_rate = float(cost_rate)
        self.holdings: dict = {}       # ts_code -> 份额
        self.last_prices: dict = {}    # ts_code -> 最近可用价格（估值 ffill 用）
        self.trades: list = []         # list[Trade]

    def mark(self, prices: dict) -> None:
        """更新最近可用价格：只接受正的有限价格（停牌日无价格 → 保持上次值）。"""
        for code, px in prices.items():
            if px is not None and not (isinstance(px, float) and math.isnan(px)) and px > 0:
                self.last_prices[code] = float(px)

    def value(self) -> float:
        """当前权益 = 现金 + Σ 持仓份额 × 最近可用价格。"""
        total = self.cash
        for code, shares in self.holdings.items():
            px = self.last_prices.get(code)
            if px is None:
                raise ValueError(f"持仓 {code} 无可用价格，无法估值（应在买入时记录价格）")
            total += shares * px
        return total

    def buy(self, date: str, code: str, price: float, shares: float) -> Trade | None:
        """按 price 买入 shares 股（向下取整为整数股）；现金不足时自动缩减到可支付份额。"""
        shares = math.floor(float(shares))
        price = float(price)
        if shares <= 0 or price <= 0 or math.isnan(price):
            return None
        # 现金约束：成本 = 成交额 + 成交额×费率
        affordable = self.cash / (price * (1.0 + self.cost_rate))
        shares = min(shares, math.floor(affordable))
        if shares <= 0:
            return None
        value = shares * price
        cost = value * self.cost_rate
        self.cash -= value + cost
        self.holdings[code] = self.holdings.get(code, 0.0) + shares
        self.last_prices[code] = price
        trade = Trade(date=date, ts_code=code, action="buy",
                      shares=shares, price=price, cost=cost, value=value)
        self.trades.append(trade)
        return trade

    def sell(self, date: str, code: str, price: float, shares: float) -> Trade | None:
        """按 price 卖出 shares 股（向下取整为整数股，受持仓约束）；无持仓或价格无效返回 None。"""
        held = self.holdings.get(code, 0.0)
        shares = min(math.floor(float(shares)), held)
        price = float(price)
        if shares <= 0 or price <= 0 or math.isnan(price):
            return None
        value = shares * price
        cost = value * self.cost_rate
        self.cash += value - cost
        self.holdings[code] = held - shares
        if self.holdings[code] <= 0:
            self.holdings.pop(code)
        self.last_prices[code] = price
        trade = Trade(date=date, ts_code=code, action="sell",
                      shares=shares, price=price, cost=cost, value=value)
        self.trades.append(trade)
        return trade
