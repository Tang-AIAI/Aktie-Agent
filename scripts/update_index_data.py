#!/usr/bin/env python3
"""沪深300 指数数据增量更新（从 update_daily_300_data.py 迁移，逻辑未改动）。

Tushare 为主，无权限/失败时降级 AkShare；统一规范列名后合并去重保存。
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime

import pandas as pd
import logging
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from data.paths import INDEX_FILE  # noqa: E402
from data.index_data import DataManager  # noqa: E402
from data.storage import atomic_save  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

load_dotenv(BASE_DIR / ".env")

def update_index_data():
    """增量更新指数数据，继承用户风格"""
    file_path = INDEX_FILE
    INDEX_CODE = "000300.SH"

    # 初始化数据管理器，替换Tushare token
    dm = DataManager(tushare_token=os.getenv("TUSHARE_TOKEN"))

    # 1. 确定更新范围
    if os.path.exists(file_path):
        df_existing = pd.read_parquet(file_path)
        df_existing['trade_date'] = df_existing['trade_date'].astype(str)
        existing_dates = set(df_existing['trade_date'].unique())
        # 假设向前补一年，找到已有数据的最早日期
        earliest_existing = df_existing['trade_date'].min()
        target_year = int(earliest_existing[:4]) - 1
        # 设置目标范围，这里简化，可自行扩展
        start_date = f"{target_year}-01-01"
        end_date = datetime.today().strftime("%Y-%m-%d")
        is_new_file = False
    else:
        # 首次全量下载
        start_date = "2026-01-01"
        end_date = datetime.today().strftime("%Y-%m-%d")
        is_new_file = True

    # 2. 调用数据管理器获取数据
    logging.info(f"开始获取数据：{INDEX_CODE}，日期范围 {start_date} 到 {end_date}")
    df_new = dm.get_index_daily(INDEX_CODE, start_date, end_date)

    if df_new is None or df_new.empty:
        logging.error("未获取到任何数据，退出更新")
        return

    # 3. 合并去重保存
    if not is_new_file:
        df_all = pd.concat([df_existing, df_new], ignore_index=True)
        df_all = df_all.drop_duplicates(subset=["ts_code", "trade_date"])
    else:
        df_all = df_new

    df_all = df_all.sort_values(["ts_code", "trade_date"])
    atomic_save(df_all, file_path)
    logging.info(f"更新完成，总记录数：{len(df_all)}，保存至 {file_path}")


if __name__ == "__main__":
    update_index_data()
