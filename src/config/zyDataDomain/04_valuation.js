/**
 * 估值域 (valuation) - 10 张表
 * 主键池：PORT_ID
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

export default {
  domain: 'valuation',
  domainName: '估值域',
  domainCode: 'VAL',
  icon: 'el-icon-money',
  color: '#F56C6C',
  tables: [
    T('dwd_val_valtable', '估值表', ['PORT_ID', 'BIZ_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('TOT_AST', '总资产', 'number', { width: 140 }),
      f('TOT_LIA', '总负债', 'number', { width: 140 }),
      f('NET_AST', '净资产', 'number', { width: 140 }),
      f('SHR_NAV', '份额净值', 'number', { width: 110 }),
      f('ACC_NAV', '累计净值', 'number', { width: 110 }),
      f('TOT_SHR', '总份额', 'number', { width: 140 }),
      f('DAILY_RTN', '日收益率', 'number', { width: 100 }),
      f('VAL_STATUS', '估值状态', 'enum', { options: ['DRAFT', 'CHECK', 'CONFIRMED'], width: 100 }),
      f('VAL_VER', '版本号', 'string', { width: 100 })
    ]),

    T('dwd_val_voucher', '估值凭证', ['PORT_ID', 'BIZ_DT', 'VOUCHER_NO'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('VOUCHER_NO', '凭证号', 'string', { required: true, primary: true, width: 140 }),
      f('VOUCHER_TYPE', '凭证类型', 'enum', { options: ['NORMAL', 'ADJUST', 'REVERSE'], width: 100 }),
      f('DESCRIPTION', '描述', 'string', { width: 220 }),
      f('DR_AMT', '借方金额', 'number', { width: 140 }),
      f('CR_AMT', '贷方金额', 'number', { width: 140 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 })
    ]),

    T('dwd_val_summary', '估值汇总', ['PORT_ID', 'BIZ_DT', 'AST_CLASS'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('AST_CLASS', '资产类别', 'enum', { required: true, primary: true, options: ['STOCK', 'BOND', 'CASH', 'FUND', 'OTHER'], width: 110 }),
      f('MKT_VAL', '市值', 'number', { width: 140 }),
      f('WEIGHT', '权重', 'number', { width: 90 }),
      f('ACI_AMT', '应计利息', 'number', { width: 110 })
    ]),

    T('dwd_val_detail', '估值明细', ['PORT_ID', 'AST_CD', 'BIZ_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('HLD_QTY', '持仓数量', 'number', { width: 130 }),
      f('COST_PRC', '成本价', 'number', { width: 100 }),
      f('MKT_PRC', '市价', 'number', { width: 100 }),
      f('COST_AMT', '成本金额', 'number', { width: 140 }),
      f('MKT_VAL', '市值', 'number', { width: 140 }),
      f('ACI_AMT', '应计利息', 'number', { width: 110 }),
      f('UNREAL_PNL', '浮动盈亏', 'number', { width: 130 }),
      f('REAL_PNL', '实现盈亏', 'number', { width: 130 }),
      f('DAILY_PNL', '日盈亏', 'number', { width: 130 }),
      f('AMORT_AMT', '摊销金额', 'number', { width: 130 })
    ]),

    T('dwd_val_notice', '估值通知', ['PORT_ID', 'BIZ_DT', 'NOTICE_TYPE'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('NOTICE_TYPE', '通知类型', 'enum', { required: true, primary: true, options: ['NAV', 'DIVIDEND', 'EVENT'], width: 110 }),
      f('TITLE', '标题', 'string', { width: 220 }),
      f('CONTENT', '内容', 'string', { width: 280 }),
      f('PUB_DT', '发布日期', 'date', { width: 110 })
    ]),

    T('dwd_val_bal', '估值科目余额', ['PORT_ID', 'BIZ_DT', 'ACC_CD'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('ACC_CD', '科目代码', 'string', { required: true, primary: true, width: 130 }),
      f('ACC_NM', '科目名称', 'string', { width: 200 }),
      f('DR_BAL', '借方余额', 'number', { width: 140 }),
      f('CR_BAL', '贷方余额', 'number', { width: 140 }),
      f('BAL', '余额', 'number', { width: 140 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 })
    ]),

    T('dwd_val_acc', '估值科目', ['ACC_CD'], [
      f('ACC_CD', '科目代码', 'string', { required: true, primary: true, width: 130 }),
      f('ACC_NM', '科目名称', 'string', { required: true, width: 200 }),
      f('PARENT_CD', '上级科目', 'string', { width: 130 }),
      f('ACC_LVL', '科目层级', 'number', { width: 100 }),
      f('DIRECTION', '余额方向', 'enum', { options: ['D', 'C'], width: 90 })
    ]),

    T('dwd_val_rpt_bs', '资产负债表', ['PORT_ID', 'RPT_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('RPT_DT', '报告期', 'date', { required: true, primary: true, width: 110 }),
      f('CASH', '现金', 'number', { width: 140 }),
      f('BOND_HLD', '债券持仓', 'number', { width: 140 }),
      f('STOCK_HLD', '股票持仓', 'number', { width: 140 }),
      f('FUND_HLD', '基金持仓', 'number', { width: 140 }),
      f('INT_RCV', '应收利息', 'number', { width: 140 }),
      f('TOT_AST', '资产总计', 'number', { width: 140 }),
      f('PAY_REDEEM', '应付赎回款', 'number', { width: 140 }),
      f('MGT_FEE_PAY', '应付管理费', 'number', { width: 140 }),
      f('TOT_LIA', '负债总计', 'number', { width: 140 }),
      f('EQUITY', '所有者权益', 'number', { width: 140 })
    ]),

    T('dwd_val_rpt_is', '利润表', ['PORT_ID', 'RPT_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('RPT_DT', '报告期', 'date', { required: true, primary: true, width: 110 }),
      f('INT_INC', '利息收入', 'number', { width: 140 }),
      f('DIV_INC', '股息收入', 'number', { width: 140 }),
      f('TRD_PNL', '交易盈亏', 'number', { width: 140 }),
      f('FV_CHG_PNL', '公允价值变动损益', 'number', { width: 160 }),
      f('MGT_FEE', '管理费', 'number', { width: 130 }),
      f('CUSTODY_FEE', '托管费', 'number', { width: 130 }),
      f('SALES_FEE', '销售费', 'number', { width: 130 }),
      f('OTHER_FEE', '其他费用', 'number', { width: 130 }),
      f('NET_INC', '净收益', 'number', { width: 140 })
    ]),

    T('dwd_val_rpt_cf', '现金流量表', ['PORT_ID', 'RPT_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('RPT_DT', '报告期', 'date', { required: true, primary: true, width: 110 }),
      f('CF_FROM_INV_INFLOW', '投资活动流入', 'number', { width: 150 }),
      f('CF_FROM_INV_OUTFLOW', '投资活动流出', 'number', { width: 150 }),
      f('CF_FROM_INV_NET', '投资活动净额', 'number', { width: 150 }),
      f('CF_FROM_FIN_SUB', '筹资-申购', 'number', { width: 140 }),
      f('CF_FROM_FIN_RDM', '筹资-赎回', 'number', { width: 140 }),
      f('CF_FROM_FIN_NET', '筹资活动净额', 'number', { width: 150 }),
      f('CASH_NET_CHG', '现金净变动', 'number', { width: 140 })
    ])
  ]
};
