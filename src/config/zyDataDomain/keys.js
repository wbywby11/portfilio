/**
 * ZY 数据域跨表主键池 / 枚举值
 * 与 mongo-seed/_keys.js 保持一致；用于动态表单的下拉选项与外键提示
 */

export const BIZ_DT = '20250324';

// AST_CDS: 150 (80 债券 + 30 股票 + 30 基金 + 10 其他)
export const AST_CDS = [
  // === 国债 CGB (20) ===
  '019601.IB', '019735.IB', '230210.IB', '230015.IB', '230018.IB',
  '220003.IB', '210009.IB', '200006.IB', '190015.IB', '240001.IB',
  '240007.IB', '240012.IB', '230001.SH', '210210.IB', '250001.IB',
  '250005.IB', '200016.IB', '220018.IB', '230204.IB', '240020.IB',
  // === 政金债 POLICY (15) ===
  '210205.IB', '220210.IB', '230210K.IB', '240205.IB', '240210.IB',
  '250203.IB', '250205.IB', '220305.IB', '230310.IB', '240310.IB',
  '220405.IB', '230410.IB', '240410.IB', '250203P.IB', '250410.IB',
  // === MTN (20) ===
  '102481234.IB', '102482156.IB', '102481508.IB', '102481600.IB', '102481700.IB',
  '102382020.IB', '102382185.IB', '102382500.IB', '102282020.IB', '102282156.IB',
  '102481805.IB', '102481906.IB', '102481950.IB', '102482020.IB', '102482100.IB',
  '102482280.IB', '102482350.IB', '102482420.IB', '102382820.IB', '102382900.IB',
  // === 企业债 (15) ===
  '012583456.IB', '012583789.IB', '012583820.IB', '012583900.IB', '012584020.IB',
  '012483156.IB', '012483420.IB', '012383020.IB', '012584150.IB', '012584200.IB',
  '012584300.IB', '012584400.IB', '012584500.IB', '012584600.IB', '012584700.IB',
  // === 可转债 (5) ===
  '113062.SH', '113065.SH', '128136.SZ', '110085.SH', '128145.SZ',
  // === 同业存单 (5) ===
  '112501234.SH', '112501500.SH', '112501800.SH', '112502000.SH', '112502200.SH',
  // === A 股 (30) ===
  '600036.SH', '601398.SH', '601939.SH', '601288.SH', '601988.SH',
  '600000.SH', '601166.SH', '601328.SH', '600519.SH', '600276.SH',
  '600900.SH', '601318.SH', '601628.SH', '601857.SH', '600028.SH',
  '601088.SH', '600585.SH', '600887.SH', '601012.SH', '600438.SH',
  '600104.SH', '601238.SH', '600009.SH', '601088B.SH', '000001.SZ',
  '000725.SZ', '000651.SZ', '000333.SZ', '300750.SZ', '300059.SZ',
  // === 基金 (30) ===
  '510300.SH', '510500.SH', '510050.SH', '159915.SZ', '159949.SZ',
  '512100.SH', '512000.SH', '512880.SH', '512170.SH', '510900.SH',
  '159920.SZ', '588000.SH', '159995.SZ', '512760.SH', '161725.SZ',
  '161005.SZ', '166019.SZ', '163406.SZ', '501050.SH', '501018.SH',
  '000595.OF', '110011.OF', '161005.OF', '001186.OF', '000001.OF',
  '000300.OF', '100025.OF', '000198.OF', '000509.OF', '270005.OF',
  // === 其他 (10) ===
  '000300.SH', '000905.SH', '399006.SZ', 'CBA00301.CS', 'H11001.CSI',
  'R001.IB', 'R007.IB', 'GC001.SH', 'GC007.SH', '188888.IB'
];

// PORT_IDS: 30 (10 货币 + 8 债券 + 6 混合 + 4 股票 + 2 FOF)
export const PORT_IDS = [
  'PORT001', 'PORT002', 'PORT003', 'PORT004', 'PORT005',
  'PORT006', 'PORT007', 'PORT008', 'PORT009', 'PORT010',
  'PORT011', 'PORT012', 'PORT013', 'PORT014', 'PORT015',
  'PORT016', 'PORT017', 'PORT018', 'PORT019', 'PORT020',
  'PORT021', 'PORT022', 'PORT023', 'PORT024', 'PORT025',
  'PORT026', 'PORT027', 'PORT028', 'PORT029', 'PORT030'
];

// ISR_IDS: 60 (部妔2 + 政策银3 + 国有大5 + 股份行/城商行15 + 企业25 + 其他10)
export const ISR_IDS = Array.from({ length: 60 }, (_, i) => `ISR${String(i + 1).padStart(6, '0')}`);

// CNTP_IDS: 20 (券商 10 + 银行 10)
export const CNTP_IDS = Array.from({ length: 20 }, (_, i) => `CNTP${String(i + 1).padStart(5, '0')}`);

// CUSTOMER_IDS: 200 (150 个人 + 50 机构)
export const CUSTOMER_IDS = Array.from({ length: 200 }, (_, i) => `CUS${String(i + 1).padStart(7, '0')}`);

// SELLER_IDS: 30
export const SELLER_IDS = Array.from({ length: 30 }, (_, i) => `SEL${String(i + 1).padStart(5, '0')}`);

// INDEX_CDS: 20
export const INDEX_CDS = [
  '000300.SH', '000905.SH', '000852.SH', '000016.SH', '000001.SH',
  '399006.SZ', '399001.SZ', '000688.SH', '399330.SZ', '000922.SH',
  'CBA00301.CS', 'CBA00601.CS', 'CBA02701.CS', 'H11001.CSI', 'H11023.CSI',
  'H11077.CSI', 'NH0100.NHF', 'NH0200.NHF', 'NH0300.NHF', 'NH0400.NHF'
];

// CURVE_IDS: 12
export const CURVE_IDS = [
  'CGB', 'CDB', 'IMP_EXP', 'AGRI_DEV', 'AAA_MTN', 'AA+_MTN',
  'AA_MTN', 'AAAm_NCD', 'SHIBOR', 'FR007_IRS', 'USD_LIBOR', 'USD_TREAS'
];

// RATE_CDS: 15
export const RATE_CDS = [
  'SHIBOR_ON', 'SHIBOR_1W', 'SHIBOR_2W', 'SHIBOR_1M', 'SHIBOR_3M',
  'SHIBOR_6M', 'SHIBOR_9M', 'SHIBOR_1Y', 'LPR_1Y', 'LPR_5Y',
  'DR001', 'DR007', 'R001', 'R007', 'NCD_3M_AAA'
];

export const RATING_AGENCIES = ['中诚信国际', '联合资信', '大公国际', '东方金诚'];

export const CCY = ['CNY', 'USD', 'EUR', 'JPY', 'HKD', 'GBP'];

export const AST_TYPE = ['BOND', 'STOCK', 'FUND', 'MMF', 'REPO', 'INDEX'];
export const AST_SUB_TYPE = ['CGB', 'POLICY', 'MTN', 'NCD', 'ENTERPRISE', 'CB', 'ETF', 'LOF', 'MMF', 'OPEN', 'A_SHARE', 'INDEX', 'REPO'];
export const ISR_TYPE = ['SOVEREIGN', 'POLICY_BANK', 'COMMERCIAL_BANK', 'CORPORATE', 'SECURITIES'];
export const MARKET = ['IB', 'SSE', 'SZSE', 'EXCH'];
export const BOND_TERM = ['3M', '6M', '1Y', '3Y', '5Y', '7Y', '10Y', '30Y'];
export const PORT_TYPE = ['MMF', 'BOND', 'EQUITY', 'MIXED', 'INDEX', 'FOF'];
export const RISK_LVL = ['R1', 'R2', 'R3', 'R4', 'R5', 'C1', 'C2', 'C3', 'C4', 'C5'];
export const STATUS = ['ACTIVE', 'INACTIVE', 'PROBATION', 'CONFIRMED', 'SUCCESS', 'PENDING', 'CANCELLED'];
export const TRD_TYPE = ['SUBSCRIBE', 'REDEEM', 'DIVIDEND'];
export const BS_DIR = ['B', 'S'];
export const TRADE_STATUS = ['NEW', 'PARTIAL', 'FILLED', 'CANCELLED', 'REJECTED'];
export const ORD_TYPE = ['LIMIT', 'MARKET', 'STOP'];
export const SETT_STATUS = ['UNSETTLED', 'SETTLED', 'PARTIAL', 'FAILED'];
export const RPT_TYPE = ['Q', 'H', 'A'];
export const ACCT_TYPE = ['BANK', 'BOND', 'STOCK', 'CASH'];
export const TENORS = ['ON', '1W', '1M', '3M', '6M', '1Y', '3Y', '5Y', '7Y', '10Y'];
export const FUND_TYPE = ['ETF', 'LOF', 'MMF', 'OPEN', 'CLOSED'];
export const HOLDER_TYPE = ['INST', 'IND', 'INTERNAL'];
export const CHANNEL = ['DIRECT', 'BANK', 'BROKER', 'ONLINE', 'S5', 'TA', 'YH'];

/**
 * 默认 audit 字段 - 不在表单展示，由后端注入
 * etl_dt / src_sys
 */
export const AUDIT_FIELDS = ['etl_dt', 'src_sys', '_id'];

export default {
  BIZ_DT, AST_CDS, PORT_IDS, ISR_IDS, CNTP_IDS, CUSTOMER_IDS,
  SELLER_IDS, INDEX_CDS, CURVE_IDS, RATE_CDS, RATING_AGENCIES,
  CCY, AST_TYPE, AST_SUB_TYPE, ISR_TYPE, MARKET, BOND_TERM, PORT_TYPE,
  RISK_LVL, STATUS, TRD_TYPE, BS_DIR, TRADE_STATUS, ORD_TYPE,
  SETT_STATUS, RPT_TYPE, ACCT_TYPE, TENORS, FUND_TYPE,
  HOLDER_TYPE, CHANNEL, AUDIT_FIELDS
};
