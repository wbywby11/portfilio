"""
期权定价核心模块 —— 兼容再导出层（P9 治理拆分）.

原单一实现已按职责拆分为三个模块：
- app.options.pricing_vanilla：基础工具/参数结构/欧式香草/价差/二元/障碍/固收
- app.options.pricing_exotic：雪球/凤凰/双鲨/亚式/彩虹/区间累积/可赎回固收/数字区间
- app.options.pricing_numeric：二叉树/有限差分/SABR/局部波动率

本文件仅维持既有导入面（from app.options.core import ...），
兼容 dispatcher.py 与 scripts，不含任何逻辑。
"""

from app.options.pricing_vanilla import (
    MarketParams,
    PricingResult,
    OptionPricer,
    SpreadOptionPricer,
    BinaryOptionPricer,
    BarrierOptionPricer,  # noqa: F401
    FixedIncomePricer,  # noqa: F401
)
from app.options.pricing_exotic import (
    SnowballParams,  # noqa: F401
    SnowballPricer,  # noqa: F401
    PhoenixParams,  # noqa: F401
    PhoenixPricer,  # noqa: F401
    DoubleBarrierPricer,  # noqa: F401
    AsianParams,  # noqa: F401
    AsianOptionPricer,  # noqa: F401
    RainbowParams,  # noqa: F401
    RainbowPricer,  # noqa: F401
    RangeAccrualParams,  # noqa: F401
    RangeAccrualPricer,  # noqa: F401
    CallableFixedParams,  # noqa: F401
    CallableFixedPricer,  # noqa: F401
    DigitalRangeParams,  # noqa: F401
    DigitalRangePricer,  # noqa: F401
)
from app.options.pricing_numeric import (
    BinomialTreeParams,  # noqa: F401
    BinomialTreePricer,  # noqa: F401
    FiniteDifferenceParams,  # noqa: F401
    FiniteDifferencePricer,  # noqa: F401
    SABRParams,  # noqa: F401
    SABRVolSurface,  # noqa: F401
    LocalVolParams,  # noqa: F401
    LocalVolPricer,  # noqa: F401
)

__all__ = ["OptionPricer", "MarketParams", "PricingResult"]


if __name__ == "__main__":
    # 示例参数
    p = MarketParams(spot=100, strike=100, tau=0.5, vol=0.20, r=0.03, q=0.01)

    pricer = OptionPricer()

    # 看涨期权
    call_r = pricer.call(p)
    put_r = pricer.put(p)
    print(f"看涨期权:  {call_r}")
    print(f"看跌期权:  {put_r}")

    # 数值 vs 解析希腊字母对比
    num = pricer.numerical_greeks(p)
    print(f"\n数值希腊字母 (差分法): {num}")
    print(f"解析希腊字母         : {call_r}")

    # 二元期权
    binary = BinaryOptionPricer()
    print(f"\n二元看涨: {binary.call(p):.6f}")
    print(f"二元看跌: {binary.put(p):.6f}")

    # 价差期权
    spread = SpreadOptionPricer()
    s = spread.call_spread(p, k_high=110)
    print(f"\n看涨价差 (100-110): price={s.price:.6f}")
