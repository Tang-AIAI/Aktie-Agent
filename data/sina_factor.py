"""新浪 qfq.js 因子链解析与合成（Tushare 因子风格的替代来源）。

背景（2026-09-15 调查实证）：
- 新浪 https://finance.sina.com.cn/realstock/company/<code>/qfq.js 返回
  每只股票的除权因子链（日期倒序，最新事件在前，末尾为 1900-01-01 哨兵）。
- 新浪事件跳变与 Tushare adj_factor 跳变吻合 ≤0.03%（高送转/分红/北交所实测）。
- 合成规则：以股票最后一条 Tushare 因子 (d0, F0) 为锚点，
  F(d) = F0 × f(d0)/f(d)，其中 f 为新浪链在日期 d 的取值。
  无 Tushare 锚点时（次新股）以上市日为 d0、F0=1.0。
"""

import json
from typing import List, Tuple


def parse_chain(text: str) -> List[Tuple[str, float]]:
    """解析 qfq.js 响应文本，返回 (日期YYYYMMDD, 因子) 列表（日期倒序）。"""
    js = text[text.find("{") : text.rfind("}") + 1]
    data = json.loads(js)["data"]
    rows = [(str(x["d"]).replace("-", ""), float(x["f"])) for x in data]
    return sorted(rows, key=lambda r: r[0], reverse=True)


def factor_at(chain: List[Tuple[str, float]], date: str) -> float:
    """日期 date（YYYYMMDD）对应的新浪因子 f：链中最新且 <= date 的事件值。"""
    for ex_date, f in chain:
        if ex_date <= date:
            return f
    return chain[-1][1]


def synth_factors(chain: List[Tuple[str, float]], dates: List[str],
                  d0: str, F0: float) -> List[Tuple[str, float]]:
    """合成 (d0, 今天] 区间内各交易日的 Tushare 风格因子。

    :param chain: parse_chain 的输出（日期倒序）
    :param dates: 需要合成的交易日列表（升序）
    :param d0: 锚点日期（最后一条 Tushare 因子日期，或上市日）
    :param F0: 锚点因子值（无 Tushare 数据时为 1.0）
    :return: [(trade_date, adj_factor)]，不含 d0 当日
    """
    gap = [d for d in dates if d > d0]
    if not gap:
        return []
    f_d0 = factor_at(chain, d0)
    if f_d0 <= 0:
        raise ValueError(f"新浪因子异常：f({d0})={f_d0}")
    out = []
    for d in gap:
        fd = factor_at(chain, d)
        if fd <= 0:
            raise ValueError(f"新浪因子异常：f({d})={fd}")
        out.append((d, F0 * f_d0 / fd))
    return out
