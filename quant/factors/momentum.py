"""Momentum 因子：近 W 个交易日收益率 = close_adj_T / close_adj_{T-W} - 1，越高越好。"""

import pandas as pd

from quant.factors.base import HIGHER_BETTER, Factor
from quant.factors.registry import register


def compute(market: pd.DataFrame, windows: tuple, *, index=None, as_of=None) -> pd.Series:
    w = windows[0]
    df = market.sort_values(["ts_code", "trade_date"])
    prev = df.groupby("ts_code", sort=False)["close_adj"].shift(w)
    ret = df["close_adj"] / prev - 1.0
    return ret.groupby(df["ts_code"], sort=False).last()


FACTOR = Factor(
    name="momentum",
    label="Momentum（动量）",
    short_label="动量",
    direction=HIGHER_BETTER,
    default_windows=(60,),
    description="近 W 个交易日收益率：最新前复权收盘价 / W 个交易日前前复权收盘价 - 1，越高越好。",
)

register(FACTOR, compute)
