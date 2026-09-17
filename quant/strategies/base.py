"""策略基类：只声明配置（因子/权重/窗口/标准化方法），计算流程统一在 quant/engine.py。

新增策略：继承本类 + 填入 factor_names / default_weights / default_windows，
并在 quant/strategies/__init__.py 注册即可复用整套引擎与页面。
"""

from quant.factors.registry import get_factor


class Strategy:
    name: str = ""                 # 注册名（页面/入口用）
    label: str = ""                # 展示名
    description: str = ""
    factor_names: tuple = ()       # 因子注册名（顺序即展示顺序）
    default_weights: dict = {}     # 各因子默认权重（自动归一化到 1）
    default_windows: dict = {}     # 各因子默认窗口参数
    standardize_method: str = "zscore"   # 横截面标准化方法：zscore / rank
    drop_na_factors: bool = True         # 任一因子无法计算（NaN）即排除出排名
    require_as_of_row: bool = True       # 要求计算日有当日行情（排除停牌/退市股票）
    use_stock_list: bool = True          # 股票池是否限定在 stock_list.csv；
                                         # 历史回测用 False（PIT 股票池：当日有行情即在池，
                                         # 避免用当前列表排除历史退市股 → 幸存者偏差）
    data_available: bool = True          # False = 设计已就绪但依赖的历史数据不可用：
                                         # 引擎拒绝运行，页面显示 unavailable_reason，
                                         # 不产生虚假回测结果
    unavailable_reason: str = ""         # data_available=False 时的原因（页面展示）
    data_requirements: dict = {}         # 数据依赖声明（接口约定，设计文档用）：
                                         # {数据字段: 说明（含 PIT 要求）}

    def __init__(self, weights: dict = None, windows: dict = None,
                 use_stock_list: bool = None):
        if use_stock_list is not None:
            self.use_stock_list = bool(use_stock_list)
        if not self.data_available:      # 设计壳：无因子可解析，weights/windows 为空
            self.weights, self.windows = {}, {}
            return
        self.weights = self._resolve_weights(weights)
        self.windows = self._resolve_windows(windows)

    def _resolve_weights(self, weights: dict) -> dict:
        """合并默认权重 → 校验非负且总和 > 0 → 归一化到和为 1。"""
        w = dict(self.default_weights)
        w.update(weights or {})
        unknown = set(w) - set(self.factor_names)
        if unknown:
            raise ValueError(f"策略 {self.name} 不含因子 {sorted(unknown)}")
        if any(v < 0 for v in w.values()):
            raise ValueError(f"策略 {self.name} 权重不能为负: {w}")
        total = sum(w.values())
        if total <= 0:
            raise ValueError(f"策略 {self.name} 权重总和必须大于 0")
        return {f: w[f] / total for f in self.factor_names}

    def _resolve_windows(self, windows: dict) -> dict:
        """合并默认窗口 → 按因子元数据校验（个数/下限/自定义约束）。"""
        out = {}
        for fname in self.factor_names:
            default = get_factor(fname).default_windows
            val = windows.get(fname, default) if windows else default
            val = tuple(int(v) for v in val)
            get_factor(fname).check_windows(val)
            out[fname] = val
        return out
