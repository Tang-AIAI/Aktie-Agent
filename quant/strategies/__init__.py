"""策略包与策略注册表：新增策略在此注册即可被引擎/页面/回测统一使用。

已注册：
- strategy_a 多因子 baseline（可回测）
- strategy_b 价值（设计就绪，数据不足未实现，不可回测）
- strategy_c 质量（设计就绪，数据不足未实现，不可回测）
- strategy_d 短期反转（可回测）
- strategy_e 低波动（可回测）
- strategy_f 趋势（可回测）
"""

from quant.strategies.strategy_a import StrategyA  # noqa: F401
from quant.strategies.strategy_b import StrategyB  # noqa: F401
from quant.strategies.strategy_c import StrategyC  # noqa: F401
from quant.strategies.strategy_d import StrategyD  # noqa: F401
from quant.strategies.strategy_e import StrategyE  # noqa: F401
from quant.strategies.strategy_f import StrategyF  # noqa: F401

_STRATEGIES = {
    "strategy_a": StrategyA,
    "strategy_b": StrategyB,
    "strategy_c": StrategyC,
    "strategy_d": StrategyD,
    "strategy_e": StrategyE,
    "strategy_f": StrategyF,
}


def get_strategy(name: str):
    if name not in _STRATEGIES:
        raise KeyError(f"未注册的策略: {name}（已注册: {sorted(_STRATEGIES)}）")
    return _STRATEGIES[name]


def all_strategies() -> list:
    return list(_STRATEGIES.values())
