"""因子注册表：策略按 name 取因子，新增因子只需实现模块并在 __init__.py 导入。"""

from typing import Callable

from quant.factors.base import Factor

_REGISTRY: dict = {}   # name -> (Factor, compute)


def register(factor: Factor, compute: Callable) -> None:
    """注册因子。compute 签名见 quant/factors/base.py。"""
    if factor.name in _REGISTRY:
        raise ValueError(f"因子 {factor.name} 重复注册")
    _REGISTRY[factor.name] = (factor, compute)


def get_factor(name: str) -> Factor:
    if name not in _REGISTRY:
        raise KeyError(f"未注册的因子: {name}（已注册: {sorted(_REGISTRY)}）")
    return _REGISTRY[name][0]


def get_compute(name: str) -> Callable:
    if name not in _REGISTRY:
        raise KeyError(f"未注册的因子: {name}（已注册: {sorted(_REGISTRY)}）")
    return _REGISTRY[name][1]


def all_factors() -> list:
    """按注册顺序返回全部因子描述。"""
    return [f for f, _ in _REGISTRY.values()]
