# 策略库基线字段集（S01 产物）

> 由 `scripts/strategy_library_baseline.py` 生成，**只读业务集合**。
> 文件内不含生成时间，连续执行两次应逐字节相同；不一致即说明库结构发生了变化。
> 后续每一步新增字段时，以本文件的「基线集合」对照：既有 key 的类型不得改变，
> 新增 key 必须走本计划约定的 `Optional=None` + insert 后 `$set` 范式。

## 1. 字段集清单

> 口径：`$objectToArray` 全集合聚合。`出现次数` 为该 key 在集合内的文档数（嵌套字段不计入，只统计顶层）。

### `strategy_models`（38 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 38 | 100.0% | objectId |
| `agent_meta` | 6 | 15.8% | object |
| `asset_codes` | 38 | 100.0% | array |
| `asset_names` | 38 | 100.0% | object |
| `asset_selection_count` | 38 | 100.0% | null |
| `asset_selection_snapshot` | 7 | 18.4% | object |
| `config_fingerprint` | 32 | 84.2% | null, string |
| `controller_code` | 38 | 100.0% | null |
| `controller_parameters` | 38 | 100.0% | null, object |
| `created_at` | 38 | 100.0% | date |
| `created_by` | 38 | 100.0% | null, string |
| `description` | 38 | 100.0% | string |
| `enable_momentum_selection` | 38 | 100.0% | bool, null |
| `inception_date` | 38 | 100.0% | date, null |
| `initial_nav` | 38 | 100.0% | double |
| `is_portfolio` | 38 | 100.0% | bool |
| `latest_backtest_summary` | 38 | 100.0% | null, object |
| `live_effective_date` | 38 | 100.0% | date, null |
| `live_publish_enabled` | 38 | 100.0% | bool |
| `live_published_at` | 38 | 100.0% | date, null |
| `live_published_version` | 26 | 68.4% | int |
| `live_rebalance_mode` | 38 | 100.0% | string |
| `live_snapshot` | 38 | 100.0% | object |
| `live_snapshot_outdated` | 38 | 100.0% | bool |
| `live_version` | 38 | 100.0% | int |
| `live_volatility_threshold` | 38 | 100.0% | double, null |
| `macd_long_window` | 38 | 100.0% | int, null |
| `macd_windows` | 38 | 100.0% | null, string |
| `min_history_days` | 38 | 100.0% | int, null |
| `mom_windows` | 38 | 100.0% | null, string |
| `momentum_windows` | 38 | 100.0% | null, string |
| `name` | 38 | 100.0% | string |
| `parameters` | 38 | 100.0% | object |
| `posi_windows` | 38 | 100.0% | null, string |
| `preset_applied_at` | 7 | 18.4% | date |
| `preset_code` | 7 | 18.4% | string |
| `preset_version` | 7 | 18.4% | string |
| `published_at` | 38 | 100.0% | date, null |
| `published_snapshot` | 32 | 84.2% | object |
| `published_version` | 32 | 84.2% | int |
| `rebalance_frequency` | 38 | 100.0% | string |
| `reversal_windows` | 38 | 100.0% | null, string |
| `selector_parameters` | 38 | 100.0% | null |
| `selector_type` | 38 | 100.0% | null, string |
| `sharp_windows` | 38 | 100.0% | null |
| `smom_windows` | 38 | 100.0% | null, string |
| `status` | 38 | 100.0% | string |
| `structured_params` | 38 | 100.0% | null, object |
| `sub_strategies` | 38 | 100.0% | array |
| `tags` | 38 | 100.0% | array |
| `template_code` | 38 | 100.0% | string |
| `tie_break_window` | 38 | 100.0% | null |
| `updated_at` | 38 | 100.0% | date |
| `weight_model_params` | 38 | 100.0% | object |
| `weight_model_type` | 38 | 100.0% | null, string |

### `backtest_records`（62 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 62 | 100.0% | objectId |
| `benchmark_code` | 62 | 100.0% | null |
| `created_at` | 62 | 100.0% | date |
| `data_fingerprint` | 62 | 100.0% | string |
| `end_date` | 62 | 100.0% | string |
| `initial_capital` | 62 | 100.0% | double |
| `model_id` | 62 | 100.0% | string |
| `param_snapshot` | 62 | 100.0% | null, object |
| `param_version_id` | 62 | 100.0% | null, string |
| `param_version_number` | 62 | 100.0% | int, null |
| `remark` | 62 | 100.0% | null, string |
| `result` | 62 | 100.0% | object |
| `start_date` | 62 | 100.0% | string |

### `monitor_states`（47 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 47 | 100.0% | objectId |
| `apl_local` | 47 | 100.0% | object |
| `cash` | 47 | 100.0% | double |
| `config_versions` | 38 | 80.9% | null, object |
| `created_at` | 47 | 100.0% | date |
| `custom_metrics` | 32 | 68.1% | object |
| `date` | 47 | 100.0% | string |
| `day_count` | 47 | 100.0% | int |
| `event_log` | 47 | 100.0% | array |
| `last_prices` | 47 | 100.0% | object |
| `last_rebalance_date` | 47 | 100.0% | string |
| `last_rebalance_fx` | 47 | 100.0% | object |
| `manual_preset_next_date` | 47 | 100.0% | null |
| `manual_preset_step_pending` | 47 | 100.0% | bool |
| `monitor_id` | 47 | 100.0% | string |
| `nav` | 47 | 100.0% | double |
| `nav_base` | 47 | 100.0% | double |
| `nav_history` | 47 | 100.0% | array |
| `nav_history_model` | 41 | 87.2% | array |
| `pending_rebalance` | 47 | 100.0% | null |
| `performance_basis` | 47 | 100.0% | null |
| `positions_cny` | 47 | 100.0% | object |
| `positions_cny_base` | 47 | 100.0% | object |
| `positions_local` | 47 | 100.0% | object |
| `quantities` | 47 | 100.0% | object |
| `strategy_model_id` | 47 | 100.0% | null, string |
| `sub_strategy_performance` | 41 | 87.2% | array |
| `target_weights` | 47 | 100.0% | object |
| `total_replication_cost` | 47 | 100.0% | double |
| `total_trading_cost` | 47 | 100.0% | double |
| `trade_day_count` | 47 | 100.0% | int |
| `updated_at` | 47 | 100.0% | date |
| `vol_reset_count` | 47 | 100.0% | int |

### `strategy_param_versions`（70 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 70 | 100.0% | objectId |
| `allocator_params` | 70 | 100.0% | object |
| `asset_codes` | 70 | 100.0% | array |
| `change_summary` | 70 | 100.0% | string |
| `controller_code` | 70 | 100.0% | null, string |
| `controller_params` | 70 | 100.0% | object |
| `created_at` | 70 | 100.0% | date |
| `created_by` | 70 | 100.0% | null |
| `model_id` | 70 | 100.0% | string |
| `selector_enabled` | 70 | 100.0% | bool |
| `selector_params` | 70 | 100.0% | object |
| `selector_type` | 70 | 100.0% | null, string |
| `template_code` | 70 | 100.0% | string |
| `version` | 70 | 100.0% | int |

### `model_templates`（28 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 28 | 100.0% | objectId |
| `category` | 28 | 100.0% | string |
| `code` | 28 | 100.0% | string |
| `composition` | 28 | 100.0% | null, object |
| `created_at` | 28 | 100.0% | date |
| `description` | 28 | 100.0% | string |
| `is_active` | 28 | 100.0% | bool |
| `is_builtin` | 28 | 100.0% | bool |
| `name` | 28 | 100.0% | string |
| `parameters` | 28 | 100.0% | array |
| `pdf_filename` | 28 | 100.0% | null, string |
| `source_code` | 28 | 100.0% | string |
| `strategy_form` | 6 | 21.4% | string |
| `updated_at` | 28 | 100.0% | date |

### `monitor_daily_reports`（7434 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 7434 | 100.0% | objectId |
| `created_at` | 7434 | 100.0% | date |
| `daily_return` | 7434 | 100.0% | double |
| `date` | 7434 | 100.0% | string |
| `monitor_id` | 7434 | 100.0% | string |
| `nav` | 7434 | 100.0% | double |
| `performance` | 7434 | 100.0% | object |
| `positions` | 7434 | 100.0% | array |
| `signals` | 7434 | 100.0% | object |
| `total_leverage` | 7434 | 100.0% | double |

### `strategy_live_change_logs`（83 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 83 | 100.0% | objectId |
| `action` | 83 | 100.0% | string |
| `after` | 83 | 100.0% | object |
| `before` | 83 | 100.0% | object |
| `change_summary` | 83 | 100.0% | string |
| `created_at` | 83 | 100.0% | date |
| `live_version` | 83 | 100.0% | int, null |
| `model_id` | 83 | 100.0% | string |
| `monitor_scoped_changes` | 35 | 42.2% | object |
| `operator` | 83 | 100.0% | null, string |
| `source` | 83 | 100.0% | string |

### `monitored_strategies`（20 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 20 | 100.0% | objectId |
| `archive_reason` | 7 | 35.0% | string |
| `archived_at` | 7 | 35.0% | date |
| `asset_codes` | 20 | 100.0% | array |
| `asset_name_map` | 2 | 10.0% | object |
| `composition` | 2 | 10.0% | object |
| `created_at` | 20 | 100.0% | date |
| `description` | 20 | 100.0% | string |
| `display_name` | 20 | 100.0% | string |
| `source_ref` | 20 | 100.0% | string |
| `source_type` | 20 | 100.0% | string |
| `status` | 20 | 100.0% | string |
| `strategy_params` | 2 | 10.0% | object |
| `updated_at` | 20 | 100.0% | date |
| `weight_caps` | 2 | 10.0% | object |

### `portfolios`（9 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 9 | 100.0% | objectId |
| `created_at` | 9 | 100.0% | date |
| `created_by` | 9 | 100.0% | null |
| `current_capital` | 9 | 100.0% | double |
| `description` | 9 | 100.0% | null, string |
| `expected_metrics` | 9 | 100.0% | null, object |
| `inception_date` | 9 | 100.0% | date |
| `initial_capital` | 9 | 100.0% | double |
| `latest_backtest_summary` | 8 | 88.9% | null, object |
| `model_id` | 9 | 100.0% | null, string |
| `name` | 9 | 100.0% | string |
| `note` | 9 | 100.0% | null |
| `performance` | 8 | 88.9% | null, object |
| `portfolio_model_id` | 9 | 100.0% | string |
| `positions` | 9 | 100.0% | array |
| `rebalance_frequency` | 9 | 100.0% | null, string |
| `source` | 9 | 100.0% | string |
| `status` | 9 | 100.0% | string |
| `sub_strategies` | 9 | 100.0% | array |
| `updated_at` | 9 | 100.0% | date |
| `vol_annualize_factor` | 7 | 77.8% | int, null |
| `vol_leverage_max` | 7 | 77.8% | null |
| `vol_leverage_min` | 7 | 77.8% | null |
| `vol_lookback_long` | 9 | 100.0% | int, null |
| `vol_lookback_short` | 9 | 100.0% | int, null |
| `vol_method` | 7 | 77.8% | null, string |
| `vol_target` | 9 | 100.0% | null |
| `weight_method` | 9 | 100.0% | null, string |
| `weight_model_params` | 9 | 100.0% | object |

### `rebalance_records`（62 条）

| 字段 | 出现次数 | 覆盖率 | BSON 类型 |
|---|---|---|---|
| `_id` | 62 | 100.0% | objectId |
| `action` | 62 | 100.0% | string |
| `created_at` | 62 | 100.0% | date |
| `portfolio_id` | 62 | 100.0% | string |
| `positions_after` | 62 | 100.0% | array |
| `positions_before` | 62 | 100.0% | array |
| `reason` | 62 | 100.0% | string |
| `rebalance_date` | 62 | 100.0% | date |
| `weights_after` | 62 | 100.0% | null, object |
| `weights_before` | 62 | 100.0% | null |

## 2. 索引清单

### `strategy_models`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

### `backtest_records`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

### `monitor_states`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

### `strategy_param_versions`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

### `model_templates`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |
| `code_unique_active` | `code:1` | Y | - | Y |

### `monitor_daily_reports`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

### `strategy_live_change_logs`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

### `monitored_strategies`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

### `portfolios`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

### `rebalance_records`

| 索引名 | key | unique | sparse | partial |
|---|---|---|---|---|
| `_id_` | `_id:1` | - | - | - |

## 3. 基线文件指纹

| 文件 | 行数 | 字节 | sha256 |
|---|---|---|---|
| `tests/_routes_baseline.txt` | 247 | 10376 | `553ecf5967fa85e6976752f01911bcb70b0b0cfd784f533caefd332119847d65` |
| `tests/regression/golden_baseline.json` | 1 | 1093971 | `92280bd5a28fc3a2abfbd8227a3cdd0b80869e7fff2f06a8df6b13b731386e83` |

## 4. 关键计数（S14a 迁移与验收基数）

> `ModelStatus` 落库为中文值（`草稿` / `已发布` / `已归档`，见 `app/models/strategy_model.py:22-26`）。迁移脚本与验收查询一律用中文值；用 `published` 这类枚举名查询会恒得 0 条。

| 口径 | 条数 |
|---|---|
| strategy_models 总数 | 38 |
| status='已发布' | 18 |
| status='草稿' | 20 |
| status='已归档' | 0 |
| live_publish_enabled=True | 12 |
| [S14a→live] status='已发布' ∧ live_publish_enabled=True | 12 |
| [S14a→paper] status='已发布' ∧ live_publish_enabled=False | 6 |
| [S14a→research] status='草稿' | 20 |
| [S14a→retired] status='已归档' | 0 |
| is_portfolio=True | 11 |
| live_snapshot 存在 | 38 |

### `asset_prices` 口径（不入字段集聚合）

- 总条数：1405539；不同 `asset_code`：1204
- 顶层字段：`_id, amount, asset_code, close, date, high, low, open, scale, volume`
- `date` BSON 类型：`{'string': 1405539}`；样例值：`'2006-01-04'`
- **日期格式为 ISO 字符串 `YYYY-MM-DD`**，与回测请求的 `YYYYMMDD` 不同。查库必须用 ISO 格式；用 `YYYYMMDD` 做范围比较会恒得 0 条。

## 5. 性能基线（12 资产 × 3 年）

- 资产（12 个）：`159262.SZ, 159501.SZ, 159531.SZ, 159915.SZ, 159980.SZ, 159981.SZ, 159985.SZ, 510300.SH, 510500.SH, 511010.SH, 511030.SH, 511220.SH`
- 区间：`20230102` ~ `20251231`，重复 5 次

| 指标 | 值 |
|---|---|
| p50 墙钟 | 9.545 s |
| p95 墙钟 | 28.524 s |
| min / max | 8.519 / 28.524 s |
| 每次运行的 Mongo 读命令数 | [52, 52, 52, 52, 52] |
| 读命令分解 | `{"find": 231, "getMore": 60}` |

