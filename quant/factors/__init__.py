"""因子包：导入各因子模块即完成注册（副作用导入，勿删）。

新增因子：在本包下新建模块（参照 momentum.py），在此导入即可被策略使用。
"""

from quant.factors.registry import all_factors, get_compute, get_factor, register  # noqa: F401

from quant.factors import (  # noqa: F401,E402
    momentum,
    relative_strength,
    short_term_reversal,
    trend,
    volatility,
    volume_trend,
)
