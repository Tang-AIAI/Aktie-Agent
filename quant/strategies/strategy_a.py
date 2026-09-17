"""Strategy A（baseline）：动量 + 波动率 + 量能趋势 + 相对沪深300 强度，四因子等权。

计算口径（详见各因子模块）：
- Momentum：60 日收益率（默认窗口可调）
- Volatility：20 日收益率标准差（越低越好，标准化后反转）
- Volume Trend：20 日 / 60 日均量比
- Relative Strength：个股 60 日收益率 − 沪深300 60 日收益率

注意：Strategy A 是 baseline 研究策略，未经过历史回测验证，
结果仅供量化研究参考，不构成投资建议或收益承诺。
"""

from quant.strategies.base import Strategy


class StrategyA(Strategy):
    name = "strategy_a"
    label = "Strategy A"
    description = ("四因子等权综合评分（baseline）：Momentum / Volatility / "
                   "Volume Trend / Relative Strength，未经历史回测验证。")
    factor_names = ("momentum", "volatility", "volume_trend", "relative_strength")
    default_weights = {"momentum": 0.25, "volatility": 0.25,
                       "volume_trend": 0.25, "relative_strength": 0.25}
    default_windows = {"momentum": (60,), "volatility": (20,),
                       "volume_trend": (20, 60), "relative_strength": (60,)}
