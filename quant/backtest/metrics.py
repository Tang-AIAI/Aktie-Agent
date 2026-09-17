"""回测指标：净值/收益序列上的纯函数，不依赖任何数据层，可直接单测。

口径约定（与回测结果展示一致）：
- 累计收益率 = 期末净值 / 期初净值 − 1（净值序列通常以 1.0 起始）；
- 年化收益率按 252 个交易日/年折算（国际惯例；A 股实际年交易日约 242~250，
  回测报告统一用 252 以保证口径一致）；
- 最大回撤 = max(1 − 净值 / 历史最高净值)，返回正数（如 0.25 表示 25%）；
- 胜率 = 调仓期收益 > 0 的期数占比（输入为各调仓期的收益序列，由 runner 生成）。
全部函数在输入为空/过短等无法定义时返回 NaN（最大回撤例外：过短返回 0.0）。
"""

import pandas as pd

PERIODS_PER_YEAR = 252   # 年化折算用的年交易日数（口径固定，勿随市场微调）


def _clean(series) -> pd.Series:
    """统一转 float64、丢弃 NaN，保持值序。"""
    s = pd.Series(series, dtype="float64")
    return s.dropna().reset_index(drop=True)


def cumulative_return(nav) -> float:
    """累计收益率：nav[-1] / nav[0] − 1。数据不足 2 个点或起点为 0 时返回 NaN。"""
    s = _clean(nav)
    if len(s) < 2 or s.iloc[0] == 0:
        return float("nan")
    return float(s.iloc[-1] / s.iloc[0] - 1.0)


def annualized_return(nav, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """年化收益率：(nav[-1]/nav[0]) ** (periods_per_year/(n−1)) − 1。

    n 为净值点数；数据不足 2 个点或首末值非正时返回 NaN。
    """
    s = _clean(nav)
    if len(s) < 2:
        return float("nan")
    first, last = s.iloc[0], s.iloc[-1]
    if first <= 0 or last <= 0:
        return float("nan")
    return float((last / first) ** (periods_per_year / (len(s) - 1)) - 1.0)


def max_drawdown(nav) -> float:
    """最大回撤（正数）：max(1 − 净值/历史最高净值)。数据不足 2 个点返回 0.0。"""
    s = _clean(nav)
    if len(s) < 2:
        return 0.0
    peak = s.cummax()
    return float((1.0 - s / peak).max())


def win_rate(period_returns) -> float:
    """胜率：收益 > 0 的期数占比。输入为空返回 NaN（避免把"无期数"显示成 0%）。"""
    s = _clean(period_returns)
    if len(s) == 0:
        return float("nan")
    return float((s > 0).mean())


def excess_return(nav, benchmark) -> float:
    """相对基准的超额收益 = 组合累计收益率 − 基准累计收益率。"""
    return cumulative_return(nav) - cumulative_return(benchmark)
