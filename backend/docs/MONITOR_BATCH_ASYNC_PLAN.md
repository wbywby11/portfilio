# 阶段一 & 阶段二：批次机制与异步化落地计划

> 适用模块：`app/monitor`、`app/services/monitor_*`、`app/api/monitor.py`、`portfilio/src/{api,store,views}/monitor*`
> 前置文档：架构方案已对齐（批次隔离 + 输出层投影 + 复用 `backtest_records`）
> 本文只覆盖阶段一（批次机制）与阶段二（异步化）。阶段三（输出层投影拆表）、阶段五（Clock 化）不在本期。

---

## 0. 范围边界

**本期做：**

1. 新增 `monitor_batches` 集合，每次监控运行生成唯一 `batch_id`，串联本次运行的全部产物。
2. 5 个附属集合加 `batch_id` 字段；查询默认读最新 `completed` 批次。
3. 监控运行结果写入 `backtest_records`，打 `run_kind="monitor"` 标记，不新建曲线存储表。
4. `POST /monitor/run`、`POST /monitor/run-range` 改为后台任务，与 `POST /monitor/init` 同一套任务机制。
5. 展示端点剥离全部计算路径（含 `performance_cache` 的按需重建）。
6. 新增批次历史查询端点，支持查看/对比历史批次。

**本期不做（明确保留）：**

- `app/backtesting/engine.py` 的 `BacktestEngine.run` 不动。
- `app/monitor/daily_stepper.py` 的逐日推演逻辑不动（只在落库处透传 `batch_id`）。
- `app/backtesting/composition_pipeline.py`、`runner.py` 的策略构建与执行语义不动。
- `monitor_states.nav_history` 不拆表（阶段三再做）。
- 主观指令的业务语义不变，只增加批次归属。

---

## 1. 前置事实核对（代码证据）

| # | 事实 | 代码位置 | 对方案的影响 |
|---|---|---|---|
| 1 | `monitor_states` 按 `monitor_id` 单文档 upsert，唯一索引 `monitor_id unique` | [save_state](file:///d:/project/portfilio/portfilio-end/app/services/monitor_service.py#L771-L784)、[index_specs.py:169](file:///d:/project/portfilio/portfilio-end/app/config/index_specs.py#L169) | 唯一索引必须改为 `{monitor_id, batch_id}`，否则新批次覆盖旧批次 |
| 2 | 组合监控 `run_daily` 从原始起点全量重跑回测管线 | [monitor_service.py:1609-1627](file:///d:/project/portfilio/portfilio-end/app/services/monitor_service.py#L1609-L1627) | 决策 5（每次全量重跑 + 新批次）与现状一致，只需显式化批次号 |
| 3 | 组合监控管线**不写** `backtest_records`（注释：避免污染） | [portfolio_backtest_monitor.py:41](file:///d:/project/portfilio/portfilio-end/app/monitor/portfolio_backtest_monitor.py#L41) | 本期新增监控专用写入路径，用 `run_kind` 隔离 |
| 4 | `save_backtest_record` 有两个副作用：写 `strategy_runs` 台账 + 写模型 `latest_backtest_summary` | [backtest_service.py:213-217,419-447](file:///d:/project/portfilio/portfilio-end/app/services/backtest_service.py#L206-L447) | 监控写入**不得**走 `save_backtest_record`，否则污染策略列表的"最近回测绩效" |
| 5 | `BacktestResult.sub_strategies` 已支持子策略结果（含 `equity_curve`） | [strategy_model.py:192-197](file:///d:/project/portfilio/portfilio-end/app/models/strategy_model.py#L192-L197) | 组合批次的子策略串联直接复用此字段，无需新结构 |
| 6 | `monitor_performance_cache` 有 `schema_version` 与按 `end_date` 的过期判定，**读取侧会按需重建** | [performance_cache.py:17-18,568-597](file:///d:/project/portfilio/portfilio-end/app/monitor/performance_cache.py#L568-L597) | 这是"纯读表"的现存破口，必须改为只读 |
| 7 | 初始化已是后台任务（`monitor_tasks` + `active=1` partial unique + 进度轮询） | [monitor_task_service.py](file:///d:/project/portfilio/portfilio-end/app/services/monitor_task_service.py) | `/run`、`/run-range` 异步化直接复用此机制，只扩展 `kind` |
| 8 | 系统内已有批次模式先例（`batch_id=uuid4().hex` + 批次登记表 + 明细表带 `batch_id`） | [data_hub_service.py:311-339](file:///d:/project/portfilio/portfilio-end/app/services/data_hub_service.py#L311-L339) | `monitor_batches` 参照此模式设计，保持系统内一致 |
| 9 | `monitor_operations` 业务键 = `monitor_id + strategy_key + op_type + signal_date + source` | [monitor_operation_service.py:100-106,152-156](file:///d:/project/portfilio/portfilio-end/app/services/monitor_operation_service.py#L99-L156) | 加 `batch_id` 后业务键变六元，`_REMARK_KEY_FIELDS` 同步扩展 |
| 10 | `monitor_id` 有三种形态：`"default"` / `monitored_strategies._id` / `strategy_models._id` | [_is_strategy_model_monitor_id](file:///d:/project/portfilio/portfilio-end/app/services/monitor_service.py#L157-L162)、[_resolve_monitored_strategy](file:///d:/project/portfilio/portfilio-end/app/services/monitor_service.py#L209-L215) | 批次表以 `monitor_id` 原值为关联键，不做归一化 |
| 11 | 不存在 `GET /monitor/overview` 端点；监控中心页由前端编排调用多个端点 | [api/monitor.py](file:///d:/project/portfilio/portfilio-end/app/api/monitor.py)、[MonitorCenter.vue:935](file:///d:/project/portfilio/portfilio/src/views/monitor/MonitorCenter.vue#L935) | 纯读表改造按 17 个查询端点逐个落实，不新增聚合端点 |
| 12 | 前端 `runMonitor` 已设 `timeout: 600000`（10 分钟）容忍同步长耗时 | [monitor.js:145-151](file:///d:/project/portfilio/portfilio/src/api/monitor.js#L137-L151) | 异步化后此超时可降至 30s |

---

## 2. 数据模型设计

### 2.1 新增集合 `monitor_batches`

常量登记：`app/config/collections.py` 域 3 区块新增

```python
# 监控运行批次：一次运行（初始化/日常/范围）一条，串联该次运行的全部产物
COL_MONITOR_BATCHES = "monitor_batches"
```

字段结构（参照 `data_hub_service` 批次模式）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `batch_id` | str | 是 | `uuid4().hex`，全局唯一，本次运行的串联键 |
| `monitor_id` | str | 是 | 监控实例 ID（原值，三种形态之一） |
| `kind` | str | 是 | `strategy` / `portfolio` / `researcher` |
| `run_mode` | str | 是 | `init` / `daily` / `range` |
| `status` | str | 是 | `pending` / `running` / `completed` / `failed` / `interrupted` / `paused` |
| `task_id` | str | 否 | 关联 `monitor_tasks.task_id`；同步模式（`async_mode=false`）为 `null` |
| `source_model_id` | str | 否 | `strategy_models._id`；`kind=researcher` 时为 `null` |
| `researcher_code` | str | 否 | `sharpe_18` / `hybrid_12`；其余为 `null` |
| `start_date` | str | 是 | 本批次覆盖区间起点 `YYYY-MM-DD` |
| `end_date` | str | 否 | 本批次覆盖区间终点；`running` 时为 `null`，完成后回填 |
| `data_date` | str | 否 | 本次跑批使用的行情最新日期（幂等判重用） |
| `config_snapshot` | dict | 是 | 本次生效配置快照，见下方子结构 |
| `backtest_record_id` | str | 否 | 本批次写入 `backtest_records` 的记录 ID（`run_kind=monitor`） |
| `parent_batch_id` | str | 否 | 增量推进（`run_mode=daily` 单策略）指向的上一批次；`init` 为 `null` |
| `metrics` | dict | 否 | 批次摘要指标，完成后回填，见下方子结构 |
| `created_at` | datetime | 是 | 批次创建时间 |
| `started_at` | datetime | 否 | 计算开始时间 |
| `finished_at` | datetime | 否 | 终态时间 |
| `duration_ms` | int | 否 | 计算耗时 |
| `error` | dict | 否 | `{message, traceback}`，失败时写入（traceback 截尾 4000 字符，与任务表一致） |

`config_snapshot` 子结构（运行开始时一次性固化，运行期间不回读策略库）：

```jsonc
{
  "template_code": "risk_budget_target_vol",
  "strategy_params": { /* 本次生效的完整参数，含实盘发布覆盖 */ },
  "config_versions": { /* 来自 live_effective_structured_params 的版本与指纹 */ },
  "execution_policy": { /* app/backtesting/policy.py 生成，含 policy_hash、commission_rate、slippage */ },
  "asset_codes": ["000300.SH", "..."],
  "sub_strategies": [            // 仅 kind=portfolio
    { "model_id": "...", "name": "...", "weight": 0.4, "sub_start": "20180101" }
  ]
}
```

`metrics` 子结构（批次列表页展示用，不复制曲线）：

```jsonc
{
  "nav": 1368.67,
  "day_count": 2543,
  "rebalance_count": 51,
  "total_return": 0.3687,
  "annual_return": 0.0812,
  "annual_volatility": 0.0934,
  "sharpe_ratio": 0.61,
  "max_drawdown": -0.1523,
  "vol_reset_count": 3,
  "total_trading_cost": 0.0,
  "subjective_override_count": 2
}
```

### 2.2 附属集合加 `batch_id`

| 集合 | 现有业务键 | 改造后业务键 | 改造点 |
|---|---|---|---|
| `monitor_states` | `monitor_id`（unique） | `monitor_id + batch_id`（unique） | `save_state` 的 `replace_one` 过滤条件加 `batch_id`；`MonitorState` 模型加字段 |
| `monitor_daily_reports` | `monitor_id + date` | `monitor_id + batch_id + date` | `_save_daily_report` 写入时带 `batch_id`；`get_daily_report`/`get_report_list` 查询加过滤 |
| `monitor_performance_cache` | `monitor_id`（unique） | `monitor_id + batch_id`（unique） | 过期判定由 `end_date` 比对改为 `batch_id` 比对；`rebuild_performance_cache` 写入带 `batch_id` |
| `monitor_operations` | `monitor_id + strategy_key + op_type + signal_date + source` | 前置加 `batch_id` | `upsert_auto_operation`、`bulk_upsert_executed_operations`、`create_subjective_operation`、`list_by_monitor` 全部加 `batch_id` 维度；`_REMARK_KEY_FIELDS` 扩展为六元 |
| `monitor_risk_alerts` | `monitor_id + signal_date`（replace） | `monitor_id + batch_id + signal_date` | `replace_for_signal_date` 加 `batch_id` 维度 |
| `subjective_overrides` | `monitor_id + status` | 加 `batch_id`（产生批次） | 创建时写入当前最新 `completed` 批次；新批次从零开始，旧批次指令封存仍可查 |

**`monitor_states` 的特殊处理**：该文档同时承担"批次最终状态"与"增量续接的 fold 状态"两个职责。批次化后：

- 一个批次一条 `monitor_states` 文档（`monitor_id + batch_id` 唯一）。
- `run_mode=daily` 的单策略增量推进：从 `parent_batch_id` 对应文档读取 fold 状态起步，结果写入**新批次文档**（不覆盖父批次），保证父批次可回溯。
- `run_mode=daily` 的组合全量重跑：同样写新批次文档。
- 查询"当前状态"= 查最新 `completed` 批次的 `monitor_states` 文档。

### 2.3 `backtest_records` 复用设计

**模型扩展**（`app/models/strategy_model.py::BacktestRecord`，全部 Optional 保证存量文档兼容）：

```python
run_kind: Optional[str] = Field(None, description="运行类型：backtest（默认）/ monitor（监控批次产出）")
batch_id: Optional[str] = Field(None, description="监控批次号；run_kind=monitor 时必填")
monitor_id: Optional[str] = Field(None, description="监控实例 ID；run_kind=monitor 时必填")
```

`run_kind=None` 视为 `backtest`（存量文档不迁移，读取侧统一归一）。

**写入路径（新增，不复用 `save_backtest_record`）**：

在 `app/services/backtest_service.py` 新增：

```python
async def save_monitor_record(self, record: BacktestRecord, batch_id: str, monitor_id: str) -> str:
    """监控批次专用写入：直接 insert，不触发 latest_backtest_summary 与 strategy_runs 台账。

    与 save_backtest_record 的差异（必须保持）：
    1. 不写 strategy_models.latest_backtest_summary —— 监控跑批不得改变策略列表的"最近回测绩效"；
    2. 不写 strategy_runs —— 监控台账已由 MonitorService._append_monitor_run 以 run_kind=monitor 写入；
    3. 强制 record.run_kind="monitor"、record.batch_id、record.monitor_id。
    """
```

**读取路径隔离**：

| 读取点 | 改造 |
|---|---|
| `backtest_service.list_backtest_records` | 默认过滤 `run_kind != "monitor"`；新增参数 `run_kind=None`（不过滤）/`"monitor"`/`"backtest"` |
| `api/strategy_model.py:820`（模型回测记录列表） | 保持默认过滤，监控批次不出现在策略详情的回测记录里 |
| `api/backtests.py:337`、`portfolio_router.py:901` | 同上 |
| `agent/tools/backtest_tools.py::QueryBacktestsTool` | list 模式默认过滤 monitor；detail 模式按 `record_id` 直查不过滤 |
| `strategy_registry_service.py:145-160`（试错计数） | 聚合管道加 `run_kind != "monitor"`，避免监控跑批被计入参数试错次数 |
| `strategy_model_monitoring.py:324` | 明确取 `run_kind="monitor"` 的最新记录（监控态展示） |

**监控结果 → `BacktestResult` 字段映射**：

| 监控产物 | `BacktestResult` 字段 | 口径说明 |
|---|---|---|
| `nav_history_model`（模型轨） | `equity_curve` | 监控写入的是**模型口径**（纯系统信号），与回测同口径可直接比对 |
| `nav_history`（实际轨，含主观） | 不写入 | 实际轨仍留在 `monitor_states`，是监控专属产物 |
| 调仓日 `asset_weights` | `weight_changes` | 单策略取调仓日快照；组合取 `pipeline.weight_history` |
| 持仓快照 | `positions` | 由 `daily_cache_rows` / `pipeline` 生成 |
| `reporter` 计算的绩效指标 | `total_return`/`annual_return`/`annual_volatility`/`sharpe_ratio`/`max_drawdown`/`calmar_ratio` + 365 口径 | 沿用 260 交易日年化统一口径，不在前端重算 |
| `sub_strategy_performance` + 子策略曲线 | `sub_strategies` | 组合批次专用，元素含 `equity_curve` |
| `execution_policy` | 记录在 `monitor_batches.config_snapshot` | `backtest_records` 不新增此字段 |

> 双轨设计要点：`backtest_records` 只存模型轨，保证"监控批次 vs 手动回测"可在同一集合内逐日比对；实际轨（含主观调整）是监控特有语义，留在 `monitor_states`。

### 2.4 索引变更（`app/config/index_specs.py`）

```python
# 新增
IndexSpec(COL_MONITOR_BATCHES, (("batch_id", ASCENDING),), unique=True, name="batch_id_unique"),
IndexSpec(
    COL_MONITOR_BATCHES,
    (("monitor_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)),
    name="monitor_status_created",
),
IndexSpec(COL_MONITOR_BATCHES, (("monitor_id", ASCENDING), ("created_at", DESCENDING)), name="monitor_created"),
IndexSpec(COL_BACKTEST_RECORDS, (("run_kind", ASCENDING), ("batch_id", ASCENDING)), name="run_kind_batch"),

# 变更（破坏性，需迁移脚本配合，见 §5.5 Step 9）
# 删除：IndexSpec(COL_MONITOR_STATES, (("monitor_id", ASCENDING),), unique=True)
# 新增：
IndexSpec(COL_MONITOR_STATES, (("monitor_id", ASCENDING), ("batch_id", ASCENDING)), unique=True, name="monitor_batch_unique"),

# 附属表查询索引
IndexSpec(COL_MONITOR_DAILY_REPORTS, (("monitor_id", ASCENDING), ("batch_id", ASCENDING), ("date", DESCENDING)), name="monitor_batch_date"),
IndexSpec(COL_MONITOR_OPERATIONS, (("monitor_id", ASCENDING), ("batch_id", ASCENDING), ("status", ASCENDING)), name="monitor_batch_status"),
IndexSpec(COL_MONITOR_RISK_ALERTS, (("monitor_id", ASCENDING), ("batch_id", ASCENDING), ("signal_date", DESCENDING)), name="monitor_batch_signal_date"),
```

`COL_MONITOR_DAILY_REPORTS`、`COL_MONITOR_OPERATIONS`、`COL_MONITOR_PERFORMANCE_CACHE` 需补进 `index_specs.py` 顶部的 import 列表（目前只 import 了部分集合）。

`monitor_states` 唯一索引变更是**破坏性操作**：必须先跑迁移脚本给存量文档补 `batch_id="legacy"`，再删旧索引、建新索引，顺序颠倒会导致存量文档冲突。

### 2.5 批次解析规则（统一入口）

新增 `app/services/monitor_batch_service.py`，对外只暴露 5 个函数，所有读写批次的地方都走它：

```python
def new_batch_id() -> str                                  # uuid4().hex
async def create_batch(monitor_id, kind, run_mode, **kw) -> dict     # status=pending，写 config_snapshot
async def mark_running(batch_id) -> None
async def mark_completed(batch_id, *, end_date, metrics, backtest_record_id, duration_ms) -> None
async def mark_failed(batch_id, error: dict) -> None
async def resolve_batch(monitor_id, batch_id: Optional[str] = None) -> Optional[dict]
    # batch_id 为空 → 取该 monitor_id 下 status=completed 的最新批次（按 created_at 倒序）
    # 无 completed 批次 → 返回 None（展示端点据此返回 404 + "请先运行初始化"）
    # batch_id="legacy" → 命中存量数据
async def list_batches(monitor_id, limit=20, skip=0) -> list[dict]
```

**关键规则**：`resolve_batch` 只认 `status=completed`。`running`/`failed`/`interrupted`/`paused` 的批次对展示不可见，展示自动回落到上一个 `completed` 批次，页面不空窗。

---

## 3. 接口改造清单

### 3.1 触发接口（计算侧）

#### `POST /monitor/init`（已异步，补批次）

改造点：

1. `create_init_task` 增加 `batch_id` 入参，任务文档写入 `batch_id`；返回值带 `batch_id`。
2. `run_init_task` 执行体：先 `create_batch(run_mode="init")` → `mark_running` → 调 `MonitorService.run_init(..., batch_id=...)` → 成功 `mark_completed`，失败 `mark_failed`。
3. `MonitorService.run_init` 签名增加 `batch_id: Optional[str] = None`；为 `None` 时内部自建批次（兼容脚本/同步模式调用）。
4. 响应体：`{task_id, batch_id, monitor_id, status, percent}`。

#### `POST /monitor/run`（同步 → 异步）

现状：[api/monitor.py:514-558](file:///d:/project/portfilio/portfilio-end/app/api/monitor.py#L514-L558) 在请求内 `await service.run_daily(...)`。

改造：

```python
@router.post("/run", response_model=Response[dict], summary="触发监控运行（后台任务）")
async def run_monitor(
    monitor_id: str = Query("default"),
    target_date: Optional[str] = Query(None),
    manual_preset_step: bool = Query(False),
    async_mode: bool = Query(True, description="true=后台任务立即返回 task_id；false=同步执行（脚本/调试兼容）"),
):
    # 1. get_active_task 冲突检查（沿用现状 409）
    # 2. async_mode=True：
    #    task = await create_run_task(monitor_id, target_date, manual_preset_step)   # kind="monitor_run"
    #    start_run_task(task["task_id"], ...)                                          # asyncio.create_task
    #    return Response.success(data=task)   # {task_id, batch_id, status:"pending"}
    # 3. async_mode=False：保留同步执行分支（与 /init 一致），便于脚本与调试
```

`monitor_task_service.py` 需要通用化（现状只有 `create_init_task`/`run_init_task`/`start_init_task`）：

| 新函数 | 职责 |
|---|---|
| `create_task(monitor_id, kind, params: dict)` | 通用任务创建；`kind ∈ {monitor_init, monitor_run, monitor_range}`；文档含 `batch_id` |
| `start_task(task_id, monitor_id, kind, params)` | `asyncio.create_task` + 引用保留（防 GC），沿用 `_running_tasks` |
| `run_task(task_id, monitor_id, kind, params)` | 按 `kind` 分发到 `run_init` / `run_daily` / `run_range`；统一 `mark_running`/`mark_completed`/`mark_failed` |
| `create_init_task` / `start_init_task` / `run_init_task` | 保留为 `create_task(kind="monitor_init")` 的薄封装，避免改动现有调用点 |

`active=1` partial unique 索引已保证同实例单活跃任务，`run` 与 `init` 天然互斥，无需额外锁。

#### `POST /monitor/run-range`（同步 → 异步）

与 `/run` 同构，`kind="monitor_range"`，`params={from_date, to_date, manual_preset_step}`。

#### 批次与任务的对应关系

- 一次触发 = 一个 `task_id` = 一个 `batch_id`，一对一。
- `manual_preset_step` 暂停（`status=paused`）时：批次状态同步置 `paused`，续跑（再次 `/run`）创建**新批次**，`parent_batch_id` 指向暂停批次。
- 任务被 `mark_stale_interrupted` 标记中断时，对应批次同步置 `interrupted`（在 `mark_stale_interrupted` 里按 `task_id` 反查批次更新）。

### 3.2 展示接口（纯读表）

17 个查询端点全部加可选参数 `batch_id: Optional[str] = Query(None)`，语义统一：不传 → 最新 `completed` 批次；传 → 指定批次；传 `legacy` → 存量数据。

| 端点 | 服务方法 | 改造内容 |
|---|---|---|
| `GET /state` | `get_state` | 加 `batch_id` 过滤；响应体增加 `batch_id`、`batch_status`、`batch_created_at` |
| `GET /nav-history` | `get_nav_history` | 先 `resolve_batch` 再读 `nav_history`；响应体带 `batch_id` |
| `GET /events` | `get_events` | 同上；事件仍从 `monitor_states.event_log` 读，按批次隔离 |
| `GET /positions` | `get_positions` | 同上 |
| `GET /daily-attribution` | `get_daily_attribution` | 同上；日期超出批次区间时返回 404（不跨批次取数） |
| `GET /performance` | `get_performance` | 同上 |
| `GET /performance-panel` | `performance_cache.get_performance_panel` | **去重建**（见下）；按 `batch_id` 读缓存 |
| `GET /performance-dual` | `get_dual_performance` | 双轨都按批次读 |
| `GET /operations` | `get_operations_grouped` | 按 `batch_id` 过滤指令 |
| `GET /positions-overlap` | `get_positions_overlap` | 多实例各自解析最新批次后求重叠 |
| `GET /signals` | `get_signal_status` | 按批次读；"下次调仓日"来自批次内预置指令 |
| `GET /risk-alerts` | `monitor_risk_alert_service.list_*` | 加 `batch_id` 过滤参数 |
| `GET /reports/{date}` | `get_daily_report` | 按 `monitor_id + batch_id + date` 查 |
| `GET /reports` | `get_report_list` | 按批次过滤后分页 |
| `GET /subjective` | `list_subjective_overrides` | 默认当前批次；`batch_id=all` 时跨批次列出（封存指令可查） |
| `GET /tasks/active` | `get_active_task` | 响应体增加 `batch_id` |
| `GET /tasks/{task_id}` | `get_task` | 同上 |

**写操作端点**（不属于展示，但需要批次归属）：

| 端点 | 改造 |
|---|---|
| `POST /subjective` | 创建时写入当前最新 `completed` 批次的 `batch_id`；无 completed 批次时返回 400（"请先运行初始化"） |
| `PUT /subjective/{id}/cancel` | 只允许操作当前批次的指令；跨批次返回 409 |
| `PATCH /operations/{id}/remark` | 备注集合 `_REMARK_KEY_FIELDS` 扩展为含 `batch_id` 的六元键 |

#### 「展示接口绝对纯读表」的三重保证

**保证一：移除查询路径的计算（必改）**

`app/monitor/performance_cache.py::ensure_performance_cache` 现状在缓存缺失/过期时调用 `rebuild_performance_cache(service, monitor_id, force_prices=True)`——这会回源行情库并重算绩效，是 `GET /performance-panel` 里的隐藏计算路径。

改造：

```python
async def get_performance_cache_readonly(service, monitor_id: str, batch_id: str) -> Optional[dict]:
    """只读缓存：命中且 batch_id 匹配则返回，否则返回 None。绝不触发重建。"""
    doc = await _collection(service).find_one({"monitor_id": monitor_id, "batch_id": batch_id})
    if not doc or doc.get("schema_version") != SCHEMA_VERSION:
        return None
    return doc

# ensure_performance_cache 保留给计算侧（run_init/run_daily/run_range 收尾）使用，
# 读取侧一律改调 get_performance_cache_readonly。
```

`GET /performance-panel` 在缓存缺失时返回 404，detail 明确写"该批次绩效缓存缺失，请重新运行监控"，**不得**回退到现算。

**保证二：依赖注入隔离**

`api/monitor.py` 的 GET 端点统一改为注入查询专用服务，不再注入完整 `MonitorService`：

```python
def get_monitor_query_service() -> MonitorQueryService:
    """查询专用服务：只聚合 MonitorQueryMixin 的读方法，不持有 engine_adapter / tracker 计算组件。"""
    return MonitorQueryService()
```

`MonitorQueryService` 新建为 `app/services/monitor_query_service.py`，只组合 `MonitorQueryMixin` + `resolve_batch`，构造时**不**初始化 `PortfolioTracker`、`MonitorEngineAdapter`、`SignalDetector`、`VolatilityCalculator`、`ReportGenerator`。这样即使误写调用，也没有计算组件可用。

> 过渡期允许 GET 端点继续用 `get_monitor_service()`，但必须在 Step 7 完成前切换到 `MonitorQueryService`，否则保证二不成立。

**保证三：静态断言测试**

新增 `tests/test_monitor_readonly_endpoints.py`，用 AST 扫描 `app/api/monitor.py`：

```python
FORBIDDEN_CALLS = {
    "run_init", "run_daily", "run_range",
    "_run_portfolio_backtest_monitor", "_run_init_sharpe18_standalone", "_run_init_hybrid12_standalone",
    "rebuild_performance_cache", "ensure_performance_cache",
    "build_pipeline", "run_unified", "_prepare_monitor_run",
}

def test_get_endpoints_have_no_compute_calls():
    """所有 @router.get 端点函数体内不得出现 FORBIDDEN_CALLS 中的调用名。"""
    # 遍历 AST：找装饰器为 router.get 的 AsyncFunctionDef，
    # 收集其函数体内所有 ast.Call 的 func.attr / func.id，断言与 FORBIDDEN_CALLS 交集为空。
```

同时补一个运行时验收用例（见 §6.3）：断开行情库连接后，所有 GET 端点仍返回 200。

### 3.3 批次历史接口（新增）

| 端点 | 方法 | 说明 |
|---|---|---|
| `GET /monitor/batches` | `list_batches` | 参数 `monitor_id`、`limit`（默认 20）、`skip`、`status`（可选过滤）。返回批次列表（不含曲线），每项含 `batch_id`/`run_mode`/`status`/`start_date`/`end_date`/`created_at`/`metrics` 摘要 |
| `GET /monitor/batches/{batch_id}` | `get_batch` | 批次详情，含 `config_snapshot`、`backtest_record_id`、`error` |
| `GET /monitor/batches/{batch_id}/nav-history` | 投影读取 | 从该批次的 `backtest_records.result.equity_curve` 读净值序列（模型轨），与 `monitor_states.nav_history`（实际轨）并列返回 |
| `GET /monitor/batches/compare` | 批次对比 | 参数 `monitor_id`、`batch_ids`（逗号分隔，2~4 个）。返回按日期对齐的多条净值序列 + 各自 `metrics`，供前端叠加画图 |
| `DELETE /monitor/batches/{batch_id}` | 清理 | 软删除：置 `status="archived"`，不物理删数据；最新 completed 批次禁止归档（409） |

批次相关端点全部为纯读（`DELETE` 只改状态字段），纳入 §3.2 保证三的 AST 扫描范围。

### 3.4 前端改造

| 文件 | 改造 |
|---|---|
| `portfilio/src/api/monitor.js` | `runMonitor`/`runMonitorRange` 增加 `async_mode` 参数（默认 true），`timeout` 由 600000 降至 30000；新增 `getMonitorBatches`、`getMonitorBatch`、`compareMonitorBatches`、`getBatchNavHistory` |
| `portfilio/src/store/modules/monitor.js` | `runMonitorAction` 改为"提交任务 → 返回 task_id/batch_id"，不再 `SET_LOADING` 长等待；新增 `pollRunTaskAction`（复用 `fetchMonitorTaskAction`）；state 增加 `currentBatchId`、`batchList` |
| `portfilio/src/views/monitor/MonitorCenter.vue` | 运行按钮走"提交 → 轮询 → 完成后 `refreshAllComponents()`"流程（与 `confirmInit` 现有轮询逻辑同构，可抽公共方法）；页面顶部显示当前批次号与生成时间；运行中显示进度条 |
| 各展示组件（`NavHistory.vue`、`Positions.vue`、`AttributionPanel.vue`、`OperationPanel.vue`、`RiskAlerts.vue`、`Signals.vue`、`EventLog.vue`、`AssetAnalysis.vue`、`ReturnsTable.vue`） | 请求参数透传 `batch_id`（默认不传 = 最新批次）；批次切换器变更时统一刷新 |
| 新增 `portfilio/src/views/monitor/BatchHistory.vue` | 批次列表 + 对比入口；路由挂在监控中心下 |

前端轮询不引入 WebSocket：现有 `GET /monitor/tasks/{task_id}` 轮询机制已满足，`run` 异步化后直接复用，避免新增推送通道。

---

## 4. 核心运行链路伪代码

### 4.1 批次生命周期（状态机）

```
create_batch(status=pending)
        │
        ▼
mark_running(status=running, started_at=now)
        │
        ├── 计算成功 ──► mark_completed(status=completed, end_date, metrics,
        │                              backtest_record_id, duration_ms, finished_at)
        │
        ├── 主观步进暂停 ──► status=paused（续跑时创建新批次，parent_batch_id 指向它）
        │
        ├── 计算异常 ──► mark_failed(status=failed, error={message, traceback})
        │
        └── 进程重启 ──► mark_stale_interrupted 同步置 status=interrupted
```

展示侧可见性：只有 `completed` 对 `resolve_batch` 可见。

### 4.2 单策略监控：一次完整生命周期

```
POST /monitor/init?monitor_id=M&start_date=2017-01-03
  │
  ├─ api/monitor.py::init_monitor
  │    batch_id = new_batch_id()
  │    task = await monitor_task_service.create_task(M, kind="monitor_init",
  │                params={start_date, manual_preset_step, batch_id})
  │    monitor_task_service.start_task(task.task_id, M, "monitor_init", params)
  │    return {task_id, batch_id, status:"pending"}          # 立即返回，不等计算
  │
  └─ 后台协程 monitor_task_service.run_task(task_id, M, "monitor_init", params)
       │
       ├─ await monitor_batch_service.create_batch(
       │        monitor_id=M, kind="strategy", run_mode="init",
       │        start_date=..., config_snapshot=固化配置)
       │     # config_snapshot 在此一次性生成：
       │     #   live_effective_structured_params(model) → strategy_params
       │     #   from_backtest_config(BacktestConfig(...)) → execution_policy(含 policy_hash)
       ├─ await monitor_batch_service.mark_running(batch_id)
       │
       ├─ result = await MonitorService().run_init(
       │              monitor_id=M, start_date=..., batch_id=batch_id,
       │              manual_preset_step=..., progress_cb=_on_progress)
       │    │
       │    │  # run_init 内部（现有逻辑不动，只在落库处带上 batch_id）
       │    ├─ _prepare_monitor_run(M)                      # 解析模型、构建 adapter
       │    ├─ create_initial_state(M, asset_list)          # 状态文档写入 batch_id
       │    ├─ enforce_price_contract(...)                  # 数据门禁，不通过直接抛错（不降级）
       │    ├─ for date in processing_dates:
       │    │     result = _process_single_day(...)         # daily_stepper，逻辑不动
       │    │     await _record_operation_events(M, result, batch_id)
       │    │     await _save_risk_alerts_from_result(M, result, batch_id)
       │    │     await _save_daily_report(M, result, batch_id)
       │    ├─ final_state = _portfolio_state_to_state(ps, M, mongo_state)
       │    │  final_state.batch_id = batch_id
       │    ├─ await save_state(final_state)                # upsert by {monitor_id, batch_id}
       │    ├─ await _rebuild_performance_cache(M, batch_id, daily_rows=...)
       │    └─ record_id = await _write_monitor_backtest_record(M, batch_id, ps, final_state)
       │              # 模型轨 → BacktestResult.equity_curve / weight_changes / positions / 绩效指标
       │              # 调 backtest_service.save_monitor_record（不触发 latest_backtest_summary）
       │
       ├─ if result.get("paused"):
       │      await mark_batch(batch_id, status="paused", end_date=result["date"], metrics=...)
       │      await _finish_task(task_id, STATUS_PAUSED, result=result)
       │  else:
       │      await monitor_batch_service.mark_completed(
       │            batch_id, end_date=result["date"], metrics=_extract_metrics(result),
       │            backtest_record_id=record_id, duration_ms=...)
       │      await _finish_task(task_id, STATUS_COMPLETED, result=result)
       │
       └─ except Exception as exc:
              await monitor_batch_service.mark_failed(batch_id, {"message": str(exc), "traceback": tb[-4000:]})
              await _finish_task(task_id, STATUS_FAILED, error=...)
              # 不吞异常、不降级：失败批次对展示不可见，页面回落到上一个 completed 批次
```

日常推进（`run_mode="daily"`，单策略增量）差异点：

```
create_batch(run_mode="daily", parent_batch_id=最新 completed 批次)
  → run_daily 从 parent 批次的 monitor_states 读 fold 状态（vol_execute_dates / vol_signal_dates / pending_rebalance）
  → 新交易日结果写入新批次文档（不覆盖父批次）
  → mark_completed
```

### 4.3 组合监控：子策略快照串联

```
POST /monitor/run?monitor_id=P            # P 是 source_type=portfolio 的监控实例
  │
  └─ 后台协程 run_task(task_id, P, "monitor_run", params)
       │
       ├─ portfolio_info = await _resolve_portfolio_source(P)
       │     # {model_id: 组合模型ID, initial_nav, rebalance_freq}
       │
       ├─ batch_id = new_batch_id()
       ├─ await create_batch(
       │      monitor_id=P, kind="portfolio", run_mode="daily",
       │      config_snapshot={
       │         template_code, strategy_params, execution_policy(commission=0.0, slippage=0.0),
       │         sub_strategies: [ {model_id, name, weight, sub_start}, ... ]   # 来自 live_snapshot.sub_strategies
       │      })
       ├─ await mark_running(batch_id)
       │
       ├─ result = await MonitorService().run_daily(P, target_date, batch_id=batch_id)
       │    │
       │    └─ _run_portfolio_backtest_monitor(P, portfolio_info, start_date=原始起点, end_date=目标日)
       │         │
       │         │  # ── 策略/组合/引擎的同步实时交互段（现状逻辑不动）──
       │         ├─ pipeline = await run_portfolio_monitor_pipeline(
       │         │                portfolio_model_id, start_yyyymmdd, end_yyyymmdd,
       │         │                initial_nav, rebalance_freq,
       │         │                commission_rate=0.0, slippage=0.0, progress_cb=...)
       │         │    │
       │         │    ├─ model_service.resolve_sub_strategies(portfolio_model, membership)
       │         │    ├─ _run_sub_strategy_backtests(sub_entries, ...)     # 子策略逐个回测（同步）
       │         │    │     └─ 每个子策略：to_backtest_request → _execute_single_strategy_backtest
       │         │    │        返回 sub_nav_series / sub_weights / sub_results_out(含 equity_curve)
       │         │    │             / all_trades / sub_snapshots_by_key
       │         │    ├─ _build_quadrant_weight_components(...)            # 四象限权重组件
       │         │    ├─ composite_runner.run_composite_unified(...)       # 合成引擎
       │         │    └─ _build_portfolio_equity_outputs(...)              # 组合级输出
       │         │
       │         │  # ── 落库段（全部带 batch_id）──
       │         ├─ fields = build_monitor_state_fields(P, model_id, pipeline, initial_nav)
       │         ├─ await _sync_portfolio_operations(P, pipeline, batch_id)
       │         │     # delete_by_monitor(P, batch_id) → bulk_upsert_executed_operations(P, ops, batch_id)
       │         │     # 组合层指令 strategy_key="portfolio"，子策略层 strategy_key=子模型ID
       │         ├─ fields["sub_strategy_performance"] = [...]              # 来自 pipeline.sub_results
       │         ├─ fields["nav_history_model"] = fields["nav_history"]     # 模型轨 = 管线输出
       │         ├─ actual_history, applied = await _build_portfolio_actual_track(P, pipeline, initial_nav, batch_id)
       │         │     # 只叠加"当前批次"的主观指令；旧批次指令已封存不参与
       │         ├─ fields["execution_policy"] = from_backtest_config(...).to_dict()
       │         ├─ await run_portfolio_risk_alerts(P, fields, batch_id)
       │         ├─ state = MonitorState(**fields, batch_id=batch_id)
       │         ├─ await save_state(state)                                 # upsert by {monitor_id, batch_id}
       │         ├─ await _rebuild_performance_cache(P, batch_id, weight_history=pipeline.weight_history)
       │         └─ record_id = await _write_portfolio_monitor_record(P, batch_id, pipeline)
       │               # BacktestRecord(model_id=组合模型ID, run_kind="monitor", batch_id=...,
       │               #   result=BacktestResult(
       │               #       equity_curve   ← pipeline.equity_curve,
       │               #       weight_changes ← pipeline.weight_history,
       │               #       sub_strategies ← [ {model_id, name, weight, annual_return, annual_vol,
       │               #                           sharpe, max_drawdown, equity_curve}, ... ],
       │               #       绩效指标 ← pipeline.performance))
       │               # 调 backtest_service.save_monitor_record
       │
       ├─ await mark_completed(batch_id, end_date=fields["date"],
       │        metrics={nav, day_count, rebalance_count=len(fields.event_log), annual_return, ...},
       │        backtest_record_id=record_id)
       └─ await _finish_task(task_id, STATUS_COMPLETED, result=result)
```

**子策略串联的可追溯链**：

```
monitor_batches(batch_id=B, kind=portfolio)
   ├─ config_snapshot.sub_strategies[]      → 本次参与的子策略清单（model_id/weight/sub_start）
   ├─ backtest_record_id=R
   │     └─ backtest_records(R).result.sub_strategies[]  → 每个子策略的完整曲线与绩效
   ├─ monitor_operations(batch_id=B, strategy_key=子模型ID)  → 子策略层调仓指令
   └─ monitor_states(batch_id=B).sub_strategy_performance    → 子策略绩效摘要（现状字段保留）
```

组合批次**不**为子策略单独创建 `monitor_batches` 记录：子策略在此是组合计算的中间产物，其结果通过 `backtest_records.result.sub_strategies` 完整保留。子策略若有自己的独立监控实例，那是另一条 `monitor_id` 的批次链，两者不交叉。

### 4.4 展示读取链路（纯读表）

```
GET /monitor/nav-history?monitor_id=M            # 不传 batch_id
  │
  ├─ batch = await monitor_batch_service.resolve_batch(M, None)
  │     └─ db[COL_MONITOR_BATCHES].find_one(
  │            {monitor_id: M, status: "completed"}, sort=[(created_at, -1)])
  │        命中 → 返回批次文档；未命中 → None
  │
  ├─ if batch is None: raise HTTPException(404, "监控实例尚无已完成批次，请先运行初始化")
  │
  ├─ state = await db[COL_MONITOR_STATES].find_one({monitor_id: M, batch_id: batch.batch_id})
  │     # 单次索引查询，无计算、无引擎构建、无行情回源
  │
  ├─ history = state["nav_history"] 按 start/end 裁剪（纯列表过滤）
  └─ return {batch_id: batch.batch_id, batch_created_at: ..., items: history}


GET /monitor/nav-history?monitor_id=M&batch_id=B7   # 指定历史批次
  └─ 同上，resolve_batch 直接按 batch_id 命中（校验 monitor_id 归属，不匹配返回 404）


GET /monitor/performance-panel?monitor_id=M
  ├─ batch = await resolve_batch(M, None)
  ├─ cache = await get_performance_cache_readonly(service, M, batch.batch_id)   # 只读，绝不重建
  ├─ if cache is None: raise HTTPException(404, "该批次绩效缓存缺失，请重新运行监控")
  └─ 区间裁剪 + 投影返回（纯字典/列表操作）
```

展示链路的依赖闭包：`monitor_batches` → `monitor_states` / `monitor_daily_reports` / `monitor_performance_cache` / `monitor_operations` / `monitor_risk_alerts` / `backtest_records`。**不含** `strategy_models` 解析、`CompositionPipeline` 构建、`asset_prices` 回源。

> 例外说明：`GET /daily-attribution` 现状会查 `asset_prices` 取当日涨跌幅（`_get_asset_daily_changes`）。这属于读底层行情数据，不属于策略/引擎计算，本期保留；若要求展示链路完全零行情依赖，需把当日涨跌幅在跑批时写入 `monitor_daily_reports`，列为阶段三事项。

---

## 5. 改造文件清单与优先级

### 5.1 P0 —— 阶段一核心（批次机制）

| # | 文件 | 改造内容 | 依赖 |
|---|---|---|---|
| 1 | `app/config/collections.py` | 新增 `COL_MONITOR_BATCHES`；补 `COL_MONITOR_DAILY_REPORTS`/`COL_MONITOR_OPERATIONS`/`COL_MONITOR_PERFORMANCE_CACHE` 的引用完整性 | — |
| 2 | `app/config/index_specs.py` | 按 §2.4 新增/变更索引声明；补 import | 1 |
| 3 | `app/models/monitor.py` | 新增 `MonitorBatch` 模型；`MonitorState`、`MonitorDailyReport`、`MonitorOperation` 加 `batch_id: Optional[str]` | — |
| 4 | `app/models/strategy_model.py` | `BacktestRecord` 加 `run_kind`/`batch_id`/`monitor_id`（全 Optional） | — |
| 5 | `app/services/monitor_batch_service.py`（新建） | §2.5 的 7 个函数 + `_extract_metrics` | 1,3 |
| 6 | `app/services/backtest_service.py` | 新增 `save_monitor_record`；`list_backtest_records` 加 `run_kind` 过滤参数 | 4 |
| 7 | `app/services/monitor_service.py` | `run_init`/`run_daily`/`run_range` 增加 `batch_id` 参数并透传到全部落库点；`save_state` 改 `{monitor_id, batch_id}` upsert；新增 `_write_monitor_backtest_record`/`_write_portfolio_monitor_record`；`_run_portfolio_backtest_monitor` 落库带 `batch_id` | 3,5,6 |
| 8 | `app/monitor/monitor_query.py` | 12 个查询方法加 `batch_id` 参数，内部先 `resolve_batch`；`_save_daily_report` 写入带 `batch_id` | 5 |
| 9 | `app/monitor/operation_recorder.py` | `_seed_monthly_operations`/`_record_operation_events`/`_sync_operations_from_event_log` 带 `batch_id`；`reset` 语义改为"只清当前批次" | 5 |
| 10 | `app/services/monitor_operation_service.py` | 全部方法加 `batch_id` 维度；`_REMARK_KEY_FIELDS` 扩为六元；索引调整 | 3 |
| 11 | `app/monitor/risk_alert_recorder.py` + `app/services/monitor_risk_alert_service.py` | `save_risk_alerts`/`replace_for_signal_date`/列表查询加 `batch_id` | 3 |
| 12 | `app/monitor/performance_cache.py` | 新增 `get_performance_cache_readonly`；`rebuild_performance_cache` 写入带 `batch_id`；`ensure_performance_cache` 限定为计算侧调用 | 5 |
| 13 | `app/api/monitor.py` | 17 个查询端点加 `batch_id` 参数；新增 5 个批次端点；写操作端点加批次归属校验 | 5,8 |
| 14 | `app/services/strategy_registry_service.py` | 试错计数聚合加 `run_kind != "monitor"` 过滤 | 4 |
| 15 | `app/agent/tools/backtest_tools.py` | list 模式过滤 monitor 记录 | 6 |

### 5.2 P1 —— 阶段二（异步化）

| # | 文件 | 改造内容 | 依赖 |
|---|---|---|---|
| 16 | `app/services/monitor_task_service.py` | 通用化 `create_task`/`start_task`/`run_task`（按 `kind` 分发）；任务文档加 `batch_id`；`mark_stale_interrupted` 同步置批次 `interrupted`；保留 `create_init_task` 等薄封装 | 5 |
| 17 | `app/api/monitor.py` | `/run`、`/run-range` 加 `async_mode` 参数并改走任务机制；`/init` 响应体补 `batch_id` | 16 |
| 18 | `portfilio/src/api/monitor.js` | `runMonitor`/`runMonitorRange` 加 `async_mode`，`timeout` 降至 30000；新增批次相关 5 个 API 函数 | 13,17 |
| 19 | `portfilio/src/store/modules/monitor.js` | `runMonitorAction` 改任务提交语义；新增 `pollRunTaskAction`；state 加 `currentBatchId`/`batchList` | 18 |
| 20 | `portfilio/src/views/monitor/MonitorCenter.vue` | 运行流程改"提交→轮询→完成刷新"；顶部显示当前批次号/生成时间；抽公共轮询方法 | 19 |
| 21 | `portfilio/src/views/monitor/BatchHistory.vue`（新建）+ 路由 | 批次列表、批次对比（净值叠加图） | 18 |
| 22 | 9 个展示组件（`NavHistory`/`Positions`/`AttributionPanel`/`OperationPanel`/`RiskAlerts`/`Signals`/`EventLog`/`AssetAnalysis`/`ReturnsTable`） | 请求透传 `batch_id`；批次切换统一刷新 | 19 |

### 5.3 P2 —— 加固与迁移

| # | 文件 | 改造内容 | 依赖 |
|---|---|---|---|
| 23 | `app/services/monitor_query_service.py`（新建） | 查询专用服务，只组合 `MonitorQueryMixin` + `resolve_batch`，构造时不初始化任何计算组件 | 8 |
| 24 | `app/api/monitor.py` | GET 端点依赖注入切换到 `get_monitor_query_service()` | 23 |
| 25 | `tests/test_monitor_readonly_endpoints.py`（新建） | AST 静态断言：GET 端点无 `FORBIDDEN_CALLS` | 24 |
| 26 | `scripts/migrate_monitor_batches.py`（新建） | 存量迁移：为每个 `monitor_states` 文档生成一条 `status=completed, batch_id="legacy"` 的批次记录；附属表存量文档补 `batch_id="legacy"`；重建 `monitor_states` 唯一索引；为存量实例重建一次 `performance_cache` 并打 `legacy` | 1-5 |
| 27 | `tests/test_backtest_monitor_parity.py` | 扩展：新增"监控批次 `backtest_records`(run_kind=monitor) vs 手动回测记录"逐日比对用例 | 6,7 |
| 28 | `app/services/strategy_model_monitoring.py` | 监控态展示改取 `run_kind="monitor"` 的最新记录 | 6 |

### 5.4 明确不动的文件（作为投影数据源与计算内核）

| 文件 | 原因 |
|---|---|
| `app/backtesting/engine.py` | 决策 6：执行层不动 |
| `app/backtesting/runner.py` | 策略构建与引擎入口不动 |
| `app/backtesting/composition_pipeline.py` | 策略层不动 |
| `app/monitor/daily_stepper.py` | 逐日推演逻辑不动，`batch_id` 由调用方透传 |
| `app/monitor/portfolio_backtest_monitor.py` | 组合管线不动，只在 `_run_portfolio_backtest_monitor` 的落库处加批次 |
| `app/portfolio/composite_runner.py` | 合成引擎不动 |
| `app/services/portfolio_backtest_helpers.py` | 子策略回测执行不动 |
| `app/monitor/researcher_strategies/**` | 研究员独立引擎不动，只在其落库处带 `batch_id` |
| `app/monitor/report_generator.py`、`volatility_calculator.py`、`signal_detector.py` | 计算组件不动 |

### 5.5 实施顺序（依赖 DAG）

```
Step 1  集合与模型层         #1 #2 #3 #4
          │
Step 2  批次服务             #5              （依赖 Step 1）
          │
Step 3  回测记录复用         #6 #14 #15      （依赖 Step 1）
          │
Step 4  计算侧接入批次       #7              （依赖 Step 2、3）
          │
Step 5  附属表批次化         #8 #9 #10 #11 #12（依赖 Step 4）
          │
Step 6  展示端点批次化       #13             （依赖 Step 5）
          │
Step 7  纯读表加固           #23 #24 #25     （依赖 Step 6）
          │
Step 8  触发接口异步化       #16 #17         （依赖 Step 4、5）
          │
Step 9  存量迁移             #26             （依赖 Step 1-5，须在 Step 6 上线前完成）
          │
Step 10 前端改造             #18-#22         （依赖 Step 6、8）
          │
Step 11 一致性验收           #27 #28         （依赖 Step 4、6）
```

关键顺序约束：

- **Step 9 必须在 Step 6 之前**：展示端点一旦默认按 `batch_id` 查询，存量数据若无 `legacy` 批次会全部查不到。
- **Step 8 可与 Step 6/7 并行**：异步化只改触发侧，不依赖展示侧改造完成。
- **Step 7 是"纯读表"的收口**：在 `MonitorQueryService` 切换 + AST 断言测试通过前，不得宣称展示接口纯读表。

---

## 6. 验收清单

### 6.1 功能验收

| # | 用例 | 期望 |
|---|---|---|
| F1 | 对同一 `monitor_id` 连续执行两次 `POST /init` | `monitor_batches` 两条记录，`batch_id` 不同，均 `status=completed`；`backtest_records` 两条 `run_kind=monitor` 记录 |
| F2 | 查询 `monitor_states`/`monitor_daily_reports`/`monitor_operations`/`monitor_risk_alerts`/`monitor_performance_cache` | 每条文档都带 `batch_id`，且能按 `batch_id` 聚合出一次运行的完整产物 |
| F3 | `GET /nav-history?monitor_id=M`（不传 batch_id） | 返回最新 `completed` 批次数据，响应体含 `batch_id` |
| F4 | `GET /nav-history?monitor_id=M&batch_id=B1`（B1 为旧批次） | 返回 B1 的数据，与 F3 不同 |
| F5 | 运行进行中（`status=running`）时查询展示端点 | 返回上一个 `completed` 批次数据，不返回半成品 |
| F6 | 无任何 `completed` 批次时查询 | 返回 404，detail 为"请先运行初始化" |
| F7 | `GET /batches?monitor_id=M` | 返回批次列表含 `metrics` 摘要，按 `created_at` 倒序 |
| F8 | `GET /batches/compare?monitor_id=M&batch_ids=B1,B2` | 返回按日期对齐的两条净值序列 |
| F9 | `POST /run?async_mode=true` | 立即返回 `{task_id, batch_id, status:"pending"}`，响应耗时 < 1s |
| F10 | `GET /tasks/{task_id}` 轮询至 `completed` | 任务文档含 `batch_id`；批次状态同步为 `completed` |
| F11 | 主观步进暂停（`manual_preset_step=true`） | 批次 `status=paused`；续跑创建新批次，`parent_batch_id` 指向暂停批次 |
| F12 | 计算过程抛异常 | 批次 `status=failed` 且 `error.traceback` 有内容；任务 `status=failed`；展示回落到上一个 `completed` 批次 |
| F13 | 服务重启后 `mark_stale_interrupted` | 遗留活跃任务置 `interrupted`，对应批次同步置 `interrupted` |
| F14 | `POST /subjective` 在无 completed 批次时 | 返回 400，不产生游离指令 |
| F15 | 新批次创建后查旧批次主观指令 | `GET /subjective?batch_id=all` 可查到封存指令；默认查询只返回当前批次 |
| F16 | 存量数据（迁移后） | `GET /state?batch_id=legacy` 返回迁移前数据；不传 `batch_id` 时若存在更新的 completed 批次则返回新批次 |

### 6.2 一致性验收（不得放松既有断言）

| # | 用例 | 期望 |
|---|---|---|
| C1 | `tests/test_backtest_monitor_parity.py` 全量执行 | diff 数不高于改造前基线（当前基线值以改造前一次运行为准，记录在 PR 描述里） |
| C2 | 同一模型、同一区间、同一 gross 口径：监控批次 vs 手动回测 | `backtest_records` 两条记录的 `equity_curve` 逐日净值差异 < 1e-9 |
| C3 | 组合监控批次 vs 组合回测（`commission_rate=0.0, slippage=0.0`） | `equity_curve` 与 `sub_strategies[].equity_curve` 逐日一致 |
| C4 | `tests/execution_baseline/engine_layer.py`、`regression_layer.py` | 四条路径（single/composite/sensitivity/monitor）与冻结夹具比对结果不变 |
| C5 | 策略列表页"最近回测绩效"（`latest_backtest_summary`） | 监控跑批前后该字段值不变（验证 `save_monitor_record` 未触发副作用） |
| C6 | `strategy_registry` 试错计数 | 监控跑批前后 `trial_count` 不变 |

### 6.3 纯读表验收

| # | 用例 | 期望 |
|---|---|---|
| R1 | 断开行情库（`asset_prices` 不可达）后调用全部 17 个 GET 端点 | 除 `GET /daily-attribution`（已知例外，见 §4.4 说明）外，全部返回 200 与完整数据 |
| R2 | 停用策略库（`strategy_models` 查询抛错）后调用全部 GET 端点 | 全部返回 200（展示链路不读 `strategy_models`） |
| R3 | `pytest tests/test_monitor_readonly_endpoints.py` | AST 断言通过：GET 端点函数体内无 `FORBIDDEN_CALLS` |
| R4 | 代码审查：`MonitorQueryService.__init__` | 不实例化 `PortfolioTracker`/`MonitorEngineAdapter`/`SignalDetector`/`VolatilityCalculator`/`ReportGenerator` |
| R5 | `GET /performance-panel` 在缓存文档被手工删除后 | 返回 404（"绩效缓存缺失，请重新运行监控"），**不**触发重建（可通过日志无 `rebuild_performance_cache` 记录验证） |

---

## 7. 风险与回滚

| # | 风险 | 影响 | 缓解 | 回滚 |
|---|---|---|---|---|
| 1 | `monitor_states` 唯一索引变更是破坏性操作 | 迁移顺序错误会导致存量文档写入冲突 | Step 9 迁移脚本先补 `batch_id="legacy"` 再换索引；在低峰期执行；执行前 `mongodump` 备份该集合 | 恢复旧索引声明 `{monitor_id} unique`，删除批次表过滤（查询退回单键） |
| 2 | 组合每次运行全量重跑，算力成本随子策略数线性增长 | 频繁触发时后端 CPU 占用高 | `active=1` 唯一索引已防并发；`create_task` 增加幂等检查：若最新 completed 批次的 `data_date` 与 `config_snapshot` 指纹均未变化，直接返回该批次不重跑 | 保留 `async_mode=false` 同步开关；极端情况回退到"组合沿用最新批次覆盖写"（去掉新批次生成） |
| 3 | 主观指令"新批次从零开始"改变用户可见行为 | 用户重新初始化后发现历史干预消失 | 前端批次切换器显示每批次的主观指令条数；`GET /subjective?batch_id=all` 可查封存指令；文档与界面文案明确说明 | 若不可接受，改为"新批次继承上一批次的 executed 指令"（只改 `_build_portfolio_actual_track` 与单策略 fold 的 overrides 查询范围，不影响批次表结构） |
| 4 | `performance_cache` 去重建后，存量实例首次访问 404 | 绩效页空白 | Step 9 迁移脚本为所有存量实例重建一次缓存并打 `legacy` | 临时恢复 `ensure_performance_cache` 的按需重建（单点回退，不影响批次机制） |
| 5 | `run_kind` 过滤遗漏某个读取点 | 监控批次混入回测列表/试错计数 | §2.3 表格逐个核对；C5、C6 验收用例覆盖；全局 grep `COL_BACKTEST_RECORDS` 与 `backtest_collection` 确认无遗漏 | 读取侧过滤是增量条件，移除即回滚 |
| 6 | 双轨语义混淆（`backtest_records` 只存模型轨） | 用户从回测记录看到的净值与监控页实际轨不一致 | 监控页净值图默认展示实际轨，批次对比页明确标注"模型口径"；`monitor_batches.metrics` 同时记录两轨终点净值 | 若需实际轨入 `backtest_records`，扩展 `BacktestResult` 增加 `equity_curve_actual` 字段（向后兼容） |
| 7 | 异步化后前端轮询逻辑缺陷导致状态不同步 | 运行完成后页面不刷新 | 复用 `confirmInit` 已验证的轮询实现，抽公共方法；轮询终态（completed/failed/paused/interrupted）后强制 `refreshAllComponents()` | `async_mode=false` 走同步分支，前端行为回到改造前 |

---

## 8. 开发任务拆分（可直接指派）

| 任务 | 内容 | 涉及文件 | 预估 | 前置 |
|---|---|---|---|---|
| T1 | 集合常量、索引声明、Pydantic 模型扩展 | #1 #2 #3 #4 | 0.5d | — |
| T2 | `monitor_batch_service.py` 新建（含单测） | #5 | 1d | T1 |
| T3 | `backtest_service` 监控写入路径 + `run_kind` 过滤（含 6 个读取点） | #6 #14 #15 | 1d | T1 |
| T4 | `MonitorService` 三个 run 入口接入批次 + 两个 `_write_*_record` | #7 | 2d | T2 T3 |
| T5 | 附属表批次化（query/operations/risk_alerts/performance_cache） | #8 #9 #10 #11 #12 | 2d | T4 |
| T6 | API 端点批次参数 + 5 个批次端点 | #13 | 1.5d | T5 |
| T7 | 纯读表加固：`MonitorQueryService` + 依赖注入切换 + AST 断言测试 | #23 #24 #25 | 1d | T6 |
| T8 | 任务服务通用化 + `/run`、`/run-range` 异步化 | #16 #17 | 1.5d | T4 T5 |
| T9 | 存量迁移脚本（含索引重建、缓存重建） | #26 | 1d | T5 |
| T10 | 前端 API/store/MonitorCenter 轮询改造 | #18 #19 #20 | 1.5d | T6 T8 |
| T11 | 前端批次历史页 + 9 个展示组件透传 `batch_id` | #21 #22 | 2d | T10 |
| T12 | 一致性验收用例扩展 + 全量回归 | #27 #28 | 1d | T4 T6 |

总计约 16 人日。关键路径：T1 → T2 → T4 → T5 → T6 → T7（后端纯读表收口），前端 T10/T11 可在 T6 完成后并行启动。

**建议交付切分**：

- 交付一（后端批次机制可用）：T1-T6 + T9 + T12，验收 §6.1 F1-F8、F12-F16 + §6.2 全部 + §6.3 R5。
- 交付二（纯读表收口）：T7，验收 §6.3 R1-R4。
- 交付三（异步化 + 前端）：T8 + T10 + T11，验收 §6.1 F9-F11。
