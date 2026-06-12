# ZY 主题数据域 — MongoDB 表结构与测试数据

> 依据《ZY主题数据域_20250324.xlsx》设计，对应 9 大数据域、80+ 张数据表。
> 产物形式：MongoDB（Collection + $jsonSchema validator + insertMany 测试数据）。
> 每张表生成 5~10 条样例数据，跨表外键（AST_CD / PORT_ID / CUSTOMER_ID / ISR_ID）已保持一致。

---

## 一、目录结构

```
mongo-seed/
├── README.md                       # 本文件（含数据字典索引）
├── 00_init.js                      # 一键入口：依序执行所有域脚本
├── _keys.js                        # 跨表主键池（AST_CD/PORT_ID/...）统一定义
├── 01_asset_domain.js              # 资产域      dwd_ast_*           12 表
├── 02_subject_domain.js            # 主体域      dwd_isr_*            3 表
├── 03_product_domain.js            # 产品域      dwd_ptl_* + cash    12 表
├── 04_valuation_domain.js          # 估值域      dwd_val_*           10 表
├── 05_transaction_domain.js        # 交易域      dwd_trn_*            6 表
├── 06_seller_domain.js             # 销售域      dwd_seller_info      1 表
├── 07_customer_domain.js           # 客户域      dwd_cust_*           8 表
├── 08_risk_domain.js               # 风险域      dwd_rsk_* + crdt    5 表
└── 09_market_domain.js             # 行情域      dwd_mkt_*           25 表
```

## 二、执行方式

### 1) mongosh（推荐）

```bash
# 进入目标库（默认 zy_data）
mongosh "mongodb://localhost:27017/zy_data" 00_init.js
```

或在 mongosh 内手动：

```js
use zy_data
load('mongo-seed/_keys.js')
load('mongo-seed/01_asset_domain.js')
load('mongo-seed/02_subject_domain.js')
// ... 依次 load
```

### 2) 单域单独导入

```bash
mongosh "mongodb://localhost:27017/zy_data" mongo-seed/01_asset_domain.js
```

## 三、主键 / 外键约定

| Key 字段 | 含义 | 示例 | 出现的表（主） |
| --- | --- | --- | --- |
| `AST_CD`      | 资产代码（证券代码） | `019601.IB`、`600519.SH` | dwd_ast_info |
| `PORT_ID`     | 组合 / 产品代码      | `PORT001`              | dwd_ptl_info |
| `ISR_ID`      | 发行人 / 机构 ID      | `ISR000001`            | dwd_isr_institution |
| `CNTP_ID`     | 交易对手 ID           | `CNTP00001`            | dwd_isr_trd_cntp |
| `CUSTOMER_ID` | 客户号               | `CUS0000001`           | dwd_cust_info |
| `SELLER_ID`   | 销售人员代码         | `SEL00001`             | dwd_seller_info |
| `INDEX_CD`    | 指数代码             | `000300.SH`            | dwd_mkt_index |
| `BIZ_DT`      | 业务日期             | `20250324`             | 所有快照型表  |

数据日期统一锚定 **2025-03-24（BIZ_DT=20250324）** 作为快照日，过去若干日做历史回溯。

## 四、数据域 → 表清单

### 1. 资产域（dwd_ast_*）— 12 表
`dwd_ast_info` 资产基础 / `dwd_ast_info_ch` 估值附加 / `dwd_ast_info_zg` 中债估值 /
`dwd_ast_yield_info` 收益率 / `dwd_ast_cf_plan` 现金流计划 / `dwd_ast_pledge` 质押 /
`dwd_ast_party` 关联方 / `dwd_ast_exe_plan` 行权计划 / `dwd_ast_fund_manager` 基金经理 /
`dwd_ast_bottom_raito` 底层穿透比例 / `dwd_ast_fiveclass` 五级分类 / `dwd_ast_calc_rule` 计算规则

### 2. 主体域（dwd_isr_*）— 3 表
`dwd_isr_institution` 机构 / `dwd_isr_institution_finance` 机构财务 / `dwd_isr_trd_cntp` 交易对手

### 3. 产品域（dwd_ptl_* / tag_ptl_* / dwd_cash_acc）— 12 表
`dwd_ptl_info` / `tag_ptl_info` / `dwd_ptl_acc` / `dwd_ptl_cedetail` / `dwd_ptl_fee` /
`dwd_ptl_managers` / `dwd_ptl_open_plan` / `dwd_ptl_asset_config_info` / `dwd_ptl_acct_bal` /
`dwd_ptl_ast_hld` / `dwd_ptl_holder_summary` / `dwd_cash_acc`

### 4. 估值域（dwd_val_*）— 10 表
`dwd_val_valtable` / `dwd_val_voucher` / `dwd_val_summary` / `dwd_val_detail` /
`dwd_val_notice` / `dwd_val_bal` / `dwd_val_acc` / `dwd_val_rpt_bs` /
`dwd_val_rpt_is` / `dwd_val_rpt_cf`

### 5. 交易域（dwd_trn_*）— 6 表
`dwd_trn_trade_ast` / `dwd_trn_trade_ptl` / `dwd_trn_trade_val` /
`dwd_trn_trade_zg` / `dwd_trn_trade_jy` / `dwd_trn_order`

### 6. 销售域 — 1 表
`dwd_seller_info`

### 7. 客户域（dwd_cust_*）— 8 表
`dwd_cust_info` / `dwd_cust_make_pstn_info` / `dwd_cust_trans_acct_info` /
`dwd_cust_trans_apply_info_s5` / `dwd_cust_trans_apply_info_ta` / `dwd_cust_trans_apply_info_yh` /
`dwd_cust_trans_cfm_info` / `dwd_cust_trans_divd_info` / `dwd_cust_trans_srl_info`

### 8. 风险域（dwd_rsk_* / dwd_crdt_*）— 5 表
`dwd_rsk_sentiment` / `dwd_rsk_credit` / `dwd_rsk_credit_position` /
`dwd_crdt_agme_info` / `dwd_crdt_main_rela_rela_info`

### 9. 行情域（dwd_mkt_*）— 25 表
债券：`dwd_mkt_bond` / `_amount` / `_creditrating` / `_duration` / `_ecl` / `_market`
日历：`dwd_mkt_calendar` / `dwd_mkt_date`
曲线：`dwd_mkt_curve` / `dwd_mkt_curve_quote`
汇率：`dwd_mkt_exrate`
基金：`dwd_mkt_fund` / `_allocation` / `_derive` / `_market` / `_structure` / `_suspension`
指数：`dwd_mkt_index` / `_member` / `_quote`
利率：`dwd_mkt_rate` / `_quote`
评级 / 股票：`dwd_mkt_rating` / `dwd_mkt_stock` / `dwd_mkt_stock_yield`

## 五、Schema 设计原则

1. 所有表统一加入审计字段：`etl_dt`（ETL 日期）、`src_sys`（来源系统）。
2. 业务日期类字段统一以 **字符串 yyyyMMdd** 存储（贴源风格），不强制 ISODate 以方便回放。
3. 金额 / 比率类字段使用 `double`（Mongo 内部为 64-bit float），生产环境如需更高精度可改 `decimal128`。
4. 每个 collection 通过 `db.createCollection(..., { validator: { $jsonSchema: {...} } })` 加宽松校验，仅约束**主键 + 必填业务字段**，其他字段允许扩展，避免误拒贴源数据。
5. 索引：主键字段（`_id` 之外）显式建唯一索引；高频过滤字段（BIZ_DT、PORT_ID、AST_CD）建普通索引。

## 六、清空 / 重建

`00_init.js` 默认对每个 collection 先 `db.collection.drop()` 再重建，可安全反复执行。
