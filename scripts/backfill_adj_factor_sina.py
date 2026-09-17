#!/usr/bin/env python3
"""用新浪 qfq.js 因子链回补 adj_factor.parquet 的缺失段（2026-05-01 至今）。

背景与方法（2026-09-15 调查实证，详见 PROJECT_CONTEXT.md）：
- Tushare adj_factor 在低积分下被限频（错误码 40203，约 1次/小时），
  2026-05 起因子数据每天只有"最新一页 5000 条"被下载，缺口约 88 个交易日。
- 新浪 qfq.js 公开每只股票的除权因子链，其事件跳变与 Tushare 因子跳变
  吻合 ≤0.03%（高送转/分红/北交所各样本实测）。
- 合成方法：以每只股票的 Tushare 因子为锚点，
  F(d) = F0 × f(d0)/f(d)，f 为新浪因子链（无 Tushare 数据的新股以
  上市日为 d0、F0=1.0）。生成缺口期逐日因子，与现有数据按
  (ts_code, trade_date) 去重，绝不覆盖已有 Tushare 行。

缺口检测（逐股）：
  1. 尾部缺口：raw 最新日期晚于最后一条 Tushare 因子日期
     （如因子停留在 2026-04-30 的 526 只股票）；
  2. 内部缺口：相邻两条 Tushare 因子记录之间日期不连续且因子值发生变化
     （如 0915 残页股在 0430→0915 之间发生过除权，中间因子缺失）。

断点续传：sina_backfill_state.json 记录已完成股票；失败股票记入
sina_backfill_failed.txt 并在下次运行时重试。全量跑完且无失败时清除状态。
重跑全量：--force。
"""

import sys
import os
import time
import json
import argparse
from pathlib import Path

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from data.paths import RAW_FILE, FCT_FILE  # noqa: E402
from data.sina_factor import parse_chain, synth_factors  # noqa: E402
from data.storage import append_dedupe, atomic_save  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

REQUEST_INTERVAL = 0.4
FLUSH_EVERY = 200
STATE_FILE = BASE_DIR / "sina_backfill_state.json"
FAILED_FILE = BASE_DIR / "sina_backfill_failed.txt"
WINDOW_START = "20260401"   # 只关注该日期之后的因子缺口（此前 Tushare 数据完整）

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
})


def sina_chain(ts_code: str) -> list:
    """拉取并解析某只股票的新浪因子链（日期倒序）。"""
    code, suffix = ts_code.split(".")
    url = f"https://finance.sina.com.cn/realstock/company/{suffix.lower()}{code}/qfq.js"
    r = SESSION.get(url, timeout=20)
    r.raise_for_status()
    return parse_chain(r.text)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"processed": [], "failed": {}}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def save_failed(failed: dict):
    with open(FAILED_FILE, "w", encoding="utf-8") as f:
        for code, err in failed.items():
            f.write(f"{code}\t{err}\n")


def find_gap_segments(raw_dates: list, recent: dict, prev: dict) -> list:
    """返回 [(d_a, F_a, d_b, is_tail)]：需要合成的区间。

    :param raw_dates: 该股 raw 交易日（升序）
    :param recent: {ts_code: (dates, vals)} WINDOW_START 之后的 Tushare 因子
    :param prev: {ts_code: (date, val)} WINDOW_START 之前最后一条 Tushare 因子
    :param is_tail: True 表示 d_b 是 raw 最新日期（尾部缺口），区间含 d_b；
                    否则区间为 (d_a, d_b)，不含 d_b（d_b 已有 Tushare 行）
    """
    segs = []
    rd, rv = recent
    if rd:
        # 边界对：窗口前最后一条 → 窗口内第一条
        if prev is not None:
            d_p, f_p = prev
            if int(rd[0]) - int(d_p) > 1 and abs(float(f_p) - float(rv[0])) > 1e-9:
                segs.append((d_p, float(f_p), rd[0], False))
        # 窗口内相邻对
        for i in range(len(rd) - 1):
            if int(rd[i + 1]) - int(rd[i]) > 1 and abs(float(rv[i + 1]) - float(rv[i])) > 1e-9:
                segs.append((rd[i], float(rv[i]), rd[i + 1], False))
    # 尾部缺口（只处理 2026-05-01 之后的缺失；更早的历史洞不在本任务范围）
    last_tush_date = rd[-1] if rd else None
    if (last_tush_date is None or raw_dates[-1] > last_tush_date) \
            and raw_dates[-1] >= "20260501":
        d_a = last_tush_date if last_tush_date is not None else raw_dates[0]
        F_a = float(rv[-1]) if rd else 1.0
        segs.append((d_a, F_a, raw_dates[-1], True))
    return segs


def synth_segment(chain, raw_dates, seg):
    d_a, F_a, d_b, is_tail = seg
    if is_tail:
        dates = [d for d in raw_dates if d_a < d <= d_b]
    else:
        dates = [d for d in raw_dates if d_a < d < d_b]
    # 任务范围：只合成 2026-05-01 之后的因子
    dates = [d for d in dates if d >= "20260501"]
    return synth_factors(chain, dates, d_a, F_a)


def main():
    parser = argparse.ArgumentParser(description="新浪因子链回补 adj_factor 缺口")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 只股票（测试用）")
    parser.add_argument("--force", action="store_true", help="忽略断点状态重新全量")
    args = parser.parse_args()

    # ---------- 1. 读取 raw 交易日与 Tushare 因子锚点 ----------
    print("读取 raw 数据（ts_code, trade_date）...", flush=True)
    raw = pd.read_parquet(RAW_FILE, columns=["ts_code", "trade_date"])
    raw["trade_date"] = raw["trade_date"].astype(str)
    raw_dates = raw.groupby("ts_code")["trade_date"].apply(lambda s: sorted(s))

    print("读取 adj_factor.parquet 锚点...", flush=True)
    fct = pd.read_parquet(FCT_FILE)
    fct["trade_date"] = fct["trade_date"].astype(str)
    tush = fct if "source" not in fct.columns else fct[fct["source"] != "sina"]
    tush = tush.sort_values(["ts_code", "trade_date"])
    tush_recent = tush[tush["trade_date"] >= WINDOW_START]
    tush_old = tush[tush["trade_date"] < WINDOW_START]

    recent_by_code = {}
    for code, grp in tush_recent.groupby("ts_code", sort=False):
        recent_by_code[code] = (grp["trade_date"].tolist(), grp["adj_factor"].tolist())
    prev_by_code = {}
    for code, grp in tush_old.groupby("ts_code", sort=False):
        prev_by_code[code] = (grp["trade_date"].iloc[-1], grp["adj_factor"].iloc[-1])

    # ---------- 2. 逐股计算需要合成的缺口 ----------
    plans = {}   # ts_code -> [(d_a, F_a, d_b, is_tail)]
    for ts_code, dates in raw_dates.items():
        segs = find_gap_segments(dates, recent_by_code.get(ts_code, ([], [])),
                                 prev_by_code.get(ts_code))
        if segs:
            plans[ts_code] = segs
    print(f"需要回补的股票: {len(plans)} 只", flush=True)

    # ---------- 3. 断点续传状态 ----------
    state = {} if args.force else load_state()
    processed = set(state.get("processed", []))
    failed = dict(state.get("failed", {}))
    todo = [c for c in plans if c not in processed and c not in failed]
    if args.limit:
        todo = todo[:args.limit]
    print(f"断点状态: 已完成 {len(processed)}, 待处理 {len(todo)}", flush=True)

    # ---------- 4. 逐股回补 ----------
    buffer = []          # [(ts_code, trade_date, adj_factor)]
    done_since_flush = []
    t_start = time.time()
    processed_count = len(processed)

    def flush():
        nonlocal buffer, done_since_flush
        if not buffer:
            return
        df = pd.DataFrame(buffer, columns=["ts_code", "trade_date", "adj_factor"])
        df["source"] = "sina"
        append_dedupe(df, FCT_FILE, keep="first")
        processed.update(done_since_flush)
        state["processed"] = sorted(processed)
        state["failed"] = failed
        save_state(state)
        save_failed(failed)
        print(f"  💾 写入 {len(df)} 行（累计完成 {len(processed)} 只）", flush=True)
        buffer = []
        done_since_flush = []

    for i, ts_code in enumerate(todo, 1):
        try:
            chain = sina_chain(ts_code)
            for seg in plans[ts_code]:
                rows = synth_segment(chain, raw_dates[ts_code], seg)
                buffer.extend((ts_code, d, f) for d, f in rows)
            done_since_flush.append(ts_code)
        except Exception as e:
            failed[ts_code] = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"  ⚠️ {ts_code} 失败: {failed[ts_code]}", flush=True)

        if i % FLUSH_EVERY == 0:
            flush()
        if i % 100 == 0:
            el = time.time() - t_start
            print(f"[{i}/{len(todo)}] 耗时 {el:.0f}s，平均 {el/i:.2f}s/只，"
                  f"预计剩余 {(len(todo)-i)*el/i/60:.0f} 分钟", flush=True)
        time.sleep(REQUEST_INTERVAL)

    flush()

    # ---------- 5. 收尾：旧行来源统一标记为 tushare ----------
    fct = pd.read_parquet(FCT_FILE)
    if "source" not in fct.columns:
        fct["source"] = "tushare"
    else:
        fct["source"] = fct["source"].fillna("tushare")
    fct["trade_date"] = fct["trade_date"].astype(str)
    atomic_save(fct, FCT_FILE)

    print(f"\n回补完成：新增处理 {len(processed) - processed_count} 只，"
          f"失败 {len(failed)} 只", flush=True)
    if failed:
        print(f"失败名单: {FAILED_FILE}（下次运行自动重试）", flush=True)
    else:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print("全部成功，断点状态已清除", flush=True)


if __name__ == "__main__":
    main()
