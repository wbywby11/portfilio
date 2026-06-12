/**
 * 交易域 (transaction) - 6 张表
 * 主键池：TRADE_ID / ORDER_ID
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

export default {
  domain: 'transaction',
  domainName: '交易域',
  domainCode: 'TRN',
  icon: 'el-icon-sort',
  color: '#909399',
  tables: [
    T('dwd_trn_trade_ast', '资产维度交易', ['TRADE_ID'], [
      f('TRADE_ID', '交易ID', 'string', { required: true, primary: true, width: 160 }),
      f('AST_CD', '资产代码', 'enum', { required: true, options: K.AST_CDS, width: 140 }),
      f('TRADE_DT', '交易日', 'date', { required: true, width: 110, defaultValue: K.BIZ_DT }),
      f('SETT_DT', '结算日', 'date', { width: 110 }),
      f('BS_DIR', '买卖方向', 'enum', { options: K.BS_DIR, width: 100 }),
      f('QTY', '数量', 'number', { width: 130 }),
      f('PRC', '价格', 'number', { width: 100 }),
      f('AMT', '金额', 'number', { width: 140 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('CNTP_ID', '对手ID', 'enum', { options: K.CNTP_IDS, width: 110 }),
      f('MARKET', '市场', 'enum', { options: K.MARKET, width: 80 }),
      f('TRADER', '交易员', 'string', { width: 110 }),
      f('STATUS', '状态', 'enum', { options: K.TRADE_STATUS, width: 100 })
    ]),

    T('dwd_trn_trade_ptl', '组合维度交易', ['TRADE_ID', 'PORT_ID'], [
      f('TRADE_ID', '交易ID', 'string', { required: true, primary: true, width: 160 }),
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('AST_CD', '资产代码', 'enum', { required: true, options: K.AST_CDS, width: 140 }),
      f('TRADE_DT', '交易日', 'date', { width: 110, defaultValue: K.BIZ_DT }),
      f('SETT_DT', '结算日', 'date', { width: 110 }),
      f('BS_DIR', '买卖方向', 'enum', { options: K.BS_DIR, width: 100 }),
      f('QTY', '数量', 'number', { width: 130 }),
      f('PRC', '价格', 'number', { width: 100 }),
      f('AMT', '金额', 'number', { width: 140 }),
      f('FEE', '费用', 'number', { width: 110 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 })
    ]),

    T('dwd_trn_trade_val', '估值维度交易', ['TRADE_ID', 'PORT_ID'], [
      f('TRADE_ID', '交易ID', 'string', { required: true, primary: true, width: 160 }),
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('AST_CD', '资产代码', 'enum', { required: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT }),
      f('BS_DIR', '买卖方向', 'enum', { options: K.BS_DIR, width: 100 }),
      f('NET_PRC', '净价', 'number', { width: 100 }),
      f('FULL_PRC', '全价', 'number', { width: 100 }),
      f('ACI_AMT', '应计利息', 'number', { width: 110 }),
      f('REAL_PNL', '实现盈亏', 'number', { width: 130 }),
      f('FEE_AMT', '费用金额', 'number', { width: 110 }),
      f('AMORT_AMT', '摊销金额', 'number', { width: 130 }),
      f('VAL_STATUS', '估值状态', 'enum', { options: ['UNVAL', 'VALUED', 'ADJUSTED'], width: 110 })
    ]),

    T('dwd_trn_trade_zg', '中证登结算', ['TRADE_ID'], [
      f('TRADE_ID', '交易ID', 'string', { required: true, primary: true, width: 160 }),
      f('SETT_DT', '结算日', 'date', { width: 110 }),
      f('SETT_AMT', '结算金额', 'number', { width: 140 }),
      f('SETT_QTY', '结算数量', 'number', { width: 130 }),
      f('SETT_TYPE', '结算方式', 'enum', { options: ['DVP', 'NETTING', 'CASH'], width: 110 }),
      f('BOND_ACCT_NO', '债券账户', 'string', { width: 200 }),
      f('CASH_ACCT_NO', '资金账户', 'string', { width: 200 }),
      f('SETT_STATUS', '结算状态', 'enum', { options: K.SETT_STATUS, width: 110 })
    ]),

    T('dwd_trn_trade_jy', '交易所结算', ['TRADE_ID'], [
      f('TRADE_ID', '交易ID', 'string', { required: true, primary: true, width: 160 }),
      f('SETT_DT', '结算日', 'date', { width: 110 }),
      f('EXCH', '交易所', 'enum', { options: ['SSE', 'SZSE'], width: 90 }),
      f('SETT_AMT', '结算金额', 'number', { width: 140 }),
      f('SETT_QTY', '结算数量', 'number', { width: 130 }),
      f('COMMISSION', '佣金', 'number', { width: 110 }),
      f('STAMP_TAX', '印花税', 'number', { width: 110 }),
      f('SETT_STATUS', '结算状态', 'enum', { options: K.SETT_STATUS, width: 110 })
    ]),

    T('dwd_trn_order', '交易指令', ['ORDER_ID'], [
      f('ORDER_ID', '指令ID', 'string', { required: true, primary: true, width: 160 }),
      f('PORT_ID', '组合ID', 'enum', { required: true, options: K.PORT_IDS, width: 110 }),
      f('AST_CD', '资产代码', 'enum', { required: true, options: K.AST_CDS, width: 140 }),
      f('SUBMIT_DT', '提交日期', 'date', { width: 110, defaultValue: K.BIZ_DT }),
      f('SUBMIT_TM', '提交时间', 'string', { width: 110 }),
      f('BS_DIR', '买卖方向', 'enum', { options: K.BS_DIR, width: 100 }),
      f('ORD_QTY', '指令数量', 'number', { width: 130 }),
      f('ORD_PRC', '指令价格', 'number', { width: 100 }),
      f('ORD_TYPE', '指令类型', 'enum', { options: K.ORD_TYPE, width: 100 }),
      f('TRADER', '交易员', 'string', { width: 110 }),
      f('PM_APPROVER', 'PM审批', 'string', { width: 110 }),
      f('STATUS', '状态', 'enum', { options: K.TRADE_STATUS, width: 100 }),
      f('FILL_QTY', '成交数量', 'number', { width: 130 }),
      f('AVG_PRC', '均价', 'number', { width: 100 }),
      f('LINK_TRADE_ID', '关联交易', 'string', { width: 160 })
    ])
  ]
};
