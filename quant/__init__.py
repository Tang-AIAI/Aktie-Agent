"""量化引擎：因子计算（factors/）、横截面标准化、策略配置（strategies/）与排名执行（engine）。

数据来源只通过 quant/market_data.py 的 MarketDataLoader 按日期区间 + 列裁剪
读取 parquet，不把全量历史读入内存。
"""
