"""Trend 因子：短窗口均线 / 长窗口均线 − 1，越高越好。

经典趋势定义（前复权收盘价）：
- 值 > 0：短均线在长均线上方（上升趋势）；< 0：下方（下降趋势）
- 默认窗口 20 / 60 日（MA20 与 MA60 的关系）

前复权口径说明：close_adj = 原价 × F_t/F_last，均线比值为
MA_short(原价×F_t) / MA_long(原价×F_t)，最新因子 F_last 在比值中抵消——
与"以当前最新因子重算历史价格"无关，不引入未来数据泄漏（与收益率因子同理）。
"""

import pandas as pd

from quant.factors.base import HIGHER_BETTER, Factor
from quant.factors.registry import register


def _check_windows(windows: tuple) -> None:
    if windows[0] >= windows[1]:
        raise ValueError(f"Trend 短期窗口必须小于长期窗口，收到 {windows}")


def compute(market: pd.DataFrame, windows: tuple, *, index=None, as_of=None) -> pd.Series:
    short, long = windows
    df = market.sort_values(["ts_code", "trade_date"])
    code = df["ts_code"]
    ma_short = df.groupby("ts_code", sort=False)["close_adj"].transform(
        lambda s: s.rolling(short, min_periods=short).mean())
    ma_long = df.groupby("ts_code", sort=False)["close_adj"].transform(
        lambda s: s.rolling(long, min_periods=long).mean())
    ratio = ma_short / ma_long - 1.0
    return ratio.groupby(code).last()


FACTOR = Factor(
    name="trend",
    label="趋势（短均线/长均线 − 1）",
    short_label="趋势",
    direction=HIGHER_BETTER,
    default_windows=(20, 60),
    description="短窗口均线 ÷ 长窗口均线 − 1（默认 MA20/MA60，前复权价），"
                "越高越好：短均线位于长均线上方表示上升趋势。",
    validate_windows=_check_windows,
)

register(FACTOR, compute)
