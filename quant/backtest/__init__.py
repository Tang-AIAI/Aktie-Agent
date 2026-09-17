"""回测子系统：指标 → 持仓账本 → 主循环（Strategy A 历史回测 MVP）。

使用：runner.run_backtest(StrategyA(...), start, end, top_n=..., ...) → BacktestResult。
防未来数据泄漏的口径见 quant/backtest/runner.py 模块注释。
"""

from quant.backtest.metrics import (  # noqa: F401
    annualized_return,
    cumulative_return,
    excess_return,
    max_drawdown,
    win_rate,
)
from quant.backtest.portfolio import Portfolio, Trade  # noqa: F401
from quant.backtest.runner import BacktestResult, run_backtest  # noqa: F401
