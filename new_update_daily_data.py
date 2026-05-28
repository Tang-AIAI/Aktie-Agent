# 每日更新程序
#!/usr/bin/env python3
"""
Tushare 数据下载器（稳健版）
- 日线：逐日下载 + batch_append（全量重写，可接受）
- 复权因子：一次性批量请求 + 安全分页 + 高效追加更新
"""

import tushare as ts
import pandas as pd
import os
import time
import tempfile
from datetime import datetime, timedelta
from typing import List, Set
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TUSHARE_TOKEN")
RAW_FILE = "market_data_raw.parquet"
FCT_FILE = "adj_factor.parquet"
ADJ_FILE = "market_data_adj.parquet"
PROGRESS_FILE = "download_progress.txt"
FAILED_FILE = "failed_dates.txt"

DAILY_INTERVAL = 0.35
BATCH_SIZE = 30
PAGE_LIMIT = 5000
MAX_RETRIES = 3

ts.set_token(TOKEN)
pro = ts.pro_api()

# ------------------ 通用函数 ------------------
def safe_call(func, **kwargs) -> pd.DataFrame:
    for attempt in range(MAX_RETRIES):
        try:
            df = func(**kwargs)
            if df is not None:
                return df
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"      ❌ 重试 {MAX_RETRIES} 次后失败: {e}", flush=True)
                return pd.DataFrame()
            time.sleep(2)
    return pd.DataFrame()

def atomic_save(df: pd.DataFrame, filepath: str):
    if df is None or df.empty:
        return
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix='.parquet', dir=os.path.dirname(filepath))
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, filepath)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

# 日线的 batch_append（全量合并）
def batch_append_daily(new_dfs: List[pd.DataFrame], filepath: str):
    if not new_dfs:
        return
    combined = pd.concat(new_dfs, ignore_index=True)
    if os.path.exists(filepath):
        old = pd.read_parquet(filepath)
        old['trade_date'] = old['trade_date'].astype(str)
        combined = pd.concat([old, combined], ignore_index=True)
    combined = combined.drop_duplicates(['ts_code', 'trade_date'])
    combined = combined.sort_values(['ts_code', 'trade_date'])
    atomic_save(combined, filepath)

# 因子的高效追加更新
def update_factors(new_factors: pd.DataFrame, factor_file: str):
    if new_factors.empty:
        return
    new_factors['trade_date'] = new_factors['trade_date'].astype(str)
    if os.path.exists(factor_file):
        old = pd.read_parquet(factor_file)
        old['trade_date'] = old['trade_date'].astype(str)
        combined = pd.concat([old, new_factors], ignore_index=True)
        combined = combined.drop_duplicates(['ts_code', 'trade_date'])
        atomic_save(combined, factor_file)
    else:
        atomic_save(new_factors, factor_file)

def get_trade_dates(start_date: str, end_date: str) -> List[str]:
    try:
        cal = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date)
        if not cal.empty:
            cal['cal_date'] = cal['cal_date'].astype(str)
            cal['is_open'] = cal['is_open'].astype(str)
            return cal[cal['is_open'] == '1']['cal_date'].tolist()
    except Exception:
        pass
    all_dates = pd.date_range(start_date, end_date).strftime("%Y%m%d").tolist()
    return [d for d in all_dates if datetime.strptime(d, "%Y%m%d").weekday() < 5]

def load_progress() -> Set[str]:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return set(line.strip() for line in f)
    return set()

def save_progress(progress: Set[str]):
    with open(PROGRESS_FILE, 'w') as f:
        for d in sorted(progress):
            f.write(d + '\n')

def load_failed() -> List[str]:
    if os.path.exists(FAILED_FILE):
        with open(FAILED_FILE, 'r') as f:
            return [line.strip() for line in f]
    return []

def save_failed(failed_dates: List[str]):
    with open(FAILED_FILE, 'w') as f:
        for d in failed_dates:
            f.write(d + '\n')

# ------------------ 日线下载 ------------------
def download_one_day(trade_date: str) -> pd.DataFrame:
    parts = []
    offset = 0
    while True:
        df = safe_call(pro.daily, trade_date=trade_date, limit=PAGE_LIMIT, offset=offset)
        if df.empty:
            break
        parts.append(df)
        if len(df) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
        time.sleep(0.1)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

# ------------------ 因子下载（安全分页） ------------------
def download_factors_batch(start_date: str, end_date: str) -> pd.DataFrame:
    all_parts = []
    offset = 0
    max_pages = 100
    last_df = None
    for _ in range(max_pages):
        df = safe_call(pro.adj_factor, start_date=start_date, end_date=end_date,
                       limit=PAGE_LIMIT, offset=offset)
        if df.empty:
            break
        # 检测 offset 是否失效（重复数据）
        if last_df is not None and df.equals(last_df):
            print("      ⚠️ 分页参数无效，停止分页", flush=True)
            break
        all_parts.append(df)
        if len(df) < PAGE_LIMIT:
            break
        last_df = df
        offset += PAGE_LIMIT
        time.sleep(1)   # 分页间隔
    if all_parts:
        combined = pd.concat(all_parts, ignore_index=True)
        combined['trade_date'] = combined['trade_date'].astype(str)
        return combined
    return pd.DataFrame()

# ------------------ 主程序 ------------------
def main():
    print("=" * 70)
    print("Tushare 数据下载器（稳健版：日线逐日 + 因子一次性批量）")
    print("=" * 70, flush=True)

    today = datetime.today().strftime("%Y%m%d")
    progress = load_progress()
    if progress:
        last_success = max(progress)
        start_date = (datetime.strptime(last_success, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        print(f"📌 增量模式：已有 {len(progress)} 个交易日，从 {start_date} 开始")
    else:
        start_date = "19900101"
        print("📌 全量模式：从 1990-01-01 开始")

    if start_date > today:
        print("✅ 数据已是最新")
        return

    trade_dates = get_trade_dates(start_date, today)
    if not trade_dates:
        print("⚠️ 无交易日需要下载")
        return
    print(f"📅 待下载交易日数量: {len(trade_dates)}")

    # ---------- 1. 逐日下载日线 ----------
    batch_raw = []
    batch_dates = []
    failed_dates = load_failed()
    total_success = 0

    for idx, d in enumerate(trade_dates, 1):
        if d in progress:
            continue

        print(f"[{idx}/{len(trade_dates)}] {d} ...", flush=True)
        raw_df = download_one_day(d)

        if raw_df.empty:
            print(f"  ❌ 日线为空，标记失败")
            failed_dates.append(d)
            save_failed(failed_dates)
            continue

        batch_raw.append(raw_df)
        batch_dates.append(d)

        if len(batch_dates) >= BATCH_SIZE or idx == len(trade_dates):
            try:
                if batch_raw:
                    batch_append_daily(batch_raw, RAW_FILE)
                    print(f"  💾 批量写入 {len(batch_raw)} 天日线")
            except Exception as e:
                print(f"  ❌ 批量写入失败: {e}，下次重试")
                batch_dates.clear()
                batch_raw.clear()
                continue

            for success_day in batch_dates:
                progress.add(success_day)
            save_progress(progress)
            total_success += len(batch_dates)
            batch_dates.clear()
            batch_raw.clear()

        time.sleep(DAILY_INTERVAL)

    print(f"\n✅ 日线下载完成！新增 {total_success} 个交易日")
    if failed_dates:
        print(f"⚠️ 失败日期记录在 {FAILED_FILE}")

    # ---------- 2. 一次性下载复权因子（整个日期范围） ----------
    print("\n📊 正在批量下载复权因子...", flush=True)
    fct_df = download_factors_batch(start_date, today)
    if not fct_df.empty:
        update_factors(fct_df, FCT_FILE)
        print(f"✅ 复权因子更新完成，新增 {len(fct_df)} 条记录")
    else:
        print("⚠️ 未获取到复权因子（可能权限不足或网络问题）")

    # ---------- 3. 生成前复权数据 ----------
    if os.path.exists(RAW_FILE) and os.path.exists(FCT_FILE):
        print("\n📊 正在生成前复权数据...")
        try:
            raw = pd.read_parquet(RAW_FILE)
            fct = pd.read_parquet(FCT_FILE)
            raw['trade_date'] = raw['trade_date'].astype(str)
            fct['trade_date'] = fct['trade_date'].astype(str)

            df = pd.merge(raw, fct, on=['ts_code', 'trade_date'], how='left')
            df = df.sort_values(['ts_code', 'trade_date'])
            df['adj_factor'] = df.groupby('ts_code')['adj_factor'].ffill().fillna(1)
            last_factor = df.groupby('ts_code')['adj_factor'].transform('last')
            for col in ['open', 'high', 'low', 'close']:
                if col in df.columns:
                    df[col + '_adj'] = df[col] * last_factor / df['adj_factor']
            atomic_save(df, ADJ_FILE)
            print(f"✅ 前复权数据保存至 {ADJ_FILE}")
        except Exception as e:
            print(f"❌ 生成前复权失败: {e}")
    else:
        print("⚠️ 缺少日线或因子文件，跳过前复权生成")

    print("\n🎉 全部完成")

if __name__ == "__main__":
    main()