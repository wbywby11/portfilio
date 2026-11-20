# 升级包 DZ_v0.01.01（2026-10-28，第 2 包）

## 一、基线

| 仓库 | 目录 | 远端 `origin/DZ_v0.01.01` | 本地 HEAD | 差异 |
|---|---|---|---|---|
| 后端 | `portfilio-end/` | `ba63fa1` | `ba63fa1` | 181 项未提交改动 |
| 前端 | `portfilio/` | `56f4da8` | `56f4da8` | 12 项未提交改动 |

两端提交历史与远端完全一致，本次升级内容**尚未 commit**，全部来自工作区改动。包内 `backend/`、`frontend/` 即这些改动的当前文件内容，按同名路径覆盖到服务器即可。

本包为**全量工作区差异**，可独立部署：无论服务器是否应用过 `upgrade_DZ_v0.01.01_20261027` / `upgrade_DZ_v0.01.01_20261028`，直接覆盖本包即到最新状态。

> 包名带 `_2` 是因为当日已有 `upgrade_DZ_v0.01.01_20261028`（14:53 生成）。两包**同基线、同范围**，本包只是在此基础上多了本轮 `nous_low_vol` 的 V6 直投版 3 与 V7 支持。相对上一包，105 个代码差异文件中 102 个逐字节一致、3 个内容有变化，前端 0 变化（见 `MANIFEST.md` 末节）。

包内构成：105 个代码差异文件 + 2 个 `migrations/` 脚本 + `MANIFEST.md` + 本文件，共 109 个文件，解压后 4.4 MB。

逐文件清单见 `MANIFEST.md`。

## 二、本次升级包含什么

181 项后端改动 + 12 项前端改动，是相对远端基线 `ba63fa1`、`56f4da8` 的**全部未提交改动**，不只有最近一轮。按时间分两部分：

- **本轮（2026-10-28 下午）**：`nous_low_vol` 支持范围从 V5 三档扩到「V5 三档 + V6 直投版 3 + V7」，后端 3 个文件，前端 0 项。
- **更早的累积**：178 项，与上一包逐字节一致（`factor_panel` dataset 维度、独立策略入库通道、前端因子截面导入页、弃用 `etf_discount`、日度波控按策略声明裁决、`factor_panel` 期日语义对齐）。

### 本轮改动

**1. `nous_low_vol` 新增港股分组与混合风险预算（`app/standalone_strategies/nous_low_vol/strategy.py`）**

| 改动 | 说明 |
|---|---|
| 第 7 个资产分组 `HK_EQ` | 新增入参 `hk_eq_codes`（港股组资产）。港股计入权益，参与 C8 混合风险预算的权益项，**不参与 A 股下限**。无港股版本留空即可 |
| 新增约束 **C8 混合风险预算** | 顺序投影变为 `C0→C2→C1→C6→C4→C3→C7→C8→C5→现金回填→剩余回填→复检 C7/C8→权重末检`。C8 计算式：权益(A股+港股)×w_eq + 黄金×w_gold + 商品×w_comm + QDII×w_qdii ≤ cap；超出时非 A 债四组同比例缩减，缺口由现金回填 A 债，剩余回填后**再次复检 C7/C8** |
| 新增 7 个入参 | `hk_eq_codes`、`mix_budget_cap`（上限）、`mix_budget_w_eq` / `mix_budget_w_gold` / `mix_budget_w_comm` / `mix_budget_w_qdii`（四组系数）、`require_full_invest`（强制满仓，默认开） |
| 数据契约放宽 | 分组必填性由「qdii / gold 必填」改为「仅 a_bond、a_eq 必填」，`hk_eq` / `qdii` / `qdii_usd` / `comm` / `gold` 允许留空。`cover_pool` 仍为 True，池内资产仍须归组 |
| 权重末检与监控指标 | 末检增加 C8 敞口断言；审计字典新增 `mix_cap_used`、`C8`、`C8_pre`、`C8_post`，随监控指标暴露到前端 |

策略参数总数 40 项，本轮新增 7 项全部落在「核心 / 高级」两组内，前端策略参数卡片直接渲染，无需前端改动。

**2. `app/allocation/strategy_manifest.py`（+4 / -2）**

`nous_low_vol` 的 `description` 由「V5 FOF 三档」改为覆盖「FOF 三档 / 含港股直投档 / 无商品低波档」三类口径。

**3. `tests/test_standalone_contract.py`（+26 / -9）**

交付边界测试由「只交 V5」改为「V5 三档 + V6 直投版 3 + V7」，并新增「已实现能力必须暴露入参」守卫（参数化 7 项，缺任一项即失败）。`hk_eq_codes` 从「不应出现」名单移入「必须出现」名单。

**4. 与原型对账结论**

V6 直投版 3 与 V7 各 143 个调仓期，用原型同窗口价格矩阵逐期调用系统策略类比对：

| 指标 | V6 直投版 3 | V7 |
|---|---|---|
| 逐资产权重最大绝对差 | `5.551e-17` | `5.551e-17` |
| 杠杆最大绝对差 | `2.220e-16` | `2.220e-16` |
| 选样不一致期数 | 0 / 143 | 0 / 143 |

差异在双精度浮点误差量级，视为完全一致。

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

`frontend/` 下只有 `src/` 内 12 个文件，与上一包逐字节一致，无依赖变更，不需重新 `npm install`。若服务器已应用过上一包，可跳过本步。

### 3.4 数据库动作（必读）

**（1）模板参数自动同步 —— 无需人工**

重启后端时 `init_builtin_templates()` 会把 `nous_low_vol` 模板的 `parameters`（40 项）、`composition`、`strategy_form` 按代码侧更新。前端策略参数区随即出现「港股组资产」「混合风险预算上限」「混合预算权益/黄金/商品/QDII 系数」「强制满仓」。

**（2）模板元数据同步 —— 必须手工执行一次**

启动同步**不覆盖** `name` / `description` / `source_code`（保护用户自定义）。本轮改了策略描述与策略源码，若不执行同步，前端「模板详情」仍显示旧的「V5 三档」说明与旧源码。

```bash
cd /path/to/portfilio-end
python migrations/sync_nous_low_vol_template.py            # 预演，只打印差异
python migrations/sync_nous_low_vol_template.py --apply    # 执行写入
```

脚本按 `code = nous_low_vol` 匹配活跃模板，命中数必须为 1 才写入，写完回读校验。可重复执行，第二次会报告「已一致」。

**（3）`factor_panel` 存量回填（同上一包）**

新代码查询一律带 `{"dataset": ...}`。若服务器库中已有 `factor_panel` 文档但**没有 `dataset` 字段**，升级后这些行查不到 —— 不报错，截面为空、策略静默选不出券。

```bash
python -c "from pymongo import MongoClient; \
db=MongoClient('mongodb://localhost:27017')['asset_allocation']; \
print('总数', db.factor_panel.count_documents({})); \
print('无dataset', db.factor_panel.count_documents({'dataset': {'\$exists': False}}))"
```

- 「无dataset」为 0（含集合不存在）：无需操作。
- 大于 0：执行回填（默认 dry-run，加 `--apply` 才写库）：

```bash
python migrations/backfill_factor_panel_dataset.py                    # 预演
python migrations/backfill_factor_panel_dataset.py --apply            # 执行
```

**（4）`sel_etf_discount` 模板自动下线（同上一包）**

后端启动时软删除（`is_active=False`，记录保留），启动日志应出现：

```
✓ 清理已移除的内置模板 [sel_etf_discount]
```

**（5）本轮无数据库结构变更**

本轮只改策略类与元数据，不新增集合、不新增索引、不写库。`model_templates` 之外的文档不受影响。

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

## 四、V6 直投版 3 与 V7 建模配置

新建模型 → 模板选「夏普风险平价」（`strategy_form = standalone`）→ 前端隐藏「资产选择策略」「风险控制策略」两张卡片，全部逻辑在策略包内，只需填资产分组与上限参数。

### 4.1 V6 直投版 3（16 选 12）

| 参数 | 值 |
|---|---|
| `a_bond_codes` | `511260.SH,511010.SH,511220.SH,511030.SH,511380.SH` |
| `a_eq_codes` | `510300.SH,510500.SH,159915.SZ,159531.SZ,510880.SH` |
| `hk_eq_codes` | `513600.SH,159262.SZ` |
| `comm_codes` | `159981.SZ,159980.SZ,159985.SZ,518880.SH` |
| `qdii_codes` / `qdii_usd_codes` / `gold_codes` | 留空 |
| `select_count` | `12` |
| `mix_budget_cap` | `0.20` |
| `mix_budget_w_eq` / `w_gold` / `w_comm` / `w_qdii` | 全部 `1.0` |
| `target_vol` | `0`（不做波动率缩放） |
| `enable_daily_vol_control` | `false`（纯月度调仓） |
| `require_full_invest` | `false` |
| `enable_aeq_backfill` | `false` |
| `qdii_cap` / `comm_cap` / `risk_budget_cap` / `abond_floor` / `abond_cap` / `aq_floor` / `aeq_risk_cap` / `aeq_floor_offset` / `abond_usd_cap` | 全部 `0`（不启用） |

### 4.2 V7（15 选 11，无美债、QDII≤3%）

| 参数 | 值 |
|---|---|
| `a_bond_codes` | `511260.SH,511010.SH,511220.SH,511030.SH,511380.SH` |
| `a_eq_codes` | `510300.SH,510500.SH,159915.SZ` |
| `qdii_codes` | `513650.SH,159501.SZ,513880.SH` |
| `comm_codes` | `159981.SZ,159980.SZ,159985.SZ,518880.SH` |
| `hk_eq_codes` / `qdii_usd_codes` / `gold_codes` | 留空 |
| `select_count` | `11` |
| `qdii_cap` | `0.03` |
| `mix_budget_cap` | `0.20` |
| `mix_budget_w_qdii` | `3.75` |
| `mix_budget_w_eq` / `w_gold` / `w_comm` | 全部 `1.0` |
| `target_vol` | `0` |
| `enable_daily_vol_control` | `false` |
| `require_full_invest` | `false` |
| `enable_aeq_backfill` | `false` |
| `abond_floor` / `abond_cap` / `aq_floor` / `aeq_risk_cap` / `aeq_floor_offset` / `abond_usd_cap` / `comm_cap` / `risk_budget_cap` | 全部 `0` |

V6 直投版 1/2 与直投版 3 只差资产池与 `select_count`，改分组即可复现，无需改代码。V2~V4 暂不支持（静态 A 股下限模式与强制替换口径未实现），参数区无对应开关。

### 4.3 数据前置（建模前必查）

V6 与 V7 的资产池里有 3 只在服务器库中**既无行情、也无主数据**，直接建模会在运行前门禁被判失败：

| 资产 | 情况 | 影响 |
|---|---|---|
| `159531.SZ` | 无 `asset_prices`、无 `assets` 记录 | V6 |
| `513600.SH` | 无 `asset_prices`、无 `assets` 记录 | V6 港股组 |
| `159262.SZ` | 无 `asset_prices`、无 `assets` 记录 | V6 港股组 |
| `510880.SH` | 有记录，但库内自 `2017-01-04` 起 | V6；缺 `2013-01-01 ~ 2017-01-03` 共 1046 个交易日 |

补数走前端既有通道（资产管理 → 导入；资产行情 → 多资产导入），不走脚本。

另有两处时效缺口，与上一包一致、不影响建模型但影响回测区间：

- 库内行情最新 `2026-07-27`，库内交易日历最新 `2026-08-26` —— 行情落后 21 个交易日；
- 原型口径终点为 `2026-10-26`，库内行情距该日还差 59 个交易日。回测终点只能取库内可用末日。

## 五、验证清单

| # | 项目 | 期望结果 |
|---|---|---|
| 1 | `python -m pytest tests -q --ignore=tests/regression` | `313 passed` |
| 2 | `python -m pytest tests/regression -q` | `56 passed` |
| 3 | 后端启动日志 | 出现 `✓ 清理已移除的内置模板 [sel_etf_discount]` |
| 4 | `python migrations/sync_nous_low_vol_template.py` | 首轮显示「需更新」并列出 3 个字段；`--apply` 后回读校验通过；再跑一次显示「已一致」 |
| 5 | 模板详情 → 策略参数 | 共 40 项，含「港股组资产」「混合风险预算上限」「混合预算权益/黄金/商品/QDII 系数」「强制满仓」 |
| 6 | 模板详情 → 说明 / 源码 | 说明含「V6 直投版 3」「V7 无商品 FOF15%」「V2~V4 暂不支持」；源码长度与 `strategy.py` 一致 |
| 7 | 新建模型 → 模板选「夏普风险平价」 | 「资产选择策略」「风险控制策略」两张卡片隐藏，参数全部在模型参数区 |
| 8 | 填 V6 / V7 分组后保存 | 数据契约通过（`qdii` / `gold` 留空不再报「必填为空」）；`hk_eq` 留空同样通过 |
| 9 | V6 直投版 3 回测 | 能跑通；补数后净值与原型 143 期对齐（权重差 ≤ 1e-16） |
| 10 | V7 回测 | 能跑通；QDII 权重 ≤ 3%，C8 敞口 ≤ 20% |
| 11 | 监控 → 发布后查看快照 | 快照 `parameters` 含资产分组与全部算法参数；`C8` / `mix_cap_used` 指标可见 |
| 12 | 前端 数据分析 → 因子截面数据 | 页面可打开，数据集下拉有 `bond_phoenix50`、`equity_quality_growth` |

第 9 项在补数前跑不通属预期：`159531.SZ` / `513600.SH` / `159262.SZ` 无数据，`510880.SH` 历史不足 `min_history_days`。V7 只用 `510300.SH` / `510500.SH` / `159915.SZ` 三只 A 股，历史齐全，补数前即可验证。

## 六、随包数据与不随包内容

**不随包**：
- `research/数据文档/` 下的因子截面 Excel（`research/` 不在任何 git 仓库内），需要导入时从本地单独取，走前端「因子截面数据」页上传：
  - `因子截面导入_凤凰50债券_2026Q4全池打分.xlsx`
  - `因子截面导入_凤凰50债券_历史成分快照.xlsx`
  - `因子截面导入_凤凰50股票_2026H1初筛池.xlsx`
- V6 / V7 缺失的行情与主数据（见 4.3），按前端通道导入。
- `.env`、`logs/`、`venv/`、`dist/`、`.mongodb-data/`。

**随包**：`tests/regression/bond_factor_score_index/` 下的价格矩阵与基线净值、`tests/regression/manifests/nous_low_vol_fof40_none_nav.csv`（原型对账基线）、`migrations/` 下两个脚本。

## 七、回滚

代码回滚：用 3.1 的备份覆盖回去。

数据库侧无破坏性变更：

- 本轮不新增集合、不新增索引；
- `model_templates` 中 `nous_low_vol` 的 `parameters` 会被写成 40 项，回滚旧代码后启动同步会按旧代码声明重新覆盖，无需手工处理；
- 若执行了 `sync_nous_low_vol_template.py --apply`，`name` / `description` / `source_code` 已写成本轮内容，回滚后需手工改回（脚本不会反向同步）；
- `factor_panel` 回填新增的 `dataset` 字段不影响旧代码查询（旧代码不投影该字段）；
- 模板软删除会因旧代码的 `_KNOWN_BUILTIN_CODES` 不含该 code 而保持下线，需要恢复时把 `model_templates` 中该记录的 `is_active` 改回 `True`。
