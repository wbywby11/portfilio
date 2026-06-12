/**
 * 客户域 (customer) - 8 张表
 * 主键池：CUSTOMER_ID
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

const applyFields = [
  f('APPLY_NO', '申请单号', 'string', { required: true, primary: true, width: 200 }),
  f('CUSTOMER_ID', '客户ID', 'enum', { required: true, options: K.CUSTOMER_IDS, width: 130 }),
  f('PORT_ID', '组合ID', 'enum', { required: true, options: K.PORT_IDS, width: 110 }),
  f('TRADE_DT', '交易日', 'date', { required: true, width: 110, defaultValue: K.BIZ_DT }),
  f('TRD_TYPE', '交易类型', 'enum', { required: true, options: K.TRD_TYPE, width: 110 }),
  f('AMT', '金额', 'number', { width: 140 }),
  f('SHR', '份额', 'number', { width: 130 }),
  f('CHANNEL', '渠道', 'enum', { options: ['S5', 'TA', 'YH'], width: 90 }),
  f('STATUS', '状态', 'enum', { options: ['CONFIRMED', 'PENDING', 'CANCELLED'], width: 100 }),
  f('CFM_DT', '确认日', 'date', { width: 110 })
];

export default {
  domain: 'customer',
  domainName: '客户域',
  domainCode: 'CUS',
  icon: 'el-icon-s-custom',
  color: '#00BCD4',
  tables: [
    T('dwd_cust_info', '客户基础', ['CUSTOMER_ID'], [
      f('CUSTOMER_ID', '客户ID', 'string', { required: true, primary: true, width: 130, options: K.CUSTOMER_IDS, allowCreate: true }),
      f('CUST_NM', '客户名称', 'string', { required: true, width: 220 }),
      f('CUST_TYPE', '客户类型', 'enum', { required: true, options: ['IND', 'INST'], width: 100 }),
      f('GENDER', '性别', 'enum', { options: ['M', 'F'], width: 80 }),
      f('BIRTH_DT', '出生日期', 'date', { width: 110 }),
      f('ID_TYPE', '证件类型', 'enum', { options: ['IDCARD', 'CREDIT', 'PASSPORT'], width: 100 }),
      f('ID_NO', '证件号码', 'string', { width: 200 }),
      f('PHONE', '手机', 'string', { width: 130 }),
      f('EMAIL', '邮箱', 'string', { width: 200 }),
      f('ADDR', '地址', 'string', { width: 220 }),
      f('RISK_LVL', '风险等级', 'enum', { options: K.RISK_LVL, width: 100 }),
      f('OPEN_DT', '开户日期', 'date', { width: 110 }),
      f('CHANNEL', '开户渠道', 'enum', { options: ['DIRECT', 'BANK', 'BROKER'], width: 100 }),
      f('SELLER_ID', '销售ID', 'enum', { options: K.SELLER_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_cust_make_pstn_info', '客户持仓', ['CUSTOMER_ID', 'PORT_ID', 'BIZ_DT'], [
      f('CUSTOMER_ID', '客户ID', 'enum', { required: true, primary: true, options: K.CUSTOMER_IDS, width: 130 }),
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('HLD_SHR', '持仓份额', 'number', { width: 130 }),
      f('HLD_AMT', '持仓金额', 'number', { width: 140 }),
      f('COST_AMT', '成本金额', 'number', { width: 140 }),
      f('UNREAL_PNL', '浮动盈亏', 'number', { width: 130 }),
      f('AVAIL_SHR', '可用份额', 'number', { width: 130 }),
      f('FROZEN_SHR', '冻结份额', 'number', { width: 130 }),
      f('FIRST_BUY_DT', '首次申购日', 'date', { width: 120 })
    ]),

    T('dwd_cust_trans_acct_info', '客户交易账户', ['CUSTOMER_ID', 'ACCT_NO'], [
      f('CUSTOMER_ID', '客户ID', 'enum', { required: true, primary: true, options: K.CUSTOMER_IDS, width: 130 }),
      f('ACCT_NO', '账户号', 'string', { required: true, primary: true, width: 200 }),
      f('ACCT_TYPE', '账户类型', 'enum', { options: K.ACCT_TYPE, width: 100 }),
      f('BANK', '银行', 'string', { width: 130 }),
      f('BR_NM', '开户行支行', 'string', { width: 160 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('OPEN_DT', '开户日', 'date', { width: 110 }),
      f('STATUS', '状态', 'enum', { options: ['ACTIVE', 'INACTIVE'], width: 100 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_cust_trans_apply_info_s5', '申请单(直销)', ['APPLY_NO'], applyFields),
    T('dwd_cust_trans_apply_info_ta', '申请单(TA)', ['APPLY_NO'], applyFields),
    T('dwd_cust_trans_apply_info_yh', '申请单(银行)', ['APPLY_NO'], applyFields),

    T('dwd_cust_trans_cfm_info', '确认信息', ['CFM_NO'], [
      f('CFM_NO', '确认号', 'string', { required: true, primary: true, width: 200 }),
      f('APPLY_NO', '申请单号', 'string', { required: true, width: 200 }),
      f('CUSTOMER_ID', '客户ID', 'enum', { options: K.CUSTOMER_IDS, width: 130 }),
      f('PORT_ID', '组合ID', 'enum', { options: K.PORT_IDS, width: 110 }),
      f('CFM_DT', '确认日', 'date', { width: 110 }),
      f('TRD_TYPE', '交易类型', 'enum', { options: K.TRD_TYPE, width: 110 }),
      f('CFM_AMT', '确认金额', 'number', { width: 140 }),
      f('CFM_SHR', '确认份额', 'number', { width: 130 }),
      f('CFM_NAV', '确认净值', 'number', { width: 100 }),
      f('FEE', '费用', 'number', { width: 110 }),
      f('NET_AMT', '净额', 'number', { width: 140 }),
      f('STATUS', '状态', 'enum', { options: ['SUCCESS', 'FAILED'], width: 100 })
    ]),

    T('dwd_cust_trans_divd_info', '客户分红', ['CUSTOMER_ID', 'PORT_ID', 'DIV_DT'], [
      f('CUSTOMER_ID', '客户ID', 'enum', { required: true, primary: true, options: K.CUSTOMER_IDS, width: 130 }),
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('DIV_DT', '权益登记日', 'date', { required: true, primary: true, width: 120 }),
      f('EX_DIV_DT', '除权日', 'date', { width: 110 }),
      f('PAY_DT', '派息日', 'date', { width: 110 }),
      f('DIV_PER_SHR', '每份分红', 'number', { width: 110 }),
      f('HLD_SHR', '持仓份额', 'number', { width: 130 }),
      f('DIV_AMT', '分红金额', 'number', { width: 140 }),
      f('DIV_TYPE', '分红方式', 'enum', { options: ['CASH', 'REINVEST'], width: 110 }),
      f('TAX', '税额', 'number', { width: 100 }),
      f('NET_DIV_AMT', '税后金额', 'number', { width: 140 })
    ]),

    T('dwd_cust_trans_srl_info', '客户流水', ['SRL_NO'], [
      f('SRL_NO', '流水号', 'string', { required: true, primary: true, width: 200 }),
      f('CUSTOMER_ID', '客户ID', 'enum', { required: true, options: K.CUSTOMER_IDS, width: 130 }),
      f('PORT_ID', '组合ID', 'enum', { options: K.PORT_IDS, width: 110 }),
      f('REL_NO', '关联单号', 'string', { width: 200 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110 }),
      f('BIZ_TYPE', '业务类型', 'enum', { options: K.TRD_TYPE, width: 110 }),
      f('AMT', '金额', 'number', { width: 140 }),
      f('BAL_BEFORE', '变动前余额', 'number', { width: 140 }),
      f('BAL_AFTER', '变动后余额', 'number', { width: 140 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('REMARK', '备注', 'string', { width: 200 })
    ])
  ]
};
