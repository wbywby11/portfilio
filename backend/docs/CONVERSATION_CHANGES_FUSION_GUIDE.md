# 对话相关代码变更 — 备份与合并融合指南

> 生成日期：2025-03-20（按对话上下文整理）  
> 用途：合并分支或解决冲突后，按本说明逐项核对或重新应用逻辑，避免遗漏。

---

## 1. 备份文件位置（请一并提交或拷贝到安全位置）

| 仓库 | 补丁文件（`git diff` 全量导出） |
|------|----------------------------------|
| **portfilio**（前端） | `docs/BACKUP_conversation_changes_2025-03-20.patch` |
| **portfilio-end**（后端） | `docs/BACKUP_conversation_changes_2025-03-20.patch` |

**重新导出补丁（合并前/后可再执行）：**

```powershell
# 前端
Set-Location d:\portfilio
git diff > docs/BACKUP_conversation_changes_2025-03-20.patch

# 后端
Set-Location d:\portfilio-end
git diff > docs/BACKUP_conversation_changes_2025-03-20.patch
```

**应用补丁（在干净分支上谨慎使用，可能冲突）：**

```powershell
git apply --check docs/BACKUP_conversation_changes_2025-03-20.patch   # 仅检查
git apply docs/BACKUP_conversation_changes_2025-03-20.patch             # 应用
```

---

## 2. 功能主题与要点（按主题融合，而非按文件死记）

### 2.1 策略详情 — 未回测不展示「有表现」、防串数据

**仓库：** portfilio  

**文件：** `src/views/strategy/StrategyModelDetail.vue`、`src/store/modules/strategy.js`

**要点：**

- `loadData` 开始时清空 `backtestHistory`；`loadBacktestHistory` 的 `catch` 中置 `[]` 且 `total=0`。
- `watch`：`id`（弹窗）、`'$route.params.id'`（非弹窗）切换时清空列表并 `loadData`，避免同组件复用残留上一条策略。
- 计算属性：`displayBacktestHistory`（过滤）、`isValidBacktestRecord`（`id`、可选 `model_id` 匹配、result 内有曲线/持仓/权重变更或完整四项指标等）。
- `hasBacktestResult` / `latestBacktest` 基于 `displayBacktestHistory`；时间轴 `v-for` 使用 `displayBacktestHistory`。
- `fetchBacktestHistory`：`res.data` 非数组时统一为 `[]`。

### 2.2 日常监控 — `monitor_id` 与实盘策略 ID 对齐、防 `default` 串单

**仓库：** portfilio  

**文件：**

- `src/store/modules/monitor.js` — 核心：`activeMonitorId`、`setActiveMonitorContext`、`RESET_MONITOR_VIEW`、`resolveMonitorId`，各 action 用模型 ID 作为 `monitor_id`。
- `src/views/monitor/MonitorCenter.vue` — 准入列表加载后 `dispatch('monitor/setActiveMonitorContext', firstStrategyId)`。
- `src/views/monitor/Index.vue` — 无 `monitorState` 时提示初始化；净值/杠杆/持仓数/回撤等无状态显示 `-`；`daysToNextRebalance` 防 `无`/非法日期导致 NaN。
- `src/views/monitor/Signals.vue` — `signals` 为空时波动率相关不要用 `0` 冒充有数据；`daysToNextRebalance` 同样防 NaN。
- `src/views/monitor/SubjectiveOverride.vue` — 提交/取消主观调仓使用当前 `activeMonitorId`，禁止写死 `'default'`。
- `src/api/monitor.js` + `src/utils/request.js` — 监控状态/绩效/信号 GET 支持 `skipGlobal404Message`，未初始化 404 不弹全局错误；store 内 404 时清空对应 state。

**注意：** 每个实盘策略首次日常监控需对该策略执行「初始化」；历史数据在 Mongo 的 `monitor_id=default` 不会自动迁移到新 ID。

### 2.3 实盘监控、路由、策略 API 等（同次迭代中常一起改）

**portfilio 中可能涉及：**  
`src/api/strategy.js`、`src/router/index.js`、`src/layout/MainLayout.vue`、`src/views/strategy/LiveMonitoring.vue`、`StrategyModelList.vue`、`webpack.config.js`、`package.json`、`src/utils/request.js`、`src/utils/apiError.js`（若存在）、各 `monitor` 子页小改等。  
**以当前 `git diff` / 补丁为准逐项对照。**

### 2.4 后端（portfilio-end）

**补丁：** `portfilio-end/docs/BACKUP_conversation_changes_2025-03-20.patch`

**涉及文件（统计自 diff）：**

- `app/api/strategy_model.py` — 如实盘准入 `eligible-for-monitor`、已发布表现范围、`live-monitoring` 等。
- `app/services/strategy_model_service.py` — 实盘发布、回测列表过滤、`published_performance_from` 等。
- `app/api/monitor.py` — 日常监控与实盘发布门禁等。
- `app/schemas/strategy_model.py`、`app/models/strategy_model.py`、`app/models/monitor.py` — 字段与模型。
- `app/monitor/strategy_engine.py` — 如 `pct_change` FutureWarning 修复。
- `app/monitor/signal_detector.py`、`main.py`、`app/config/settings.py`、`.gitignore` 等。

合并时优先保证 **前后端接口与 query 参数**（如 `published_scope_only`、`eligible-for-monitor` 响应结构、`monitor_id` 语义）一致。

---

## 3. 合并后自检清单

- [ ] 策略详情：从未回测的已发布策略不展示错误回测数值；切换路由/弹窗策略不串单。
- [ ] 日常监控：新实盘策略未初始化时无 `default` 残留净值；初始化/运行后数据写入 `monitor_id = 模型ID`。
- [ ] 未初始化时监控页无全局 404 弹窗轰炸，指标为 `-` 或空列表。
- [ ] 主观调仓指令与当前绑定策略一致。
- [ ] 后端与前端环境变量、代理、`VUE_APP_BASE_URL` 等与 `request.js` 一致。

---

## 4. 若补丁无法直接应用

1. 打开本目录下 `.patch` 用 diff 阅读器或 IDE 对比。  
2. 按 **§2 主题** 在目标分支上手动改同一逻辑。  
3. 用 **§3** 做手工验收。

---

## 5. 版本说明

本指南描述的是 **截至 2025-03-20** 工作区中未提交变更所体现的意图；若之后本地继续修改，请重新执行 §1 中的 `git diff > ...patch` 更新备份。
