"""条件选股：可视化条件构建器（不做公式语言）。

- 指标计算与条件求值全部在 quant/screener.py（与 Strategy A 同数据口径，
  前复权价、股票池 = 有当日行情 ∩ stock_list.csv）；
- 页面只负责：条件行的增删改、AND/OR/NOT 组合、触发筛选、结果展示；
- 组合语义：条件自上而下、按每行的 AND/OR 与上一结果结合（无运算优先级，
  避免误解；NOT 只作用于本行条件）；
- 指标值为 NaN（数据不足）的条件视为"不满足"，NOT 也不放行。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.common import data_version, latest_as_of, save_screener_state
from quant.market_data import MarketDataLoader
from quant.screener import INDICATORS, compute_indicators, evaluate

st.set_page_config(page_title="条件选股", page_icon="🔍", layout="wide")

OPS = [">", ">=", "<", "<=", "=", "!="]
INDICATOR_NAMES = list(INDICATORS)
INDICATOR_LABELS = {n: s.label for n, s in INDICATORS.items()}

loader = MarketDataLoader()
st.title("条件选股")
st.caption("可视化条件构建器：指标 vs 数值 / 指标 vs 指标，AND / OR / NOT 组合。"
           "所有指标基于前复权价计算，与 Strategy A 同口径。")

# ---------------------------------------------------------------- 条件状态
def _default_cond() -> dict:
    return {"connector": "AND", "negate": False, "left": "close", "op": ">",
            "right_type": "value", "right_value": 10.0, "right_indicator": "ma60"}


if "conds" not in st.session_state:
    st.session_state["conds"] = [_default_cond()]
conds = st.session_state["conds"]

_WIDGET_PREFIXES = ("conn", "neg", "left", "op", "rtype", "rval", "rind", "del")


def _k(prefix: str, i: int) -> str:
    return f"sc_{prefix}_{i}"


# ---------------------------------------------------------------- 条件编辑区
st.subheader("条件")
del_idx = None
for i, cond in enumerate(conds):
    cols = st.columns([0.9, 0.6, 1.8, 1.0, 1.0, 1.9, 0.5], gap="small")
    with cols[0]:
        if i == 0:
            st.markdown("**与上一行**")
            conn = cond["connector"]
        else:
            conn = st.selectbox("与上一行", ["AND", "OR"], key=_k("conn", i),
                                index=0 if cond["connector"] == "AND" else 1)
    with cols[1]:
        neg = st.checkbox("NOT", value=cond["negate"], key=_k("neg", i))
    with cols[2]:
        left = st.selectbox("左指标", INDICATOR_NAMES, key=_k("left", i),
                            index=INDICATOR_NAMES.index(cond["left"]),
                            format_func=lambda n: INDICATOR_LABELS[n],
                            label_visibility="visible" if i == 0 else "collapsed")
    with cols[3]:
        op = st.selectbox("运算符", OPS, key=_k("op", i),
                          index=OPS.index(cond["op"]),
                          label_visibility="visible" if i == 0 else "collapsed")
    with cols[4]:
        right_type = st.selectbox("右值类型", ["数值", "指标"], key=_k("rtype", i),
                                  index=0 if cond["right_type"] == "value" else 1,
                                  label_visibility="visible" if i == 0 else "collapsed")
    with cols[5]:
        if right_type == "数值":
            right_value = st.number_input("右值", value=cond["right_value"], step=1.0,
                                          format="%.4f", key=_k("rval", i),
                                          label_visibility="visible" if i == 0 else "collapsed")
            right_indicator = cond["right_indicator"]
        else:
            right_value = cond["right_value"]
            right_indicator = st.selectbox("右指标", INDICATOR_NAMES, key=_k("rind", i),
                                           index=INDICATOR_NAMES.index(cond["right_indicator"]),
                                           format_func=lambda n: INDICATOR_LABELS[n],
                                           label_visibility="visible" if i == 0 else "collapsed")
    with cols[6]:
        st.write("")
        if st.button("✕", key=_k("del", i), help="删除该条件"):
            del_idx = i
    # 每次渲染把 widget 当前值写回 session_state（唯一真源）
    cond.update({"connector": conn, "negate": neg, "left": left, "op": op,
                 "right_type": "value" if right_type == "数值" else "indicator",
                 "right_value": right_value, "right_indicator": right_indicator})

if del_idx is not None:
    conds.pop(del_idx)
    st.session_state["conds"] = conds
    # 删除该行及之后所有行的 widget 状态，防止旧 key 在新位置"复活"旧值
    for key in list(st.session_state.keys()):
        for p in _WIDGET_PREFIXES:
            prefix = f"sc_{p}_"
            if key.startswith(prefix) and key[len(prefix):].isdigit() \
                    and int(key[len(prefix):]) >= del_idx:
                del st.session_state[key]
                break
    st.rerun()

c1, c2 = st.columns([1, 4])
with c1:
    if st.button("➕ 添加条件", icon="➕"):
        st.session_state["conds"] = conds + [_default_cond()]
        st.rerun()

# ---------------------------------------------------------------- 触发筛选
as_of_date = st.date_input("计算日期（默认最新交易日）", value=pd.Timestamp(latest_as_of(loader)))
as_of = as_of_date.strftime("%Y%m%d")

def _build_conditions() -> list:
    specs = []
    for cond in conds:
        right = ({"kind": "value", "value": cond["right_value"]}
                 if cond["right_type"] == "value"
                 else {"kind": "indicator", "name": cond["right_indicator"]})
        specs.append({"left": cond["left"], "op": cond["op"], "right": right,
                      "negate": cond["negate"], "connector": cond["connector"]})
    return specs


@st.cache_data(show_spinner="正在计算指标…")
def _indicators(as_of: str, names: tuple, dv: str):
    return compute_indicators(as_of=as_of, indicators=names)


if st.button("开始筛选", type="primary", disabled=not conds, icon="🔍"):
    try:
        specs = _build_conditions()
        needed = sorted({c["left"] for c in specs}
                        | {c["right"]["name"] for c in specs if c["right"]["kind"] == "indicator"})
        table = _indicators(as_of, tuple(needed), data_version(loader))
        mask = evaluate(table.table, specs)
        results = table.table[mask].reset_index(names="ts_code")
        st.session_state["screen_result"] = {
            "as_of": table.as_of, "results": results, "specs": specs,
            "needed": needed, "total": len(table.table), "warnings": table.warnings,
        }
        save_screener_state(specs, table.as_of)
    except Exception as e:  # 真实报错，不吞
        st.session_state["screen_result"] = None
        st.error(f"筛选失败：{e}")

screen = st.session_state.get("screen_result")

# ---------------------------------------------------------------- 结果展示
if screen is not None:
    st.divider()
    st.subheader("筛选结果")
    for wmsg in screen["warnings"]:
        st.warning(wmsg)
    n = len(screen["results"])
    m1, m2, m3 = st.columns(3)
    m1.metric("筛选结果", f"{n} 只")
    m2.metric("股票池", f"{screen['total']} 只")
    m3.metric("计算日期", screen["as_of"])

    if n == 0:
        st.info("没有符合条件的股票（0 只）。可以放宽条件或调整运算符后重试。")
    else:
        results = screen["results"]
        disp_cols = ["ts_code", "name", "close_raw"] + screen["needed"]
        labels = {"ts_code": "股票代码", "name": "股票名称", "close_raw": "最新价格"}
        for ind in screen["needed"]:
            labels[ind] = INDICATOR_LABELS[ind]
        # 数值格式：价格/均线 2 位、收益率 4 位、成交量整数、比值/波动率 3-4 位
        fmts = {"ts_code": None, "name": None, "close_raw": "%.2f"}
        for ind in screen["needed"]:
            fmts[ind] = ("%.4f" if ind in ("ret20", "ret60", "rs_hs300")
                         else "%.0f" if ind in ("vol20avg", "vol60avg")
                         else "%.4f" if ind == "volatility" else "%.2f")
        cfg = {labels[c]: st.column_config.NumberColumn(format=fmts[c]) for c in disp_cols
               if fmts.get(c)}
        st.dataframe(
            results[disp_cols].rename(columns=labels), hide_index=True, width="stretch",
            column_config=cfg)
        st.caption(f"共 {n} 只满足条件（自上而下 AND/OR 组合，无优先级；"
                   "指标数据不足视为不满足）。")
