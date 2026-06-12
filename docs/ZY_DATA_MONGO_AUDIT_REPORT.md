# ZY 数据域 MongoDB 字段对齐审计报告（修复后）

- 审计时间: 2026-06-01
- 数据库: `mongodb://localhost:27017/portfilio`

## 一、对齐状态总览

| 状态 | 数量 |
|------|------|
| ✅ 完全对齐 (ok) | **29** |
| ⚠️ 部分缺失 (partial) | 0 |
| ❌ 严重缺失 (critical) | 0 |
| 🟠 字段空值率高 | 0 |
| 📭 无数据 | 53 |
| **总计** | **82** |

## 二、各表详细

| 表名 | 中文 | 状态 | 期望字段数 | 实际字段数 | 缺失字段 |
|------|------|------|----------|----------|---------|
| `dwd_ast_info` | 资产基础信息 | ✅ 对齐 | 13 | 242 | — |
| `dwd_ast_info_ch` | 中债估值信息 | ✅ 对齐 | 9 | 20 | — |
| `dwd_ast_info_zg` | 中证估值信息 | ✅ 对齐 | 9 | 20 | — |
| `dwd_ast_yield_info` | 资产收益率 | ✅ 对齐 | 9 | 20 | — |
| `dwd_ast_cf_plan` | 资产现金流计划 | ✅ 对齐 | 5 | 14 | — |
| `dwd_ast_pledge` | 资产质押状态 | ✅ 对齐 | 7 | 18 | — |
| `dwd_ast_party` | 资产关联方 | ✅ 对齐 | 5 | 14 | — |
| `dwd_ast_exe_plan` | 资产行权计划 | ✅ 对齐 | 5 | 14 | — |
| `dwd_ast_fund_manager` | 资产基金经理 | ✅ 对齐 | 6 | 18 | — |
| `dwd_ast_bottom_raito` | 资产穿透底层 | ✅ 对齐 | 4 | 14 | — |
| `dwd_ast_fiveclass` | 资产五级分类 | ✅ 对齐 | 6 | 15 | — |
| `dwd_ast_calc_rule` | 资产计算规则 | ✅ 对齐 | 5 | 16 | — |
| `dwd_isr_institution` | 发行人主体 | ✅ 对齐 | 11 | 40 | — |
| `dwd_isr_institution_finance` | 主体财务报表 | ✅ 对齐 | 11 | 24 | — |
| `dwd_isr_trd_cntp` | 交易对手方 | ✅ 对齐 | 10 | 21 | — |
| `dwd_ptl_info` | 产品基础信息 | ✅ 对齐 | 13 | 282 | — |
| `tag_ptl_info` | 产品标签 | ✅ 对齐 | 3 | 3 | — |
| `dwd_ptl_acc` | 产品账户 | 📭 集合为空 | 6 | 0 | — |
| `dwd_ptl_cedetail` | 产品申赎明细 | 📭 集合为空 | 6 | 0 | — |
| `dwd_ptl_fee` | 产品费率 | ✅ 对齐 | 6 | 17 | — |
| `dwd_ptl_managers` | 产品经理 | 📭 集合为空 | 6 | 0 | — |
| `dwd_ptl_open_plan` | 产品开放计划 | 📭 集合为空 | 5 | 0 | — |
| `dwd_ptl_asset_config_info` | 产品资产配置 | 📭 集合为空 | 5 | 0 | — |
| `dwd_ptl_acct_bal` | 产品账户余额 | 📭 集合为空 | 5 | 0 | — |
| `dwd_ptl_ast_hld` | 产品持仓 | 📭 集合为空 | 11 | 0 | — |
| `dwd_ptl_holder_summary` | 产品持有人汇总 | 📭 集合为空 | 7 | 0 | — |
| `dwd_cash_acc` | 现金账户 | 📭 集合为空 | 9 | 0 | — |
| `dwd_val_valtable` | 估值表 | 📭 集合为空 | 11 | 0 | — |
| `dwd_val_voucher` | 估值凭证 | 📭 集合为空 | 8 | 0 | — |
| `dwd_val_summary` | 估值汇总 | ✅ 对齐 | 6 | 26 | — |
| `dwd_val_detail` | 估值明细 | ✅ 对齐 | 13 | 78 | — |
| `dwd_val_notice` | 估值通知 | 📭 集合为空 | 6 | 0 | — |
| `dwd_val_bal` | 估值科目余额 | ✅ 对齐 | 8 | 22 | — |
| `dwd_val_acc` | 估值科目 | 📭 集合为空 | 5 | 0 | — |
| `dwd_val_rpt_bs` | 资产负债表 | 📭 集合为空 | 12 | 0 | — |
| `dwd_val_rpt_is` | 利润表 | 📭 集合为空 | 11 | 0 | — |
| `dwd_val_rpt_cf` | 现金流量表 | 📭 集合为空 | 9 | 0 | — |
| `dwd_trn_trade_ast` | 资产维度交易 | ✅ 对齐 | 13 | 68 | — |
| `dwd_trn_trade_ptl` | 组合维度交易 | ✅ 对齐 | 11 | 24 | — |
| `dwd_trn_trade_val` | 估值维度交易 | 📭 集合为空 | 12 | 0 | — |
| `dwd_trn_trade_zg` | 中证登结算 | 📭 集合为空 | 8 | 0 | — |
| `dwd_trn_trade_jy` | 交易所结算 | 📭 集合为空 | 8 | 0 | — |
| `dwd_trn_order` | 交易指令 | 📭 集合为空 | 15 | 0 | — |
| `dwd_seller_info` | 销售人员 | 📭 集合为空 | 12 | 0 | — |
| `dwd_cust_info` | 客户基础 | ✅ 对齐 | 15 | 28 | — |
| `dwd_cust_make_pstn_info` | 客户持仓 | ✅ 对齐 | 10 | 24 | — |
| `dwd_cust_trans_acct_info` | 客户交易账户 | 📭 集合为空 | 9 | 0 | — |
| `dwd_cust_trans_apply_info_ta` | 申请单(TA) | 📭 集合为空 | 0 | 0 | — |
| `dwd_cust_trans_apply_info_yh` | 申请单(银行) | 📭 集合为空 | 0 | 0 | — |
| `dwd_cust_trans_cfm_info` | 确认信息 | 📭 集合为空 | 12 | 0 | — |
| `dwd_cust_trans_divd_info` | 客户分红 | 📭 集合为空 | 11 | 0 | — |
| `dwd_cust_trans_srl_info` | 客户流水 | 📭 集合为空 | 11 | 0 | — |
| `dwd_rsk_sentiment` | 舆情 | 📭 集合为空 | 10 | 0 | — |
| `dwd_rsk_credit` | 主体信用风险 | 📭 集合为空 | 10 | 0 | — |
| `dwd_rsk_credit_position` | 信用风险敞口 | 📭 集合为空 | 9 | 0 | — |
| `dwd_crdt_agme_info` | 授信协议 | 📭 集合为空 | 10 | 0 | — |
| `dwd_crdt_main_rela_rela_info` | 主体关联关系 | 📭 集合为空 | 6 | 0 | — |
| `dwd_mkt_bond` | 债券行情 | ✅ 对齐 | 10 | 29 | — |
| `dwd_mkt_bond_amount` | 债券存量 | 📭 集合为空 | 5 | 0 | — |
| `dwd_mkt_bond_creditrating` | 债项评级 | 📭 集合为空 | 6 | 0 | — |
| `dwd_mkt_bond_duration` | 久期凸性 | 📭 集合为空 | 9 | 0 | — |
| `dwd_mkt_bond_ecl` | 预期信用损失 | 📭 集合为空 | 8 | 0 | — |
| `dwd_mkt_bond_market` | 债券逐日成交 | 📭 集合为空 | 7 | 0 | — |
| `dwd_mkt_calendar` | 日历 | 📭 集合为空 | 4 | 0 | — |
| `dwd_mkt_date` | 日期维度 | 📭 集合为空 | 9 | 0 | — |
| `dwd_mkt_curve` | 收益率曲线主数据 | 📭 集合为空 | 5 | 0 | — |
| `dwd_mkt_curve_quote` | 曲线节点报价 | 📭 集合为空 | 5 | 0 | — |
| `dwd_mkt_exrate` | 汇率 | 📭 集合为空 | 6 | 0 | — |
| `dwd_mkt_fund` | 基金主数据 | ✅ 对齐 | 9 | 26 | — |
| `dwd_mkt_fund_allocation` | 基金资产配置 | 📭 集合为空 | 5 | 0 | — |
| `dwd_mkt_fund_derive` | 基金衍生指标 | 📭 集合为空 | 9 | 0 | — |
| `dwd_mkt_fund_market` | 基金行情(净值) | 📭 集合为空 | 7 | 0 | — |
| `dwd_mkt_fund_structure` | 基金份额结构 | 📭 集合为空 | 5 | 0 | — |
| `dwd_mkt_fund_suspension` | 基金停牌 | 📭 集合为空 | 5 | 0 | — |
| `dwd_mkt_index` | 指数主数据 | ✅ 对齐 | 7 | 16 | — |
| `dwd_mkt_index_member` | 指数成分 | 📭 集合为空 | 6 | 0 | — |
| `dwd_mkt_index_quote` | 指数行情 | 📭 集合为空 | 10 | 0 | — |
| `dwd_mkt_rate` | 利率主数据 | 📭 集合为空 | 5 | 0 | — |
| `dwd_mkt_rate_quote` | 利率报价 | 📭 集合为空 | 4 | 0 | — |
| `dwd_mkt_rating` | 评级动作 | 📭 集合为空 | 8 | 0 | — |
| `dwd_mkt_stock` | 股票主数据 | ✅ 对齐 | 10 | 30 | — |
| `dwd_mkt_stock_yield` | 股票收益率 | 📭 集合为空 | 15 | 0 | — |