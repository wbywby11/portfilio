# 数据导入子系统规范

> **已归档（2026-10-31）**：本文档已并入 `DATA_SYSTEM.md` 第四节，后续导入通道变更只更新该文档。本文保留作历史参考，不再修改。
>
> 定义所有外部数据进入系统的标准链路。
> - **前端导入界面**：规范交互流程、UI 组件、模板下载
> - **后端导入脚本**：规范映射、校验、写入、审计
>
> 配套文档：`DATA_ARCHITECTURE.md`（集合设计）、`DATA_GOVERNANCE.md`（生命周期管理）

---

## 一、导入入口全景

### 1.1 入口清单

> **审计接入现状（遗留项）**：`services/import_audit_service.py`（`ImportAuditService`）
> 的**写入侧**目前仅 `services/trade_calendar_service.py`（交易日历导入）一处调用；
> 读取侧另有 `agent/tools/data_ops_tools.py`（审计查询/管理）。
> 下表其余导入端点（资产主数据、单资产行情、多资产宽表、汇率）**尚未接入审计**，
> 登记为遗留项，不在「独立策略统一接入管道」范围内。
> 例外：因子截面（#10）为新增端点，写入侧已接入审计。

| # | 数据类型 | API 端点 | 输入 | 前端入口 | 目标集合 |
|---|---------|---------|------|---------|---------|
| 1 | 资产主数据 | `POST /assets/import/excel` | Excel | AssetList.vue | `assets` |
| 2 | 单资产行情(JSON) | `POST /assets/prices/import` | JSON | Agent / 内部 | `asset_prices` |
| 3 | 单资产行情(Excel) | `POST /assets/prices/import/excel` | Excel | AssetQuote.vue | `asset_prices` |
| 4 | 多资产宽表解析 | `POST /assets/prices/import/multi-asset/parse` | Excel | AssetQuote.vue | — (仅解析) |
| 5 | 多资产宽表导入 | `POST /assets/prices/import/multi-asset` | JSON | AssetQuote.vue | `assets` + `asset_prices` |
| 6 | 汇率 | `POST /fx/import` | Excel | FxImport.vue | `fx_rates` |
| 7 | 交易日历 | `POST /trade-dates/import` | Excel | TradeCalendarPanel.vue | `trade_dates` |
| 8 | 波动率曲面 | `POST /options/vol-surface/import/excel` | Excel | optionPricing.js | `option_vol_surfaces` |
| 9 | 主体风险 | `POST /subject-risk/import` | JSON(上游API) | Agent 调用 | `subject_risk_records` |
| 10 | 因子截面 | `POST /factor-panel/import` | Excel | FactorPanelImport.vue | `factor_panel` |
| 11 | 宏观与估值序列 | `POST /macro/import` | Excel | MacroImport.vue | `macro_series` |

> **#10 因子截面的特殊之处（必读）**：`factor_panel` 集合被**多个数据产品共用**，
> 导入时 `dataset` 为 **Form 必填参数**（受控清单 `field_mappings.FACTOR_DATASETS`，
> 不在清单内直接报错），业务主键为 `(dataset, as_of_date, code)` 三元。
> 选错 dataset **不会报错**，数据会静默写进另一个截面，因子键与策略参数对不上。
> 配套端点共 6 个：`POST /import`、`GET /datasets`（数据集清单）、`GET /overview`（库内总览）、
> `GET /period/{dataset}/{as_of_date}`（读某期核对）、`DELETE /period/{dataset}/{as_of_date}`（整期删除，
> 只删本数据集）、`GET /template/download?dataset=`（模板按数据集出）。
>
> **#11 宏观与估值序列**：`macro_series` 一个集合装多条序列（指数 PE/PB/股息率、
> 债券收益率、信用利差、ERP 分量等），业务主键 `(code, date)`，与 `assets` /
> `asset_prices` 完全解耦（这些序列不是可交易资产）。数据表支持宽表（第一列日期 +
> 后续列名为序列代码）与长表（含 `序列代码`/`数值`/`日期`）两种形态，自动识别；
> 可选「序列说明」工作表标注 `series_type`（受控清单 `MACRO_SERIES_TYPES`）/单位/来源，
> 缺表时按 `other` 归档并在返回 warnings 里列出未登记序列。`mode=replace` **只清空
> 文件中出现的序列代码**（不是整集合清空），`incremental` 只补缺失 `(code, date)`。
> 配套端点：`GET /macro/stats`、`GET /macro/series`、`GET /macro/data?code=`、
> `GET /macro/template/download`。

### 1.2 分类

| 类型 | 输入 | 协议 | 典型场景 |
|------|------|------|---------|
| **文件导入** | Excel/CSV | `multipart/form-data` | 用户在界面上传 |
| **结构化导入** | JSON | `application/json` | Agent 工具调用、API 直传 |

两类共享同一套流程层和审计层规范。

---

## 二、五层架构总览

```
前端层（Layer 5） ─── 统一导入交互组件
审计层（Layer 4） ─── _import_audit_log 集合
流程层（Layer 3） ─── 标准 8 步链路
协议层（Layer 2） ─── 统一 ImportResponse Schema
映射层（Layer 1） ─── field_mappings.py 集中映射
```

---

## 三、后端规范（Layer 1 ~ Layer 4）

### Layer 1：映射层

**文件位置**：`app/schemas/field_mappings.py`（唯一映射来源）

**映射表**：

| 常量名 | 用途 | 核心映射示例 |
|--------|------|-------------|
| `PRICE_COLUMN_MAPPING` | 行情导入 | 日期→date, 收盘价→close, 开盘价→open, 成交量→volume ... |
| `ASSET_COLUMN_MAPPING` | 资产主数据 | 资产代码\*→code, 资产名称\*→name, 资产类型\*→asset_type ... |
| `TRADE_DATES_COLUMN_MAPPING` | 交易日历 | 交易日→date, Date→date, trade_date→date ... |

**强制规则**：
- 所有导入路径（API 端点、Agent Tool、脚本）**禁止硬编码列名映射**，必须引用上述常量
- 新增数据类型时，在此文件中添加对应映射常量
- 汇率列名固定为货币代码（EUR/USD/HKD/JPY/CNH），由 `FxService.FX_COLUMNS` 管理，无需映射

**改造清单**（当前存在 3 处重复定义）：

| 现有位置 | 现有变量 | 改为引用 |
|---------|---------|---------|
| `api/asset.py` L31-55 | `_parse_excel_to_price_list` 内 `column_mapping` | `PRICE_COLUMN_MAPPING` |
| `api/asset.py` L213-227 | `import_assets_from_excel` 内 `mapping` | `ASSET_COLUMN_MAPPING` |
| `schemas/asset.py` L11-31 | `_PRICE_IMPORT_ROW_KEY_CN` | `PRICE_COLUMN_MAPPING` |
| `trade_calendar_service.py` L20-25 | `_DATE_COLUMN_MAPPING` | `TRADE_DATES_COLUMN_MAPPING` |

---

### Layer 2：协议层

**统一响应 Schema**：`app/schemas/import_protocol.py`

#### ImportResponse 字段规范

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `target_collection` | string | ✅ | 目标集合名 |
| `mode` | enum | ✅ | `upsert` / `replace` / `incremental` / `strict` |
| `total_rows` | int | — | 文件/请求中总行数 |
| `inserted_count` | int | — | 新增条数 |
| `updated_count` | int | — | 更新条数 |
| `skipped_count` | int | — | 跳过条数 |
| `error_count` | int | — | 错误条数 |
| `errors` | list | — | 错误明细（最多前 50 条），每条含 `row_index` / `code` / `field` / `message` / `raw_value` |
| `skipped_reasons` | dict | — | 跳过原因分类，如 `{"non_trade_day": 3, "duplicate": 5}` |
| `date_range` | string | — | `"YYYY-MM-DD ~ YYYY-MM-DD"` |
| `import_id` | string | ✅ | 审计日志 ID |

#### ImportErrorCode 枚举

| 错误码 | 含义 | 触发场景 |
|--------|------|---------|
| `parse_failed` | 文件/格式解析失败 | Excel 损坏、无法读取 |
| `missing_required` | 必填字段缺失 | 模板缺少必要列 |
| `type_mismatch` | 字段类型不匹配 | 数值列出现文本 |
| `invalid_value` | 值域校验失败 | 日期不合法、close ≤ 0 |
| `ref_not_found` | 外键引用不存在 | asset_code 不在 assets 中 |
| `duplicate_key` | 主键重复（仅 strict 模式） | — |
| `internal` | 服务端内部错误 | 未知异常 |

#### ImportMode 枚举

| 模式 | 含义 | 适用场景 |
|------|------|---------|
| `upsert` | 按业务主键 upsert（默认） | 日常增量导入 |
| `replace` | 清空后全量覆盖 | 全量替换数据 |
| `incremental` | 仅新增，已有跳过 | 填补历史空缺 |
| `strict` | 有任何错误则全部回滚 | 高可靠性场景 |

---

### Layer 3：流程层

所有导入必须经过以下 8 步链路：

| 步骤 | 动作 | 失败处理 |
|:----:|------|---------|
| ① | 文件接收 / JSON 接收 | 文件上限 50MB，仅 `.xlsx`/`.xls`/`.csv`，超限返回 413 |
| ② | 格式解析（pandas / Pydantic） | → `parse_failed` |
| ③ | 列名映射（引用 `field_mappings.py`） | 缺失必要列 → `missing_required`；**禁止硬编码** |
| ④ | Pydantic 类型校验（逐行，收集所有错误） | → `type_mismatch`；不因一行中止全批 |
| ⑤ | 值域归一化：日期→`YYYY-MM-DD`，数值→float，枚举→合法值 | → `invalid_value` |
| ⑥ | 业务校验：外键存在性、日期合理性（1990~今日+30天） | → `ref_not_found` |
| ⑦ | 幂等写入：BulkWrite 每批 ≤ 1000 条 | 按 mode 执行 |
| ⑧ | 写入审计日志 + 返回 ImportResponse | — |

**日期归一化细则**：
- 兼容输入：`YYYY-MM-DD`、`YYYYMMDD`、Excel 序列日、ISO 8601
- 入库统一为 `"YYYY-MM-DD"` 字符串
- **例外**：`trade_dates.date` 存为 datetime（ISODate），写入时须转换

---

### Layer 4：审计层

每次导入操作写入 `_import_audit_log` 集合：

| 字段 | 类型 | 说明 |
|------|------|------|
| `_id` | ObjectId | 导入操作 ID |
| `target_collection` | string | 目标集合 |
| `import_mode` | string | upsert / replace / incremental |
| `source_type` | string | `excel` / `json` / `api_upstream` |
| `source_filename` | string\|null | 文件名 |
| `operator` | string | 用户ID / `"agent"` / `"system"` |
| `created_at` | datetime | 操作时间 |
| `stats` | object | `{total_rows, inserted, updated, skipped, errors}` |
| `error_summary` | list | 错误摘要（前 10 条） |
| `date_range` | string\|null | 数据日期范围 |
| `duration_ms` | int | 耗时（毫秒） |

**索引**：`{target_collection: 1, created_at: -1}`、`{operator: 1, created_at: -1}`

**生命周期**：rolling，保留 180 天。

---

## 四、前端导入界面规范（Layer 5）

### 4.1 标准交互流程

```
选择文件 + 选模式  →  预览确认（dry-run）  →  执行导入  →  结果展示
```

### 4.2 Step 1 — 选择文件与模式

**必须元素**：
- `el-upload` 组件，限制 `.xlsx`/`.xls`，单次 1 文件
- 导入模式单选：增量合并（upsert，默认）/ 全量覆盖（replace）/ 仅新增（incremental）
- **下载模板**按钮
- **预览数据**按钮
- **数据集选择器**：仅当一个集合被多个数据产品共用时需要（当前只有因子截面）。
  `factor_panel` 的导入、模板下载、总览、读取与删除全部按 `dataset` 分区，
  页面必须先选定数据集再选文件；可选项走 `GET /factor-panel/datasets`，不得前端写死

**规则**：
- 默认模式为 `upsert`
- 选择 `replace` 模式时须弹出二次确认对话框："此操作将清空现有数据，确定继续？"

### 4.3 Step 2 — 预览确认（dry-run）

调用后端 parse + validate 端点，**不写库**，返回统计 + 错误。

**展示内容**：
- 有效行数、日期范围
- 预估新增 / 更新 / 跳过条数
- 错误列表（前 10 条），用 `el-alert type="warning"` 展示
- 错误 > 10 条时提示"还有 N 条错误，导入后可查看完整列表"

**操作按钮**：取消 / 确认导入

### 4.4 Step 3 — 执行导入

- 小批量（< 500 行）：loading 遮罩 + 按钮禁用
- 大批量（≥ 500 行）：进度条（轮询进度接口）

### 4.5 Step 4 — 结果展示

**必须展示**：
- 状态标记（成功/部分成功/失败）
- 统计：新增 N 条 / 更新 N 条 / 跳过 N 条 / 错误 N 条
- 日期范围
- 错误明细表格：行号 / 字段 / 错误描述（如有错误时展示）

**操作按钮**：关闭 / 查看导入历史

> **统计字段契约**：结果统计统一使用 `inserted_count` / `updated_count` / `skipped_count` /
> `error_count`（不存在 `success_count` 字段）。历史上前端 AssetList.vue 误读 `success_count`
> 导致提示永远 0 条，已于 `upgrade_20260819_v4` 修复。

### 4.6 模板下载规范

每个支持 Excel 导入的数据类型**必须**提供模板下载端点：

| 数据类型 | 模板下载端点 | 状态 |
|---------|-------------|:----:|
| 资产主数据 | `GET /assets/template/download` | ✅ 已有 |
| 单资产行情 | `GET /assets/prices/template/download?kind=full` | ✅ 已有 |
| 多资产宽表 | `GET /assets/prices/template/download/multi-asset` | ✅ 已有 |
| 汇率 | `GET /fx/template/download` | 待新增 |
| 交易日历 | `GET /trade-dates/template/download` | 待新增 |
| 波动率曲面 | `GET /options/vol-surface/template/download` | 待新增 |
| 因子截面 | `GET /factor-panel/template/download?dataset=<数据集>` | ✅ 已有 |

**模板格式**：
- `.xlsx` 格式，UTF-8 编码
- 第 1 行为表头，必填列加 `*` 后缀（如 `资产代码*`、`日期*`）
- 第 2~4 行为示例数据（3 行示例 + 注释说明行）
- 日期示例用 `YYYY-MM-DD`，数值用小数无千分位

> **模板按数据集分开出的情形**：因子截面模板由 `services/factor_panel_templates.py` 的
> `TEMPLATE_COLUMNS_BY_DATASET` 驱动，债券券池（`bond_phoenix50`）与 A 股质量成长
> （`equity_quality_growth`）的因子列不同，共用一份模板会让人把 A 数据集的因子填进
> B 数据集的文件（落库不报错，属静默错误）。新增数据集必须同时在
> `FACTOR_DATASETS` 与本模块登记模板列，否则模块导入即报错（`_validate_template_coverage`）。

---

## 五、原始数据文件规范（研究员数据源）

> 研究员提供的原始 Excel 文件是系统基础数据的权威来源。
> 导入时必须确保文件与库内数据完全对齐，任何偏差都会导致回测/监控结果不一致。

### 5.1 标准文件清单

| 文件 | 内容 | 目标集合 | 关键格式 |
|------|------|---------|----------|
| `daily_px.xlsx` | 18 类资产日频收盘价（宽表） | `asset_prices` | 第1列=日期，后续列=资产中文名 |
| `fx.xlsx` | 汇率（各币种兑人民币） | `fx_rates` | 第1列=日期索引，后续列=币种代码 |
| `trade_dates.xlsx` | 交易日历 | `trade_dates` | 单列日期（列名 `trade_dates` 或第一列） |

### 5.1.1 派生导入文件（research/数据文档）

原始源文件经生成脚本转换为前端可直接导入的文件，入口对照详见 `research/数据文档/README.md`：

| 派生文件 | 生成脚本 | 格式 | 正确导入入口 |
|---------|---------|------|---------|
| `资产列表导入.xlsx` | `gen_import_files.py` | 资产主数据长表 | 资产管理页「批量导入 Excel」（`POST /assets/import/excel`） |
| `行情导入_收盘价.xlsx` | `gen_import_files.py` | 多资产宽表 | 资产行情页「多资产Excel导入」（metric=收盘价） |
| `daily_px_导入版.xlsx` | `optimize_daily_px_layout.py` | 多资产宽表 | 同上 |
| `资产列表导入_夏普18.xlsx` | `optimize_daily_px_layout.py` | 资产主数据长表 | 资产管理页「批量导入 Excel」 |
| `因子截面导入_凤凰50债券_2026Q4全池打分.xlsx` | `gen_import_from_factor_pool.py` | 因子截面长表（sheet 名「因子截面数据」） | 数据分析 →「因子截面数据」页，dataset=`bond_phoenix50` |
| `因子截面导入_凤凰50债券_历史成分快照.xlsx` | `gen_import_from_factor_pool.py` | 同上，**不含任何因子列**（整期无因子才被判为成分快照期） | 同上，dataset=`bond_phoenix50` |
| `因子截面导入_凤凰50股票_2026H1初筛池.xlsx` | `gen_import_from_factor_pool.py` | 因子截面长表 | 同上，dataset=`equity_quality_growth`；导入前需先补 `assets` 与行情 |

> **格式红线**：单资产行情导入（`POST /assets/prices/import/excel`）只接受长表
> （日期 + 收盘价/开盘价等数值列至少一列）；宽表必须走多资产入口，否则 400。

### 5.2 daily_px.xlsx 格式说明

- **日期列**：第一列，可能无表头（`Unnamed`），导入时须兼容处理
- **资产列**：列名为中文资产名（如“沪深300”“标普500”）
- **值**：归一化价格指数（非原始点位，基期=1.0）
- **空值**：资产未上市期间为空，导入时跳过

**资产列名 → asset_code 映射**（引用 `app/monitor/config.py` 中 `SHARPE_NAME_TO_CODE`，仅供 legacy 研究员通道使用）：

| 列名 | asset_code | 计价货币 |
|------|-----------|----------|
| 沪深300 | `000300.SH` | CNH |
| 中证500 | `ZZ000905` | CNH |
| 创业板指 | `SZ399006` | CNH |
| 标普500 | `SPX` | USD |
| 纳斯达克100 | `NDX` | USD |
| 日经225 | `N225` | JPY |
| 中国10年国债 | `ZQGZ10` | CNH |
| 中国5年国债 | `ZQGZ5` | CNH |
| 中国2年国债 | `ZQGZ2` | CNH |
| 美国10年国债 | `UST10` | USD |
| 美国2年国债 | `UST2` | USD |
| 可转债 | `CVTBND` | CNH |
| 黄金 | `GLD` | CNH |
| 布伦特原油 | `B00Y` | USD |
| 沪铜 | `SHCU` | CNH |
| 沪铝 | `SHAL` | CNH |
| 沪锡 | `SHSN` | CNH |
| 豆粕 | `DM` | CNH |

> **资产 code 自由命名，但一经使用不得变更**。`assets.code` 是业务主键（任意字符串），
> `asset_prices.asset_code` 引用它，且 `uniq_asset_date` 唯一索引以 (asset_code, date) 为键：
> 改 code 等于新建一份历史，旧行情全部失联。
>
> 上表 18 个代码是 `monitor/config.py` `SHARPE_NAME_TO_CODE` 的 **legacy 研究员通道专用映射**，
> 仅 `monitor_runtime.legacy_runtime()`、`monitor_service` 基线路径与夏普 18 研究员引擎消费，
> **不是导入白名单**——导入链路（`schemas/field_mappings.py` `ASSET_COLUMN_MAPPING`）不做任何代码合法性校验。
>
> 新接入的数据集建议命名 `<域前缀>_<语义>`（如 `nous_lowvol_a10y_bond`），
> 同一底层标的的不同加工口径（原始收盘价 / 拼接连续序列 / 复权净值）**必须用不同 code**：
> 同 code 在 `uniq_asset_date` 下会互相覆盖，且不同日历口径（交易日 vs 工作日）的行会混存，
> 污染所有读该资产的策略。
>
> 数据是否符合某个策略的要求，不由导入侧判定，而由策略自己声明的
> **数据契约**在运行前把关（`app/backtesting/data_contract.py`，见 DATA_GOVERNANCE.md §5.2）。

### 5.3 fx.xlsx 格式说明

- **读取方式**：`pd.read_excel(path, index_col=0, parse_dates=True)`
- **币种列**：列名为货币代码（USD / JPY / CNH / EUR / HKD）
- **值**：该货币兑人民币汇率（如 JPY=0.0415 表示 1 日元 = 0.0415 人民币）
- **当前实际包含**：USD、CNH、JPY 三列（EUR、HKD 待补充）
- **导入模式**：增量填补（不覆盖已有值）或全量替换

> **关键警告**：缺少任何币种汇率会导致监控引擎将外币资产折算为 1.0（静默错误），
> 直接影响 NAV 计算结果。导入后必须验证所有策略涉及的币种均有数据。

### 5.4 trade_dates.xlsx 格式说明

- **列名**：`trade_dates` 或第一列（无固定表头）
- **入库格式**：datetime（ISODate），非字符串（历史设计，见 DATA_ARCHITECTURE.md §1.3）
- **导入模式**：存在则跳过（幂等）

### 5.5 导入环境要求

| 配置项 | 正确值 | 说明 |
|--------|--------|------|
| MongoDB 地址 | `mongodb://localhost:27018` | 项目专用实例（.env 中配置） |
| 数据库名 | `asset_allocation` | settings.py 中 DATABASE_NAME，**禁止硬编码其他名称** |
| 价格集合 | `asset_prices` | — |
| 汇率集合 | `fx_rates` | — |
| 日历集合 | `trade_dates` | — |

> **历史教训**：曾因脚本中硬编码错误数据库名（如 `portfilio`）导致数据写入错误实例，
> 前端无法看到导入结果。所有脚本必须从 `app.config.settings` 读取连接配置。

### 5.6 导入后校验清单（必执行）

导入完成后，必须执行以下校验（可使用 `scripts/_compare_excel_vs_db.py`）：

| # | 校验项 | 判定标准 | 失败影响 |
|---|--------|---------|----------|
| 1 | 资产数量对齐 | Excel 列数 = DB 中对应 asset_code 数 | 缺失资产无法回测 |
| 2 | 记录数对齐 | 每个资产 Excel 有效行数 = DB 条数 | 数据缺失导致回测偏差 |
| 3 | 数值一致性 | 抽样对比 close 值，容差 ≤ 1e-6 | NAV 计算结果不一致 |
| 4 | 汇率币种完整性 | 策略涉及的所有币种均有数据 | 外币资产折算错误 |
| 5 | 交易日历对齐 | Excel 天数 = DB 天数，无差异日期 | 调仓日对齐错误 |
| 6 | 日期范围对齐 | 起止日期一致 | 回测窗口缩短 |

---

## 六、后端导入脚本规范

> 适用于 `scripts/` 目录中的数据导入脚本、Agent 工具调用的导入逻辑。

### 6.1 脚本编写规范

| 规则 | 说明 |
|------|------|
| **引用映射** | `from app.schemas.field_mappings import PRICE_COLUMN_MAPPING` — 禁止硬编码 |
| **幂等写入** | 必须 upsert by 业务主键，脚本可重复执行 |
| **批量写入** | 使用 `BulkWrite`，每批 ≤ 1000 条，禁止逐条 `insert_one` |
| **日期归一化** | 入库前统一为 `YYYY-MM-DD` 字符串（trade_dates 例外） |
| **审计日志** | 脚本完成后写入 `_import_audit_log`，`operator` 填 `"script:{脚本名}"` |
| **错误收集** | 不因单行错误中止全批；收集所有错误后统一报告 |
| **统计输出** | 脚本结束时打印：total / inserted / updated / skipped / errors |

### 6.2 Agent 触发的导入

Agent 通过工具调用触发的导入（如 `subject_risk_search`）：
- `operator` 记为 `"agent"`
- 不经过前端预览流程
- **必须写入审计日志**
- 错误由 Agent 在对话中汇报，不抛 HTTP 500

### 6.3 特殊场景

**多资产宽表**：解析端点（parse）只执行步骤 ②~⑥，不写库；写入端点接收解析结果的完整数据。资产不存在时可自动创建（需前端确认）。**宽表禁止走单资产行情导入入口**：该入口仅接受长表；`upgrade_20260819_v4` 起后端在报「缺少行情数值列」前探测宽表布局（日期/Date 拐角+行0名称+行1代码、基金/证券两行表头），命中则 400 消息追加改道引导。

**汇率增量**：不覆盖已有数值，只填补空缺。`skipped_reasons` 中记录 `existing_value_preserved` 计数。

---

## 七、改造计划

### 7.1 问题清单

| # | 问题 | 严重度 | 改造方案 |
|---|------|:------:|---------|
| 1 | 列名映射 3 处重复 | **P0** | 抽取到 `field_mappings.py`，各处改为引用 |
| 2 | 响应格式 4 种不统一 | P1 | 统一为 `ImportResponse` |
| 3 | 无导入审计日志 | P1 | 新增 `_import_audit_log` 集合 + 写入逻辑。**现状**：集合与 `ImportAuditService` 已建成，但写入侧仅 `trade_calendar_service.py` 一处接入，其余导入端点仍未写审计（遗留项） |
| 4 | 汇率/交易日历/波动率无模板下载 | P2 | 新增模板生成端点 |
| 5 | 前端导入 UI 不统一 | P2 | 抽取 `ImportPanel` 通用组件 |
| 6 | 无 dry-run/预览 | P2 | 新增 `/import/preview` 端点 |

### 7.2 分阶段执行

```
Phase 1（基础设施）— 不影响现有功能
  ├── 创建 field_mappings.py，替换各处硬编码映射
  ├── 创建 import_protocol.py（ImportResponse / ImportError Schema）
  └── 新增 _import_audit_log 集合 + 写入逻辑

Phase 2（后端改造）— 逐端点改造，保持向后兼容
  ├── 各 endpoint 返回 ImportResponse（新增字段，不删旧字段）
  ├── 新增模板下载端点（fx / trade_dates / vol_surface）
  └── 新增 dry-run 端点（parse + validate 不写库）

Phase 3（前端统一）— 前端重构
  ├── 抽取 ImportPanel 通用组件
  └── 各导入页面替换为 ImportPanel
```
