"""Strategy F（Trend 趋势）：均线关系 baseline。

定义：MA20 / MA60 − 1 越高越好（20 日均线位于 60 日均线上方 → 上升趋势）。
- 经典、可解释的趋势基准：短均线在长均线上方且价差为正；不引入复杂技术指标
- 均线用前复权收盘价；比值为口径（最新复权因子在比值中抵消），无未来数据泄漏，
  见 quant/factors/trend.py
- 默认窗口 20/60 日为合理基线（经典双均线组合），非最优参数；
  页面/回测可调窗口，本阶段不做参数寻优
"""

from quant.strategies.base import Strategy


class StrategyF(Strategy):
    name = "strategy_f"
    label = "Strategy F（Trend 趋势）"
    description = ("趋势 baseline：MA20/MA60 − 1 越高越好"
                   "（20 日均线位于 60 日均线上方表示上升趋势）。")
    factor_names = ("trend",)
    default_weights = {"trend": 1.0}
    default_windows = {"trend": (20, 60)}
