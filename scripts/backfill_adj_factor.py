#!/usr/bin/env python3
"""复权因子缺口回补（限频感知 + 断点续传）。

背景：adj_factor 接口限频 1次/分钟，旧脚本分页间隔仅 1s，第 2 页起必被限频，
导致 2026-05 之后因子数据只有每天"最新一页 5000 条"被下载，形成缺口。

本脚本：
- 按 offset 分页回补 [start, end] 的因子数据（默认 20260501 ~ 今天）
- 每页间隔 65s 尊重限频；失败重试 5 次，每次等 65s
- 断点续传：adj_backfill_state.txt 记录下一个 offset，中断后重跑即续传
- 每页立即去重合并进 adj_factor.parquet（原子写）

预估时长：约 100 页 × 65s ≈ 110 分钟，建议后台运行。
"""

import sys
import os
import time
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
import tushare as ts
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from data.paths import RAW_FILE, FCT_FILE  # noqa: E402
from data.storage import append_dedupe  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

load_dotenv(BASE_DIR / ".env")
ts.set_token(os.getenv("TUSHARE_TOKEN"))
pro = ts.pro_api()

PAGE_LIMIT = 5000
PAGE_INTERVAL = 65  # adj_factor 限频 1次/分钟
MAX_RETRIES = 5
STATE_FILE = BASE_DIR / "adj_backfill_state.txt"


def load_state() -> int:
    if STATE_FILE.exists():
        return int(STATE_FILE.read_text().strip())
    return 0


def save_state(offset: int):
    STATE_FILE.write_text(str(offset))


def clear_state():
    if STATE_FILE.exists():
        os.remove(STATE_FILE)


def fetch_page(start: str, end: str, offset: int) -> pd.DataFrame:
    """带重试的单页请求；5 次失败返回 None（中止，可续传）。"""
    for attempt in range(MAX_RETRIES):
        try:
            df = pro.adj_factor(start_date=start, end_date=end,
                                limit=PAGE_LIMIT, offset=offset)
            if df is not None:
                return df
        except Exception as e:
            print(f"  ⚠️ 请求失败（第 {attempt+1}/{MAX_RETRIES} 次）: {e}", flush=True)
        if attempt < MAX_RETRIES - 1:
            time.sleep(PAGE_INTERVAL)
    return None


def main():
    parser = argparse.ArgumentParser(description="复权因子缺口回补")
    parser.add_argument("--start", default="20260501")
    parser.add_argument("--end", default=datetime.today().strftime("%Y%m%d"))
    args = parser.parse_args()

    # 预估页数（用窗口内 raw 行数近似因子行数）
    expected = 0
    if os.path.exists(RAW_FILE):
        raw = pd.read_parquet(RAW_FILE)
        raw["trade_date"] = raw["trade_date"].astype(str)
        expected = ((raw["trade_date"] >= args.start) & (raw["trade_date"] <= args.end)).sum()
    est_pages = -(-expected // PAGE_LIMIT)
    print(f"回补范围 {args.start} ~ {args.end}，预估 {est_pages} 页，约 {est_pages} 分钟", flush=True)

    offset = load_state()
    if offset:
        print(f"📌 断点续传：从 offset={offset} 继续", flush=True)

    pages = 0
    while True:
        df = fetch_page(args.start, args.end, offset)
        if df is None:
            print(f"❌ offset={offset} 连续 {MAX_RETRIES} 次失败，中止（重跑本脚本可续传）", flush=True)
            return

        if df.empty:
            print("✅ 已到数据末尾，回补完成", flush=True)
            clear_state()
            return

        df["trade_date"] = df["trade_date"].astype(str)
        df["source"] = "tushare"
        # keep="last"：Tushare 官方数据覆盖同键的新浪合成因子
        append_dedupe(df, FCT_FILE, keep="last")
        offset += len(df)
        save_state(offset)
        pages += 1
        print(f"✅ 第 {pages} 页：+{len(df)} 条（{df['trade_date'].min()} ~ {df['trade_date'].max()}），"
              f"累计 offset={offset}", flush=True)

        if len(df) < PAGE_LIMIT:
            print("🎉 回补完成", flush=True)
            clear_state()
            return
        time.sleep(PAGE_INTERVAL)


if __name__ == "__main__":
    main()
