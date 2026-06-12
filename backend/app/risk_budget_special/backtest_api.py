# -*- coding: utf-8 -*-
"""
[THIN WRAPPER] 本文件已重构为转发层。
实际实现位于:
  - app.backtesting.hybrid_momentum_engine  (HybridMomentumConfig, run_hybrid_momentum_backtest)
  - app.backtesting.hybrid_momentum_export  (export_all, _resolve_reference_weight_path)

保留此文件是为了兼容现有的 import 路径：
  - app/api/asset_index.py   → run_hybrid_momentum_backtest, HybridMomentumConfig
  - app/api/backtests.py     → run_hybrid_momentum_backtest, HybridMomentumConfig (fallback)
  - app/api/backtests.py     → export_all, _resolve_reference_weight_path
"""

from app.backtesting.hybrid_momentum_engine import (
    HybridMomentumConfig,
    run_hybrid_momentum_backtest,
)
from app.backtesting.hybrid_momentum_export import (
    export_all,
    _resolve_reference_weight_path,
)

__all__ = [
    "HybridMomentumConfig",
    "run_hybrid_momentum_backtest",
    "export_all",
    "_resolve_reference_weight_path",
]
