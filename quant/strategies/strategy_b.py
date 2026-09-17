"""Strategy B（Value 价值）：设计说明（暂未实现——缺少历史 PIT 估值数据）。

设计定义（baseline，未来接入数据后实现）：
- 目标：选择估值较低的股票（低 PE / 低 PB / 低 PS 等）
- 候选因子：PE_TTM（滚动市盈率，越低越好）、PB（市净率，越低越好）、
  股息率（越高越好）——取当日可得的最新报告期口径，避免使用未来财报
- 权重（暂定）：PE_TTM 50% / PB 30% / 股息率 20%（仅为设计基线，不代表最优）

数据要求（当前全部缺失，见 PROJECT_CONTEXT.md「数据可用性审计」）：
- 逐日逐股的 PE/PB/市值等估值数据（如 Tushare daily_basic），且必须是
  **当日实际公布值**（PIT）：不能用"今天的 PE 历史序列"回填过去（那等价于
  用最新财报重算历史时点，属未来数据泄漏）
- 可靠的历史退市股覆盖（估值数据与行情同日同范围）

按用户要求：数据不足时不伪造、不接入不可靠数据、不产生虚假回测结果。
本类只完成策略接口与设计说明（data_available=False，引擎/回测页会明确显示原因）。
"""

from quant.strategies.base import Strategy


class StrategyB(Strategy):
    name = "strategy_b"
    label = "Strategy B（Value 价值）"
    description = ("价值 baseline：低 PE/PB 选股。因缺少历史 PIT 估值数据"
                   "（PE/PB/市值等）暂未实现，不产生回测结果。")
    factor_names = ()                       # 待数据接入后填：pe_ttm / pb / dividend_yield
    default_weights = {}
    default_windows = {}
    data_available = False
    unavailable_reason = (
        "Strategy B（Value）暂不能可靠实现：缺少历史 PIT 估值数据。"
        "当前数据仅含行情类字段（OHLCV/amount/复权因子），无逐日 PE/PB/市值等估值字段；"
        "用今日数据回填历史会引入未来数据泄漏，故不实现、不回测。")
    data_requirements = {
        "pe_ttm（逐日逐股，PIT）": "滚动市盈率：必须为当日实际可得值，禁止用当前值回填历史",
        "pb（逐日逐股，PIT）": "市净率：同上",
        "dv_ratio（逐日逐股，PIT）": "股息率：同上",
        "total_mv（逐日逐股，PIT）": "总市值：可选，用于市值暴露控制",
    }
