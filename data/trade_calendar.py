"""交易所交易日历：新浪交易日列表（主）+ Tushare trade_cal（备）+ 本地缓存。

背景（2026-09-15 调查）：
- 低积分下 Tushare trade_cal 限频约 1次/小时，且大跨度查询被服务端截断
  （36 年范围只返回最近 3 行），导致旧实现的日历缓存损坏。
- 新浪 klc_td_sh 列表（经 akshare.tool_trade_date_hist_sina 解密）覆盖
  1990-12-19 至今及未来计划交易日，一次请求全量返回，无积分限制。
- 写入缓存前必须通过校验：覆盖范围完整 + 与 raw 数据实际交易日交叉一致。
  不完整的接口返回绝不写入正式缓存。
"""

import os
import sys

import pandas as pd
import tushare as ts
from dotenv import load_dotenv

# 本模块的回退路径会打印 ⚠️ 等字符；Windows 默认 GBK 控制台下会触发
# UnicodeEncodeError（测试/命令行运行中断）。统一按 UTF-8 输出（与 scripts/check_data.py 同口径）。
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from data.paths import BASE_DIR, CALENDAR_FILE, RAW_FILE
from data.storage import atomic_save

CAL_START = "19900101"  # 日历最早日期（上交所开市前，覆盖全部历史）

load_dotenv(BASE_DIR / ".env")
ts.set_token(os.getenv("TUSHARE_TOKEN"))
pro = ts.pro_api()


def _sina_dates() -> list:
    """新浪交易日列表（YYYYMMDD 字符串，升序）。"""
    import akshare as ak
    df = ak.tool_trade_date_hist_sina()
    return sorted(df["trade_date"].astype(str).str.replace("-", ""))


def _validate(dates: list, end_date: str) -> bool:
    """校验日历：最近日期足够新，且与 raw 数据实际交易日（2026 年起）完全一致。"""
    dates = set(dates)
    if not dates:
        return False
    if max(dates) < end_date:
        return False
    try:
        raw = pd.read_parquet(RAW_FILE, columns=["trade_date"])
        raw_dates = set(raw["trade_date"].astype(str))
        recent_raw = {d for d in raw_dates if d >= "20260101"}
        recent_cal = {d for d in dates if "20260101" <= d <= end_date}
        if recent_raw and not recent_raw.issubset(recent_cal):
            return False
    except Exception:
        pass  # raw 不可读时不做强校验
    return True


def _cache_usable(old: pd.DataFrame, end_date: str) -> bool:
    """缓存可用性校验：覆盖 end 且近 90 天有不少于 50 个交易日。"""
    dates = set(old["cal_date"].astype(str))
    if not dates:
        return False
    if max(dates) < end_date:
        return False
    start = (pd.Timestamp(end_date) - pd.Timedelta(days=90)).strftime("%Y%m%d")
    recent = {d for d in dates if start <= d <= end_date}
    return len(recent) >= 50


def refresh_calendar(end_date: str) -> pd.DataFrame:
    """刷新日历缓存至 end_date（含），返回 DataFrame[cal_date, is_open]。

    数据源优先级：新浪（一次请求全量）→ Tushare trade_cal（小跨度）→
    已有缓存/工作日回退。只有通过校验的数据才会写入缓存。
    """
    # 已有缓存足够新且内容可用时直接使用
    if os.path.exists(CALENDAR_FILE):
        old = pd.read_parquet(CALENDAR_FILE)
        if _cache_usable(old, end_date):
            return old

    # 1) 新浪（主源）
    try:
        dates = _sina_dates()
        if _validate(dates, end_date):
            df = pd.DataFrame({"cal_date": sorted(dates), "is_open": 1})
            atomic_save(df, CALENDAR_FILE)
            return df
        raise RuntimeError("新浪日历校验失败")
    except Exception as e:
        print(f"  ⚠️ 新浪日历不可用: {e}", flush=True)

    # 2) Tushare trade_cal（小跨度查询，规避服务端截断）
    try:
        start = (pd.Timestamp(end_date) - pd.Timedelta(days=90)).strftime("%Y%m%d")
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end_date)
        if cal is not None and not cal.empty:
            cal["cal_date"] = cal["cal_date"].astype(str)
            cal["is_open"] = cal["is_open"].astype(int)
            if str(cal["cal_date"].max()) >= end_date:
                if os.path.exists(CALENDAR_FILE):
                    old = pd.read_parquet(CALENDAR_FILE)
                    cal = pd.concat([old, cal], ignore_index=True).drop_duplicates("cal_date")
                cal = cal.sort_values("cal_date").reset_index(drop=True)
                atomic_save(cal, CALENDAR_FILE)
                return cal
            raise RuntimeError("trade_cal 覆盖不完整")
    except Exception as e:
        print(f"  ⚠️ Tushare 日历不可用: {e}", flush=True)

    # 3) 已有缓存仍可覆盖 end 时使用缓存（不应到达：步骤 0 已处理）
    if os.path.exists(CALENDAR_FILE):
        old = pd.read_parquet(CALENDAR_FILE)
        if str(old["cal_date"].max()) >= end_date:
            return old

    raise RuntimeError("无法获取交易日历")


def get_trade_dates(start: str, end: str) -> list:
    """返回 [start, end] 内的开盘日列表（YYYYMMDD 字符串）。

    优先用缓存日历；全部数据源失败时退回工作日列表（不写缓存）。
    """
    try:
        cal = refresh_calendar(end)
        mask = (
            (cal["cal_date"] >= start)
            & (cal["cal_date"] <= end)
            & (cal["is_open"] == 1)
        )
        return cal.loc[mask, "cal_date"].tolist()
    except Exception:
        all_dates = pd.date_range(start, end).strftime("%Y%m%d").tolist()
        return [d for d in all_dates if pd.Timestamp(d).weekday() < 5]


def missing_trade_dates(dates: pd.Series, start: str, end: str) -> list:
    """给定数据中已有的交易日集合，返回 [start, end] 内缺失的开盘日。"""
    expected = set(get_trade_dates(start, end))
    have = set(dates.astype(str))
    return sorted(expected - have)
