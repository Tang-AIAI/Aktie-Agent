"""条件选股引擎：指标表计算 + 条件求值（纯逻辑，可单元测试，不依赖 Streamlit）。

指标口径与 Strategy A 因子保持一致（ret60/volatility/vol_ratio/rs_hs300 直接复用
quant/factors 的计算函数），均基于前复权价；页面只负责把 UI 条件翻译成
condition dict 后调用 evaluate()。
"""

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from quant.factors import momentum, relative_strength, volatility, volume_trend
from quant.market_data import MarketDataLoader

LOOKBACK_CALENDAR_RATIO = 1.7
LOOKBACK_CALENDAR_BUFFER = 20


@dataclass(frozen=True)
class Indicator:
    """一个选股指标：名称/展示名/口径说明/所需窗口/是否需要指数。"""
    name: str
    label: str
    description: str
    window: int = 1          # 所需最大回看交易日数（决定数据切片长度）
    needs_index: bool = False
    compute: Callable = None  # (market, index, as_of) -> pd.Series[ts_code]


def _last(column: str):
    def f(market, index, as_of):
        return market.groupby("ts_code", sort=False)[column].last()
    return f


def _ma(n: int):
    def f(market, index, as_of):
        df = market.sort_values(["ts_code", "trade_date"])
        m = df.groupby("ts_code", sort=False)["close_adj"].transform(
            lambda s: s.rolling(n, min_periods=n).mean())
        return m.groupby(df["ts_code"], sort=False).last()
    return f


def _vol_avg(n: int):
    def f(market, index, as_of):
        df = market.sort_values(["ts_code", "trade_date"])
        m = df.groupby("ts_code", sort=False)["vol"].transform(
            lambda s: s.rolling(n, min_periods=n).mean())
        return m.groupby(df["ts_code"], sort=False).last()
    return f


INDICATORS = {
    "close": Indicator("close", "收盘价（前复权）", "最新前复权收盘价", window=1,
                       compute=_last("close_adj")),
    "ma5": Indicator("ma5", "MA5", "前复权收盘价 5 日移动平均", window=5, compute=_ma(5)),
    "ma20": Indicator("ma20", "MA20", "前复权收盘价 20 日移动平均", window=20, compute=_ma(20)),
    "ma60": Indicator("ma60", "MA60", "前复权收盘价 60 日移动平均", window=60, compute=_ma(60)),
    "ma120": Indicator("ma120", "MA120", "前复权收盘价 120 日移动平均", window=120, compute=_ma(120)),
    "ret20": Indicator("ret20", "20日收益率", "close_adj_T / close_adj_{T-20} - 1（与 Strategy A 动量同口径）",
                       window=21, compute=lambda m, idx, asof: momentum.compute(m, (20,))),
    "ret60": Indicator("ret60", "60日收益率", "close_adj_T / close_adj_{T-60} - 1（与 Strategy A 动量同口径）",
                       window=61, compute=lambda m, idx, asof: momentum.compute(m, (60,))),
    "vol20avg": Indicator("vol20avg", "20日平均成交量", "成交量 20 日移动平均", window=20,
                          compute=_vol_avg(20)),
    "vol60avg": Indicator("vol60avg", "60日平均成交量", "成交量 60 日移动平均", window=60,
                          compute=_vol_avg(60)),
    "vol_ratio": Indicator("vol_ratio", "成交量比", "20 日均量 / 60 日均量（与 Strategy A 同口径）",
                           window=60, compute=lambda m, idx, asof: volume_trend.compute(m, (20, 60))),
    "volatility": Indicator("volatility", "波动率", "20 日日收益率样本标准差（与 Strategy A 同口径）",
                            window=21, compute=lambda m, idx, asof: volatility.compute(m, (20,))),
    "rs_hs300": Indicator("rs_hs300", "与沪深300相对强度",
                          "个股 60 日收益率 − 沪深300 60 日收益率（原始值，未标准化）",
                          window=61, needs_index=True,
                          compute=lambda m, idx, asof: relative_strength.compute(
                              m, (60,), index=idx, as_of=asof)),
}


def get_indicator(name: str) -> Indicator:
    if name not in INDICATORS:
        raise KeyError(f"未注册的指标: {name}（已注册: {sorted(INDICATORS)}）")
    return INDICATORS[name]


@dataclass
class IndicatorTable:
    as_of: str
    table: pd.DataFrame   # index=ts_code；列：last_date, close_raw, name + 请求的指标
    warnings: list = field(default_factory=list)


def compute_indicators(as_of: str = None, indicators=("close",),
                       loader: MarketDataLoader = None) -> IndicatorTable:
    """计算指标表：与引擎同口径——区间+列裁剪读数据、股票池 = 有当日行情 ∩ stock_list。

    indicators 中任一指标未注册会抛 KeyError；数据不足的指标值为 NaN（
    条件求值时按"不满足"处理，见 evaluate）。
    """
    loader = loader or MarketDataLoader()
    warnings = []
    if as_of is None:
        as_of = str(loader.latest_trade_date())
    else:
        as_of = str(as_of).replace("-", "")

    specs = [get_indicator(n) for n in indicators]
    max_window = max(s.window for s in specs)
    start = (pd.Timestamp(as_of)
             - pd.Timedelta(days=int(max_window * LOOKBACK_CALENDAR_RATIO) + LOOKBACK_CALENDAR_BUFFER)
             ).strftime("%Y%m%d")

    market = loader.load_market_data(start, as_of,
                                     columns=("ts_code", "trade_date", "close", "close_adj", "vol"))
    if market is None or market.empty:
        raise ValueError(f"个股数据为空（{start} ~ {as_of}），请先运行数据更新")
    data_max = str(market["trade_date"].max())
    if data_max < as_of:
        warnings.append(f"数据最新日期 {data_max} 早于所选日期 {as_of}，已改用 {data_max}")
        as_of = data_max
        market = market[market["trade_date"] <= as_of]

    index = loader.load_index(start, as_of) if any(s.needs_index for s in specs) else None
    if index is not None and index.empty:
        raise ValueError("沪深300 指数数据为空，请先运行 scripts/update_index_data.py")

    last_dates = market.groupby("ts_code")["trade_date"].max()
    frame = pd.DataFrame({"last_date": last_dates.values}, index=last_dates.index)
    frame = frame[frame["last_date"] == as_of]     # 无当日行情（停牌/退市）排除
    for spec in specs:
        frame[spec.name] = spec.compute(market, index, as_of)

    frame["close_raw"] = market.groupby("ts_code", sort=False)["close"].last()
    names = loader.stock_names()
    if names:                                      # 股票池限定在 stock_list.csv
        frame = frame[frame.index.isin(names)]
    frame["name"] = [names.get(c, c) for c in frame.index]

    table = frame[["last_date", "close_raw", "name"] + [s.name for s in specs]].sort_index()
    return IndicatorTable(as_of=as_of, table=table, warnings=warnings)


# ------------------------------------------------------------------ 条件求值
_OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    # 浮点等值比较用 1e-9 相对容差（= / != 对纯浮点指标意义有限，建议优先 > / <）
    "=": lambda a, b: np.isclose(a, b, rtol=1e-9, atol=0),
    "!=": lambda a, b: ~np.isclose(a, b, rtol=1e-9, atol=0),
}


def _right_series(table: pd.DataFrame, right: dict) -> pd.Series:
    if right["kind"] == "value":
        return pd.Series(float(right["value"]), index=table.index)
    if right["kind"] == "indicator":
        name = right["name"]
        if name not in table.columns:
            raise ValueError(f"指标表缺少列: {name}")
        return table[name]
    raise ValueError(f"未知右值类型: {right}")


def evaluate(table: pd.DataFrame, conditions: list) -> pd.Series:
    """按顺序求值条件列表，返回以 table 索引为准的布尔 Series。

    每个 condition dict：
      {"left": 指标名, "op": 运算符, "right": {"kind":"value","value":数值}
          | {"kind":"indicator","name":指标名}, "negate": bool, "connector": "AND"/"OR"}
    第一条的 connector 被忽略；其后每条与已有结果按 connector 组合（自左向右，
    无运算优先级，UI 中已注明）。指标值为 NaN 的比较结果保持 NaN（NOT 也保持
    NaN），最终未参与有效比较的股票一律排除——避免"数据不足却通过 NOT 条件"。
    """
    if not conditions:
        raise ValueError("条件列表为空")
    mask = None
    for i, cond in enumerate(conditions):
        left_name = cond["left"]
        if left_name not in table.columns:
            raise ValueError(f"指标表缺少列: {left_name}")
        op = _OPS.get(cond["op"])
        if op is None:
            raise ValueError(f"未知运算符: {cond['op']}")
        left, right = table[left_name], _right_series(table, cond["right"])
        cmp_result = op(left, right)
        # pandas 比较会把 NaN 当 False；这里显式改为：任一侧为 NaN → NA。
        # nullable boolean dtype（Kleene 逻辑）：~NA 保持 NA，避免 NaN 经 NOT 放行。
        na_mask = left.isna() | right.isna()
        cmp_result = (pd.Series(cmp_result, index=table.index)
                      .astype("boolean").mask(na_mask, pd.NA))
        if cond.get("negate"):
            cmp_result = ~cmp_result
        connector = cond.get("connector")
        if i == 0:
            mask = cmp_result
        elif connector == "AND":
            mask = mask & cmp_result
        elif connector == "OR":
            mask = mask | cmp_result
        else:
            raise ValueError(f"未知连接符: {connector}（可选 AND / OR）")
    return mask.fillna(False)
