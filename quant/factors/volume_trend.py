"""Volume Trend 因子：近短窗口平均成交量 / 近长窗口平均成交量，越高越好。"""

import pandas as pd

from quant.factors.base import HIGHER_BETTER, Factor
from quant.factors.registry import register


def _check_windows(windows: tuple) -> None:
    if windows[0] >= windows[1]:
        raise ValueError(f"Volume Trend 短期窗口必须小于长期窗口，收到 {windows}")


def compute(market: pd.DataFrame, windows: tuple, *, index=None, as_of=None) -> pd.Series:
    short, long = windows
    df = market.sort_values(["ts_code", "trade_date"])
    code = df["ts_code"]
    avg_short = df.groupby("ts_code", sort=False)["vol"].transform(
        lambda s: s.rolling(short, min_periods=short).mean())
    avg_long = df.groupby("ts_code", sort=False)["vol"].transform(
        lambda s: s.rolling(long, min_periods=long).mean())
    ratio = avg_short / avg_long
    return ratio.groupby(code).last()


FACTOR = Factor(
    name="volume_trend",
    label="Volume Trend（量能趋势）",
    short_label="量能趋势",
    direction=HIGHER_BETTER,
    default_windows=(20, 60),
    description="近短窗口平均成交量 ÷ 近长窗口平均成交量（默认 20 日 / 60 日），越高越好。",
    validate_windows=_check_windows,
)

register(FACTOR, compute)
