"""首页 Dashboard：数据状态 / 当前持仓 / 量化系统 / 条件选股 四个区域。

主线：数据 → 量化 → 筛选 → 研究。信息密度克制，不做行情软件式满屏数字。
计算全部复用 quant/ 引擎与 data/ 数据层（见 app/common.py），页面只做组装。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from app.common import (compute_holdings, compute_strategy_a, data_version,
                        format_conditions, latest_as_of, load_positions,
                        load_screener_state, render_update_log, save_positions,
                        stream_update_pipeline)
from quant.market_data import MarketDataLoader

st.set_page_config(page_title="量化研究台 · 首页", page_icon="📊", layout="wide")

loader = MarketDataLoader()

# ---------------------------------------------------------------- 顶部
st.title("量化研究台")
st.caption("个人量化研究工具 · 数据 → 量化 → 筛选 → 研究 · 不是交易终端")

c1, c2, c3, c4 = st.columns(4)
for col, (step, desc) in zip([c1, c2, c3, c4], [
        ("① 数据", "日线 / 指数 / 复权，完整性可查"),
        ("② 量化", "Strategy A 评分排名（baseline）"),
        ("③ 筛选", "可视化条件选股，无需公式语言"),
        ("④ 研究", "个股因子构成与指标明细")]):
    with col.container(border=True):
        st.markdown(f"**{step}**\n\n{desc}")

st.divider()

# ---------------------------------------------------------------- A. 数据状态
st.subheader("数据状态")
status = loader.data_status()
cal = loader.calendar_status()
raw_latest = status["raw"]["latest"]
expected = cal["latest_open"]   # 数据应更新到的最近交易日（今日开盘则含今日）

def _state_text(latest: str, kind: str) -> tuple:
    if expected is None:
        return "⚠️ 无法判断", f"交易日历缺失，无法判断{kind}是否最新"
    if latest is None:
        return "❌ 缺失", f"{kind}数据文件缺失"
    if latest == expected:
        return "✅ 已最新", f"最新交易日 {latest}"
    if cal["today_open"]:
        return "⏳ 未更新", f"最新 {latest}，今日为交易日（应更新至 {expected}）"
    return "⚠️ 落后", f"最新 {latest}，最近交易日应为 {expected}"

stocks_state, stocks_reason = _state_text(raw_latest, "个股日线")
idx_state, idx_reason = _state_text(status["index"]["latest"], "沪深300")

m1, m2, m3, m4 = st.columns(4)
m1.metric("个股日线", raw_latest or "—", stocks_state, delta_color="off")
m2.metric("沪深300", status["index"]["latest"] or "—", idx_state, delta_color="off")
m3.metric("复权因子", status["adj_factor"]["latest"] or "—",
          ("✅ 已最新" if status["adj_factor"]["latest"] == raw_latest else "⚠️ 落后于日线"),
          delta_color="off")
m4.metric("交易日历", cal["max_cal"] or "—",
          ("✅ 正常" if cal["max_cal"] and cal["max_cal"] >= pd.Timestamp.today().strftime("%Y%m%d")
           else "⚠️ 需刷新"),
          delta_color="off")

if "已最新" not in (stocks_state, idx_state):
    st.warning(f"数据不是最新。原因：{stocks_reason}；{idx_reason}。")

with st.expander("更新数据（运行现有更新脚本，过程实时显示）"):
    st.caption("顺序：个股日线 + 复权因子 + 前复权重建 → 沪深300 → 完整性检查。"
               "下载逻辑与命令行完全一致（scripts/）。")
    if st.button("更新数据", type="primary", icon="🔄"):
        stream_update_pipeline()   # 流式展示 + 日志持久化到 session_state
        st.rerun()                 # 刷新状态；日志由 render_update_log 重新渲染
render_update_log()

st.divider()

# ---------------------------------------------------------------- C. 量化系统 / B. 当前持仓
left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("量化系统 · Strategy A")
    try:
        result = compute_strategy_a(latest_as_of(loader), data_version(loader))
        top = result.ranking.head(10)
        t1, t2, t3 = st.columns(3)
        t1.metric("最近一次计算", result.as_of)
        t2.metric("股票池规模", result.universe_size)
        t3.metric("当前第 1 名", f"{top.iloc[0]['name']} ({top.iloc[0]['ts_code']})")
        disp = top[["rank", "ts_code", "name", "score"]].rename(columns={
            "rank": "排名", "ts_code": "代码", "name": "名称", "score": "Strategy Score"})
        st.dataframe(disp, hide_index=True, width="stretch", column_config={
            "排名": st.column_config.NumberColumn(width="small"),
            "Strategy Score": st.column_config.NumberColumn(format="%.3f"),
        })
        st.page_link("pages/2_量化策略.py", label="进入 Strategy A 页面（调整权重/窗口 · 完整排名 · 个股因子构成）",
                     icon="📈")
    except Exception as e:
        st.error(f"Strategy A 计算失败：{e}")

with right:
    st.subheader("当前持仓")
    positions = load_positions()
    holdings = compute_holdings(positions, loader)
    if holdings.empty:
        st.info("暂无持仓记录。点下方「编辑持仓」添加。")
    else:
        total_mv = holdings["market_value"].sum()
        total_profit = holdings["profit"].sum()
        cost_basis = (holdings["cost_price"] * holdings["quantity"]).sum()
        h1, h2 = st.columns(2)
        h1.metric("总市值", f"{total_mv:,.0f}")
        h2.metric("总盈亏", f"{total_profit:+,.0f}",
                  delta=f"{total_profit / cost_basis * 100:+.2f}%"   # 相对成本的总收益率
                  if pd.notna(cost_basis) and cost_basis != 0 else None)
        disp = holdings.rename(columns={
            "ts_code": "代码", "name": "名称", "quantity": "数量", "cost_price": "成本价",
            "close": "现价", "market_value": "市值", "profit": "盈亏",
            "profit_pct": "盈亏%", "weight": "权重"})
        st.dataframe(
            disp.style.map(lambda v: ("color:#006300" if v > 0 else "color:#d03b3b" if v < 0 else ""),
                           subset=["盈亏", "盈亏%"]).format(
                {"数量": "{:,.0f}", "成本价": "{:.3f}", "现价": "{:.3f}", "市值": "{:,.0f}",
                 "盈亏": "{:+,.0f}", "盈亏%": "{:+.2%}", "权重": "{:.2%}"}),
            hide_index=True, width="stretch")
        no_px = holdings[holdings["close"].isna()]
        if not no_px.empty:
            st.warning(f"{', '.join(no_px['ts_code'])} 无最新行情，未计入合计。")
    with st.expander("编辑持仓（本地 positions.csv，手工维护）"):
        edited = st.data_editor(positions, num_rows="dynamic", key="pos_editor",
                                hide_index=True, width="stretch", column_config={
                                    "ts_code": st.column_config.TextColumn("股票代码", required=True),
                                    "name": st.column_config.TextColumn("股票名称（留空自动补全）"),
                                    "quantity": st.column_config.NumberColumn("持仓数量", min_value=0),
                                    "cost_price": st.column_config.NumberColumn("成本价", min_value=0.0),
                                })
        if st.button("保存持仓", icon="💾"):
            bad = edited[(edited["ts_code"].astype(str).str.strip() == "")
                         | edited["quantity"].isna() | (edited["quantity"] <= 0)
                         | edited["cost_price"].isna() | (edited["cost_price"] <= 0)]
            if not bad.empty:
                st.error(f"{len(bad)} 行持仓无效（代码为空、数量或成本价 ≤ 0），未保存。")
            else:
                names = loader.stock_names()
                edited["name"] = edited.apply(
                    lambda r: (r["name"] or "").strip() or names.get(r["ts_code"].strip(), ""), axis=1)
                save_positions(edited)
                st.session_state.pop("pos_editor", None)
                st.success("持仓已保存。")
                st.rerun()

st.divider()

# ---------------------------------------------------------------- D. 条件选股
st.subheader("条件选股")
d1, d2 = st.columns([2, 3])
with d1:
    st.markdown("用可视化条件构建器筛选股票，无需公式语言。\n\n"
                "例如：`收盘价 > MA60 AND 60日收益率 > 10% AND 成交量比 > 1.2`")
    st.page_link("pages/3_条件选股.py", label="进入条件选股页面", icon="🔍")
with d2:
    last = load_screener_state()
    st.markdown(f"**最近使用条件**（{last.get('saved_at', '暂无')}，计算日 {last.get('as_of', '—')}）\n\n"
                f"{format_conditions(last.get('conditions', []))}")
