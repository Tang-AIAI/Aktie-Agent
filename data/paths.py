"""数据文件路径集中定义。

所有数据文件（parquet 与状态 txt）统一放在项目根目录，
任何入口（scripts/、app/、quant/）都从这里取路径，避免 cwd 依赖。
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 个股数据
RAW_FILE = str(BASE_DIR / "market_data_raw.parquet")      # 原始日线（Tushare daily 全字段）
FCT_FILE = str(BASE_DIR / "adj_factor.parquet")           # 复权因子
ADJ_FILE = str(BASE_DIR / "market_data_adj.parquet")      # 前复权数据

# 指数数据
INDEX_FILE = str(BASE_DIR / "index_data.parquet")         # 沪深300 日线

# 交易日历（缓存）
CALENDAR_FILE = str(BASE_DIR / "trade_calendar.parquet")

# 股票列表
STOCK_LIST_FILE = str(BASE_DIR / "stock_list.csv")

# 断点续传状态
PROGRESS_FILE = str(BASE_DIR / "download_progress.txt")   # 已完成交易日集合
FAILED_FILE = str(BASE_DIR / "failed_dates.txt")          # 失败日期记录

# Web App 本地状态
POSITIONS_FILE = str(BASE_DIR / "positions.csv")          # 手工维护持仓（csv，UTF-8）
SCREENER_STATE_FILE = str(BASE_DIR / "screener_state.json")  # 条件选股最近一次条件
