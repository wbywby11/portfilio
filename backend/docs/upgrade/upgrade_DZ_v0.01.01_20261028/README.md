# 升级包 DZ_v0.01.01（2026-10-28）

## 一、基线

| 仓库 | 目录 | 远端 `origin/DZ_v0.01.01` | 本地 HEAD | 差异 |
|---|---|---|---|---|
| 后端 | `portfilio-end/` | `ba63fa1` | `ba63fa1` | 181 项未提交改动 |
| 前端 | `portfilio/` | `56f4da8` | `56f4da8` | 12 项未提交改动 |

两端提交历史与远端完全一致，本次升级内容**尚未 commit**，全部来自工作区改动。包内 `backend/`、`frontend/` 即这些改动的当前文件内容，按同名路径覆盖到服务器即可。

本包为**全量工作区差异**，可独立部署。相对上一包 `upgrade_DZ_v0.01.01_20261027`，后端只多 16 项变化，前端无变化（见 `MANIFEST.md` 末节）。服务器无论是否已应用上一包，直接覆盖本包即可。

逐文件清单见 `MANIFEST.md`。

## 二、本次升级包含什么

181 项后端改动 + 12 项前端改动，是相对远端基线 `ba63fa1`、`56f4da8` 的**全部未提交改动**，不只有最近一轮。按时间分两部分：

- **本轮（2026-10-28）**：下面 3 组，共 16 项后端，前端 0 项。
- **更早的累积**：165 项，同上一包（`factor_panel` dataset 维度、独立策略入库通道、前端因子截面导入页、弃用 `etf_discount`）。

### 本轮改动

**1. 日度波控按策略声明裁决（后端 5 个文件 + 3 个测试文件）**

波控的三条裁决规则从引擎内部固定行为改为策略声明驱动：

| 文件 | 动作 |
|---|---|
| `app/backtesting/schedule.py` | 新增 `VOL_RESET_POLICY_PROTOTYPE`（三键全 `True`）、`VOL_RESET_POLICY_LEGACY_ENGINE`（三键全 `False`）、`parse_declared_vol_reset_policy` |
| `app/standalone_strategies/nous_low_vol/strategy.py` | `get_execution_schedule()` 返回 `vol_reset_policy` 三键 |
| `app/backtesting/engine.py` | 读策略声明；未声明走 LEGACY。按三键裁决：同一执行日月度优先、信号日即常规调仓执行日跳过、信号日至执行日之间存在常规调仓执行日跳过 |
| `app/monitor/signal_detector.py` | 波动率窗口与年化因子改读策略参数 `vol_windows`、`annualization_factor`（此前固定用 `config.VOL_WINDOWS` / `ANNUALIZE_FACTOR`）；同步三键裁决 |
| `app/services/published_snapshot.py`、`app/monitor/monitor_runtime.py` | 发布快照冻结 `vol_reset_policy`，监控运行态从快照透传 |

**升级后 `nous_low_vol` 的回测净值会与升级前不同**：该策略此前走引擎 LEGACY 行为，现在按自己声明的三键执行。这是本次修正的目标，不是回归问题。其他策略未声明该键，仍走 LEGACY，净值不变。

**2. `factor_panel` 期日语义对齐（后端 5 个文件 + 1 个测试）**

`as_of_date` 的语义由「权重生效日」改为「决策日（信号日）」：T 日收盘用该截面算权重，收益自 T+1 起。

| 文件 | 动作 |
|---|---|
| `app/models/factor_panel.py` | 新增 `data_date` 不得晚于 `as_of_date` 的模型校验，前视直接报错拒绝 |
| `app/services/factor_panel_service.py` | 同一期日存在多个 `data_date` 时写入 `warnings.periods_with_multiple_data_dates`，不静默放行 |
| `app/services/factor_panel_templates.py` | 股票模板示例日期 `2026-06-15` 改为决策日 `2026-06-12` |
| `app/api/factor_panel.py`、`app/services/factor_panel_importer.py` | 参数说明与注释措辞统一 |

**3. 新增测试**

`tests/test_factor_panel_asof_semantics.py`、`tests/test_standalone_contract.py`；原型对账门禁 `tests/regression/test_prototype_alignment.py` 与 `tests/regression/manifests/`（`nous_low_vol.yaml`、`nous_low_vol_fof40_none_nav.csv`）。

## 三、部署步骤

### 3.1 备份

```bash
cd /path/to/portfilio-end && tar czf ~/backup-end-$(date +%Y%m%d).tar.gz .
cd /path/to/portfilio     && tar czf ~/backup-fe-$(date +%Y%m%d).tar.gz src
```

### 3.2 后端代码

```bash
cp -r upgrade_.../backend/. /path/to/portfilio-end/
cp -r upgrade_.../migrations /path/to/portfilio-end/    # 本包附带，非 git 差异
```

包内只含差异文件，未改动的文件不会被覆盖。`.env`、`venv/`、`logs/` 不在包内，保持服务器原样。

### 3.3 前端代码

```bash
cp -r upgrade_.../frontend/. /path/to/portfilio/
cd /path/to/portfilio && npm run build
```

`frontend/` 下只有 `src/` 内 12 个文件，无依赖变更，不需重新 `npm install`。

### 3.4 数据库动作（必读）

**（1）`factor_panel` 存量回填**

新代码查询一律带 `{"dataset": ...}`。若服务器库中已有 `factor_panel` 文档但**没有 `dataset` 字段**，升级后这些行查不到 —— 不报错，截面为空、策略静默选不出券。

先查存量：

```bash
python -c "from pymongo import MongoClient; \
db=MongoClient('mongodb://localhost:27017')['asset_allocation']; \
print('总数', db.factor_panel.count_documents({})); \
print('无dataset', db.factor_panel.count_documents({'dataset': {'\$exists': False}}))"
```

- 若「无dataset」为 0（含集合不存在）：无需操作。
- 若大于 0：执行回填（默认 dry-run，加 `--apply` 才写库）：

```bash
cd /path/to/portfilio-end
python migrations/backfill_factor_panel_dataset.py                    # 预演
python migrations/backfill_factor_panel_dataset.py --apply            # 执行
python migrations/backfill_factor_panel_dataset.py --apply --dataset bond_phoenix50
```

索引无需手工处理：`FactorPanelService.ensure_indexes` 会自动建三元唯一索引 `uniq_dataset_period_code`，并由 `_drop_legacy_indexes` 删除旧的二元唯一索引 `uniq_period_code`。

**（2）`sel_etf_discount` 模板自动下线**

后端启动时 `init_builtin_templates()` 会把该模板软删除（`is_active=False`，记录保留）。启动日志应出现：

```
✓ 清理已移除的内置模板 [sel_etf_discount]
```

**（3）`etf_discount_market_data` 集合**

本包不含删表操作。若服务器存在该集合，数据原样保留。

**（4）本轮新增：无数据库结构变更**

- `data_date` 校验只作用于写入路径，存量文档不回溯、不批量改写。
- 发布快照新增的 `vol_reset_policy` 键在下次发布时写入。存量快照缺该键时，监控按 `VOL_RESET_POLICY_PROTOTYPE`（三键全 `True`）执行，与升级前行为一致，**不需要**为本次升级重新发布存量组合。

### 3.5 处理删除项

`MANIFEST.md` 中「删除（包内无，须在服务器删除）」共 88 项，与上一包一致：

| 类别 | 数量 | 处理建议 |
|---|---|---|
| `app/models/etf_discount.py`、`app/selection/selectors/etf_discount.py` | 2 | 建议删除。对应 import 已全部移除 |
| `scripts/_*.py`、`scripts/_*.log`、`scripts/_*.txt` | 11 | 建议删除，历史临时诊断脚本 |
| `data/seed/gmsi2/**`、`data/seed/.gitkeep` | 75 | 先确认再删。复现用期货 seed 数据，若服务器有代码读取则保留 |

```bash
cd /path/to/portfilio-end
rm -f app/models/etf_discount.py app/selection/selectors/etf_discount.py
rm -f scripts/_*.py scripts/_*.log scripts/_*.txt
```

### 3.6 重启与验证

```bash
cd /path/to/portfilio-end && python main.py
# 前端已构建到 dist/，按现有方式发布
```

## 四、验证清单

| # | 项目 | 期望结果 |
|---|---|---|
| 1 | `python -m pytest tests -q --ignore=tests/regression` | `307 passed` |
| 2 | `python -m pytest tests/regression -q` | `56 passed` |
| 3 | 后端启动日志 | 出现 `✓ 清理已移除的内置模板 [sel_etf_discount]` |
| 4 | `GET /api/v1/factor-panel/datasets` | 返回 `bond_phoenix50`、`equity_quality_growth` |
| 5 | 前端 数据分析 → 因子截面数据 | 页面可打开，数据集下拉有值，可下载对应模板 |
| 6 | 前端 新建模型 → 选择器 | 下拉无「ETF贴水率」，选择器共 6 个 |
| 7 | 债券券池因子打分指数 回测 | 能跑通，与 `tests/regression/bond_factor_score_index/baseline_nav.csv` 对齐 |
| 8 | NOUS 低波版 回测 | 波控日志出现「跳过日度信号」或「月度优先：丢弃挂起的日度信号」；净值与升级前不同属预期 |

## 五、随包数据与不随包内容

**不随包**：
- `research/数据文档/` 下的因子截面 Excel（`research/` 不在任何 git 仓库内），需要导入时从本地单独取，走前端「因子截面数据」页上传：
  - `因子截面导入_凤凰50债券_2026Q4全池打分.xlsx`
  - `因子截面导入_凤凰50债券_历史成分快照.xlsx`
  - `因子截面导入_凤凰50股票_2026H1初筛池.xlsx`
- `.env`、`logs/`、`venv/`、`dist/`、`.mongodb-data/`。

**随包**：`tests/regression/bond_factor_score_index/` 下的价格矩阵与基线净值（第 7 项验证用）、`tests/regression/manifests/nous_low_vol_fof40_none_nav.csv`（原型对账基线）。

## 六、回滚

代码回滚：用 3.1 的备份覆盖回去。

数据库侧无破坏性变更：

- 三元唯一索引比原二元索引更宽（允许同 (期日,代码) 多数据集并存），旧数据加 `dataset` 后可继续用；
- 若执行了回填，回滚旧代码后多出的 `dataset` 字段不影响旧查询（旧代码不投影该字段）；
- 回滚后 `nous_low_vol` 的回测净值会回到 LEGACY 波控口径；
- 模板软删除会因旧代码的 `_KNOWN_BUILTIN_CODES` 不含该 code 而保持下线，需要恢复时把 `model_templates` 中该记录的 `is_active` 改回 `True`。
