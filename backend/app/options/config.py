# -*- coding: utf-8 -*-
"""
收益凭证估值系统——配置管理

仅保留纯参数常量，文件路径常量已移除（数据层迁移至 MongoDB）。
"""

import tempfile
from pathlib import Path

# ── MC 模拟参数 ─────────────────────────────────────────

DEFAULT_N_PATHS = 50000        # MC 默认路径数
DEFAULT_MC_SEED = 42           # MC 随机种子（保证可复现）
DEFAULT_N_STEPS_FACTOR = 252   # 每年步数

# ── 波动率期限 ─────────────────────────────────────────

VOL_TENORS = ["1M", "3M", "6M", "12M"]  # 波动率期限标签
VOL_TENOR_DAYS = {"1M": 30, "3M": 90, "6M": 180, "12M": 365}  # 对应天数

# ── 利率曲线 ─────────────────────────────────────────

RATE_TENORS = ["1M", "3M", "6M", "1Y", "2Y", "5Y"]  # 利率期限标签
RATE_TENOR_YEARS = {"1M": 1/12, "3M": 3/12, "6M": 6/12, "1Y": 1.0, "2Y": 2.0, "5Y": 5.0}

# ── 障碍期权离散监控修正常数 ──────────────────────────

BG_CONSTANT = 0.5826  # Broadie, Glasserman & Kou (1997)

# ── 临时输出目录（仅用于风险报告等临时输出）──────────

RISK_DIR = Path(tempfile.gettempdir()) / "options_risk_reports"
RISK_DIR.mkdir(parents=True, exist_ok=True)
