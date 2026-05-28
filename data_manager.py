"""
data_manager.py
统一数据接口：指数日线数据
支持 Tushare Pro（主力） + AkShare（备用）
返回标准 OHLCV 字段
"""

import akshare as ak
import pandas as pd
import tushare as ts
from typing import Optional
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class DataManager:
    def __init__(self, tushare_token: str):
        """
        初始化数据管理器
        :param tushare_token: Tushare Pro 的 token（字符串）
        """
        ts.set_token(tushare_token)
        self.pro = ts.pro_api()

    @staticmethod
    def _format_date(date_str: str) -> str:
        """将 '2025-01-01' 或 '20250101' 统一转为 '20250101' 字符串"""
        return date_str.replace('-', '')

    @staticmethod
    def _standardize_columns(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
        """
        统一列名和字段子集
        输入 df 必须包含：date/trade_date, open, high, low, close, volume/vol
        输出列：ts_code, trade_date, open, high, low, close, vol
        """
        # 重命名
        rename_map = {}
        if 'date' in df.columns:
            rename_map['date'] = 'trade_date'
        if 'volume' in df.columns:
            rename_map['volume'] = 'vol'

        if rename_map:
            df.rename(columns=rename_map, inplace=True)

        # 确保 trade_date 为字符串且格式 YYYYMMDD
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')

        # 只保留必要字段
        keep_cols = ['trade_date', 'open', 'high', 'low', 'close', 'vol']
        existing_cols = [c for c in keep_cols if c in df.columns]
        df = df[existing_cols].copy()
        df['ts_code'] = ts_code

        # 调整列顺序
        final_cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol']
        df = df[final_cols]
        return df

    def get_index_daily(self, ts_code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取指数日线数据（OHLCV）
        :param ts_code: 指数代码，如 '000300.SH'
        :param start_date: 起始日期，支持 '2025-01-01' 或 '20250101'
        :param end_date: 结束日期，同上
        :return: DataFrame，列为 ts_code, trade_date, open, high, low, close, vol；失败返回 None
        """
        # 统一日期格式为 YYYYMMDD（用于 Tushare）
        start_fmt = self._format_date(start_date)
        end_fmt = self._format_date(end_date)

        # ---------- 1. 尝试 Tushare Pro ----------
        try:
            logging.info(f"[Tushare] 请求 {ts_code} 数据，日期 {start_fmt} -> {end_fmt}")
            df = self.pro.index_daily(ts_code=ts_code, start_date=start_fmt, end_date=end_fmt)
            if df is not None and not df.empty:
                df = self._standardize_columns(df, ts_code)
                logging.info(f"[Tushare] 成功获取 {len(df)} 条记录")
                return df
            else:
                logging.warning("[Tushare] 返回空数据")
        except Exception as e:
            logging.warning(f"[Tushare] 请求失败: {e}")

        # ---------- 2. 降级：AkShare ----------
        logging.info(f"[AkShare] 降级使用，获取 {ts_code} 数据")
        try:
            # AkShare 指数代码转换：'000300.SH' -> 'sh000300', '399300.SZ' -> 'sz399300'
            if ts_code.endswith('.SH'):
                symbol = f"sh{ts_code.split('.')[0]}"
            elif ts_code.endswith('.SZ'):
                symbol = f"sz{ts_code.split('.')[0]}"
            else:
                # 默认沪深300
                symbol = "sh000300"
                logging.warning(f"[AkShare] 未知指数后缀，使用默认 {symbol}")

            # 获取全量历史数据（akshare 不支持日期参数，需后过滤）
            df_ak = ak.stock_zh_index_daily(symbol=symbol)
            if df_ak is None or df_ak.empty:
                logging.warning("[AkShare] 返回空数据")
                return None

            # 日期筛选：统一转为 datetime 再比较（避免字符串比较的不确定性）
            df_ak['date'] = pd.to_datetime(df_ak['date'])
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            mask = (df_ak['date'] >= start_dt) & (df_ak['date'] <= end_dt)
            df_ak = df_ak.loc[mask].copy()

            if df_ak.empty:
                logging.warning("[AkShare] 筛选后无数据")
                return None

            # 标准化
            df_ak = self._standardize_columns(df_ak, ts_code)
            logging.info(f"[AkShare] 成功获取 {len(df_ak)} 条记录")
            return df_ak

        except Exception as e:
            logging.error(f"[AkShare] 请求失败: {e}")
            return None


# 简单测试（可选，运行时可注释）
if __name__ == "__main__":
    # 测试代码（需要替换成真实 token）
    dm = DataManager(tushare_token="你的token")
    df = dm.get_index_daily("000300.SH", "2025-01-01", "2025-12-31")
    if df is not None:
        print(df.head())
    else:
        print("获取数据失败")