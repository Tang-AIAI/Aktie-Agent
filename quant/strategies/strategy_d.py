"""Strategy D（Reversal 反转）：短期收益反转 baseline。

定义：5 日收益率越低越好（近期跌幅越大的股票反转评分越高）。
- 因子复用 momentum 的计算函数（同一 W 日收益口径），仅方向相反，见
  quant/factors/short_term_reversal.py
- 默认窗口 5 日为合理基线（经典短期反转窗口 5~20 日），非最优参数；
  页面/回测可调窗口，本阶段不做参数寻优
- 只依赖行情数据（前复权价），无未来数据泄漏（口径同 momentum）
"""

from quant.strategies.base import Strategy


class StrategyD(Strategy):
    name = "strategy_d"
    label = "Strategy D（Reversal 反转）"
    description = ("短期反转 baseline：近 5 个交易日收益率越低越好"
                   "（超跌反弹，与 momentum 同口径反向）。")
    factor_names = ("short_term_reversal",)
    default_weights = {"short_term_reversal": 1.0}
    default_windows = {"short_term_reversal": (5,)}
