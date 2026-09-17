#!/usr/bin/env python3
"""用 raw 日线 + 复权因子重建前复权数据（不下载任何数据）。

适用场景：因子数据修复/回补后刷新 market_data_adj.parquet。
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402

from data.paths import RAW_FILE, FCT_FILE, ADJ_FILE  # noqa: E402
from data.adj_data import build_forward_adjusted  # noqa: E402
from data.storage import atomic_save  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def main():
    print("读取 raw 与因子数据...", flush=True)
    raw = pd.read_parquet(RAW_FILE)
    fct = pd.read_parquet(FCT_FILE)
    print(f"raw {len(raw):,} 行，factor {len(fct):,} 行", flush=True)

    print("构建前复权数据...", flush=True)
    df = build_forward_adjusted(raw, fct)
    atomic_save(df, ADJ_FILE)
    latest = df["trade_date"].max()
    print(f"✅ 完成：{len(df):,} 行，最新交易日 {latest}，已保存至 {ADJ_FILE}")


if __name__ == "__main__":
    main()
