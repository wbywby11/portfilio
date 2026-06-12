/**
 * 风险域 (risk) - 5 张表
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

export default {
  domain: 'risk',
  domainName: '风险域',
  domainCode: 'RSK',
  icon: 'el-icon-warning-outline',
  color: '#FF5722',
  tables: [
    T('dwd_rsk_sentiment', '舆情', ['SENT_ID'], [
      f('SENT_ID', '舆情ID', 'string', { required: true, primary: true, width: 130 }),
      f('TARGET_TYPE', '目标类型', 'enum', { required: true, options: ['ISR', 'AST', 'PORT'], width: 100 }),
      f('TARGET_CD', '目标代码', 'string', { required: true, width: 140 }),
      f('PUB_DT', '发布日期', 'date', { required: true, width: 110 }),
      f('PUB_TM', '发布时间', 'string', { width: 100 }),
      f('SOURCE', '信息源', 'string', { width: 130 }),
      f('TITLE', '标题', 'string', { required: true, width: 240 }),
      f('SENT_TYPE', '情绪类型', 'enum', { options: ['POSITIVE', 'NEGATIVE', 'NEUTRAL'], width: 110 }),
      f('SCORE', '情绪分值', 'number', { width: 100 }),
      f('SUMMARY', '摘要', 'string', { width: 260 })
    ]),

    T('dwd_rsk_credit', '主体信用风险', ['ISR_ID', 'BIZ_DT'], [
      f('ISR_ID', '主体ID', 'enum', { required: true, primary: true, options: K.ISR_IDS, width: 120 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('INTERNAL_RATING', '内部评级', 'string', { width: 100 }),
      f('EXT_RATING', '外部评级', 'string', { width: 100 }),
      f('PD_1Y', '1年违约概率', 'number', { width: 130 }),
      f('LGD', '违约损失率', 'number', { width: 110 }),
      f('EAD', '违约风险敞口', 'number', { width: 140 }),
      f('EXPECTED_LOSS', '预期损失', 'number', { width: 140 }),
      f('WATCH_FLAG', '观察标识', 'enum', { options: ['Y', 'N'], width: 90 }),
      f('LAST_RATING_DT', '上次评级日', 'date', { width: 110 })
    ]),

    T('dwd_rsk_credit_position', '信用风险敞口', ['PORT_ID', 'AST_CD', 'BIZ_DT'], [
      f('PORT_ID', '组合ID', 'enum', { required: true, primary: true, options: K.PORT_IDS, width: 110 }),
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('EXPOSURE', '敞口金额', 'number', { width: 140 }),
      f('RATING', '评级', 'string', { width: 90 }),
      f('DURATION', '久期', 'number', { width: 90 }),
      f('EL_AMT', '预期损失金额', 'number', { width: 130 }),
      f('VAR_99', 'VaR 99%', 'number', { width: 120 }),
      f('LIMIT_FLAG', '限额状态', 'enum', { options: ['NORMAL', 'WARN', 'BREACH'], width: 100 })
    ]),

    T('dwd_crdt_agme_info', '授信协议', ['AGME_NO'], [
      f('AGME_NO', '协议号', 'string', { required: true, primary: true, width: 180 }),
      f('CNTP_ID', '对手ID', 'enum', { required: true, options: K.CNTP_IDS, width: 110 }),
      f('AGME_TYPE', '协议类型', 'enum', { options: ['NAFMII', 'ISDA', 'INTERBANK', 'OTHER'], width: 110 }),
      f('EFF_DT', '生效日', 'date', { width: 110 }),
      f('EXP_DT', '失效日', 'date', { width: 110 }),
      f('LIMIT_AMT', '授信额度', 'number', { width: 140 }),
      f('USED_AMT', '已用额度', 'number', { width: 140 }),
      f('REMAIN_AMT', '剩余额度', 'number', { width: 140 }),
      f('RISK_LVL', '风险等级', 'enum', { options: ['LOW', 'MID', 'HIGH'], width: 100 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_crdt_main_rela_rela_info', '主体关联关系', ['SRC_ISR_ID', 'TGT_ISR_ID', 'REL_TYPE'], [
      f('SRC_ISR_ID', '源主体ID', 'enum', { required: true, primary: true, options: K.ISR_IDS, width: 120 }),
      f('TGT_ISR_ID', '目标主体ID', 'enum', { required: true, primary: true, options: K.ISR_IDS, width: 120 }),
      f('REL_TYPE', '关系类型', 'enum', { required: true, primary: true, options: ['CMRC_PEER', 'POLICY_PEER', 'UNDERWRITER', 'BUSINESS', 'PARENT', 'SUBSIDIARY'], width: 130 }),
      f('SHARE_RATIO', '持股比例', 'number', { width: 110 }),
      f('REMARK', '备注', 'string', { width: 220 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ])
  ]
};
