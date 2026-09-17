"""Strategy E（Low Volatility 低波动）：20 日收益率标准差越低越好。

- 直接复用 Strategy A 的 volatility 因子（quant/factors/volatility.py），
  口径完全一致（前复权收盘价日收益率、样本标准差 ddof=1、rolling(20)），
  不重复实现
- 默认窗口 20 日为合理基线（经典低波动窗口），非最优参数；
  页面/回测可调窗口，本阶段不做参数寻优
- 只依赖行情数据（前复权价），无未来数据泄漏（口径同 Strategy A）
"""

from quant.strategies.base import Strategy


class StrategyE(Strategy):
    name = "strategy_e"
    label = "Strategy E（Low Vol 低波动）"
    description = ("低波动 baseline：近 20 个交易日收益率标准差越低越好"
                   "（复用 Strategy A 的 volatility 因子，口径一致）。")
    factor_names = ("volatility",)
    default_weights = {"volatility": 1.0}
    default_windows = {"volatility": (20,)}
