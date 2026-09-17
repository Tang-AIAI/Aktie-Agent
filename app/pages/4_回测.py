"""策略历史回测页：选择策略（A~F）→ 参数输入 → 运行回测 → 指标 + 净值曲线 + 调仓记录。

页面只负责 UI（策略选择、参数输入、触发计算、结果展示），回测逻辑全部在 quant/backtest/：
- 主循环/防未来数据泄漏口径：quant/backtest/runner.py
- 指标：quant/backtest/metrics.py；账本：quant/backtest/portfolio.py
- 排名复用现有 quant/engine（PIT 股票池：use_stock_list=False）

所有策略走同一流程：strategy → factors → 横截面打分 → 排名 → 回测。
数据不足的策略（Strategy B/C）在页面明确显示原因，不运行、不产生误导性结果。
结果仅供量化研究参考，不构成投资建议。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import altair as alt
import pandas as pd
import streamlit as st

from app.common import data_version
from quant.backtest.runner import run_backtest
from quant.factors.registry import get_factor
from quant.market_data import MarketDataLoader
from quant.strategies import all_strategies, get_strategy

st.set_page_config(page_title="回测 · 策略库", page_icon="🧪", layout="wide")

STRATEGY_BY_NAME = {s.name: s for s in all_strategies()}
# 沪深300 指数数据起点 2002-01-04 + 60 交易日因子窗口缓冲 → 最早可用回测起点
EARLIEST_START = pd.Timestamp("20020501")
INITIAL_CASH = 1_000_000.0


def _strategy_label(name: str) -> str:
    cls = STRATEGY_BY_NAME[name]
    return cls.label + ("" if cls.data_available else "（数据不足）")


# ---------------------------------------------------------------- 回测（带缓存）
@st.cache_data(show_spinner="正在运行回测…")
def _run(strategy_name: str, start: str, end: str, top_n: int, period: int,
         cost_pct: float, weights: tuple, windows: tuple, dv: str):
    """参数以 tuple 传入保证可哈希；键含数据版本，数据更新后缓存自动失效。"""
    cls = get_strategy(strategy_name)
    strategy = cls(weights=dict(weights), windows=dict(windows),
                   use_stock_list=False)
    return run_backtest(strategy, start, end, top_n=top_n, rebalance_every=period,
                        cost_rate=cost_pct / 100.0)


def _direction_text(direction: str) -> str:
    return "越高越好 ↑" if direction == "higher_better" else "越低越好 ↓"


loader = MarketDataLoader()
try:
    latest = loader.latest_trade_date()
except Exception as e:
    st.error(f"无法读取数据文件：{e}\n\n请先运行 `scripts/update_stock_data.py`。")
    st.stop()

# ---------------------------------------------------------------- 侧边栏参数
st.sidebar.title("策略历史回测")
st.sidebar.caption(
    "在历史区间上模拟：每 N 个交易日收盘按所选策略排名调仓，"
    "Top N 等权、次一交易日开盘价成交（停牌不成交）。")
st.sidebar.caption("首次运行约 3~6 分钟（近 5 年），参数不变时重复运行即时返回缓存。")

strategy_name = st.sidebar.selectbox(
    "策略（A~F，统一回测流程）", list(STRATEGY_BY_NAME),
    format_func=_strategy_label, index=0)
strategy_cls = STRATEGY_BY_NAME[strategy_name]
st.sidebar.caption(strategy_cls.description)

start_date = st.sidebar.date_input(
    "开始日期（默认近 5 年）",
    value=pd.Timestamp(latest) - pd.Timedelta(days=365 * 5),
    min_value=EARLIEST_START, max_value=pd.Timestamp(latest))
end_date = st.sidebar.date_input(
    "结束日期（默认最新交易日）",
    value=pd.Timestamp(latest),
    min_value=EARLIEST_START, max_value=pd.Timestamp(latest))
top_n = st.sidebar.number_input("Top N（等权持仓数）", min_value=1, max_value=100,
                                value=10, step=5)
period = st.sidebar.number_input("调仓周期（交易日）", min_value=1, max_value=250,
                                 value=20, step=5)
cost_pct = st.sidebar.number_input("单边交易成本（%）", min_value=0.0, max_value=1.0,
                                   value=0.1, step=0.05, format="%.2f")

factors = [get_factor(f) for f in strategy_cls.factor_names]
weights_in, windows_in = {}, {}
if strategy_cls.data_available:
    st.sidebar.subheader("因子参数（Baseline 默认值，非最优）")
    for spec in factors:
        st.sidebar.markdown(f"**{spec.label}** · {_direction_text(spec.direction)}")
        default_w = strategy_cls.default_weights.get(spec.name, 0)
        if len(spec.default_windows) == 2:      # 双窗口因子（量能趋势/趋势）
            short = st.sidebar.number_input(
                "短期窗口（日）", min_value=2, value=spec.default_windows[0], step=5,
                key=f"bt_{strategy_name}_{spec.name}_short")
            long = st.sidebar.number_input(
                "长期窗口（日）", min_value=2, value=spec.default_windows[1], step=5,
                key=f"bt_{strategy_name}_{spec.name}_long")
            windows_in[spec.name] = (short, long)
        else:
            w = st.sidebar.number_input(
                "窗口（日）", min_value=2, value=spec.default_windows[0], step=5,
                key=f"bt_{strategy_name}_{spec.name}")
            windows_in[spec.name] = (w,)
        weights_in[spec.name] = st.sidebar.number_input(
            f"{spec.short_label or spec.label} 权重（%）", min_value=0, max_value=100,
            value=round(default_w * 100), step=5,
            key=f"bt_{strategy_name}_{spec.name}_w")

weight_sum = sum(weights_in.values())
weight_ok = abs(weight_sum - 100.0) < 1e-9 if strategy_cls.data_available else False
window_ok = all(w[0] < w[1] for w in windows_in.values() if len(w) == 2)
dates_ok = end_date > start_date
if strategy_cls.data_available:
    if not weight_ok:
        st.sidebar.warning(f"权重合计 {weight_sum:.0f}%，必须等于 100% 才能运行。")
    if not window_ok:
        st.sidebar.warning("双窗口因子的短期窗口必须小于长期窗口。")
    st.sidebar.caption("权重合计：**{:.0f}%**".format(weight_sum))
else:
    st.sidebar.error(strategy_cls.unavailable_reason)
if not dates_ok:
    st.sidebar.warning("结束日期必须晚于开始日期。")

run = st.sidebar.button(
    "运行回测", type="primary",
    disabled=not (strategy_cls.data_available and weight_ok and window_ok and dates_ok))
if run:
    st.session_state["bt_result"] = _run(
        strategy_name,
        start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"),
        top_n, period, cost_pct,
        tuple(weights_in.items()),
        tuple((n, ws) for n, ws in windows_in.items()),
        data_version(loader))
result = st.session_state.get("bt_result")

# ---------------------------------------------------------------- 主区域
st.title("策略历史回测")
st.caption(f"{strategy_cls.label} · {strategy_cls.description}")
st.caption("回测结果仅供量化研究参考，不构成投资建议。")

if not strategy_cls.data_available:
    st.error(strategy_cls.unavailable_reason)
    st.info("该策略的设计说明与数据依赖见 PROJECT_CONTEXT.md「策略库」一节。"
            "接入可靠的历史 PIT 数据前不运行、不产生回测结果。")
    st.stop()

if strategy_name == "strategy_a":
    st.warning(
        "当前 Strategy A 的 Momentum 与 Relative Strength 横截面 score 恒等，"
        "因此实际综合权重相当于 Momentum 50%、Volatility 25%、Volume Trend 25%。"
        "（已记录为 Strategy A v2 改进点，本回测按现行定义执行。）")

if result is None:
    st.info("在左侧选择策略、设置回测区间与参数后，点击「运行回测」查看结果。")
    st.stop()

for wmsg in result.warnings[:15]:
    st.warning(wmsg)
if len(result.warnings) > 15:
    st.caption(f"…共 {len(result.warnings)} 条警告，其余略。")

nav = result.nav
m = result.metrics
p_m = m["portfolio"]
b_m = m["benchmark"]


def _fmt(v):
    return "—" if v is None or pd.isna(v) else f"{v:+.2%}"


# ---------------------------------------------------------------- 指标卡片
st.subheader("回测指标")
c1, c2, c3, c4 = st.columns(4)
c1.metric("累计收益率", _fmt(p_m["cumulative_return"]))
c2.metric("年化收益率（252 日）", _fmt(p_m["annualized_return"]))
c3.metric("最大回撤", "—" if p_m["max_drawdown"] is None
          else f"{p_m['max_drawdown']:.2%}")
c4.metric("胜率（调仓期）", "—" if pd.isna(m["win_rate"])
          else f"{m['win_rate']:.1%}",
          help="调仓周期收益 > 0 的期数占比；期收益 = 相邻两次调仓执行日收盘净值之比 − 1，"
               "首期为首个执行日相对期初。")

st.caption(f"区间 {result.start} ~ {result.end} · {m['trading_days']} 个交易日 · "
           f"{len(result.rebalances)} 次调仓 · {m['periods']} 期 · "
           f"初始资金 {INITIAL_CASH:,.0f} · 数据版本 {result.data_version}")

if b_m is not None:
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("沪深300 累计", _fmt(b_m["cumulative_return"]))
    b2.metric("沪深300 年化", _fmt(b_m["annualized_return"]))
    b3.metric("沪深300 最大回撤", f"{b_m['max_drawdown']:.2%}")
    b4.metric("超额收益（组合 − 基准）", _fmt(m["excess_return"]))
else:
    st.info("本次回测无基准对比：回测区间内无沪深300 指数数据。")

# ---------------------------------------------------------------- 净值曲线
st.subheader("净值曲线（期初 = 1.0）")
chart_data = nav[["trade_date", "nav"]].rename(
    columns={"trade_date": "日期", "nav": "净值"})
chart_data["系列"] = "组合"
if b_m is not None and "benchmark" in nav.columns:
    bench = nav[["trade_date", "benchmark"]].rename(
        columns={"trade_date": "日期", "benchmark": "净值"})
    bench["系列"] = "沪深300"
    chart_data = pd.concat([chart_data, bench], ignore_index=True)
chart_data["日期"] = pd.to_datetime(chart_data["日期"], format="%Y%m%d")

dark = st.get_option("theme.base") == "dark"
# 分类色第 1/2 槽（蓝/橙，明暗模式均通过可访问性校验）：组合蓝、基准橙
port_color, bench_color = ("#2a78d6", "#eb6834") if not dark else ("#3987e5", "#d95926")

scale = alt.Scale(domain=["组合", "沪深300"] if b_m is not None else ["组合"],
                  range=[port_color] + ([bench_color] if b_m is not None else []))
line = alt.Chart(chart_data).mark_line(strokeWidth=2).encode(
    x=alt.X("日期:T", axis=alt.Axis(title=None, format="%Y-%m", grid=False,
                                     labelColor="#898781")),
    y=alt.Y("净值:Q", axis=alt.Axis(title=None, gridColor="#e1e0d9", labelColor="#898781"),
            scale=alt.Scale(zero=False)),
    color=alt.Color("系列:N", scale=scale,
                    legend=alt.Legend(orient="top", title=None)),
    tooltip=[alt.Tooltip("日期:T", format="%Y-%m-%d"),
             alt.Tooltip("系列:N"), alt.Tooltip("净值:Q", format=".4f")],
)
# 线尾直接标注（选择性标签，标识不依赖颜色）
end_labels = (
    alt.Chart(chart_data.groupby("系列", as_index=False).tail(1))
    .mark_text(align="left", dx=6, color="#898781")
    .encode(x="日期:T", y="净值:Q", text=alt.Text("系列:N"))
)
st.altair_chart(line + end_labels, width="stretch")

# ---------------------------------------------------------------- 调仓记录
st.subheader("历史调仓记录")
if result.rebalances.empty:
    st.info("区间内未产生任何调仓（可能股票池持续为空）。")
else:
    rb = result.rebalances.copy()
    rb["组合净值"] = rb["exec_date"].map(
        dict(zip(nav["trade_date"], nav["nav"])))
    disp = rb.rename(columns={
        "rebalance_date": "排名日", "exec_date": "执行日",
        "buys": "买入(只)", "sells": "卖出(只)",
        "buy_skipped": "买跳(停牌)", "sell_skipped": "卖跳(停牌)",
        "turnover": "换手金额", "cash": "现金", "equity": "执行后权益",
    })[["排名日", "执行日", "买入(只)", "卖出(只)", "买跳(停牌)", "卖跳(停牌)",
        "换手金额", "现金", "执行后权益", "组合净值"]]
    st.dataframe(disp, hide_index=True, width="stretch", column_config={
        "换手金额": st.column_config.NumberColumn(format="%.0f"),
        "现金": st.column_config.NumberColumn(format="%.2f"),
        "执行后权益": st.column_config.NumberColumn(format="%.2f"),
        "组合净值": st.column_config.NumberColumn(format="%.4f"),
    })

with st.expander(f"逐笔成交（共 {len(result.trades)} 笔）"):
    if result.trades.empty:
        st.info("无成交记录。")
    else:
        td = result.trades.rename(columns={
            "exec_date": "执行日", "rebalance_date": "排名日",
            "ts_code": "代码", "name": "名称", "action": "方向",
            "shares": "份额", "price": "价格", "cost": "成本", "value": "金额"})
        td["方向"] = td["方向"].map({"buy": "买入", "sell": "卖出"})
        st.dataframe(td, hide_index=True, width="stretch", column_config={
            "份额": st.column_config.NumberColumn(format="%.0f"),
            "价格": st.column_config.NumberColumn(format="%.4f"),
            "成本": st.column_config.NumberColumn(format="%.2f"),
            "金额": st.column_config.NumberColumn(format="%.2f"),
        })

with st.expander("本次回测参数快照（可复现）"):
    params = result.params
    st.dataframe(pd.DataFrame([
        {"参数": "策略", "值": params["strategy"]},
        {"参数": "股票池", "值": params["universe"]},
        {"参数": "Top N", "值": params["top_n"]},
        {"参数": "调仓周期（交易日）", "值": params["rebalance_every"]},
        {"参数": "单边成本", "值": f"{params['cost_rate']:.2%}"},
        {"参数": "执行价", "值": params["execution"]},
        {"参数": "初始资金", "值": f"{params['initial_cash']:,.0f}"},
        {"参数": "标准化方法", "值": params["standardize_method"]},
        {"参数": "权重", "值": ", ".join(f"{k}={v:.0%}" for k, v in params["weights"].items())},
        {"参数": "窗口", "值": ", ".join(f"{k}={v}" for k, v in params["windows"].items())},
        {"参数": "数据版本", "值": result.data_version},
    ]), hide_index=True, width="stretch")

st.divider()
st.caption("口径说明：排名只用 ≤ 排名日的数据；成交为次一交易日开盘价（停牌不成交）；"
           "持仓按前复权收盘价估值（停牌沿用最后可用价）；前复权价格只用于收益比值，"
           "与最新复权因子无关，不引入未来数据；整数股成交、不模拟 100 股整手；"
           "基准为沪深300 价格指数（不含分红再投资）；不模拟涨停买不进/跌停卖不出；"
           "默认参数只是 Baseline，不代表最优。")
