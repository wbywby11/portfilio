/**
 * 主体域 (subject) - 3 张表
 * 主键池：ISR_ID / CNTP_ID
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

export default {
  domain: 'subject',
  domainName: '主体域',
  domainCode: 'ISR',
  icon: 'el-icon-office-building',
  color: '#67C23A',
  tables: [
    T('dwd_isr_institution', '发行人主体', ['ISR_ID'], [
      f('ISR_ID', '主体ID', 'string', { required: true, primary: true, width: 120, options: K.ISR_IDS, allowCreate: true }),
      f('ISR_NM', '主体名称', 'string', { required: true, width: 240 }),
      f('ISR_SHORT_NM', '主体简称', 'string', { width: 140 }),
      f('ISR_TYPE', '主体类型', 'enum', { options: ['SOVEREIGN', 'POLICY_BANK', 'COMMERCIAL_BANK', 'CORPORATE', 'SECURITIES'], width: 130 }),
      f('CREDIT_CD', '统一社会信用代码', 'string', { width: 200 }),
      f('INDUSTRY_CD', '行业代码', 'string', { width: 110 }),
      f('REG_PROV', '注册省份', 'string', { width: 100 }),
      f('LIST_FLAG', '是否上市', 'enum', { options: ['Y', 'N'], width: 90 }),
      f('REG_CAP_AMT', '注册资本', 'number', { width: 140 }),
      f('EST_DT', '成立日期', 'date', { width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_isr_institution_finance', '主体财务报表', ['ISR_ID', 'RPT_DT', 'RPT_TYPE'], [
      f('ISR_ID', '主体ID', 'enum', { required: true, primary: true, options: K.ISR_IDS, width: 120 }),
      f('RPT_DT', '报告期', 'date', { required: true, primary: true, width: 110 }),
      f('RPT_TYPE', '报告类型', 'enum', { required: true, primary: true, options: K.RPT_TYPE, width: 90 }),
      f('TOT_AST', '总资产', 'number', { width: 140 }),
      f('TOT_LIA', '总负债', 'number', { width: 140 }),
      f('EQUITY', '所有者权益', 'number', { width: 140 }),
      f('REVENUE', '营业收入', 'number', { width: 140 }),
      f('NET_PRFT', '净利润', 'number', { width: 140 }),
      f('ROE', 'ROE', 'number', { width: 90 }),
      f('ROA', 'ROA', 'number', { width: 90 }),
      f('DEBT_RATIO', '资产负债率', 'number', { width: 110 })
    ]),

    T('dwd_isr_trd_cntp', '交易对手方', ['CNTP_ID'], [
      f('CNTP_ID', '交易对手ID', 'string', { required: true, primary: true, width: 120, options: K.CNTP_IDS, allowCreate: true }),
      f('CNTP_NM', '交易对手名称', 'string', { required: true, width: 240 }),
      f('LINKED_ISR_ID', '关联主体ID', 'enum', { options: K.ISR_IDS, width: 120 }),
      f('CNTP_TYPE', '对手类型', 'enum', { options: ['BANK', 'BROKER', 'FUND', 'INSURANCE', 'OTHER'], width: 100 }),
      f('MARKET', '市场', 'enum', { options: K.MARKET, width: 80 }),
      f('RATING', '评级', 'string', { width: 80 }),
      f('WHITELIST', '白名单', 'enum', { options: ['Y', 'N'], width: 80 }),
      f('SETT_BANK', '结算行', 'string', { width: 130 }),
      f('SETT_ACCT', '结算账户', 'string', { width: 180 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ])
  ]
};
