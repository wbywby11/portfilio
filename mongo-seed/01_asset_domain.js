/**
 * 资产域 dwd_ast_* — 12 张表
 * 主键：AST_CD（证券代码）
 * 依赖：_keys.js (ZY_KEYS)
 *
 * 表清单：
 *   1. dwd_ast_info          资产基础信息   12 条
 *   2. dwd_ast_info_ch       中债估值       12 条
 *   3. dwd_ast_info_zg       中证估值        8 条
 *   4. dwd_ast_yield_info    收益率信息     12 条
 *   5. dwd_ast_cf_plan       现金流计划     15 条
 *   6. dwd_ast_pledge        质押状态        8 条
 *   7. dwd_ast_flow_trade    交易流水       15 条
 *   8. dwd_ast_rating        信用评级       10 条
 *   9. dwd_ast_guarantor     担保信息        5 条
 *  10. dwd_ast_clause        债券条款        8 条
 *  11. dwd_ast_holder        持有人信息     10 条
 *  12. dwd_ast_event         资产事件        8 条
 */
load('_keys.js');
print('--- [01] asset domain start ---');

var BIZ_DT = ZY_KEYS.BIZ_DT;
var AST    = ZY_KEYS.AST_CDS;
var aud    = ZY_KEYS.audit;

/* ================ 1. dwd_ast_info 资产基础信息 (12) ================ */
ZY_KEYS.recreate('dwd_ast_info', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'AST_NM', 'AST_TYPE', 'BIZ_DT'],
  properties: {
    AST_CD:   { bsonType: 'string', description: '资产代码（主键）' },
    AST_NM:   { bsonType: 'string', description: '资产名称' },
    AST_TYPE: { bsonType: 'string', description: 'BOND/STOCK/FUND/ABS/NCD/CASH' },
    BIZ_DT:   { bsonType: 'string', description: '业务日期 yyyymmdd' }
  }
}});
db.dwd_ast_info.createIndex({ AST_CD: 1 }, { unique: true });

var astInfoSeed = [
  { AST_CD: '019601.IB',  AST_NM: '25国债03',                AST_TYPE: 'BOND',  AST_SUB_TYPE: 'CGB',        ISR_ID: 'ISR000001', CCY: 'CNY', LIST_DT: '20250115', MATURITY_DT: '20350115', COUPON_RATE: 0.0195, ISSUE_AMT:  500.0e8, MARKET: '银行间', BOND_TERM: 10  },
  { AST_CD: '019735.IB',  AST_NM: '25特别国债03',            AST_TYPE: 'BOND',  AST_SUB_TYPE: 'CGB',        ISR_ID: 'ISR000001', CCY: 'CNY', LIST_DT: '20250120', MATURITY_DT: '20550120', COUPON_RATE: 0.0235, ISSUE_AMT: 1000.0e8, MARKET: '银行间', BOND_TERM: 30  },
  { AST_CD: '230210.IB',  AST_NM: '23国开10',                AST_TYPE: 'BOND',  AST_SUB_TYPE: 'POLICY',     ISR_ID: 'ISR000002', CCY: 'CNY', LIST_DT: '20231012', MATURITY_DT: '20331012', COUPON_RATE: 0.0258, ISSUE_AMT:  300.0e8, MARKET: '银行间', BOND_TERM: 10  },
  { AST_CD: '220215.IB',  AST_NM: '22国开15',                AST_TYPE: 'BOND',  AST_SUB_TYPE: 'POLICY',     ISR_ID: 'ISR000002', CCY: 'CNY', LIST_DT: '20220815', MATURITY_DT: '20320815', COUPON_RATE: 0.0298, ISSUE_AMT:  250.0e8, MARKET: '银行间', BOND_TERM: 10  },
  { AST_CD: '2480006.IB', AST_NM: '24工商银行MTN001',        AST_TYPE: 'BOND',  AST_SUB_TYPE: 'MTN',        ISR_ID: 'ISR000003', CCY: 'CNY', LIST_DT: '20240315', MATURITY_DT: '20290315', COUPON_RATE: 0.0285, ISSUE_AMT:   80.0e8, MARKET: '银行间', BOND_TERM:  5  },
  { AST_CD: '112311.SZ',  AST_NM: '24万科MTN003',            AST_TYPE: 'BOND',  AST_SUB_TYPE: 'ENTERPRISE', ISR_ID: 'ISR000005', CCY: 'CNY', LIST_DT: '20240620', MATURITY_DT: '20270620', COUPON_RATE: 0.0420, ISSUE_AMT:   30.0e8, MARKET: '深交所', BOND_TERM:  3  },
  { AST_CD: '600036.SH',  AST_NM: '招商银行',                AST_TYPE: 'STOCK', AST_SUB_TYPE: 'A_SHARE',    ISR_ID: 'ISR000007', CCY: 'CNY', LIST_DT: '20020409', MATURITY_DT: null,       COUPON_RATE: null,   ISSUE_AMT: null,    MARKET: '上交所', BOND_TERM: null },
  { AST_CD: '601318.SH',  AST_NM: '中国平安',                AST_TYPE: 'STOCK', AST_SUB_TYPE: 'A_SHARE',    ISR_ID: 'ISR000008', CCY: 'CNY', LIST_DT: '20070301', MATURITY_DT: null,       COUPON_RATE: null,   ISSUE_AMT: null,    MARKET: '上交所', BOND_TERM: null },
  { AST_CD: '510300.SH',  AST_NM: '沪深300ETF',              AST_TYPE: 'FUND',  AST_SUB_TYPE: 'ETF',        ISR_ID: null,        CCY: 'CNY', LIST_DT: '20120528', MATURITY_DT: null,       COUPON_RATE: null,   ISSUE_AMT: null,    MARKET: '上交所', BOND_TERM: null },
  { AST_CD: '511260.SH',  AST_NM: '十年国债ETF',             AST_TYPE: 'FUND',  AST_SUB_TYPE: 'ETF',        ISR_ID: null,        CCY: 'CNY', LIST_DT: '20170804', MATURITY_DT: null,       COUPON_RATE: null,   ISSUE_AMT: null,    MARKET: '上交所', BOND_TERM: null },
  { AST_CD: '127080.SZ',  AST_NM: '2024华能新能ABS001优先A', AST_TYPE: 'ABS',   AST_SUB_TYPE: 'ABS_SENIOR', ISR_ID: 'ISR000006', CCY: 'CNY', LIST_DT: '20240520', MATURITY_DT: '20290520', COUPON_RATE: 0.0345, ISSUE_AMT:   20.0e8, MARKET: '深交所', BOND_TERM:  5  },
  { AST_CD: '180401.IB',  AST_NM: '24农发绿色债01',          AST_TYPE: 'BOND',  AST_SUB_TYPE: 'POLICY',     ISR_ID: 'ISR000004', CCY: 'CNY', LIST_DT: '20240410', MATURITY_DT: '20340410', COUPON_RATE: 0.0272, ISSUE_AMT:  150.0e8, MARKET: '银行间', BOND_TERM: 10  }
];
astInfoSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_info.insertMany(astInfoSeed);
print('  dwd_ast_info: ' + db.dwd_ast_info.countDocuments());

/* ================ 2. dwd_ast_info_ch 中债估值 (12) ================ */
ZY_KEYS.recreate('dwd_ast_info_ch', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'BIZ_DT', 'VAL_NET_PRC'],
  properties: {
    AST_CD:      { bsonType: 'string' },
    BIZ_DT:      { bsonType: 'string' },
    VAL_NET_PRC: { bsonType: 'double' }
  }
}});
db.dwd_ast_info_ch.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true });

var chSeed = [
  { AST_CD: '019601.IB',  VAL_NET_PRC: 100.1230, VAL_FULL_PRC: 100.4528, VAL_YIELD: 0.01935, DURATION:  8.85, CONVEXITY:  92.4 },
  { AST_CD: '019735.IB',  VAL_NET_PRC:  99.6840, VAL_FULL_PRC:  99.9215, VAL_YIELD: 0.02368, DURATION: 18.62, CONVEXITY: 198.5 },
  { AST_CD: '230210.IB',  VAL_NET_PRC: 101.4520, VAL_FULL_PRC: 102.0845, VAL_YIELD: 0.02418, DURATION:  7.58, CONVEXITY:  73.8 },
  { AST_CD: '220215.IB',  VAL_NET_PRC: 102.8730, VAL_FULL_PRC: 103.5240, VAL_YIELD: 0.02635, DURATION:  6.42, CONVEXITY:  58.6 },
  { AST_CD: '2480006.IB', VAL_NET_PRC: 100.2580, VAL_FULL_PRC: 100.7910, VAL_YIELD: 0.02798, DURATION:  3.95, CONVEXITY:  18.4 },
  { AST_CD: '112311.SZ',  VAL_NET_PRC:  98.4520, VAL_FULL_PRC:  99.0150, VAL_YIELD: 0.04415, DURATION:  2.18, CONVEXITY:   6.8 },
  { AST_CD: '600036.SH',  VAL_NET_PRC:  43.5800, VAL_FULL_PRC:  43.5800, VAL_YIELD: null,    DURATION: null,  CONVEXITY: null  },
  { AST_CD: '601318.SH',  VAL_NET_PRC:  52.6400, VAL_FULL_PRC:  52.6400, VAL_YIELD: null,    DURATION: null,  CONVEXITY: null  },
  { AST_CD: '510300.SH',  VAL_NET_PRC:   4.1850, VAL_FULL_PRC:   4.1850, VAL_YIELD: null,    DURATION: null,  CONVEXITY: null  },
  { AST_CD: '511260.SH',  VAL_NET_PRC: 117.3200, VAL_FULL_PRC: 117.3200, VAL_YIELD: null,    DURATION: null,  CONVEXITY: null  },
  { AST_CD: '127080.SZ',  VAL_NET_PRC: 100.5680, VAL_FULL_PRC: 101.1530, VAL_YIELD: 0.03385, DURATION:  3.68, CONVEXITY:  15.2 },
  { AST_CD: '180401.IB',  VAL_NET_PRC: 101.0950, VAL_FULL_PRC: 101.6420, VAL_YIELD: 0.02685, DURATION:  8.12, CONVEXITY:  78.6 }
];
chSeed.forEach(function (d) {
  d.BIZ_DT = BIZ_DT;
  d.RATING_AGENCY = '中债估值中心';
  d.VAL_SRC = 'CH';
  Object.assign(d, aud());
});
db.dwd_ast_info_ch.insertMany(chSeed);
print('  dwd_ast_info_ch: ' + db.dwd_ast_info_ch.countDocuments());

/* ================ 3. dwd_ast_info_zg 中证估值 (8 仅债券/ABS) ================ */
ZY_KEYS.recreate('dwd_ast_info_zg', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'BIZ_DT', 'VAL_NET_PRC'],
  properties: {
    AST_CD:      { bsonType: 'string' },
    BIZ_DT:      { bsonType: 'string' },
    VAL_NET_PRC: { bsonType: 'double' }
  }
}});
db.dwd_ast_info_zg.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true });

var zgSeed = [
  { AST_CD: '019601.IB',  VAL_NET_PRC: 100.1085, VAL_FULL_PRC: 100.4380, VAL_YIELD: 0.01942, DURATION:  8.83, CONVEXITY:  92.1 },
  { AST_CD: '019735.IB',  VAL_NET_PRC:  99.7012, VAL_FULL_PRC:  99.9388, VAL_YIELD: 0.02362, DURATION: 18.65, CONVEXITY: 198.9 },
  { AST_CD: '230210.IB',  VAL_NET_PRC: 101.4685, VAL_FULL_PRC: 102.1010, VAL_YIELD: 0.02410, DURATION:  7.60, CONVEXITY:  73.9 },
  { AST_CD: '220215.IB',  VAL_NET_PRC: 102.8512, VAL_FULL_PRC: 103.5022, VAL_YIELD: 0.02642, DURATION:  6.41, CONVEXITY:  58.4 },
  { AST_CD: '2480006.IB', VAL_NET_PRC: 100.2415, VAL_FULL_PRC: 100.7745, VAL_YIELD: 0.02810, DURATION:  3.94, CONVEXITY:  18.3 },
  { AST_CD: '112311.SZ',  VAL_NET_PRC:  98.4085, VAL_FULL_PRC:  98.9715, VAL_YIELD: 0.04432, DURATION:  2.17, CONVEXITY:   6.7 },
  { AST_CD: '127080.SZ',  VAL_NET_PRC: 100.5320, VAL_FULL_PRC: 101.1170, VAL_YIELD: 0.03398, DURATION:  3.67, CONVEXITY:  15.1 },
  { AST_CD: '180401.IB',  VAL_NET_PRC: 101.0712, VAL_FULL_PRC: 101.6182, VAL_YIELD: 0.02692, DURATION:  8.10, CONVEXITY:  78.4 }
];
zgSeed.forEach(function (d) {
  d.BIZ_DT = BIZ_DT;
  d.RATING_AGENCY = '中证指数';
  d.VAL_SRC = 'ZG';
  Object.assign(d, aud());
});
db.dwd_ast_info_zg.insertMany(zgSeed);
print('  dwd_ast_info_zg: ' + db.dwd_ast_info_zg.countDocuments());

/* ================ 4. dwd_ast_yield_info 收益率信息 (12) ================ */
ZY_KEYS.recreate('dwd_ast_yield_info', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'BIZ_DT'],
  properties: { AST_CD: { bsonType: 'string' }, BIZ_DT: { bsonType: 'string' } }
}});
db.dwd_ast_yield_info.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true });

var yieldSeed = [
  { AST_CD: '019601.IB',  YTM: 0.01935, SPREAD:   0, BASE_RATE: 0.01935, DAILY_RTN:  0.00018, WEEK_RTN:  0.00125, MONTH_RTN:  0.00485, YTD_RTN:  0.01480, SETTLE_PRC: 100.1230 },
  { AST_CD: '019735.IB',  YTM: 0.02368, SPREAD:   0, BASE_RATE: 0.02368, DAILY_RTN:  0.00022, WEEK_RTN:  0.00148, MONTH_RTN:  0.00612, YTD_RTN:  0.01820, SETTLE_PRC:  99.6840 },
  { AST_CD: '230210.IB',  YTM: 0.02418, SPREAD:   8, BASE_RATE: 0.02338, DAILY_RTN:  0.00020, WEEK_RTN:  0.00135, MONTH_RTN:  0.00540, YTD_RTN:  0.01650, SETTLE_PRC: 101.4520 },
  { AST_CD: '220215.IB',  YTM: 0.02635, SPREAD:  12, BASE_RATE: 0.02515, DAILY_RTN:  0.00019, WEEK_RTN:  0.00128, MONTH_RTN:  0.00510, YTD_RTN:  0.01580, SETTLE_PRC: 102.8730 },
  { AST_CD: '2480006.IB', YTM: 0.02798, SPREAD:  60, BASE_RATE: 0.02198, DAILY_RTN:  0.00025, WEEK_RTN:  0.00168, MONTH_RTN:  0.00682, YTD_RTN:  0.02050, SETTLE_PRC: 100.2580 },
  { AST_CD: '112311.SZ',  YTM: 0.04415, SPREAD: 215, BASE_RATE: 0.02265, DAILY_RTN: -0.00038, WEEK_RTN: -0.00185, MONTH_RTN: -0.00420, YTD_RTN: -0.00650, SETTLE_PRC:  98.4520 },
  { AST_CD: '600036.SH',  YTM: null,    SPREAD: null, BASE_RATE: null,    DAILY_RTN:  0.00485, WEEK_RTN:  0.01820, MONTH_RTN:  0.04250, YTD_RTN:  0.08620, SETTLE_PRC:  43.5800 },
  { AST_CD: '601318.SH',  YTM: null,    SPREAD: null, BASE_RATE: null,    DAILY_RTN:  0.00328, WEEK_RTN:  0.01250, MONTH_RTN:  0.03180, YTD_RTN:  0.06480, SETTLE_PRC:  52.6400 },
  { AST_CD: '510300.SH',  YTM: null,    SPREAD: null, BASE_RATE: null,    DAILY_RTN:  0.00215, WEEK_RTN:  0.00865, MONTH_RTN:  0.02180, YTD_RTN:  0.04250, SETTLE_PRC:   4.1850 },
  { AST_CD: '511260.SH',  YTM: 0.02485, SPREAD:  10, BASE_RATE: 0.02385, DAILY_RTN:  0.00028, WEEK_RTN:  0.00152, MONTH_RTN:  0.00580, YTD_RTN:  0.01720, SETTLE_PRC: 117.3200 },
  { AST_CD: '127080.SZ',  YTM: 0.03385, SPREAD: 100, BASE_RATE: 0.02385, DAILY_RTN:  0.00023, WEEK_RTN:  0.00155, MONTH_RTN:  0.00610, YTD_RTN:  0.01890, SETTLE_PRC: 100.5680 },
  { AST_CD: '180401.IB',  YTM: 0.02685, SPREAD:  35, BASE_RATE: 0.02335, DAILY_RTN:  0.00021, WEEK_RTN:  0.00138, MONTH_RTN:  0.00558, YTD_RTN:  0.01710, SETTLE_PRC: 101.0950 }
];
yieldSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_yield_info.insertMany(yieldSeed);
print('  dwd_ast_yield_info: ' + db.dwd_ast_yield_info.countDocuments());

/* ================ 5. dwd_ast_cf_plan 现金流计划 (15) ================ */
ZY_KEYS.recreate('dwd_ast_cf_plan', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'CF_DT', 'CF_TYPE'],
  properties: { AST_CD: { bsonType: 'string' }, CF_DT: { bsonType: 'string' }, CF_TYPE: { bsonType: 'string' } }
}});
db.dwd_ast_cf_plan.createIndex({ AST_CD: 1, CF_DT: 1, CF_TYPE: 1 });

var cfPlanSeed = [
  // 25国债03（年付息，10年期）
  { AST_CD: '019601.IB',  CF_DT: '20260115', CF_TYPE: 'COUPON',           CF_AMT:  9.75e8,  CCY: 'CNY', NOTE: '第1期付息' },
  { AST_CD: '019601.IB',  CF_DT: '20270115', CF_TYPE: 'COUPON',           CF_AMT:  9.75e8,  CCY: 'CNY', NOTE: '第2期付息' },
  { AST_CD: '019601.IB',  CF_DT: '20350115', CF_TYPE: 'COUPON_PRINCIPAL', CF_AMT: 509.75e8, CCY: 'CNY', NOTE: '到期还本付息' },
  // 23国开10
  { AST_CD: '230210.IB',  CF_DT: '20251012', CF_TYPE: 'COUPON',           CF_AMT:  7.74e8,  CCY: 'CNY', NOTE: '第3期付息' },
  { AST_CD: '230210.IB',  CF_DT: '20261012', CF_TYPE: 'COUPON',           CF_AMT:  7.74e8,  CCY: 'CNY', NOTE: '第4期付息' },
  { AST_CD: '230210.IB',  CF_DT: '20331012', CF_TYPE: 'COUPON_PRINCIPAL', CF_AMT: 307.74e8, CCY: 'CNY', NOTE: '到期还本付息' },
  // 24工商银行MTN001（半年付息）
  { AST_CD: '2480006.IB', CF_DT: '20250915', CF_TYPE: 'COUPON',           CF_AMT:  1.140e8, CCY: 'CNY', NOTE: '第3期付息' },
  { AST_CD: '2480006.IB', CF_DT: '20260315', CF_TYPE: 'COUPON',           CF_AMT:  1.140e8, CCY: 'CNY', NOTE: '第4期付息' },
  { AST_CD: '2480006.IB', CF_DT: '20290315', CF_TYPE: 'COUPON_PRINCIPAL', CF_AMT: 81.140e8, CCY: 'CNY', NOTE: '到期还本付息' },
  // 24万科MTN003
  { AST_CD: '112311.SZ',  CF_DT: '20250620', CF_TYPE: 'COUPON',           CF_AMT:  1.260e8, CCY: 'CNY', NOTE: '第1期付息' },
  { AST_CD: '112311.SZ',  CF_DT: '20270620', CF_TYPE: 'COUPON_PRINCIPAL', CF_AMT: 31.260e8, CCY: 'CNY', NOTE: '到期还本付息' },
  // 华能ABS（按季度过手）
  { AST_CD: '127080.SZ',  CF_DT: '20250520', CF_TYPE: 'COUPON',           CF_AMT:  0.690e8, CCY: 'CNY', NOTE: '第4期付息' },
  { AST_CD: '127080.SZ',  CF_DT: '20290520', CF_TYPE: 'COUPON_PRINCIPAL', CF_AMT: 20.690e8, CCY: 'CNY', NOTE: '到期还本付息' },
  // 24农发绿色债01
  { AST_CD: '180401.IB',  CF_DT: '20250410', CF_TYPE: 'COUPON',           CF_AMT:  4.080e8, CCY: 'CNY', NOTE: '第1期付息' },
  { AST_CD: '180401.IB',  CF_DT: '20340410', CF_TYPE: 'COUPON_PRINCIPAL', CF_AMT: 154.080e8,CCY: 'CNY', NOTE: '到期还本付息' }
];
cfPlanSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_cf_plan.insertMany(cfPlanSeed);
print('  dwd_ast_cf_plan: ' + db.dwd_ast_cf_plan.countDocuments());

/* ================ 6. dwd_ast_pledge 质押状态 (8) ================ */
ZY_KEYS.recreate('dwd_ast_pledge', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'BIZ_DT'],
  properties: { AST_CD: { bsonType: 'string' }, BIZ_DT: { bsonType: 'string' } }
}});
db.dwd_ast_pledge.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true });

var pledgeSeed = [
  { AST_CD: '019601.IB',  PLEDGE_FLAG: 'Y', PLEDGE_RATIO: 0.95, PLEDGE_INST: '中央国债登记结算公司', PLEDGE_NOTE: '质押式回购合格券', PLEDGE_STD: 'STD' },
  { AST_CD: '019735.IB',  PLEDGE_FLAG: 'Y', PLEDGE_RATIO: 0.93, PLEDGE_INST: '中央国债登记结算公司', PLEDGE_NOTE: '超长期特别国债',     PLEDGE_STD: 'STD' },
  { AST_CD: '230210.IB',  PLEDGE_FLAG: 'Y', PLEDGE_RATIO: 0.90, PLEDGE_INST: '中央国债登记结算公司', PLEDGE_NOTE: '政策性银行债',       PLEDGE_STD: 'STD' },
  { AST_CD: '220215.IB',  PLEDGE_FLAG: 'Y', PLEDGE_RATIO: 0.90, PLEDGE_INST: '中央国债登记结算公司', PLEDGE_NOTE: '政策性银行债',       PLEDGE_STD: 'STD' },
  { AST_CD: '2480006.IB', PLEDGE_FLAG: 'Y', PLEDGE_RATIO: 0.80, PLEDGE_INST: '上海清算所',           PLEDGE_NOTE: '商业银行金融债',     PLEDGE_STD: 'STD' },
  { AST_CD: '180401.IB',  PLEDGE_FLAG: 'Y', PLEDGE_RATIO: 0.88, PLEDGE_INST: '中央国债登记结算公司', PLEDGE_NOTE: '政策性银行绿色债',   PLEDGE_STD: 'STD' },
  { AST_CD: '112311.SZ',  PLEDGE_FLAG: 'N', PLEDGE_RATIO: 0.00, PLEDGE_INST: null,                   PLEDGE_NOTE: '主体评级下调暂不接受质押', PLEDGE_STD: 'NON' },
  { AST_CD: '127080.SZ',  PLEDGE_FLAG: 'Y', PLEDGE_RATIO: 0.65, PLEDGE_INST: '中国证券登记结算公司', PLEDGE_NOTE: '交易所ABS优先档',   PLEDGE_STD: 'STD' }
];
pledgeSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_pledge.insertMany(pledgeSeed);
print('  dwd_ast_pledge: ' + db.dwd_ast_pledge.countDocuments());

/* ================ 7. dwd_ast_flow_trade 交易流水 (15) ================ */
ZY_KEYS.recreate('dwd_ast_flow_trade', { $jsonSchema: {
  bsonType: 'object',
  required: ['TRADE_ID', 'AST_CD', 'TRADE_DT', 'TRADE_DIR'],
  properties: {
    TRADE_ID:  { bsonType: 'string' },
    AST_CD:    { bsonType: 'string' },
    TRADE_DT:  { bsonType: 'string' },
    TRADE_DIR: { bsonType: 'string', description: 'BUY/SELL' }
  }
}});
db.dwd_ast_flow_trade.createIndex({ TRADE_ID: 1 }, { unique: true });
db.dwd_ast_flow_trade.createIndex({ AST_CD: 1, TRADE_DT: 1 });

var tradeSeed = [
  { TRADE_ID: 'T20250318001', AST_CD: '019601.IB',  TRADE_DT: '20250318', TRADE_DIR: 'BUY',  TRADE_AMT:  50.0e6, TRADE_PRC: 100.0850, TRADE_QTY:  500000, CNTP_ID: 'CNTP00004', PORT_ID: 'PORT002', SETTLE_DT: '20250319' },
  { TRADE_ID: 'T20250318002', AST_CD: '230210.IB',  TRADE_DT: '20250318', TRADE_DIR: 'BUY',  TRADE_AMT:  30.0e6, TRADE_PRC: 101.4280, TRADE_QTY:  300000, CNTP_ID: 'CNTP00001', PORT_ID: 'PORT002', SETTLE_DT: '20250319' },
  { TRADE_ID: 'T20250319001', AST_CD: '019735.IB',  TRADE_DT: '20250319', TRADE_DIR: 'BUY',  TRADE_AMT: 100.0e6, TRADE_PRC:  99.6520, TRADE_QTY: 1000000, CNTP_ID: 'CNTP00004', PORT_ID: 'PORT001', SETTLE_DT: '20250320' },
  { TRADE_ID: 'T20250319002', AST_CD: '2480006.IB', TRADE_DT: '20250319', TRADE_DIR: 'BUY',  TRADE_AMT:  20.0e6, TRADE_PRC: 100.2210, TRADE_QTY:  200000, CNTP_ID: 'CNTP00005', PORT_ID: 'PORT001', SETTLE_DT: '20250320' },
  { TRADE_ID: 'T20250320001', AST_CD: '600036.SH',  TRADE_DT: '20250320', TRADE_DIR: 'BUY',  TRADE_AMT:   8.7e6, TRADE_PRC:  43.4800, TRADE_QTY:  200000, CNTP_ID: 'CNTP00003', PORT_ID: 'PORT003', SETTLE_DT: '20250322' },
  { TRADE_ID: 'T20250320002', AST_CD: '601318.SH',  TRADE_DT: '20250320', TRADE_DIR: 'BUY',  TRADE_AMT:  10.5e6, TRADE_PRC:  52.5200, TRADE_QTY:  200000, CNTP_ID: 'CNTP00003', PORT_ID: 'PORT003', SETTLE_DT: '20250322' },
  { TRADE_ID: 'T20250320003', AST_CD: '510300.SH',  TRADE_DT: '20250320', TRADE_DIR: 'BUY',  TRADE_AMT:   4.2e6, TRADE_PRC:   4.1820, TRADE_QTY: 1000000, CNTP_ID: 'CNTP00001', PORT_ID: 'PORT005', SETTLE_DT: '20250322' },
  { TRADE_ID: 'T20250321001', AST_CD: '220215.IB',  TRADE_DT: '20250321', TRADE_DIR: 'SELL', TRADE_AMT:  20.0e6, TRADE_PRC: 102.9120, TRADE_QTY:  200000, CNTP_ID: 'CNTP00002', PORT_ID: 'PORT002', SETTLE_DT: '20250324' },
  { TRADE_ID: 'T20250321002', AST_CD: '511260.SH',  TRADE_DT: '20250321', TRADE_DIR: 'BUY',  TRADE_AMT: 117.3e6, TRADE_PRC: 117.3000, TRADE_QTY: 1000000, CNTP_ID: 'CNTP00001', PORT_ID: 'PORT004', SETTLE_DT: '20250322' },
  { TRADE_ID: 'T20250324001', AST_CD: '180401.IB',  TRADE_DT: '20250324', TRADE_DIR: 'BUY',  TRADE_AMT:  50.0e6, TRADE_PRC: 101.0680, TRADE_QTY:  500000, CNTP_ID: 'CNTP00004', PORT_ID: 'PORT001', SETTLE_DT: '20250325' },
  { TRADE_ID: 'T20250324002', AST_CD: '127080.SZ',  TRADE_DT: '20250324', TRADE_DIR: 'BUY',  TRADE_AMT:  20.0e6, TRADE_PRC: 100.5320, TRADE_QTY:  200000, CNTP_ID: 'CNTP00002', PORT_ID: 'PORT003', SETTLE_DT: '20250325' },
  { TRADE_ID: 'T20250324003', AST_CD: '019601.IB',  TRADE_DT: '20250324', TRADE_DIR: 'SELL', TRADE_AMT:  10.0e6, TRADE_PRC: 100.1380, TRADE_QTY:  100000, CNTP_ID: 'CNTP00005', PORT_ID: 'PORT002', SETTLE_DT: '20250325' },
  { TRADE_ID: 'T20250324004', AST_CD: '112311.SZ',  TRADE_DT: '20250324', TRADE_DIR: 'SELL', TRADE_AMT:  15.0e6, TRADE_PRC:  98.3500, TRADE_QTY:  150000, CNTP_ID: 'CNTP00003', PORT_ID: 'PORT003', SETTLE_DT: '20250326' },
  { TRADE_ID: 'T20250324005', AST_CD: '230210.IB',  TRADE_DT: '20250324', TRADE_DIR: 'BUY',  TRADE_AMT:  20.0e6, TRADE_PRC: 101.4480, TRADE_QTY:  200000, CNTP_ID: 'CNTP00001', PORT_ID: 'PORT001', SETTLE_DT: '20250325' },
  { TRADE_ID: 'T20250324006', AST_CD: '600036.SH',  TRADE_DT: '20250324', TRADE_DIR: 'SELL', TRADE_AMT:   4.4e6, TRADE_PRC:  43.5800, TRADE_QTY:  100000, CNTP_ID: 'CNTP00003', PORT_ID: 'PORT003', SETTLE_DT: '20250326' }
];
tradeSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; d.CCY = 'CNY'; Object.assign(d, aud()); });
db.dwd_ast_flow_trade.insertMany(tradeSeed);
print('  dwd_ast_flow_trade: ' + db.dwd_ast_flow_trade.countDocuments());

/* ================ 8. dwd_ast_rating 信用评级 (10) ================ */
ZY_KEYS.recreate('dwd_ast_rating', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'RATING_AGENCY', 'RATING_DT'],
  properties: {
    AST_CD:        { bsonType: 'string' },
    RATING_AGENCY: { bsonType: 'string' },
    RATING_DT:     { bsonType: 'string' }
  }
}});
db.dwd_ast_rating.createIndex({ AST_CD: 1, RATING_AGENCY: 1, RATING_DT: 1 }, { unique: true });

var ratingSeed = [
  { AST_CD: '019601.IB',  RATING_AGENCY: '中诚信国际', BOND_RATING: 'AAA', ISR_RATING: 'AAA', RATING_DT: '20250108', OUTLOOK: '稳定', RATING_TYPE: '初评' },
  { AST_CD: '019735.IB',  RATING_AGENCY: '中诚信国际', BOND_RATING: 'AAA', ISR_RATING: 'AAA', RATING_DT: '20250115', OUTLOOK: '稳定', RATING_TYPE: '初评' },
  { AST_CD: '230210.IB',  RATING_AGENCY: '联合资信',   BOND_RATING: 'AAA', ISR_RATING: 'AAA', RATING_DT: '20240620', OUTLOOK: '稳定', RATING_TYPE: '跟踪' },
  { AST_CD: '220215.IB',  RATING_AGENCY: '联合资信',   BOND_RATING: 'AAA', ISR_RATING: 'AAA', RATING_DT: '20240620', OUTLOOK: '稳定', RATING_TYPE: '跟踪' },
  { AST_CD: '2480006.IB', RATING_AGENCY: '中诚信国际', BOND_RATING: 'AAA', ISR_RATING: 'AAA', RATING_DT: '20240220', OUTLOOK: '稳定', RATING_TYPE: '初评' },
  { AST_CD: '2480006.IB', RATING_AGENCY: '联合资信',   BOND_RATING: 'AAA', ISR_RATING: 'AAA', RATING_DT: '20240228', OUTLOOK: '稳定', RATING_TYPE: '初评' },
  { AST_CD: '112311.SZ',  RATING_AGENCY: '大公国际',   BOND_RATING: 'AA',  ISR_RATING: 'AA+', RATING_DT: '20240522', OUTLOOK: '负面', RATING_TYPE: '初评' },
  { AST_CD: '112311.SZ',  RATING_AGENCY: '中诚信国际', BOND_RATING: 'AA',  ISR_RATING: 'AA+', RATING_DT: '20250215', OUTLOOK: '负面', RATING_TYPE: '下调' },
  { AST_CD: '127080.SZ',  RATING_AGENCY: '东方金诚',   BOND_RATING: 'AAA', ISR_RATING: 'AA+', RATING_DT: '20240425', OUTLOOK: '稳定', RATING_TYPE: '初评' },
  { AST_CD: '180401.IB',  RATING_AGENCY: '中诚信国际', BOND_RATING: 'AAA', ISR_RATING: 'AAA', RATING_DT: '20240315', OUTLOOK: '稳定', RATING_TYPE: '初评' }
];
ratingSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_rating.insertMany(ratingSeed);
print('  dwd_ast_rating: ' + db.dwd_ast_rating.countDocuments());

/* ================ 9. dwd_ast_guarantor 担保信息 (5) ================ */
ZY_KEYS.recreate('dwd_ast_guarantor', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'GUAR_NM', 'GUAR_TYPE'],
  properties: {
    AST_CD:    { bsonType: 'string' },
    GUAR_NM:   { bsonType: 'string' },
    GUAR_TYPE: { bsonType: 'string' }
  }
}});
db.dwd_ast_guarantor.createIndex({ AST_CD: 1, GUAR_NM: 1 }, { unique: true });

var guarSeed = [
  { AST_CD: '112311.SZ',  GUAR_NM: '万科企业股份有限公司',         GUAR_TYPE: '母公司全额无条件不可撤销连带责任担保', GUAR_AMT: 30.0e8, GUAR_RATIO: 1.00, EFF_DT: '20240620', EXP_DT: '20270620' },
  { AST_CD: '127080.SZ',  GUAR_NM: '中国华能集团有限公司',         GUAR_TYPE: '差额支付承诺',                         GUAR_AMT: 20.0e8, GUAR_RATIO: 1.00, EFF_DT: '20240520', EXP_DT: '20290520' },
  { AST_CD: '127080.SZ',  GUAR_NM: '华能新能源股份有限公司',       GUAR_TYPE: '原始权益人差额补足',                   GUAR_AMT:  6.0e8, GUAR_RATIO: 0.30, EFF_DT: '20240520', EXP_DT: '20290520' },
  { AST_CD: '2480006.IB', GUAR_NM: '中央汇金投资有限责任公司',     GUAR_TYPE: '隐性政府支持',                         GUAR_AMT:  null,   GUAR_RATIO: null, EFF_DT: '20240315', EXP_DT: '20290315' },
  { AST_CD: '180401.IB',  GUAR_NM: '中华人民共和国财政部',         GUAR_TYPE: '政策性金融债隐性主权信用',             GUAR_AMT:  null,   GUAR_RATIO: null, EFF_DT: '20240410', EXP_DT: '20340410' }
];
guarSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_guarantor.insertMany(guarSeed);
print('  dwd_ast_guarantor: ' + db.dwd_ast_guarantor.countDocuments());

/* ================ 10. dwd_ast_clause 债券条款 (8) ================ */
ZY_KEYS.recreate('dwd_ast_clause', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'CLAUSE_TYPE', 'EFF_DT'],
  properties: {
    AST_CD:      { bsonType: 'string' },
    CLAUSE_TYPE: { bsonType: 'string', description: 'PUT/CALL/RATE_ADJ' },
    EFF_DT:      { bsonType: 'string' }
  }
}});
db.dwd_ast_clause.createIndex({ AST_CD: 1, CLAUSE_TYPE: 1, EFF_DT: 1 });

var clauseSeed = [
  { AST_CD: '2480006.IB', CLAUSE_TYPE: 'CALL',     CLAUSE_NM: '发行人赎回选择权', TRIGGER:    '存续期第3年末',           EFF_DT: '20270315', EXE_PRC: 100.00, NOTE: '次级债强制赎回安排' },
  { AST_CD: '2480006.IB', CLAUSE_TYPE: 'RATE_ADJ', CLAUSE_NM: '票面利率调整选择权', TRIGGER:  '不赎回则上调300BP',         EFF_DT: '20270315', EXE_PRC: null,   NOTE: '与赎回联动' },
  { AST_CD: '112311.SZ',  CLAUSE_TYPE: 'PUT',      CLAUSE_NM: '投资者回售选择权',   TRIGGER:  '存续期第2年末',             EFF_DT: '20260620', EXE_PRC: 100.00, NOTE: '应对主体评级下调' },
  { AST_CD: '112311.SZ',  CLAUSE_TYPE: 'CROSS_DEF',CLAUSE_NM: '交叉违约条款',       TRIGGER:  '其他债务违约金额>5亿',      EFF_DT: '20240620', EXE_PRC: null,   NOTE: '加速到期' },
  { AST_CD: '127080.SZ',  CLAUSE_TYPE: 'CALL',     CLAUSE_NM: '清算赎回',           TRIGGER:  '余额低于10%清算',           EFF_DT: '20280520', EXE_PRC: 100.00, NOTE: 'ABS 清算条款' },
  { AST_CD: '230210.IB',  CLAUSE_TYPE: 'NONE',     CLAUSE_NM: '无含权',             TRIGGER:  '到期一次性还本付息',        EFF_DT: '20231012', EXE_PRC: null,   NOTE: '标准固息债' },
  { AST_CD: '180401.IB',  CLAUSE_TYPE: 'GREEN_BIND',CLAUSE_NM: '绿色专项用途',      TRIGGER:  '募集资金80%以上用于绿色项目',EFF_DT: '20240410', EXE_PRC: null,   NOTE: '存续期需披露资金用途' },
  { AST_CD: '019735.IB',  CLAUSE_TYPE: 'NONE',     CLAUSE_NM: '无含权',             TRIGGER:  '到期一次性还本付息',        EFF_DT: '20250120', EXE_PRC: null,   NOTE: '超长期特别国债' }
];
clauseSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_clause.insertMany(clauseSeed);
print('  dwd_ast_clause: ' + db.dwd_ast_clause.countDocuments());

/* ================ 11. dwd_ast_holder 持有人信息 (10) ================ */
ZY_KEYS.recreate('dwd_ast_holder', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'HOLDER_NM', 'BIZ_DT'],
  properties: {
    AST_CD:    { bsonType: 'string' },
    HOLDER_NM: { bsonType: 'string' },
    BIZ_DT:    { bsonType: 'string' }
  }
}});
db.dwd_ast_holder.createIndex({ AST_CD: 1, HOLDER_NM: 1, BIZ_DT: 1 }, { unique: true });

var holderSeed = [
  { AST_CD: '019601.IB',  HOLDER_NM: '中国工商银行股份有限公司', HOLDER_TYPE: 'BANK',      HOLD_FACE_AMT: 80.0e8,  HOLD_RATIO: 0.1600, RANK: 1 },
  { AST_CD: '019601.IB',  HOLDER_NM: '中国农业银行股份有限公司', HOLDER_TYPE: 'BANK',      HOLD_FACE_AMT: 65.0e8,  HOLD_RATIO: 0.1300, RANK: 2 },
  { AST_CD: '019601.IB',  HOLDER_NM: '中国人寿保险股份有限公司', HOLDER_TYPE: 'INSURANCE', HOLD_FACE_AMT: 45.0e8,  HOLD_RATIO: 0.0900, RANK: 3 },
  { AST_CD: '230210.IB',  HOLDER_NM: '中国工商银行股份有限公司', HOLDER_TYPE: 'BANK',      HOLD_FACE_AMT: 50.0e8,  HOLD_RATIO: 0.1667, RANK: 1 },
  { AST_CD: '230210.IB',  HOLDER_NM: '中国建设银行股份有限公司', HOLDER_TYPE: 'BANK',      HOLD_FACE_AMT: 40.0e8,  HOLD_RATIO: 0.1333, RANK: 2 },
  { AST_CD: '2480006.IB', HOLDER_NM: '兴业银行股份有限公司',     HOLDER_TYPE: 'BANK',      HOLD_FACE_AMT:  8.5e8,  HOLD_RATIO: 0.1063, RANK: 1 },
  { AST_CD: '2480006.IB', HOLDER_NM: '太平洋人寿保险股份有限公司',HOLDER_TYPE: 'INSURANCE', HOLD_FACE_AMT:  6.0e8,  HOLD_RATIO: 0.0750, RANK: 2 },
  { AST_CD: '112311.SZ',  HOLDER_NM: '招商财富资产管理公司',     HOLDER_TYPE: 'AMC',       HOLD_FACE_AMT:  4.5e8,  HOLD_RATIO: 0.1500, RANK: 1 },
  { AST_CD: '127080.SZ',  HOLDER_NM: '稳健配置一号',             HOLDER_TYPE: 'PORTFOLIO', HOLD_FACE_AMT:  2.0e8,  HOLD_RATIO: 0.1000, RANK: 1 },
  { AST_CD: '180401.IB',  HOLDER_NM: '全国社保基金理事会',       HOLDER_TYPE: 'SSF',       HOLD_FACE_AMT: 25.0e8,  HOLD_RATIO: 0.1667, RANK: 1 }
];
holderSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_holder.insertMany(holderSeed);
print('  dwd_ast_holder: ' + db.dwd_ast_holder.countDocuments());

/* ================ 12. dwd_ast_event 资产事件 (8) ================ */
ZY_KEYS.recreate('dwd_ast_event', { $jsonSchema: {
  bsonType: 'object',
  required: ['AST_CD', 'EVENT_TYPE', 'EVENT_DT'],
  properties: {
    AST_CD:     { bsonType: 'string' },
    EVENT_TYPE: { bsonType: 'string', description: 'COUPON/MATURITY/RATING_CHG/CALL/PUT/DEFAULT' },
    EVENT_DT:   { bsonType: 'string' }
  }
}});
db.dwd_ast_event.createIndex({ AST_CD: 1, EVENT_DT: 1, EVENT_TYPE: 1 });

var eventSeed = [
  { AST_CD: '019601.IB',  EVENT_TYPE: 'ISSUE',      EVENT_DT: '20250108', EVENT_DESC: '簿记建档完成，发行规模500亿元，中标利率1.95%', IMPACT: 'NEUTRAL' },
  { AST_CD: '019601.IB',  EVENT_TYPE: 'COUPON',     EVENT_DT: '20260115', EVENT_DESC: '第1期付息9.75亿元',                              IMPACT: 'NEUTRAL' },
  { AST_CD: '019735.IB',  EVENT_TYPE: 'ISSUE',      EVENT_DT: '20250115', EVENT_DESC: '超长期特别国债首发，规模1000亿元',               IMPACT: 'POSITIVE' },
  { AST_CD: '112311.SZ',  EVENT_TYPE: 'RATING_CHG', EVENT_DT: '20250215', EVENT_DESC: '中诚信国际下调主体评级展望由稳定至负面',          IMPACT: 'NEGATIVE' },
  { AST_CD: '112311.SZ',  EVENT_TYPE: 'PUT_DCLR',   EVENT_DT: '20250320', EVENT_DESC: '触发投资者回售公告，回售期2026-04-20至2026-05-19',IMPACT: 'NEGATIVE' },
  { AST_CD: '2480006.IB', EVENT_TYPE: 'COUPON',     EVENT_DT: '20250315', EVENT_DESC: '第2期付息1.14亿元',                              IMPACT: 'NEUTRAL' },
  { AST_CD: '127080.SZ',  EVENT_TYPE: 'POOL_REPORT',EVENT_DT: '20250228', EVENT_DESC: '资产池逾期率0.32%，风险准备金覆盖率280%',        IMPACT: 'POSITIVE' },
  { AST_CD: '180401.IB',  EVENT_TYPE: 'GREEN_DCLR', EVENT_DT: '20250120', EVENT_DESC: '披露募集资金投放：风电项目120亿、光伏项目30亿', IMPACT: 'POSITIVE' }
];
eventSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ast_event.insertMany(eventSeed);
print('  dwd_ast_event: ' + db.dwd_ast_event.countDocuments());

print('--- [01] asset domain done ---');
