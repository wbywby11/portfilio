# 升级包文件清单

- 包名：`upgrade_DZ_v0.01.01_20261028_2`
- 分支：`DZ_v0.01.01`
- 生成时间：2026-10-28 16:08

> 基线 = Codeup `origin/DZ_v0.01.01` 当前提交。包内文件为**工作区差异内容**，覆盖到服务器同名路径即可；删除项不在包内，须按清单在服务器上手动删除。

## 后端 `portfilio-end`

- 基线提交：`ba63fa1`（origin/DZ_v0.01.01 = `ba63fa1`）
- 新增 35 / 修改 58 / 删除 88，合计 181 项

### 新增（包内） —— 35 个

- `app/api/factor_panel.py`  (10.0 KB)
- `app/backtesting/data_contract.py`  (23.9 KB)
- `app/models/factor_panel.py`  (6.9 KB)
- `app/services/factor_panel_importer.py`  (20.5 KB)
- `app/services/factor_panel_service.py`  (21.9 KB)
- `app/services/factor_panel_templates.py`  (15.7 KB)
- `app/services/live_portfolio_usage.py`  (1.7 KB)
- `app/services/strategy_data_contract_service.py`  (7.4 KB)
- `app/standalone_strategies/__init__.py`  (1.2 KB)
- `app/standalone_strategies/bond_factor_score_index/__init__.py`  (274 B)
- `app/standalone_strategies/bond_factor_score_index/strategy.py`  (30.0 KB)
- `app/standalone_strategies/factor_score_index/__init__.py`  (250 B)
- `app/standalone_strategies/factor_score_index/strategy.py`  (29.0 KB)
- `app/standalone_strategies/nous_low_vol/__init__.py`  (217 B)
- `app/standalone_strategies/nous_low_vol/strategy.py`  (72.2 KB)
- `tests/regression/bond_factor_score_index/asset_codes.txt`  (4.4 KB)
- `tests/regression/bond_factor_score_index/asset_ledger.csv`  (69.3 KB)
- `tests/regression/bond_factor_score_index/baseline_nav.csv`  (89.4 KB)
- `tests/regression/bond_factor_score_index/factor_panel_2026Q4.csv`  (98.4 KB)
- `tests/regression/bond_factor_score_index/factor_panel_snapshots.csv`  (66.2 KB)
- `tests/regression/bond_factor_score_index/panel_periods.csv`  (1.3 KB)
- `tests/regression/bond_factor_score_index/prices.parquet`  (1013.4 KB)
- `tests/regression/manifests/nous_low_vol.yaml`  (1.6 KB)
- `tests/regression/manifests/nous_low_vol_fof40_none_nav.csv`  (134.9 KB)
- `tests/regression/rebase_log/P6_standalone_pipeline.md`  (6.0 KB)
- `tests/regression/rebase_log/P7_standalone_acceptance.md`  (10.6 KB)
- `tests/regression/rebase_log/P8_bond_factor_score_index.md`  (31.5 KB)
- `tests/regression/test_bond_factor_score_index.py`  (34.8 KB)
- `tests/test_data_contract.py`  (18.1 KB)
- `tests/test_factor_panel_asof_semantics.py`  (4.9 KB)
- `tests/test_factor_panel_dataset.py`  (25.4 KB)
- `tests/test_live_publish_dependency.py`  (3.6 KB)
- `tests/test_standalone_contract.py`  (14.5 KB)
- `tests/test_standalone_delivery.py`  (17.6 KB)
- `tests/test_standalone_pipeline.py`  (21.6 KB)

### 修改（包内） —— 58 个

- `app/allocation/builtin_templates.py`  (17.8 KB)
- `app/allocation/models/base.py`  (11.3 KB)
- `app/allocation/models/param_schema.py`  (11.9 KB)
- `app/allocation/services/strategy_service.py`  (17.2 KB)
- `app/allocation/strategy_manifest.py`  (11.5 KB)
- `app/api/asset.py`  (38.2 KB)
- `app/api/strategy_model.py`  (37.7 KB)
- `app/backtesting/composition_builder.py`  (8.7 KB)
- `app/backtesting/composition_pipeline.py`  (41.7 KB)
- `app/backtesting/config.py`  (2.6 KB)
- `app/backtesting/data_feed.py`  (14.4 KB)
- `app/backtesting/engine.py`  (45.9 KB)
- `app/backtesting/runner.py`  (11.1 KB)
- `app/backtesting/schedule.py`  (17.4 KB)
- `app/config/collections.py`  (4.4 KB)
- `app/data/trade_dates.py`  (2.2 KB)
- `app/models/model_template.py`  (6.8 KB)
- `app/models/monitor.py`  (20.1 KB)
- `app/monitor/config.py`  (11.8 KB)
- `app/monitor/daily_stepper.py`  (25.0 KB)
- `app/monitor/data_provider.py`  (21.8 KB)
- `app/monitor/monitor_query.py`  (22.3 KB)
- `app/monitor/monitor_runtime.py`  (40.4 KB)
- `app/monitor/portfolio_tracker.py`  (41.6 KB)
- `app/monitor/rebalance_planning.py`  (19.0 KB)
- `app/monitor/signal_detector.py`  (34.5 KB)
- `app/monitor/time_norm.py`  (6.3 KB)
- `app/monitor/types.py`  (9.3 KB)
- `app/portfolio/portfolio_service.py`  (54.3 KB)
- `app/schemas/asset.py`  (21.2 KB)
- `app/schemas/backtests.py`  (16.7 KB)
- `app/schemas/field_mappings.py`  (15.0 KB)
- `app/schemas/model_template.py`  (3.7 KB)
- `app/selection/__init__.py`  (2.5 KB)
- `app/selection/selectors/__init__.py`  (804 B)
- `app/services/asset_service.py`  (35.4 KB)
- `app/services/backtest_analysis_service.py`  (13.3 KB)
- `app/services/backtest_execution.py`  (24.0 KB)
- `app/services/live_publish_service.py`  (35.7 KB)
- `app/services/monitor_service.py`  (89.1 KB)
- `app/services/option_pricing_service.py`  (31.7 KB)
- `app/services/price_importer.py`  (30.1 KB)
- `app/services/published_snapshot.py`  (7.2 KB)
- `app/services/strategy_model_service.py`  (43.4 KB)
- `app/services/template_init_service.py`  (12.2 KB)
- `docs/DATA_ARCHITECTURE.md`  (34.4 KB)
- `docs/DATA_GOVERNANCE.md`  (18.5 KB)
- `docs/DATA_IMPORT_SPEC.md`  (22.6 KB)
- `docs/knowledge/业务术语表.md`  (8.6 KB)
- `docs/knowledge/数据层与集合全景.md`  (5.0 KB)
- `docs/knowledge/系统策略库配置模型详解.md`  (10.6 KB)
- `docs/knowledge/选择层与风控层模块说明.md`  (6.6 KB)
- `main.py`  (9.0 KB)
- `tests/_routes_baseline.txt`  (9.7 KB)
- `tests/regression/compare.py`  (3.8 KB)
- `tests/regression/fixture.py`  (10.8 KB)
- `tests/regression/golden_baseline.json`  (1068.3 KB)
- `tests/regression/test_prototype_alignment.py`  (7.6 KB)

### 删除（包内无，须在服务器删除） —— 88 个

- `app/models/etf_discount.py`
- `app/selection/selectors/etf_discount.py`
- `data/seed/.gitkeep`
- `data/seed/gmsi2/gcmi_adj/CF.csv`
- `data/seed/gmsi2/gcmi_adj/FG.csv`
- `data/seed/gmsi2/gcmi_adj/MA.csv`
- `data/seed/gmsi2/gcmi_adj/OI.csv`
- `data/seed/gmsi2/gcmi_adj/PF.csv`
- `data/seed/gmsi2/gcmi_adj/PK.csv`
- `data/seed/gmsi2/gcmi_adj/RM.csv`
- `data/seed/gmsi2/gcmi_adj/SA.csv`
- `data/seed/gmsi2/gcmi_adj/SF.csv`
- `data/seed/gmsi2/gcmi_adj/SH.csv`
- `data/seed/gmsi2/gcmi_adj/SM.csv`
- `data/seed/gmsi2/gcmi_adj/SR.csv`
- `data/seed/gmsi2/gcmi_adj/TA.csv`
- `data/seed/gmsi2/gcmi_adj/UR.csv`
- `data/seed/gmsi2/gcmi_adj/a.csv`
- `data/seed/gmsi2/gcmi_adj/ag.csv`
- `data/seed/gmsi2/gcmi_adj/al.csv`
- `data/seed/gmsi2/gcmi_adj/ao.csv`
- `data/seed/gmsi2/gcmi_adj/au.csv`
- `data/seed/gmsi2/gcmi_adj/b.csv`
- `data/seed/gmsi2/gcmi_adj/bu.csv`
- `data/seed/gmsi2/gcmi_adj/c.csv`
- `data/seed/gmsi2/gcmi_adj/cs.csv`
- `data/seed/gmsi2/gcmi_adj/cu.csv`
- `data/seed/gmsi2/gcmi_adj/eb.csv`
- `data/seed/gmsi2/gcmi_adj/eg.csv`
- `data/seed/gmsi2/gcmi_adj/fu.csv`
- `data/seed/gmsi2/gcmi_adj/hc.csv`
- `data/seed/gmsi2/gcmi_adj/i.csv`
- `data/seed/gmsi2/gcmi_adj/jm.csv`
- `data/seed/gmsi2/gcmi_adj/l.csv`
- `data/seed/gmsi2/gcmi_adj/m.csv`
- `data/seed/gmsi2/gcmi_adj/ni.csv`
- `data/seed/gmsi2/gcmi_adj/p.csv`
- `data/seed/gmsi2/gcmi_adj/pb.csv`
- `data/seed/gmsi2/gcmi_adj/pg.csv`
- `data/seed/gmsi2/gcmi_adj/pp.csv`
- `data/seed/gmsi2/gcmi_adj/rb.csv`
- `data/seed/gmsi2/gcmi_adj/sc.csv`
- `data/seed/gmsi2/gcmi_adj/si.csv`
- `data/seed/gmsi2/gcmi_adj/sn.csv`
- `data/seed/gmsi2/gcmi_adj/sp.csv`
- `data/seed/gmsi2/gcmi_adj/ss.csv`
- `data/seed/gmsi2/gcmi_adj/v.csv`
- `data/seed/gmsi2/gcmi_adj/y.csv`
- `data/seed/gmsi2/gcmi_adj/zn.csv`
- `data/seed/gmsi2/gmap_adj/AU.csv`
- `data/seed/gmsi2/gmap_adj/CU.csv`
- `data/seed/gmsi2/gmap_adj/FG.csv`
- `data/seed/gmsi2/gmap_adj/I.csv`
- `data/seed/gmsi2/gmap_adj/IC.csv`
- `data/seed/gmsi2/gmap_adj/IF.csv`
- `data/seed/gmsi2/gmap_adj/IM.csv`
- `data/seed/gmsi2/gmap_adj/M.csv`
- `data/seed/gmsi2/gmap_adj/T.csv`
- `data/seed/gmsi2/gmap_adj/TF.csv`
- `data/seed/gmsi2/trade_dates.xlsx`
- `scripts/_check_asset_type.py`
- `scripts/_check_asset_types.py`
- `scripts/_check_fees.py`
- `scripts/_check_last.py`
- `scripts/_check_last2.py`
- `scripts/_check_mongo_weights.py`
- `scripts/_check_monitors.py`
- `scripts/_check_trade_dates.py`
- `scripts/_check_weights.py`
- `scripts/_compare_nav.py`
- `scripts/_compare_nav2.py`
- `scripts/_compare_options.py`
- `scripts/_definitive_audit.py`
- `scripts/_diag_load_weights.py`
- `scripts/_diag_v2.py`
- `scripts/_diag_v3.py`
- `scripts/_diag_weights.py`
- `scripts/_final_check.py`
- `scripts/_find_diff_origin.py`
- `scripts/_fix_last_contamination.py`
- `scripts/_inspect_dsml.py`
- `scripts/_last_init_index_run.log`
- `scripts/_nav_diff.txt`
- `scripts/_spec_audit.py`
- `scripts/_test_filtering.py`
- `scripts/_test_pv.py`
- `scripts/_verify_api.py`
- `scripts/_verify_nav.py`

## 前端 `portfilio`

- 基线提交：`56f4da8`（origin/DZ_v0.01.01 = `56f4da8`）
- 新增 2 / 修改 10 / 删除 0，合计 12 项

### 新增（包内） —— 2 个

- `src/api/factorPanel.js`  (3.6 KB)
- `src/views/analysis/FactorPanelImport.vue`  (25.6 KB)

### 修改（包内） —— 10 个

- `src/layout/MainLayout.vue`  (10.8 KB)
- `src/router/index.js`  (10.8 KB)
- `src/views/monitor/Index.vue`  (16.3 KB)
- `src/views/monitor/Signals.vue`  (35.4 KB)
- `src/views/portfolio/PortfolioDetail.vue`  (36.7 KB)
- `src/views/strategy/BacktestExecution.vue`  (65.6 KB)
- `src/views/strategy/StrategyModelDetail.vue`  (60.7 KB)
- `src/views/strategy/StrategyModelForm.vue`  (29.2 KB)
- `src/views/strategy/StrategyModelList.vue`  (19.9 KB)
- `src/views/strategy/TemplateList.vue`  (18.2 KB)

## 相对 `upgrade_DZ_v0.01.01_20261028` 的增量 —— 3 个

> 上一包生成于 2026-10-28 14:53。本节列出此后**内容有变化**的后端文件，前端无变化。
> 其余 102 个文件与上一包逐字节一致（sha1 比对）。本包为全量工作区差异，可独立部署。

### 内容有变化 —— 3 个

| 文件 | 改动 | 说明 |
|---|---|---|
| `app/standalone_strategies/nous_low_vol/strategy.py` | +213 / -33 | 新增 HK_EQ 第 7 分组、C8 混合风险预算（含剩余回填后复检）、7 个入参、契约放宽；权重末检与监控指标同步 |
| `app/allocation/strategy_manifest.py` | +4 / -2 | 描述改为覆盖「FOF 三档 / 含港股直投档 / 无商品低波档」 |
| `tests/test_standalone_contract.py` | +26 / -9 | 交付边界测试由「只交 V5」改为「V5 三档 + V6 直投版 3 + V7」，并新增「已实现能力必须暴露入参」守卫 |

### 随包附带（非 git 差异）

- `migrations/backfill_factor_panel_dataset.py` —— factor_panel 存量回填，与上一包相同
- `migrations/sync_nous_low_vol_template.py` —— 新增：同步 `nous_low_vol` 模板的 `name` / `description` / `source_code`（服务启动只自动同步参数、composition、strategy_form）
