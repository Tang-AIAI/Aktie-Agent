"""Volatility 因子：近 W 个交易日日收益率标准差（样本标准差 ddof=1），越低越好。"""

import pandas as pd

from quant.factors.base import LOWER_BETTER, Factor
from quant.factors.registry import register


def compute(market: pd.DataFrame, windows: tuple, *, index=None, as_of=None) -> pd.Series:
    w = windows[0]
    df = market.sort_values(["ts_code", "trade_date"])
    code = df["ts_code"]
    rets = df.groupby("ts_code", sort=False)["close_adj"].pct_change(fill_method=None)
    vol = rets.groupby(code).transform(
        lambda s: s.rolling(w, min_periods=w).std(ddof=1))
    return vol.groupby(code).last()


FACTOR = Factor(
    name="volatility",
    label="Volatility（波动率）",
    short_label="波动率",
    direction=LOWER_BETTER,
    default_windows=(20,),
    description="近 W 个交易日日收益率（前复权收盘价日涨跌幅）的样本标准差，越低越好。",
)

register(FACTOR, compute)
