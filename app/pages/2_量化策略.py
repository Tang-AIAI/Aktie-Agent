"""Strategy A 页面：参数输入 → 重新计算 → Top 10 排名 + 个股因子构成。

页面只负责 UI（参数输入、触发计算、结果展示），策略逻辑全部在 quant/ 包：
- 因子定义与计算：quant/factors/
- 策略配置（权重/窗口）：quant/strategies/strategy_a.py
- 标准化 + 加权 + 排名：quant/engine.py

注意：Strategy A 是 baseline 研究策略，未经过历史回测验证。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import altair as alt
import pandas as pd
import streamlit as st

from quant.engine import run_strategy
from quant.factors.base import HIGHER_BETTER
from quant.factors.registry import get_factor
from quant.market_data import MarketDataLoader
from quant.strategies.strategy_a import StrategyA

st.set_page_config(page_title="量化策略 · Strategy A", page_icon="📈", layout="wide")

FACTORS = [get_factor(f) for f in StrategyA.factor_names]

# ---------------------------------------------------------------- 计算（带缓存）
@st.cache_data(show_spinner="正在计算 Strategy A 排名…")
def _compute(as_of: str, weights: tuple, windows: tuple):
    """权重/窗口以 tuple 传入保证可哈希缓存；参数不变时直接命中缓存。"""
    strategy = StrategyA(weights=dict(weights), windows=dict(windows))
    return run_strategy(strategy, as_of=as_of)


# ---------------------------------------------------------------- 侧边栏参数
def _direction_text(direction: str) -> str:
    return "越高越好 ↑" if direction == HIGHER_BETTER else "越低越好 ↓"


loader = MarketDataLoader()
st.sidebar.title("Strategy A")
st.sidebar.caption("调整参数后点击「重新计算」生成新排名。")

try:
    latest = loader.latest_trade_date()
except Exception as e:  # 数据文件缺失/损坏
    st.error(f"无法读取数据文件：{e}\n\n请先运行 `scripts/update_stock_data.py`。")
    st.stop()

as_of_date = st.sidebar.date_input("计算日期（默认最新交易日）", value=pd.Timestamp(latest))
as_of = as_of_date.strftime("%Y%m%d")

weights_in, windows_in = {}, {}
st.sidebar.subheader("因子参数")
for spec in FACTORS:
    st.sidebar.markdown(f"**{spec.label}** · {_direction_text(spec.direction)}")
    if len(spec.default_windows) == 2:      # Volume Trend：双窗口
        short = st.sidebar.number_input(
            "短期窗口（日）", min_value=2, value=spec.default_windows[0], step=5,
            key=f"win_{spec.name}_short")
        long = st.sidebar.number_input(
            "长期窗口（日）", min_value=2, value=spec.default_windows[1], step=5,
            key=f"win_{spec.name}_long")
        windows_in[spec.name] = (short, long)
    else:
        w = st.sidebar.number_input(
            "窗口（日）", min_value=2, value=spec.default_windows[0], step=5,
            key=f"win_{spec.name}")
        windows_in[spec.name] = (w,)
    weights_in[spec.name] = st.sidebar.number_input(
        f"{spec.short_label or spec.label} 权重（%）", min_value=0, max_value=100,
        value=25, step=5, key=f"w_{spec.name}")

weight_sum = sum(weights_in.values())
weight_ok = abs(weight_sum - 100.0) < 1e-9
window_ok = all(w[0] < w[1] for w in windows_in.values() if len(w) == 2)
if not weight_ok:
    st.sidebar.warning(f"权重合计 {weight_sum:.0f}%，必须等于 100% 才能计算。")
if not window_ok:
    st.sidebar.warning("量能趋势的短期窗口必须小于长期窗口。")
st.sidebar.caption("权重合计：**{:.0f}%**".format(weight_sum))

run = st.sidebar.button("重新计算", type="primary", disabled=not (weight_ok and window_ok))
if run:
    st.session_state["result"] = _compute(
        as_of, tuple(weights_in.items()), tuple((n, ws) for n, ws in windows_in.items()))
result = st.session_state.get("result")

# ---------------------------------------------------------------- 主区域
st.title("Strategy A · 量化评分排名")
st.caption("Strategy A 是 baseline 策略，未经过历史回测验证，"
           "结果仅供量化研究参考，不构成投资建议。")

if result is None:
    st.info("在左侧调整策略参数后，点击「重新计算」查看最新排名。")
    st.stop()

for wmsg in result.warnings:
    st.warning(wmsg)

# 参数已修改但未重算时提示
current_ok = (dict(weights_in) == {f: int(round(v * 100)) for f, v in result.weights.items()}
              and dict(windows_in) == result.windows)
if not current_ok:
    st.info("参数已修改，点击左侧「重新计算」后生效。当前显示的是上一次计算结果。")

m1, m2, m3, m4 = st.columns(4)
m1.metric("计算日期", result.as_of)
m2.metric("股票池（进入排名）", result.universe_size)
m3.metric("已排除", result.excluded_count)
m4.metric("标准化方法", result.method)

if result.universe_size == 0:
    st.warning("股票池为空：没有股票满足计算条件（当日行情 + 完整窗口数据）。")
    st.stop()

ranking = result.ranking
score_cols = [f"{f.name}_score" for f in FACTORS]
raw_cols = [f"{f.name}_raw" for f in FACTORS]
show_raw = st.checkbox("同时显示原始因子值", value=False)

# ---------------------------------------------------------------- Top 10
st.subheader("最新排名 Top 10")
top = ranking.head(10)
disp_cols = ["rank", "ts_code", "name", "score"] + score_cols + (raw_cols if show_raw else [])
top_disp = top[disp_cols].rename(columns={
    "rank": "排名", "ts_code": "股票代码", "name": "股票名称", "score": "Strategy Score",
    **{c: (get_factor(c[:-6]).short_label or get_factor(c[:-6]).label) + " 得分" for c in score_cols},
    **{c: (get_factor(c[:-4]).short_label or get_factor(c[:-4]).label) + " 原始值" for c in raw_cols},
})

col_cfg = {"排名": st.column_config.NumberColumn(width="small"),
           "Strategy Score": st.column_config.NumberColumn(format="%.3f")}
for c in score_cols:
    col_cfg[(get_factor(c[:-6]).short_label or get_factor(c[:-6]).label) + " 得分"] = \
        st.column_config.NumberColumn(format="%.3f")
for c in raw_cols:
    label = (get_factor(c[:-4]).short_label or get_factor(c[:-4]).label) + " 原始值"
    fmt = "%.4f" if c == "volatility_raw" else "%.3f"
    col_cfg[label] = st.column_config.NumberColumn(format=fmt)

sel_event = st.dataframe(
    top_disp, hide_index=True, width="stretch", column_config=col_cfg,
    key="top10", on_select="rerun", selection_mode="single-row")
if sel_event.selection.rows:
    # 点击 Top 10 行 → 联动下方因子构成。选中状态会跨 rerun 持久化，
    # 只在选择发生变化时处理一次（一次性 flag 同步 selectbox），
    # 避免覆盖用户手动操作 selectbox。
    # 注意：实测 Streamlit 1.55 的 canvas 网格在前端不发送选择事件（点击仅
    # 客户端高亮），此联动在 selectbox 外兜底，不依赖它完成核心交互。
    rows = list(sel_event.selection.rows)
    if rows != st.session_state.get("_handled_top10_sel"):
        st.session_state["_handled_top10_sel"] = rows
        st.session_state["sel_code"] = top.iloc[rows[0]]["ts_code"]
        st.session_state["_sync_selectbox"] = True

# ---------------------------------------------------------------- 参数与完整排名
with st.expander("策略参数（本次计算）"):
    params = pd.DataFrame([{
        "因子": spec.label, "方向": _direction_text(spec.direction),
        "窗口": " / ".join(str(w) for w in result.windows[spec.name]),
        "权重": f"{result.weights[spec.name]:.0%}",
    } for spec in FACTORS])
    st.dataframe(params, hide_index=True, width="stretch")

with st.expander(f"完整排名（共 {result.universe_size} 只）"):
    st.dataframe(ranking[disp_cols].rename(columns={
        "rank": "排名", "ts_code": "股票代码", "name": "股票名称", "score": "Strategy Score",
        **{c: (get_factor(c[:-6]).short_label or get_factor(c[:-6]).label) + " 得分" for c in score_cols},
        **{c: (get_factor(c[:-4]).short_label or get_factor(c[:-4]).label) + " 原始值" for c in raw_cols},
    }), hide_index=True, width="stretch", column_config=col_cfg)

# ---------------------------------------------------------------- 个股因子构成
st.divider()
st.subheader("个股因子构成")

codes = ranking["ts_code"].tolist()
stock_names = ranking["name"].tolist()
labels = [f"{c} · {n}" for c, n in zip(codes, stock_names)]
sel_code = st.session_state.get("sel_code")
default_idx = codes.index(sel_code) if sel_code in codes else 0
if st.session_state.pop("_sync_selectbox", False) and sel_code in codes:
    # selectbox 的 widget 状态跨 rerun 持久化，需显式写入才会跳到表格点击的股票
    st.session_state["detail_select"] = default_idx
choice = st.selectbox("选择股票", labels, key="detail_select", index=default_idx)
row = ranking[ranking["ts_code"] == codes[labels.index(choice)]].iloc[0]

detail_rows = []
for spec in FACTORS:
    raw_v = row[f"{spec.name}_raw"]
    z = row[f"{spec.name}_score"]
    w = result.weights[spec.name]
    detail_rows.append({
        "因子": spec.label,
        "方向": _direction_text(spec.direction),
        "窗口": " / ".join(str(x) for x in result.windows[spec.name]),
        "权重": f"{w:.0%}",
        "原始值": raw_v,
        "横截面得分（方向已调整）": z,
        "对总分贡献": z * w,
    })
detail = pd.DataFrame(detail_rows)
st.dataframe(detail, hide_index=True, width="stretch", column_config={
    "原始值": st.column_config.NumberColumn(format="%.4f"),
    "横截面得分（方向已调整）": st.column_config.NumberColumn(format="%.3f"),
    "对总分贡献": st.column_config.NumberColumn(format="%.3f"),
})

chart_df = pd.DataFrame({
    "因子": [spec.short_label or spec.label for spec in FACTORS],
    "得分": [row[f"{spec.name}_score"] for spec in FACTORS],
})
dark = st.get_option("theme.base") == "dark"
pos_color, neg_color = ("#3987e5", "#e66767") if dark else ("#2a78d6", "#e34948")  # 发散色对（蓝↔红）

# 正/负分层渲染（本版 Altair 的 mark 属性不支持 condition，分两层更稳）
enc = dict(
    x=alt.X("得分:Q", axis=alt.Axis(title="方向调整后得分（横截面 z-score × 方向）")),
    y=alt.Y("因子:N", sort=None, axis=alt.Axis(title=None)),
)
tooltip = [alt.Tooltip("因子:N"), alt.Tooltip("得分:Q", format="+.3f")]
pos = alt.Chart(chart_df).transform_filter(alt.datum["得分"] >= 0)
neg = alt.Chart(chart_df).transform_filter(alt.datum["得分"] < 0)
bars = (
    pos.mark_bar(size=26, color=pos_color).encode(**enc, tooltip=tooltip)
    + neg.mark_bar(size=26, color=neg_color).encode(**enc, tooltip=tooltip)
)
labels_chart = (
    pos.mark_text(baseline="middle", align="left", dx=4, color="#898781")
       .encode(**enc, text=alt.Text("得分:Q", format="+.3f"))
    + neg.mark_text(baseline="middle", align="right", dx=-4, color="#898781")
          .encode(**enc, text=alt.Text("得分:Q", format="+.3f"))
)
st.altair_chart(bars + labels_chart, width="stretch")

with st.expander("计算方法说明"):
    st.markdown("\n".join(f"- **{spec.label}**：{spec.description}" for spec in FACTORS))
    st.markdown(
        "- 每个因子在计算日的股票池内做横截面 z-score 标准化（`(x − mean) / std`，"
        "总体标准差），\"越低越好\"的因子乘 −1 反转方向；\n"
        "- Strategy Score = 四个标准化因子得分 × 各自权重之和；\n"
        "- 排除规则：无当日行情（停牌/退市）、任一因子数据不足、不在 stock_list.csv 中的股票。")
