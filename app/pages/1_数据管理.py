"""数据管理：各数据文件状态（最新交易日/行数/来源/是否最新）+ 一键更新。

更新直接以子进程运行现有 scripts/（update_stock_data → update_index_data →
check_data），日志实时透传、真实失败如实展示，不重写任何下载逻辑；
命令行更新方式保持不变。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.common import render_update_log, stream_update_pipeline
from quant.market_data import MarketDataLoader

st.set_page_config(page_title="数据管理", page_icon="🗄️", layout="wide")

loader = MarketDataLoader()
st.title("数据管理")
st.caption("数据文件均在本项目根目录（Parquet）。更新与命令行 scripts/ 完全一致。")

status = loader.data_status()
cal = loader.calendar_status()
expected = cal["latest_open"]
today = pd.Timestamp.today().strftime("%Y%m%d")


def _state(latest: str) -> str:
    if latest is None:
        return "❌ 缺失"
    if expected is None:
        return "⚠️ 无法判断"
    if latest == expected:
        return "✅ 已最新"
    if cal["today_open"]:
        return "⏳ 今日为交易日，尚未更新"
    return f"⚠️ 落后（应为 {expected}）"


rows = [
    {"数据": "个股日线", "文件": "market_data_raw.parquet",
     "最新交易日": status["raw"]["latest"], "最新日行数": status["raw"]["rows_latest"],
     "来源": "Tushare Pro daily（断点续传，download_progress.txt）",
     "状态": _state(status["raw"]["latest"])},
    {"数据": "复权因子", "文件": "adj_factor.parquet",
     "最新交易日": status["adj_factor"]["latest"], "最新日行数": status["adj_factor"]["rows_latest"],
     "来源": "Tushare adj_factor + 新浪 qfq.js 回补（source 列标记）",
     "状态": ("✅ 与日线同步" if status["adj_factor"]["latest"] == status["raw"]["latest"]
              else f"⚠️ 落后于日线（{status['adj_factor']['latest']} vs {status['raw']['latest']}）")},
    {"数据": "前复权数据", "文件": "market_data_adj.parquet",
     "最新交易日": status["adj"]["latest"], "最新日行数": status["adj"]["rows_latest"],
     "来源": "本地重建（日线 × 因子，公式 p × F_当日/F_最新）",
     "状态": ("✅ 与日线同步" if status["adj"]["latest"] == status["raw"]["latest"]
              else f"⚠️ 落后于日线（{status['adj']['latest']} vs {status['raw']['latest']}）")},
    {"数据": "沪深300", "文件": "index_data.parquet",
     "最新交易日": status["index"]["latest"], "最新日行数": status["index"]["rows_latest"],
     "来源": "Tushare index_daily（失败降级 AkShare）",
     "状态": _state(status["index"]["latest"])},
    {"数据": "交易日历", "文件": "trade_calendar.parquet",
     "最新交易日": f"{cal['max_cal'] or '—'}（覆盖至）", "最新日行数": status["calendar"]["rows_latest"],
     "来源": "新浪交易日列表（主）+ Tushare trade_cal（备）",
     "状态": ("✅ 覆盖到未来" if cal["max_cal"] and cal["max_cal"] >= today else "⚠️ 覆盖不足，更新时自动刷新")},
]

st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
st.caption("「最新日行数」= 最新交易日当天该文件的记录行数；完整性检查的细粒度结果见更新日志。")

st.divider()

st.subheader("更新数据")
st.caption("流程：个股日线（含复权因子与前复权重建）→ 沪深300 → 完整性检查。"
           "断点续传，可重复运行；任何失败都会展示脚本真实输出。")
if st.button("更新数据", type="primary", icon="🔄"):
    stream_update_pipeline()   # 流式展示 + 日志持久化到 session_state
    st.rerun()                 # 刷新数据状态；日志由 render_update_log 重新渲染
render_update_log()

st.caption("命令行更新方式不变：`python scripts/update_stock_data.py`、"
           "`python scripts/update_index_data.py`、`python scripts/check_data.py` 等。")
