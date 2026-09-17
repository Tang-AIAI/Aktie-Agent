"""Short-term Reversal 因子：近 W 个交易日收益率，越低越好（跌幅越大 → 反转评分越高）。

计算函数与 momentum 完全相同（同一函数复用，保证口径一致），仅方向相反：
- momentum：同一 W 日收益，越高越好（追涨）
- short_term_reversal：同一 W 日收益，越低越好（超跌反弹）
两者是同一定义的两种用法，见 quant/factors/momentum.py。
"""

from quant.factors.base import LOWER_BETTER, Factor
from quant.factors.momentum import compute
from quant.factors.registry import register

FACTOR = Factor(
    name="short_term_reversal",
    label="短期反转（W 日收益，越低越好）",
    short_label="短期反转",
    direction=LOWER_BETTER,
    default_windows=(5,),
    description="近 W 个交易日收益率（前复权收盘价比值 − 1，与 momentum 同口径），"
                "越低越好：近期跌幅越大的股票反转评分越高。",
)

register(FACTOR, compute)
