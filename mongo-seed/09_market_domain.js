load('_keys.js');
/**
 * 行情域 dwd_mkt_* — 25 张表
 * 多日时间序列数据：20250318, 20250319, 20250320, 20250321, 20250324
 */
print('--- [09] market domain start ---');

var BIZ_DT  = ZY_KEYS.BIZ_DT;
var ASTS    = ZY_KEYS.AST_CDS;
var INDEXES = ZY_KEYS.INDEX_CDS;
var CURVES  = ZY_KEYS.CURVE_IDS;
var aud     = ZY_KEYS.audit;

// 连续5个交易日
var TRADE_DAYS = ['20250318', '20250319', '20250320', '20250321', '20250324'];

// 8只债券用于行情
var BONDS = ['019601.IB', '019735.IB', '230210.IB', '220215.IB', '2480006.IB', '112311.SZ', '127080.SZ', '180401.IB'];
var BOND_BASE = [99.72, 98.85, 101.35, 102.18, 100.52, 97.80, 100.10, 100.25];
var BOND_YTM  = [0.0195, 0.0225, 0.0210, 0.0235, 0.0268, 0.0385, 0.0290, 0.0245];
var BOND_DUR  = [9.5, 12.3, 7.8, 8.5, 3.2, 2.8, 1.5, 5.6];

/* ============ 1. dwd_mkt_bond 债券行情 (40条: 8只*5天) ============ */
var col1 = ZY_KEYS.recreate('dwd_mkt_bond');
col1.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true });
var bondMktSeed = [];
BONDS.forEach(function (cd, i) {
  TRADE_DAYS.forEach(function (dt, k) {
    var drift = (k - 2) * 0.03;
    bondMktSeed.push({
      AST_CD: cd, BIZ_DT: dt,
      OPEN_PRC: +(BOND_BASE[i] + drift - 0.10).toFixed(4),
      HIGH_PRC: +(BOND_BASE[i] + drift + 0.15).toFixed(4),
      LOW_PRC:  +(BOND_BASE[i] + drift - 0.20).toFixed(4),
      CLOSE_PRC:+(BOND_BASE[i] + drift).toFixed(4),
      VOL: (800000 + i * 200000 + k * 50000),
      AMT: +((800000 + i * 200000 + k * 50000) * (BOND_BASE[i] + drift)).toFixed(0) * 1,
      YTM: +(BOND_YTM[i] - drift * 0.0002).toFixed(6),
      CHG_BP: +((k === 0 ? 0 : (drift > 0 ? -1 : 1) * (1 + Math.abs(k - 2)))).toFixed(1),
      DURATION: BOND_DUR[i]
    });
  });
});
bondMktSeed.forEach(function (d) { Object.assign(d, aud()); });
col1.insertMany(bondMktSeed);
print('  dwd_mkt_bond: ' + col1.countDocuments());

/* ============ 2. dwd_mkt_equity 股票行情 (10条: 2只*5天) ============ */
var col2 = ZY_KEYS.recreate('dwd_mkt_equity');
col2.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true });
var EQ_CDS = ['600036.SH', '601318.SH'];
var EQ_BASE = [38.50, 52.80];
var eqSeed = [];
EQ_CDS.forEach(function (cd, i) {
  TRADE_DAYS.forEach(function (dt, k) {
    var drift = (k - 2) * 0.25;
    eqSeed.push({
      AST_CD: cd, BIZ_DT: dt,
      OPEN_PRC: +(EQ_BASE[i] + drift - 0.15).toFixed(2),
      HIGH_PRC: +(EQ_BASE[i] + drift + 0.35).toFixed(2),
      LOW_PRC:  +(EQ_BASE[i] + drift - 0.30).toFixed(2),
      CLOSE_PRC:+(EQ_BASE[i] + drift).toFixed(2),
      VOL: (12000000 + i * 3000000 + k * 500000),
      AMT: +((12000000 + i * 3000000) * (EQ_BASE[i] + drift)).toFixed(0) * 1,
      PE_TTM: +(6.5 + i * 2.5 + k * 0.05).toFixed(2),
      PB_LF: +(0.85 + i * 0.35 + k * 0.01).toFixed(2)
    });
  });
});
eqSeed.forEach(function (d) { Object.assign(d, aud()); });
col2.insertMany(eqSeed);
print('  dwd_mkt_equity: ' + col2.countDocuments());

/* ============ 3. dwd_mkt_fund 基金行情 (10条: 2只ETF*5天) ============ */
var col3 = ZY_KEYS.recreate('dwd_mkt_fund');
col3.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true });
var FUND_CDS = ['510300.SH', '511260.SH'];
var FUND_NAV = [4.1520, 1.0285];
var fundSeed = [];
FUND_CDS.forEach(function (cd, i) {
  TRADE_DAYS.forEach(function (dt, k) {
    var navDrift = (k - 2) * (i === 0 ? 0.008 : 0.0003);
    fundSeed.push({
      AST_CD: cd, BIZ_DT: dt,
      NAV: +(FUND_NAV[i] + navDrift).toFixed(4),
      ACC_NAV: +(FUND_NAV[i] + navDrift + (i === 0 ? 0.85 : 0.12)).toFixed(4),
      DISCOUNT_RATE: +(i === 0 ? -0.0012 + k * 0.0002 : 0.0001 + k * 0.00005).toFixed(6),
      VOL: (5000000 + i * 2000000 + k * 100000),
      AMT: +((5000000 + i * 2000000) * (FUND_NAV[i] + navDrift)).toFixed(0) * 1
    });
  });
});
fundSeed.forEach(function (d) { Object.assign(d, aud()); });
col3.insertMany(fundSeed);
print('  dwd_mkt_fund: ' + col3.countDocuments());

/* ============ 4. dwd_mkt_index 指数行情 (25条: 5只*5天) ============ */
var col4 = ZY_KEYS.recreate('dwd_mkt_index');
col4.createIndex({ INDEX_CD: 1, BIZ_DT: 1 }, { unique: true });
var IDX_BASE = [3580.25, 5120.80, 2050.15, 2680.50, 215.38];
var idxSeed = [];
INDEXES.forEach(function (idx, i) {
  TRADE_DAYS.forEach(function (dt, k) {
    var drift = (k - 2) * (15 + i * 5);
    idxSeed.push({
      INDEX_CD: idx, BIZ_DT: dt,
      OPEN_VAL: +(IDX_BASE[i] + drift - 8).toFixed(2),
      HIGH_VAL: +(IDX_BASE[i] + drift + 12).toFixed(2),
      LOW_VAL:  +(IDX_BASE[i] + drift - 15).toFixed(2),
      CLOSE_VAL:+(IDX_BASE[i] + drift).toFixed(2),
      VOL: 2.5e10 + i * 5e9,
      AMT: 3.2e11 + i * 8e10,
      CHG_PCT: +((drift / IDX_BASE[i]) * 100).toFixed(4)
    });
  });
});
idxSeed.forEach(function (d) { Object.assign(d, aud()); });
col4.insertMany(idxSeed);
print('  dwd_mkt_index: ' + col4.countDocuments());

/* ============ 5. dwd_mkt_curve 收益率曲线 (25条: 5曲线*5天) ============ */
var col5 = ZY_KEYS.recreate('dwd_mkt_curve');
col5.createIndex({ CURVE_ID: 1, BIZ_DT: 1 }, { unique: true });
var CURVE_BASE = { CGB: 0.0155, CDB: 0.0190, AAA_MTN: 0.0250, AAAm_NCD: 0.0220, SHIBOR: 0.0195 };
var curveSeed = [];
CURVES.forEach(function (cid) {
  TRADE_DAYS.forEach(function (dt, k) {
    var shift = (k - 2) * 0.0002;
    curveSeed.push({
      CURVE_ID: cid, BIZ_DT: dt,
      Y_3M: +(CURVE_BASE[cid] - 0.0040 + shift).toFixed(6),
      Y_6M: +(CURVE_BASE[cid] - 0.0025 + shift).toFixed(6),
      Y_1Y: +(CURVE_BASE[cid] - 0.0010 + shift).toFixed(6),
      Y_2Y: +(CURVE_BASE[cid] + shift).toFixed(6),
      Y_3Y: +(CURVE_BASE[cid] + 0.0015 + shift).toFixed(6),
      Y_5Y: +(CURVE_BASE[cid] + 0.0035 + shift).toFixed(6),
      Y_7Y: +(CURVE_BASE[cid] + 0.0050 + shift).toFixed(6),
      Y_10Y: +(CURVE_BASE[cid] + 0.0065 + shift).toFixed(6),
      Y_15Y: +(CURVE_BASE[cid] + 0.0078 + shift).toFixed(6),
      Y_20Y: +(CURVE_BASE[cid] + 0.0085 + shift).toFixed(6),
      Y_30Y: +(CURVE_BASE[cid] + 0.0092 + shift).toFixed(6)
    });
  });
});
curveSeed.forEach(function (d) { Object.assign(d, aud()); });
col5.insertMany(curveSeed);
print('  dwd_mkt_curve: ' + col5.countDocuments());

/* ============ 6. dwd_mkt_repo_rate 回购利率 (10条: 5天*2品种) ============ */
var col6 = ZY_KEYS.recreate('dwd_mkt_repo_rate');
col6.createIndex({ RATE_CD: 1, BIZ_DT: 1 }, { unique: true });
var repoRateSeed = [];
[{cd:'DR001',base:0.0165},{cd:'DR007',base:0.0182}].forEach(function(r) {
  TRADE_DAYS.forEach(function (dt, k) {
    repoRateSeed.push({ RATE_CD: r.cd, BIZ_DT: dt, RATE_VAL: +(r.base + (k-2)*0.0003).toFixed(6), HIGH: +(r.base + 0.0015 + (k-2)*0.0003).toFixed(6), LOW: +(r.base - 0.0010 + (k-2)*0.0003).toFixed(6), VOL: 3.5e11 + k * 2e10 });
  });
});
repoRateSeed.forEach(function (d) { Object.assign(d, aud()); });
col6.insertMany(repoRateSeed);
print('  dwd_mkt_repo_rate: ' + col6.countDocuments());

/* ============ 7. dwd_mkt_shibor SHIBOR利率 (10条) ============ */
var col7 = ZY_KEYS.recreate('dwd_mkt_shibor');
col7.createIndex({ TENOR: 1, BIZ_DT: 1 }, { unique: true });
var shiborSeed = [];
[{tn:'ON',base:0.0162},{tn:'1W',base:0.0178},{tn:'2W',base:0.0195},{tn:'1M',base:0.0208},{tn:'3M',base:0.0215}].forEach(function(s) {
  TRADE_DAYS.slice(-2).forEach(function (dt, k) {
    shiborSeed.push({ TENOR: s.tn, BIZ_DT: dt, RATE: +(s.base + k*0.0001).toFixed(6), CHG_BP: +(k === 0 ? 0 : 0.1).toFixed(1) });
  });
});
shiborSeed.forEach(function (d) { Object.assign(d, aud()); });
col7.insertMany(shiborSeed);
print('  dwd_mkt_shibor: ' + col7.countDocuments());

/* ============ 8. dwd_mkt_fx_rate 汇率 (8条) ============ */
var col8 = ZY_KEYS.recreate('dwd_mkt_fx_rate');
col8.createIndex({ CCY_PAIR: 1, BIZ_DT: 1 }, { unique: true });
var fxSeed = [];
[{p:'USD/CNY',mid:7.2231},{p:'EUR/CNY',mid:7.8132},{p:'JPY/CNY',mid:0.0480},{p:'HKD/CNY',mid:0.9298}].forEach(function(fx) {
  TRADE_DAYS.slice(-2).forEach(function (dt, k) {
    fxSeed.push({ CCY_PAIR: fx.p, BIZ_DT: dt, MID: +(fx.mid + k*0.002).toFixed(4), BID: +(fx.mid + k*0.002 - 0.0005).toFixed(4), ASK: +(fx.mid + k*0.002 + 0.0005).toFixed(4), SOURCE: 'CFETS' });
  });
});
fxSeed.forEach(function (d) { Object.assign(d, aud()); });
col8.insertMany(fxSeed);
print('  dwd_mkt_fx_rate: ' + col8.countDocuments());

/* ============ 9. dwd_mkt_commodity 商品价格 (6条) ============ */
var col9 = ZY_KEYS.recreate('dwd_mkt_commodity');
col9.createIndex({ COMMODITY: 1, BIZ_DT: 1 }, { unique: true });
var comSeed = [];
[{nm:'黄金',unit:'元/克',base:580.5},{nm:'原油(WTI)',unit:'美元/桶',base:68.2},{nm:'铜',unit:'元/吨',base:72500}].forEach(function(c) {
  TRADE_DAYS.slice(-2).forEach(function (dt, k) {
    comSeed.push({ COMMODITY: c.nm, BIZ_DT: dt, UNIT: c.unit, CLOSE_PRC: +(c.base + k * c.base * 0.005).toFixed(2), CHG_PCT: +(k * 0.5).toFixed(2) });
  });
});
comSeed.forEach(function (d) { Object.assign(d, aud()); });
col9.insertMany(comSeed);
print('  dwd_mkt_commodity: ' + col9.countDocuments());

/* ============ 10. dwd_mkt_option 期权隐含波动率 (6条) ============ */
var col10 = ZY_KEYS.recreate('dwd_mkt_option');
col10.createIndex({ UNDERLYING: 1, BIZ_DT: 1, EXPIRY: 1 }, { unique: true });
var optSeed = [
  { UNDERLYING: '510300.SH', BIZ_DT: '20250324', EXPIRY: '20250423', STRIKE: 4.15, CALL_IV: 0.182, PUT_IV: 0.195, CALL_DELTA: 0.52, PUT_DELTA: -0.48 },
  { UNDERLYING: '510300.SH', BIZ_DT: '20250324', EXPIRY: '20250528', STRIKE: 4.20, CALL_IV: 0.198, PUT_IV: 0.210, CALL_DELTA: 0.48, PUT_DELTA: -0.52 },
  { UNDERLYING: '510300.SH', BIZ_DT: '20250321', EXPIRY: '20250423', STRIKE: 4.15, CALL_IV: 0.185, PUT_IV: 0.198, CALL_DELTA: 0.51, PUT_DELTA: -0.49 },
  { UNDERLYING: '000300.SH', BIZ_DT: '20250324', EXPIRY: '20250425', STRIKE: 3600, CALL_IV: 0.175, PUT_IV: 0.188, CALL_DELTA: 0.50, PUT_DELTA: -0.50 },
  { UNDERLYING: '000300.SH', BIZ_DT: '20250324', EXPIRY: '20250627', STRIKE: 3650, CALL_IV: 0.192, PUT_IV: 0.205, CALL_DELTA: 0.46, PUT_DELTA: -0.54 },
  { UNDERLYING: '000300.SH', BIZ_DT: '20250321', EXPIRY: '20250425', STRIKE: 3600, CALL_IV: 0.178, PUT_IV: 0.190, CALL_DELTA: 0.49, PUT_DELTA: -0.51 }
];
optSeed.forEach(function (d) { Object.assign(d, aud()); });
col10.insertMany(optSeed);
print('  dwd_mkt_option: ' + col10.countDocuments());

/* ============ 11. dwd_mkt_credit_spread 信用利差 (10条) ============ */
var col11 = ZY_KEYS.recreate('dwd_mkt_credit_spread');
col11.createIndex({ RATING: 1, TENOR: 1, BIZ_DT: 1 }, { unique: true });
var csSeed = [];
[{r:'AAA',sp:0.0035},{r:'AA+',sp:0.0058},{r:'AA',sp:0.0085},{r:'AA-',sp:0.0125},{r:'A+',sp:0.0180}].forEach(function(g) {
  TRADE_DAYS.slice(-2).forEach(function (dt, k) {
    csSeed.push({ RATING: g.r, TENOR: '3Y', BIZ_DT: dt, SPREAD: +(g.sp + k*0.0002).toFixed(6), CHG_BP: +(k * 0.2).toFixed(1), BENCHMARK: 'CGB_3Y' });
  });
});
csSeed.forEach(function (d) { Object.assign(d, aud()); });
col11.insertMany(csSeed);
print('  dwd_mkt_credit_spread: ' + col11.countDocuments());

/* ============ 12. dwd_mkt_swap_rate IRS利率互换 (8条) ============ */
var col12 = ZY_KEYS.recreate('dwd_mkt_swap_rate');
col12.createIndex({ SWAP_TYPE: 1, TENOR: 1, BIZ_DT: 1 }, { unique: true });
var swapSeed = [];
[{tp:'FR007',tn:'1Y',base:0.0178},{tp:'FR007',tn:'5Y',base:0.0205},{tp:'SHIBOR_3M',tn:'1Y',base:0.0195},{tp:'SHIBOR_3M',tn:'5Y',base:0.0225}].forEach(function(s) {
  TRADE_DAYS.slice(-2).forEach(function (dt, k) {
    swapSeed.push({ SWAP_TYPE: s.tp, TENOR: s.tn, BIZ_DT: dt, FIX_RATE: +(s.base + k*0.0002).toFixed(6), CHG_BP: +(k*0.2).toFixed(1) });
  });
});
swapSeed.forEach(function (d) { Object.assign(d, aud()); });
col12.insertMany(swapSeed);
print('  dwd_mkt_swap_rate: ' + col12.countDocuments());

/* ============ 13. dwd_mkt_bond_issue 债券发行信息 (6条) ============ */
var col13 = ZY_KEYS.recreate('dwd_mkt_bond_issue');
col13.createIndex({ ISSUE_CD: 1 }, { unique: true });
var issueSeed = [
  { ISSUE_CD: '250301.IB', ISSUE_NM: '25国债05', ISR_NM: '中华人民共和国财政部', ISSUE_DT: '20250319', ISSUE_AMT: 50000000000, COUPON: 0.0185, TENOR_Y: 10, MATURITY_DT: '20350319', ISSUE_PRC: 100.00, BID_MULTIPLE: 3.25 },
  { ISSUE_CD: '250302.IB', ISSUE_NM: '25国开03', ISR_NM: '国家开发银行', ISSUE_DT: '20250320', ISSUE_AMT: 30000000000, COUPON: 0.0220, TENOR_Y: 5, MATURITY_DT: '20300320', ISSUE_PRC: 100.00, BID_MULTIPLE: 2.85 },
  { ISSUE_CD: '250303.IB', ISSUE_NM: '25农发02', ISR_NM: '中国农业发展银行', ISSUE_DT: '20250321', ISSUE_AMT: 20000000000, COUPON: 0.0215, TENOR_Y: 3, MATURITY_DT: '20280321', ISSUE_PRC: 100.00, BID_MULTIPLE: 3.10 },
  { ISSUE_CD: '250304.IB', ISSUE_NM: '25工行MTN002', ISR_NM: '中国工商银行股份有限公司', ISSUE_DT: '20250318', ISSUE_AMT: 10000000000, COUPON: 0.0265, TENOR_Y: 3, MATURITY_DT: '20280318', ISSUE_PRC: 100.00, BID_MULTIPLE: 2.50 },
  { ISSUE_CD: '250305.SZ', ISSUE_NM: '25平安债01', ISR_NM: '中国平安保险(集团)股份有限公司', ISSUE_DT: '20250324', ISSUE_AMT: 5000000000, COUPON: 0.0295, TENOR_Y: 5, MATURITY_DT: '20300324', ISSUE_PRC: 100.00, BID_MULTIPLE: 2.15 },
  { ISSUE_CD: '250306.IB', ISSUE_NM: '25招行CD001', ISR_NM: '招商银行股份有限公司', ISSUE_DT: '20250324', ISSUE_AMT: 8000000000, COUPON: 0.0205, TENOR_Y: 1, MATURITY_DT: '20260324', ISSUE_PRC: 100.00, BID_MULTIPLE: 2.95 }
];
issueSeed.forEach(function (d) { Object.assign(d, aud()); });
col13.insertMany(issueSeed);
print('  dwd_mkt_bond_issue: ' + col13.countDocuments());

/* ============ 14. dwd_mkt_bond_redeem 债券到期兑付 (5条) ============ */
var col14 = ZY_KEYS.recreate('dwd_mkt_bond_redeem');
col14.createIndex({ REDEEM_CD: 1 }, { unique: true });
var redeemSeed = [
  { REDEEM_CD: '220318.IB', BOND_NM: '22国债05', MATURITY_DT: '20250318', FACE_AMT: 40000000000, COUPON: 0.0255, ISR_NM: '中华人民共和国财政部', REDEEM_STATUS: 'COMPLETED' },
  { REDEEM_CD: '220319.IB', BOND_NM: '22国开02', MATURITY_DT: '20250319', FACE_AMT: 25000000000, COUPON: 0.0290, ISR_NM: '国家开发银行', REDEEM_STATUS: 'COMPLETED' },
  { REDEEM_CD: '220321.IB', BOND_NM: '22农发MTN001', MATURITY_DT: '20250321', FACE_AMT: 8000000000, COUPON: 0.0310, ISR_NM: '中国农业发展银行', REDEEM_STATUS: 'COMPLETED' },
  { REDEEM_CD: '240324A.IB', BOND_NM: '24工行CD035', MATURITY_DT: '20250324', FACE_AMT: 5000000000, COUPON: 0.0210, ISR_NM: '中国工商银行股份有限公司', REDEEM_STATUS: 'COMPLETED' },
  { REDEEM_CD: '240324B.IB', BOND_NM: '24招行CP001', MATURITY_DT: '20250324', FACE_AMT: 3000000000, COUPON: 0.0225, ISR_NM: '招商银行股份有限公司', REDEEM_STATUS: 'COMPLETED' }
];
redeemSeed.forEach(function (d) { Object.assign(d, aud()); });
col14.insertMany(redeemSeed);
print('  dwd_mkt_bond_redeem: ' + col14.countDocuments());

/* ============ 15. dwd_mkt_secondary_trade 二级市场成交统计 (5条) ============ */
var col15 = ZY_KEYS.recreate('dwd_mkt_secondary_trade');
col15.createIndex({ MARKET: 1, BIZ_DT: 1 }, { unique: true });
var secTrdSeed = [];
TRADE_DAYS.forEach(function (dt, k) {
  secTrdSeed.push({ MARKET: 'IB', BIZ_DT: dt, TOTAL_VOL: 3.8e11 + k*1e10, TOTAL_AMT: 3.8e11 + k*1e10, TRADE_CNT: 8500 + k*200, OUTRIGHT_AMT: 1.2e11 + k*5e9, REPO_AMT: 2.6e11 + k*5e9, TOP_ACTIVE: '019601.IB' });
});
secTrdSeed.forEach(function (d) { Object.assign(d, aud()); });
col15.insertMany(secTrdSeed);
print('  dwd_mkt_secondary_trade: ' + col15.countDocuments());

/* ============ 16. dwd_mkt_abs_pool ABS资产池表现 (5条) ============ */
var col16 = ZY_KEYS.recreate('dwd_mkt_abs_pool');
col16.createIndex({ ABS_CD: 1, RPT_DT: 1 }, { unique: true });
var absSeed = [
  { ABS_CD: '127080.SZ', ABS_NM: '2024华能新能ABS001优先A', RPT_DT: '20250228', POOL_BAL: 4500000000, DEFAULT_RATE: 0.0012, PREPAY_RATE: 0.08, COVERAGE_RATIO: 1.35, RATING: 'AAA', STATUS: 'NORMAL' },
  { ABS_CD: '127080.SZ', ABS_NM: '2024华能新能ABS001优先A', RPT_DT: '20250131', POOL_BAL: 4650000000, DEFAULT_RATE: 0.0010, PREPAY_RATE: 0.07, COVERAGE_RATIO: 1.38, RATING: 'AAA', STATUS: 'NORMAL' },
  { ABS_CD: 'ABS2024002.IB', ABS_NM: '2024招行信用卡ABS01A', RPT_DT: '20250228', POOL_BAL: 8200000000, DEFAULT_RATE: 0.0025, PREPAY_RATE: 0.12, COVERAGE_RATIO: 1.42, RATING: 'AAA', STATUS: 'NORMAL' },
  { ABS_CD: 'ABS2024003.IB', ABS_NM: '2024工行个贷ABS01优先', RPT_DT: '20250228', POOL_BAL: 12000000000, DEFAULT_RATE: 0.0008, PREPAY_RATE: 0.06, COVERAGE_RATIO: 1.55, RATING: 'AAA', STATUS: 'NORMAL' },
  { ABS_CD: 'ABS2024004.IB', ABS_NM: '2024平安消费ABS02A', RPT_DT: '20250228', POOL_BAL: 3800000000, DEFAULT_RATE: 0.0035, PREPAY_RATE: 0.15, COVERAGE_RATIO: 1.28, RATING: 'AA+', STATUS: 'ATTENTION' }
];
absSeed.forEach(function (d) { Object.assign(d, aud()); });
col16.insertMany(absSeed);
print('  dwd_mkt_abs_pool: ' + col16.countDocuments());

/* ============ 17. dwd_mkt_ncd_rate NCD发行利率 (10条) ============ */
var col17 = ZY_KEYS.recreate('dwd_mkt_ncd_rate');
col17.createIndex({ BANK_TYPE: 1, TENOR: 1, BIZ_DT: 1 }, { unique: true });
var ncdSeed = [];
[{bt:'AAA国股',base:0.0195},{bt:'AAA城商',base:0.0210},{bt:'AA+城商',base:0.0235},{bt:'AA农商',base:0.0268},{bt:'AAA国股(1Y)',base:0.0205}].forEach(function(n) {
  TRADE_DAYS.slice(-2).forEach(function (dt, k) {
    ncdSeed.push({ BANK_TYPE: n.bt, TENOR: '3M', BIZ_DT: dt, ISSUE_RATE: +(n.base + k*0.0001).toFixed(6), ISSUE_AMT: 5e9 + k*1e9, ISSUE_CNT: 15 + k*3 });
  });
});
ncdSeed.forEach(function (d) { Object.assign(d, aud()); });
col17.insertMany(ncdSeed);
print('  dwd_mkt_ncd_rate: ' + col17.countDocuments());

/* ============ 18. dwd_mkt_etf_flow ETF申赎数据 (10条) ============ */
var col18 = ZY_KEYS.recreate('dwd_mkt_etf_flow');
col18.createIndex({ AST_CD: 1, BIZ_DT: 1 }, { unique: true });
var etfFlowSeed = [];
['510300.SH','511260.SH'].forEach(function (cd, i) {
  TRADE_DAYS.forEach(function (dt, k) {
    var netFlow = (k % 2 === 0 ? 1 : -1) * (2e8 + i*5e7 + k*1e7);
    etfFlowSeed.push({ AST_CD: cd, BIZ_DT: dt, SUBSCRIBE_AMT: 5e8 + k*1e7, REDEEM_AMT: 5e8 + k*1e7 - netFlow, NET_FLOW: netFlow, SHARE_CHG: +(netFlow / (i===0?4.15:1.03)).toFixed(0)*1 });
  });
});
etfFlowSeed.forEach(function (d) { Object.assign(d, aud()); });
col18.insertMany(etfFlowSeed);
print('  dwd_mkt_etf_flow: ' + col18.countDocuments());

/* ============ 19. dwd_mkt_fund_flow 基金资金流向 (5条) ============ */
var col19 = ZY_KEYS.recreate('dwd_mkt_fund_flow');
col19.createIndex({ FUND_TYPE: 1, BIZ_DT: 1 }, { unique: true });
var ffSeed = [];
TRADE_DAYS.forEach(function (dt, k) {
  ffSeed.push({ FUND_TYPE: 'BOND', BIZ_DT: dt, NET_SUBSCRIBE: (k%2===0?1:-1)*15e8 + k*1e8, TOTAL_SUBSCRIBE: 85e8 + k*2e8, TOTAL_REDEEM: 70e8 + k*1e8, AUM_CHG: (k%2===0?1:-1)*20e8 });
});
ffSeed.forEach(function (d) { Object.assign(d, aud()); });
col19.insertMany(ffSeed);
print('  dwd_mkt_fund_flow: ' + col19.countDocuments());

/* ============ 20. dwd_mkt_margin 融资融券数据 (5条) ============ */
var col20 = ZY_KEYS.recreate('dwd_mkt_margin');
col20.createIndex({ MARKET: 1, BIZ_DT: 1 }, { unique: true });
var marginSeed = [];
TRADE_DAYS.forEach(function (dt, k) {
  marginSeed.push({ MARKET: 'ALL', BIZ_DT: dt, MARGIN_BUY: 850e8 + k*10e8, MARGIN_SELL: 120e8 + k*2e8, MARGIN_BAL: 16500e8 + k*50e8, SHORT_BAL: 980e8 + k*5e8, NET_BUY: 730e8 + k*8e8 });
});
marginSeed.forEach(function (d) { Object.assign(d, aud()); });
col20.insertMany(marginSeed);
print('  dwd_mkt_margin: ' + col20.countDocuments());

/* ============ 21. dwd_mkt_volatility 波动率指数 (5条) ============ */
var col21 = ZY_KEYS.recreate('dwd_mkt_volatility');
col21.createIndex({ INDEX_CD: 1, BIZ_DT: 1 }, { unique: true });
var volSeed = [];
TRADE_DAYS.forEach(function (dt, k) {
  volSeed.push({ INDEX_CD: 'iVIX', INDEX_NM: '中国波指', BIZ_DT: dt, CLOSE_VAL: +(18.5 + k*0.3).toFixed(2), HIGH_VAL: +(19.2 + k*0.3).toFixed(2), LOW_VAL: +(17.8 + k*0.3).toFixed(2), CHG_PCT: +((k-2)*0.8).toFixed(2) });
});
volSeed.forEach(function (d) { Object.assign(d, aud()); });
col21.insertMany(volSeed);
print('  dwd_mkt_volatility: ' + col21.countDocuments());

/* ============ 22. dwd_mkt_sentiment 市场情绪指标 (5条) ============ */
var col22 = ZY_KEYS.recreate('dwd_mkt_sentiment');
col22.createIndex({ BIZ_DT: 1 }, { unique: true });
var sentSeed = [];
TRADE_DAYS.forEach(function (dt, k) {
  sentSeed.push({ BIZ_DT: dt, ADVANCE_CNT: 2800 + k*50, DECLINE_CNT: 2100 - k*30, LIMIT_UP: 35 + k*5, LIMIT_DOWN: 12 - k, TURNOVER_RATE: +(0.85 + k*0.02).toFixed(4), NORTH_FLOW: (k%2===0?1:-1)*(35 + k*5)*1e8, SENTIMENT_IDX: +(52 + k*1.5).toFixed(1) });
});
sentSeed.forEach(function (d) { Object.assign(d, aud()); });
col22.insertMany(sentSeed);
print('  dwd_mkt_sentiment: ' + col22.countDocuments());

/* ============ 23. dwd_mkt_macro 宏观经济指标 (8条) ============ */
var col23 = ZY_KEYS.recreate('dwd_mkt_macro');
col23.createIndex({ INDICATOR: 1, RPT_DT: 1 }, { unique: true });
var macroSeed = [
  { INDICATOR: 'CPI', RPT_DT: '20250315', RPT_PERIOD: '2025-02', VALUE: 0.7, UNIT: '%', YOY: 0.7, MOM: 0.2, SOURCE: '国家统计局' },
  { INDICATOR: 'PPI', RPT_DT: '20250315', RPT_PERIOD: '2025-02', VALUE: -1.5, UNIT: '%', YOY: -1.5, MOM: -0.2, SOURCE: '国家统计局' },
  { INDICATOR: 'PMI_MFG', RPT_DT: '20250301', RPT_PERIOD: '2025-02', VALUE: 50.2, UNIT: '%', YOY: null, MOM: 0.3, SOURCE: '国家统计局' },
  { INDICATOR: 'PMI_SVC', RPT_DT: '20250301', RPT_PERIOD: '2025-02', VALUE: 51.8, UNIT: '%', YOY: null, MOM: 0.5, SOURCE: '国家统计局' },
  { INDICATOR: 'GDP_YOY', RPT_DT: '20250117', RPT_PERIOD: '2024-Q4', VALUE: 5.2, UNIT: '%', YOY: 5.2, MOM: null, SOURCE: '国家统计局' },
  { INDICATOR: 'M2_YOY', RPT_DT: '20250312', RPT_PERIOD: '2025-02', VALUE: 7.0, UNIT: '%', YOY: 7.0, MOM: null, SOURCE: '中国人民银行' },
  { INDICATOR: 'SOCIAL_FIN', RPT_DT: '20250312', RPT_PERIOD: '2025-02', VALUE: 15800, UNIT: '亿元', YOY: null, MOM: null, SOURCE: '中国人民银行' },
  { INDICATOR: 'EXPORT_YOY', RPT_DT: '20250307', RPT_PERIOD: '2025-02', VALUE: 8.5, UNIT: '%', YOY: 8.5, MOM: null, SOURCE: '海关总署' }
];
macroSeed.forEach(function (d) { Object.assign(d, aud()); });
col23.insertMany(macroSeed);
print('  dwd_mkt_macro: ' + col23.countDocuments());

/* ============ 24. dwd_mkt_policy 政策事件 (6条) ============ */
var col24 = ZY_KEYS.recreate('dwd_mkt_policy');
col24.createIndex({ POLICY_ID: 1 }, { unique: true });
col24.createIndex({ EVENT_DT: 1 });
var policySeed = [
  { POLICY_ID: 'POL20250115001', EVENT_DT: '20250115', SOURCE: '中国人民银行', POLICY_TYPE: 'MLF', TITLE: 'MLF操作利率维持2.50%不变', DESC: '1月MLF操作量5000亿元，中标利率2.50%持平上期，符合市场预期', IMPACT: 'NEUTRAL' },
  { POLICY_ID: 'POL20250205002', EVENT_DT: '20250205', SOURCE: '中国人民银行', POLICY_TYPE: 'RRR_CUT', TITLE: '央行宣布降准50BP', DESC: '为保持流动性合理充裕，支持实体经济，全面降准0.5个百分点，释放长期资金约1万亿元', IMPACT: 'POSITIVE' },
  { POLICY_ID: 'POL20250220003', EVENT_DT: '20250220', SOURCE: '中国人民银行', POLICY_TYPE: 'LPR', TITLE: 'LPR报价下调：1年期3.00%，5年期3.50%', DESC: '2月LPR报价1年期下调10BP至3.00%，5年期下调15BP至3.50%', IMPACT: 'POSITIVE' },
  { POLICY_ID: 'POL20250310004', EVENT_DT: '20250310', SOURCE: '财政部', POLICY_TYPE: 'FISCAL', TITLE: '2025年特别国债发行计划公布', DESC: '财政部公布全年1.5万亿特别国债发行计划，分批次发行用于重大项目建设', IMPACT: 'NEUTRAL' },
  { POLICY_ID: 'POL20250318005', EVENT_DT: '20250318', SOURCE: '中国人民银行', POLICY_TYPE: 'WINDOW', TITLE: '央行窗口指导银行加大信贷投放', DESC: '据悉央行窗口指导部分银行加大一季度信贷投放力度，确保"开门红"', IMPACT: 'POSITIVE' },
  { POLICY_ID: 'POL20250320006', EVENT_DT: '20250320', SOURCE: '银保监会', POLICY_TYPE: 'REGULATION', TITLE: '房地产融资协调机制"白名单"扩围', DESC: '监管进一步扩大房地产融资"白名单"项目范围，支持房企合理融资需求', IMPACT: 'POSITIVE' }
];
policySeed.forEach(function (d) { Object.assign(d, aud()); });
col24.insertMany(policySeed);
print('  dwd_mkt_policy: ' + col24.countDocuments());

/* ============ 25. dwd_mkt_calendar 交易日历 (10条) ============ */
var col25 = ZY_KEYS.recreate('dwd_mkt_calendar');
col25.createIndex({ CAL_DT: 1, MARKET: 1 }, { unique: true });
var calSeed = [];
// 本周及下周的日历
var calDays = ['20250317','20250318','20250319','20250320','20250321','20250322','20250323','20250324','20250325','20250326'];
calDays.forEach(function (dt) {
  var y = parseInt(dt.substr(0,4),10), m = parseInt(dt.substr(4,2),10)-1, d = parseInt(dt.substr(6,2),10);
  var dow = new Date(y,m,d).getDay();
  var isTrade = (dow >= 1 && dow <= 5) ? 'Y' : 'N';
  calSeed.push({ CAL_DT: dt, MARKET: 'IB', IS_TRADE: isTrade, WEEK_DAY: dow, WEEK_DAY_NM: ['日','一','二','三','四','五','六'][dow] });
});
calSeed.forEach(function (d) { Object.assign(d, aud()); });
col25.insertMany(calSeed);
print('  dwd_mkt_calendar: ' + col25.countDocuments());

print('--- [09] market domain done ---');
