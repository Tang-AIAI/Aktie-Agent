#!/usr/bin/env python3
"""
个股数据每日更新（从 new_update_daily_data.py 迁移，下载逻辑保持原样）
- 日线：逐日下载 + batch_append（全量重写，可接受）
- 复权因子：一次性批量请求 + 安全分页；adj_factor 限频 1次/分钟，页间等待 65s，
  不再静默截断；下载后做覆盖率校验，不完整时提示运行 backfill_adj_factor.py
- 交易日判断：data/trade_calendar.py（交易所日历 + 本地缓存）
- 路径：统一从 data/paths.py 取，任意 cwd 均可运行
"""

import sys
import os
import time
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Set

import tushare as ts
import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from data.paths import RAW_FILE, FCT_FILE, ADJ_FILE, PROGRESS_FILE, FAILED_FILE  # noqa: E402
from data.trade_calendar import get_trade_dates  # noqa: E402
from data.storage import atomic_save, append_dedupe  # noqa: E402
from data.adj_data import build_forward_adjusted  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("TUSHARE_TOKEN")
DAILY_INTERVAL = 0.35
BATCH_SIZE = 30
PAGE_LIMIT = 5000
MAX_RETRIES = 3
FCT_PAGE_INTERVAL = 65      # adj_factor 接口限频 1次/分钟
FCT_MAX_RETRIES = 5

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

def safe_call_fct(func, **kwargs) -> pd.DataFrame:
    """复权因子专用请求：限频 1次/分钟，失败后等 65s 重试。"""
    for attempt in range(FCT_MAX_RETRIES):
        try:
            df = func(**kwargs)
            if df is not None:
                return df
        except Exception as e:
            print(f"      ⚠️ 请求失败（第 {attempt+1}/{FCT_MAX_RETRIES} 次）: {e}", flush=True)
            if attempt < FCT_MAX_RETRIES - 1:
                time.sleep(FCT_PAGE_INTERVAL)
    return pd.DataFrame()

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

# ------------------ 因子下载（限频感知分页） ------------------
def download_factors_batch(start_date: str, end_date: str) -> pd.DataFrame:
    all_parts = []
    offset = 0
    max_pages = 200
    for page in range(max_pages):
        df = safe_call_fct(pro.adj_factor, start_date=start_date, end_date=end_date,
                           limit=PAGE_LIMIT, offset=offset)
        if df.empty:
            break
        all_parts.append(df)
        if len(df) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
        time.sleep(FCT_PAGE_INTERVAL)   # 尊重 1次/分钟 限频
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
                    append_dedupe(pd.concat(batch_raw, ignore_index=True), RAW_FILE)
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
    print("\n📊 正在批量下载复权因子...（限频 1次/分钟，耐心等待）", flush=True)
    fct_df = download_factors_batch(start_date, today)
    if not fct_df.empty:
        fct_df["source"] = "tushare"
        # keep="last"：Tushare 官方数据覆盖同键的新浪合成因子
        append_dedupe(fct_df, FCT_FILE, keep="last")
        print(f"✅ 复权因子更新完成，新增 {len(fct_df)} 条记录")

        # 覆盖率校验：本窗口因子行数应约等于窗口内日线行数（逐日逐股）
        raw = pd.read_parquet(RAW_FILE)
        raw['trade_date'] = raw['trade_date'].astype(str)
        expected = ((raw['trade_date'] >= start_date) & (raw['trade_date'] <= today)).sum()
        if len(fct_df) < expected * 0.98:
            print(f"❌ 复权因子疑似截断：窗口内日线 {expected} 行，因子仅 {len(fct_df)} 条")
            print(f"   请运行 python scripts/backfill_adj_factor.py 回补缺口")
    else:
        print("⚠️ 未获取到复权因子（可能权限不足或网络问题）")

    # ---------- 3. 生成前复权数据 ----------
    if os.path.exists(RAW_FILE) and os.path.exists(FCT_FILE):
        print("\n📊 正在生成前复权数据...", flush=True)
        try:
            raw = pd.read_parquet(RAW_FILE)
            fct = pd.read_parquet(FCT_FILE)
            df = build_forward_adjusted(raw, fct)
            atomic_save(df, ADJ_FILE)
            print(f"✅ 前复权数据保存至 {ADJ_FILE}")
        except Exception as e:
            print(f"❌ 生成前复权失败: {e}")
    else:
        print("⚠️ 缺少日线或因子文件，跳过前复权生成")

    print("\n🎉 全部完成")

if __name__ == "__main__":
    main()
