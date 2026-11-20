# P7 独立策略统一接入管道 · 交付与测试

验收对象：`nous_low_vol`（夏普风险平价，打包独立形态）
数据口径：**全部使用库内已有资产**，不导入任何外部数据（拼接序列导入按用户指示暂缓）
验证口径：**代码交付点 + 自动化测试覆盖**。功能与界面表现由使用者自行验证。

> 三条通道（回测 / 监控 / 组合）都是「先执行、结果落库、前端读库展示」。只要策略能被管道执行、
> 结果写进对应集合，前端无需针对独立策略做任何特判即可展示。因此本报告只证明两件事：
> ① 每个交付点的落库链路完整；② 全量测试与回归基线全绿。渲染效果不作为验收项。

---

## 1. 通道 → 集合 → 代码落点

| 通道 | 触发入口 | 结果集合 | 写入代码 |
|---|---|---|---|
| 回测 | 策略详情 → 回测 | `backtest_records`、`strategy_models.latest_backtest_summary` | `backtesting/engine.py` → `backtest_record_service` |
| 实盘发布 | 策略详情 → 实盘发布 | `strategy_models.published_snapshot`、`monitor_states` | `services/live_publish_service.py` |
| 日常监控 | 发布后启动 / 步进 | `monitor_states`、`monitor_daily_reports`、`monitor_operations` | `services/monitor_service.py`、`monitor/monitor_query.py` |
| 组合子策略 | 组合管理 → 创建组合 | `portfolios`、`rebalance_records` | `portfolio/portfolio_service.py` |

自定义监控指标沿同一链路落 `monitor_states.custom_metrics` 与日报 `performance.custom_metrics`。

---

## 2. 策略侧不再约束日期与数据规模

按「策略本身不用约束日期，什么数据日期进来都可以跑」，`nous_low_vol` 的声明收口为：

| 项 | 改动前 | 改动后 |
|---|---|---|
| `DEFAULT_SELECTION_START = "2014-01-31"` | 作为 `selection_start_date` 写进 schedule | **删除**，`get_execution_schedule()` 只留 `month_end` + `execution_delay=2` |
| 契约 `min_assets` | 15 | 不声明（0） |
| 契约 `min_history_days` | 260（error 级硬门禁） | 不声明（0）；选样最小样本量由模型参数 `min_history_days` 控制，前端可调 |
| 契约 `require_continuous` | True（要求池内日历完全一致） | 不声明（False） |
| 契约 `calendar` | `"prices"` | 不声明（默认 `trade_dates`）；日历口径由模型参数 `calendar_source` 决定 |

保留的契约声明只覆盖**算法逻辑必需**的校验：6 个分组必填与覆盖全池（`cover_pool`）、`expected_asset_class`、`max_single_day_jump=0.25`、`min_price` 默认正值、自定义检查 `group_caps_feasible`。

依据：`app/standalone_strategies/nous_low_vol/strategy.py` 的 `get_execution_schedule()` 与 `get_data_contract()`。

---

## 3. 本轮补齐的三处通用能力

三处都是**通用路径增强**（所有策略可用），没有为 `nous_low_vol` 增加任何专用分支。

### 3.1 监控日报落库（`monitor_daily_reports`）

历史缺陷：`run_init` 的日报写入写在 `if step_mode:` 内（仅主观预设逐步模式生效），常规启动后
`monitor_daily_reports` 恒为空表，日报历史只能从第二次步进开始累积。

| 文件 | 改动 |
|---|---|
| `app/services/monitor_service.py` | `run_init` 逐日循环改为**无条件**调用 `_save_daily_report`，与 `run_daily` / `run_range` 三条路径口径一致 |

日报以 `(monitor_id, date)` 为业务主键 `replace_one(upsert=True)`，重复推演幂等、不产生重复文档。

### 3.2 组合初始建仓记录（`rebalance_records`）

历史缺陷：`create_from_single_model`（单策略→组合）与 `create_from_portfolio_model`（组合模型→组合）
都会追溯写调仓记录，但「多个已发布策略直接组合」（`create_from_strategies`，组合管理页最常用路径）
只创建 `portfolios` 文档 → 组合调仓历史恒空。

| 文件 | 改动 |
|---|---|
| `app/portfolio/portfolio_service.py` | `create_from_strategies` 创建组合后写一条 `RebalanceAction.BUY` 记录：`weights_after` = 各子策略权重，`rebalance_date` = 组合成立日，`reason` = 组合创建：按子策略权重初始化建仓 |
| `src/views/portfolio/PortfolioDetail.vue` | 组合详情页新增「调仓记录」卡片，消费已有 `GET /portfolios/{id}/rebalance-records`（该 API 与前端封装此前已存在但无页面消费） |

### 3.3 自定义监控指标端到端

| 文件 | 改动 |
|---|---|
| `app/monitor/types.py` | `PortfolioState` 新增 `custom_metrics: Dict[str, Any]` |
| `app/models/monitor.py` | `MonitorState` 新增 `custom_metrics` 字段（落 `monitor_states`） |
| `app/services/monitor_service.py` | `_portfolio_state_to_state` 两条分支（新建 / 复用）均映射该字段 |
| `app/monitor/daily_stepper.py` | 新增「步骤 E2」与 `_compute_custom_metrics()`：每日经 `_get_engine_adapter(rt)` → `CompositionPipeline` → `allocator.compute_monitoring_metrics` 取指标；异常仅 warning 不阻断推演 |
| `app/monitor/daily_stepper.py` | `_json_safe()`：**本轮修复** ndarray / Index 等多元素容器先 `tolist` 再递归（原实现 `item()` 对多元素数组抛错后退化成字符串，指标会以 `"[1. 2.]"` 形式落库） |
| `app/monitor/monitor_query.py` | 日报 `performance.custom_metrics` 写入（非空才写，未实现该接口的策略字段不出现） |
| `src/views/monitor/Signals.vue` | 波动率监控卡片新增「策略自定义指标」区，键值对渲染 |

---

## 4. 测试覆盖

### 4.1 新增 `tests/test_standalone_delivery.py`（18 项）

全部不触库、不启引擎：集合与适配器以桩替代，源码结构用 AST 断言守卫。

**日报落库（5 项）**

| 用例 | 断言 |
|---|---|
| `test_save_daily_report_upserts_by_monitor_and_date` | 同 `(monitor_id, date)` 两次写入只留一份文档，且持仓/信号映射正确 |
| `test_save_daily_report_carries_custom_metrics` | 自定义指标写入 `performance.custom_metrics` |
| `test_save_daily_report_omits_empty_custom_metrics` | 空指标不产生多余字段（存量策略行为不变） |
| `test_every_daily_loop_persists_report_unconditionally[run_init / run_daily / run_range]` | AST 断言三条路径的 `_save_daily_report` **直挂 for 循环体**，且不得被任何 `if` 包裹（直接防住历史缺陷复发） |
| `test_monitor_daily_report_model_roundtrip` | 日报模型 `to_dict` 字段与集合查询口径一致 |

**组合调仓记录（3 项）**

| 用例 | 断言 |
|---|---|
| `test_create_from_strategies_writes_initial_rebalance_record` | 建 1 条 `BUY` 记录，`weights_after`/`reason`/`rebalance_date` 与组合文档一致 |
| `test_create_from_strategies_record_weights_match_sub_allocations` | 多子策略时记录权重与 `portfolios.sub_strategies` 逐项一致 |
| `test_create_from_strategies_rejects_unpublished_without_record` | 未发布策略仍被拒，且不产生任何记录（前置校验未被绕过） |

**自定义监控指标（10 项）**

| 用例 | 断言 |
|---|---|
| `test_json_safe_converts_numpy_and_nested_containers` | `np.int64/float64/bool_`、`ndarray`、嵌套 dict、tuple 全部转原生类型 |
| `test_compute_custom_metrics_filters_weights_to_price_columns` | 只有价格矩阵内的持仓参与计算，历史截止到信号日 |
| `test_compute_custom_metrics_returns_empty_without_usable_weights` | 空持仓 / 无适配器返回 `{}` |
| `test_compute_custom_metrics_swallows_adapter_errors` | 适配器异常只记 warning，返回 `{}` |
| `test_portfolio_state_carries_custom_metrics_field` | 日度内存态有 `custom_metrics` 槽位 |
| `test_monitor_state_model_exposes_custom_metrics` | 落库模型有该字段且默认空 dict |
| `test_portfolio_state_to_state_maps_custom_metrics` | 新建 / 复用两条分支都映射 |
| `test_custom_metrics_are_json_safe_before_persisting` | numpy 值经 `_json_safe` 后才进状态 |

### 4.2 全量结果

```
python -m pytest tests -q
223 passed, 1 skipped in 117.43s

python tests/regression/run_regression.py check
REGRESSION IDENTICAL   (exit code 0)
```

`golden_baseline.json` 四链路（C1-C4b）逐字节不变 —— 三处改动均未触碰数值路径
（日报落库不影响 `monitor_states` 数值、`_json_safe` 只作用于自定义指标、建仓记录只新增集合文档）。

既有守卫全绿且断言未修改：`test_backtesting_boundary.py`、`test_architecture_guard.py`、
`test_schema_consistency.py`、`test_standalone_pipeline.py`、`test_data_contract.py`。

前端改动仅做编译校验：`vue-template-compiler` 模板编译 `TEMPLATE_OK`、`@babel/core` 脚本转译 `SCRIPT_OK`。

---

## 5. 门禁负向行为（已实测的代码行为，保留作参考）

| 用例 | 配置 | 结果 |
|---|---|---|
| 漏归组 | `gold_codes` 留空，池内 15 只 | 回测被拒：`策略 nous_low_vol 数据契约校验未通过（2 项）`，指出 `gold_codes` 必填为空、**`GLD` 未归入任何分组**，两条均带修复建议 |
| 资产大类不符 | `SPX`（权益）填进 `a_bond_codes`（要求固收） | 回测通过（回测链路不做大类校验，设计如此）；**发布被拒** 409：`[SPX] 资产大类为 '权益'，但分组 a_bond_codes 要求 '固收'` |
| 无行情资产 | 池内追加库中无行情的 `511380.SH` | 回测被拒 400：`以下资产代码不存在或未配置：511380.SH`（拦截在资产库存在性校验，早于价格矩阵取数） |

---

## 6. 已知边界

1. **回测与发布门禁不对称**：`expected_asset_class` 只在发布校验，回测不校验。计划只要求发布门禁；
   若需回测阶段提前暴露，应作为通用能力增强（所有策略可用），不在本策略内特判。
2. **初始化耗时随区间线性增长**：`run_init` 会逐日写日报，起点越早写入越多。默认基日
   `2014-02-10` 到 2026-08-25 约 3272 个交易日，初始化属于一次性操作；日常步进只写当日一条。
3. **日报无前端列表页**：`GET /monitor/report-list` 与 `GET /monitor/daily-report` 后端已具备，
   前端监控页当前只读实时状态（`monitor_states`）。日报作为数据留档先落库，展示页按需再开。

---

## 7. 复跑方式

```
python -m pytest tests -q                      # 223 passed, 1 skipped
python tests/regression/run_regression.py check # REGRESSION IDENTICAL
```

环境：Windows PowerShell 需先设 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`；
后端 `python main.py`（8000），前端 `npm run dev`（8080）；MongoDB 27018（`start-mongodb.bat`）。
