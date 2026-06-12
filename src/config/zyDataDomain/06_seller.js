/**
 * 销售域 (seller) - 1 张表
 * 主键池：SELLER_ID
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

export default {
  domain: 'seller',
  domainName: '销售域',
  domainCode: 'SEL',
  icon: 'el-icon-user',
  color: '#9C27B0',
  tables: [
    T('dwd_seller_info', '销售人员', ['SELLER_ID'], [
      f('SELLER_ID', '销售ID', 'string', { required: true, primary: true, width: 110, options: K.SELLER_IDS, allowCreate: true }),
      f('SELLER_NM', '销售姓名', 'string', { required: true, width: 130 }),
      f('SELLER_TYPE', '销售类型', 'enum', { options: ['INTERNAL', 'EXTERNAL'], width: 100 }),
      f('CHANNEL_TYPE', '渠道类型', 'enum', { required: true, options: ['DIRECT', 'BANK', 'BROKER', 'ONLINE'], width: 110 }),
      f('ORG', '所属机构', 'string', { width: 200 }),
      f('CERT_NO', '资格证书', 'string', { width: 130 }),
      f('CERT_TYPE', '证书类型', 'string', { width: 110 }),
      f('PHONE', '手机', 'string', { width: 130 }),
      f('EMAIL', '邮箱', 'string', { width: 200 }),
      f('ENTRY_DT', '入职日期', 'date', { width: 110 }),
      f('STATUS', '状态', 'enum', { options: ['ACTIVE', 'INACTIVE', 'PROBATION'], width: 100 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ])
  ]
};
