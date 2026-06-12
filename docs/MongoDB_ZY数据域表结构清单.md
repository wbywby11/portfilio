# ZY 数据域 MongoDB 表结构清单

## 总览

ZY 数据域共包含 **82 张表**,分布在 9 个业务域中。所有表都存储在 MongoDB `portfilio` 数据库中。

## 表结构详情

### 1️⃣ 资产域 (dwd_ast_*) - 12 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_ast_info` | 资产基础信息 | AST_CD | 12 | 债券/股票/基金/ABS 基本信息 |
| `dwd_ast_info_ch` | 中债估值 | AST_CD + BIZ_DT | 12 | 中债估值中心数据 |
| `dwd_ast_info_zg` | 中证估值 | AST_CD + BIZ_DT | 8 | 中证指数估值(仅债券) |
| `dwd_ast_yield_info` | 收益率信息 | AST_CD + BIZ_DT | 12 | YTM、利差、回报率 |
| `dwd_ast_cf_plan` | 现金流计划 | AST_CD + CF_DT + CF_TYPE | 15 | 付息/还本计划 |
| `dwd_ast_pledge` | 质押状态 | AST_CD + BIZ_DT | 8 | 质押式回购合格券 |
| `dwd_ast_flow_trade` | 交易流水 | TRADE_ID | 15 | 资产级交易记录 |
| `dwd_ast_rating` | 信用评级 | AST_CD + RATING_AGENCY + RATING_DT | 10 | 多机构评级历史 |
| `dwd_ast_guarantor` | 担保信息 | AST_CD + GUAR_NM | 5 | 担保方/差额支付 |
| `dwd_ast_clause` | 债券条款 | AST_CD + CLAUSE_TYPE + EFF_DT | 8 | 赎回/回售/交叉违约 |
| `dwd_ast_holder` | 持有人信息 | AST_CD + HOLDER_NM + BIZ_DT | 10 | 前十大持有人 |
| `dwd_ast_event` | 资产事件 | AST_CD + EVENT_DT + EVENT_TYPE | 8 | 付息/评级下调/发行 |

**关键字段示例 (dwd_ast_info)**:
```javascript
{
  AST_CD: "019601.IB",          // 资产代码
  AST_NM: "25国债03",            // 资产名称
  AST_TYPE: "BOND",             // BOND/STOCK/FUND/ABS
  AST_SUB_TYPE: "CGB",          // CGB/POLICY/MTN/ETF等
  ISR_ID: "ISR000001",          // 发行主体ID
  CCY: "CNY",
  LIST_DT: "20250115",
  MATURITY_DT: "20350115",
  COUPON_RATE: 0.0195,
  ISSUE_AMT: 50000000000,
  MARKET: "银行间",
  BOND_TERM: 10,
  BIZ_DT: "20250324",
  etl_dt: "20250324",
  src_sys: "SEED"
}
```

---

### 2️⃣ 主体域 (dwd_isr_*) - 3 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_isr_institution` | 机构信息 | ISR_ID | 8 | 财政部/银行/企业 |
| `dwd_isr_institution_finance` | 机构财务 | ISR_ID + RPT_DT | 16 | 资产负债表/利润表(8机构×2期) |
| `dwd_isr_trd_cntp` | 交易对手 | CNTP_ID | 5 | 券商/银行/其他 |

**关键字段示例 (dwd_isr_institution)**:
```javascript
{
  ISR_ID: "ISR000001",
  ISR_NM: "中华人民共和国财政部",
  ISR_SHORT_NM: "财政部",
  ISR_TYPE: "GOV",            // GOV/BANK/POLICY_BANK/CORP
  CREDIT_CD: "11100000MF0000001N",
  INDUSTRY_CD: "S9510",
  REG_PROV: "北京",
  LIST_FLAG: "N",
  LATEST_RATING: "AAA",
  BIZ_DT: "20250324"
}
```

---

### 3️⃣ 产品域 (dwd_ptl_*) - 12 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_ptl_info` | 产品基础信息 | PORT_ID | 5 | 稳健/纯债/混合/货币/指增 |
| `dwd_ptl_holding` | 持仓明细 | PORT_ID + AST_CD + BIZ_DT | 30 | 产品持仓(5产品×6日) |
| `dwd_ptl_nav_hist` | 净值历史 | PORT_ID + BIZ_DT | 30 | 单位净值/累计净值 |
| `dwd_ptl_return` | 收益率 | PORT_ID + BIZ_DT | 30 | 日/周/月/年收益 |
| `dwd_ptl_risk_indicator` | 风险指标 | PORT_ID + BIZ_DT | 30 | Sharpe/最大回撤/VaR |
| `dwd_ptl_benchmark` | 基准信息 | PORT_ID + BIZ_DT | 30 | 基准收益率对比 |
| `dwd_ptl_fee` | 费率信息 | PORT_ID + FEE_TYPE | 10 | 管理费/托管费/业绩报酬 |
| `dwd_ptl_investor` | 投资者结构 | PORT_ID + HOLDER_TYPE + BIZ_DT | 10 | 机构/个人占比 |
| `dwd_ptl_limit` | 投资限制 | PORT_ID + RULE_CD | 15 | 集中度/杠杆/评级限制 |
| `dwd_ptl_transaction_summary` | 交易汇总 | PORT_ID + BIZ_DT | 30 | 买卖统计 |
| `dwd_ptl_attribution` | 业绩归因 | PORT_ID + BIZ_DT | 30 | 利率/信用/选股贡献 |
| `dwd_ptl_compliance` | 合规检查 | PORT_ID + CHECK_DT + RULE_CD | 30 | 违规预警记录 |

**关键字段示例 (dwd_ptl_info)**:
```javascript
{
  PORT_ID: "PORT001",
  PORT_NM: "稳健配置一号",
  PORT_SHORT_NM: "稳健1号",
  PORT_TYPE: "MIXED",         // MIXED/BOND/MMF/INDEX
  RISK_LVL: "R3",
  ESTAB_DT: "20210601",
  CCY: "CNY",
  BENCHMARK: "中债综合指数*70%+沪深300*30%",
  SHR_NAV: 1.0512,
  ACC_NAV: 1.1835,
  AUM: 1250000000,
  MGR_INST: "ISR000008",
  CUSTODY_BANK: "ISR000003",
  STATUS: "ACTIVE"
}
```

---

### 4️⃣ 估值域 (dwd_val_*) - 10 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_val_valtable` | 估值表 | PORT_ID + BIZ_DT | 5 | 总资产/净资产/份额净值 |
| `dwd_val_voucher` | 凭证 | PORT_ID + VOUCHER_NO + BIZ_DT | 10 | 会计分录 |
| `dwd_val_summary` | 估值汇总 | PORT_ID + AST_CLASS + BIZ_DT | 15 | 资产类别汇总 |
| `dwd_val_detail` | 估值明细 | PORT_ID + AST_CD + BIZ_DT | 30 | 单资产估值 |
| `dwd_val_notice` | 估值公告 | PORT_ID + NOTICE_TYPE + BIZ_DT | 10 | 净值/分红公告 |
| `dwd_val_bal` | 余额表 | PORT_ID + ACC_CD + BIZ_DT | 25 | 会计科目余额 |
| `dwd_val_acc` | 会计科目 | ACC_CD | 30 | 科目表 |
| `dwd_val_rpt_bs` | 资产负债表 | PORT_ID + RPT_DT | 5 | 资产=负债+权益 |
| `dwd_val_rpt_is` | 利润表 | PORT_ID + RPT_DT | 5 | 收入/费用/净利润 |
| `dwd_val_rpt_cf` | 现金流量表 | PORT_ID + RPT_DT | 5 | 经营/投资/筹资 |

---

### 5️⃣ 交易域 (dwd_trn_*) - 7 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_trn_trade_ast` | 资产交易 | TRADE_ID | 15 | 资产级交易 |
| `dwd_trn_trade_ptl` | 产品交易 | TRADE_ID + PORT_ID | 15 | 产品级交易 |
| `dwd_trn_trade_val` | 交易估值 | TRADE_ID + PORT_ID + BIZ_DT | 15 | 交易估值核算 |
| `dwd_trn_trade_zg` | 交易结算 | TRADE_ID | 15 | 结算信息 |
| `dwd_trn_trade_jy` | 交易费用 | TRADE_ID | 15 | 佣金/印花税 |
| `dwd_trn_order` | 委托订单 | ORDER_ID | 15 | 委托/成交 |
| `dwd_trn_settle` | 结算流水 | SETTLE_ID | 15 | DVP/券款对付 |

---

### 6️⃣ 客户域 (dwd_cust_*) - 9 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_cust_info` | 客户信息 | CUSTOMER_ID | 7 | 个人/机构客户 |
| `dwd_cust_transaction` | 客户交易 | CUSTOMER_ID + TRADE_DT + TRD_TYPE | 35 | 申购/赎回(7客户×5日) |
| `dwd_cust_return` | 客户收益 | CUSTOMER_ID + PORT_ID + BIZ_DT | 35 | 客户持仓收益 |
| `dwd_cust_risk_assess` | 风险测评 | CUSTOMER_ID + ASSESS_DT | 7 | 风险等级C1-C4 |
| `dwd_cust_complaint` | 投诉记录 | COMPLAINT_ID | 5 | 客户投诉 |
| `dwd_cust_service` | 服务记录 | SERVICE_ID | 10 | 客户服务 |
| `dwd_cust_contact` | 联系记录 | CONTACT_ID | 15 | 电话/邮件 |
| `dwd_cust_behavior` | 行为分析 | CUSTOMER_ID + BIZ_DT | 35 | 登录/查询/交易 |
| `dwd_cust_profile` | 客户画像 | CUSTOMER_ID + BIZ_DT | 7 | 偏好/标签 |

**关键字段示例 (dwd_cust_info)**:
```javascript
{
  CUSTOMER_ID: "CUS0000001",
  CUST_NM: "张明远",
  CUST_TYPE: "IND",           // IND/INST
  GENDER: "M",
  BIRTH_DT: "19780815",
  ID_TYPE: "IDCARD",
  PHONE: "13812345001",
  EMAIL: "zhangmingyuan@163.com",
  RISK_LVL: "C3",
  OPEN_DT: "20210601",
  CHANNEL: "DIRECT",
  SELLER_ID: "SEL000001",
  BIZ_DT: "20250324"
}
```

---

### 7️⃣ 销售域 (dwd_seller_*) - 1 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_seller_info` | 销售信息 | SELLER_ID | 6 | 内部/外部销售 |

---

### 8️⃣ 风险域 (dwd_rsk_* / dwd_crdt_*) - 7 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_rsk_limit_check` | 风控检查 | PORT_ID + RULE_CD + BIZ_DT | 15 | 集中度/杠杆检查 |
| `dwd_rsk_alert` | 预警记录 | ALERT_ID | 10 | 超标预警 |
| `dwd_rsk_var` | VaR计算 | PORT_ID + BIZ_DT | 30 | 风险价值 |
| `dwd_crdt_rating_change` | 评级变动 | ISR_ID + CHANGE_DT + AGENCY | 5 | 评级上调/下调 |
| `dwd_crdt_watchlist` | 观察名单 | ISR_ID + BIZ_DT | 10 | 风险主体监控 |
| `dwd_rsk_stress_test` | 压力测试 | TEST_ID | 5 | 情景分析 |
| `dwd_rsk_report` | 风险报告 | REPORT_ID | 5 | 日报/周报/月报 |

---

### 9️⃣ 行情域 (dwd_mkt_*) - 18 张表

| 表名 | 中文名 | 主键 | 记录数 | 说明 |
|------|--------|------|--------|------|
| `dwd_mkt_bond` | 债券行情 | AST_CD + BIZ_DT | 60 | 5债券×12日 |
| `dwd_mkt_equity` | 股票行情 | AST_CD + BIZ_DT | 36 | 3股票×12日 |
| `dwd_mkt_fund` | 基金行情 | AST_CD + BIZ_DT | 48 | 4基金×12日 |
| `dwd_mkt_index` | 指数行情 | INDEX_CD + BIZ_DT | 60 | 5指数×12日 |
| `dwd_mkt_curve` | 收益率曲线 | CURVE_ID + TENOR + BIZ_DT | 60 | 5曲线×12期限 |
| `dwd_mkt_repo_rate` | 回购利率 | RATE_CD + BIZ_DT | 72 | 6利率×12日 |
| `dwd_mkt_shibor` | SHIBOR | TENOR + BIZ_DT | 72 | 8期限×12日 |
| `dwd_mkt_fx_rate` | 汇率 | CCY_PAIR + BIZ_DT | 60 | 5货币对×12日 |
| `dwd_mkt_commodity` | 商品行情 | AST_CD + BIZ_DT | 36 | 3商品×12日 |
| `dwd_mkt_option` | 期权行情 | AST_CD + BIZ_DT | 24 | 2期权×12日 |
| `dwd_mkt_credit_spread` | 信用利差 | RATING + TENOR + BIZ_DT | 60 | 5评级×12日 |
| `dwd_mkt_swap_rate` | 互换利率 | TENOR + BIZ_DT | 60 | 5期限×12日 |
| `dwd_mkt_bond_issue` | 债券发行 | AST_CD + ISSUE_DT | 5 | 新发债券信息 |
| `dwd_mkt_bond_redeem` | 债券兑付 | AST_CD + REDEEM_DT | 5 | 到期兑付 |
| `dwd_mkt_secondary_trade` | 二级交易 | TRADE_ID | 50 | 银行间/交易所 |
| `dwd_mkt_calendar` | 交易日历 | CAL_DT + CAL_TYPE | 365 | 全年交易日 |
| `dwd_mkt_data_quality` | 数据质量 | AST_CD + BIZ_DT | 100 | 完整性检查 |
| `dwd_mkt_snapshot` | 行情快照 | SNAPSHOT_DT | 12 | 日内快照 |

---

## 🔑 主键池 (跨表关联)

| 主键 | 说明 | 示例值 |
|------|------|--------|
| `AST_CD` | 资产代码 | 019601.IB, 600036.SH, 510300.SH |
| `ISR_ID` | 机构ID | ISR000001~ISR000008 |
| `PORT_ID` | 产品ID | PORT001~PORT005 |
| `CNTP_ID` | 交易对手ID | CNTP00001~CNTP00005 |
| `CUSTOMER_ID` | 客户ID | CUS0000001~CUS0000007 |
| `SELLER_ID` | 销售ID | SEL00001~SEL00006 |
| `BIZ_DT` | 业务日期 | 20250324 |

---

## 📊 数据规模统计

| 指标 | 数值 |
|------|------|
| 总表数 | 82 张 |
| 总记录数 | ~1,500+ 条 |
| 资产数 | 12 个 |
| 机构数 | 8 个 |
| 产品数 | 5 个 |
| 客户数 | 7 个 |
| 销售数 | 6 个 |
| 交易对手数 | 5 个 |
| 交易日数 | 12 天 (2025-03-17 ~ 2025-03-24) |

---

## 🗂️ 索引策略

### 主要索引

```javascript
// 资产域
db.dwd_ast_info.createIndex({ AST_CD: 1 }, { unique: true })
db.dwd_ast_info_ch.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true })
db.dwd_ast_yield_info.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true })

// 主体域
db.dwd_isr_institution.createIndex({ ISR_ID: 1 }, { unique: true })
db.dwd_isr_institution.createIndex({ ISR_NM: 1 })

// 产品域
db.dwd_ptl_info.createIndex({ PORT_ID: 1 }, { unique: true })
db.dwd_ptl_holding.createIndex({ PORT_ID: 1, AST_CD: 1, BIZ_DT: 1 }, { unique: true })
db.dwd_ptl_nav_hist.createIndex({ PORT_ID: 1, BIZ_DT: 1 }, { unique: true })

// 通用
db.*.createIndex({ BIZ_DT: 1 })  // 所有含BIZ_DT的表
db.*.createIndex({ etl_dt: 1 })  // ETL日期
```

---

## 🔗 外键关联

```
dwd_ast_info.AST_CD
  ↓
dwd_ast_info_ch.AST_CD
dwd_ast_yield_info.AST_CD
dwd_ptl_holding.AST_CD
dwd_trn_trade_ast.AST_CD

dwd_isr_institution.ISR_ID
  ↓
dwd_ast_info.ISR_ID
dwd_ptl_info.MGR_INST

dwd_ptl_info.PORT_ID
  ↓
dwd_ptl_holding.PORT_ID
dwd_ptl_nav_hist.PORT_ID
dwd_cust_transaction.PORT_ID

dwd_cust_info.CUSTOMER_ID
  ↓
dwd_cust_transaction.CUSTOMER_ID
dwd_cust_return.CUSTOMER_ID
```

---

## 📝 审计字段

所有表包含以下审计字段:

```javascript
{
  etl_dt: "20250324",      // ETL日期
  src_sys: "SEED",         // 数据来源系统
  created_at: ISODate(),   // 创建时间
  updated_at: ISODate()    // 更新时间
}
```

---

## 🚀 数据导入

### 方式 1: 使用 mongo-seed 脚本 (推荐)

```bash
cd d:\portfilio\mongo-seed
mongosh portfilio 01_asset_domain.js
mongosh portfilio 02_subject_domain.js
# ... 依次运行 9 个脚本
```

### 方式 2: 一键导入所有域

```bash
cd d:\portfilio\mongo-seed
for f in *.js; do mongosh portfilio "$f"; done
```

### 方式 3: 使用 Python 导入脚本

```bash
cd d:\portfilio
python scripts/import_mongo_seeds.py
```

---

## ✅ 验证查询

```javascript
// 查看所有集合
use portfilio
show collections

// 查看记录数
db.dwd_ast_info.countDocuments()
db.dwd_ptl_info.countDocuments()
db.dwd_isr_institution.countDocuments()

// 查询样例
db.dwd_ast_info.findOne({ AST_CD: "019601.IB" })
db.dwd_ptl_info.findOne({ PORT_ID: "PORT001" })
db.dwd_isr_institution.findOne({ ISR_ID: "ISR000001" })
```

---

## 📚 相关文档

- [mongo-seed/README.md](../mongo-seed/README.md) - 种子数据说明
- [ZY_DATA_API_INTEGRATION_GUIDE.md](./ZY_DATA_API_INTEGRATION_GUIDE.md) - API 集成指南
- [ZY_DATA域解决方案-快速指南.md](../ZY_DATA域解决方案-快速指南.md) - 快速开始
