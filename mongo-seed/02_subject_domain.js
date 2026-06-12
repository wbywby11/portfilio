/**
 * 主体域 dwd_isr_* — 3 张表
 * 主键：ISR_ID（机构）、CNTP_ID（交易对手）
 * 依赖：_keys.js (ZY_KEYS)
 *
 * 表清单：
 *   1. dwd_isr_institution         机构信息   8 条
 *   2. dwd_isr_institution_finance 机构财务  16 条 (8 机构 × 2 期)
 *   3. dwd_isr_trd_cntp            交易对手   5 条
 */
load('_keys.js');
print('--- [02] subject domain start ---');

var BIZ_DT = ZY_KEYS.BIZ_DT;
var aud    = ZY_KEYS.audit;

/* ================ 1. dwd_isr_institution 机构信息 (8) ================ */
ZY_KEYS.recreate('dwd_isr_institution', { $jsonSchema: {
  bsonType: 'object',
  required: ['ISR_ID', 'ISR_NM', 'ISR_TYPE'],
  properties: {
    ISR_ID:   { bsonType: 'string', description: '机构 ID（主键）' },
    ISR_NM:   { bsonType: 'string', description: '机构全称' },
    ISR_TYPE: { bsonType: 'string', description: 'GOV/BANK/POLICY_BANK/CORP/STATE_CORP/INSURANCE' }
  }
}});
db.dwd_isr_institution.createIndex({ ISR_ID: 1 }, { unique: true });
db.dwd_isr_institution.createIndex({ ISR_NM: 1 });

var isrSeed = [
  {
    ISR_ID: 'ISR000001', ISR_NM: '中华人民共和国财政部',           ISR_SHORT_NM: '财政部',
    ISR_TYPE: 'GOV',         CREDIT_CD: '11100000MF0000001N',
    INDUSTRY_CD: 'S9510', INDUSTRY_NM: '国家机构',
    REG_PROV: '北京', REG_CAP: null,         LIST_FLAG: 'N',
    EST_DT: '19490701',
    LATEST_RATING: 'AAA', RATING_AGENCY: '中诚信国际', RATING_DT: '20240815'
  },
  {
    ISR_ID: 'ISR000002', ISR_NM: '国家开发银行',                   ISR_SHORT_NM: '国开行',
    ISR_TYPE: 'POLICY_BANK', CREDIT_CD: '91110000100000023L',
    INDUSTRY_CD: 'J6611', INDUSTRY_NM: '中央银行及政策性银行',
    REG_PROV: '北京', REG_CAP: 4212.48e8,    LIST_FLAG: 'N',
    EST_DT: '19940317',
    LATEST_RATING: 'AAA', RATING_AGENCY: '中诚信国际', RATING_DT: '20240620'
  },
  {
    ISR_ID: 'ISR000003', ISR_NM: '中国工商银行股份有限公司',       ISR_SHORT_NM: '工商银行',
    ISR_TYPE: 'BANK',        CREDIT_CD: '91110000100003962T',
    INDUSTRY_CD: 'J6612', INDUSTRY_NM: '货币银行服务',
    REG_PROV: '北京', REG_CAP: 3564.06e8,    LIST_FLAG: 'Y',
    EST_DT: '19840101',
    LATEST_RATING: 'AAA', RATING_AGENCY: '中诚信国际', RATING_DT: '20240920'
  },
  {
    ISR_ID: 'ISR000004', ISR_NM: '中国农业发展银行',               ISR_SHORT_NM: '农发行',
    ISR_TYPE: 'POLICY_BANK', CREDIT_CD: '91110000100000056X',
    INDUSTRY_CD: 'J6611', INDUSTRY_NM: '中央银行及政策性银行',
    REG_PROV: '北京', REG_CAP: 570.00e8,     LIST_FLAG: 'N',
    EST_DT: '19941101',
    LATEST_RATING: 'AAA', RATING_AGENCY: '联合资信',   RATING_DT: '20240712'
  },
  {
    ISR_ID: 'ISR000005', ISR_NM: '万科企业股份有限公司',           ISR_SHORT_NM: '万科A',
    ISR_TYPE: 'CORP',        CREDIT_CD: '91440300192181490G',
    INDUSTRY_CD: 'K7010', INDUSTRY_NM: '房地产开发经营',
    REG_PROV: '广东', REG_CAP: 119.31e8,     LIST_FLAG: 'Y',
    EST_DT: '19840530',
    LATEST_RATING: 'AA+', RATING_AGENCY: '大公国际',   RATING_DT: '20250215'
  },
  {
    ISR_ID: 'ISR000006', ISR_NM: '华能新能源股份有限公司',         ISR_SHORT_NM: '华能新能源',
    ISR_TYPE: 'STATE_CORP',  CREDIT_CD: '911100007109340163',
    INDUSTRY_CD: 'D4415', INDUSTRY_NM: '风力发电',
    REG_PROV: '北京', REG_CAP: 105.42e8,     LIST_FLAG: 'N',
    EST_DT: '20020114',
    LATEST_RATING: 'AAA', RATING_AGENCY: '东方金诚',   RATING_DT: '20240425'
  },
  {
    ISR_ID: 'ISR000007', ISR_NM: '招商银行股份有限公司',           ISR_SHORT_NM: '招商银行',
    ISR_TYPE: 'BANK',        CREDIT_CD: '91440300100016920K',
    INDUSTRY_CD: 'J6612', INDUSTRY_NM: '货币银行服务',
    REG_PROV: '广东', REG_CAP: 252.20e8,     LIST_FLAG: 'Y',
    EST_DT: '19870408',
    LATEST_RATING: 'AAA', RATING_AGENCY: '中诚信国际', RATING_DT: '20240830'
  },
  {
    ISR_ID: 'ISR000008', ISR_NM: '中国平安保险(集团)股份有限公司', ISR_SHORT_NM: '中国平安',
    ISR_TYPE: 'INSURANCE',   CREDIT_CD: '914403001000017644',
    INDUSTRY_CD: 'J6820', INDUSTRY_NM: '人寿保险',
    REG_PROV: '广东', REG_CAP: 182.80e8,     LIST_FLAG: 'Y',
    EST_DT: '19880321',
    LATEST_RATING: 'AAA', RATING_AGENCY: '联合资信',   RATING_DT: '20240910'
  }
];
isrSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_isr_institution.insertMany(isrSeed);
print('  dwd_isr_institution: ' + db.dwd_isr_institution.countDocuments());

/* ================ 2. dwd_isr_institution_finance 机构财务 (16) ================ */
ZY_KEYS.recreate('dwd_isr_institution_finance', { $jsonSchema: {
  bsonType: 'object',
  required: ['ISR_ID', 'RPT_DT', 'RPT_TYPE'],
  properties: {
    ISR_ID:   { bsonType: 'string' },
    RPT_DT:   { bsonType: 'string' },
    RPT_TYPE: { bsonType: 'string', description: 'ANNUAL/SEMI/Q1/Q3' }
  }
}});
db.dwd_isr_institution_finance.createIndex({ ISR_ID: 1, RPT_DT: 1, RPT_TYPE: 1 }, { unique: true });

// 每机构 2 期：2023 年报、2024 中报。数值依据真实公开年报量级（单位：元）。
// 财政部以国家财政收支替代企业三表，仅记录 REVENUE/NET_PROFIT 字段。
var finSeed = [
  // ISR000001 财政部 —— 国家公共预算
  { ISR_ID: 'ISR000001', RPT_DT: '20231231', RPT_TYPE: 'ANNUAL',
    TOTAL_ASSET: null, TOTAL_LIAB: null, NET_ASSET: null,
    REVENUE: 21678400000000, NET_PROFIT: -3878400000000, ASSET_LIAB_RATIO: null, ROE: null, ROA: null },
  { ISR_ID: 'ISR000001', RPT_DT: '20240630', RPT_TYPE: 'SEMI',
    TOTAL_ASSET: null, TOTAL_LIAB: null, NET_ASSET: null,
    REVENUE: 11591000000000, NET_PROFIT: -2235000000000, ASSET_LIAB_RATIO: null, ROE: null, ROA: null },

  // ISR000002 国开行 —— 总资产 ~18 万亿
  { ISR_ID: 'ISR000002', RPT_DT: '20231231', RPT_TYPE: 'ANNUAL',
    TOTAL_ASSET: 18205800000000, TOTAL_LIAB: 16952400000000, NET_ASSET: 1253400000000,
    REVENUE: 412800000000, NET_PROFIT: 132500000000, ASSET_LIAB_RATIO: 0.9311, ROE: 0.1085, ROA: 0.0073 },
  { ISR_ID: 'ISR000002', RPT_DT: '20240630', RPT_TYPE: 'SEMI',
    TOTAL_ASSET: 18920000000000, TOTAL_LIAB: 17605000000000, NET_ASSET: 1315000000000,
    REVENUE: 218500000000, NET_PROFIT:  72800000000, ASSET_LIAB_RATIO: 0.9305, ROE: 0.0568, ROA: 0.0039 },

  // ISR000003 工商银行 —— 总资产 ~44 万亿
  { ISR_ID: 'ISR000003', RPT_DT: '20231231', RPT_TYPE: 'ANNUAL',
    TOTAL_ASSET: 44697000000000, TOTAL_LIAB: 41139000000000, NET_ASSET: 3558000000000,
    REVENUE: 843070000000, NET_PROFIT: 365116000000, ASSET_LIAB_RATIO: 0.9204, ROE: 0.1029, ROA: 0.0082 },
  { ISR_ID: 'ISR000003', RPT_DT: '20240630', RPT_TYPE: 'SEMI',
    TOTAL_ASSET: 47012000000000, TOTAL_LIAB: 43258000000000, NET_ASSET: 3754000000000,
    REVENUE: 414975000000, NET_PROFIT: 170470000000, ASSET_LIAB_RATIO: 0.9201, ROE: 0.0454, ROA: 0.0036 },

  // ISR000004 农发行 —— 总资产 ~11 万亿
  { ISR_ID: 'ISR000004', RPT_DT: '20231231', RPT_TYPE: 'ANNUAL',
    TOTAL_ASSET: 11320000000000, TOTAL_LIAB: 10612000000000, NET_ASSET: 708000000000,
    REVENUE: 263800000000, NET_PROFIT: 75600000000, ASSET_LIAB_RATIO: 0.9375, ROE: 0.1068, ROA: 0.0067 },
  { ISR_ID: 'ISR000004', RPT_DT: '20240630', RPT_TYPE: 'SEMI',
    TOTAL_ASSET: 11815000000000, TOTAL_LIAB: 11070000000000, NET_ASSET: 745000000000,
    REVENUE: 138500000000, NET_PROFIT:  41200000000, ASSET_LIAB_RATIO: 0.9370, ROE: 0.0553, ROA: 0.0035 },

  // ISR000005 万科 —— 总资产 ~1.4 万亿
  { ISR_ID: 'ISR000005', RPT_DT: '20231231', RPT_TYPE: 'ANNUAL',
    TOTAL_ASSET: 1501500000000, TOTAL_LIAB: 1129200000000, NET_ASSET: 372300000000,
    REVENUE: 466900000000, NET_PROFIT:  12160000000, ASSET_LIAB_RATIO: 0.7521, ROE: 0.0327, ROA: 0.0081 },
  { ISR_ID: 'ISR000005', RPT_DT: '20240630', RPT_TYPE: 'SEMI',
    TOTAL_ASSET: 1422600000000, TOTAL_LIAB: 1085500000000, NET_ASSET: 337100000000,
    REVENUE: 142780000000, NET_PROFIT: -9852000000, ASSET_LIAB_RATIO: 0.7631, ROE: -0.0292, ROA: -0.0069 },

  // ISR000006 华能新能源 —— 总资产 ~1800 亿
  { ISR_ID: 'ISR000006', RPT_DT: '20231231', RPT_TYPE: 'ANNUAL',
    TOTAL_ASSET: 178200000000, TOTAL_LIAB: 124200000000, NET_ASSET: 54000000000,
    REVENUE: 28850000000, NET_PROFIT: 6285000000, ASSET_LIAB_RATIO: 0.6970, ROE: 0.1164, ROA: 0.0353 },
  { ISR_ID: 'ISR000006', RPT_DT: '20240630', RPT_TYPE: 'SEMI',
    TOTAL_ASSET: 192500000000, TOTAL_LIAB: 134800000000, NET_ASSET: 57700000000,
    REVENUE: 16320000000, NET_PROFIT: 3520000000, ASSET_LIAB_RATIO: 0.7003, ROE: 0.0610, ROA: 0.0183 },

  // ISR000007 招商银行 —— 总资产 ~11 万亿
  { ISR_ID: 'ISR000007', RPT_DT: '20231231', RPT_TYPE: 'ANNUAL',
    TOTAL_ASSET: 11028500000000, TOTAL_LIAB: 9942700000000, NET_ASSET: 1085800000000,
    REVENUE: 339120000000, NET_PROFIT: 146602000000, ASSET_LIAB_RATIO: 0.9015, ROE: 0.1491, ROA: 0.0139 },
  { ISR_ID: 'ISR000007', RPT_DT: '20240630', RPT_TYPE: 'SEMI',
    TOTAL_ASSET: 11574000000000, TOTAL_LIAB: 10406000000000, NET_ASSET: 1168000000000,
    REVENUE: 172945000000, NET_PROFIT:  74743000000, ASSET_LIAB_RATIO: 0.8991, ROE: 0.0675, ROA: 0.0066 },

  // ISR000008 中国平安 —— 总资产 ~12 万亿
  { ISR_ID: 'ISR000008', RPT_DT: '20231231', RPT_TYPE: 'ANNUAL',
    TOTAL_ASSET: 11583500000000, TOTAL_LIAB: 10618500000000, NET_ASSET: 965000000000,
    REVENUE: 913789000000, NET_PROFIT: 85665000000, ASSET_LIAB_RATIO: 0.9167, ROE: 0.0921, ROA: 0.0077 },
  { ISR_ID: 'ISR000008', RPT_DT: '20240630', RPT_TYPE: 'SEMI',
    TOTAL_ASSET: 12087800000000, TOTAL_LIAB: 11079400000000, NET_ASSET: 1008400000000,
    REVENUE: 494230000000, NET_PROFIT:  74619000000, ASSET_LIAB_RATIO: 0.9166, ROE: 0.0763, ROA: 0.0063 }
];
finSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_isr_institution_finance.insertMany(finSeed);
print('  dwd_isr_institution_finance: ' + db.dwd_isr_institution_finance.countDocuments());

/* ================ 3. dwd_isr_trd_cntp 交易对手 (5) ================ */
ZY_KEYS.recreate('dwd_isr_trd_cntp', { $jsonSchema: {
  bsonType: 'object',
  required: ['CNTP_ID', 'CNTP_NM', 'CNTP_TYPE'],
  properties: {
    CNTP_ID:   { bsonType: 'string', description: '交易对手 ID（主键）' },
    CNTP_NM:   { bsonType: 'string' },
    CNTP_TYPE: { bsonType: 'string', description: 'SECURITIES/BANK/INSURANCE/FUND/OTHER' }
  }
}});
db.dwd_isr_trd_cntp.createIndex({ CNTP_ID: 1 }, { unique: true });
db.dwd_isr_trd_cntp.createIndex({ CNTP_NM: 1 });

var cntpSeed = [
  {
    CNTP_ID: 'CNTP00001', CNTP_NM: '中信证券股份有限公司', CNTP_SHORT_NM: '中信证券',
    CNTP_TYPE: 'SECURITIES', LINKED_ISR_ID: null,
    CREDIT_LIMIT: 5000000000, USED_LIMIT: 1200000000,
    STATUS: 'ACTIVE',
    CONTACT_PERSON: '王磊',  CONTACT_PHONE: '010-65608888',
    MASTER_AGREEMENT: 'NAFMII', AGREEMENT_DT: '20220315',
    MARKET: 'IB,SH,SZ', RATING: 'AAA', WHITELIST: 'Y',
    SETT_BANK: '中国工商银行', SETT_ACCT: '1100110000022001'
  },
  {
    CNTP_ID: 'CNTP00002', CNTP_NM: '中国国际金融股份有限公司固定收益部', CNTP_SHORT_NM: '中金固收',
    CNTP_TYPE: 'SECURITIES', LINKED_ISR_ID: null,
    CREDIT_LIMIT: 4500000000, USED_LIMIT:  980000000,
    STATUS: 'ACTIVE',
    CONTACT_PERSON: '李婷',  CONTACT_PHONE: '010-65051166',
    MASTER_AGREEMENT: 'NAFMII', AGREEMENT_DT: '20210908',
    MARKET: 'IB,SH,SZ', RATING: 'AAA', WHITELIST: 'Y',
    SETT_BANK: '中国银行',     SETT_ACCT: '7011200056789012'
  },
  {
    CNTP_ID: 'CNTP00003', CNTP_NM: '国泰君安证券股份有限公司做市部', CNTP_SHORT_NM: '国君做市',
    CNTP_TYPE: 'SECURITIES', LINKED_ISR_ID: null,
    CREDIT_LIMIT: 4000000000, USED_LIMIT:  860000000,
    STATUS: 'ACTIVE',
    CONTACT_PERSON: '孙志强', CONTACT_PHONE: '021-38676666',
    MASTER_AGREEMENT: 'NAFMII', AGREEMENT_DT: '20230420',
    MARKET: 'IB,SH,SZ', RATING: 'AAA', WHITELIST: 'Y',
    SETT_BANK: '上海浦东发展银行', SETT_ACCT: '9810010012345678'
  },
  {
    CNTP_ID: 'CNTP00004', CNTP_NM: '兴业银行金融市场部',                  CNTP_SHORT_NM: '兴业金市',
    CNTP_TYPE: 'BANK',       LINKED_ISR_ID: null,
    CREDIT_LIMIT: 6000000000, USED_LIMIT: 1850000000,
    STATUS: 'ACTIVE',
    CONTACT_PERSON: '周敏',   CONTACT_PHONE: '021-22118888',
    MASTER_AGREEMENT: 'NAFMII', AGREEMENT_DT: '20210512',
    MARKET: 'IB',          RATING: 'AAA', WHITELIST: 'Y',
    SETT_BANK: '兴业银行',   SETT_ACCT: '5566001088990001'
  },
  {
    CNTP_ID: 'CNTP00005', CNTP_NM: '中国银行间市场交易商协会',            CNTP_SHORT_NM: '交易商协会',
    CNTP_TYPE: 'OTHER',      LINKED_ISR_ID: null,
    CREDIT_LIMIT:        0, USED_LIMIT:        0,
    STATUS: 'ACTIVE',
    CONTACT_PERSON: '吴晓峰', CONTACT_PHONE: '010-66557788',
    MASTER_AGREEMENT: 'NAFMII_SELF', AGREEMENT_DT: '20200101',
    MARKET: 'IB',          RATING: 'NR',  WHITELIST: 'Y',
    SETT_BANK: null,         SETT_ACCT: null
  }
];
cntpSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
db.dwd_isr_trd_cntp.insertMany(cntpSeed);
print('  dwd_isr_trd_cntp: ' + db.dwd_isr_trd_cntp.countDocuments());

print('--- [02] subject domain done ---');
