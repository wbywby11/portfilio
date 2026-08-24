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
COL_ETF_DISCOUNT_MARKET_DATA = "etf_discount_market_data"

# ─── 域 2：策略配置 ───────────────────────────────────────────────────────────
COL_STRATEGY_MODELS = "strategy_models"
COL_MODEL_TEMPLATES = "model_templates"
COL_STRATEGY_PARAM_VERSIONS = "strategy_param_versions"

# ─── 域 3：回测与监控 ─────────────────────────────────────────────────────────
COL_BACKTEST_RECORDS = "backtest_records"
COL_MONITOR_STATES = "monitor_states"
COL_MONITOR_DAILY_REPORTS = "monitor_daily_reports"
COL_SUBJECTIVE_OVERRIDES = "subjective_overrides"
COL_SHARPE_REBALANCE_WEIGHTS = "sharpe_rebalance_weights"
COL_STRATEGY_LIVE_CHANGE_LOGS = "strategy_live_change_logs"
COL_STRATEGY_LIVE_MONITORING_RECORDS = "strategy_live_monitoring_records"
COL_MONITORED_STRATEGIES = "monitored_strategies"

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
