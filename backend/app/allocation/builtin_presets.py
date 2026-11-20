"""策略原型预设（内置常量，不落库）。

预设是一份「策略原型的完整配置声明」：资产池分组 + 参数取值 + 调仓频率，
用户在策略配置页选择预设后由 ``strategy_preset_service`` 展开成
``asset_codes`` + ``parameters``，应用时写入模型留痕字段。

声明层单一事实源
----------------
预设**不声明** ``asset_codes``，``parameters`` 里也**不写**任何 ``*_codes``。
资产池 = ``asset_selection`` 各分组的并集，分组代码由 resolve 在返回时
写回 ``parameters.*_codes``。因此「参数里的分组」与「资产池」结构上不可能
不一致，不需要额外的强制相等校验。

快照语义
--------
``mode="tags"`` 的池子在应用时展开为快照，不做动态绑定。
``published_snapshot`` 是下游回测/监控/组合的唯一读取源，动态展开会让同一
模型在不同时间得到不同资产池，与「发布冻结快照」冲突，也无法复现历史净值。
需要动态语义时，落点是给已发布模型单独加「池子重算」动作。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

# 预设 code 由 ``<template_code>__<版本标识>`` 组成，便于从 code 反查所属模板
PRESET_CODE_SEP = "__"

# 预设内容 hash 覆盖的字段：只含会影响运行结果的项。
# name / description 属说明文字，改动不构成预设版本变化。
_HASH_FIELDS = ("asset_selection", "parameters", "rebalance_frequency", "min_history_days")


def preset_content_hash(preset: Dict[str, Any]) -> str:
    """返回预设定义的内容 hash（sha256 前 8 位）。

    用 sha256 而非内置 ``hash()``：后者带随机 salt、跨进程不稳定，
    无法用来判断「模型所基于的预设定义是否已被改动」。
    """
    payload = {k: preset.get(k) for k in _HASH_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# 低波原型资产池
# 来源：research/涌鑫低波版指数/低波版模型/config_versions.py（ASSETS 与 _POOL_* 常量）
# ---------------------------------------------------------------------------

_BOND_ETF = ["511260.SH", "511010.SH", "511220.SH", "511030.SH", "511380.SH"]
_AEQ = ["510300.SH", "510500.SH", "159915.SZ"]
_AEQ_ADD = ["159531.SZ", "510880.SH"]  # 中证2000、上证红利
_HK_EQ = ["513600.SH", "159262.SZ"]  # 恒生指数、港股通科技
_QDII3 = ["513650.SH", "159501.SZ", "513880.SH"]  # 标普500、纳指100、日经225
_COMM = ["159981.SZ", "159980.SZ", "159985.SZ", "518880.SH"]  # 能化、有色、豆粕、黄金


def _low_vol_v6v7_params(select_count: int, **overrides: Any) -> Dict[str, Any]:
    """V6/V7 共用参数基座：只保留 C0 杠杆 + C8 混合风险预算两条约束。

    对照原型 ``config_versions._mix_cons(cap, w_qdii, qdii_cap=None)``：
    ``qdii_cap`` / ``comm_cap`` / ``aeq_floor`` / ``abond_floor`` /
    ``abond_cap`` / ``abond_usd_cap`` / ``risk_budget`` 全部关闭，
    因为 V6/V7 的 Excel「权重限制」只有杠杆与混合预算两条，
    且明确不继承 V2~V5 的 A股动态下限与 A债下限。

    ``gold_codes`` 留空、黄金（518880.SH）留在 ``comm_codes``：
    原型 V6/V7 的 ``gold_in_comm`` 保持默认 True。
    """
    params: Dict[str, Any] = {
        "select_count": select_count,
        "qdii_cap": 0,
        "comm_cap": 0,
        "risk_budget_cap": 0,
        "mix_budget_cap": 0.20,
        "mix_budget_w_qdii": 1.0,
        "target_vol": 0,
        "enable_daily_vol_control": False,
        "aeq_floor_offset": 0,
        "aq_floor": 0,
        "abond_floor": 0,
        "abond_cap": 0,
        "abond_usd_cap": 0,
        "aeq_risk_cap": 0,
        "comm_cap_per": 0,
        # 原型 V6/V7 未声明 aeq_swap，即不做 A 股补选
        "enable_aeq_backfill": False,
        # _mix_cons 的 require_full_invest=False：A 债未入选时允许留现金
        "require_full_invest": False,
        "strict_validate": True,
    }
    params.update(overrides)
    return params


# ---------------------------------------------------------------------------
# 其余五个独立策略的资产池
# 无可对账的原型配置文件，取值口径来自 ParamSchema 默认值与策略文档说明；
# 代码按「当前库存量资产 + 有行情」筛选，保证应用预设后池子能真实展开。
# ---------------------------------------------------------------------------

# 因子策略按标签池展开：股票池随调仓换成分，不打标签时池子为空
_FACTOR_POOL_TAG = "pool:equity_quality_growth"
_BOND_POOL_TAG = "pool:bond_phoenix50"

# 申万一级行业（共 31 只，构成 industry_codes 池与 DAR 面板）
_INDUSTRY_SW1 = [
    "801010.SL", "801030.SL", "801040.SL", "801050.SL", "801080.SL",
    "801110.SL", "801120.SL", "801130.SL", "801140.SL", "801150.SL",
    "801160.SL", "801170.SL", "801180.SL", "801200.SL", "801210.SL",
    "801230.SL", "801710.SL", "801720.SL", "801730.SL", "801740.SL",
    "801750.SL", "801760.SL", "801770.SL", "801780.SL", "801790.SL",
    "801880.SL", "801890.SL", "801950.SL", "801960.SL", "801970.SL",
    "801980.SL",
]

# 择时候选：31 个行业去掉「801230.SL 申万综合」。综合不承载单一赛道语义，
# 是各行业加权的合成体，纳入择时会让排名与行业轮动混在一起（对账模型同口径）。
_INDUSTRY_CANDIDATES = [c for c in _INDUSTRY_SW1 if c != "801230.SL"]

# 巨潮六风格，顺序固定（SMB/HML 合成与六赛道基准都按此顺序解释）
_STYLE6 = [
    "399372.SZ",  # 大盘成长
    "399373.SZ",  # 大盘价值
    "399374.SZ",  # 中盘成长
    "399375.SZ",  # 中盘价值
    "399376.SZ",  # 小盘成长
    "399377.SZ",  # 小盘价值
]

# 赛道基准：沪深300 / 中证500 / 中证1000 / A500 / 创业板指 / 科创50 / 上证50
# 创业板用指数 399006.SZ 而非 ETF 159915.SZ：赛道归类看的是标的本身，
# ETF 价格含折溢价，作为基准会与同一赛道的基金净值不同源。
# 沪深300 取 000300.SHA：000300.SH 在远端同时承载夏普18 的期货序列，
# 两者量级差三个数量级，共用代码会在数据同步时互相覆盖。
_TRACK7 = [
    "000300.SHA", "000905.SH", "000852.SH", "000510.SH",
    "399006.SZ", "000688.SH", "000016.SH",
]

# 场内指数增强池（60 只：增强 ETF + 增强 LOF），模型只买交易所可交易品种。
# 场外基金不进持仓池：此前 354 只场外指增按「赛道中性化基线」配置，但系统实现是
# 把 fund_codes 直接赋权，等于回测买场外、实盘买 ETF，两条净值不同源。
# 池子只做筛选输入，最终持仓由 select_count + max_per_track 决定。
# 159209.SZ（中证A500增强ETF）行情自 2017-01-04 起、净值 0.47→0.90，与 A500 指数
# 2024-09 才发布的事实矛盾，判为串位数据，未纳入；修正后再补。
_ERP_ETF_POOL = [
    # 增强 LOF：2014-2019 上市，2022 年以前仅有的场内增强品种
    "163407.SZ", "502000.SH", "161039.SZ", "162216.SZ",
    # 沪深300 增强
    "561300.SH", "561990.SH", "561000.SH", "159238.SZ", "562070.SH",
    # 中证500 增强
    "561550.SH", "159610.SZ", "560100.SH", "159678.SZ",
    "563030.SH", "561950.SH", "560950.SH",
    # 中证1000 增强
    "159680.SZ", "561590.SH", "159677.SZ", "159679.SZ",
    "159685.SZ", "561280.SH", "560590.SH", "561780.SH",
    # 中证2000 增强（无独立赛道基准，按跟踪误差归入最近赛道）
    "159555.SZ", "159556.SZ", "159553.SZ", "159552.SZ",
    # 中证800 增强
    "159517.SZ",
    # 创业板增强 / 创业板综增强
    "159675.SZ", "159676.SZ", "159291.SZ", "159292.SZ",
    "159290.SZ", "159293.SZ",
    # 科创50 / 科创100 / 科创综指 / 双创50 增强
    "588370.SH", "588460.SH", "588450.SH", "588500.SH",
    "588680.SH", "588670.SH", "588550.SH", "588520.SH",
    "588690.SH", "589280.SH", "588320.SH",
    # A500 / A50 / 上证50 / 上证指数 增强
    "563550.SH", "159226.SZ", "159240.SZ", "561090.SH",
    "563630.SH", "159249.SZ", "512370.SH", "563600.SH",
    "563280.SH", "512030.SH", "563090.SH", "562810.SH", "563930.SH",
    # 2026-09 成立，仅作新发跟踪
    "158022.SZ",
]


# ---------------------------------------------------------------------------
# 预设清单（唯一注册点，顺序即前端下拉展示顺序）
# ---------------------------------------------------------------------------

PRESETS: List[Dict[str, Any]] = [
    # ── 夏普风险平价：V6 直投版三档 ───────────────────────────────────────
    {
        "code": f"nous_low_vol{PRESET_CODE_SEP}v6_d1",
        "template_code": "nous_low_vol",
        "name": "V6 直投版1（15 只，不含中证2000）",
        "description": (
            "5 债 + 4 A股 + 2 港股 + 4 商品，15 选 11；"
            "「无 159531」指 A 股端不含中证2000ETF，港股端两只全含。"
            "仅 C0 杠杆 + C8 混合预算（权益+黄金+商品≤20%），无日度波控"
        ),
        "version_tag": "V6",
        "source": "builtin",
        "asset_selection": {
            "mode": "explicit",
            "groups": {
                "a_bond_codes": list(_BOND_ETF),
                "a_eq_codes": _AEQ + ["510880.SH"],
                "hk_eq_codes": list(_HK_EQ),
                "qdii_codes": [],
                "qdii_usd_codes": [],
                "comm_codes": list(_COMM),
                "gold_codes": [],
            },
        },
        "parameters": _low_vol_v6v7_params(11),
        "rebalance_frequency": "月",
        "min_history_days": 260,
    },
    {
        "code": f"nous_low_vol{PRESET_CODE_SEP}v6_d2",
        "template_code": "nous_low_vol",
        "name": "V6 直投版2（15 只，不含港股通科技）",
        "description": (
            "5 债 + 5 A股 + 1 港股 + 4 商品，15 选 11；"
            "港股端只保留恒生指数ETF。"
            "仅 C0 杠杆 + C8 混合预算（权益+黄金+商品≤20%），无日度波控"
        ),
        "version_tag": "V6",
        "source": "builtin",
        "asset_selection": {
            "mode": "explicit",
            "groups": {
                "a_bond_codes": list(_BOND_ETF),
                "a_eq_codes": _AEQ + _AEQ_ADD,
                "hk_eq_codes": ["513600.SH"],
                "qdii_codes": [],
                "qdii_usd_codes": [],
                "comm_codes": list(_COMM),
                "gold_codes": [],
            },
        },
        "parameters": _low_vol_v6v7_params(11),
        "rebalance_frequency": "月",
        "min_history_days": 260,
    },
    {
        "code": f"nous_low_vol{PRESET_CODE_SEP}v6_d3",
        "template_code": "nous_low_vol",
        "name": "V6 直投版3（16 只全含）",
        "description": (
            "5 债 + 5 A股 + 2 港股 + 4 商品，16 选 12；"
            "含中证2000与港股通科技。"
            "仅 C0 杠杆 + C8 混合预算（权益+黄金+商品≤20%），无日度波控"
        ),
        "version_tag": "V6",
        "source": "builtin",
        "asset_selection": {
            "mode": "explicit",
            "groups": {
                "a_bond_codes": list(_BOND_ETF),
                "a_eq_codes": _AEQ + _AEQ_ADD,
                "hk_eq_codes": list(_HK_EQ),
                "qdii_codes": [],
                "qdii_usd_codes": [],
                "comm_codes": list(_COMM),
                "gold_codes": [],
            },
        },
        "parameters": _low_vol_v6v7_params(12),
        "rebalance_frequency": "月",
        "min_history_days": 260,
    },
    # ── 夏普风险平价：V7 无美债 FOF15% ───────────────────────────────────
    {
        "code": f"nous_low_vol{PRESET_CODE_SEP}v7",
        "template_code": "nous_low_vol",
        "name": "V7 无美债 FOF15%",
        "description": (
            "5 债 + 3 A股 + 3 QDII + 4 商品，15 选 11；"
            "C1 QDII≤3%，C8 权益+黄金+商品+3.75×QDII≤20%，无日度波控"
        ),
        "version_tag": "V7",
        "source": "builtin",
        "asset_selection": {
            "mode": "explicit",
            "groups": {
                "a_bond_codes": list(_BOND_ETF),
                "a_eq_codes": list(_AEQ),
                "hk_eq_codes": [],
                "qdii_codes": list(_QDII3),
                "qdii_usd_codes": [],
                "comm_codes": list(_COMM),
                "gold_codes": [],
            },
        },
        "parameters": _low_vol_v6v7_params(
            11,
            qdii_cap=0.03,
            mix_budget_w_qdii=3.75,
        ),
        "rebalance_frequency": "月",
        "min_history_days": 260,
    },
    # ── 质量成长因子选股：标签池 ─────────────────────────────────────────
    {
        "code": f"factor_score_index{PRESET_CODE_SEP}equity_quality_growth",
        "template_code": "factor_score_index",
        "name": "凤凰 50 股票因子打分（675 选 50）",
        "description": (
            "初始样本池 675 只，按「单季营收同比增速 > 0、单季扣非净利同比增速 > 0、"
            "股息率 TTM > 0」三指标初筛得 203 只；再以扣非净利同比（正向）+ 扣非 PE"
            "（反向）+ 股息率 TTM（正向）等权打分，行业内取前 5 只截到 180 只，"
            "按综合得分取前 50 只，最后按总市值加权（8 位小数，尾差归市值最大股）。"
            f"资产池按 {_FACTOR_POOL_TAG} 标签展开：需先在资产管理页给股票打上该标签；"
            "当前未打标签时池子为空，可保存但禁止回测。"
            "因子截面未覆盖的早期区间由拼接指数 512190.SH（凤凰ETF，须在资产池内、"
            "行情已导入）补足，默认已配置；splice_until 可指定强制拼接的截止日。"
        ),
        "version_tag": "V1",
        "source": "builtin",
        "asset_selection": {
            "mode": "tags",
            "tags": [_FACTOR_POOL_TAG],
        },
        "parameters": {
            "score_factors": "profit_yoy_sq_dn,pe_ttm_dn,dividend_yield_ttm",
            "reverse_factors": "pe_ttm_dn",
            "screen_positive_factors": "revenue_yoy_sq,profit_yoy_sq_dn,dividend_yield_ttm",
            "select_count": 50,
            "industry_top_n": 5,
            "weight_method": "market_cap",
            "winsorize_k": 2.0,
            "reverse_zero_floor": True,
            "panel_max_lag_days": 5,
            "splice_index_code": "512190.SH",
        },
        "rebalance_frequency": "月",
        "min_history_days": 260,
    },
    # ── 债券因子打分选券：标签池 ─────────────────────────────────────────
    {
        "code": f"bond_factor_score_index{PRESET_CODE_SEP}bond_phoenix50",
        "template_code": "bond_factor_score_index",
        "name": "凤凰 50 债券打分（久期 2.5 年）",
        "description": (
            "发行规模与主体规模按名次打分（各 20%）、修正久期按距目标 2.5 年打分（60%），"
            "券池分组限额：其它信用债单发行人 2 只 / 取前 10，金融债·地方债·二永债"
            "单发行人 10 只 / 取前 50；面板滞后 5 日。"
            f"资产池按 {_BOND_POOL_TAG} 标签展开：需先在资产管理页给债券打上该标签；"
            "当前未打标签时池子为空，可保存但禁止回测。"
            "券池截面未覆盖的早期区间由拼接指数 CCX11801.WI（浙江债券指数，须在"
            "资产池内、行情已导入）补足，默认已配置；splice_until 可指定强制拼接的截止日。"
            "口径来自 ParamSchema 默认值与券池分组说明"
        ),
        "version_tag": "V1",
        "source": "builtin",
        "asset_selection": {
            "mode": "tags",
            "tags": [_BOND_POOL_TAG],
        },
        "parameters": {
            "score_factors": "issue_size,issuer_size,modified_duration",
            "score_weights": "0.2,0.2,0.6",
            "rank_factors": "issue_size,issuer_size",
            "duration_target": 2.5,
            "duration_span": 7.5,
            "pool_caps": "其它信用债:2,金融债/地方债/二永债:10",
            "pool_topk": "其它信用债:10,金融债/地方债/二永债:50",
            "panel_max_lag_days": 5,
            "splice_index_code": "CCX11801.WI",
        },
        "rebalance_frequency": "月",
        "min_history_days": 260,
    },
    # ── 红利 GARP 增强：显式池 ───────────────────────────────────────────
    {
        "code": f"dividend_garp{PRESET_CODE_SEP}equity_account",
        "template_code": "dividend_garp",
        "name": "红利 GARP 增强（权益类专户）",
        "description": (
            "红利端（红利低波 ETF 复权净值 + 中证央企红利 50 全收益）与成长端"
            "（东证优势成长全收益）按 80/20 合成，实现波动率 60 日、目标 14%，"
            "参与度 0.60~1.00；估值序列 H00922_PE 近 3 年分位做红利防守"
            "（80% 进入、70% 退出、乘数 0.75），成长端按 200 日均线偏离防守与加仓；"
            "权益类专户中枢 1.00 / 上限 1.00 / 下限 0.83，剩余权重进短期纯债基金指数。"
            "年费 0.6% 只挂在两只全收益指数上（ETF 复权净值已含管理费，不重复计提）。"
            "口径来自库内「红利 GARP 增强（权益类专户·对账）」模型"
        ),
        "version_tag": "V1",
        "source": "builtin",
        "asset_selection": {
            "mode": "explicit",
            "groups": {
                "dividend_codes": ["512890.OF", "931231CNY01.CSI"],
                "growth_codes": ["931579CNY01.CSI"],
                # 债腿用指数而非 ETF：ETF 价格含折溢价，防守端抢反弹时会失真
                "bond_codes": ["992618.SSI"],
            },
        },
        "parameters": {
            "account_mode": "equity",
            "w_div": 0.80,
            "w_grw": 0.20,
            "vol_n": 60,
            "vol_target": 0.14,
            "part_min": 0.60,
            "part_max": 1.00,
            "pe_code": "H00922_PE",
            "pe_years": 3,
            "pe_hi": 0.80,
            "pe_lo": 0.70,
            "div_mult": 0.75,
            "ma_n": 200,
            "grw_def": 0.75,
            "add_lo": 0.03,
            "add_hi": 0.15,
            "cost_eq": 0.0010,
            "cost_bond": 0.0001,
            "tool_fee": 0.006,
            "tool_fee_codes": "931231CNY01.CSI,931579CNY01.CSI",
            "eq_center": 1.00,
            "eq_cap": 1.00,
            "eq_floor": 0.83,
            "enable_daily_vol_control": False,
        },
        "rebalance_frequency": "月",
        "min_history_days": 260,
    },
    # ── 行业择时目标波动：显式池（42 只）────────────────────────────────
    {
        "code": f"industry_timing_target_vol{PRESET_CODE_SEP}sw1_target_1_25",
        "template_code": "industry_timing_target_vol",
        "name": "行业择时目标波动（申万一级 31 行业）",
        "description": (
            "4 权益 + 黄金 + 4 债 + 现金代理 + 申万一级 31 行业 + 中证全指基准，共 42 只；"
            "日频按四桶目标波动解配（756 日协方差，目标 1.25%、上限 1.5%），"
            "策略原生调仓频率为日频；下跌反弹/顶部切换/横盘突破三形态触发后 20 日持综合分前 5 行业，"
            "择时候选为 31 个行业中去掉申万综合后的 30 个；"
            "DAR 按行业收益主成分占比控成长端（阈值 0.5、锁定 20 日）；"
            "沿中性→候选线段投影满足主动风险（目标波动 20%）与总波动上限。"
            "最少历史 760 日（大于 756 日协方差窗口）。"
            "口径来自库内「行业择时目标波动（对账用模型）」"
        ),
        "version_tag": "V1",
        "source": "builtin",
        "asset_selection": {
            "mode": "explicit",
            "groups": {
                # 中证1000全收益 / 沪深300成长 / 中证红利 / 沪深300价值，
                # 顺序即风险平价的分母口径
                "equity_codes": [
                    "H00852.SH", "H00918.CSI",
                    "H00922.CSI", "H00919.CSI",
                ],
                # 黄金用现货 SGE 报价而非黄金 ETF：ETF 含折溢价与跟踪误差
                "commodity_codes": ["AU9999.SGE"],
                "bond_codes": [
                    "CBA00621.CS", "CBA00651.CS",
                    "CBA01921.CS", "CBA01931.CS",
                ],
                "cash_codes": ["885009.WI"],
                "industry_codes": list(_INDUSTRY_SW1),
                "market_codes": ["000985.CSI"],
            },
        },
        "parameters": {
            "base_alloc_mode": "risk_budget",
            "vol_target": 0.0125,
            "vol_max": 0.015,
            "vol_min": 0.01,
            "cov_window": 756,
            "cov_windows": "63,252,756",
            "te_ratio": 0.2,
            "timing_hold": 20,
            "timing_top": 5,
            "industry_candidates": ",".join(_INDUSTRY_CANDIDATES),
            "dar_trigger": 0.5,
            "dar_hold_days": 20,
            "transaction_cost": 0.0005,
            "min_history_days": 760,
        },
        "rebalance_frequency": "日",
        "min_history_days": 760,
    },
    # ── ERP 择时指数增强：显式池 ─────────────────────────────────────────
    {
        "code": f"erp_timing_enhance{PRESET_CODE_SEP}index_enhance_pool",
        "template_code": "erp_timing_enhance",
        "name": "ERP 择时指数增强（场内增强 ETF 池）",
        "description": (
            "股息率 / 中债十年 / 美债十年 / 汇率 / 中长期贷款五序列合成 ERP2，"
            "920 日滚动分位经 sigmoid 映射权益中枢（上限 10%）；"
            "60 只场内指数增强 ETF/LOF 按八因子打分取前 10、单赛道最多 2 只，"
            "赛道基准为沪深300/中证500/中证1000/A500/创业板指/科创50/上证50，"
            "中证2000/科创100/双创50/创业板综 无独立基准，按跟踪误差归入最近赛道；"
            "巨潮六风格按「大盘成长、大盘价值、中盘成长、中盘价值、小盘成长、小盘价值」"
            "顺序声明；剩余权重进中债-新综合财富（1-3 年）指数。"
            "持仓只买场内品种，不含场外基金，回测与实盘同口径。"
            "sig3 高低 PB 分组依赖 index_enhance_stock 个股截面（现有 22 期，2025-01-27 起），"
            "更早区间该信号缺失，合成信号按 0 处理。"
            "场内增强 ETF 最早 2021-12 上市，12 个月窗口内需至少 10 只覆盖达标，"
            "起测日不得早于 2023-08，更早区间会直接报「通过筛选不足」并终止回测。"
        ),
        "version_tag": "V1",
        "source": "builtin",
        "asset_selection": {
            "mode": "explicit",
            "groups": {
                "fund_codes": list(_ERP_ETF_POOL),
                "style_codes": list(_STYLE6),
                "bench_codes": ["000985.CSI"],
                "track_codes": list(_TRACK7),
                "bond_codes": ["CBA00121.CS"],
            },
        },
        "parameters": {
            "series_codes": "DIV,Y_CN10Y,Y_US10Y_RAW,FX_CFETS,LOAN_MLT",
            "cap": 0.10,
            "sig_weight": 0.10,
            "erp_window": 920,
            "select_count": 10,
            "max_per_track": 2,
            "train_months": 12,
            "min_cov": 0.70,
            "min_days": 60,
            "w_abs": 0.5,
            "intra_min_n": 4,
            "track_min_funds": 3,
            "cost_bp": 0.0,
        },
        "rebalance_frequency": "月",
        # 60 只场内增强品种中 2023 年后新发占多数，按 260 卡整池会误报：策略内部已用
        # min_days=60 + min_cov=0.70 逐基金淘汰，预设门禁应与之间口径
        "min_history_days": 60,
    },
]


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

_BY_CODE: Dict[str, Dict[str, Any]] = {p["code"]: p for p in PRESETS}


def get_presets_for(template_code: str) -> List[Dict[str, Any]]:
    """返回某模板的全部预设（保持声明顺序）。"""
    return [p for p in PRESETS if p.get("template_code") == template_code]


def find_preset(preset_code: str) -> Optional[Dict[str, Any]]:
    """按 preset_code 查预设定义，未命中返回 None。"""
    return _BY_CODE.get(preset_code)


def list_preset_summaries(template_code: Optional[str] = None) -> List[Dict[str, Any]]:
    """返回预设摘要列表（不含展开细节），供前端下拉展示。

    摘要只带 code / template_code / name / description / version_tag /
    source / preset_version，不含 asset_selection / parameters 明细——
    明细由 ``POST /presets/{preset_code}/resolve`` 按需返回。
    """
    pool = PRESETS if template_code is None else get_presets_for(template_code)
    return [
        {
            "code": p["code"],
            "template_code": p["template_code"],
            "name": p["name"],
            "description": p.get("description", ""),
            "version_tag": p.get("version_tag", ""),
            "source": p.get("source", "builtin"),
            "preset_version": preset_content_hash(p),
        }
        for p in pool
    ]
