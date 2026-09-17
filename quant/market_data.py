"""量化引擎数据入口：按日期区间 + 列裁剪读取 parquet，带内存缓存。

不做全量历史读入：read_parquet 只取需要的列并下推日期过滤，
实测单年 4 列（ts_code/trade_date/close_adj/vol）约 0.6s。
缓存 key 含文件 mtime/size，更新脚本原子替换数据文件后缓存自动失效。
"""

import os

import pandas as pd
import pyarrow.parquet as pq

from data.paths import ADJ_FILE, CALENDAR_FILE, FCT_FILE, INDEX_FILE, RAW_FILE, STOCK_LIST_FILE

DEFAULT_COLUMNS = ("ts_code", "trade_date", "close_adj", "vol")
_CACHE_MAX = 6   # 内存缓存条目上限（不同窗口参数会产生不同 key），FIFO 淘汰


class MarketDataLoader:
    """按区间读取个股/指数行情与股票名称，供策略引擎使用。"""

    def __init__(self, adj_file=ADJ_FILE, index_file=INDEX_FILE,
                 stock_list_file=STOCK_LIST_FILE):
        self.adj_file = adj_file
        self.index_file = index_file
        self.stock_list_file = stock_list_file
        self._market_cache = {}
        self._index_cache = None
        self._index_key = None
        self._names_cache = None
        self._names_key = None
        self._latest_key = None
        self._latest_value = None

    @staticmethod
    def _file_key(path: str) -> tuple:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)

    # ---------- 个股行情 ----------
    def load_market_data(self, start: str, end: str,
                         columns=DEFAULT_COLUMNS) -> pd.DataFrame:
        """读取 [start, end] 内的个股行情（默认四列），带缓存。返回副本可自由修改。"""
        key = (self._file_key(self.adj_file), start, end, tuple(columns))
        if key in self._market_cache:
            return self._market_cache[key].copy()
        df = pd.read_parquet(
            self.adj_file, columns=list(columns),
            filters=[("trade_date", ">=", start), ("trade_date", "<=", end)])
        df["trade_date"] = df["trade_date"].astype(str)
        self._market_cache[key] = df
        if len(self._market_cache) > _CACHE_MAX:
            self._market_cache.pop(next(iter(self._market_cache)))
        return df.copy()

    # ---------- 指数行情 ----------
    def load_index(self, start: str, end: str) -> pd.DataFrame:
        """读取 [start, end] 内的指数行情（trade_date, close）。"""
        key = self._file_key(self.index_file)
        if self._index_key != key:
            idx = pd.read_parquet(self.index_file)
            idx["trade_date"] = idx["trade_date"].astype(str)
            self._index_cache = idx
            self._index_key = key
        idx = self._index_cache
        mask = (idx["trade_date"] >= start) & (idx["trade_date"] <= end)
        return idx.loc[mask, ["trade_date", "close"]].copy()

    # ---------- 最新交易日 ----------
    def latest_trade_date(self) -> str:
        """从 parquet 元数据统计量取 trade_date 最大值（不扫描数据）。

        统计量不可用时退回单列扫描。返回 YYYYMMDD 字符串。
        """
        key = self._file_key(self.adj_file)
        if self._latest_key == key:
            return self._latest_value
        latest = self._stats_max_trade_date() or self._scan_max_trade_date()
        self._latest_key, self._latest_value = key, latest
        return latest

    def _stats_max_trade_date(self):
        try:
            pf = pq.ParquetFile(self.adj_file)
            col_idx = pf.schema.names.index("trade_date")
            best = None
            for i in range(pf.metadata.num_row_groups):
                stats = pf.metadata.row_group(i).column(col_idx).statistics
                if stats is None or stats.max is None:
                    continue
                v = stats.max.decode("utf-8") if isinstance(stats.max, bytes) else str(stats.max)
                if best is None or v > best:
                    best = v
            return best
        except Exception:
            return None

    def _scan_max_trade_date(self) -> str:
        df = pd.read_parquet(self.adj_file, columns=["trade_date"])
        return str(df["trade_date"].max())

    # ---------- 最新价格（持仓估值用，原始 close，不复权） ----------
    def load_latest_prices(self, codes=None) -> pd.DataFrame:
        """最新交易日的原始收盘价：DataFrame[ts_code, trade_date, close]。

        codes 为 None 时返回全部有当日行情的股票；否则只返回指定代码。
        """
        latest = self.latest_trade_date()
        cols = ["ts_code", "trade_date", "close"]
        filters = [("trade_date", "==", latest)]
        if codes:
            filters.append(("ts_code", "in", list(codes)))
        df = pd.read_parquet(self.adj_file, columns=cols, filters=filters)
        df["trade_date"] = df["trade_date"].astype(str)
        return df

    # ---------- 数据状态（Web App 数据管理页/首页用，全部走元数据统计量，不扫全表） ----------
    def data_status(self) -> dict:
        """各数据文件的最新交易日与最新日行数，返回：
        {file_key: {"latest": YYYYMMDD 或 None, "rows_latest": int 或 None}}。

        file_key: raw / adj_factor / adj / index / calendar。
        用 parquet 元数据统计量取最大值，失败时退回单列扫描；文件缺失时值为 None。
        """
        def file_latest(filepath, date_col="trade_date"):
            if not os.path.exists(filepath):
                return {"latest": None, "rows_latest": None}
            latest = self._stats_max_trade_date_file(filepath, date_col)
            if latest is None:
                try:
                    df = pd.read_parquet(filepath, columns=[date_col])
                    latest = str(df[date_col].max())
                except Exception:
                    return {"latest": None, "rows_latest": None}
            try:
                count = pd.read_parquet(
                    filepath, columns=[date_col],
                    filters=[(date_col, "==", latest)]).shape[0]
            except Exception:
                count = None
            return {"latest": latest, "rows_latest": count}

        return {
            "raw": file_latest(RAW_FILE),
            "adj_factor": file_latest(FCT_FILE),
            "adj": file_latest(ADJ_FILE),
            "index": file_latest(INDEX_FILE),
            "calendar": file_latest(CALENDAR_FILE, date_col="cal_date"),
        }

    def _stats_max_trade_date_file(self, filepath: str, date_col: str):
        """取 filepath 的 date_col 列最大值（走元数据统计量），失败返回 None。"""
        try:
            pf = pq.ParquetFile(filepath)
            col_idx = pf.schema.names.index(date_col)
            best = None
            for i in range(pf.metadata.num_row_groups):
                stats = pf.metadata.row_group(i).column(col_idx).statistics
                if stats is None or stats.max is None:
                    continue
                v = stats.max.decode("utf-8") if isinstance(stats.max, bytes) else str(stats.max)
                if best is None or v > best:
                    best = v
            return best
        except Exception:
            return None

    # ---------- 日历状态（数据是否最新判断用） ----------
    def calendar_status(self, today: str = None) -> dict:
        """返回 {"latest_open": 最近开盘日(≤today), "today_open": 今日是否开盘,
        "max_cal": 日历最大覆盖日}；日历文件缺失时各值为 None。"""
        today = today or pd.Timestamp.today().strftime("%Y%m%d")
        if not os.path.exists(CALENDAR_FILE):
            return {"latest_open": None, "today_open": None, "max_cal": None}
        try:
            cal = pd.read_parquet(CALENDAR_FILE)
            cal["cal_date"] = cal["cal_date"].astype(str)
            if "is_open" not in cal.columns:
                cal["is_open"] = 1
            open_dates = set(cal.loc[cal["is_open"] == 1, "cal_date"])
            recent = sorted(d for d in open_dates if d <= today)
            return {
                "latest_open": recent[-1] if recent else None,
                "today_open": today in open_dates,
                "max_cal": str(cal["cal_date"].max()),
            }
        except Exception:
            return {"latest_open": None, "today_open": None, "max_cal": None}

    # ---------- 股票名称 ----------
    def stock_names(self) -> dict:
        """{ts_code: 名称}。列表文件缺失/损坏时返回 {}（引擎跳过股票池过滤）。"""
        if not os.path.exists(self.stock_list_file):
            return {}
        key = self._file_key(self.stock_list_file)
        if self._names_key != key:
            try:
                sl = pd.read_csv(self.stock_list_file)
                self._names_cache = dict(zip(sl["ts_code"], sl["name"]))
                self._names_key = key
            except Exception:
                self._names_cache = {}
        return dict(self._names_cache or {})
