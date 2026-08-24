"""18资产夏普率风险预算策略 - 策略元数据定义

迁自 monitor/config.py SHARPE 参数表（SHARPE_ASSET_LIST + SHARPE_* 参数）。
三层引擎表达：
  Selection: sharpe（3窗口综合打分，选13）
  Allocation: vol_scaled_budget（selection_equal 等权预算）
  Control: rolling_vol（组合波动率监控 + 紧急降杠杆）
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.monitor.researcher_strategies.base import ResearcherStrategyBase


class SharpeBudget18Strategy(ResearcherStrategyBase):
    """18资产夏普率风险预算策略。

    原 monitor/config.py 中的夏普率策略：
    - 18 资产宇宙（A股/美股/日股/中美国债/可转债/商品/金属/农产品）
    - 3窗口夏普率综合打分选 13 个
    - 选中资产等权预算 1/N × 目标波动率定标
    - 组合波动率超 6% 触发紧急降杠杆
    """

    @property
    def code(self) -> str:
        return "sharpe_18"

    @property
    def display_name(self) -> str:
        return "夏普率18（目标波动5%）"

    @property
    def description(self) -> str:
        return (
            "18资产宇宙，夏普率3窗口打分选13，"
            "等权预算 × 目标波动率5%定标，"
            "组合波动率6%触发降杠杆，杠杆上限4倍"
        )

    @property
    def asset_codes(self) -> List[str]:
        return [
            "000300.SH",  # 沪深300
            "ZZ000905",   # 中证500
            "SZ399006",   # 创业板指
            "SPX",        # 标普500
            "NDX",        # 纳斯达克100
            "N225",       # 日经225
            "ZQGZ10",     # 中国10年国债
            "ZQGZ5",      # 中国5年国债
            "ZQGZ2",      # 中国2年国债
            "UST10",      # 美国10年国债
            "UST2",       # 美国2年国债
            "CVTBND",     # 可转债
            "GLD",        # 黄金
            "B00Y",       # 布伦特原油
            "SHCU",       # 沪铜
            "SHAL",       # 沪铝
            "SHSN",       # 沪锡
            "DM",         # 豆粕
        ]

    @property
    def asset_name_map(self) -> Dict[str, str]:
        return {
            "000300.SH": "沪深300",
            "ZZ000905": "中证500",
            "SZ399006": "创业板指",
            "SPX": "标普500",
            "NDX": "纳斯达克100",
            "N225": "日经225",
            "ZQGZ10": "中国10年国债",
            "ZQGZ5": "中国5年国债",
            "ZQGZ2": "中国2年国债",
            "UST10": "美国10年国债",
            "UST2": "美国2年国债",
            "CVTBND": "可转债",
            "GLD": "黄金",
            "B00Y": "布伦特原油",
            "SHCU": "沪铜",
            "SHAL": "沪铝",
            "SHSN": "沪锡",
            "DM": "豆粕",
        }

    @property
    def weight_caps(self) -> Dict[str, float]:
        return {
            "000300.SH": 0.10,
            "ZZ000905": 0.10,
            "SZ399006": 0.10,
            "SPX": 0.15,
            "NDX": 0.15,
            "N225": 0.10,
            "ZQGZ10": 0.60,
            "ZQGZ5": 0.60,
            "ZQGZ2": 0.90,
            "UST10": 0.60,
            "UST2": 0.60,
            "CVTBND": 0.10,
            "GLD": 0.10,
            "B00Y": 0.10,
            "SHCU": 0.10,
            "SHAL": 0.10,
            "SHSN": 0.10,
            "DM": 0.10,
        }

    @property
    def composition(self) -> Dict[str, Any]:
        return {
            "selector": "sharpe",
            "allocator": "vol_scaled_budget",
            "controller": "rolling_vol",
            "schedule": {
                "rebalance_freq": "month_end",
                "execution_delay": 2,
            },
            "n_assets": 13,
            "selection_params": {
                "sharp_windows": "22,65,260",
                "tie_break_window": 22,
                "min_history_days": 260,
            },
        }

    @property
    def trading_costs(self) -> Dict[str, float]:
        """交易费率（单次调仓），写死在本策略内，不依赖全局 config。"""
        return {
            "000300.SH": 0.0003, "ZZ000905": 0.0003, "SZ399006": 0.0003,
            "SPX": 0.0002, "NDX": 0.0002, "N225": 0.0003,
            "ZQGZ10": 0.0003, "ZQGZ5": 0.0003, "ZQGZ2": 0.0003,
            "UST10": 0.0002, "UST2": 0.0002,
            "CVTBND": 0.0003, "GLD": 0.0003, "B00Y": 0.0001,
            "SHCU": 0.0003, "SHAL": 0.0003, "SHSN": 0.0003, "DM": 0.0003,
        }

    @property
    def replication_costs(self) -> Dict[str, float]:
        """复制费率（年化），写死在本策略内，不依赖全局 config。"""
        return {
            "000300.SH": 0.004, "ZZ000905": 0.004, "SZ399006": 0.030,
            "SPX": 0.006, "NDX": 0.006, "N225": 0.006,
            "ZQGZ10": 0.003, "ZQGZ5": 0.003, "ZQGZ2": 0.003,
            "UST10": 0.004, "UST2": 0.004,
            "CVTBND": 0.030, "GLD": 0.006, "B00Y": 0.006,
            "SHCU": 0.006, "SHAL": 0.006, "SHSN": 0.006, "DM": 0.006,
        }

    @property
    def strategy_params(self) -> Dict[str, Any]:
        return {
            "budget_source": "selection_equal",
            "target_vol": 0.05,
            "max_total_leverage": 4.0,
            "vol_windows": "22,65,130",
            "min_history_days": 260,
            "lookback_days": 260,
            "enable_vol_reset": True,
            "vol_reset_threshold": 0.06,
            "sharp_windows": "22,65,260",
            "tie_break_window": 22,
        }
