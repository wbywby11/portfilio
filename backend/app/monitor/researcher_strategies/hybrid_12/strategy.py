"""12资产混合动量+风险预算目标波动策略 - 策略元数据定义

迁自 monitor/config.py 主参数表（ASSET_LIST + MOMENTUM/REVERSAL 参数）。
三层引擎表达：
  Selection: momentum_reversal（7+1）
  Allocation: vol_scaled_budget（tag_based 标签等分预算）
  Control: rolling_vol（组合波动率监控 + 紧急降杠杆）
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.monitor.researcher_strategies.base import ResearcherStrategyBase


class HybridMomentum12Strategy(ResearcherStrategyBase):
    """12资产混合动量+风险预算目标波动策略。

    原 monitor/config.py 中的主策略：
    - 12 资产宇宙（A股/港股/美股/欧股/国债/商品）
    - 动量因子选 7 + 反转因子选 1
    - 标签等分风险预算 × 目标波动率定标
    - 组合波动率超 6% 触发紧急降杠杆
    """

    @property
    def code(self) -> str:
        return "hybrid_12"

    @property
    def display_name(self) -> str:
        return "混合动量12（目标波动5%）"

    @property
    def description(self) -> str:
        return (
            "12资产宇宙，动量(7)+反转(1)选择，"
            "标签等分风险预算 × 目标波动率5%定标，"
            "组合波动率6%触发降杠杆，杠杆上限4倍"
        )

    @property
    def asset_codes(self) -> List[str]:
        return [
            "000300.SH",  # 沪深300
            "SZ399006",   # 创业板指
            "ZZ000001",   # 红利低波
            "HSTECH",     # 恒生科技
            "SPX",        # 标普500
            "GDAXI",      # 德国DAX
            "ZQGZ10",     # 中国10年国债
            "ZQGZ2",      # 中国2年国债
            "B00Y",       # 布伦特原油
            "GLD",        # 黄金
            "IRON",       # 铁矿石
            "YSJS",       # 中国有色金属
        ]

    @property
    def asset_name_map(self) -> Dict[str, str]:
        return {
            "000300.SH": "沪深300",
            "SZ399006": "创业板指",
            "ZZ000001": "红利低波",
            "HSTECH": "恒生科技",
            "SPX": "标普500",
            "GDAXI": "德国DAX",
            "ZQGZ10": "中国10年国债",
            "ZQGZ2": "中国2年国债",
            "B00Y": "布伦特原油",
            "GLD": "黄金",
            "IRON": "铁矿石",
            "YSJS": "中国有色金属",
        }

    @property
    def weight_caps(self) -> Dict[str, float]:
        return {
            "000300.SH": 0.10,
            "SZ399006": 0.10,
            "ZZ000001": 0.10,
            "HSTECH": 0.10,
            "SPX": 0.15,
            "GDAXI": 0.10,
            "ZQGZ10": 0.60,
            "ZQGZ2": 0.90,
            "B00Y": 0.10,
            "GLD": 0.10,
            "IRON": 0.10,
            "YSJS": 0.10,
        }

    @property
    def trading_costs(self) -> Dict[str, float]:
        """交易费率（单次调仓），写死在本策略内，不依赖全局 config。"""
        return {
            "000300.SH": 0.0003,
            "SZ399006": 0.0003,
            "ZZ000001": 0.0003,
            "HSTECH": 0.0005,
            "SPX": 0.0002,
            "GDAXI": 0.0002,
            "ZQGZ10": 0.0003,
            "ZQGZ2": 0.0003,
            "B00Y": 0.0001,
            "GLD": 0.0003,
            "IRON": 0.0003,
            "YSJS": 0.0003,
        }

    @property
    def replication_costs(self) -> Dict[str, float]:
        """复制费率（年化），写死在本策略内，不依赖全局 config。"""
        return {
            "000300.SH": 0.0040,
            "SZ399006": 0.0300,
            "ZZ000001": 0.0300,
            "HSTECH": 0.0200,
            "SPX": 0.0060,
            "GDAXI": 0.0070,
            "ZQGZ10": 0.0030,
            "ZQGZ2": 0.0030,
            "B00Y": 0.0060,
            "GLD": 0.0060,
            "IRON": 0.0060,
            "YSJS": 0.0060,
        }

    @property
    def composition(self) -> Dict[str, Any]:
        return {
            "selector": "momentum_reversal",
            "allocator": "vol_scaled_budget",
            "controller": "rolling_vol",
            "schedule": {
                "rebalance_freq": "month_end",
                "execution_delay": 2,
            },
            "selection_params": {
                "n_momentum": 7,
                "n_reversal": 1,
                "momentum_windows": "20,60,120,250",
                "macd_windows": "40,80,120,160",
                "reversal_windows": "10,22",
                "min_history_days": 260,
                "min_history_reversal": 22,
            },
        }

    @property
    def strategy_params(self) -> Dict[str, Any]:
        return {
            # ── 分配器参数（VolScaledBudgetStrategy / tag_based）──
            "budget_source": "tag_based",
            "target_vol": 0.05,
            "max_total_leverage": 4.0,
            "vol_windows": "22,65,130",
            "min_history_days": 260,
            "lookback_days": 260,
            "enable_vol_reset": True,
            "vol_reset_threshold": 0.06,
            # ── 选择器参数（Pipeline 路由到 momentum_reversal）──
            "n_momentum": 7,
            "n_reversal": 1,
            "momentum_windows": "20,60,120,250",
            "macd_windows": "40,80,120,160",
            "reversal_windows": "10,22",
            "min_history_reversal": 22,
        }
