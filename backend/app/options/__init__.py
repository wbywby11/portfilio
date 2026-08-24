# -*- coding: utf-8 -*-
"""收益凭证估值模块 (Structured Product Valuation)

计算逻辑从 options_pricing 原型迁入，核心定价算法保持不变。

模块结构:
- core: 期权定价核心（8个Pricer类）
- risk: 情景分析/压力测试/P&L归因
- vol: 波动率曲面插值 + 隐含波动率
- config: 参数常量
- data_provider: MongoDB 数据提供者
- dispatcher: 定价派发器（ValuationRecord + PricingDispatcher）
"""
