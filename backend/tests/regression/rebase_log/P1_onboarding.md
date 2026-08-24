# P1 原型入库通道与数据修正

日期：2026-08-11
阶段：P1（方案 7.1~7.3 + 4.4 D6 + 5.5 命名日历）

## 1. 变更内容

### P1a 命名信号日历（断裂点 D）

| 项 | 变更 |
| --- | --- |
| 新增 | `app/data/calendar_registry.py`：`resolve_calendar(name)` 进程内缓存 + `upsert_calendar()`；日历缺失直接抛 `CalendarNotFoundError`，不回退行情日历 |
| 新增集合 | `trading_calendars`（`name / dates / start_date / end_date / count / source`） |
| 改 | `strategy_model_service.build_backtest_params()` 末尾新增第 6 步 `_resolve_named_signal_calendar()`：把 `signal_calendar="<name>"` 展开为下游消费的 `signal_calendar_dates` |
| 改 | 参数白名单放行 `signal_calendar`（`_RUNTIME_PARAM_WHITELIST` + `_PIPELINE_CONTROL_KEYS`） |

设计取舍：解析放在 `build_backtest_params`（5 个回测入口的共同汇聚点）而非
7 个日历消费点，因此调度层/选择器零改动，数值天然不变。

### P1b 原型入库通道（断裂点 J）

| 文件 | 作用 |
| --- | --- |
| `app/allocation/onboarding/manifest.py` | `PrototypeManifest` Pydantic 定义（calendars / models / portfolio_model / portfolio / baseline） |
| `app/allocation/onboarding/loader.py` | 通用幂等 loader，**不含任何具体原型名** |
| `app/allocation/onboarding/load.py` | CLI：`py -m app.allocation.onboarding.load gmsi2 [--dry-run] [--skip-portfolio] [--list]` |
| `app/allocation/onboarding/manifests/gmsi2.yaml` | GMSI 2.0 清单（含口径注释） |

删除：`scripts/seed_gmsi2_models.py`（被 loader 替代，含 `PROTO_ROOT =
d:/project/portfilio/gmsi2_replication` 绝对路径）。

### P1c D6 资产费率字段名

`scripts/migrate_asset_cost_field_names.py`（幂等，新旧共存时拒绝自动覆盖）：
`trading_cost → trading_cost_rate`、`replication_cost → replication_cost_rate`，
各 74 个文档（另有 47 个本已是新名，0 冲突）。

### P1d 验收进 pytest

| 项 | 变更 |
| --- | --- |
| 新增 | `tests/regression/test_prototype_alignment.py`（清单驱动，参数化 `PROTOTYPES`） |
| 删除 | `scripts/verify_gmsi2_alignment.py`（`end_date=datetime.now()` 不可复现、基线 CSV 走绝对路径） |
| 固定窗口 | `end_date` 由清单声明 `2026-06-30`（原 `now()`=2026-08-11） |

## 2. 数值归因

**无 rebase。两条验收线数值逐位不变。**

### 命名日历迁移前后逐日一致

迁移前库内两个模型 `parameters.signal_calendar_dates` 与 manifest 从
`data/seed/gmsi2/trade_dates.xlsx` 读出的日历比对：

```
manifest calendar: 4290 天 2006-11-01 ~ 2026-06-05
GMSI2-GMAP → db: 4290 天 identical: True
GMSI2-GCMI → db: 4290 天 identical: True
```

模型 `parameters` 体积：GMAP ~50KB → 347 字节，GCMI → 179 字节。

### D6 字段迁移零影响

回测引擎 `app/backtesting/engine.py` **不读** `asset.trading_cost_rate /
replication_cost_rate`；唯一消费者 `app/analysis/asset_processor/
nav_calculator.py` 属 analysis 域（指数编制），费率由调用方显式传入而非从
资产文档读取。因此字段改名后费率仍未进入两条验收链路。

### 双闸门结果（每次变更后各跑一次，均通过）

| 闸门 | 结果 |
| --- | --- |
| `py tests\regression\run_regression.py check` | `REGRESSION IDENTICAL`（EXIT=0） |
| `py -m pytest tests\regression\test_prototype_alignment.py -s` | `1 passed` |

原型对账（与 P1 前旧脚本逐位相同）：

| 层级 | 天数 | 收益相关 | 端点误差 | 最大偏差 | 结果 |
| --- | --- | --- | --- | --- | --- |
| GMAP | 3020 | 0.9996 | 0.76% | 0.0126 | PASS |
| GCMI | 3021 | 0.9998 | 0.01% | 0.0023 | PASS |
| PORTFOLIO | 2614 | 0.9997 | 0.19% | 0.0059 | PASS |

## 3. 遗留

- GMAP 端点误差 0.76% 距 1% 阈值较近，后续阶段每次改动都需盯住该行。
- `scripts/debug_gmap_*.py`（7 个）、`debug_calendar*.py`（2 个）、
  `check_gmap_prices.py` 仍在，它们各自直接构造 `CompositionPipeline`
  绕过统一入口（`CompositionPipeline(` 构造点共 22 处，其中 9 处在这些脚本里）。
  待 P3 `runner.run_unified` 落地时一并清理。
- `verify_gmsi2_output.log` 等过期日志未清理（内容为 2026-08-06 的失败状态，
  易被误读为现状）。

## 4. 勘误（2026-08-12）

用户反馈：onboarding 只是临时脚本，不应作为系统架构组件；GMSI2 模型是
前端策略建模产出的配置实例（后续通过前端操作配置）。据此：

- 删除 `app/allocation/onboarding/` 整目录与项目根 `manifests/`。
- 清单解析迁至测试侧 `tests/regression/prototype_manifest.py`，清单文件
  迁至 `tests/regression/manifests/gmsi2.yaml`；`test_prototype_alignment.py`
  改从 `regression.prototype_manifest` 导入。
- 模型入库不再走 loader CLI；库内三个 GMSI2 模型为既有入库结果，
  验收测试只按名称引用，缺失时报错指引经前端创建同名模型。
