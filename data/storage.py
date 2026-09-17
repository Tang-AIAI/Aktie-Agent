"""数据文件写入基础设施：原子保存 + 去重追加合并。"""

import os
import tempfile

import pandas as pd


def atomic_save(df: pd.DataFrame, filepath: str):
    """通过临时文件 + os.replace 原子写入，避免中断损坏数据。"""
    if df is None or df.empty:
        return
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".parquet", dir=os.path.dirname(filepath))
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, filepath)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def append_dedupe(new_df: pd.DataFrame, filepath: str,
                  key_cols=("ts_code", "trade_date"), keep="first"):
    """把 new_df 合并进 filepath（已存在则读旧数据），按 key_cols 去重后原子写回。

    :param keep: 重复键保留哪一方。默认 "first"（保留旧行，增量追加安全）；
                 "last" 用于需要新行覆盖旧行的场景（如 Tushare 官方数据
                 覆盖新浪合成因子）。
    """
    if new_df is None or new_df.empty:
        return
    new_df = new_df.copy()
    if "trade_date" in new_df.columns:
        new_df["trade_date"] = new_df["trade_date"].astype(str)
    if os.path.exists(filepath):
        old = pd.read_parquet(filepath)
        if "trade_date" in old.columns:
            old["trade_date"] = old["trade_date"].astype(str)
        combined = pd.concat([old, new_df], ignore_index=True)
        combined = combined.drop_duplicates(list(key_cols), keep=keep)
    else:
        combined = new_df
    combined = combined.sort_values(list(key_cols))
    atomic_save(combined, filepath)
