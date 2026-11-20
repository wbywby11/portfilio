"""红利 GARP 增强（dividend_garp）：打包独立形态的红利估值防守 + 成长趋势 + 波动率控制策略."""

from app.standalone_strategies.dividend_garp.strategy import DividendGarpStrategy

__all__ = ["DividendGarpStrategy"]
