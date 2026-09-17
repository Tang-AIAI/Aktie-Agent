"""前复权数据构建：raw 日线 × 复权因子 → 前复权 OHLC。

公式（Tushare 官方口径，2026-09-15 经腾讯 qfq 基准验证）：
    前复权价 = 原价 × 当日因子 / 最新因子
即 p_adj = p × F_current / F_last（历史价格按因子比例缩放，除权日连续）。

注意：2026-08-14 起旧实现误用了反式公式 p × F_last/F_current（历史价格被
放大、除权日出现幻影跳空），已修正。
"""

import pandas as pd


def build_forward_adjusted(raw: pd.DataFrame, fct: pd.DataFrame) -> pd.DataFrame:
    raw = raw.copy()
    fct = fct.copy()
    raw["trade_date"] = raw["trade_date"].astype(str)
    fct["trade_date"] = fct["trade_date"].astype(str)

    df = pd.merge(raw, fct, on=["ts_code", "trade_date"], how="left")
    df = df.sort_values(["ts_code", "trade_date"])
    df["adj_factor"] = df.groupby("ts_code")["adj_factor"].ffill().fillna(1)
    last_factor = df.groupby("ts_code")["adj_factor"].transform("last")
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df[col + "_adj"] = df[col] * df["adj_factor"] / last_factor
    # 因子来源标记（tushare/sina）只保留在 adj_factor 表，不进入复权结果表
    df = df.drop(columns=["source"], errors="ignore")
    return df
