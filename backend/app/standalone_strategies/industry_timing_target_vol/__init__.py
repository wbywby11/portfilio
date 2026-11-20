"""行业择时目标波动（industry_timing_target_vol）：打包独立形态的目标波动打底 + 三形态时点行业 + DAR 成长控仓策略."""

from app.standalone_strategies.industry_timing_target_vol.strategy import (
    IndustryTimingTargetVolStrategy,
)

__all__ = ["IndustryTimingTargetVolStrategy"]
