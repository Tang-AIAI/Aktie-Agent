#!/usr/bin/env python3
"""数据完整性检查：用交易所交易日历比对各数据文件的缺失日期。

用法：python scripts/check_data.py
输出每个数据文件的最新交易日 + 缺失交易日列表（应为空）。
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402

from data.paths import RAW_FILE, FCT_FILE, ADJ_FILE, INDEX_FILE  # noqa: E402
from data.trade_calendar import missing_trade_dates  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def check(name: str, filepath: str, start: str):
    df = pd.read_parquet(filepath)
    latest = str(df["trade_date"].max())
    missing = missing_trade_dates(df["trade_date"], start, latest)
    print(f"{name}: {len(df):,} 行, 最新 {latest}, 缺失 {len(missing)} 天")
    if missing:
        print(f"    缺失: {missing}")
    return latest


def check_factor_staleness():
    """每股维度：因子最新日期落后于日线最新日期超过 1 天的活跃股票数。"""
    raw = pd.read_parquet(RAW_FILE)
    fct = pd.read_parquet(FCT_FILE)
    raw["trade_date"] = raw["trade_date"].astype(str)
    fct["trade_date"] = fct["trade_date"].astype(str)

    raw_latest = raw.groupby("ts_code")["trade_date"].max()
    fct_latest = fct.groupby("ts_code")["trade_date"].max()
    merged = pd.concat([raw_latest, fct_latest], axis=1, join="inner").astype(str)
    merged.columns = ["raw", "fct"]

    stale = merged[merged["raw"] > merged["fct"]]
    if stale.empty:
        print("因子每股覆盖: 全部最新 ✅")
        return
    old = stale[stale["fct"] <= "20260430"]
    print(f"因子每股覆盖: {len(stale)} 只股票的因子落后于日线"
          f"（其中 {len(old)} 只因子停留在 20260430 及之前）")
    for ts_code, row in stale.sort_values("fct").head(5).iterrows():
        print(f"    {ts_code}: 因子最新 {row['fct']}, 日线最新 {row['raw']}")


if __name__ == "__main__":
    print("=" * 60)
    print("数据完整性检查（以交易所日历为准）")
    print("=" * 60)
    check("个股日线   ", RAW_FILE, "19901219")
    check("复权因子   ", FCT_FILE, "19901219")
    check("前复权数据 ", ADJ_FILE, "19901219")
    check("沪深300   ", INDEX_FILE, "20020104")
    check_factor_staleness()
    # 因子来源分布
    fct = pd.read_parquet(FCT_FILE)
    if "source" in fct.columns:
        dist = fct["source"].fillna("tushare").value_counts()
        print("因子来源分布:")
        for src, n in dist.items():
            print(f"    {src}: {n:,}")
    else:
        print("因子来源分布: 无 source 列")
