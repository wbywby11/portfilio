/**
 * 资产域 (asset) - 12 张表
 * 主键池：AST_CD / ISR_ID
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

export default {
  domain: 'asset',
  domainName: '资产域',
  domainCode: 'AST',
  icon: 'el-icon-coin',
  color: '#409EFF',
  tables: [
    T('dwd_ast_info', '资产基础信息', ['AST_CD'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140, options: K.AST_CDS, allowCreate: true }),
      f('AST_NM', '资产名称', 'string', { required: true, width: 220 }),
      f('AST_TYPE', '资产类型', 'enum', { options: K.AST_TYPE, width: 100 }),
      f('AST_SUB_TYPE', '资产子类型', 'enum', { options: K.AST_SUB_TYPE, width: 110 }),
      f('ISR_ID', '发行人ID', 'enum', { options: K.ISR_IDS, width: 120 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('LIST_DT', '上市日', 'date', { width: 110 }),
      f('MATURITY_DT', '到期日', 'date', { width: 110 }),
      f('COUPON_RATE', '票面利率', 'number', { width: 100, step: 0.0001 }),
      f('ISSUE_AMT', '发行规模', 'number', { width: 140 }),
      f('MARKET', '市场', 'enum', { options: K.MARKET, width: 80 }),
      f('BOND_TERM', '债券期限', 'enum', { options: K.BOND_TERM, width: 90 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_ast_info_ch', '中债估值信息', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('VAL_NET_PRC', '估值净价', 'number', { width: 110 }),
      f('VAL_FULL_PRC', '估值全价', 'number', { width: 110 }),
      f('VAL_YIELD', '估值收益率', 'number', { width: 110 }),
      f('DURATION', '久期', 'number', { width: 90 }),
      f('CONVEXITY', '凸性', 'number', { width: 90 }),
      f('RATING_AGENCY', '评级机构', 'enum', { options: K.RATING_AGENCIES, width: 130 }),
      f('VAL_SRC', '估值来源', 'string', { width: 100, defaultValue: 'CCDC' })
    ]),

    T('dwd_ast_info_zg', '中证估值信息', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('VAL_NET_PRC', '估值净价', 'number', { width: 110 }),
      f('VAL_FULL_PRC', '估值全价', 'number', { width: 110 }),
      f('VAL_YIELD', '估值收益率', 'number', { width: 110 }),
      f('DURATION', '久期', 'number', { width: 90 }),
      f('CONVEXITY', '凸性', 'number', { width: 90 }),
      f('RATING_AGENCY', '评级机构', 'enum', { options: K.RATING_AGENCIES, width: 130 }),
      f('VAL_SRC', '估值来源', 'string', { width: 100, defaultValue: 'CSI' })
    ]),

    T('dwd_ast_yield_info', '资产收益率', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('YIELD_TM', '到期收益率', 'number', { width: 110 }),
      f('YIELD_EX', '行权收益率', 'number', { width: 110 }),
      f('DAILY_RTN', '日收益率', 'number', { width: 100 }),
      f('WEEK_RTN', '周收益率', 'number', { width: 100 }),
      f('MONTH_RTN', '月收益率', 'number', { width: 100 }),
      f('YTD_RTN', '年初至今', 'number', { width: 100 }),
      f('SETTLE_PRC', '结算价', 'number', { width: 100 })
    ]),

    T('dwd_ast_cf_plan', '资产现金流计划', ['AST_CD', 'CF_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('CF_DT', '现金流日', 'date', { required: true, primary: true, width: 110 }),
      f('CF_TYPE', '现金流类型', 'enum', { options: ['INTEREST', 'PRINCIPAL', 'BOTH'], width: 110 }),
      f('CF_AMT', '现金流金额', 'number', { width: 130 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 })
    ]),

    T('dwd_ast_pledge', '资产质押状态', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('PLEDGE_FLAG', '是否质押', 'enum', { options: ['Y', 'N'], width: 90 }),
      f('PLEDGE_RATIO', '质押比例', 'number', { width: 100 }),
      f('PLEDGE_STD_BOND', '标准券折算', 'number', { width: 110 }),
      f('PLEDGE_BOND_CD', '质押债券', 'string', { width: 130 }),
      f('PLEDGE_NOTE', '备注', 'string', { width: 200 })
    ]),

    T('dwd_ast_party', '资产关联方', ['AST_CD', 'PARTY_ID'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('PARTY_ID', '关联方ID', 'string', { required: true, primary: true, width: 130 }),
      f('PARTY_NM', '关联方名称', 'string', { width: 220 }),
      f('PARTY_ROLE', '关联方角色', 'enum', { options: ['ISSUER', 'GUARANTOR', 'TRUSTEE', 'CUSTODIAN', 'UNDERWRITER'], width: 120 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_ast_exe_plan', '资产行权计划', ['AST_CD', 'EXE_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('EXE_DT', '行权日', 'date', { required: true, primary: true, width: 110 }),
      f('EXE_TYPE', '行权类型', 'enum', { options: ['CALL', 'PUT', 'EXTENSION'], width: 100 }),
      f('EXE_PRC', '行权价格', 'number', { width: 100 }),
      f('NOTE', '备注', 'string', { width: 200 })
    ]),

    T('dwd_ast_fund_manager', '资产基金经理', ['AST_CD', 'MANAGER_ID'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('MANAGER_ID', '经理ID', 'string', { required: true, primary: true, width: 110 }),
      f('MANAGER_NM', '经理姓名', 'string', { required: true, width: 130 }),
      f('START_DT', '任职起始', 'date', { width: 110 }),
      f('END_DT', '任职结束', 'date', { width: 110 }),
      f('SHR_FLAG', '是否共管', 'enum', { options: ['Y', 'N'], width: 90 })
    ]),

    T('dwd_ast_bottom_raito', '资产穿透底层', ['AST_CD', 'BTM_AST_CD'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BTM_AST_CD', '底层资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('RATIO', '占比', 'number', { width: 100 }),
      f('BTM_NM', '底层资产名称', 'string', { width: 220 })
    ]),

    T('dwd_ast_fiveclass', '资产五级分类', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('CLASS_LVL', '分类等级', 'enum', { options: ['NORMAL', 'WATCH', 'SUBSTANDARD', 'DOUBTFUL', 'LOSS'], width: 110 }),
      f('CLASS_REASON', '分类原因', 'string', { width: 200 }),
      f('ADJ_FLAG', '是否调整', 'enum', { options: ['Y', 'N'], width: 90 }),
      f('LAST_LVL', '上次等级', 'enum', { options: ['NORMAL', 'WATCH', 'SUBSTANDARD', 'DOUBTFUL', 'LOSS'], width: 110 })
    ]),

    T('dwd_ast_calc_rule', '资产计算规则', ['AST_TYPE', 'RULE_CD'], [
      f('AST_TYPE', '资产类型', 'enum', { required: true, primary: true, options: K.AST_TYPE, width: 100 }),
      f('RULE_CD', '规则代码', 'string', { required: true, primary: true, width: 130 }),
      f('RULE_NM', '规则名称', 'string', { width: 200 }),
      f('FORMULA', '计算公式', 'string', { width: 240 }),
      f('EFF_DT', '生效日', 'date', { width: 110 })
    ])
  ]
};
