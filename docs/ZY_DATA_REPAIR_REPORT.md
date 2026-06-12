# ZY 数据域字段对齐与填充修复报告

- 修复时间: 2026-06-01
- 数据库: `mongodb://localhost:27017/portfilio`
- 修复范围: MongoDB 现有集合（执行 $rename + 缺失字段 $set 填充）

## 一、修复总览

| 指标 | 数值 |
|------|------|
| 处理表数 | 29 |
| 字段重命名（对齐前端 schema）总条数 | 68 |
| 重命名影响的文档数 | 4,435 |
| 缺失字段填充影响的文档数 | 4,365 |

## 二、各表修复明细

| 表名 | 中文名 | 期望字段 | 重命名映射 | 填充字段 | 修复后剩余缺失 |
|------|--------|---------|-----------|---------|-------------|
| `dwd_ast_bottom_raito` | 资产穿透底层 | 4 | 0 | 2 | 2 |
| `dwd_ast_calc_rule` | 资产计算规则 | 5 | 1 | 4 | 4 |
| `dwd_ast_cf_plan` | 资产现金流计划 | 5 | 1 | 1 | 1 |
| `dwd_ast_exe_plan` | 资产行权计划 | 5 | 2 | 1 | 1 |
| `dwd_ast_fiveclass` | 资产五级分类 | 6 | 2 | 2 | 2 |
| `dwd_ast_fund_manager` | 资产基金经理 | 6 | 2 | 4 | 4 |
| `dwd_ast_info` | 资产基础信息 | 13 | 4 | 6 | 6 |
| `dwd_ast_info_ch` | 中债估值信息 | 9 | 1 | 7 | 7 |
| `dwd_ast_info_zg` | 中证估值信息 | 9 | 1 | 7 | 7 |
| `dwd_ast_party` | 资产关联方 | 5 | 2 | 0 | 0 |
| `dwd_ast_pledge` | 资产质押状态 | 7 | 2 | 4 | 4 |
| `dwd_ast_yield_info` | 资产收益率 | 9 | 1 | 7 | 7 |
| `dwd_cust_info` | 客户基础 | 15 | 5 | 5 | 5 |
| `dwd_cust_make_pstn_info` | 客户持仓 | 10 | 2 | 8 | 8 |
| `dwd_isr_institution` | 发行人主体 | 11 | 3 | 8 | 8 |
| `dwd_isr_institution_finance` | 主体财务报表 | 11 | 2 | 6 | 6 |
| `dwd_isr_trd_cntp` | 交易对手方 | 10 | 1 | 8 | 8 |
| `dwd_mkt_bond` | 债券行情 | 10 | 7 | 2 | 2 |
| `dwd_mkt_fund` | 基金主数据 | 9 | 1 | 7 | 7 |
| `dwd_mkt_index` | 指数主数据 | 7 | 3 | 2 | 2 |
| `dwd_mkt_stock` | 股票主数据 | 10 | 4 | 5 | 5 |
| `dwd_ptl_fee` | 产品费率 | 6 | 1 | 3 | 3 |
| `dwd_ptl_info` | 产品基础信息 | 13 | 5 | 6 | 6 |
| `dwd_trn_trade_ast` | 资产维度交易 | 13 | 5 | 6 | 6 |
| `dwd_trn_trade_ptl` | 组合维度交易 | 11 | 4 | 6 | 6 |
| `dwd_val_bal` | 估值科目余额 | 8 | 2 | 6 | 6 |
| `dwd_val_detail` | 估值明细 | 13 | 2 | 10 | 10 |
| `dwd_val_summary` | 估值汇总 | 6 | 2 | 4 | 4 |
| `tag_ptl_info` | 产品标签 | 3 | 0 | 0 | 0 |

## 三、字段重命名详细映射

### `dwd_ast_calc_rule` - 资产计算规则

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `CALC_RULE` | → | `FORMULA` |

### `dwd_ast_cf_plan` - 资产现金流计划

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `CF_DATE` | → | `CF_DT` |

### `dwd_ast_exe_plan` - 资产行权计划

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `EXE_DATE` | → | `EXE_DT` |
| `EXE_PRICE` | → | `EXE_PRC` |

### `dwd_ast_fiveclass` - 资产五级分类

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |
| `FIVE_CLASS` | → | `CLASS_LVL` |

### `dwd_ast_fund_manager` - 资产基金经理

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `FM_ID` | → | `MANAGER_ID` |
| `FM_NAME` | → | `MANAGER_NM` |

### `dwd_ast_info` - 资产基础信息

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `AST_NAME` | → | `AST_NM` |
| `CUSTOMER_ID` | → | `ISR_ID` |
| `LIST_DATE` | → | `LIST_DT` |
| `MDATE` | → | `MATURITY_DT` |

### `dwd_ast_info_ch` - 中债估值信息

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |

### `dwd_ast_info_zg` - 中证估值信息

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |

### `dwd_ast_party` - 资产关联方

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |
| `PARTY_NAME` | → | `PARTY_NM` |

### `dwd_ast_pledge` - 资产质押状态

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |
| `PLEDGE_RATE` | → | `PLEDGE_RATIO` |

### `dwd_ast_yield_info` - 资产收益率

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |

### `dwd_cust_info` - 客户基础

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `CUST_ID` | → | `CUSTOMER_ID` |
| `CUST_NAME` | → | `CUST_NM` |
| `DATA_DT` | → | `BIZ_DT` |
| `OPEN_DATE` | → | `OPEN_DT` |
| `RISK_LEVEL` | → | `RISK_LVL` |

### `dwd_cust_make_pstn_info` - 客户持仓

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `CUST_ID` | → | `CUSTOMER_ID` |
| `DATA_DT` | → | `BIZ_DT` |

### `dwd_isr_institution` - 发行人主体

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `CUSTOMER_ID` | → | `ISR_ID` |
| `DATA_DT` | → | `BIZ_DT` |
| `INDUSTRY_GB` | → | `INDUSTRY_CD` |

### `dwd_isr_institution_finance` - 主体财务报表

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `CUSTOMER_ID` | → | `ISR_ID` |
| `REPORT_DATE` | → | `RPT_DT` |

### `dwd_isr_trd_cntp` - 交易对手方

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |

### `dwd_mkt_bond` - 债券行情

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `AMOUNT` | → | `AMT` |
| `CLOSE_PRICE` | → | `CLOSE_PRC` |
| `DATA_DT` | → | `BIZ_DT` |
| `HIGH_PRICE` | → | `HIGH_PRC` |
| `LOW_PRICE` | → | `LOW_PRC` |
| `OPEN_PRICE` | → | `OPEN_PRC` |
| `VOLUME` | → | `VOL` |

### `dwd_mkt_fund` - 基金主数据

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |

### `dwd_mkt_index` - 指数主数据

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `BASE_DATE` | → | `BASE_DT` |
| `DATA_DT` | → | `BIZ_DT` |
| `INDEX_NAME` | → | `INDEX_NM` |

### `dwd_mkt_stock` - 股票主数据

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `AST_NAME` | → | `STOCK_NM` |
| `DATA_DT` | → | `BIZ_DT` |
| `MARKET_CAP` | → | `TOT_CAP` |
| `MKT_CD` | → | `EXCH` |

### `dwd_ptl_fee` - 产品费率

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `PROD_CD` | → | `PORT_ID` |

### `dwd_ptl_info` - 产品基础信息

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `CURR` | → | `CCY` |
| `INT_BENCHMARK` | → | `BENCHMARK` |
| `PROD_ABBR` | → | `PORT_NM` |
| `PROD_CD` | → | `PORT_ID` |
| `START_DATE` | → | `ESTAB_DT` |

### `dwd_trn_trade_ast` - 资产维度交易

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `LONG_CURRENCY` | → | `CCY` |
| `LONG_QUANTITY` | → | `QTY` |
| `SETTLE_DATE` | → | `SETT_DT` |
| `TRAN_DATE` | → | `TRADE_DT` |
| `TRAN_SIDE` | → | `BS_DIR` |

### `dwd_trn_trade_ptl` - 组合维度交易

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `PROD_CD` | → | `PORT_ID` |
| `TRADE_AMT` | → | `AMT` |
| `TRADE_DATE` | → | `TRADE_DT` |
| `TRADE_QTY` | → | `QTY` |

### `dwd_val_bal` - 估值科目余额

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |
| `PROD_CD` | → | `PORT_ID` |

### `dwd_val_detail` - 估值明细

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |
| `PROD_CD` | → | `PORT_ID` |

### `dwd_val_summary` - 估值汇总

| 原字段（实际）| → | 新字段（前端期望）|
|------|------|------|
| `DATA_DT` | → | `BIZ_DT` |
| `PROD_CD` | → | `PORT_ID` |

## 四、字段填充详细

### `dwd_ast_bottom_raito` - 资产穿透底层

| 字段 | 默认值（示例） |
|------|---------------|
| `BTM_AST_CD` | `''` |
| `BTM_NM` | `'底层资产'` |

### `dwd_ast_calc_rule` - 资产计算规则

| 字段 | 默认值（示例） |
|------|---------------|
| `AST_TYPE` | `'BOND'` |
| `EFF_DT` | `'2025-03-24'` |
| `RULE_CD` | `''` |
| `RULE_NM` | `'计算规则'` |

### `dwd_ast_cf_plan` - 资产现金流计划

| 字段 | 默认值（示例） |
|------|---------------|
| `CCY` | `'CNY'` |

### `dwd_ast_exe_plan` - 资产行权计划

| 字段 | 默认值（示例） |
|------|---------------|
| `NOTE` | `''` |

### `dwd_ast_fiveclass` - 资产五级分类

| 字段 | 默认值（示例） |
|------|---------------|
| `ADJ_FLAG` | `'N'` |
| `LAST_LVL` | `'NORMAL'` |

### `dwd_ast_fund_manager` - 资产基金经理

| 字段 | 默认值（示例） |
|------|---------------|
| `AST_CD` | `'019601.IB'` |
| `END_DT` | `'2030-12-31'` |
| `SHR_FLAG` | `'N'` |
| `START_DT` | `'2025-03-24'` |

### `dwd_ast_info` - 资产基础信息

| 字段 | 默认值（示例） |
|------|---------------|
| `AST_SUB_TYPE` | `'CGB'` |
| `BIZ_DT` | `'2025-03-24'` |
| `BOND_TERM` | `'10Y'` |
| `CCY` | `'CNY'` |
| `COUPON_RATE` | `0.0356` |
| `MARKET` | `'IB'` |

### `dwd_ast_info_ch` - 中债估值信息

| 字段 | 默认值（示例） |
|------|---------------|
| `CONVEXITY` | `52.41` |
| `DURATION` | `0.011` |
| `RATING_AGENCY` | `''` |
| `VAL_FULL_PRC` | `105.1505` |
| `VAL_NET_PRC` | `106.0471` |
| `VAL_SRC` | `''` |
| `VAL_YIELD` | `0.021` |

### `dwd_ast_info_zg` - 中证估值信息

| 字段 | 默认值（示例） |
|------|---------------|
| `CONVEXITY` | `90.17` |
| `DURATION` | `0.0457` |
| `RATING_AGENCY` | `''` |
| `VAL_FULL_PRC` | `98.2796` |
| `VAL_NET_PRC` | `95.447` |
| `VAL_SRC` | `''` |
| `VAL_YIELD` | `0.0135` |

### `dwd_ast_pledge` - 资产质押状态

| 字段 | 默认值（示例） |
|------|---------------|
| `PLEDGE_BOND_CD` | `''` |
| `PLEDGE_FLAG` | `'N'` |
| `PLEDGE_NOTE` | `''` |
| `PLEDGE_STD_BOND` | `809.43` |

### `dwd_ast_yield_info` - 资产收益率

| 字段 | 默认值（示例） |
|------|---------------|
| `DAILY_RTN` | `0.0318` |
| `MONTH_RTN` | `0.018` |
| `SETTLE_PRC` | `95.398` |
| `WEEK_RTN` | `0.0188` |
| `YIELD_EX` | `0.0302` |
| `YIELD_TM` | `0.0336` |
| `YTD_RTN` | `0.036` |

### `dwd_cust_info` - 客户基础

| 字段 | 默认值（示例） |
|------|---------------|
| `ADDR` | `''` |
| `BIRTH_DT` | `'1985-06-15'` |
| `CHANNEL` | `'DIRECT'` |
| `GENDER` | `'M'` |
| `SELLER_ID` | `''` |

### `dwd_cust_make_pstn_info` - 客户持仓

| 字段 | 默认值（示例） |
|------|---------------|
| `AVAIL_SHR` | `392554` |
| `COST_AMT` | `278695629.51` |
| `FIRST_BUY_DT` | `'2025-03-24'` |
| `FROZEN_SHR` | `180555` |
| `HLD_AMT` | `636048759.82` |
| `HLD_SHR` | `408591` |
| `PORT_ID` | `'PORT001'` |
| `UNREAL_PNL` | `370.18` |

### `dwd_isr_institution` - 发行人主体

| 字段 | 默认值（示例） |
|------|---------------|
| `CREDIT_CD` | `''` |
| `EST_DT` | `'2025-03-24'` |
| `ISR_NM` | `''` |
| `ISR_SHORT_NM` | `''` |
| `ISR_TYPE` | `''` |
| `LIST_FLAG` | `''` |
| `REG_CAP_AMT` | `7492260.92` |
| `REG_PROV` | `''` |

### `dwd_isr_institution_finance` - 主体财务报表

| 字段 | 默认值（示例） |
|------|---------------|
| `EQUITY` | `340.25` |
| `NET_PRFT` | `957.21` |
| `ROA` | `155.48` |
| `RPT_TYPE` | `''` |
| `TOT_AST` | `805.82` |
| `TOT_LIA` | `698.14` |

### `dwd_isr_trd_cntp` - 交易对手方

| 字段 | 默认值（示例） |
|------|---------------|
| `CNTP_ID` | `''` |
| `CNTP_NM` | `''` |
| `LINKED_ISR_ID` | `''` |
| `MARKET` | `'IB'` |
| `RATING` | `''` |
| `SETT_ACCT` | `''` |
| `SETT_BANK` | `''` |
| `WHITELIST` | `''` |

### `dwd_mkt_bond` - 债券行情

| 字段 | 默认值（示例） |
|------|---------------|
| `CHG_BP` | `0.0184` |
| `YTM` | `266.98` |

### `dwd_mkt_fund` - 基金主数据

| 字段 | 默认值（示例） |
|------|---------------|
| `AUM` | `936.65` |
| `BENCHMARK` | `''` |
| `CUSTODY_BANK` | `''` |
| `ESTAB_DT` | `'2025-03-24'` |
| `FUND_NM` | `'基金名称'` |
| `FUND_TYPE` | `'OPEN'` |
| `MGR_INST` | `''` |

### `dwd_mkt_index` - 指数主数据

| 字段 | 默认值（示例） |
|------|---------------|
| `BASE_VAL` | `104.7205` |
| `PUBLISHER` | `''` |

### `dwd_mkt_stock` - 股票主数据

| 字段 | 默认值（示例） |
|------|---------------|
| `FREE_CAP` | `609521874.66` |
| `INDUSTRY_CD` | `''` |
| `INDUSTRY_NM` | `'行业'` |
| `ISR_ID` | `'ISR000001'` |
| `LIST_DT` | `'2025-03-24'` |

### `dwd_ptl_fee` - 产品费率

| 字段 | 默认值（示例） |
|------|---------------|
| `EFF_DT` | `'2025-03-24'` |
| `EXP_DT` | `'2030-12-31'` |
| `FEE_BASE` | `''` |

### `dwd_ptl_info` - 产品基础信息

| 字段 | 默认值（示例） |
|------|---------------|
| `AUM` | `336.59` |
| `CUSTODY_BANK` | `''` |
| `MGR_INST` | `''` |
| `PORT_SHORT_NM` | `'产品简称'` |
| `SHR_NAV` | `96.3912` |
| `STATUS` | `'ACTIVE'` |

### `dwd_trn_trade_ast` - 资产维度交易

| 字段 | 默认值（示例） |
|------|---------------|
| `AMT` | `773295272.45` |
| `CNTP_ID` | `''` |
| `MARKET` | `'IB'` |
| `PRC` | `109.7783` |
| `STATUS` | `'ACTIVE'` |
| `TRADER` | `''` |

### `dwd_trn_trade_ptl` - 组合维度交易

| 字段 | 默认值（示例） |
|------|---------------|
| `AST_CD` | `'019601.IB'` |
| `BS_DIR` | `'B'` |
| `CCY` | `'CNY'` |
| `FEE` | `4278.04` |
| `PRC` | `107.9973` |
| `SETT_DT` | `'2025-03-25'` |

### `dwd_val_bal` - 估值科目余额

| 字段 | 默认值（示例） |
|------|---------------|
| `ACC_CD` | `''` |
| `ACC_NM` | `''` |
| `BAL` | `661.26` |
| `CCY` | `'CNY'` |
| `CR_BAL` | `192.29` |
| `DR_BAL` | `69.56` |

### `dwd_val_detail` - 估值明细

| 字段 | 默认值（示例） |
|------|---------------|
| `ACI_AMT` | `885566296.19` |
| `AMORT_AMT` | `973142648.22` |
| `COST_AMT` | `552488590.64` |
| `COST_PRC` | `103.0434` |
| `DAILY_PNL` | `378.53` |
| `HLD_QTY` | `879693` |
| `MKT_PRC` | `107.1069` |
| `MKT_VAL` | `105.946` |
| `REAL_PNL` | `628.64` |
| `UNREAL_PNL` | `361.64` |

### `dwd_val_summary` - 估值汇总

| 字段 | 默认值（示例） |
|------|---------------|
| `ACI_AMT` | `847646871.98` |
| `AST_CLASS` | `'BOND'` |
| `MKT_VAL` | `104.0559` |
| `WEIGHT` | `0.0139` |

## 五、前端有 schema 但 MongoDB 中无数据的表

> 这些表无法通过本次修复得到数据，需要后续单独补齐 mock 数据。

- `dwd_cash_acc` - 现金账户
- `dwd_crdt_agme_info` - 授信协议
- `dwd_crdt_main_rela_rela_info` - 主体关联关系
- `dwd_cust_trans_acct_info` - 客户交易账户
- `dwd_cust_trans_apply_info_ta` - 申请单(TA)
- `dwd_cust_trans_apply_info_yh` - 申请单(银行)
- `dwd_cust_trans_cfm_info` - 确认信息
- `dwd_cust_trans_divd_info` - 客户分红
- `dwd_cust_trans_srl_info` - 客户流水
- `dwd_mkt_bond_amount` - 债券存量
- `dwd_mkt_bond_creditrating` - 债项评级
- `dwd_mkt_bond_duration` - 久期凸性
- `dwd_mkt_bond_ecl` - 预期信用损失
- `dwd_mkt_bond_market` - 债券逐日成交
- `dwd_mkt_calendar` - 日历
- `dwd_mkt_curve` - 收益率曲线主数据
- `dwd_mkt_curve_quote` - 曲线节点报价
- `dwd_mkt_date` - 日期维度
- `dwd_mkt_exrate` - 汇率
- `dwd_mkt_fund_allocation` - 基金资产配置
- `dwd_mkt_fund_derive` - 基金衍生指标
- `dwd_mkt_fund_market` - 基金行情(净值)
- `dwd_mkt_fund_structure` - 基金份额结构
- `dwd_mkt_fund_suspension` - 基金停牌
- `dwd_mkt_index_member` - 指数成分
- `dwd_mkt_index_quote` - 指数行情
- `dwd_mkt_rate` - 利率主数据
- `dwd_mkt_rate_quote` - 利率报价
- `dwd_mkt_rating` - 评级动作
- `dwd_mkt_stock_yield` - 股票收益率
- `dwd_ptl_acc` - 产品账户
- `dwd_ptl_acct_bal` - 产品账户余额
- `dwd_ptl_asset_config_info` - 产品资产配置
- `dwd_ptl_ast_hld` - 产品持仓
- `dwd_ptl_cedetail` - 产品申赎明细
- `dwd_ptl_holder_summary` - 产品持有人汇总
- `dwd_ptl_managers` - 产品经理
- `dwd_ptl_open_plan` - 产品开放计划
- `dwd_rsk_credit` - 主体信用风险
- `dwd_rsk_credit_position` - 信用风险敞口
- `dwd_rsk_sentiment` - 舆情
- `dwd_seller_info` - 销售人员
- `dwd_trn_order` - 交易指令
- `dwd_trn_trade_jy` - 交易所结算
- `dwd_trn_trade_val` - 估值维度交易
- `dwd_trn_trade_zg` - 中证登结算
- `dwd_val_acc` - 估值科目
- `dwd_val_notice` - 估值通知
- `dwd_val_rpt_bs` - 资产负债表
- `dwd_val_rpt_cf` - 现金流量表
- `dwd_val_rpt_is` - 利润表
- `dwd_val_valtable` - 估值表
- `dwd_val_voucher` - 估值凭证

## 六、后续操作建议

1. **后端集成**: 将 `scripts/zy_data_field_aliases.py` 引入后端 API；
   在 `zy_data_api_implementation.py` 的列表查询响应中调用 `apply_field_aliases(collection, record)`。
2. **前端验证**: 重启前端，访问 `/zy-data` 模块查看 `dwd_trn_trade_ptl` 等表，
   确认"交易日/买卖方向/数量/价格/金额/币种"等字段不再为空。
3. **重复运行安全**: 脚本可重入；MongoDB 已对齐字段不会被反复重命名。
4. **缺失数据补齐**: 第五节列出的表需后续单独生成。