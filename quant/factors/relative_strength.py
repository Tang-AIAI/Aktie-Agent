"""Relative Strength 因子：个股近 W 日收益率 - 沪深300 近 W 日收益率，越高越好。"""

import pandas as pd

from quant.factors.base import HIGHER_BETTER, Factor
from quant.factors.registry import register


def compute(market: pd.DataFrame, windows: tuple, *, index=None, as_of=None) -> pd.Series:
    w = windows[0]
    # 个股收益率（与 momentum 同口径）
    df = market.sort_values(["ts_code", "trade_date"])
    prev = df.groupby("ts_code", sort=False)["close_adj"].shift(w)
    stock_ret = (df["close_adj"] / prev - 1.0).groupby(df["ts_code"], sort=False).last()
    # 沪深300 收益率（指数不复权，直接用 close）
    if index is None or index.empty:
        raise ValueError("Relative Strength 需要沪深300 指数数据（index_data.parquet）")
    idx = index.sort_values("trade_date")
    if as_of is not None:
        idx = idx[idx["trade_date"] <= as_of]
    idx_ret = idx["close"].iloc[-1] / idx["close"].shift(w).iloc[-1] - 1.0
    return stock_ret - idx_ret


FACTOR = Factor(
    name="relative_strength",
    label="Relative Strength（相对强度）",
    short_label="相对强度",
    direction=HIGHER_BETTER,
    default_windows=(60,),
    description="个股近 W 日收益率 − 沪深300 近 W 日收益率（相对基准的超额收益），越高越好。",
    needs_index=True,
)

register(FACTOR, compute)
