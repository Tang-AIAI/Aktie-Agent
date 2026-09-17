"""因子定义规范：静态元数据（名称/方向/默认窗口/说明）+ 可选窗口约束。"""

from dataclasses import dataclass
from typing import Callable, Optional

HIGHER_BETTER = "higher_better"   # 越高越好
LOWER_BETTER = "lower_better"     # 越低越好


@dataclass(frozen=True)
class Factor:
    """一个因子的静态描述。

    compute 约定签名（在 registry 注册时绑定）：
        compute(market, windows, *, index=None, as_of=None) -> pd.Series
      market: 长表 DataFrame（ts_code, trade_date, close_adj, vol，按需取列）
      windows: 该因子的窗口参数 tuple，与 default_windows 等长
      index: 指数行情（trade_date, close），仅依赖指数的因子使用
      as_of: 计算日期 YYYYMMDD
      返回：以 ts_code 为索引的原始因子值 Series；无法计算（数据不足）为 NaN
    """

    name: str
    label: str
    direction: str
    default_windows: tuple
    description: str = ""
    short_label: str = ""        # 表格/图表里的简短展示名（缺省用 label）
    validate_windows: Optional[Callable[[tuple], None]] = None
    needs_index: bool = False    # 计算是否依赖指数数据（如沪深300）；
                                 # 引擎据此决定是否必须加载指数（不依赖指数的策略
                                 # 可在指数数据覆盖范围之外的历史区间运行）

    def check_windows(self, windows: tuple) -> None:
        """窗口参数校验：个数一致 + 每个 ≥ 2 + 因子自定义约束。"""
        if len(windows) != len(self.default_windows):
            raise ValueError(
                f"因子 {self.name} 需要 {len(self.default_windows)} 个窗口参数，收到 {len(windows)} 个")
        if any(w < 2 for w in windows):
            raise ValueError(f"因子 {self.name} 窗口参数必须 ≥ 2")
        if self.validate_windows:
            self.validate_windows(windows)
