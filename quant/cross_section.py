"""横截面标准化：同一计算日、全股票池上，把不同量纲的因子换算为可比较的分值。

策略最终得分 = Σ(标准化因子 × 方向符号 × 权重)，其中方向符号把
"越低越好"（如波动率）的因子反转，保证所有因子方向统一为"分越高越好"。
"""

import pandas as pd

from quant.factors.base import HIGHER_BETTER, LOWER_BETTER


def zscore(series: pd.Series) -> pd.Series:
    """横截面 z-score：(x - mean) / std（总体标准差 ddof=0）。

    NaN 保持 NaN（数据不足的股票后续被排除）；std 为 0（全体同值）时返回全 0。
    """
    s = pd.Series(series, dtype="float64")
    mu = s.mean()
    sd = s.std(ddof=0)
    if pd.isna(sd) or sd == 0:
        return s * 0.0
    return (s - mu) / sd


def rank_score(series: pd.Series) -> pd.Series:
    """横截面百分位排名，映射到 [-1, 1]（2 × 百分位 - 1）。NaN 保持 NaN。"""
    r = pd.Series(series, dtype="float64").rank(pct=True)
    return 2.0 * r - 1.0


def standardize(series: pd.Series, method: str = "zscore") -> pd.Series:
    """按 method 做横截面标准化（zscore 或 rank），默认 zscore。"""
    if method == "zscore":
        return zscore(series)
    if method == "rank":
        return rank_score(series)
    raise ValueError(f"未知标准化方法: {method}（可选 zscore / rank）")


def direction_sign(direction: str) -> float:
    """因子方向 → 符号：越高越好 +1；越低越好 -1（标准化后相乘实现反转）。"""
    if direction == HIGHER_BETTER:
        return 1.0
    if direction == LOWER_BETTER:
        return -1.0
    raise ValueError(f"未知因子方向: {direction}")
