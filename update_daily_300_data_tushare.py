import tushare as ts
import pandas as pd
from datetime import datetime
import os
import time

ts.set_token("28456e0dd968c6a7ba5f6d1c45eb2d8304cc465f5750ff7e077b7074")
pro = ts.pro_api()

index_parquet_file = "index_data.parquet"
INDEX_CODE = "000300.SH"

# -----------------------------
# 1. 确定需要下载的日期范围
# -----------------------------
if os.path.exists(index_parquet_file):
    df_existing = pd.read_parquet(index_parquet_file)
    df_existing['trade_date'] = df_existing['trade_date'].astype(str)
    existing_dates = set(df_existing['trade_date'].unique())
    earliest_date = df_existing['trade_date'].min()
    earliest_year = int(earliest_date[:4])
    target_year = earliest_year - 1
    print(f"当前最早指数日期: {earliest_date}")
    print(f"向前补数据: {target_year}年")
    start_dt = datetime(target_year, 1, 1)
    end_dt   = datetime(target_year, 12, 31)
    all_dates = pd.date_range(start_dt, end_dt).strftime("%Y%m%d").tolist()
    dates_to_download = [d for d in all_dates if d not in existing_dates]
else:
    print("index_data.parquet 不存在，进行首次全量下载（例如从2015年至今）")
    existing_dates = set()
    start_dt = datetime(2015, 1, 1)   # 你可以改成 2010 或更早
    end_dt = datetime.today()
    all_dates = pd.date_range(start_dt, end_dt).strftime("%Y%m%d").tolist()
    dates_to_download = all_dates
    # 创建一个空的 df_existing 便于后续合并
    df_existing = pd.DataFrame()

print(f"需要下载 {len(dates_to_download)} 天")

# -----------------------------
# 2. 下载指数日线数据
# -----------------------------
all_data = []
failed_dates = []

for i, date in enumerate(dates_to_download):
    try:
        # 注意接口是 index_daily，不是 daily
        df = pro.index_daily(ts_code=INDEX_CODE, trade_date=date, retry_count=3, timeout=60)
        if df.empty:
            print(f"[{i+1}] {date} 空数据")
        else:
            all_data.append(df)
            print(f"[{i+1}] {date} OK")
        time.sleep(0.1)
    except Exception as e:
        print(f"[{i+1}] {date} 失败: {e}")
        failed_dates.append(date)

# -----------------------------
# 3. 合并 + 去重 + 保存（完全模仿你的个股逻辑）
# -----------------------------
if all_data:
    df_new = pd.concat(all_data, ignore_index=True)

    if not df_existing.empty:
        df_all = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_all = df_new

    # 去重：指数没有 ts_code 多样，但为了一致性，也用 ts_code + trade_date
    # 注意 index_daily 返回的字段中代码列叫 ts_code
    df_all = df_all.drop_duplicates(subset=["ts_code", "trade_date"])

    # 可选：排序，让你的数据更整洁
    df_all = df_all.sort_values(["ts_code", "trade_date"])

    df_all.to_parquet(index_parquet_file, index=False)
    print(f"更新完成，总指数数据条数：{len(df_all)}")
else:
    print("没有新增指数数据")

print("失败日期：", failed_dates)