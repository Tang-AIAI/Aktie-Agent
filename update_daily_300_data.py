# 下载沪深300指数数据，先尝试tushare，没有权限的话就用akshare，并将数据进行统一规范（调用data_manager.py的核心程序）
import pandas as pd
import os
import time
from datetime import datetime
from data_manager import DataManager
import logging
from dotenv import load_dotenv

load_dotenv()

def update_index_data():
    """增量更新指数数据，继承用户风格"""
    file_path = "index_data.parquet"
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
    df_all.to_parquet(file_path, index=False)
    logging.info(f"更新完成，总记录数：{len(df_all)}，保存至 {file_path}")


if __name__ == "__main__":
    update_index_data()