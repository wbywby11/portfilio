# ZY 数据域字段深度审计报告

> 基于前端 `src/config/zyDataDomain/*.js` schema 与实际 JSON 数据的精确字段对比

- 数据源: `C:\Users\wangb\.hermes\cache\mock_data\full_output`

- Schema 来源: `D:\portfilio\src\config\zyDataDomain`

- 报告时间: 2026-06-01


## 一、总览

| 状态 | 数量 | 说明 |
|------|------|------|
| ✅ 完全匹配 (ok) | 0 | 字段全部对齐 |
| ⚠️ 部分缺失 (partial) | 2 | 缺少部分前端期望字段 |
| ❌ 严重不匹配 (critical) | 26 | 缺失字段≥50%，前端无法正常显示 |
| 🟠 字段为空 (null_heavy) | 0 | 字段存在但大量为空 |
| ⚪ 无 schema (no_schema) | 36 | 数据存在但前端未定义 |
| **总计** | **64** | |

## 二、❌ 严重不匹配的表（critical）

> 这些表前端期望的字段在数据中**严重缺失**（缺失率 ≥ 50%），前端表格列大面积为空。

### `dwd_ast_bottom_raito` - 资产穿透底层

- 记录数: **30**
- 前端期望字段: 4 个
- 实际数据字段: 8 个
- **缺失字段数: 2 个 (50%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BTM_AST_CD, BTM_NM
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
ASSET_CLASS, AST_NAME
```

### `dwd_ast_calc_rule` - 资产计算规则

- 记录数: **50**
- 前端期望字段: 5 个
- 实际数据字段: 8 个
- **缺失字段数: 5 个 (100%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AST_TYPE, EFF_DT, FORMULA, RULE_CD, RULE_NM
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AST_CD, AST_NAME, CALC_RULE, PAY_FREQ
```

### `dwd_ast_exe_plan` - 资产行权计划

- 记录数: **12**
- 前端期望字段: 5 个
- 实际数据字段: 9 个
- **缺失字段数: 3 个 (60%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
EXE_DT, EXE_PRC, NOTE
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AST_NAME, EXE_DATE, EXE_PRICE
```

### `dwd_ast_fiveclass` - 资产五级分类

- 记录数: **50**
- 前端期望字段: 6 个
- 实际数据字段: 9 个
- **缺失字段数: 4 个 (66%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
ADJ_FLAG, BIZ_DT, CLASS_LVL, LAST_LVL
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AST_NAME, CLASS_DATE, FIVE_CLASS
```

### `dwd_ast_fund_manager` - 资产基金经理

- 记录数: **5**
- 前端期望字段: 6 个
- 实际数据字段: 10 个
- **缺失字段数: 6 个 (100%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AST_CD, END_DT, MANAGER_ID, MANAGER_NM, SHR_FLAG, START_DT
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
FM_DEPT, FM_EXP, FM_ID, FM_NAME, FM_STYLE, FM_TITLE
```

### `dwd_ast_info` - 资产基础信息

- 记录数: **100**
- 前端期望字段: 13 个
- 实际数据字段: 232 个
- **缺失字段数: 10 个 (76%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AST_NM, AST_SUB_TYPE, BIZ_DT, BOND_TERM, CCY, COUPON_RATE, ISR_ID, LIST_DT, MARKET, MATURITY_DT
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
ACTUALCONTROLLER_NAME, APPRAISAL_BENCHMARK, ASSET_BOT_TYPE, ASSET_PLAN_TYPE1, ASSET_PLAN_TYPE2, ASSET_PLAN_TYPE3, ASSET_PLAN_TYPE4, ASSET_PLAN_TYPE5, AST_ABBR, AST_CATEGORY_DCPN, AST_INSTITUTION, AST_INSTITUTION_NAME, AST_NAME, AST_PNTRT_STTN, AST_RISK_CLASS5_TYPE, AST_TYPE2, AST_TYPE3, AST_TYPE4, AST_TYPE5, AUTO_TYPE, BANK_TYPE, BASERATECODE, BETA_RATE, BILL_MEDIUM, BLN_AREA, BOARD, BOND_TYPE, BX_DEFAULT_DATE, CALL_DEPOSIT_TYPE, CHENG_TOU_ELVEL, CHENG_TOU_FALG, CHL_ID, CHL_MANAGER, CH_TYPE, CH_TYPE2, CITY, CJ_REPO_DAYS, CLAIMS_INVEST_TYPE, CL_TYPE, COL_INFORMATION, COL_OWBER, COL_OWNER, COL_RATE, COL_TYPE, COMPANY_NATURE, COP_ORG, COUNTRY, COUNTY, CREDITOR_ID, CREDITOR_NAME, CREDIT_ENHANCEMENT_TYPE, CUR, CUSTOMER_ABBR, CUSTOMER_ID, CUSTOMER_NAME, DEAL_DEPT, DEFAULT_DATE, DEPOSIT_TYPE, DJLL, DPST_AMT, DRCT_OR_IDC_IVTN, DTS_TYPE, ECHFLR_PLN_NM, ECH_FLR_PLN_TYP, END_DATE, EXTEN_START_DATE, EXT_CD, FC_TYPE, FC_TYPE2, FINANCIER_ID, FINANCIER_NAME, FIRSTINVESTSTYLE, FNDS_DPST_BANK, FNDS_USE_DSCR, FNN_PRJCT, FNN_PSN, FNO_PROD_HLD_BTTM_LYR_AST_CVS_RMB_AMT, FUND_INDEX, FUND_STYLE, FUND_STYLE_INVEST, FUND_STYLE_WIND, FUND_STYLE_YHFL, FUND_TYPE, FUND_TYPE_WIND, G6_TYPE1, G6_TYPE2, G6_TYPE3, G6_TYPE4, G6_TYPE5, GUARANTOR, GUARANT_MODE, IF_CUSODIAN, IMGR_ID_NAME, IMPORT_TYPE2, INDUSTRY_CH, INDUSTRY_CH2, INDUSTRY_GB, INDUSTRY_GB2, INDUSTRY_GMJJ, INDUSTRY_GMJJ2, INDUSTRY_GMJJ3, INDUSTRY_GMJJ4, INDUSTRY_SW, INDUSTRY_SW2, INDUSTRY_SW3, INDUSTRY_WIND, INDUSTRY_WIND2, INDUSTRY_WIND3, INDUSTRY_WIND4, INDUSTRY_ZJH, INDUSTRY_ZJH2, INDUSTRY_ZJH3, INDUSTRY_ZJH4, INTEREST_RATE, INT_DEFAULT_DATE, INT_FIRST_INDU, INT_INDU_TYPE, INVESTMENT_AREA, INVEST_DEPT, INVEST_NATURE, INVEST_RISK_TYPE, INVEST_SIDE, INVEST_STRATEGY, INVEST_TEAMS, INVEST_TYPE, IN_WAY_FNDS_AMT, ISSUE_NUMBER, ISSUE_TYPE, IS_AD_DRAW, IS_AST_BOND, IS_BANK_SUP_DEBT, IS_CB_FUND, IS_CLASS_BABY_FUND, IS_CONVERTIBLE, IS_CON_DRAW, IS_DEFAULT, IS_EXCHANGEABLE, IS_EXTENSION, IS_HKSC, IS_HK_THEME_FUND, IS_JRJG, IS_MODIFY, IS_OUTSOURCING, IS_PIERCE, IS_PREF_STK, IS_RIGHT, IS_RISK_ASSETS, IS_ST, IS_TIER2_CAPITAL, ITS_BSS, JRJG_TYPE, JRJG_TYPE2, JUYUAN_TYPE, JUYUAN_TYPE2, LIQUIDATION_DAY, LISTING_DATE, LIST_DATE, LIST_STATUS, MANAGECORP, MANAGERS, MANAGER_ID, MANAGER_NAME, MDATE, MKT_CD, MON_MAN_TYPE, MORTGAGE_PLEDGE, MORTGAGE_PLEDGE_NATURE, NC_PROD_HLD_BTTMLYR_AST_SHR, NEXT_RAISE_START_DATE, NON_STD_CLMAST_DSTN_RTO, NOTICE_DEPOSIT_TYPE, OPEN_FREQUENCY, OPEN_TYPE, OPERATING_MODE, OPTION_AST_TYPE, OPTION_STRUCTURE, ORG_TYPE_FC, OUPON_SPECIES, PAYMENTS, PCLASS_TYPE1, PCLASS_TYPE2, PCLASS_TYPE3, PERFORMANCE, PERP_BOND_FLAG, PERP_DEBT_TYPE, PI_DEFAULT_DATE, PRINCIPAL, PROVINCE, PUBLISH_DATE, PUBLISH_PRIVATE, PUT_DEFAULT_DATE, RATE, RATE_PAY_TYPE, RATE_RULE, RATE_SPREAD, RATE_TYPE, REPO_DIRECTION, RGHT_STIN_DCPN, RIGHT_FLAG, RISK_CLASS, RISK_RATING, RMN_TRM, SETTLE_SPEED, SETUPDATE, SFBB, SFFJ, SPV_CLASSIFY, SPV_MANAGER_MODE, START_DATE, STD_BUSS_TYPE, STK_NATURE_ISS, STOCK_INVEST_TYPE, STOCK_STYLE, STOCT_INVEST_NATURE, STOP_LOSS_LINE, SUPP_GTR, TMT_FLRAST_LBY_CD, TMT_NUM_OF_LYRS, TRAN_CCT_PLC, UNDER_AST_CD, VDATE, WARNING_LINE, WIND_CODE, WIND_TYPE, WIND_TYPE2, WIND_TYPE3
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `AST_NM` | `AST_NAME` | 资产名称命名差异 |
| `ISR_ID` | `CUSTOMER_ID` | 发行人/客户ID命名差异 |
| `LIST_DT` | `LIST_DATE` | 上市日命名差异 |

### `dwd_ast_info_ch` - 中债估值信息

- 记录数: **50**
- 前端期望字段: 9 个
- 实际数据字段: 9 个
- **缺失字段数: 8 个 (88%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BIZ_DT, CONVEXITY, DURATION, RATING_AGENCY, VAL_FULL_PRC, VAL_NET_PRC, VAL_SRC, VAL_YIELD
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AST_NAME, AST_TYPE, HOLD_AMT, HOLD_QTY
```

### `dwd_ast_info_zg` - 中证估值信息

- 记录数: **50**
- 前端期望字段: 9 个
- 实际数据字段: 9 个
- **缺失字段数: 8 个 (88%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BIZ_DT, CONVEXITY, DURATION, RATING_AGENCY, VAL_FULL_PRC, VAL_NET_PRC, VAL_SRC, VAL_YIELD
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AST_NAME, AST_TYPE, IN_WAY_AMT, IN_WAY_QTY
```

### `dwd_ast_pledge` - 资产质押状态

- 记录数: **30**
- 前端期望字段: 7 个
- 实际数据字段: 10 个
- **缺失字段数: 6 个 (85%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BIZ_DT, PLEDGE_BOND_CD, PLEDGE_FLAG, PLEDGE_NOTE, PLEDGE_RATIO, PLEDGE_STD_BOND
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AST_NAME, PLEDGEE, PLEDGE_AMT, PLEDGE_RATE, PLEDGE_TYPE
```

### `dwd_ast_yield_info` - 资产收益率

- 记录数: **110**
- 前端期望字段: 9 个
- 实际数据字段: 9 个
- **缺失字段数: 8 个 (88%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BIZ_DT, DAILY_RTN, MONTH_RTN, SETTLE_PRC, WEEK_RTN, YIELD_EX, YIELD_TM, YTD_RTN
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AST_NAME, YIELD_DATE, YIELD_RATE, YIELD_TYPE
```

### `dwd_cust_info` - 客户基础

- 记录数: **200**
- 前端期望字段: 15 个
- 实际数据字段: 19 个
- **缺失字段数: 10 个 (66%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
ADDR, BIRTH_DT, BIZ_DT, CHANNEL, CUSTOMER_ID, CUST_NM, GENDER, OPEN_DT, RISK_LVL, SELLER_ID
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
ADDRESS, CITY, CUST_ID, CUST_NAME, DEPT, MANAGER, OPEN_DATE, PROVINCE, RISK_LEVEL, RISK_TYPE
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `ADDR` | `ADDRESS` | 字段名相似（疑似映射） |

### `dwd_cust_make_pstn_info` - 客户持仓

- 记录数: **612**
- 前端期望字段: 10 个
- 实际数据字段: 12 个
- **缺失字段数: 10 个 (100%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AVAIL_SHR, BIZ_DT, COST_AMT, CUSTOMER_ID, FIRST_BUY_DT, FROZEN_SHR, HLD_AMT, HLD_SHR, PORT_ID, UNREAL_PNL
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
CUST_ID, CUST_NAME, HOLD_AMT, HOLD_QTY, HOLD_RATIO, PARENT_PROD_CD, PROD_NAME, RISK_LEVEL
```

### `dwd_isr_institution` - 发行人主体

- 记录数: **30**
- 前端期望字段: 11 个
- 实际数据字段: 28 个
- **缺失字段数: 11 个 (100%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BIZ_DT, CREDIT_CD, EST_DT, INDUSTRY_CD, ISR_ID, ISR_NM, ISR_SHORT_NM, ISR_TYPE, LIST_FLAG, REG_CAP_AMT, REG_PROV
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
BANK_TYPE, CHENG_TOU_FALG, CITY, COMPANY_NATURE, COUNTY, CUSTOMER_ABBR, CUSTOMER_ID, CUSTOMER_NAME, INDUSTRY_CH, INDUSTRY_CH2, INDUSTRY_GB, INDUSTRY_GB2, INDUSTRY_SW, INDUSTRY_SW2, INDUSTRY_WIND, INDUSTRY_WIND2, INDUSTRY_ZJH, INDUSTRY_ZJH2, INDUSTRY_ZJH3, IS_DEFAULT, IS_JRJG, JRJG_TYPE, ORG_TYPE_FC, PROVINCE
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `ISR_ID` | `CUSTOMER_ID` | 发行人/客户ID命名差异 |

### `dwd_isr_institution_finance` - 主体财务报表

- 记录数: **30**
- 前端期望字段: 11 个
- 实际数据字段: 14 个
- **缺失字段数: 8 个 (72%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
EQUITY, ISR_ID, NET_PRFT, ROA, RPT_DT, RPT_TYPE, TOT_AST, TOT_LIA
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
CUSTOMER_ID, CUSTOMER_NAME, NET_ASSETS, NET_PROFIT, REPORT_DATE, TOTAL_ASSETS, TOTAL_LIABILITIES
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `ISR_ID` | `CUSTOMER_ID` | 发行人/客户ID命名差异 |

### `dwd_isr_trd_cntp` - 交易对手方

- 记录数: **10**
- 前端期望字段: 10 个
- 实际数据字段: 9 个
- **缺失字段数: 9 个 (90%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BIZ_DT, CNTP_ID, CNTP_NM, LINKED_ISR_ID, MARKET, RATING, SETT_ACCT, SETT_BANK, WHITELIST
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
CNTP_ROLE, CREDIT_LIMIT, CUSTOMER_ID, CUSTOMER_NAME
```

### `dwd_mkt_bond` - 债券行情

- 记录数: **840**
- 前端期望字段: 10 个
- 实际数据字段: 23 个
- **缺失字段数: 9 个 (90%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AMT, BIZ_DT, CHG_BP, CLOSE_PRC, HIGH_PRC, LOW_PRC, OPEN_PRC, VOL, YTM
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
ACCRUAL, AMOUNT, AST_NAME, CLEAN_PRICE, CLOSE_PRICE, CONVEXITY, CREDIT_RATING, FULL_PRICE, HIGH_PRICE, LOW_PRICE, MKT_CD, MOD_DURATION, OPEN_PRICE, PV01, SPREAD, TRADE_DATE, VOLUME, YIELD
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `AMT` | `AMOUNT` | 金额字段简写差异 |
| `VOL` | `VOLUME` | 字段名相似（疑似映射） |

### `dwd_mkt_fund` - 基金主数据

- 记录数: **225**
- 前端期望字段: 9 个
- 实际数据字段: 15 个
- **缺失字段数: 8 个 (88%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AUM, BENCHMARK, BIZ_DT, CUSTODY_BANK, ESTAB_DT, FUND_NM, FUND_TYPE, MGR_INST
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
ADJ_NAV, AMOUNT, AST_NAME, CUM_NAV, DAILY_RETURN, DISCOUNT, MKT_CD, TRADE_DATE, UNIT_NAV, VOLUME
```

### `dwd_mkt_index` - 指数主数据

- 记录数: **5**
- 前端期望字段: 7 个
- 实际数据字段: 10 个
- **缺失字段数: 5 个 (71%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BASE_DT, BASE_VAL, BIZ_DT, INDEX_NM, PUBLISHER
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
BASE_DATE, BASE_POINT, COMPONENT_COUNT, INDEX_NAME
```

### `dwd_mkt_stock` - 股票主数据

- 记录数: **285**
- 前端期望字段: 10 个
- 实际数据字段: 21 个
- **缺失字段数: 9 个 (90%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
BIZ_DT, EXCH, FREE_CAP, INDUSTRY_CD, INDUSTRY_NM, ISR_ID, LIST_DT, STOCK_NM, TOT_CAP
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AMOUNT, AST_NAME, CHANGE, CLOSE, HIGH, LOW, MARKET_CAP, MKT_CD, OPEN, PB, PCT_CHANGE, PE_TTM, PRE_CLOSE, TRADE_DATE, TURNOVER, VOLUME
```

### `dwd_ptl_fee` - 产品费率

- 记录数: **50**
- 前端期望字段: 6 个
- 实际数据字段: 10 个
- **缺失字段数: 4 个 (66%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
EFF_DT, EXP_DT, FEE_BASE, PORT_ID
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
FEE_AMT, FEE_DATE, PROD_CD, PROD_NAME
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `PORT_ID` | `PROD_CD` | 产品/组合主键命名差异 |

### `dwd_ptl_info` - 产品基础信息

- 记录数: **50**
- 前端期望字段: 13 个
- 实际数据字段: 272 个
- **缺失字段数: 11 个 (84%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AUM, BENCHMARK, CCY, CUSTODY_BANK, ESTAB_DT, MGR_INST, PORT_ID, PORT_NM, PORT_SHORT_NM, SHR_NAV, STATUS
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
ABRD_CSTDY_ORG_CNTRY, ABRD_CSTDY_ORG_NM, ACHV_RT_OF_RTRN, ACT_PROD_END_DATE, ACT_RAISE_AMOUNT, AGENCY, ASSIST_INVEST_TEAMS, ASSIST_MANAGERS, ASSIST_MANAGERS2, AUXILIARY_INVESTMENT_TEAM, AVG_OPEN_DAYS, BANK_FND_ACTL_INCM, BANK_INT_ID, BSC_INFO_PBLC_FLG, BUSS_CNTCT_PRSN_MCHN, BUSS_CNTCT_PRSN_MLBX, BUSS_CNTCT_PRSN_NM, BUSS_CNTCT_PRSN_TLPHN, BUSS_END_DATE, BUSS_STRT_DATE, CALENDAR_ID, CALENDAR_ID2, CAPITAL_SOURCE, CASH_MAX, CASH_MIN, CLSD_PROD_CLM_TYP_AST_AVG_TRM_MMC_RTO, CL_TYPE, CMD_DERIV_MAX, CMD_DERIV_MIN, CON_BENCHMARK, CON_BENCHMARK_AVG, CON_BENCHMARK_AVG2, CON_BENCHMARK_AVG_DESC, CON_BENCHMARK_DESC, CON_BENCHMARK_DOWN, CON_BENCHMARK_DOWN2, CON_BENCHMARK_DOWN_DESC, CON_BENCHMARK_UP, CON_BENCHMARK_UP2, CON_BENCHMARK_UP_DESC, CORP_ACHV_INCM, CORP_ACTL_ACHV_INCVC_YN, CPRTN_CRG_NM, CRRNI_MNTH_ANZ_RT_OF_RTRN, CRSS_BRDR_FNC_PROD_THRGH, CSNN_ORG_CD, CSNN_ORG_NM, CSNN_ORG_OWN_SRS_ORG, CSN_NTTL_SUM, CSTDY_FEE_RT, CURR, CUSTODIAN, CUSTODY_FEE, CUST_RDM_PWR_FLG, CUS_TYPE, CVS_RMB_AMT, DATA_SRC2, DATA_SRC3, DATA_TIME2, DCLR_EPT_CUST_MNMMYR_RT_OF_RTRN, DCR_EPT_CUST_HGHST_YR_RT_OF_RTRN, DEAL_DEPT, DEAL_DEPT2, DIVID_MECHANISM, DMSTC_CSTDY_ORG_CD, DMSTC_CSTDY_ORG_NM, EARLY_TERM_DATE, EFFECTIVE_STATUS, END_DATE, EPT_CUST_HGHST_YR_RT_OF_RTRN, EPT_CUST_MNMM_YR_RT_OF_RTRN, EQUITY_MAX, EQUITY_MIN, EXCESS_RETURN, FIRST_NAV_C, FIRST_OPEN_DATE, FIRST_OPEN_DATE2, FIXED_MANAGE_FEE, FI_INCOME_MAX, FI_INCOME_MIN, FNC_PROD_BUSS_SVC_MD, FNC_PROD_FNDS_CSTDY_ACCT_ID, FNC_PROD_FNDS_CSTDY_ACCT_NM, FNDS_ACCTL_INVST, FNDS_CSTDY_ACCT, FNDS_CSTDY_ACCT_ID, FNDS_INVST_RGON, FNL_PROD_PROD_AMT, FRST_OPN_WK_FRM_STRT_DAY, FUND_MANAGERS_CODE, GRDNG_RTO, HOLDING_DATE, HOLDING_DATE_UNIT, HOLDING_DAYS, IF_AT_LQDTN_IN, IF_CSH_MGT_TYP, IF_FNC_PR_ECS, IF_FOR_SRTD_GRDNG_PRD, IF_HV_EXPCT_RT_OF_RTRN, IF_HV_OTHR_ORG_CSNN, IF_HV_RT_OF_RTRN_ESTMT_INACDC_WTH, IMPORT_TYPE2, INCM_PWR_TNF_PROD_FLG, INT_BENCHMARK, INT_BENCHMARK_DESC, INVEST_NATURE, INVEST_TEAMS, INVEST_TREM_DAYS, INV_NATURE_SUBTYPE, INV_PERIOD_END_DATE, INV_PERIOD_START_DATE, INV_SCOPE, INV_STRATEGY, ISSD_ORGADVNC_TML_PWR_FLG, ISSD_ORG_ITN_PROD_CD, ISSUER_NAME, ISS_PROD_EPT_AVG_RT_OF_RTRN, ISS_PROD_EPT_CUST_HGHST_YR_RT_OF_RTRN, ISS_PROD_EPT_CUST_MNMM_YR_RT_OF_RTRN, IS_EARLY_TERM, IS_HOLIDAY_OPEN, IS_MODIFY, IS_OPEN_DAILY, IS_OVER_HALF, IS_PPEN_DAILY, IS_REDEMP_AFTER_SHORT_TERM, IS_SET_SHORT_TERM, IS_SINGLE_INVESTOR, IVTN_INCMTOACCT_DAY, IVTN_MD, IVTN_MGT_FEE_RT, IVTN_MNGR_ID_NO, IVTN_MNGR_NM, IVTN_PNP_TOACCT_DAY, IVTN_RGN, IVT_RSK_PFN, KBJJC, LGL_PRSN_IVT_TOT, LIQUIDATION_DATE, LLGL_PSN_IVT_TO, LVL_CATEGORY, MANAGECORP, MANAGERS, MDATE, MKT_BENCHMARK, MKT_BENCHMARK_DESC, MULT_SHR_ID, NEW_OLD_PROD_FLG, NL_PROD_PROD_SHR, NON_SNR_CIMAST_DSTN_RTO, NON_STD_DEBT_MAX, NON_STD_DEBT_MIN, NO_OPN_DCPN, NWST_EXPCTRT_OF_RTRN, OPEN_BUSS_DCPN, OPEN_FREQUENCY, OPEN_TYPE, OPN_BUSS_TYP, OPN_PRDD_ESY_RLZ_AST_FNL_PROD_PSTN_OCCPY_RTO, OTHER_ASSET_MAX, OTHER_ASSET_MIN, OTHER_REG_OPEN_CYC, OUT_ASSET_ID, PARENT_PROD_CD, PAY_INCOME_CUR, PAY_PRINCIPAL_CUR, PERF_BM_FORM, PLN_RS_AMT_CNY, PORT_MODEL, PORT_MODEL2, PORT_NATURE, PORT_SERIES, PORT_SERIES_XF, PORT_STAT, PORT_TERM_TYPE, PRODUCT_TYPE, PROD_ABBR, PROD_ACTL_ANZ_RT_OF_RTRN, PROD_ACTL_ANZ_RT_OF_RTRN2, PROD_APV_PSN_ID_NO, PROD_APV_PSN_NM, PROD_AST_CFRN_WAY, PROD_BRND, PROD_CD, PROD_CHNG_DT, PROD_DSGN_PSN_ID_NO, PROD_DSGN_PSN_NM, PROD_ETS_FLG, PROD_FNL_PROD_TBL_NOW, PROD_ID, PROD_INCRS_TRST_FRM, PROD_INCRS_TRST_HLG, PROD_INCRS_TRST_ORG_TYP, PROD_IVTN_CNTRY_OR_RGON, PROD_IVTN_NTR, PROD_MAX_BALA, PROD_MGT_MD, PROD_NAME, PROD_NSP_PRPR_CD, PROD_NSP_PRPR_NM, PROD_PRC_WAY, PROD_PRTNR_NM, PROD_RSK_GRD, PROD_RSRN_CD, PROD_RS_WAY, PROD_SLRGN, PROD_SPCL_ATBS, PROD_SSTG_BAL, PROD_STATUS, PROD_STRT_DT, PROD_STTS, PROD_STTS_DAY_STTS, PROD_TMT_DT, PROD_TRM, PROD_TYPE2, PROFIT_TYPE, PSN_IVT_TOT, RAISE_END_DATE, RAISE_START_DATE, RAISE_START_DATE2, REG_OPEN_CYC, RGN_RS_AMT, RMT_CUST_INCM_CNY, RMT_CUST_TTL_SUM_CNY, RMT_TTL_SHARES, RPRT_RSRN_DATE, RS_RSRN_DATE, RS_SHR, RT_OF_RTRN_BNNNG_DCPN, RUN_MODE, SALEAREA, SALES_FEE, SHORT_TERM, SHORT_TERM2, SHORT_TERM3, SL_HDN_FEE_RT, SNGL_HGHST_SSRT_AMT, SPV_IN_RATEGY, SPV_KH_BENCHMARK, SPV_MANAGER_MODE, SPV_MANAGER_MODE2, SPV_TYPE, SRN_PNT_SL_AMT, SRTL_PROD_HK_UP_SBJCT, SSD_RSRN_DATE, SSRT_AMT, SSRT_CUR, START_DATE, STD_DEBT_MAX, STD_DEBT_MIN, TMT_RSRN_DATE, TOT_PRCHS_SHR, TOT_RDM_SHR, TOT_RMT_AMT_CNY, TOT_RMT_INCM_AMT_CNY, TOT_SUB_AMT_CNY, TRST_ORG_MGT_DTS, UT_PROD_REG_CODE, VALUATION_METHOD, VALUATION_METHOD2, VAL_FREQUENCY, VDATE, VTN_AST_RTO, VTN_AST_TYP, VTN_AST_TYP_AND_RTO, VTN_TYP
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `PORT_ID` | `PROD_CD` | 产品/组合主键命名差异 |
| `PORT_NM` | `PROD_NAME` | 产品/组合名称命名差异 |
| `CCY` | `CURR` | 币种字段命名差异 |
| `ESTAB_DT` | `START_DATE` | 成立日命名差异 |
| `BENCHMARK` | `CON_BENCHMARK` | 字段名相似（疑似映射） |
| `BENCHMARK` | `INT_BENCHMARK` | 字段名相似（疑似映射） |
| `BENCHMARK` | `MKT_BENCHMARK` | 字段名相似（疑似映射） |
| `STATUS` | `PROD_STATUS` | 字段名相似（疑似映射） |

### `dwd_trn_trade_ast` - 资产维度交易

- 记录数: **500**
- 前端期望字段: 13 个
- 实际数据字段: 58 个
- **缺失字段数: 11 个 (84%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AMT, BS_DIR, CCY, CNTP_ID, MARKET, PRC, QTY, SETT_DT, STATUS, TRADER, TRADE_DT
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
AST_TRANS_SRL_NO, BOND_PS_PAYMENT, CASH_PS_PAYMENT, COUNTER_PARTY, COUNTER_TRADER, CPRICE_AMT, CPRICE_DATE, DEAL_DEP, DEPT_ID, ENT_INT_FLAG, EXER_SIDE, FPRICE_AMT, FULL_PRICE, F_GHF, F_HHF, F_JSF, F_JSFWF, F_JSFXJ, F_RGF, F_SGF, F_SHF, F_YHS, F_ZGF, IMGR_ID_NAME, INT_AST_CD, INT_RATE, INV_AIM, IS_CANCEL, IS_REAL_TRADE, LONG_AMOUNT, LONG_CURRENCY, LONG_INTEREST, LONG_PRINCIPAL, LONG_QUANTITY, LONG_TRAN_FEE, NET_PRICE, ORGNL_TRANS_NO, PARENT_TRANS_NO, PAR_VALUE, PRD_CD, PRICE_YIELD, REGIST_ORG, REMARK, SETTLE_DATE, SETTLE_SPEED, SUB_PRD_CD, TRADER_NAME, TRADE_MARKET, TRAN_COMMISION, TRAN_DATE, TRAN_SIDE, TRAN_STATUS
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `SETT_DT` | `SETTLE_DATE` | 日期字段命名差异 |
| `STATUS` | `TRAN_STATUS` | 字段名相似（疑似映射） |
| `TRADER` | `TRADER_NAME` | 字段名相似（疑似映射） |

### `dwd_trn_trade_ptl` - 组合维度交易

- 记录数: **200**
- 前端期望字段: 11 个
- 实际数据字段: 14 个
- **缺失字段数: 10 个 (90%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
AMT, AST_CD, BS_DIR, CCY, FEE, PORT_ID, PRC, QTY, SETT_DT, TRADE_DT
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
CUST_ID, CUST_NAME, PROD_CD, PROD_NAME, TRADE_AMT, TRADE_DATE, TRADE_QTY, TRADE_STATUS, TRADE_TYPE
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `TRADE_DT` | `TRADE_DATE` | 日期字段命名差异 |
| `AMT` | `TRADE_AMT` | 金额字段简写差异 |
| `PORT_ID` | `PROD_CD` | 产品/组合主键命名差异 |
| `BS_DIR` | `TRADE_TYPE` | 业务方向 vs 交易类型 |

### `dwd_val_bal` - 估值科目余额

- 记录数: **181**
- 前端期望字段: 8 个
- 实际数据字段: 12 个
- **缺失字段数: 8 个 (100%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
ACC_CD, ACC_NM, BAL, BIZ_DT, CCY, CR_BAL, DR_BAL, PORT_ID
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
ACCOUNT_CD, ACCOUNT_NAME, BAL_DATE, CREDIT_BAL, DEBIT_BAL, NET_BAL, PROD_CD, PROD_NAME
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `PORT_ID` | `PROD_CD` | 产品/组合主键命名差异 |
| `BAL` | `BAL_DATE` | 字段名相似（疑似映射） |
| `BAL` | `NET_BAL` | 字段名相似（疑似映射） |

### `dwd_val_detail` - 估值明细

- 记录数: **433**
- 前端期望字段: 13 个
- 实际数据字段: 64 个
- **缺失字段数: 12 个 (92%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
ACI_AMT, AMORT_AMT, BIZ_DT, COST_AMT, COST_PRC, DAILY_PNL, HLD_QTY, MKT_PRC, MKT_VAL, PORT_ID, REAL_PNL, UNREAL_PNL
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
ACCOUNT_CLASS_TYPE, AMOR_GL, ASSET_LOSS, AST_NAME, CURRENCY, DEPT_ID, EXPENSE, EX_GL, FULL_COST, FULL_MV, FULL_MV_LOSS, FULL_PRICE, GAINLOSS, GAINLOSS_GL, HOLDING_AMOUNT, HOLDING_SIDE, INCOME_GL, INTEREST, INTEREST_GL, INVALID_DATE, INVEST_GL, IS_LT_BOUNDED, L_AMOR_GL, L_ASSET_LOSS, L_CURRENCY, L_DIVIDEND, L_EXPENSE, L_FULL_COST, L_FULL_PRICE, L_GAINLOSS, L_GAINLOSS_GL, L_INCOME_GL, L_INTEREST, L_INTEREST_GL, L_INVEST_GL, L_MV, L_MV_LOSS, L_NET_COST, L_NET_MV, L_NET_MV_LOSS, L_NET_PRICE, L_R_GL, L_SHADOW_DELTA, L_SHADOW_MV, L_TOTAL_GL, L_ZYJ, NET_COST, NET_MV, NET_MV_LOSS, NET_PRICE, PRINFXRATE, PROD_CD, R_GL, SHADOW_DELTA, SHADOW_MV, SUB_PROD_CD, TOTAL_GL, VALID_DATE, ZYJ
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `PORT_ID` | `PROD_CD` | 产品/组合主键命名差异 |

### `dwd_val_summary` - 估值汇总

- 记录数: **50**
- 前端期望字段: 6 个
- 实际数据字段: 18 个
- **缺失字段数: 6 个 (100%)**

**🔴 缺失字段 (前端期望但数据中没有)**:

```
ACI_AMT, AST_CLASS, BIZ_DT, MKT_VAL, PORT_ID, WEIGHT
```

**🟡 额外字段 (数据中有但前端不识别)**:

```
BOND_RATIO, CASH_RATIO, CUM_NAV, FUND_RATIO, NET_VALUE, OTHER_RATIO, PROD_CD, PROD_NAME, SHARES, STOCK_RATIO, TOTAL_ASSET, TOTAL_LIABILITY, UNIT_NAV, VAL_DATE
```

**💡 疑似字段名映射**:

| 前端期望 | 数据实际 | 推测 |
|---------|---------|------|
| `PORT_ID` | `PROD_CD` | 产品/组合主键命名差异 |

## 三、⚠️ 部分缺失字段的表（partial）

| 表名 | 中文名 | 记录数 | 前端字段数 | 缺失字段数 | 缺失字段 |
|------|--------|--------|-----------|-----------|---------|
| `dwd_ast_cf_plan` | 资产现金流计划 | 177 | 5 | 2 | `CCY`, `CF_DT` |
| `dwd_ast_party` | 资产关联方 | 100 | 5 | 2 | `BIZ_DT`, `PARTY_NM` |

## 五、⚪ 数据文件存在但前端未定义 schema

> 这些 JSON 文件的数据已导入 MongoDB，但前端 ZY 数据域页面**无法识别和展示**。

| 数据文件 | 记录数 | 前端 schema |
|---------|--------|------------|
| `dwd_cust_asset_summary.json` | 200 | ❌ 未定义 |
| `dwd_cust_belong.json` | 200 | ❌ 未定义 |
| `dwd_cust_contact.json` | 200 | ❌ 未定义 |
| `dwd_cust_intention.json` | 200 | ❌ 未定义 |
| `dwd_cust_risk.json` | 200 | ❌ 未定义 |
| `dwd_cust_tag.json` | 395 | ❌ 未定义 |
| `dwd_cust_trade.json` | 2,095 | ❌ 未定义 |
| `dwd_isr_rating.json` | 60 | ❌ 未定义 |
| `dwd_mkt_commodity.json` | 150 | ❌ 未定义 |
| `dwd_mkt_credit_spread.json` | 480 | ❌ 未定义 |
| `dwd_mkt_fx.json` | 150 | ❌ 未定义 |
| `dwd_mkt_industry_index.json` | 240 | ❌ 未定义 |
| `dwd_mkt_repo_rate.json` | 150 | ❌ 未定义 |
| `dwd_mkt_yield_curve.json` | 270 | ❌ 未定义 |
| `dwd_ptl_attribution.json` | 50 | ❌ 未定义 |
| `dwd_ptl_channel.json` | 97 | ❌ 未定义 |
| `dwd_ptl_class_map.json` | 50 | ❌ 未定义 |
| `dwd_ptl_contract.json` | 50 | ❌ 未定义 |
| `dwd_ptl_manager.json` | 50 | ❌ 未定义 |
| `dwd_ptl_nav.json` | 1,500 | ❌ 未定义 |
| `dwd_ptl_pstn_detail.json` | 531 | ❌ 未定义 |
| `dwd_ptl_risk.json` | 50 | ❌ 未定义 |
| `dwd_ptl_sub_red.json` | 1,419 | ❌ 未定义 |
| `dwd_rsk_alert.json` | 10 | ❌ 未定义 |
| `dwd_rsk_compliance.json` | 50 | ❌ 未定义 |
| `dwd_rsk_limit.json` | 150 | ❌ 未定义 |
| `dwd_rsk_report.json` | 50 | ❌ 未定义 |
| `dwd_rsk_stress_test.json` | 200 | ❌ 未定义 |
| `dwd_sls_sales.json` | 300 | ❌ 未定义 |
| `dwd_val_adjustment.json` | 10 | ❌ 未定义 |
| `dwd_val_diff.json` | 5 | ❌ 未定义 |
| `dwd_val_exception.json` | 5 | ❌ 未定义 |
| `dwd_val_impairment.json` | 10 | ❌ 未定义 |
| `dwd_val_method.json` | 150 | ❌ 未定义 |
| `dwd_val_receivable_payable.json` | 146 | ❌ 未定义 |
| `dwd_val_review.json` | 50 | ❌ 未定义 |

## 七、🔧 修复建议

### 方案A：在后端 API 添加字段映射（推荐，无需改数据）

在 `scripts/zy_data_api_implementation.py` 的查询响应中，按表添加字段映射，

将实际数据字段映射为前端期望字段。例如：


```python
FIELD_ALIASES = {
    'dwd_trn_trade_ptl': {
        'TRADE_DATE': 'TRADE_DT',
        'TRADE_AMT': 'AMT',
        'PROD_CD': 'PORT_ID',
        # ... 其他映射
    }
}
```

### 方案B：在 MongoDB 中执行字段重命名（一次性）

```javascript
// 例如重命名 dwd_trn_trade_ptl 表字段
db.dwd_trn_trade_ptl.updateMany({}, {
  $rename: { 'TRADE_DATE': 'TRADE_DT', 'TRADE_AMT': 'AMT' }
})
```

### 方案C：补充数据生成脚本，按前端 schema 输出对齐字段
