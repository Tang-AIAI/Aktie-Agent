"""Strategy C（Quality 质量）：设计说明（暂未实现——缺少历史 PIT 财务数据）。

设计定义（baseline，未来接入数据后实现）：
- 目标：衡量盈利能力、盈利稳定性与财务质量
- 候选因子：ROE（净资产收益率，越高越好）、毛利率（越高越好）、
  盈利稳定性（近 N 期 ROE 标准差，越低越好）、资产负债率（越低越好）
- 权重（暂定）：ROE 40% / 毛利率 20% / 盈利稳定性 20% / 资产负债率 20%
  （仅为设计基线，不代表最优）

数据要求（当前全部缺失，见 PROJECT_CONTEXT.md「数据可用性审计」）：
- 历史财务报表数据（资产负债表/利润表，Tushare fina_indicator 等），且必须
  按**报告期公布时点**使用（PIT）：例如 2024Q3 财报只能在公告日后使用，
  不能把全年报数据用于公告之前的时点（未来数据泄漏）
- 可靠的历史退市股覆盖（财务数据与行情同日同范围）

按用户要求：数据不足时不伪造、不接入不可靠数据、不产生虚假回测结果。
本类只完成策略接口与设计说明（data_available=False，引擎/回测页会明确显示原因）。
"""

from quant.strategies.base import Strategy


class StrategyC(Strategy):
    name = "strategy_c"
    label = "Strategy C（Quality 质量）"
    description = ("质量 baseline：ROE/毛利率/盈利稳定性选股。因缺少历史 PIT 财务数据"
                   "暂未实现，不产生回测结果。")
    factor_names = ()                       # 待数据接入后填：roe / gross_margin / ...
    default_weights = {}
    default_windows = {}
    data_available = False
    unavailable_reason = (
        "Strategy C（Quality）暂不能可靠实现：缺少历史 PIT 财务数据。"
        "当前数据仅含行情类字段（OHLCV/amount/复权因子），无 ROE/毛利率/负债率等"
        "财报数据；且财务数据必须按报告期公告时点使用（PIT），不能提前使用未来财报，"
        "故不实现、不回测。")
    data_requirements = {
        "roe（按报告期公告时点，PIT）": "净资产收益率：财报公告日之后才可用于该时点",
        "gross_margin（按报告期公告时点，PIT）": "毛利率：同上",
        "roe_volatility（近 N 期，PIT）": "盈利稳定性：近 N 期 ROE 标准差，越低越好",
        "debt_to_assets（按报告期公告时点，PIT）": "资产负债率：越低越好",
    }
