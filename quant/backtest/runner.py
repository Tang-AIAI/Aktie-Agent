"""Strategy A 历史回测主流程：调仓日排名（<= as_of 数据）→ 次日开盘成交 → 每日收盘估值。

防未来数据泄漏的边界（设计保证，勿改）：
1. 第 d 个交易日收盘后调用 run_strategy(as_of=d)：引擎内部按 [d−窗口, d] 切片，
   排名只使用 <= d 的数据（见 quant/engine.py）；
2. 选出的 Top N 在次一交易日 d+1 以开盘价成交（默认 next_open）：
   选股决策不依赖 d+1 的任何数据；只有成交价依赖 d+1 开盘（成交时刻才可知），
   不构成泄漏；
3. 停牌（执行日无行情行）→ 不假装成交：买入跳过（现金保留）、卖出跳过（继续持有）；
4. 持仓估值用每日收盘价 close_adj，停牌期间 ffill 最后可用价格；
5. 前复权价口径：close_adj = 原价 × F_t / F_last（data/adj_data.py）。收益计算只取
   复权价"比值"，比值 = (p_t·F_t) / (p_{t-w}·F_{t-w})，与 F_last（当前最新因子）
   无关——即"以今天的最新因子重算历史价格"不改变历史任意两日的收益率，
   因此不引入未来数据泄漏；历史绝对价格随 F_last 整体缩放，但本回测只用比值。
6. 股票池为 PIT：调用方传 use_stock_list=False 的 Strategy（当日有行情即在池），
   不用当前 stock_list.csv 排除历史退市股（避免幸存者偏差）。

简化口径（MVP，报告中注明）：
- 整数股成交（不模拟 100 股整手，误差 ≤ 1 股/笔）；交易成本单边 cost_rate；
- 退市/长期停牌股按最后可用价格继续估值（不模拟退市清算）；
- 基准为沪深300 价格指数（不含分红再投资）。
"""

import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.backtest.metrics import (
    annualized_return,
    cumulative_return,
    max_drawdown,
    win_rate,
)
from quant.backtest.portfolio import Portfolio
from quant.engine import run_strategy
from quant.market_data import MarketDataLoader

PRICE_COLUMNS = ("ts_code", "trade_date", "close_adj", "open_adj")
INITIAL_CASH = 1_000_000.0
MAX_RANKING_WARNINGS = 3    # 每个调仓日最多透传的引擎警告条数
MAX_TOTAL_WARNINGS = 30     # 回测总警告条数上限（避免长区间刷屏）


@dataclass
class BacktestResult:
    start: str
    end: str
    params: dict                     # 本次回测全部参数（可复现快照）
    data_version: str                # 数据文件指纹（mtime+size）
    nav: pd.DataFrame                # trade_date, nav, benchmark（无基准时无 benchmark 列）
    rebalances: pd.DataFrame         # 每次调仓一行：日期/买卖数/跳数/换手/现金/净值
    trades: pd.DataFrame             # 逐笔成交：执行日/调仓日/代码/名称/方向/份额/价格/成本/金额
    metrics: dict                    # 组合指标 / 基准指标 / 超额收益 / 胜率 / 交易日数
    warnings: list = field(default_factory=list)


class PriceTable:
    """每股价格序列的内存列式存储：按日取收盘价（ffill）/ 按日取开盘价（仅当日）。

    由整段行情 DataFrame 构建（trade_date 先整体升序，groupby 保持组内日期序）。
    """

    def __init__(self, market: pd.DataFrame):
        self._dates = {}    # ts_code -> np.int64 数组（YYYYMMDD）
        self._close = {}    # ts_code -> float64 数组
        self._open = {}     # ts_code -> float64 数组
        market = market.sort_values("trade_date")
        for code, g in market.groupby("ts_code", sort=False):
            self._dates[code] = g["trade_date"].astype("int64").to_numpy()
            self._close[code] = g["close_adj"].astype("float64").to_numpy()
            self._open[code] = g["open_adj"].astype("float64").to_numpy()

    def close_on(self, code: str, date: str) -> float | None:
        """<= date 的最近收盘价（停牌/未上市则取更早值）；date 之前无数据返回 None。"""
        dates = self._dates.get(code)
        if dates is None:
            return None
        i = int(np.searchsorted(dates, int(date), side="right")) - 1
        return float(self._close[code][i]) if i >= 0 else None

    def open_on(self, code: str, date: str) -> float | None:
        """恰好在 date 的开盘价；当日无行情（停牌/未上市/退市）返回 None。"""
        dates = self._dates.get(code)
        if dates is None:
            return None
        i = int(np.searchsorted(dates, int(date), side="left"))
        if i >= len(dates) or dates[i] != int(date):
            return None
        v = float(self._open[code][i])
        return v if not np.isnan(v) else None


def _data_fingerprint(loader: MarketDataLoader) -> str:
    """数据文件指纹（mtime+size），与 Web App 缓存失效同口径；文件缺失记为 missing。"""
    parts = []
    for attr in ("adj_file", "index_file", "stock_list_file"):
        path = getattr(loader, attr, None)
        if not path or not os.path.exists(path):
            parts.append("missing")
            continue
        st = os.stat(path)
        parts.append(f"{st.st_mtime_ns}-{st.st_size}")
    return "|".join(parts)


def _append_warning(warnings: list, text: str) -> None:
    if len(warnings) < MAX_TOTAL_WARNINGS:
        warnings.append(text)


def _plan_rebalance(portfolio, targets: list, exec_date: str,
                    exec_open: dict, top_n: int, warnings: list):
    """按 Top N 等权生成调仓计划（不执行）：卖出目标外持仓，目标内调到 1/N 权重。

    停牌股（exec_open 无价格）不买卖：买入跳过、卖出跳过（继续持有）。
    返回 dict：{exec_date, sells: [(code, shares, px)], buys: [...],
               skipped_sells: [code], skipped_buys: [code], target_value}。
    """
    plan = {"exec_date": exec_date, "sells": [], "buys": [],
            "skipped_sells": [], "skipped_buys": []}
    # 组合权益（执行日开盘价估值；停牌股用最近收盘价）
    equity = portfolio.cash
    for code, shares in portfolio.holdings.items():
        px = exec_open.get(code)
        equity += shares * (px if px is not None else portfolio.last_prices[code])
    target_value = equity / len(targets)

    # 1) 卖出不在目标内的持仓（停牌不卖）
    for code in list(portfolio.holdings):
        if code in targets:
            continue
        px = exec_open.get(code)
        if px is None:
            plan["skipped_sells"].append(code)
            continue
        plan["sells"].append((code, portfolio.holdings[code], px))

    # 2) 目标持仓调到等权（停牌不动）
    for code in targets:
        px = exec_open.get(code)
        if px is None:
            plan["skipped_buys"].append(code)
            continue
        current = portfolio.holdings.get(code, 0.0)
        want = np.floor(target_value / px)   # 整数股，误差 ≤ 1 股
        if want > current:
            plan["buys"].append((code, want - current, px))
        elif want < current:
            plan["sells"].append((code, current - want, px))
    return plan


def run_backtest(strategy, start: str, end: str, *, top_n: int = 10,
                 rebalance_every: int = 20, cost_rate: float = 0.001,
                 initial_cash: float = INITIAL_CASH, loader: MarketDataLoader = None,
                 benchmark: bool = True) -> BacktestResult:
    """在 [start, end] 历史区间上回测 Strategy A：每 rebalance_every 个交易日调仓。

    - 调仓日收盘用 run_strategy(as_of=d) 排名（只使用 <= d 的数据），Top N 等权；
    - 成交在次一交易日开盘价（停牌不成交）；持仓每日收盘估值（停牌 ffill）；
    - 基准 = 沪深300 价格指数（区间首日归一化到 1）。
    """
    loader = loader or MarketDataLoader()
    warnings = []
    start = str(start).replace("-", "")
    end = str(end).replace("-", "")
    if start >= end:
        raise ValueError(f"回测开始日期 {start} 必须早于结束日期 {end}")
    if top_n < 1:
        raise ValueError("top_n 必须 >= 1")
    if rebalance_every < 1:
        raise ValueError("rebalance_every 必须 >= 1")
    if not (0.0 <= cost_rate < 1.0):
        raise ValueError("cost_rate 必须在 [0, 1) 区间")

    # 1) 整段行情一次读入（收盘估值 + 次日开盘成交价）；交易日 = 数据中实际存在的日期
    market = loader.load_market_data(start, end, columns=PRICE_COLUMNS)
    if market is None or market.empty:
        raise ValueError(f"回测区间 {start} ~ {end} 无个股行情数据，请先更新数据")
    market = market[market["trade_date"] <= end]   # loader 语义兜底（区间裁剪）
    dates = sorted(market["trade_date"].unique())
    if dates[-1] < end:
        _append_warning(warnings, f"数据最新交易日 {dates[-1]} 早于结束日期 {end}，回测实际截止到 {dates[-1]}")
    if len(dates) < 2:
        raise ValueError("回测区间不足 2 个交易日（至少需要调仓日 + 次日成交日）")
    price_table = PriceTable(market)
    del market

    # 2) 基准：沪深300 收盘价归一化
    bench_map = {}
    if benchmark:
        idx = loader.load_index(start, end)
        if idx is None or idx.empty:
            _append_warning(warnings, "沪深300 指数数据为空，本次回测不做基准比较")
            benchmark = False
        else:
            idx = idx.sort_values("trade_date")
            first_close = None
            for _, row in idx.iterrows():
                if row["trade_date"] >= dates[0]:
                    first_close = float(row["close"])
                    break
            if first_close is None or first_close <= 0:
                _append_warning(warnings, "回测区间内无沪深300 指数数据，不做基准比较")
                benchmark = False
            else:
                bench_map = {d: float(c) / first_close
                             for d, c in zip(idx["trade_date"], idx["close"])}

    # 3) 主循环：调仓日在 d 收盘计划，次一交易日执行（开盘价），每日收盘估值
    portfolio = Portfolio(cash=initial_cash, cost_rate=cost_rate)
    rebalance_positions = set(range(0, len(dates), rebalance_every))
    pending = None                      # 上一调仓日生成的计划（在本日开盘执行）
    rebalance_rows, nav_rows = [], []
    names = loader.stock_names()
    ranking_count = 0

    for i, d in enumerate(dates):
        # 3a) 先执行上一调仓日的计划（其 exec_date == d，价格 = d 的开盘价）
        if pending is not None:
            for code, shares, px in pending["sells"]:
                portfolio.sell(pending["exec_date"], code, px, shares)
            for code, shares, px in pending["buys"]:
                t = portfolio.buy(pending["exec_date"], code, px, shares)
                if t is None:   # 计划买入因现金不足（如卖出停牌被跳过）未成交，如实记录
                    _append_warning(warnings,
                                    f"[{pending['rebalance_date']}] {code} 买入未成交（现金不足）")
            day_trades = [t for t in portfolio.trades
                          if t.date == pending["exec_date"]]
            rebalance_rows.append({
                "rebalance_date": pending["rebalance_date"],
                "exec_date": pending["exec_date"],
                "buys": sum(1 for t in day_trades if t.action == "buy"),
                "sells": sum(1 for t in day_trades if t.action == "sell"),
                "buy_skipped": len(pending["skipped_buys"]),
                "sell_skipped": len(pending["skipped_sells"]),
                "turnover": sum(t.value for t in day_trades),
                "cash": portfolio.cash,
                "equity": portfolio.value(),
            })
            pending = None

        # 3b) 调仓日：收盘后按 <= d 的数据排名，生成次日计划
        #     注意：本块不使用 continue——估值(3c)必须每天执行
        if i in rebalance_positions:
            ranking_count += 1
            try:
                result = run_strategy(strategy, as_of=d, loader=loader)
            except Exception as e:      # 数据边界（如指数缺失）不中断整个回测
                _append_warning(warnings, f"[{d}] 排名计算失败，跳过本次调仓: {e}")
                result = None
            if result is not None:
                for wmsg in result.warnings[:MAX_RANKING_WARNINGS]:
                    _append_warning(warnings, f"[{d}] {wmsg}")
                if result.universe_size == 0:
                    _append_warning(warnings, f"[{d}] 股票池为空（无当日行情或因子数据不足），跳过调仓")
                elif i + 1 >= len(dates):
                    _append_warning(warnings, f"[{d}] 是区间最后一个交易日，无次日行情可执行，跳过调仓")
                else:
                    ranking = result.ranking.sort_values(["rank", "ts_code"])
                    targets = ranking["ts_code"].head(top_n).tolist()
                    exec_date = dates[i + 1]
                    involved = set(targets) | set(portfolio.holdings)
                    exec_open = {c: price_table.open_on(c, exec_date) for c in involved}
                    plan = _plan_rebalance(portfolio, targets, exec_date,
                                           exec_open, top_n, warnings)
                    for code in plan["skipped_sells"]:
                        _append_warning(warnings, f"[{d}] {code} 执行日停牌，卖出跳过（继续持有）")
                    for code in plan["skipped_buys"]:
                        _append_warning(warnings, f"[{d}] {code} 执行日停牌，买入跳过（现金保留）")
                    plan.update({"rebalance_date": d})
                    pending = plan

        # 3c) 每日收盘估值（停牌 ffill）
        prices = {code: price_table.close_on(code, d) for code in portfolio.holdings}
        portfolio.mark(prices)
        nav_row = {"trade_date": d, "nav": portfolio.value() / initial_cash}
        if benchmark and d in bench_map:
            nav_row["benchmark"] = bench_map[d]
        nav_rows.append(nav_row)

    nav = pd.DataFrame(nav_rows, columns=["trade_date", "nav"] + (["benchmark"] if benchmark else []))
    if rebalance_rows:
        rebalances = pd.DataFrame(rebalance_rows)
    else:
        rebalances = pd.DataFrame(columns=[
            "rebalance_date", "exec_date", "buys", "sells",
            "buy_skipped", "sell_skipped", "turnover", "cash", "equity"])
    rb_map = {r["exec_date"]: r["rebalance_date"] for r in rebalance_rows}
    if portfolio.trades:
        trades = pd.DataFrame([{
            "exec_date": t.date, "rebalance_date": rb_map.get(t.date, ""),
            "ts_code": t.ts_code, "name": names.get(t.ts_code, t.ts_code),
            "action": t.action, "shares": t.shares, "price": t.price,
            "cost": t.cost, "value": t.value,
        } for t in portfolio.trades])
    else:
        trades = pd.DataFrame(columns=[
            "exec_date", "rebalance_date", "ts_code", "name",
            "action", "shares", "price", "cost", "value"])

    # 4) 指标（胜率 = 相邻调仓执行日收盘净值之比为正的期数占比；首期为首个执行日对期初）
    exec_dates = rebalances["exec_date"].tolist()
    nav_map = dict(zip(nav["trade_date"], nav["nav"]))
    period_returns = []
    if exec_dates:
        period_returns.append(nav_map[exec_dates[0]] - 1.0)
        for k in range(1, len(exec_dates)):
            period_returns.append(nav_map[exec_dates[k]] / nav_map[exec_dates[k - 1]] - 1.0)
    metrics = {
        "portfolio": {
            "cumulative_return": cumulative_return(nav["nav"]),
            "annualized_return": annualized_return(nav["nav"]),
            "max_drawdown": max_drawdown(nav["nav"]),
        },
        "benchmark": (None if not benchmark else {
            "cumulative_return": cumulative_return(nav["benchmark"]),
            "annualized_return": annualized_return(nav["benchmark"]),
            "max_drawdown": max_drawdown(nav["benchmark"]),
        }),
        "win_rate": win_rate(pd.Series(period_returns, dtype="float64")),
        "periods": len(period_returns),
        "excess_return": (None if not benchmark
                          else cumulative_return(nav["nav"]) - cumulative_return(nav["benchmark"])),
        "trading_days": len(nav),
        "rebalances": ranking_count,
    }

    return BacktestResult(
        start=dates[0], end=dates[-1],
        params={
            "strategy": strategy.name,
            "weights": dict(strategy.weights),
            "windows": {k: list(v) for k, v in strategy.windows.items()},
            "standardize_method": strategy.standardize_method,
            "universe": "PIT（当日有行情即在池，不用当前 stock_list.csv）",
            "use_stock_list": bool(strategy.use_stock_list),
            "top_n": top_n,
            "rebalance_every": rebalance_every,
            "cost_rate": cost_rate,
            "execution": "next_open（次一交易日开盘价）",
            "initial_cash": initial_cash,
        },
        data_version=_data_fingerprint(loader),
        nav=nav,
        rebalances=rebalances,
        trades=trades,
        metrics=metrics,
        warnings=warnings,
    )
