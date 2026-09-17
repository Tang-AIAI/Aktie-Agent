"""Web App 共享工具：Strategy A 计算缓存、持仓维护、数据更新流水线、选股条件持久化。

页面只从这里取能力，不直接读 parquet、不复制计算逻辑：
- 量化计算走 quant/engine + MarketDataLoader（带 st.cache_data）
- 数据更新以子进程调用现有 scripts/（下载逻辑不重写，输出原样透传）

导航用 Streamlit 默认多页模式（pages/ 目录 + 文件名顺序）；实测 st.navigation
在本机 1.55 上会破坏 URL 路由（所有子页都回落到首页），故不使用。
"""

import json
import os
import queue
import subprocess
import sys
import threading
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from data.paths import POSITIONS_FILE, SCREENER_STATE_FILE  # noqa: E402
from quant.engine import run_strategy  # noqa: E402
from quant.market_data import MarketDataLoader  # noqa: E402
from quant.strategies.strategy_a import StrategyA  # noqa: E402

POSITIONS_COLUMNS = ["ts_code", "name", "quantity", "cost_price"]


# ---------------------------------------------------------------- 量化计算缓存
def data_version(loader: MarketDataLoader = None) -> str:
    """数据文件指纹（mtime+size），并入 st.cache_data key 使数据更新后缓存失效。"""
    loader = loader or MarketDataLoader()
    parts = []
    for f in (loader.adj_file, loader.index_file, loader.stock_list_file):
        try:
            st_info = os.stat(f)
            parts.append(f"{st_info.st_mtime_ns}-{st_info.st_size}")
        except OSError:
            parts.append("missing")
    return "|".join(parts)


@st.cache_data(show_spinner="正在计算 Strategy A 排名…")
def compute_strategy_a(as_of: str, dv: str):
    """Strategy A 默认参数排名（与量化策略页同引擎同口径，缓存键含数据版本）。"""
    return run_strategy(StrategyA(), as_of=as_of)


def latest_as_of(loader: MarketDataLoader = None) -> str:
    loader = loader or MarketDataLoader()
    return str(loader.latest_trade_date())


# ---------------------------------------------------------------- 持仓（本地 CSV）
def load_positions() -> pd.DataFrame:
    """读 positions.csv；缺失/损坏时返回空表（空表 = 无持仓，不报错）。"""
    if not os.path.exists(POSITIONS_FILE):
        return pd.DataFrame(columns=POSITIONS_COLUMNS)
    try:
        df = pd.read_csv(POSITIONS_FILE)
    except Exception:
        return pd.DataFrame(columns=POSITIONS_COLUMNS)
    for col in POSITIONS_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["cost_price"] = pd.to_numeric(df["cost_price"], errors="coerce")
    df["ts_code"] = df["ts_code"].astype(str).str.strip()
    df["name"] = df["name"].fillna("").astype(str)
    return df[POSITIONS_COLUMNS]


def save_positions(df: pd.DataFrame) -> None:
    """原子写入 positions.csv（tempfile + os.replace），UTF-8。"""
    df = df.copy()
    for col in POSITIONS_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[POSITIONS_COLUMNS].dropna(subset=["ts_code"])
    df["ts_code"] = df["ts_code"].astype(str).str.strip()
    df = df[df["ts_code"] != ""]
    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=BASE_DIR)
    os.close(fd)
    try:
        df.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, POSITIONS_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def compute_holdings(positions: pd.DataFrame, loader: MarketDataLoader = None) -> pd.DataFrame:
    """持仓估值：最新交易日原始收盘价 → 市值/盈亏/盈亏%/权重。

    返回列：ts_code, name, quantity, cost_price, close, close_date,
           market_value, profit, profit_pct, weight。
    无行情数据的持仓保留行（数值为 NaN），不计入合计。
    """
    loader = loader or MarketDataLoader()
    cols = POSITIONS_COLUMNS + ["close", "close_date", "market_value", "profit",
                                "profit_pct", "weight"]
    empty = pd.DataFrame(columns=cols)
    if positions is None or positions.empty:
        return empty
    df = positions.copy()
    names = loader.stock_names()
    px = loader.load_latest_prices(codes=list(df["ts_code"]))
    px_map = dict(zip(px["ts_code"], px["close"]))
    latest_date = str(px["trade_date"].max()) if not px.empty else ""
    df["name"] = df.apply(lambda r: r["name"] or names.get(r["ts_code"], ""), axis=1)
    df["close"] = df["ts_code"].map(px_map)
    df["close_date"] = latest_date
    df["market_value"] = df["close"] * df["quantity"]
    df["profit"] = (df["close"] - df["cost_price"]) * df["quantity"]
    df["profit_pct"] = (df["close"] - df["cost_price"]) / df["cost_price"]
    total = df["market_value"].sum()
    df["weight"] = df["market_value"] / total if total and total > 0 else None
    return df[cols]


# ---------------------------------------------------------------- 数据更新流水线
# 顺序：个股日线(+因子+前复权重建) → 沪深300 → 完整性检查（与需求一致）
# 每步设有超时（UI 层监督，不修改脚本逻辑）：个股日线可断点续传、允许长时间运行
# 故不设超时；沪深300 的 AkShare 降级路径无内建超时（实测会挂死）设 3 分钟；
# 完整性检查为纯本地扫描（实测约 41s）设 3 分钟。
UPDATE_PIPELINE = [
    ("个股日线 / 复权因子 / 前复权重建", "scripts/update_stock_data.py", None),
    ("沪深300 指数", "scripts/update_index_data.py", 180),
    ("数据完整性检查", "scripts/check_data.py", 180),
]


def _run_script(script: str, q: queue.Queue, timeout: int | None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(BASE_DIR / script)], cwd=str(BASE_DIR),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)

    def _read():
        for line in proc.stdout:
            q.put(line.rstrip())

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=timeout)
        reader.join(timeout=10)
        q.put(("__DONE__", code))
    except subprocess.TimeoutExpired:
        # 超时兜底（如 AkShare 降级路径无内建超时挂死）：终止子进程并如实上报
        proc.kill()
        reader.join(timeout=10)
        q.put(("__LOG__", f"（该步骤超过 {timeout // 60} 分钟未完成，已被终止，"
                          "请根据上方日志判断是否重试。）"))
        q.put(("__DONE__", -9))


def run_update_pipeline():
    """生成器：逐行产出更新日志。

    产出 (kind, text)：kind = step（步骤标题）/ log（脚本输出行）/
    done（退出码 + 该步全部日志文本，供调用方判断"退出 0 但未取得数据"的情况）。
    """
    for label, script, timeout in UPDATE_PIPELINE:
        yield ("step", label)
        q = queue.Queue()
        t = threading.Thread(target=_run_script, args=(script, q, timeout), daemon=True)
        t.start()
        step_lines = []
        while True:
            try:
                item = q.get(timeout=0.5)
            except queue.Empty:
                continue
            if isinstance(item, tuple) and item[0] == "__DONE__":
                yield ("done", item[1], "\n".join(step_lines))
                break
            if isinstance(item, tuple) and item[0] == "__LOG__":
                yield ("log", item[1])
                continue
            step_lines.append(item)
            yield ("log", item)
        t.join(timeout=10)


# 退出码为 0 但实际未取得数据时，步骤仍应如实标记失败：
# index 脚本在 Tushare 限频且 AkShare 降级失败时打印"未获取到任何数据"但退出 0
_NO_DATA_MARKERS = ("未获取到任何数据",)


def _step_failed(code: int, log_text: str) -> bool:
    if code != 0:
        return True
    if any(m in log_text for m in _NO_DATA_MARKERS):
        return True
    return False


def stream_update_pipeline() -> dict:
    """在页面上实时流式展示更新过程，返回 {failed_steps: [...]}（真实失败才记录）。

    注意：write_stream 的内容在随后的 st.rerun() 后不会保留（容器随本次运行消失），
    因此同时把完整日志与结论写入 session_state，页面在 rerun 后重新渲染展示。
    """
    failed_steps = []
    log_lines = []

    def gen():
        for kind, *rest in run_update_pipeline():
            if kind == "step":
                log_lines.append(f"▶ {rest[0]}")
                yield f"\n**▶ {rest[0]}**\n```\n"
            elif kind == "log":
                log_lines.append(rest[0])
                yield rest[0] + "\n"
            elif kind == "done":
                code, log_text = rest
                if _step_failed(code, log_text):
                    failed_steps.append(code or 1)
                    msg = (f"❌ 该步骤失败"
                           + (f"（退出码 {code}）" if code != 0 else "（脚本未取得数据）")
                           + "，上方日志为真实输出")
                    log_lines.append(msg)
                    yield f"\n```\n{msg}\n"
                else:
                    log_lines.append("✅ 该步骤完成")
                    yield "\n```\n✅ 该步骤完成\n"

    st.write_stream(gen())
    st.session_state["update_log"] = log_lines
    st.session_state["update_result"] = {
        "failed_steps": failed_steps,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"failed_steps": failed_steps}


def render_update_log():
    """rerun 后重新渲染最近一次更新日志与结论（session_state 持久化）。

    结论（成功/失败）直接可见；完整日志在可展开区，失败时是真实脚本输出。
    """
    log_lines = st.session_state.get("update_log")
    result = st.session_state.get("update_result")
    if not log_lines:
        return
    if result.get("failed_steps"):
        st.error(f"最近一次更新：有 {len(result['failed_steps'])} 个步骤失败，展开下方日志查看真实输出。")
    else:
        st.success("最近一次更新：全部步骤完成。")
    with st.expander(f"最近一次更新日志（{result.get('finished_at', '')}）"):
        st.text("\n".join(log_lines))


# ---------------------------------------------------------------- 条件选股状态
def load_screener_state() -> dict:
    """最近一次筛选条件（首页展示入口用），缺失/损坏返回 {}。"""
    if not os.path.exists(SCREENER_STATE_FILE):
        return {}
    try:
        with open(SCREENER_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_screener_state(conditions: list, as_of: str) -> None:
    data = {"saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "as_of": as_of, "conditions": conditions}
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=BASE_DIR)
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SCREENER_STATE_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def format_conditions(conditions: list) -> str:
    """把条件列表转成人类可读的一行描述（首页"最近使用条件"展示用）。"""
    from quant.screener import INDICATORS
    if not conditions:
        return "（暂无记录）"
    parts = []
    for i, cond in enumerate(conditions):
        label = INDICATORS[cond["left"]].label
        right = cond["right"]
        right_text = (f"{right['value']:g}" if right["kind"] == "value"
                      else INDICATORS[right["name"]].label)
        text = f"{label} {cond['op']} {right_text}"
        if cond.get("negate"):
            text = f"NOT ({text})"
        if i > 0:
            text = f"{cond.get('connector', 'AND')} {text}"
        parts.append(text)
    return " ".join(parts)
