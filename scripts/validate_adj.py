#!/usr/bin/env python3
"""复权数据交叉验证（2026-09-15 修复后的验收脚本）。

验证内容（对应调查报告的验证点）：
1. 因子跳变：6 只调查样本的除权日因子跳变与已知基准一致（≤0.5%）
2. 除权日连续性：大额除权（raw 单日 >10%）不再出现复权价幻影跳空
3. 方向正确性：600519 前复权价与腾讯 qfq 基准（20250102=1408.419）一致（≤2%）
4. 最新日不变式：最新交易日 close_adj == close（前复权锚定现价）
5. 历史一致性：随机抽样复核 p_adj = p × F_current / F_last 在旧区间成立
6. 来源分布：adj_factor 表中 tushare / sina 行数统计

用法：python scripts/validate_adj.py [--sample 20]
退出码：全部通过为 0，任一失败为 1。
"""

import sys
import argparse
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402

from data.paths import RAW_FILE, FCT_FILE, ADJ_FILE  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

# (ts_code, 除权日, 期望跳变 F_after/F_before) —— 来自 2026-09-15 调查实测
EXPECTED_JUMPS = [
    ("688256.SH", "20260508", 1.491200),
    ("603596.SH", "20260511", 1.491816),
    ("002245.SZ", "20260521", 1.485907),
    ("600519.SH", "20260626", 1.023667),
    ("920029.BJ", "20260529", 1.526100),
    ("000001.SZ", "20260612", 1.032907),
]

failures = []


def check(name, ok, detail):
    print(f"  {'✅' if ok else '❌'} {name}: {detail}")
    if not ok:
        failures.append(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=20)
    args = parser.parse_args()

    print("读取数据...", flush=True)
    raw = pd.read_parquet(RAW_FILE)
    fct = pd.read_parquet(FCT_FILE)
    adj = pd.read_parquet(ADJ_FILE)
    for df in (raw, fct, adj):
        df["trade_date"] = df["trade_date"].astype(str)
    fct = fct.sort_values(["ts_code", "trade_date"])
    adj = adj.sort_values(["ts_code", "trade_date"])

    # ---------- 1. 因子跳变 ----------
    print("\n[1] 因子跳变对照")
    for ts_code, ex_date, expected in EXPECTED_JUMPS:
        f = fct[fct["ts_code"] == ts_code]
        if f.empty:
            check(ts_code, False, "无因子数据")
            continue
        before = f[f["trade_date"] < ex_date]
        after = f[f["trade_date"] >= ex_date]
        if before.empty or after.empty:
            check(ts_code, False, f"除权日 {ex_date} 前后因子缺失")
            continue
        got = float(after["adj_factor"].iloc[0]) / float(before["adj_factor"].iloc[-1])
        rel = abs(got / expected - 1)
        check(ts_code, rel <= 0.005, f"跳变 {got:.6f} vs 基准 {expected:.6f} ({rel*100:.4f}%)")

    # ---------- 2. 除权日连续性 ----------
    print("\n[2] 除权日复权连续性（大额除权不应出现幻影跳空）")
    for ts_code, ex_date, _ in EXPECTED_JUMPS:
        a = adj[adj["ts_code"] == ts_code].set_index("trade_date")
        if ex_date not in a.index:
            check(ts_code, False, f"{ex_date} 无复权数据")
            continue
        i = a.index.get_loc(ex_date)
        if i == 0:
            check(ts_code, False, f"{ex_date} 是首日")
            continue
        prev = a.iloc[i - 1]
        cur = a.iloc[i]
        raw_ret = cur["close"] / prev["close"] - 1
        adj_ret = cur["close_adj"] / prev["close_adj"] - 1
        ok = abs(raw_ret) < 0.10 or abs(adj_ret) < 0.10
        check(ts_code, ok,
              f"raw {raw_ret*100:+.2f}% → 复权 {adj_ret*100:+.2f}%")

    # ---------- 3. 方向正确性（腾讯 qfq 基准） ----------
    print("\n[3] 方向正确性（600519 前复权 vs 腾讯基准 1408.419 @20250102）")
    a = adj[(adj["ts_code"] == "600519.SH") & (adj["trade_date"] == "20250102")]
    if a.empty:
        check("600519 方向", False, "无数据")
    else:
        got = float(a["close_adj"].iloc[0])
        rel = abs(got / 1408.419 - 1)
        check("600519 方向", rel <= 0.02, f"close_adj={got:.3f} vs 1408.419 ({rel*100:.2f}%)")

    # ---------- 4. 最新日不变式 ----------
    print("\n[4] 最新日不变式（close_adj == close @ 最新交易日）")
    latest = adj["trade_date"].max()
    a_latest = adj[adj["trade_date"] == latest]
    ratio = a_latest["close_adj"] / a_latest["close"]
    exact = (ratio - 1).abs() < 1e-6
    ok = exact.mean() >= 0.99
    check("最新日不变式", bool(ok),
          f"{latest}: {exact.sum()}/{len(a_latest)} 只股票复权价==原价 ({exact.mean()*100:.2f}%)")

    # ---------- 5. 历史一致性（随机抽样复核公式） ----------
    print(f"\n[5] 历史一致性（随机 {args.sample} 只股票 × 5 个旧交易日）")
    rng = random.Random(20260915)
    stocks = sorted(raw["ts_code"].unique())
    sample = rng.sample(stocks, args.sample)
    all_ok = True
    for ts_code in sample:
        r = raw[raw["ts_code"] == ts_code].set_index("trade_date")
        f = fct[fct["ts_code"] == ts_code]
        if f.empty:
            continue
        a = adj[adj["ts_code"] == ts_code].set_index("trade_date")
        # 5 个 2020~2026-04-30 间的日期
        candidates = [d for d in r.index if "20200101" <= d <= "20260430"]
        if not candidates:
            continue
        picks = rng.sample(candidates, min(5, len(candidates)))
        f_map = dict(zip(f["trade_date"], f["adj_factor"]))
        f_last = f["adj_factor"].iloc[-1]
        # ffill 语义：日期 d 的因子 = d 之前最近一条记录
        f_sorted = f.set_index("trade_date")["adj_factor"]
        for d in picks:
            cur_factor = f_sorted[f_sorted.index <= d].iloc[-1]
            expected = float(r.loc[d, "close"]) * float(cur_factor) / float(f_last)
            got = float(a.loc[d, "close_adj"])
            if abs(got / expected - 1) > 1e-6:
                all_ok = False
                check(f"{ts_code}@{d}", False, f"{got} vs 公式 {expected}")
                break
        if failures and f"{ts_code}" in str(failures):
            break
    if all_ok and not any("@" in x for x in failures):
        check(f"随机抽样({len(sample)}只)", True, "全部符合 p_adj = p × F_current / F_last")

    # ---------- 6. 来源分布 ----------
    print("\n[6] 因子来源分布")
    if "source" in fct.columns:
        dist = fct["source"].fillna("tushare").value_counts()
        print("  " + dist.to_string())
        check("来源列", True, "source 列存在")
    else:
        check("来源列", False, "无 source 列")

    print(f"\n{'='*50}\n结果: {'✅ 全部通过' if not failures else f'❌ {len(failures)} 项失败: {failures}'}")
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
