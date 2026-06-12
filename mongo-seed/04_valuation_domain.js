/**
 * 估值域 dwd_val_* — 10 张表
 * 主键：PORT_ID + BIZ_DT 组合；估值表头 + 资产明细 + 损益明细 + 风险分布
 *
 * 包含：
 *   1. dwd_val_valtable        估值表
 *   2. dwd_val_asset_detail    估值资产明细
 *   3. dwd_val_income          收入明细
 *   4. dwd_val_expense         费用明细
 *   5. dwd_val_cash_flow       资金流水
 *   6. dwd_val_fx_exposure     外汇敞口
 *   7. dwd_val_duration_bucket 久期分布
 *   8. dwd_val_credit_bucket   信用分布
 *   9. dwd_val_sector_bucket   行业分布
 *  10. dwd_val_concentration   集中度
 */
load('_keys.js');
print('--- [04] valuation domain start ---');

var BIZ_DT     = ZY_KEYS.BIZ_DT;
var PORTS      = ZY_KEYS.PORT_IDS;
var PORT_NAMES = ZY_KEYS.PORT_NAMES;
var AST_NAMES  = ZY_KEYS.AST_NAMES;
var aud        = ZY_KEYS.audit;

// 6 个交易日（与产品域 dwd_ptl_nav_hist 保持一致）
var TDAYS = ['20250317', '20250318', '20250319', '20250320', '20250321', '20250324'];

// 与 03_product_domain.js dwd_ptl_info 保持一致的关键参数
var portMeta = {
  'PORT001': { netAst: 1250000000, totShare: 1189250000, shrNav: 1.0512, accNav: 1.1835, dayRet:  0.00171 },
  'PORT002': { netAst: 4520000000, totShare: 4078026250, shrNav: 1.1086, accNav: 1.2563, dayRet:  0.00063 },
  'PORT003': { netAst:  870000000, totShare:  898378550, shrNav: 0.9683, accNav: 0.9683, dayRet: -0.00258 },
  'PORT004': { netAst: 5000000000, totShare: 5000000000, shrNav: 1.0000, accNav: 1.1942, dayRet:  0.00006 },
  'PORT005': { netAst: 3500000000, totShare: 3401690155, shrNav: 1.0289, accNav: 1.0289, dayRet:  0.00097 }
};
// 应付费用、应付赎回相对净资产的小比例
var liabRatio = 0.0020;

/* ================ 1. dwd_val_valtable 估值表 ================ */
ZY_KEYS.recreate('dwd_val_valtable', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_val_valtable.createIndex({ PORT_ID: 1, BIZ_DT: 1 }, { unique: true });
var vtSeed = [];
PORTS.forEach(function (pid) {
  var meta = portMeta[pid];
  TDAYS.forEach(function (dt, idx) {
    // 每日轻微抖动
    var driftAcc = +(meta.accNav - (5 - idx) * meta.dayRet * 0.85).toFixed(6);
    var driftShr = pid === 'PORT004' ? 1.0000 : +(meta.shrNav - (5 - idx) * meta.dayRet * 0.85).toFixed(6);
    var dayNetAst = +(driftShr * meta.totShare).toFixed(2);
    var dayLiab   = +(dayNetAst * liabRatio).toFixed(2);
    var dayTotAst = +(dayNetAst + dayLiab).toFixed(2);
    vtSeed.push({
      PORT_ID:     pid,
      BIZ_DT:      dt,
      TOTAL_ASSET: dayTotAst,
      TOTAL_LIAB:  dayLiab,
      NET_ASSET:   dayNetAst,
      SHR_NAV:     driftShr,
      ACC_NAV:     driftAcc,
      TOTAL_SHARE: meta.totShare,
      DAILY_RET:   idx === 0 ? 0 : +(meta.dayRet + (idx - 3) * 0.00012).toFixed(6),
      VAL_STATUS:  idx === 5 ? 'PUBLISHED' : 'CONFIRMED',
      VAL_VERSION: 1
    });
  });
});
vtSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_valtable.insertMany(vtSeed);
print('  dwd_val_valtable: ' + db.dwd_val_valtable.countDocuments());

/* ================ 2. dwd_val_asset_detail 估值资产明细 ================ */
ZY_KEYS.recreate('dwd_val_asset_detail', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'AST_CD', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    AST_CD:  { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_val_asset_detail.createIndex({ PORT_ID: 1, AST_CD: 1, BIZ_DT: 1 }, { unique: true });
// 5 组合 * 5 个资产 = 25 条，与 dwd_ptl_holding 对齐
var detailMap = {
  'PORT001': [
    { cd: '019601.IB',  qty:  200000, costPrc:  99.2500, mktPrc:  99.5600, mvPrev: 198560000, mvCurr: 199120000 },
    { cd: '230210.IB',  qty:  150000, costPrc: 100.2667, mktPrc: 100.8500, mvPrev: 150525000, mvCurr: 151275000 },
    { cd: '2480006.IB', qty:  120000, costPrc:  99.8333, mktPrc: 100.7000, mvPrev: 120240000, mvCurr: 120840000 },
    { cd: '600036.SH',  qty: 2500000, costPrc:  40.8000, mktPrc:  42.2500, mvPrev: 105000000, mvCurr: 105625000 },
    { cd: '510300.SH',  qty:18000000, costPrc:   4.3800, mktPrc:   4.4000, mvPrev:  79100000, mvCurr:  79200000 }
  ],
  'PORT002': [
    { cd: '019601.IB',  qty:  800000, costPrc:  99.2500, mktPrc:  99.5600, mvPrev: 794240000, mvCurr: 796480000 },
    { cd: '019735.IB',  qty:  700000, costPrc: 100.4000, mktPrc: 100.9000, mvPrev: 704620000, mvCurr: 706300000 },
    { cd: '230210.IB',  qty:  600000, costPrc: 100.2000, mktPrc: 100.8500, mvPrev: 603300000, mvCurr: 605100000 },
    { cd: '220215.IB',  qty:  500000, costPrc: 100.1000, mktPrc: 100.6500, mvPrev: 502250000, mvCurr: 503250000 },
    { cd: '180401.IB',  qty:  350000, costPrc: 100.1000, mktPrc: 100.3500, mvPrev: 350490000, mvCurr: 351225000 }
  ],
  'PORT003': [
    { cd: '601318.SH',  qty:  900000, costPrc:  49.5000, mktPrc:  51.5000, mvPrev:  46035000, mvCurr:  46350000 },
    { cd: '600036.SH',  qty: 1100000, costPrc:  40.9000, mktPrc:  42.2500, mvPrev:  46145000, mvCurr:  46475000 },
    { cd: '510300.SH',  qty: 8500000, costPrc:   4.3700, mktPrc:   4.4000, mvPrev:  37187500, mvCurr:  37400000 },
    { cd: '220215.IB',  qty:  100000, costPrc: 100.1000, mktPrc: 100.6500, mvPrev: 100450000, mvCurr: 100650000 },
    { cd: '127080.SZ',  qty:  500000, costPrc:  99.7000, mktPrc: 100.1500, mvPrev:  49975000, mvCurr:  50075000 }
  ],
  'PORT004': [
    { cd: '019601.IB',  qty: 1500000, costPrc:  99.2500, mktPrc:  99.6100, mvPrev: 1490175000, mvCurr: 1494150000 },
    { cd: '2480006.IB', qty: 1200000, costPrc:  99.8333, mktPrc: 100.7000, mvPrev: 1206000000, mvCurr: 1208400000 },
    { cd: '019735.IB',  qty:  900000, costPrc: 100.4000, mktPrc: 100.9000, mvPrev:  906480000, mvCurr:  908100000 },
    { cd: '230210.IB',  qty:  600000, costPrc: 100.2000, mktPrc: 100.8500, mvPrev:  603300000, mvCurr:  605100000 },
    { cd: '511260.SH',  qty: 3000000, costPrc: 111.3500, mktPrc: 111.8000, mvPrev:  334800000, mvCurr:  335400000 }
  ],
  'PORT005': [
    { cd: '510300.SH',  qty:35000000, costPrc:   4.3730, mktPrc:   4.4000, mvPrev: 1538950000, mvCurr: 1540000000 },
    { cd: '600036.SH',  qty: 8500000, costPrc:  41.4000, mktPrc:  42.2500, mvPrev:  357850000, mvCurr:  359125000 },
    { cd: '601318.SH',  qty: 6800000, costPrc:  50.4000, mktPrc:  51.5000, mvPrev:  348160000, mvCurr:  350200000 },
    { cd: '511260.SH',  qty: 2200000, costPrc: 111.1200, mktPrc: 111.8000, mvPrev:  245476000, mvCurr:  245960000 },
    { cd: '019601.IB',  qty:  200000, costPrc:  99.2000, mktPrc:  99.5600, mvPrev:  198720000, mvCurr:  199120000 }
  ]
};
var detailSeed = [];
PORTS.forEach(function (pid) {
  detailMap[pid].forEach(function (h) {
    var costAmt = +(h.qty * h.costPrc).toFixed(2);
    detailSeed.push({
      PORT_ID:    pid,
      BIZ_DT:     BIZ_DT,
      AST_CD:     h.cd,
      AST_NM:     AST_NAMES[h.cd],
      HOLD_QTY:   h.qty,
      COST_PRC:   h.costPrc,
      MKT_PRC:    h.mktPrc,
      COST_AMT:   costAmt,
      MKT_VAL:    h.mvCurr,
      VAL_CHANGE: +(h.mvCurr - h.mvPrev).toFixed(2),  // 估值增减 = 当日市值 - 前日市值
      UNREAL_PNL: +(h.mvCurr - costAmt).toFixed(2),    // 浮动盈亏 = 市值 - 成本
      DAILY_PNL:  +(h.mvCurr - h.mvPrev).toFixed(2)
    });
  });
});
detailSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_asset_detail.insertMany(detailSeed);
print('  dwd_val_asset_detail: ' + db.dwd_val_asset_detail.countDocuments());

/* ================ 3. dwd_val_income 收入明细 ================ */
ZY_KEYS.recreate('dwd_val_income', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'INC_TYPE'],
  properties: {
    PORT_ID:  { bsonType: 'string' },
    BIZ_DT:   { bsonType: 'string' },
    INC_TYPE: { bsonType: 'string' }
  }
}});
db.dwd_val_income.createIndex({ PORT_ID: 1, BIZ_DT: 1, INC_TYPE: 1 }, { unique: true });
// 每个组合 3 类收入 = 15 条
var incomeSeed = [
  // PORT001 - MIXED
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, INC_TYPE: 'INTEREST',  INC_DESC: '债券利息收入(含国债+国开+MTN)',  AMT:    96850.00, CCY: 'CNY' },
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, INC_TYPE: 'DIVIDEND',  INC_DESC: '股票股息收入',                     AMT:     8425.00, CCY: 'CNY' },
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, INC_TYPE: 'FV_CHANGE', INC_DESC: '公允价值变动损益',                 AMT:  2185600.00, CCY: 'CNY' },
  // PORT002 - BOND
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, INC_TYPE: 'INTEREST',  INC_DESC: '纯债组合利息收入',                 AMT:   478520.00, CCY: 'CNY' },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, INC_TYPE: 'DIVIDEND',  INC_DESC: '股息收入(无)',                     AMT:        0.00, CCY: 'CNY' },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, INC_TYPE: 'FV_CHANGE', INC_DESC: '债券公允价值变动',                 AMT:  3142800.00, CCY: 'CNY' },
  // PORT003 - MIXED
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, INC_TYPE: 'INTEREST',  INC_DESC: '债券利息收入',                     AMT:    16850.00, CCY: 'CNY' },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, INC_TYPE: 'DIVIDEND',  INC_DESC: '股票股息收入',                     AMT:    21450.00, CCY: 'CNY' },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, INC_TYPE: 'FV_CHANGE', INC_DESC: '公允价值变动损益',                 AMT: -2245100.00, CCY: 'CNY' },
  // PORT004 - MMF
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, INC_TYPE: 'INTEREST',  INC_DESC: '货基利息收入(债券+回购+存单)',     AMT:   286400.00, CCY: 'CNY' },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, INC_TYPE: 'DIVIDEND',  INC_DESC: '股息收入(无)',                     AMT:        0.00, CCY: 'CNY' },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, INC_TYPE: 'FV_CHANGE', INC_DESC: '公允价值变动(摊余成本影响有限)',   AMT:    14250.00, CCY: 'CNY' },
  // PORT005 - INDEX
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, INC_TYPE: 'INTEREST',  INC_DESC: '债券利息收入',                     AMT:    24360.00, CCY: 'CNY' },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, INC_TYPE: 'DIVIDEND',  INC_DESC: '股票及ETF分红',                     AMT:   162400.00, CCY: 'CNY' },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, INC_TYPE: 'FV_CHANGE', INC_DESC: '公允价值变动(指数增强超额)',       AMT:  3392150.00, CCY: 'CNY' }
];
incomeSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_income.insertMany(incomeSeed);
print('  dwd_val_income: ' + db.dwd_val_income.countDocuments());

/* ================ 4. dwd_val_expense 费用明细 ================ */
ZY_KEYS.recreate('dwd_val_expense', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'EXP_TYPE'],
  properties: {
    PORT_ID:  { bsonType: 'string' },
    BIZ_DT:   { bsonType: 'string' },
    EXP_TYPE: { bsonType: 'string' }
  }
}});
db.dwd_val_expense.createIndex({ PORT_ID: 1, BIZ_DT: 1, EXP_TYPE: 1 }, { unique: true });
// 每个组合 3 类费用 = 15 条
var expenseSeed = [];
var feeRateMap = {
  'PORT001': { mgt: 0.0120, custody: 0.0020, txnRate: 0.0003, txnAmt:  147570000 },
  'PORT002': { mgt: 0.0070, custody: 0.0020, txnRate: 0.0003, txnAmt:  744340000 },
  'PORT003': { mgt: 0.0150, custody: 0.0025, txnRate: 0.0005, txnAmt:  111200000 },
  'PORT004': { mgt: 0.0033, custody: 0.0008, txnRate: 0.0000750, txnAmt: 1905700000 },
  'PORT005': { mgt: 0.0100, custody: 0.0020, txnRate: 0.0003, txnAmt:  289280000 }
};
PORTS.forEach(function (pid) {
  var fr = feeRateMap[pid];
  var meta = portMeta[pid];
  var dailyMgt     = +(meta.netAst * fr.mgt / 365).toFixed(2);
  var dailyCustody = +(meta.netAst * fr.custody / 365).toFixed(2);
  var dailyTxn     = +(fr.txnAmt * fr.txnRate).toFixed(2);
  expenseSeed.push({ PORT_ID: pid, BIZ_DT: BIZ_DT, EXP_TYPE: 'MGT_FEE',     EXP_DESC: '基金管理费(每日计提)',   AMT: dailyMgt,     CCY: 'CNY' });
  expenseSeed.push({ PORT_ID: pid, BIZ_DT: BIZ_DT, EXP_TYPE: 'CUSTODY_FEE', EXP_DESC: '基金托管费(每日计提)',   AMT: dailyCustody, CCY: 'CNY' });
  expenseSeed.push({ PORT_ID: pid, BIZ_DT: BIZ_DT, EXP_TYPE: 'TXN_FEE',     EXP_DESC: '交易费用(佣金+过户费)',  AMT: dailyTxn,     CCY: 'CNY' });
});
expenseSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_expense.insertMany(expenseSeed);
print('  dwd_val_expense: ' + db.dwd_val_expense.countDocuments());

/* ================ 5. dwd_val_cash_flow 资金流水 ================ */
ZY_KEYS.recreate('dwd_val_cash_flow', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'CF_TYPE', 'CF_SEQ'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' },
    CF_TYPE: { bsonType: 'string' },
    CF_SEQ:  { bsonType: 'int' }
  }
}});
db.dwd_val_cash_flow.createIndex({ PORT_ID: 1, BIZ_DT: 1, CF_TYPE: 1, CF_SEQ: 1 }, { unique: true });
// 每个组合 4 条 = 20 条
var cashFlowSeed = [
  // PORT001
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, CF_TYPE: 'SUBSCRIBE', CF_SEQ: NumberInt(1), AMT:  5450000.00, CCY: 'CNY', SUMMARY: '客户申购确认入账' },
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, CF_TYPE: 'REDEEM',    CF_SEQ: NumberInt(2), AMT: -2180000.00, CCY: 'CNY', SUMMARY: '客户赎回款项支付' },
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, CF_TYPE: 'INTEREST',  CF_SEQ: NumberInt(3), AMT:    96850.00, CCY: 'CNY', SUMMARY: '债券每日应收利息计提' },
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, CF_TYPE: 'DIVIDEND',  CF_SEQ: NumberInt(4), AMT:        0.00, CCY: 'CNY', SUMMARY: '组合本日无分红支付' },
  // PORT002
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, CF_TYPE: 'SUBSCRIBE', CF_SEQ: NumberInt(1), AMT: 12640000.00, CCY: 'CNY', SUMMARY: '机构客户大额申购' },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, CF_TYPE: 'REDEEM',    CF_SEQ: NumberInt(2), AMT: -3580000.00, CCY: 'CNY', SUMMARY: '客户赎回款项支付' },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, CF_TYPE: 'INTEREST',  CF_SEQ: NumberInt(3), AMT:   478520.00, CCY: 'CNY', SUMMARY: '债券每日应收利息计提' },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, CF_TYPE: 'DIVIDEND',  CF_SEQ: NumberInt(4), AMT: -1850000.00, CCY: 'CNY', SUMMARY: '2024年度第二次分红派付' },
  // PORT003
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, CF_TYPE: 'SUBSCRIBE', CF_SEQ: NumberInt(1), AMT:  1250000.00, CCY: 'CNY', SUMMARY: '客户日常申购' },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, CF_TYPE: 'REDEEM',    CF_SEQ: NumberInt(2), AMT: -8420000.00, CCY: 'CNY', SUMMARY: '净值下跌引发的赎回潮' },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, CF_TYPE: 'INTEREST',  CF_SEQ: NumberInt(3), AMT:    16850.00, CCY: 'CNY', SUMMARY: '债券每日应收利息计提' },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, CF_TYPE: 'DIVIDEND',  CF_SEQ: NumberInt(4), AMT:    21450.00, CCY: 'CNY', SUMMARY: '招商银行/中国平安股息到账' },
  // PORT004
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, CF_TYPE: 'SUBSCRIBE', CF_SEQ: NumberInt(1), AMT: 28500000.00, CCY: 'CNY', SUMMARY: '货基T+0申购实时确认' },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, CF_TYPE: 'REDEEM',    CF_SEQ: NumberInt(2), AMT:-22150000.00, CCY: 'CNY', SUMMARY: '货基T+0赎回实时支付' },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, CF_TYPE: 'INTEREST',  CF_SEQ: NumberInt(3), AMT:   286400.00, CCY: 'CNY', SUMMARY: '货基组合日利息计提' },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, CF_TYPE: 'DIVIDEND',  CF_SEQ: NumberInt(4), AMT:  -286400.00, CCY: 'CNY', SUMMARY: '货基日结收益自动转份额' },
  // PORT005
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, CF_TYPE: 'SUBSCRIBE', CF_SEQ: NumberInt(1), AMT:  6280000.00, CCY: 'CNY', SUMMARY: '客户申购确认入账' },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, CF_TYPE: 'REDEEM',    CF_SEQ: NumberInt(2), AMT: -1450000.00, CCY: 'CNY', SUMMARY: '客户赎回款项支付' },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, CF_TYPE: 'INTEREST',  CF_SEQ: NumberInt(3), AMT:    24360.00, CCY: 'CNY', SUMMARY: '债券每日应收利息计提' },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, CF_TYPE: 'DIVIDEND',  CF_SEQ: NumberInt(4), AMT:   162400.00, CCY: 'CNY', SUMMARY: '成份股股息及ETF分红' }
];
cashFlowSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_cash_flow.insertMany(cashFlowSeed);
print('  dwd_val_cash_flow: ' + db.dwd_val_cash_flow.countDocuments());

/* ================ 6. dwd_val_fx_exposure 外汇敞口 ================ */
ZY_KEYS.recreate('dwd_val_fx_exposure', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_val_fx_exposure.createIndex({ PORT_ID: 1, BIZ_DT: 1 }, { unique: true });
// 5 个组合各 1 条；本批组合均为人民币计价，外汇敞口为 0
var fxSeed = [];
PORTS.forEach(function (pid) {
  var meta = portMeta[pid];
  fxSeed.push({
    PORT_ID:       pid,
    BIZ_DT:        BIZ_DT,
    BASE_CCY:      'CNY',
    NET_ASSET_CNY: meta.netAst,
    USD_EXPOSURE:  0,
    HKD_EXPOSURE:  0,
    EUR_EXPOSURE:  0,
    JPY_EXPOSURE:  0,
    OTHER_EXPOSURE: 0,
    NET_FX_RATIO:  0,
    HEDGE_RATIO:   0,
    HEDGE_DESC:    '本组合无外币资产，外汇敞口为零，无需对冲'
  });
});
fxSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_fx_exposure.insertMany(fxSeed);
print('  dwd_val_fx_exposure: ' + db.dwd_val_fx_exposure.countDocuments());

/* ================ 7. dwd_val_duration_bucket 久期分布 ================ */
ZY_KEYS.recreate('dwd_val_duration_bucket', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'DUR_BUCKET'],
  properties: {
    PORT_ID:    { bsonType: 'string' },
    BIZ_DT:     { bsonType: 'string' },
    DUR_BUCKET: { bsonType: 'string' }
  }
}});
db.dwd_val_duration_bucket.createIndex({ PORT_ID: 1, BIZ_DT: 1, DUR_BUCKET: 1 }, { unique: true });
// 6 区间 * 抽样 - 实际只取与组合特征匹配的 3 个区间，5 组合 * 3 = 15
var durBucketMap = {
  'PORT001': [['1-3Y', 0.4218, 199120000], ['3-5Y', 0.3215, 151275000], ['5-7Y', 0.2567, 120840000]],
  'PORT002': [['3-5Y', 0.2675, 1209025000], ['5-7Y', 0.2898, 1310000000], ['7-10Y', 0.4427, 2000990000]],
  'PORT003': [['1-3Y', 0.5012, 50075000], ['3-5Y', 0.4988, 100650000], ['5-7Y', 0.0000, 0]],
  'PORT004': [['0-1Y', 0.6812, 2702550000], ['1-3Y', 0.3188, 1248450000], ['3-5Y', 0.0000, 0]],
  'PORT005': [['1-3Y', 0.5025, 100000000], ['3-5Y', 0.4975, 99120000], ['5-7Y', 0.0000, 0]]
};
var durSeed = [];
PORTS.forEach(function (pid) {
  durBucketMap[pid].forEach(function (b) {
    durSeed.push({
      PORT_ID:    pid,
      BIZ_DT:     BIZ_DT,
      DUR_BUCKET: b[0],
      WEIGHT:     b[1],
      MKT_VAL:    b[2],
      AVG_DUR:    +({'0-1Y':0.5,'1-3Y':2.1,'3-5Y':3.8,'5-7Y':5.9,'7-10Y':8.4,'10Y+':12.5})[b[0]]
    });
  });
});
durSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_duration_bucket.insertMany(durSeed);
print('  dwd_val_duration_bucket: ' + db.dwd_val_duration_bucket.countDocuments());

/* ================ 8. dwd_val_credit_bucket 信用分布 ================ */
ZY_KEYS.recreate('dwd_val_credit_bucket', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'CREDIT_BUCKET'],
  properties: {
    PORT_ID:       { bsonType: 'string' },
    BIZ_DT:        { bsonType: 'string' },
    CREDIT_BUCKET: { bsonType: 'string' }
  }
}});
db.dwd_val_credit_bucket.createIndex({ PORT_ID: 1, BIZ_DT: 1, CREDIT_BUCKET: 1 }, { unique: true });
// 5 组合 * 3 评级 = 15
var creditBucketMap = {
  'PORT001': [['AAA', 0.6315, 297880000], ['AA+', 0.2618, 123495000], ['AA', 0.1067,  50330000]],
  'PORT002': [['AAA', 0.7825, 3537300000], ['AAA-',0.1325, 598900000], ['AA+', 0.0850, 384390000]],
  'PORT003': [['AAA', 0.6644, 100150000], ['AA+', 0.3356,  50575000], ['AA',  0.0000,         0]],
  'PORT004': [['AAA', 0.8120, 3208650000], ['AAA-',0.1525, 602650000], ['AA+', 0.0355, 140350000]],
  'PORT005': [['AAA', 1.0000, 199120000], ['AA+', 0.0000,         0], ['AA',  0.0000,         0]]
};
var creditSeed = [];
PORTS.forEach(function (pid) {
  creditBucketMap[pid].forEach(function (b) {
    creditSeed.push({
      PORT_ID:       pid,
      BIZ_DT:        BIZ_DT,
      CREDIT_BUCKET: b[0],
      WEIGHT:        b[1],
      MKT_VAL:       b[2],
      RATING_AGENCY: '中诚信国际'
    });
  });
});
creditSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_credit_bucket.insertMany(creditSeed);
print('  dwd_val_credit_bucket: ' + db.dwd_val_credit_bucket.countDocuments());

/* ================ 9. dwd_val_sector_bucket 行业分布 ================ */
ZY_KEYS.recreate('dwd_val_sector_bucket', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'SECTOR'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' },
    SECTOR:  { bsonType: 'string' }
  }
}});
db.dwd_val_sector_bucket.createIndex({ PORT_ID: 1, BIZ_DT: 1, SECTOR: 1 }, { unique: true });
// 5 组合 * 3 行业 = 15
var sectorBucketMap = {
  'PORT001': [['利率债',  0.5602, 350395000], ['银行',     0.1689, 105625000], ['宽基ETF', 0.1267,  79200000]],
  'PORT002': [['利率债',  0.6325,2860615000], ['金融',     0.0900, 406800000], ['绿色债券',0.0775, 351225000]],
  'PORT003': [['银行',    0.5343, 92825000], ['宽基ETF',   0.2153,  37400000], ['ABS',     0.2884,  50075000]],
  'PORT004': [['利率债',  0.6018,3007350000], ['同业存单', 0.2417,1208400000], ['国债ETF', 0.0671, 335400000]],
  'PORT005': [['宽基ETF', 0.5103,1785960000], ['银行/保险',0.2027, 709325000], ['利率债',  0.0569, 199120000]]
};
var sectorSeed = [];
PORTS.forEach(function (pid) {
  sectorBucketMap[pid].forEach(function (b) {
    sectorSeed.push({
      PORT_ID: pid,
      BIZ_DT:  BIZ_DT,
      SECTOR:  b[0],
      WEIGHT:  b[1],
      MKT_VAL: b[2],
      ASSET_CNT: b[2] > 0 ? 2 : 0
    });
  });
});
sectorSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_sector_bucket.insertMany(sectorSeed);
print('  dwd_val_sector_bucket: ' + db.dwd_val_sector_bucket.countDocuments());

/* ================ 10. dwd_val_concentration 集中度 ================ */
ZY_KEYS.recreate('dwd_val_concentration', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'CONC_TYPE'],
  properties: {
    PORT_ID:   { bsonType: 'string' },
    BIZ_DT:    { bsonType: 'string' },
    CONC_TYPE: { bsonType: 'string' }
  }
}});
db.dwd_val_concentration.createIndex({ PORT_ID: 1, BIZ_DT: 1, CONC_TYPE: 1 }, { unique: true });
// 5 组合 * 2 维度(TOP1/TOP5) = 10
var concSeed = [
  // PORT001
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP1', RANK_DESC: '前1大持仓集中度', TOP_N: NumberInt(1), MKT_VAL: 199120000, RATIO: 0.1593, NOTE: '019601.IB 25国债03' },
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP5', RANK_DESC: '前5大持仓集中度', TOP_N: NumberInt(5), MKT_VAL: 656060000, RATIO: 0.5249, NOTE: '前5大资产合计占比' },
  // PORT002
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP1', RANK_DESC: '前1大持仓集中度', TOP_N: NumberInt(1), MKT_VAL: 796480000, RATIO: 0.1762, NOTE: '019601.IB 25国债03' },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP5', RANK_DESC: '前5大持仓集中度', TOP_N: NumberInt(5), MKT_VAL: 2962355000, RATIO: 0.6553, NOTE: '前5大资产合计占比' },
  // PORT003
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP1', RANK_DESC: '前1大持仓集中度', TOP_N: NumberInt(1), MKT_VAL: 100650000, RATIO: 0.1157, NOTE: '220215.IB 22国开15' },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP5', RANK_DESC: '前5大持仓集中度', TOP_N: NumberInt(5), MKT_VAL: 280950000, RATIO: 0.3229, NOTE: '前5大资产合计占比' },
  // PORT004
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP1', RANK_DESC: '前1大持仓集中度', TOP_N: NumberInt(1), MKT_VAL: 1494150000, RATIO: 0.2988, NOTE: '019601.IB 25国债03' },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP5', RANK_DESC: '前5大持仓集中度', TOP_N: NumberInt(5), MKT_VAL: 4551150000, RATIO: 0.9102, NOTE: '前5大资产合计占比' },
  // PORT005
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP1', RANK_DESC: '前1大持仓集中度', TOP_N: NumberInt(1), MKT_VAL: 1540000000, RATIO: 0.4400, NOTE: '510300.SH 沪深300ETF' },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, CONC_TYPE: 'TOP5', RANK_DESC: '前5大持仓集中度', TOP_N: NumberInt(5), MKT_VAL: 2694405000, RATIO: 0.7698, NOTE: '前5大资产合计占比' }
];
concSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_val_concentration.insertMany(concSeed);
print('  dwd_val_concentration: ' + db.dwd_val_concentration.countDocuments());

print('--- [04] valuation domain done ---');
