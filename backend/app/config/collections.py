# -*- coding: utf-8 -*-
"""
MongoDB 集合名常量 —— 禁止在 Service 中硬编码集合名字符串

DATA_ARCHITECTURE.md §1.4 规定：
  app/config/collections.py ← 所有集合名常量（禁止硬编码字符串）

使用方式：
    from app.config.collections import COL_ASSETS, COL_ASSET_PRICES
    collection = db[COL_ASSETS]
"""

# ─── 域 1：市场行情数据 ───────────────────────────────────────────────────────
COL_ASSETS = "assets"
COL_ASSET_PRICES = "asset_prices"
COL_FX_RATES = "fx_rates"
COL_TRADE_DATES = "trade_dates"
# 因子截面面板：一期一股一行，多个数据产品共用，业务主键 (dataset, as_of_date, code)
COL_FACTOR_PANEL = "factor_panel"
# 宏观与估值序列：一条序列一日一行（指数PE/PB/股息率、债券收益率、信用/汇率等），
# 业务主键 (code, date)。与 asset_prices 的区别是「不是可交易资产」，不进 assets
COL_MACRO_SERIES = "macro_series"

# ─── 域 2：策略配置 ───────────────────────────────────────────────────────────
COL_STRATEGY_MODELS = "strategy_models"
COL_MODEL_TEMPLATES = "model_templates"
COL_STRATEGY_PARAM_VERSIONS = "strategy_param_versions"
# 策略档案：一个 manifest_key 一条，strategy_id 由采集器生成后永不变更
COL_STRATEGY_REGISTRY = "strategy_registry"
# 发布期版本链：每次 publish/republish/live_publish 追加一条不可变正文副本
COL_STRATEGY_VERSIONS = "strategy_versions"
# 资产池多版本：同一 universe_id 可并存多版，按 effective_from/to 解析 active
COL_ASSET_UNIVERSE_VERSIONS = "asset_universe_versions"
# 生命周期事件：状态动作与准入拒绝的结构化审计（正文引用 version_id，不重复存）
COL_STRATEGY_LIFECYCLE_EVENTS = "strategy_lifecycle_events"

# ─── 域 3：回测与监控 ─────────────────────────────────────────────────────────
COL_BACKTEST_RECORDS = "backtest_records"
# 监控运行批次：一次运行（初始化/日常/区间）一条，batch_id 串联该次运行的全部产物。
# 展示端点只读 status=completed 的最新批次，计算端点写新批次，二者不互相阻塞。
COL_MONITOR_BATCHES = "monitor_batches"
COL_MONITOR_STATES = "monitor_states"
COL_MONITOR_DAILY_REPORTS = "monitor_daily_reports"
# 绩效页预计算缓存：按 (monitor_id, batch_id) 唯一保存，跑批结束时重建，展示侧只读不重建
COL_MONITOR_PERFORMANCE_CACHE = "monitor_performance_cache"
COL_SUBJECTIVE_OVERRIDES = "subjective_overrides"
COL_MONITOR_OPERATIONS = "monitor_operations"
# 操作指令补充说明：独立集合按业务键挂靠，避免组合通道全量重建 ops 时被清空
COL_MONITOR_OPERATION_REMARKS = "monitor_operation_remarks"
# 风险预警：波动率比较 / 相关性反转，策略与组合两条通道共用一份记录
COL_MONITOR_RISK_ALERTS = "monitor_risk_alerts"
# 监控后台任务：初始化等长耗时操作的任务状态与进度（active=1 表示进行中）
COL_MONITOR_TASKS = "monitor_tasks"
COL_SHARPE_REBALANCE_WEIGHTS = "sharpe_rebalance_weights"
COL_STRATEGY_LIVE_CHANGE_LOGS = "strategy_live_change_logs"
COL_STRATEGY_LIVE_MONITORING_RECORDS = "strategy_live_monitoring_records"
COL_MONITORED_STRATEGIES = "monitored_strategies"
# 回测/监控/信号回放的统一运行记录（摘要，不复制净值曲线）
COL_STRATEGY_RUNS = "strategy_runs"
# 引擎适配器解析失败观测（template_code 未注册/类导入失败），只增观测不改回退
COL_STRATEGY_RESOLUTION_EVENTS = "strategy_resolution_events"

# ─── 域 4：组合管理 ───────────────────────────────────────────────────────────
COL_PORTFOLIOS = "portfolios"
COL_REBALANCE_RECORDS = "rebalance_records"
COL_SIM_TRADES = "sim_trades"
COL_SIM_DAILY_SNAPSHOTS = "sim_daily_snapshots"

# ─── 域 5：期权估值 ───────────────────────────────────────────────────────────
COL_OPTION_PRODUCTS = "option_products"
COL_OPTION_MARKET_DATA = "option_market_data"
COL_OPTION_VOL_SURFACES = "option_vol_surfaces"
COL_OPTION_VALUATIONS = "option_valuations"
COL_OPTION_VALUATION_HISTORY = "option_valuation_history"
COL_OPTION_LIFECYCLE_EVENTS = "option_lifecycle_events"
COL_OPTION_RISK_REPORTS = "option_risk_reports"
COL_OPTION_ACCOUNTING_ENTRIES = "option_accounting_entries"
COL_OPTION_ACCOUNTING_CONFIG = "option_accounting_config"

# ─── 域 6：AI 助手 ────────────────────────────────────────────────────────────
COL_AGENT_CONVERSATIONS = "agent_conversations"
COL_AGENT_MESSAGES = "agent_messages"
COL_AGENT_PLANS = "agent_plans"
COL_AGENT_MEMORIES = "agent_memories"
COL_AGENT_TOOL_RESULTS = "agent_tool_results"
COL_AGENT_WRITE_LOGS = "agent_write_logs"
COL_AGENT_CONFIRMATIONS = "agent_confirmations"
COL_SUBJECT_RISK_RECORDS = "subject_risk_records"
COL_SUBJECT_RISK_IMPORT_BATCHES = "subject_risk_import_batches"

# ─── 域 7：研究与报告 ─────────────────────────────────────────────────────────
COL_RESEARCH_KNOWLEDGE = "research_knowledge"
COL_REPORTS = "reports"
COL_ANALYSIS_TEMPLATES = "analysis_templates"

# ─── 域 8：系统基础设施 ───────────────────────────────────────────────────────
COL_COLLECTION_REGISTRY = "_collection_registry"
COL_QUERY_AUDIT_LOG = "_query_audit_log"
COL_IMPORT_AUDIT_LOG = "_import_audit_log"
COL_DATA_ASSET_REGISTRY = "_data_asset_registry"
COL_LINEAGE_NODES = "lineage_nodes"
COL_LINEAGE_EDGES = "lineage_edges"
