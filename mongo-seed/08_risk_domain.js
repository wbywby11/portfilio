load('_keys.js');
/**
 * 风险域 dwd_rsk_* / dwd_crdt_* — 5 张表
 * dwd_rsk_limit_check(15), dwd_rsk_alert(8), dwd_rsk_var(5),
 * dwd_crdt_rating_change(6), dwd_crdt_watchlist(5)
 */
print('--- [08] risk domain start ---');

var BIZ_DT = ZY_KEYS.BIZ_DT;
var ASTS    = ZY_KEYS.AST_CDS;
var ISRS    = ZY_KEYS.ISR_IDS;
var PORTS   = ZY_KEYS.PORT_IDS;
var aud     = ZY_KEYS.audit;

/* ================ 1. dwd_rsk_limit_check 限额检查 (15条) ================ */
var col1 = ZY_KEYS.recreate('dwd_rsk_limit_check');
col1.createIndex({ CHECK_ID: 1 }, { unique: true });
col1.createIndex({ PORT_ID: 1, CHECK_DT: 1 });
col1.createIndex({ STATUS: 1 });

var limitSeed = [
  { CHECK_ID: 'CHK20250324001', PORT_ID: 'PORT001', RULE_ID: 'RULE001', RULE_NM: '单一债券集中度限制', RULE_DESC: '单一债券持仓市值不超过基金净资产的10%', THRESHOLD: 0.10, CURRENT_VALUE: 0.0593, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324002', PORT_ID: 'PORT001', RULE_ID: 'RULE002', RULE_NM: '前十大重仓债券集中度', RULE_DESC: '前十大重仓债券合计不超过基金净资产的50%', THRESHOLD: 0.50, CURRENT_VALUE: 0.4215, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324003', PORT_ID: 'PORT001', RULE_ID: 'RULE005', RULE_NM: '组合杠杆率限制', RULE_DESC: '组合杠杆率不超过140%', THRESHOLD: 1.40, CURRENT_VALUE: 1.25, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324004', PORT_ID: 'PORT002', RULE_ID: 'RULE001', RULE_NM: '单一债券集中度限制', RULE_DESC: '单一债券持仓市值不超过基金净资产的10%', THRESHOLD: 0.10, CURRENT_VALUE: 0.0812, STATUS: 'WARNING', CHECK_DT: '20250324', BREACH_REASON: '23国开10持仓占比8.12%接近限额' },
  { CHECK_ID: 'CHK20250324005', PORT_ID: 'PORT002', RULE_ID: 'RULE003', RULE_NM: '低评级信用债限制', RULE_DESC: '信用债评级低于AA的不超过基金净资产的20%', THRESHOLD: 0.20, CURRENT_VALUE: 0.05, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324006', PORT_ID: 'PORT002', RULE_ID: 'RULE006', RULE_NM: '现金类资产下限', RULE_DESC: '现金类资产不低于基金净资产的5%', THRESHOLD: 0.05, CURRENT_VALUE: 0.08, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324007', PORT_ID: 'PORT003', RULE_ID: 'RULE001', RULE_NM: '单一债券集中度限制', RULE_DESC: '单一债券持仓市值不超过基金净资产的10%', THRESHOLD: 0.10, CURRENT_VALUE: 0.1105, STATUS: 'BREACH', CHECK_DT: '20250324', BREACH_REASON: '24万科MTN003持仓占比11.05%，超过10%限额，因信用事件后市值缩水导致被动超限' },
  { CHECK_ID: 'CHK20250324008', PORT_ID: 'PORT003', RULE_ID: 'RULE004', RULE_NM: '同一发行人集中度限制', RULE_DESC: '同一发行人发行的债券持仓不超过基金净资产的10%', THRESHOLD: 0.10, CURRENT_VALUE: 0.1105, STATUS: 'BREACH', CHECK_DT: '20250324', BREACH_REASON: '万科发行人合计持仓超限11.05%' },
  { CHECK_ID: 'CHK20250324009', PORT_ID: 'PORT003', RULE_ID: 'RULE005', RULE_NM: '组合杠杆率限制', RULE_DESC: '组合杠杆率不超过140%', THRESHOLD: 1.40, CURRENT_VALUE: 1.32, STATUS: 'WARNING', CHECK_DT: '20250324', BREACH_REASON: '杠杆率132%接近140%上限' },
  { CHECK_ID: 'CHK20250324010', PORT_ID: 'PORT004', RULE_ID: 'RULE001', RULE_NM: '单一债券集中度限制', RULE_DESC: '单一债券持仓市值不超过基金净资产的10%', THRESHOLD: 0.10, CURRENT_VALUE: 0.0720, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324011', PORT_ID: 'PORT004', RULE_ID: 'RULE006', RULE_NM: '现金类资产下限', RULE_DESC: '现金类资产不低于基金净资产的5%', THRESHOLD: 0.05, CURRENT_VALUE: 0.15, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324012', PORT_ID: 'PORT005', RULE_ID: 'RULE002', RULE_NM: '前十大重仓债券集中度', RULE_DESC: '前十大重仓债券合计不超过基金净资产的50%', THRESHOLD: 0.50, CURRENT_VALUE: 0.3850, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324013', PORT_ID: 'PORT005', RULE_ID: 'RULE005', RULE_NM: '组合杠杆率限制', RULE_DESC: '组合杠杆率不超过140%', THRESHOLD: 1.40, CURRENT_VALUE: 1.18, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324014', PORT_ID: 'PORT001', RULE_ID: 'RULE006', RULE_NM: '现金类资产下限', RULE_DESC: '现金类资产不低于基金净资产的5%', THRESHOLD: 0.05, CURRENT_VALUE: 0.062, STATUS: 'NORMAL', CHECK_DT: '20250324', BREACH_REASON: null },
  { CHECK_ID: 'CHK20250324015', PORT_ID: 'PORT003', RULE_ID: 'RULE003', RULE_NM: '低评级信用债限制', RULE_DESC: '信用债评级低于AA的不超过基金净资产的20%', THRESHOLD: 0.20, CURRENT_VALUE: 0.1650, STATUS: 'WARNING', CHECK_DT: '20250324', BREACH_REASON: '低评级占比16.5%接近20%限额，需关注万科降级后影响' }
];
limitSeed.forEach(function (d) { Object.assign(d, aud()); });
col1.insertMany(limitSeed);
print('  dwd_rsk_limit_check: ' + col1.countDocuments());

/* ================ 2. dwd_rsk_alert 风险预警 (8条) ================ */
var col2 = ZY_KEYS.recreate('dwd_rsk_alert');
col2.createIndex({ ALERT_ID: 1 }, { unique: true });
col2.createIndex({ PORT_ID: 1, TRIGGER_DT: 1 });
col2.createIndex({ ALERT_LVL: 1, HANDLE_STATUS: 1 });

var alertSeed = [
  { ALERT_ID: 'ALT20250320001', PORT_ID: 'PORT003', ALERT_TYPE: 'CREDIT_DOWNGRADE', ALERT_LVL: 'HIGH', ALERT_DESC: '持仓债券24万科MTN003的发行人万科企业被联合资信下调主体评级至AA-，触发信用风险预警', TRIGGER_DT: '20250320', RELATED_AST: '112311.SZ', RELATED_ISR: 'ISR000005', HANDLER: '周敏', HANDLE_STATUS: 'PROCESSING', HANDLE_COMMENT: '已通知投资经理评估减持方案，计划3个交易日内降低持仓至合规水平' },
  { ALERT_ID: 'ALT20250320002', PORT_ID: 'PORT003', ALERT_TYPE: 'LIMIT_BREACH', ALERT_LVL: 'HIGH', ALERT_DESC: '24万科MTN003持仓占比因市值缩水被动超限至11.05%，超过单一债券10%限额', TRIGGER_DT: '20250320', RELATED_AST: '112311.SZ', RELATED_ISR: 'ISR000005', HANDLER: '周敏', HANDLE_STATUS: 'PROCESSING', HANDLE_COMMENT: '已制定减持计划，预计3-5个交易日内恢复合规' },
  { ALERT_ID: 'ALT20250318003', PORT_ID: 'PORT002', ALERT_TYPE: 'DURATION_BREACH', ALERT_LVL: 'MEDIUM', ALERT_DESC: '组合修正久期达到5.8年，超过投资指引中5.5年上限', TRIGGER_DT: '20250318', RELATED_AST: null, RELATED_ISR: null, HANDLER: '吴晓峰', HANDLE_STATUS: 'RESOLVED', HANDLE_COMMENT: '已通过卖出长端国开债降低久期至5.3年' },
  { ALERT_ID: 'ALT20250321004', PORT_ID: 'PORT001', ALERT_TYPE: 'LIQUIDITY', ALERT_LVL: 'LOW', ALERT_DESC: '组合现金类资产占比降至6.2%，接近5%下限预警线', TRIGGER_DT: '20250321', RELATED_AST: null, RELATED_ISR: null, HANDLER: '孙志强', HANDLE_STATUS: 'RESOLVED', HANDLE_COMMENT: '已安排到期回购资金回流，次日现金占比恢复至8%' },
  { ALERT_ID: 'ALT20250319005', PORT_ID: 'PORT003', ALERT_TYPE: 'CONCENTRATION', ALERT_LVL: 'MEDIUM', ALERT_DESC: '万科发行人合计敞口占基金净资产的11.05%，超过单一发行人10%上限', TRIGGER_DT: '20250319', RELATED_AST: '112311.SZ', RELATED_ISR: 'ISR000005', HANDLER: '周敏', HANDLE_STATUS: 'PROCESSING', HANDLE_COMMENT: '与ALT20250320002合并处理，减持计划执行中' },
  { ALERT_ID: 'ALT20250324006', PORT_ID: 'PORT003', ALERT_TYPE: 'LEVERAGE', ALERT_LVL: 'MEDIUM', ALERT_DESC: '组合杠杆率达到132%，距离140%红线仅8个百分点', TRIGGER_DT: '20250324', RELATED_AST: null, RELATED_ISR: null, HANDLER: '周敏', HANDLE_STATUS: 'PENDING', HANDLE_COMMENT: null },
  { ALERT_ID: 'ALT20250315007', PORT_ID: 'PORT005', ALERT_TYPE: 'TRACKING_ERROR', ALERT_LVL: 'LOW', ALERT_DESC: '指数增强五号近20日年化跟踪误差达到3.2%，超过3%内部预警线', TRIGGER_DT: '20250315', RELATED_AST: null, RELATED_ISR: null, HANDLER: '吴晓峰', HANDLE_STATUS: 'RESOLVED', HANDLE_COMMENT: '已调整偏离度较大的个券持仓，跟踪误差回落至2.5%' },
  { ALERT_ID: 'ALT20250322008', PORT_ID: 'PORT004', ALERT_TYPE: 'COUNTERPARTY', ALERT_LVL: 'LOW', ALERT_DESC: '与兴业银行金融市场部回购余额达到授信额度的85%，触发集中度预警', TRIGGER_DT: '20250322', RELATED_AST: null, RELATED_ISR: null, HANDLER: '孙志强', HANDLE_STATUS: 'RESOLVED', HANDLE_COMMENT: '已分散至其他交易对手，兴业银行余额降至60%' }
];
alertSeed.forEach(function (d) { Object.assign(d, aud()); });
col2.insertMany(alertSeed);
print('  dwd_rsk_alert: ' + col2.countDocuments());

/* ================ 3. dwd_rsk_var VaR计算 (5条) ================ */
var col3 = ZY_KEYS.recreate('dwd_rsk_var');
col3.createIndex({ PORT_ID: 1, CALC_DT: 1 }, { unique: true });

var varSeed = [
  { PORT_ID: 'PORT001', PORT_NM: '稳健配置一号', CALC_DT: '20250324', METHOD: 'HIST_SIM', CONFIDENCE: 0.99, HORIZON_DAYS: 1, VAR_AMT: 8500000, VAR_PCT: 0.0042, ES_AMT: 12200000, ES_PCT: 0.0061, NAV: 2020000000 },
  { PORT_ID: 'PORT002', PORT_NM: '纯债精选二号', CALC_DT: '20250324', METHOD: 'HIST_SIM', CONFIDENCE: 0.99, HORIZON_DAYS: 1, VAR_AMT: 5800000, VAR_PCT: 0.0038, ES_AMT: 8500000, ES_PCT: 0.0056, NAV: 1530000000 },
  { PORT_ID: 'PORT003', PORT_NM: '混合增强三号', CALC_DT: '20250324', METHOD: 'HIST_SIM', CONFIDENCE: 0.99, HORIZON_DAYS: 1, VAR_AMT: 15200000, VAR_PCT: 0.0076, ES_AMT: 22800000, ES_PCT: 0.0114, NAV: 2000000000 },
  { PORT_ID: 'PORT004', PORT_NM: '短融货币四号', CALC_DT: '20250324', METHOD: 'PARAMETRIC', CONFIDENCE: 0.99, HORIZON_DAYS: 1, VAR_AMT: 1200000, VAR_PCT: 0.0008, ES_AMT: 1800000, ES_PCT: 0.0012, NAV: 1500000000 },
  { PORT_ID: 'PORT005', PORT_NM: '指数增强五号', CALC_DT: '20250324', METHOD: 'HIST_SIM', CONFIDENCE: 0.99, HORIZON_DAYS: 1, VAR_AMT: 9800000, VAR_PCT: 0.0056, ES_AMT: 14500000, ES_PCT: 0.0083, NAV: 1750000000 }
];
varSeed.forEach(function (d) { Object.assign(d, aud()); });
col3.insertMany(varSeed);
print('  dwd_rsk_var: ' + col3.countDocuments());

/* ================ 4. dwd_crdt_rating_change 信用评级变动 (6条) ================ */
var col4 = ZY_KEYS.recreate('dwd_crdt_rating_change');
col4.createIndex({ CHANGE_ID: 1 }, { unique: true });
col4.createIndex({ ISR_ID: 1, CHANGE_DT: 1 });

var ratingChgSeed = [
  { CHANGE_ID: 'RC20250320001', ISR_ID: 'ISR000005', ISR_NM: '万科企业股份有限公司', AGENCY: '联合资信', PREV_RATING: 'AA', NEW_RATING: 'AA-', CHANGE_TYPE: 'DOWNGRADE', CHANGE_DT: '20250320', REASON: '该主体近12个月内经营性现金流持续为负，有息债务规模未见明显压降，土地储备去化周期延长，偿债能力持续弱化', IMPACT_ASSETS: ['112311.SZ'], IMPACT_PORTS: ['PORT003'] },
  { CHANGE_ID: 'RC20250315002', ISR_ID: 'ISR000005', ISR_NM: '万科企业股份有限公司', AGENCY: '中诚信国际', PREV_RATING: 'AA', NEW_RATING: 'AA', CHANGE_TYPE: 'OUTLOOK_CHG', CHANGE_DT: '20250315', REASON: '维持AA评级但展望由稳定调整为负面，关注其短期偿债压力', IMPACT_ASSETS: ['112311.SZ'], IMPACT_PORTS: ['PORT003'] },
  { CHANGE_ID: 'RC20250310003', ISR_ID: 'ISR000003', ISR_NM: '中国工商银行股份有限公司', AGENCY: '大公国际', PREV_RATING: 'AAA', NEW_RATING: 'AAA', CHANGE_TYPE: 'UPGRADE', CHANGE_DT: '20250310', REASON: '经营稳健，不良率持续下降，资本充足率保持行业领先水平', IMPACT_ASSETS: ['2480006.IB'], IMPACT_PORTS: ['PORT003'] },
  { CHANGE_ID: 'RC20250228004', ISR_ID: 'ISR000006', ISR_NM: '华能新能源股份有限公司', AGENCY: '东方金诚', PREV_RATING: 'AA+', NEW_RATING: 'AAA', CHANGE_TYPE: 'UPGRADE', CHANGE_DT: '20250228', REASON: '新能源装机容量持续扩张，盈利能力增强，获得集团有力支持', IMPACT_ASSETS: ['127080.SZ'], IMPACT_PORTS: ['PORT003'] },
  { CHANGE_ID: 'RC20250205005', ISR_ID: 'ISR000007', ISR_NM: '招商银行股份有限公司', AGENCY: '中诚信国际', PREV_RATING: 'AAA', NEW_RATING: 'AAA', CHANGE_TYPE: 'OUTLOOK_CHG', CHANGE_DT: '20250205', REASON: '维持AAA评级，展望稳定，零售银行业务优势明显', IMPACT_ASSETS: ['600036.SH'], IMPACT_PORTS: ['PORT001', 'PORT005'] },
  { CHANGE_ID: 'RC20250118006', ISR_ID: 'ISR000004', ISR_NM: '中国农业发展银行', AGENCY: '联合资信', PREV_RATING: 'AAA', NEW_RATING: 'AAA', CHANGE_TYPE: 'OUTLOOK_CHG', CHANGE_DT: '20250118', REASON: '政策性银行属性不变，国家信用背书，展望维持稳定', IMPACT_ASSETS: ['180401.IB'], IMPACT_PORTS: ['PORT005'] }
];
ratingChgSeed.forEach(function (d) { Object.assign(d, aud()); });
col4.insertMany(ratingChgSeed);
print('  dwd_crdt_rating_change: ' + col4.countDocuments());

/* ================ 5. dwd_crdt_watchlist 信用观察名单 (5条) ================ */
var col5 = ZY_KEYS.recreate('dwd_crdt_watchlist');
col5.createIndex({ WATCH_ID: 1 }, { unique: true });
col5.createIndex({ ISR_ID: 1 });
col5.createIndex({ WATCH_LVL: 1, STATUS: 1 });

var watchSeed = [
  { WATCH_ID: 'WL20250315001', ISR_ID: 'ISR000005', ISR_NM: '万科企业股份有限公司', ADD_DT: '20250315', WATCH_REASON: '该主体短期债务占比较高，流动性压力加大，且存在大额债务集中到期风险', WATCH_LVL: 'SPECIAL_ATTENTION', REVIEWER: '周敏', NEXT_REVIEW_DT: '20250415', STATUS: 'ACTIVE' },
  { WATCH_ID: 'WL20250301002', ISR_ID: 'ISR000008', ISR_NM: '中国平安保险(集团)股份有限公司', ADD_DT: '20250301', WATCH_REASON: '保险投资端受权益市场波动影响较大，综合投资收益率下行，需持续关注偿付能力充足率变化', WATCH_LVL: 'NORMAL_WATCH', REVIEWER: '吴晓峰', NEXT_REVIEW_DT: '20250401', STATUS: 'ACTIVE' },
  { WATCH_ID: 'WL20250210003', ISR_ID: 'ISR000006', ISR_NM: '华能新能源股份有限公司', ADD_DT: '20250210', WATCH_REASON: '虽获评级上调但应收账款规模较大，补贴回款进度需持续跟踪', WATCH_LVL: 'NORMAL_WATCH', REVIEWER: '周敏', NEXT_REVIEW_DT: '20250410', STATUS: 'ACTIVE' },
  { WATCH_ID: 'WL20250105004', ISR_ID: 'ISR000007', ISR_NM: '招商银行股份有限公司', ADD_DT: '20250105', WATCH_REASON: '零售不良率边际上行，房贷集中度较高，地产风险传导需关注', WATCH_LVL: 'NORMAL_WATCH', REVIEWER: '吴晓峰', NEXT_REVIEW_DT: '20250405', STATUS: 'ACTIVE' },
  { WATCH_ID: 'WL20250320005', ISR_ID: 'ISR000005', ISR_NM: '万科企业股份有限公司', ADD_DT: '20250320', WATCH_REASON: '联合资信下调评级至AA-后触发交叉违约条款风险，密切关注近期到期债务兑付情况', WATCH_LVL: 'CRITICAL', REVIEWER: '周敏', NEXT_REVIEW_DT: '20250327', STATUS: 'ACTIVE' }
];
watchSeed.forEach(function (d) { Object.assign(d, aud()); });
col5.insertMany(watchSeed);
print('  dwd_crdt_watchlist: ' + col5.countDocuments());

print('--- [08] risk domain done ---');
