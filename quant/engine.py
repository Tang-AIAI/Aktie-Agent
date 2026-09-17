"""策略执行引擎：数据切片 → 因子计算 → 横截面标准化 → 方向调整 → 加权合成 → 排名。

所有策略共用本流程；Strategy 只声明配置（因子/权重/窗口）。
流程（对计算日 as_of 的横截面）：
1. 按最大窗口换算自然日区间，只加载该区间的个股行情（列裁剪）；
   指数行情仅在策略含 needs_index 因子时加载（否则不依赖、不校验）；
2. 逐因子计算原始值（数据不足为 NaN）；
3. 股票池过滤：无当日行情（停牌/退市）或任一因子 NaN 的股票排除，
   并按策略配置限定在 stock_list.csv 股票列表内（先过滤后标准化：
   横截面 = 进入排名的股票池，被排除的股票不参与均值/标准差）；
   策略 use_stock_list=False 时跳过列表限定（历史回测的 PIT 股票池）；
4. 横截面标准化（默认 z-score），"越低越好"因子乘 -1 反转方向；
5. Score = Σ(标准化因子 × 权重)，按 Score 降序排名。
"""

from dataclasses import dataclass, field

import pandas as pd

from quant.cross_section import direction_sign, standardize
from quant.factors.registry import get_compute, get_factor
from quant.market_data import MarketDataLoader

# 最大窗口换算成自然日的放大系数 + 缓冲（覆盖停牌/节假日造成的交易日缺口）
LOOKBACK_CALENDAR_RATIO = 1.7
LOOKBACK_CALENDAR_BUFFER = 20


@dataclass
class RankingResult:
    as_of: str                          # 实际使用的计算日 YYYYMMDD
    universe_size: int                  # 进入排名的股票数
    excluded_count: int                 # 加载范围内被排除的股票数
    ranking: pd.DataFrame               # rank, ts_code, name, score, {factor}_score, {factor}_raw, last_date
    weights: dict                       # 归一化后的权重（和为 1）
    windows: dict                       # 实际使用的窗口参数
    method: str                         # 标准化方法
    warnings: list = field(default_factory=list)


def run_strategy(strategy, as_of: str = None, loader: MarketDataLoader = None) -> RankingResult:
    """按策略配置在 as_of 交易日执行全流程，返回排名结果。"""
    loader = loader or MarketDataLoader()
    warnings = []
    if not strategy.data_available:
        # 设计壳策略（如 Value/Quality 缺数据）：拒绝运行而非产出虚假排名
        raise ValueError(f"策略 {strategy.name} 暂不可运行：{strategy.unavailable_reason}")
    if as_of is None:
        as_of = str(loader.latest_trade_date())
    else:
        as_of = str(as_of).replace("-", "")

    max_window = max(w for ws in strategy.windows.values() for w in ws)
    lookback_days = int(max_window * LOOKBACK_CALENDAR_RATIO) + LOOKBACK_CALENDAR_BUFFER
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=lookback_days)).strftime("%Y%m%d")

    # 1) 数据切片（不读全量历史）
    market = loader.load_market_data(start, as_of)
    if market is None or market.empty:
        raise ValueError(f"个股数据为空（{start} ~ {as_of}），请先运行 scripts/update_stock_data.py")
    data_max = str(market["trade_date"].max())
    if data_max < as_of:
        warnings.append(f"数据最新日期 {data_max} 早于所选日期 {as_of}，已改用 {data_max}")
        as_of = data_max
        market = market[market["trade_date"] <= as_of]

    # 仅当策略含有依赖指数的因子时才加载并校验指数；无指数依赖的策略
    # （如 D/E/F）可在指数数据覆盖范围之外的历史区间运行
    index = None
    if any(get_factor(f).needs_index for f in strategy.factor_names):
        index = loader.load_index(start, as_of)
        if index is None or index.empty:
            raise ValueError("沪深300 指数数据为空，请先运行 scripts/update_index_data.py")

    names = loader.stock_names()

    total_stocks = market["ts_code"].nunique()
    last_dates = market.groupby("ts_code")["trade_date"].max()

    # 2) 因子原始值计算（数据不足为 NaN）
    raw_map = {
        fname: get_compute(fname)(market, strategy.windows[fname], index=index, as_of=as_of)
        for fname in strategy.factor_names
    }

    # 3) 股票池过滤（先于标准化：横截面 = 进入排名的股票池）
    frame = pd.DataFrame({"ts_code": last_dates.index, "last_date": last_dates.values})
    for fname in strategy.factor_names:
        frame[f"{fname}_raw"] = frame["ts_code"].map(raw_map[fname])
    if strategy.require_as_of_row:
        frame = frame[frame["last_date"] == as_of]
    if strategy.drop_na_factors:
        frame = frame.dropna(subset=[f"{n}_raw" for n in strategy.factor_names])
    if names and strategy.use_stock_list:
        # 排名股票池限定在 stock_list.csv；列表不可用时跳过该限制。
        # 历史回测置 use_stock_list=False：以"当日有行情"为 PIT 在场条件，
        # 不用当前列表排除历史退市股（避免幸存者偏差）。
        frame = frame[frame["ts_code"].isin(names)]
    if frame.empty:
        warnings.append("股票池为空：没有股票同时满足当日行情与全部因子可计算")

    # 4) 横截面标准化（股票池内）+ 方向调整
    for fname in strategy.factor_names:
        spec = get_factor(fname)
        frame[f"{fname}_score"] = (
            standardize(frame[f"{fname}_raw"], strategy.standardize_method)
            * direction_sign(spec.direction))

    # 5) 加权合成 + 排名
    frame["score"] = sum(strategy.weights[f] * frame[f"{f}_score"] for f in strategy.factor_names)
    frame["rank"] = frame["score"].rank(ascending=False, method="min").astype(int)
    frame["name"] = frame["ts_code"].map(lambda c: names.get(c, c))
    frame = frame.sort_values("rank")

    cols = (["rank", "ts_code", "name", "score"]
            + [f"{n}_score" for n in strategy.factor_names]
            + [f"{n}_raw" for n in strategy.factor_names]
            + ["last_date"])
    return RankingResult(
        as_of=as_of,
        universe_size=len(frame),
        excluded_count=total_stocks - len(frame),
        ranking=frame[cols].reset_index(drop=True),
        weights=dict(strategy.weights),
        windows={k: v for k, v in strategy.windows.items()},
        method=strategy.standardize_method,
        warnings=warnings,
    )
