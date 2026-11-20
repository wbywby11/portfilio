# 三策略系统化数据清单（Phase 0.1）

> **已归档（2026-10-31）**：本文档已并入 `DATA_SYSTEM.md` 第五节，后续三策略数据变更只更新该文档。本文保留作交付记录，不再修改。

适用范围：红利GARP专户、FOF 融合、指数增强（ERP + 三信号 + ETF 实现）落库前的数据准备。
依据：`standalone-strategy-onboard` Phase 0；集合与导入通道以 `docs/DATA_IMPORT_SPEC.md` 为准。

---

## 一、融合原则

不新建集合。现有两类容器已覆盖全部需求：

1. `asset_prices` 字段含 `open / high / low / close / volume / amount / scale`，
   导入映射已支持「成交额」「成交量」「规模」中文列（`app/schemas/field_mappings.py`
   的 `PRICE_COLUMN_MAPPING`）。成交额类数据不进新集合，走这一列。
2. `factor_panel` 是多数据集共用容器，业务主键 `(dataset, as_of_date, code)`，
   导入端点 `POST /factor-panel/import`，前端 `FactorPanelImport.vue`，
   按 dataset 出模板。新增数据产品 = 在 `FACTOR_DATASETS` 加一行，
   不动 `collections.py`、不动 `_collection_registry`。

新增动作只有两类：

- `assets` 新增资产记录（带 `instrument_type` / `asset_class` / `security_type`）
- `factor_panel` 新增 dataset 登记（3 处：数据集清单、列名映射、类别因子键）

三个策略共用同一批指数，按资产建一次、多策略引用。重叠关系见第二节。

---

## 二、共用资产池

现状列基于本机 `asset_allocation` 库实测：下列代码全部 0 命中，`asset_prices.amount` 全库 0 条非空。

### 2.1 宽基 / 风格 / 红利

| asset_code | 名称 | asset_class | instrument_type | 行情字段 | 使用方 | 现状 |
|---|---|---|---|---|---|---|
| 000985.CSI | 中证全指 | 权益 | 指数型 | close, amount, open, high, low | FOF（形态判定）、指增（sig1、ERP、基准） | 0 命中 |
| H00852.SH | 中证1000全收益 | 权益 | 指数型 | close | FOF | 0 命中 |
| H00918.CSI | 沪深300成长全收益 | 权益 | 指数型 | close | FOF（DAR 仓位账户） | 0 命中 |
| H00919.CSI | 沪深300价值全收益 | 权益 | 指数型 | close | FOF | 0 命中 |
| H00922.CSI | 中证红利全收益 | 权益 | 指数型 | close | FOF、GARP（基准） | 0 命中 |
| 931231CNY01.CSI | 央企红利50全收益 | 权益 | 指数型 | close | GARP | 0 命中 |
| 931579CNY01.CSI | 东证优势成长全收益 | 权益 | 指数型 | close | GARP | 0 命中 |
| 512890.SH | 华泰柏瑞红利低波ETF | 权益 | 现货型 | close（复权净值） | GARP | 0 命中 |
| 885009.WI | 现金代理 | 货币 | 指数型 | close | FOF | 0 命中 |
| AU9999.SGE | 黄金 | 商品 | 现货型 | close | FOF | 0 命中 |

### 2.2 债券

| asset_code | 名称 | asset_class | instrument_type | 行情字段 | 使用方 | 现状 |
|---|---|---|---|---|---|---|
| CBA00621.CS | 国债1—3年 | 固收 | 指数型 | close | FOF | 0 命中 |
| CBA00651.CS | 国债7—10年 | 固收 | 指数型 | close | FOF | 0 命中 |
| CBA01921.CS | 高等级信用债1—3年 | 固收 | 指数型 | close | FOF | 0 命中 |
| CBA01931.CS | 高等级信用债3—5年 | 固收 | 指数型 | close | FOF | 0 命中 |
| CBA00121.CB | 中债-新综合财富(1-3年) | 固收 | 指数型 | close | 指增（债端） | 0 命中 |
| 992618（后缀待确认） | 短期纯债基金指数 | 固收 | 指数型 | close | GARP | 0 命中 |

### 2.3 申万一级行业（30 条）

| 项 | 内容 |
|---|---|
| 代码范围 | `801010.SI` 农林牧渔 … `801980.SI` 美容护理，31 个 |
| 使用方 | FOF：30 个（剔除 801230 综合）收盘价，用于 DAR 与三形态行业排序；指增：31 个成交额，用于 sig2 |
| 行情字段 | close（FOF）+ amount（指增），同一批资产一次导入 |
| 现状 | `801xxx` 在 `assets` 中 0 个 |
| 额外要求 | 行业代码与名称的对照表走 `assets.name`，不另建集合 |

### 2.4 风格指数（指增选基用）

| asset_code | 用途 | 现状 |
|---|---|---|
| 399372.SZ / 399373.SZ / 399374.SZ / 399375.SZ / 399376.SZ / 399377.SZ | 巨潮六宫格风格指数，基金风格暴露打分 | 0 命中 |

---

## 三、红利GARP专户

### 3.1 数据清单

| 数据项 | 内容 | 时效级别 | 目标集合 | 更新通道 | 最小历史 | 复用/新增 |
|---|---|---|---|---|---|---|
| 资产主数据 | 5 条资产 | S 静态 | `assets` | 资产管理 → 导入 | — | 复用 |
| 资产行情 | 512890、931231CNY01、931579CNY01、992618、H00922 的日收盘 | D 日频 | `asset_prices` | 资产行情 → 导入 | 2020-01 起（PE 需前推 3 年） | 复用 |
| PE-TTM 序列 | 中证红利 H00922 的日频市盈率 TTM | D 日频 | `factor_panel`（dataset `index_valuation`） | 因子截面 → 导入 | 与行情同长 | **新增 dataset** |
| 交易日历 | 逐日推演轴 | D 日频 | `trade_dates` | 数据导入 → 交易日历 | 覆盖回测区间 | 复用 |
| 工具费 0.6%/年 | 指数→产品化的持有成本 | — | 策略参数（非数据） | 前端策略表单 | — | 参数 |

### 3.2 关键口径

- PE 必须**日频**，不能用月末。信号用「近 3 年窗口内全部交易日的 PE」算分位，
  月末只有 36 个点，分位会偏离，影响 80% 进入 / 70% 退出的滞回边界，
  对账过不了 0.1pp。
- 512890 是 ETF 复权净值，931231/931579 是全收益指数，两者口径不同，
  按原型分别导入，不能互相替代。
- 中证指数官网导出的日期整体早 1 天，导入前校正，不留给策略处理。

### 3.3 factor_panel 登记

```
FACTOR_DATASETS["index_valuation"] = "指数估值日频截面：PE-TTM、股息率、国债收益率、ERP"
FACTOR_NAME_MAPPING_BY_DATASET["index_valuation"] = {
    "市盈率TTM": "pe_ttm", "股息率TTM": "dividend_yield_ttm",
    "十年国债收益率": "ytm_10y", "ERP2": "erp2",
}
FACTOR_CATEGORICAL_KEYS_BY_DATASET["index_valuation"] = frozenset()
```

入库形态：`code=H00922.CSI`，`as_of_date=每个交易日`，`industry="红利指数"`，
`factors={"pe_ttm": 7.85}`。约 3300 行。

---

## 四、FOF 融合

### 4.1 数据清单

| 数据项 | 内容 | 时效级别 | 目标集合 | 更新通道 | 最小历史 | 复用/新增 |
|---|---|---|---|---|---|---|
| 资产主数据 | 10 条资产 | S 静态 | `assets` | 资产管理 → 导入 | — | 复用 |
| 资产行情 | 10 条日收盘 | D 日频 | `asset_prices` | 资产行情 → 导入 | 756 日（协方差窗口）+ 10 日 | 复用 |
| 市场行情 | 000985 的 open/high/low/close/amount | D 日频 | `asset_prices` | 资产行情 → 导入 | 252 日（形态窗口） | 复用 |
| 行业行情 | 30 个申万一级行业日收盘 | D 日频 | `asset_prices` | 多资产宽表导入 | 250 日（DAR 窗口） | 复用（与指增共用） |
| 国债收益率 | 与指增 ERP 同源，仅用于对照 | L 低频 | 不单独入库 | — | — | 复用指增数据 |
| 交易日历 | 逐日推演轴 | D 日频 | `trade_dates` | 数据导入 → 交易日历 | 覆盖回测区间 | 复用 |

### 4.2 关键口径

- **市场行情必须带 high / low**。三形态里的 ATR 用「最高−最低、最高−前收、最低−前收」
  三者最大值，只有 close 算不出来。当前 `asset_prices` 的 high/low 全库为空，
  导入 000985 时必须带这三列。
- 10 个资产全部用**全收益指数**（H00852/H00918/H00922/H00919、CBA 系列、885009），
  不能用同名 ETF 替代，否则分红口径缺失，红利类年化差 2~3 个点。
- 现金代理 885009 作为资产入库（`asset_class=货币`），策略内部按现金处理，
  不参与组约束校验。
- 债券指数是净价还是全价需要按原型确认：原型直接 `pct_change` 求收益，
  默认价格序列已含票息（财富指数）。导入时核对首尾净值与原型一致。

---

## 五、指数增强

### 5.1 数据清单

| 数据项 | 内容 | 时效级别 | 目标集合 | 更新通道 | 最小历史 | 复用/新增 |
|---|---|---|---|---|---|---|
| 000985 行情 | close + amount | D 日频 | `asset_prices` | 资产行情 → 导入 | 920 日（ERP 分位窗口） | 复用 |
| 行业成交额 | 31 个申万一级行业 amount | D 日频 | `asset_prices` | 多资产宽表导入 | 30 日（sig2 窗口） | 复用（与 FOF 共用） |
| 指数估值 | 000985 股息率、10Y 国债收益率、ERP2 | D 日频 | `factor_panel`（`index_valuation`） | 因子截面 → 导入 | 920 日 | **新增 dataset** |
| 个股 PB 截面 | 中证全指成分内个股 PB，月末一期 | L 低频 | `factor_panel`（`index_enhance_stock`） | 因子截面 → 导入 | 165 个月末 | **新增 dataset** |
| 个股 20 日收益 | 个股日频收益，sig3 分组用 | D 日频 | `factor_panel`（`index_enhance_stock`） | 待定（见 5.3） | 同 PB | **新增 dataset** |
| 中证全指月度成分 | 每月成分股名单 | L 低频 | `factor_panel`（同 dataset，`industry="成分"`） | 因子截面 → 导入 | 165 期 | **新增 dataset** |
| 指增 ETF / 场外基金 | 约 100 只复权净值 | D 日频 | `asset_prices` | 多资产宽表导入 | 12 个月（训练窗口）+60 日 | 复用 |
| 赛道指数 | 各基金对标指数收盘 | D 日频 | `asset_prices` | 多资产宽表导入 | 与基金同长 | 复用 |
| 风格指数 | 399372—399377 收盘 | D 日频 | `asset_prices` | 多资产宽表导入 | 12 个月 | 复用 |
| CBA00121 | 债端指数收盘 | D 日频 | `asset_prices` | 资产行情 → 导入 | 与股端同长 | 复用 |
| 基金赛道映射 | 基金 → 赛道 → 基准指数 | S 静态 | 策略参数（text） | 前端策略表单 | — | 参数 |

### 5.2 关键口径

- ERP2 为派生列：`ERP2 = 股息率 − 10Y 国债收益率`，在导入前算好，
  与两个原始列一并入库，策略只读不算，便于对账。
- sig1 用 000985 的成交额，sig2 用 31 行业成交额，全部走 `asset_prices.amount`，
  不新建集合。
- 基金池、赛道映射不写死在策略类，进参数 Schema；
  映射表按原型《数据映射表.xlsx》整理成参数默认值。

### 5.3 sig3 的三种落法（需决策）

| 方案 | 入库内容 | 行数 | 优点 | 缺点 |
|---|---|---|---|---|
| A 全量明细 | 月末 PB + 每日个股 20 日收益 + 月度成分 | 约 1650 万 | 策略算法完整可见，可换分组参数 | 存储 1~2 GB；前端 Excel 导入不可行 |
| B 月末 PB + 日频组合收益差 | 月末 PB 截面 + 每日「高/低 PB 组收益中位数差」 | 约 83 万（82.5 万 PB + 3300 收益差） | 数据量降一个量级 | sig3 的分组逻辑被移到数据层，策略只读信号，换参数要重导 |
| C 只存派生信号 | 每日 sig3 ∈ {-1,+1} | 约 3300 | 最轻 | 策略内看不到 PB 分组，无法调参、无法归因 |

建议 B：保留月末 PB 截面（分组可调），日频只存两只组合的收益差（3300 行），
合计约 83 万行，MongoDB 可承受，同时保住分组参数可调。

### 5.4 factor_panel 登记

```
FACTOR_DATASETS["index_valuation"] = "指数估值日频截面：PE-TTM、股息率、国债收益率、ERP"
FACTOR_DATASETS["index_enhance_stock"] = "指增 sig3 用个股截面：PB、20日收益、成分标记"
FACTOR_NAME_MAPPING_BY_DATASET["index_enhance_stock"] = {
    "市净率": "pb", "20日收益": "ret_20d", "是否成分": "in_index",
}
FACTOR_CATEGORICAL_KEYS_BY_DATASET["index_enhance_stock"] = frozenset()
```

入库形态：`code=600000.SH`，`as_of_date=月末`，`industry=申万一级行业名`，
`factors={"pb": 0.85, "in_index": 1}`。

---

## 六、新增登记汇总（最小集）

| 动作 | 文件 | 内容 |
|---|---|---|
| dataset 登记 ×2 | `app/schemas/field_mappings.py` | `FACTOR_DATASETS` 加 `index_valuation`、`index_enhance_stock` |
| 列名映射 ×2 | 同上 | `FACTOR_NAME_MAPPING_BY_DATASET` 加两组中文→英文键 |
| 类别键 ×2 | 同上 | `FACTOR_CATEGORICAL_KEYS_BY_DATASET` 各加一行空集合 |
| 资产记录 | `assets`（前端导入） | 共用 20 条 + GARP 2 条 + 指增池约 120 条 |
| 集合常量 | 不改 | `asset_prices`、`factor_panel` 均已存在 |
| 集合注册 | 不改 | 无新集合 |
| 前端 | 不改 | `FactorPanelImport.vue` 按 dataset 拉清单，自动出现新数据集 |

---

## 七、缺口与决策点

| # | 事项 | 现状 | 处理 |
|---|---|---|---|
| 1 | GARP 的 PE 频率 | 原型日频，方案未定 | 定日频；3300 行，成本可忽略 |
| 2 | sig3 落法 | 三选一 | 建议方案 B（5.3） |
| 3 | 000985 的 high/low | 系统全库为空，FOF 的 ATR 必需 | 导入时带这 3 列，不能只导 close |
| 4 | 成交额 | 全库 0 条非空 | 导入时带上「成交额」列，映射已支持 |
| 5 | 指增基金池名单 | 在原型《数据映射表.xlsx》 | 转成参数默认值，进 ParamSchema |
| 6 | 992618 的交易所后缀 | 原型只给数字代码 | 查中证指数官网确认后缀，再建资产 |
| 7 | 现金代理 885009 | 0 命中 | 建为资产，`asset_class=货币`；策略内按现金处理 |
| 8 | 全收益 vs ETF | 多个同名标的 | 按原型代码逐条导入，不做替代 |

---

## 八、导入顺序

```
1. assets 主数据（共用 20 条 + GARP 2 条 + 指增池）
2. asset_prices（先 20 条共用指数，verify 首尾与原型一致；再指增池）
3. factor_panel：index_valuation（H00922 的 PE、000985 的股息率/国债/ERP2）
4. factor_panel：index_enhance_stock（月末 PB + 成分 + 每日组合收益差）
5. trade_dates（覆盖 2013-01 至今）
6. 数据验收：抽样 ≥20 个日期 × 全部资产，与原型数据逐日比对
```

前三步完成即可对 GARP 与 FOF 的择时层对账；第 4 步只影响指数增强的 sig3。
