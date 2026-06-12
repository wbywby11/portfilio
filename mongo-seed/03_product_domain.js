/**
 * 产品域 dwd_ptl_* — 12 张表
 * 主键：PORT_ID (+ 业务日期/类别)
 *
 * 包含：
 *   1. dwd_ptl_info               产品基础信息
 *   2. dwd_ptl_holding            持仓明细
 *   3. dwd_ptl_nav_hist           净值历史
 *   4. dwd_ptl_return             收益率
 *   5. dwd_ptl_risk_indicator     风险指标
 *   6. dwd_ptl_benchmark          基准信息
 *   7. dwd_ptl_fee                费率信息
 *   8. dwd_ptl_investor           投资者结构
 *   9. dwd_ptl_limit              投资限制
 *  10. dwd_ptl_transaction_summary 交易汇总
 *  11. dwd_ptl_attribution        业绩归因
 *  12. dwd_ptl_compliance         合规检查记录
 */
load('_keys.js');
print('--- [03] product domain start ---');

var BIZ_DT = ZY_KEYS.BIZ_DT;
var PORTS  = ZY_KEYS.PORT_IDS;
var PORT_NAMES = ZY_KEYS.PORT_NAMES;
var AST_NAMES  = ZY_KEYS.AST_NAMES;
var aud        = ZY_KEYS.audit;

// 最近 6 个交易日（剔除 03-22/03-23 周末）
var TDAYS = ['20250317', '20250318', '20250319', '20250320', '20250321', '20250324'];

/* ================ 1. dwd_ptl_info 产品基础信息 ================ */
ZY_KEYS.recreate('dwd_ptl_info', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'PORT_NM', 'PORT_TYPE'],
  properties: {
    PORT_ID:   { bsonType: 'string' },
    PORT_NM:   { bsonType: 'string' },
    PORT_TYPE: { bsonType: 'string' }
  }
}});
db.dwd_ptl_info.createIndex({ PORT_ID: 1 }, { unique: true });
var ptlSeed = [
  {
    PORT_ID: 'PORT001', PORT_NM: '稳健配置一号', PORT_SHORT_NM: '稳健1号',
    PORT_TYPE: 'MIXED', RISK_LVL: 'R3', ESTAB_DT: '20210601', CCY: 'CNY',
    BENCHMARK: '中债综合财富指数*70%+沪深300*30%',
    SHR_NAV: 1.0512, ACC_NAV: 1.1835,
    AUM: 1250000000, TOTAL_SHARE: 1189250000,
    MGR_INST: 'ISR000008', CUSTODY_BANK: 'ISR000003',
    STATUS: 'ACTIVE',
    INV_SCOPE: '投资于固定收益类资产不低于基金资产净值的70%，权益类资产不超过30%，现金及到期日在一年以内的政府债券不低于5%。'
  },
  {
    PORT_ID: 'PORT002', PORT_NM: '纯债精选二号', PORT_SHORT_NM: '纯债2号',
    PORT_TYPE: 'BOND', RISK_LVL: 'R2', ESTAB_DT: '20200115', CCY: 'CNY',
    BENCHMARK: '中债-综合财富(总值)指数',
    SHR_NAV: 1.1086, ACC_NAV: 1.2563,
    AUM: 4520000000, TOTAL_SHARE: 4078026250,
    MGR_INST: 'ISR000005', CUSTODY_BANK: 'ISR000003',
    STATUS: 'ACTIVE',
    INV_SCOPE: '投资于固定收益类金融工具的比例不低于基金资产的80%，不直接投资于股票、权证等权益类资产。'
  },
  {
    PORT_ID: 'PORT003', PORT_NM: '混合增强三号', PORT_SHORT_NM: '混合3号',
    PORT_TYPE: 'MIXED', RISK_LVL: 'R4', ESTAB_DT: '20220301', CCY: 'CNY',
    BENCHMARK: '沪深300*60%+中债-综合财富指数*40%',
    SHR_NAV: 0.9683, ACC_NAV: 0.9683,
    AUM: 870000000, TOTAL_SHARE: 898378550,
    MGR_INST: 'ISR000008', CUSTODY_BANK: 'ISR000007',
    STATUS: 'ACTIVE',
    INV_SCOPE: '股票投资比例为基金资产的30%-80%，债券投资比例为20%-65%，权证投资比例不超过基金资产净值的3%。'
  },
  {
    PORT_ID: 'PORT004', PORT_NM: '短融货币四号', PORT_SHORT_NM: '货币4号',
    PORT_TYPE: 'MMF', RISK_LVL: 'R1', ESTAB_DT: '20190820', CCY: 'CNY',
    BENCHMARK: '七天通知存款利率(税后)',
    SHR_NAV: 1.0000, ACC_NAV: 1.1942,
    AUM: 5000000000, TOTAL_SHARE: 5000000000,
    MGR_INST: 'ISR000005', CUSTODY_BANK: 'ISR000003',
    STATUS: 'ACTIVE',
    INV_SCOPE: '投资于剩余期限不超过397天的现金、债券、回购及同业存单，组合平均剩余期限不超过120天。'
  },
  {
    PORT_ID: 'PORT005', PORT_NM: '指数增强五号', PORT_SHORT_NM: '指增5号',
    PORT_TYPE: 'INDEX', RISK_LVL: 'R4', ESTAB_DT: '20230408', CCY: 'CNY',
    BENCHMARK: '沪深300指数收益率*95%+银行活期存款利率(税后)*5%',
    SHR_NAV: 1.0289, ACC_NAV: 1.0289,
    AUM: 3500000000, TOTAL_SHARE: 3401690155,
    MGR_INST: 'ISR000008', CUSTODY_BANK: 'ISR000007',
    STATUS: 'ACTIVE',
    INV_SCOPE: '投资于沪深300成份股及备选成份股的资产比例不低于非现金基金资产的80%，力争跟踪误差日均不超过0.35%。'
  }
];
ptlSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ptl_info.insertMany(ptlSeed);
print('  dwd_ptl_info: ' + db.dwd_ptl_info.countDocuments());

/* ================ 2. dwd_ptl_holding 持仓明细 ================ */
ZY_KEYS.recreate('dwd_ptl_holding', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'AST_CD', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    AST_CD:  { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_ptl_holding.createIndex({ PORT_ID: 1, AST_CD: 1, BIZ_DT: 1 }, { unique: true });
// 每个组合 5 个持仓 - 与组合类型匹配的真实资产组合
var holdingMap = {
  'PORT001': [ // MIXED
    { cd: '019601.IB',  amt: 200000000, mv: 199120000,  cost: 198500000,  ratio: 0.1593, aci: 1520000, pl:  620000 },
    { cd: '230210.IB',  amt: 150000000, mv: 151275000,  cost: 150400000,  ratio: 0.1210, aci:  985000, pl:  875000 },
    { cd: '2480006.IB', amt: 120000000, mv: 120840000,  cost: 119800000,  ratio: 0.0967, aci:  720000, pl: 1040000 },
    { cd: '600036.SH',  amt:   2500000, mv: 105625000,  cost: 102000000,  ratio: 0.0845, aci:       0, pl: 3625000 },
    { cd: '510300.SH',  amt:  18000000, mv:  79200000,  cost:  78840000,  ratio: 0.0634, aci:       0, pl:  360000 }
  ],
  'PORT002': [ // BOND
    { cd: '019601.IB',  amt: 800000000, mv: 796480000,  cost: 794000000,  ratio: 0.1762, aci: 6080000, pl: 2480000 },
    { cd: '019735.IB',  amt: 700000000, mv: 706300000,  cost: 702800000,  ratio: 0.1562, aci: 5460000, pl: 3500000 },
    { cd: '230210.IB',  amt: 600000000, mv: 605100000,  cost: 601200000,  ratio: 0.1339, aci: 3940000, pl: 3900000 },
    { cd: '220215.IB',  amt: 500000000, mv: 503250000,  cost: 500500000,  ratio: 0.1113, aci: 3275000, pl: 2750000 },
    { cd: '180401.IB',  amt: 350000000, mv: 351225000,  cost: 350350000,  ratio: 0.0777, aci: 2310000, pl:  875000 }
  ],
  'PORT003': [ // MIXED (偏股)
    { cd: '601318.SH',  amt:    900000, mv:  46350000,  cost:  44550000,  ratio: 0.0533, aci:       0, pl: 1800000 },
    { cd: '600036.SH',  amt:   1100000, mv:  46475000,  cost:  44990000,  ratio: 0.0534, aci:       0, pl: 1485000 },
    { cd: '510300.SH',  amt:   8500000, mv:  37400000,  cost:  37145000,  ratio: 0.0430, aci:       0, pl:  255000 },
    { cd: '220215.IB',  amt: 100000000, mv: 100650000,  cost: 100100000,  ratio: 0.1157, aci:  655000, pl:  550000 },
    { cd: '127080.SZ',  amt:  50000000, mv:  50075000,  cost:  49850000,  ratio: 0.0576, aci:  282500, pl:  225000 }
  ],
  'PORT004': [ // MMF
    { cd: '019601.IB',  amt: 1500000000, mv: 1494150000, cost: 1488750000, ratio: 0.2988, aci: 11400000, pl: 5400000 },
    { cd: '2480006.IB', amt: 1200000000, mv: 1208400000, cost: 1198000000, ratio: 0.2417, aci:  7200000, pl: 10400000 },
    { cd: '019735.IB',  amt:  900000000, mv:  908100000, cost:  903600000, ratio: 0.1816, aci:  7020000, pl:  4500000 },
    { cd: '230210.IB',  amt:  600000000, mv:  605100000, cost:  601200000, ratio: 0.1210, aci:  3940000, pl:  3900000 },
    { cd: '511260.SH',  amt:    3000000, mv:  335400000, cost:  334050000, ratio: 0.0671, aci:        0, pl:  1350000 }
  ],
  'PORT005': [ // INDEX (跟踪沪深300)
    { cd: '510300.SH',  amt:  35000000, mv: 1540000000, cost: 1530550000, ratio: 0.4400, aci:       0, pl: 9450000 },
    { cd: '600036.SH',  amt:   8500000, mv:  359125000, cost:  351900000, ratio: 0.1026, aci:       0, pl: 7225000 },
    { cd: '601318.SH',  amt:   6800000, mv:  350200000, cost:  342720000, ratio: 0.1001, aci:       0, pl: 7480000 },
    { cd: '511260.SH',  amt:   2200000, mv:  245960000, cost:  244464000, ratio: 0.0703, aci:       0, pl: 1496000 },
    { cd: '019601.IB',  amt: 200000000, mv:  199120000, cost:  198400000, ratio: 0.0569, aci: 1520000, pl:  720000 }
  ]
};
var holdingSeed = [];
PORTS.forEach(function (pid) {
  holdingMap[pid].forEach(function (h) {
    holdingSeed.push({
      PORT_ID:    pid,
      AST_CD:     h.cd,
      AST_NM:     AST_NAMES[h.cd],
      HOLD_AMT:   h.amt,
      HOLD_MV:    h.mv,
      HOLD_COST:  h.cost,
      HOLD_RATIO: h.ratio,
      ACCRUED_INT: h.aci,
      FLOAT_PL:   h.pl,
      BIZ_DT:     BIZ_DT
    });
  });
});
holdingSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_ptl_holding.insertMany(holdingSeed);
print('  dwd_ptl_holding: ' + db.dwd_ptl_holding.countDocuments());

/* ================ 3. dwd_ptl_nav_hist 净值历史 ================ */
ZY_KEYS.recreate('dwd_ptl_nav_hist', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_ptl_nav_hist.createIndex({ PORT_ID: 1, BIZ_DT: 1 }, { unique: true });
// 每个组合 BIZ_DT (20250324) 的最终净值，往前推算 6 天
var navBaseMap = {
  'PORT001': { shr: 1.0512, acc: 1.1835 },
  'PORT002': { shr: 1.1086, acc: 1.2563 },
  'PORT003': { shr: 0.9683, acc: 0.9683 },
  'PORT004': { shr: 1.0000, acc: 1.1942 },
  'PORT005': { shr: 1.0289, acc: 1.0289 }
};
// 每天的微小波动（百分点），最后一天为基准
var navDeltaSeq = {
  'PORT001': [-0.0028, -0.0014, -0.0006,  0.0011,  0.0019,  0.0018],
  'PORT002': [-0.0011, -0.0006, -0.0002,  0.0004,  0.0008,  0.0007],
  'PORT003': [-0.0085, -0.0042,  0.0017, -0.0023,  0.0036, -0.0025],
  'PORT004': [ 0.0000,  0.0000,  0.0000,  0.0000,  0.0000,  0.0000],
  'PORT005': [-0.0072,  0.0048, -0.0035,  0.0029,  0.0021,  0.0010]
};
var navSeed = [];
PORTS.forEach(function (pid) {
  var base = navBaseMap[pid];
  var deltas = navDeltaSeq[pid];
  // 由最终净值倒推每个交易日净值
  var shrSeries = [];
  var accSeries = [];
  shrSeries[5] = base.shr; accSeries[5] = base.acc;
  for (var k = 4; k >= 0; k--) {
    shrSeries[k] = +(shrSeries[k + 1] - deltas[k + 1]).toFixed(6);
    accSeries[k] = +(accSeries[k + 1] - deltas[k + 1]).toFixed(6);
  }
  TDAYS.forEach(function (dt, idx) {
    var dayShr = pid === 'PORT004' ? 1.0000 : shrSeries[idx];
    var dayAcc = pid === 'PORT004' ? +(base.acc - (5 - idx) * 0.00018).toFixed(6) : accSeries[idx];
    navSeed.push({
      PORT_ID:  pid,
      BIZ_DT:   dt,
      SHR_NAV:  dayShr,
      ACC_NAV:  dayAcc,
      DAILY_RET: idx === 0 ? 0 : +((accSeries[idx] - accSeries[idx - 1]) / accSeries[idx - 1]).toFixed(6),
      NAV_STATUS: 'CONFIRMED'
    });
  });
});
navSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_ptl_nav_hist.insertMany(navSeed);
print('  dwd_ptl_nav_hist: ' + db.dwd_ptl_nav_hist.countDocuments());

/* ================ 4. dwd_ptl_return 收益率 ================ */
ZY_KEYS.recreate('dwd_ptl_return', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_ptl_return.createIndex({ PORT_ID: 1, BIZ_DT: 1 }, { unique: true });
// 5 组合 * 5 个统计日 = 25 条
var retDays = ['20250318', '20250319', '20250320', '20250321', '20250324'];
var retBaseMap = {
  'PORT001': { d:  0.00171, w:  0.00382, m:  0.00614, y:  0.02145 },
  'PORT002': { d:  0.00063, w:  0.00154, m:  0.00298, y:  0.01187 },
  'PORT003': { d: -0.00258, w: -0.00714, m:  0.01205, y: -0.03172 },
  'PORT004': { d:  0.00006, w:  0.00041, m:  0.00185, y:  0.00564 },
  'PORT005': { d:  0.00097, w:  0.00428, m: -0.00536, y:  0.02893 }
};
var retSeed = [];
PORTS.forEach(function (pid) {
  var rb = retBaseMap[pid];
  retDays.forEach(function (dt, idx) {
    var jitter = (idx - 2) * 0.00012;
    retSeed.push({
      PORT_ID:    pid,
      BIZ_DT:     dt,
      DAILY_RET:  +(rb.d + jitter).toFixed(6),
      WEEKLY_RET: +(rb.w + jitter * 2).toFixed(6),
      MTD_RET:    +(rb.m + idx * 0.00021).toFixed(6),
      YTD_RET:    +(rb.y + idx * 0.00038).toFixed(6),
      BENCH_DAILY_RET: +((rb.d + jitter) * 0.85).toFixed(6),
      EXCESS_RET: +((rb.d + jitter) * 0.15).toFixed(6)
    });
  });
});
retSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_ptl_return.insertMany(retSeed);
print('  dwd_ptl_return: ' + db.dwd_ptl_return.countDocuments());

/* ================ 5. dwd_ptl_risk_indicator 风险指标 ================ */
ZY_KEYS.recreate('dwd_ptl_risk_indicator', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_ptl_risk_indicator.createIndex({ PORT_ID: 1, BIZ_DT: 1 }, { unique: true });
var riskSeed = [
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, VOL: 0.0683, MAX_DRAWDOWN: -0.0512, SHARPE: 1.42, TRACKING_ERROR: 0.0218, INFO_RATIO: 0.78, BETA: 0.34, VAR_95: -0.0142, CALMAR: 0.85 },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, VOL: 0.0234, MAX_DRAWDOWN: -0.0186, SHARPE: 2.05, TRACKING_ERROR: 0.0089, INFO_RATIO: 1.12, BETA: 0.08, VAR_95: -0.0048, CALMAR: 1.92 },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, VOL: 0.1735, MAX_DRAWDOWN: -0.1842, SHARPE: 0.32, TRACKING_ERROR: 0.0428, INFO_RATIO: -0.45, BETA: 0.92, VAR_95: -0.0356, CALMAR: 0.18 },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, VOL: 0.0042, MAX_DRAWDOWN: -0.0008, SHARPE: 3.85, TRACKING_ERROR: 0.0015, INFO_RATIO: 2.34, BETA: 0.01, VAR_95: -0.0009, CALMAR: 8.20 },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, VOL: 0.1582, MAX_DRAWDOWN: -0.1256, SHARPE: 0.95, TRACKING_ERROR: 0.0312, INFO_RATIO: 0.86, BETA: 0.97, VAR_95: -0.0328, CALMAR: 0.62 }
];
riskSeed.forEach(function (d) {
  d.RISK_FREE_RATE = 0.0210;
  d.OBS_PERIOD = 'TRAILING_1Y';
  Object.assign(d, aud());
});
db.dwd_ptl_risk_indicator.insertMany(riskSeed);
print('  dwd_ptl_risk_indicator: ' + db.dwd_ptl_risk_indicator.countDocuments());

/* ================ 6. dwd_ptl_benchmark 基准信息 ================ */
ZY_KEYS.recreate('dwd_ptl_benchmark', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_ptl_benchmark.createIndex({ PORT_ID: 1, BIZ_DT: 1 }, { unique: true });
var bmSeed = [
  {
    PORT_ID: 'PORT001', BIZ_DT: BIZ_DT,
    BENCHMARK_NM: '中债综合财富指数*70%+沪深300*30%',
    COMPONENTS: [
      { CD: 'CBA00203.CS', NM: '中债-综合财富(总值)指数', WGT: 0.70 },
      { CD: '000300.SH',   NM: '沪深300', WGT: 0.30 }
    ],
    BENCH_DAILY_RET: 0.00145,
    BENCH_YTD_RET:   0.01823,
    BENCH_1Y_RET:    0.06542
  },
  {
    PORT_ID: 'PORT002', BIZ_DT: BIZ_DT,
    BENCHMARK_NM: '中债-综合财富(总值)指数',
    COMPONENTS: [
      { CD: 'CBA00203.CS', NM: '中债-综合财富(总值)指数', WGT: 1.00 }
    ],
    BENCH_DAILY_RET: 0.00056,
    BENCH_YTD_RET:   0.00984,
    BENCH_1Y_RET:    0.04812
  },
  {
    PORT_ID: 'PORT003', BIZ_DT: BIZ_DT,
    BENCHMARK_NM: '沪深300*60%+中债-综合财富指数*40%',
    COMPONENTS: [
      { CD: '000300.SH',   NM: '沪深300', WGT: 0.60 },
      { CD: 'CBA00203.CS', NM: '中债-综合财富(总值)指数', WGT: 0.40 }
    ],
    BENCH_DAILY_RET: -0.00185,
    BENCH_YTD_RET:   -0.02568,
    BENCH_1Y_RET:    -0.04127
  },
  {
    PORT_ID: 'PORT004', BIZ_DT: BIZ_DT,
    BENCHMARK_NM: '七天通知存款利率(税后)',
    COMPONENTS: [
      { CD: 'NOTICE7D.CN', NM: '七天通知存款利率(税后)', WGT: 1.00 }
    ],
    BENCH_DAILY_RET: 0.00004,
    BENCH_YTD_RET:   0.00302,
    BENCH_1Y_RET:    0.01368
  },
  {
    PORT_ID: 'PORT005', BIZ_DT: BIZ_DT,
    BENCHMARK_NM: '沪深300指数收益率*95%+银行活期存款利率(税后)*5%',
    COMPONENTS: [
      { CD: '000300.SH',   NM: '沪深300', WGT: 0.95 },
      { CD: 'DEMAND.CN',   NM: '银行活期存款利率(税后)', WGT: 0.05 }
    ],
    BENCH_DAILY_RET: 0.00102,
    BENCH_YTD_RET:   0.02715,
    BENCH_1Y_RET:    -0.01284
  }
];
bmSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_ptl_benchmark.insertMany(bmSeed);
print('  dwd_ptl_benchmark: ' + db.dwd_ptl_benchmark.countDocuments());

/* ================ 7. dwd_ptl_fee 费率信息 ================ */
ZY_KEYS.recreate('dwd_ptl_fee', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'EFF_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    EFF_DT:  { bsonType: 'string' }
  }
}});
db.dwd_ptl_fee.createIndex({ PORT_ID: 1, EFF_DT: 1 }, { unique: true });
var feeSeed = [
  { PORT_ID: 'PORT001', EFF_DT: '20210601', MGT_FEE_RATE: 0.0120, CUSTODY_FEE_RATE: 0.0020, SUB_FEE_RATE: 0.0120, RDM_FEE_RATE: 0.0050, SALES_FEE_RATE: 0.0040, PERF_FEE_RATE: 0.20, PERF_FEE_BENCHMARK: '年化4%', FEE_CURRENCY: 'CNY' },
  { PORT_ID: 'PORT002', EFF_DT: '20200115', MGT_FEE_RATE: 0.0070, CUSTODY_FEE_RATE: 0.0020, SUB_FEE_RATE: 0.0080, RDM_FEE_RATE: 0.0015, SALES_FEE_RATE: 0.0025, PERF_FEE_RATE: 0.00, PERF_FEE_BENCHMARK: null,    FEE_CURRENCY: 'CNY' },
  { PORT_ID: 'PORT003', EFF_DT: '20220301', MGT_FEE_RATE: 0.0150, CUSTODY_FEE_RATE: 0.0025, SUB_FEE_RATE: 0.0150, RDM_FEE_RATE: 0.0075, SALES_FEE_RATE: 0.0050, PERF_FEE_RATE: 0.20, PERF_FEE_BENCHMARK: '年化6%', FEE_CURRENCY: 'CNY' },
  { PORT_ID: 'PORT004', EFF_DT: '20190820', MGT_FEE_RATE: 0.0033, CUSTODY_FEE_RATE: 0.0008, SUB_FEE_RATE: 0.0000, RDM_FEE_RATE: 0.0000, SALES_FEE_RATE: 0.0010, PERF_FEE_RATE: 0.00, PERF_FEE_BENCHMARK: null,    FEE_CURRENCY: 'CNY' },
  { PORT_ID: 'PORT005', EFF_DT: '20230408', MGT_FEE_RATE: 0.0100, CUSTODY_FEE_RATE: 0.0020, SUB_FEE_RATE: 0.0100, RDM_FEE_RATE: 0.0050, SALES_FEE_RATE: 0.0030, PERF_FEE_RATE: 0.10, PERF_FEE_BENCHMARK: '相对沪深300超额收益', FEE_CURRENCY: 'CNY' }
];
feeSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_ptl_fee.insertMany(feeSeed);
print('  dwd_ptl_fee: ' + db.dwd_ptl_fee.countDocuments());

/* ================ 8. dwd_ptl_investor 投资者结构 ================ */
ZY_KEYS.recreate('dwd_ptl_investor', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'INVESTOR_TYPE'],
  properties: {
    PORT_ID:       { bsonType: 'string' },
    BIZ_DT:        { bsonType: 'string' },
    INVESTOR_TYPE: { bsonType: 'string' }
  }
}});
db.dwd_ptl_investor.createIndex({ PORT_ID: 1, BIZ_DT: 1, INVESTOR_TYPE: 1 }, { unique: true });
var invSeed = [];
var investorMix = {
  'PORT001': { instRatio: 0.5824, indvRatio: 0.4176, top10: 0.4258, instCnt:  18, indvCnt: 1845 },
  'PORT002': { instRatio: 0.7821, indvRatio: 0.2179, top10: 0.6517, instCnt:  42, indvCnt:  876 },
  'PORT003': { instRatio: 0.2415, indvRatio: 0.7585, top10: 0.2864, instCnt:   9, indvCnt: 2354 },
  'PORT004': { instRatio: 0.6953, indvRatio: 0.3047, top10: 0.5728, instCnt:  76, indvCnt: 5210 },
  'PORT005': { instRatio: 0.4392, indvRatio: 0.5608, top10: 0.3915, instCnt:  31, indvCnt: 1623 }
};
PORTS.forEach(function (pid) {
  var info = ptlSeed[PORTS.indexOf(pid)];
  var mix  = investorMix[pid];
  invSeed.push({
    PORT_ID: pid, BIZ_DT: BIZ_DT, INVESTOR_TYPE: 'INSTITUTION',
    HOLDER_CNT: mix.instCnt,
    HOLD_SHARE: Math.round(info.TOTAL_SHARE * mix.instRatio),
    HOLD_AMT:   Math.round(info.AUM * mix.instRatio),
    HOLD_RATIO: mix.instRatio,
    TOP10_RATIO: mix.top10
  });
  invSeed.push({
    PORT_ID: pid, BIZ_DT: BIZ_DT, INVESTOR_TYPE: 'INDIVIDUAL',
    HOLDER_CNT: mix.indvCnt,
    HOLD_SHARE: Math.round(info.TOTAL_SHARE * mix.indvRatio),
    HOLD_AMT:   Math.round(info.AUM * mix.indvRatio),
    HOLD_RATIO: mix.indvRatio,
    TOP10_RATIO: +(mix.top10 * 0.35).toFixed(4)
  });
});
invSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_ptl_investor.insertMany(invSeed);
print('  dwd_ptl_investor: ' + db.dwd_ptl_investor.countDocuments());

/* ================ 9. dwd_ptl_limit 投资限制 ================ */
ZY_KEYS.recreate('dwd_ptl_limit', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'LIMIT_TYPE'],
  properties: {
    PORT_ID:    { bsonType: 'string' },
    LIMIT_TYPE: { bsonType: 'string' }
  }
}});
db.dwd_ptl_limit.createIndex({ PORT_ID: 1, LIMIT_TYPE: 1, CHECK_DT: 1 }, { unique: true });
var limitSeed = [
  // PORT001 MIXED - 3 项
  { PORT_ID: 'PORT001', LIMIT_TYPE: 'SINGLE_BOND',     LIMIT_DESC: '单一债券持仓不超过基金净资产的10%',                LIMIT_VALUE: 0.1000, CURRENT_VALUE: 0.1593, STATUS: 'BREACH',  CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT001', LIMIT_TYPE: 'EQUITY_CAP',      LIMIT_DESC: '股票及权益类资产合计不超过基金资产净值的30%',     LIMIT_VALUE: 0.3000, CURRENT_VALUE: 0.1479, STATUS: 'NORMAL',  CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT001', LIMIT_TYPE: 'CASH_FLOOR',      LIMIT_DESC: '现金及到期日在一年以内的政府债券不低于5%',         LIMIT_VALUE: 0.0500, CURRENT_VALUE: 0.0613, STATUS: 'NORMAL',  CHECK_DT: BIZ_DT },
  // PORT002 BOND - 3 项
  { PORT_ID: 'PORT002', LIMIT_TYPE: 'BOND_FLOOR',      LIMIT_DESC: '固定收益类资产投资比例不低于基金资产的80%',       LIMIT_VALUE: 0.8000, CURRENT_VALUE: 0.9215, STATUS: 'NORMAL',  CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT002', LIMIT_TYPE: 'CREDIT_BOND',     LIMIT_DESC: '信用债持仓比例不超过基金资产净值的50%',           LIMIT_VALUE: 0.5000, CURRENT_VALUE: 0.4823, STATUS: 'WARNING', CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT002', LIMIT_TYPE: 'DURATION',        LIMIT_DESC: '组合修正久期控制在3-7年区间',                     LIMIT_VALUE: 7.0000, CURRENT_VALUE: 5.6800, STATUS: 'NORMAL',  CHECK_DT: BIZ_DT },
  // PORT003 MIXED 偏股 - 3 项
  { PORT_ID: 'PORT003', LIMIT_TYPE: 'EQUITY_RANGE',    LIMIT_DESC: '股票投资比例为基金资产的30%-80%',                 LIMIT_VALUE: 0.8000, CURRENT_VALUE: 0.1497, STATUS: 'BREACH',  CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT003', LIMIT_TYPE: 'SINGLE_STOCK',    LIMIT_DESC: '单只股票持仓不超过基金净资产的10%',               LIMIT_VALUE: 0.1000, CURRENT_VALUE: 0.0534, STATUS: 'NORMAL',  CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT003', LIMIT_TYPE: 'WARRANT_CAP',     LIMIT_DESC: '权证投资比例不超过基金资产净值的3%',             LIMIT_VALUE: 0.0300, CURRENT_VALUE: 0.0000, STATUS: 'NORMAL',  CHECK_DT: BIZ_DT },
  // PORT004 MMF - 3 项
  { PORT_ID: 'PORT004', LIMIT_TYPE: 'AVG_MATURITY',    LIMIT_DESC: '组合平均剩余期限不得超过120天',                   LIMIT_VALUE: 120.00, CURRENT_VALUE: 87.5000, STATUS: 'NORMAL', CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT004', LIMIT_TYPE: 'MAX_MATURITY',    LIMIT_DESC: '单只投资品种剩余期限不得超过397天',               LIMIT_VALUE: 397.00, CURRENT_VALUE: 365.0000, STATUS: 'NORMAL', CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT004', LIMIT_TYPE: 'NEG_DEVIATION',   LIMIT_DESC: '影子定价偏离度负向不得超过-0.25%',                LIMIT_VALUE: -0.0025, CURRENT_VALUE: -0.0008, STATUS: 'NORMAL', CHECK_DT: BIZ_DT },
  // PORT005 INDEX - 3 项
  { PORT_ID: 'PORT005', LIMIT_TYPE: 'INDEX_TRACK',     LIMIT_DESC: '投资于沪深300成份股的资产比例不低于非现金基金资产的80%', LIMIT_VALUE: 0.8000, CURRENT_VALUE: 0.6427, STATUS: 'BREACH', CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT005', LIMIT_TYPE: 'TRACK_ERR_CAP',   LIMIT_DESC: '日均跟踪误差不超过0.35%',                         LIMIT_VALUE: 0.0035, CURRENT_VALUE: 0.0028, STATUS: 'WARNING', CHECK_DT: BIZ_DT },
  { PORT_ID: 'PORT005', LIMIT_TYPE: 'STOCK_INDEX_DEV', LIMIT_DESC: '个股权重相对成份股权重的偏离不超过2个百分点',     LIMIT_VALUE: 0.0200, CURRENT_VALUE: 0.0142, STATUS: 'NORMAL',  CHECK_DT: BIZ_DT }
];
limitSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_ptl_limit.insertMany(limitSeed);
print('  dwd_ptl_limit: ' + db.dwd_ptl_limit.countDocuments());

/* ================ 10. dwd_ptl_transaction_summary 交易汇总 ================ */
ZY_KEYS.recreate('dwd_ptl_transaction_summary', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT'],
  properties: {
    PORT_ID: { bsonType: 'string' },
    BIZ_DT:  { bsonType: 'string' }
  }
}});
db.dwd_ptl_transaction_summary.createIndex({ PORT_ID: 1, BIZ_DT: 1 }, { unique: true });
var txnSumSeed = [
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, BUY_CNT: 12, BUY_AMT:  85420000, SELL_CNT:  8, SELL_AMT:  62150000, NET_AMT:  23270000, TURNOVER: 147570000, TURNOVER_RATIO: 0.1181, TOTAL_FEE:  44271 },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, BUY_CNT: 26, BUY_AMT: 425600000, SELL_CNT: 18, SELL_AMT: 318740000, NET_AMT: 106860000, TURNOVER: 744340000, TURNOVER_RATIO: 0.1646, TOTAL_FEE: 223302 },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, BUY_CNT:  9, BUY_AMT:  42850000, SELL_CNT: 15, SELL_AMT:  68350000, NET_AMT: -25500000, TURNOVER: 111200000, TURNOVER_RATIO: 0.1278, TOTAL_FEE:  55600 },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, BUY_CNT: 38, BUY_AMT: 985200000, SELL_CNT: 32, SELL_AMT: 920500000, NET_AMT:  64700000, TURNOVER:1905700000, TURNOVER_RATIO: 0.3811, TOTAL_FEE: 142927 },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, BUY_CNT: 21, BUY_AMT: 156800000, SELL_CNT: 17, SELL_AMT: 132480000, NET_AMT:  24320000, TURNOVER: 289280000, TURNOVER_RATIO: 0.0826, TOTAL_FEE:  86784 }
];
txnSumSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_ptl_transaction_summary.insertMany(txnSumSeed);
print('  dwd_ptl_transaction_summary: ' + db.dwd_ptl_transaction_summary.countDocuments());

/* ================ 11. dwd_ptl_attribution 业绩归因 ================ */
ZY_KEYS.recreate('dwd_ptl_attribution', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'BIZ_DT', 'ATTR_FACTOR'],
  properties: {
    PORT_ID:     { bsonType: 'string' },
    BIZ_DT:      { bsonType: 'string' },
    ATTR_FACTOR: { bsonType: 'string' }
  }
}});
db.dwd_ptl_attribution.createIndex({ PORT_ID: 1, BIZ_DT: 1, ATTR_FACTOR: 1 }, { unique: true });
var attrSeed = [
  // PORT001 MIXED - 利率/信用
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'INTEREST_RATE', ATTR_DESC: '利率因子贡献(久期暴露收益)',  CONTRIBUTION:  0.00072, WEIGHT: 0.4218 },
  { PORT_ID: 'PORT001', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'CREDIT_SPREAD', ATTR_DESC: '信用利差因子贡献',            CONTRIBUTION:  0.00028, WEIGHT: 0.1639 },
  // PORT002 BOND - 利率/选券
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'INTEREST_RATE', ATTR_DESC: '利率因子贡献(国开债波动)',    CONTRIBUTION:  0.00041, WEIGHT: 0.6512 },
  { PORT_ID: 'PORT002', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'BOND_SELECT',   ATTR_DESC: '个券选择超额收益',            CONTRIBUTION:  0.00015, WEIGHT: 0.2375 },
  // PORT003 MIXED - 选券/交易
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'STOCK_SELECT',  ATTR_DESC: '个股选择对超额的贡献',        CONTRIBUTION: -0.00148, WEIGHT: 0.1497 },
  { PORT_ID: 'PORT003', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'TRADING',       ATTR_DESC: '交易因子(择时与冲击成本)',    CONTRIBUTION: -0.00064, WEIGHT: 0.1278 },
  // PORT004 MMF - 利率/交易
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'INTEREST_RATE', ATTR_DESC: '资金面利率因子',              CONTRIBUTION:  0.00005, WEIGHT: 0.8210 },
  { PORT_ID: 'PORT004', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'TRADING',       ATTR_DESC: '回购套息交易贡献',            CONTRIBUTION:  0.00001, WEIGHT: 0.1145 },
  // PORT005 INDEX - 选券/交易
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'STOCK_SELECT',  ATTR_DESC: '增强选股因子相对沪深300超额', CONTRIBUTION:  0.00086, WEIGHT: 0.6427 },
  { PORT_ID: 'PORT005', BIZ_DT: BIZ_DT, ATTR_FACTOR: 'TRADING',       ATTR_DESC: '调仓交易贡献(冲击成本扣除)',  CONTRIBUTION: -0.00012, WEIGHT: 0.0826 }
];
attrSeed.forEach(function (d) { Object.assign(d, aud()); });
db.dwd_ptl_attribution.insertMany(attrSeed);
print('  dwd_ptl_attribution: ' + db.dwd_ptl_attribution.countDocuments());

/* ================ 12. dwd_ptl_compliance 合规检查记录 ================ */
ZY_KEYS.recreate('dwd_ptl_compliance', { $jsonSchema: {
  bsonType: 'object',
  required: ['PORT_ID', 'CHECK_DT', 'CHECK_ITEM'],
  properties: {
    PORT_ID:    { bsonType: 'string' },
    CHECK_DT:   { bsonType: 'string' },
    CHECK_ITEM: { bsonType: 'string' }
  }
}});
db.dwd_ptl_compliance.createIndex({ PORT_ID: 1, CHECK_DT: 1, CHECK_ITEM: 1 }, { unique: true });
var compSeed = [
  // PORT001
  { PORT_ID: 'PORT001', CHECK_DT: BIZ_DT, CHECK_ITEM: 'SINGLE_BOND_10PCT',     CHECK_DESC: '单一债券持仓占比检查(≤10%)',     RESULT: 'FAIL', VIOLATION: '019601.IB持仓占比15.93%，超过10%上限',          ACTION: '已发起减持指令，预计T+2日内调整至限额内', LEVEL: 'MAJOR' },
  { PORT_ID: 'PORT001', CHECK_DT: BIZ_DT, CHECK_ITEM: 'EQUITY_30PCT_CAP',      CHECK_DESC: '权益类资产占比检查(≤30%)',         RESULT: 'PASS', VIOLATION: null,                                            ACTION: null,                                       LEVEL: 'INFO'  },
  // PORT002
  { PORT_ID: 'PORT002', CHECK_DT: BIZ_DT, CHECK_ITEM: 'BOND_FLOOR_80PCT',      CHECK_DESC: '固收资产占比检查(≥80%)',           RESULT: 'PASS', VIOLATION: null,                                            ACTION: null,                                       LEVEL: 'INFO'  },
  { PORT_ID: 'PORT002', CHECK_DT: BIZ_DT, CHECK_ITEM: 'CREDIT_BOND_50PCT',     CHECK_DESC: '信用债占比检查(≤50%)',             RESULT: 'WARN', VIOLATION: '当前信用债占比48.23%，接近50%警戒线',           ACTION: '加入观察名单，暂停新增信用债增量',         LEVEL: 'MINOR' },
  // PORT003
  { PORT_ID: 'PORT003', CHECK_DT: BIZ_DT, CHECK_ITEM: 'EQUITY_30TO80PCT',      CHECK_DESC: '股票投资比例检查(30%-80%)',        RESULT: 'FAIL', VIOLATION: '当前股票占比14.97%，低于30%下限',                ACTION: '基金经理已提交调仓方案，将逐步增配权益资产', LEVEL: 'MAJOR' },
  { PORT_ID: 'PORT003', CHECK_DT: BIZ_DT, CHECK_ITEM: 'SINGLE_STOCK_10PCT',    CHECK_DESC: '单只股票持仓占比检查(≤10%)',       RESULT: 'PASS', VIOLATION: null,                                            ACTION: null,                                       LEVEL: 'INFO'  },
  // PORT004
  { PORT_ID: 'PORT004', CHECK_DT: BIZ_DT, CHECK_ITEM: 'AVG_MATURITY_120D',     CHECK_DESC: '组合平均剩余期限检查(≤120天)',     RESULT: 'PASS', VIOLATION: null,                                            ACTION: null,                                       LEVEL: 'INFO'  },
  { PORT_ID: 'PORT004', CHECK_DT: BIZ_DT, CHECK_ITEM: 'SHADOW_PRICE_DEVIATION', CHECK_DESC: '影子定价偏离度检查(±0.25%)',       RESULT: 'PASS', VIOLATION: null,                                            ACTION: null,                                       LEVEL: 'INFO'  },
  // PORT005
  { PORT_ID: 'PORT005', CHECK_DT: BIZ_DT, CHECK_ITEM: 'INDEX_COMPONENT_80PCT', CHECK_DESC: '沪深300成份股占比检查(≥非现金资产80%)', RESULT: 'FAIL', VIOLATION: '当前成份股占比64.27%，低于80%下限',           ACTION: '已与基金经理沟通，将于T+5日内完成补仓',     LEVEL: 'MAJOR' },
  { PORT_ID: 'PORT005', CHECK_DT: BIZ_DT, CHECK_ITEM: 'TRACKING_ERROR_35BPS',  CHECK_DESC: '日均跟踪误差检查(≤0.35%)',         RESULT: 'WARN', VIOLATION: '当前TE=0.28%，接近警戒线',                       ACTION: '加密复盘频率，每日核查权重偏离',           LEVEL: 'MINOR' }
];
compSeed.forEach(function (d) { d.CHECKER = 'COMPLIANCE_AUTO'; Object.assign(d, aud()); });
db.dwd_ptl_compliance.insertMany(compSeed);
print('  dwd_ptl_compliance: ' + db.dwd_ptl_compliance.countDocuments());

print('--- [03] product domain done ---');
