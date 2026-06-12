/**
 * 产品域 (product) - 12 张表
 * 主键池：PORT_ID
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

export default {
  domain: 'product',
  domainName: '产品域',
  domainCode: 'PTL',
  icon: 'el-icon-suitcase',
  color: '#E6A23C',
  tables: [
    T('dwd_ptl_info', '产品基础信息', ['PORT_ID'], [
      f('PORT_ID', '组合ID', 'string', { required: true, primary: true, width: 110, options: K.PORT_IDS, allowCreate: true }),
      f('PORT_NM', '组合名称', 'string', { required: true, width: 220 }),
      f('PORT_SHORT_NM', '组合简称', 'string', { width: 130 }),
      f('PORT_TYPE', '产品类型', 'enum', { options: K.PORT_TYPE, width: 100 }),
      f('RISK_LVL', '风险等级', 'enum', { options: K.RISK_LVL, width: 90 }),
      f('ESTAB_DT', '成立日', 'date', { width: 110 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('BENCHMARK', '业绩基准', 'string', { width: 200 }),
      f('SHR_NAV', '份额净值', 'number', { width: 110 }),
      f('AUM', '管理规模', 'number', { width: 140 }),
      f('MGR_INST', '管理人', 'string', { width: 160 }),
      f('CUSTODY_BANK', '托管行', 'string', { width: 140 }),
      f('STATUS', '状态', 'enum', { options: K.STATUS, width: 100 })
    ]),

    T('tag_ptl_info', '产品标签', ['PORT_ID', 'TAG_GROUP', 'TAG_VAL'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('TAG_GROUP', '标签组', 'string', { required: true, primary: true, width: 130 }),
      f('TAG_VAL', '标签值', 'string', { required: true, primary: true, width: 200 })
    ]),

    T('dwd_ptl_acc', '产品账户', ['PORT_ID', 'ACCT_NO'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('ACCT_NO', '账户号', 'string', { required: true, primary: true, width: 200 }),
      f('ACCT_TYPE', '账户类型', 'enum', { options: K.ACCT_TYPE, width: 100 }),
      f('ACCT_NM', '账户名称', 'string', { width: 200 }),
      f('BANK_BR', '开户行', 'string', { width: 160 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 })
    ]),

    T('dwd_ptl_cedetail', '产品申赎明细', ['PORT_ID', 'TRADE_DT', 'CE_TYPE'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('TRADE_DT', '交易日期', 'date', { required: true, primary: true, width: 110 }),
      f('CE_TYPE', '事件类型', 'enum', { required: true, primary: true, options: ['SUB', 'RDM', 'DIV'], width: 100 }),
      f('AMT', '金额', 'number', { width: 140 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('SUMMARY', '摘要', 'string', { width: 220 })
    ]),

    T('dwd_ptl_fee', '产品费率', ['PORT_ID', 'FEE_TYPE'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('FEE_TYPE', '费用类型', 'enum', { required: true, primary: true, options: ['MGT', 'CUSTODY', 'SALES', 'PERF'], width: 110 }),
      f('FEE_RATE', '费率', 'number', { width: 100 }),
      f('FEE_BASE', '计费基数', 'string', { width: 110 }),
      f('EFF_DT', '生效日', 'date', { width: 110 }),
      f('EXP_DT', '失效日', 'date', { width: 110 })
    ]),

    T('dwd_ptl_managers', '产品经理', ['PORT_ID', 'MANAGER_ID'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('MANAGER_ID', '经理ID', 'string', { required: true, primary: true, width: 120 }),
      f('MANAGER_NM', '经理姓名', 'string', { required: true, width: 130 }),
      f('ROLE', '角色', 'enum', { options: ['LEAD', 'CO', 'ASSIST'], width: 90 }),
      f('START_DT', '任职起始', 'date', { width: 110 }),
      f('END_DT', '任职结束', 'date', { width: 110 })
    ]),

    T('dwd_ptl_open_plan', '产品开放计划', ['PORT_ID', 'OPEN_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('OPEN_DT', '开放日', 'date', { required: true, primary: true, width: 110 }),
      f('OPEN_TYPE', '开放类型', 'enum', { options: ['SUB', 'RDM', 'BOTH'], width: 100 }),
      f('CLOSE_DT', '关闭日', 'date', { width: 110 }),
      f('QUOTA_AMT', '额度', 'number', { width: 140 })
    ]),

    T('dwd_ptl_asset_config_info', '产品资产配置', ['PORT_ID', 'AST_CLASS'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('AST_CLASS', '资产类别', 'enum', { required: true, primary: true, options: ['STOCK', 'BOND', 'CASH', 'FUND', 'OTHER'], width: 110 }),
      f('TGT_RATIO', '目标比例', 'number', { width: 100 }),
      f('MIN_RATIO', '下限', 'number', { width: 90 }),
      f('MAX_RATIO', '上限', 'number', { width: 90 })
    ]),

    T('dwd_ptl_acct_bal', '产品账户余额', ['PORT_ID', 'BIZ_DT', 'BAL_TYPE'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('BAL_TYPE', '余额类型', 'enum', { required: true, primary: true, options: ['TOTAL', 'AVAIL', 'FROZEN'], width: 100 }),
      f('AMT', '金额', 'number', { width: 140 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 })
    ]),

    T('dwd_ptl_ast_hld', '产品持仓', ['PORT_ID', 'AST_CD', 'BIZ_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('HLD_QTY', '持仓数量', 'number', { width: 130 }),
      f('COST_PRC', '成本价', 'number', { width: 100 }),
      f('MKT_PRC', '市价', 'number', { width: 100 }),
      f('COST_AMT', '成本金额', 'number', { width: 140 }),
      f('MKT_VAL', '市值', 'number', { width: 140 }),
      f('ACI_AMT', '应计利息', 'number', { width: 110 }),
      f('WEIGHT', '权重', 'number', { width: 90 }),
      f('ACCT_NO', '账户号', 'string', { width: 200 })
    ]),

    T('dwd_ptl_holder_summary', '产品持有人汇总', ['PORT_ID', 'BIZ_DT', 'HOLDER_TYPE'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('HOLDER_TYPE', '持有人类型', 'enum', { required: true, primary: true, options: K.HOLDER_TYPE, width: 110 }),
      f('HOLDER_CNT', '持有人数', 'number', { width: 110 }),
      f('TOT_SHR', '总份额', 'number', { width: 140 }),
      f('TOT_AMT', '总金额', 'number', { width: 140 }),
      f('RATIO', '占比', 'number', { width: 90 })
    ]),

    T('dwd_cash_acc', '现金账户', ['PORT_ID', 'ACCT_NO', 'BIZ_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('ACCT_NO', '账户号', 'string', { required: true, primary: true, width: 200 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('BAL', '余额', 'number', { width: 140 }),
      f('AVAIL_BAL', '可用余额', 'number', { width: 140 }),
      f('FROZEN_BAL', '冻结余额', 'number', { width: 140 }),
      f('BANK', '银行', 'string', { width: 120 }),
      f('RATE', '利率', 'number', { width: 90 })
    ])
  ]
};
