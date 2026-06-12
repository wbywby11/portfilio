/**
 * 跨表主键 / 外键池 —— 在所有域脚本中复用，保证关联一致性。
 * 在 mongosh 里 load('mongo-seed/_keys.js') 后，全局对象 ZY_KEYS 即可用。
 */
var ZY_KEYS = {
  // 快照基准日
  BIZ_DT: '20250324',
  ETL_DT: '20250324',
  SRC_SYS: 'ZY',

  // 资产代码池 - 12个真实证券代码
  AST_CDS: [
    '019601.IB', '019735.IB', '230210.IB', '220215.IB',
    '2480006.IB', '112311.SZ', '600036.SH', '601318.SH',
    '510300.SH', '511260.SH', '127080.SZ', '180401.IB'
  ],
  // 资产名称映射
  AST_NAMES: {
    '019601.IB': '25国债03',
    '019735.IB': '25特别国债03',
    '230210.IB': '23国开10',
    '220215.IB': '22国开15',
    '2480006.IB': '24工商银行MTN001',
    '112311.SZ': '24万科MTN003',
    '600036.SH': '招商银行',
    '601318.SH': '中国平安',
    '510300.SH': '沪深300ETF',
    '511260.SH': '十年国债ETF',
    '127080.SZ': '2024华能新能ABS001优先A',
    '180401.IB': '24农发绿色债01'
  },

  // 组合ID池 - 5个
  PORT_IDS: ['PORT001', 'PORT002', 'PORT003', 'PORT004', 'PORT005'],
  PORT_NAMES: {
    'PORT001': '稳健配置一号',
    'PORT002': '纯债精选二号',
    'PORT003': '混合增强三号',
    'PORT004': '短融货币四号',
    'PORT005': '指数增强五号'
  },

  // 机构(发行人)ID池 - 8个真实机构
  ISR_IDS: ['ISR000001', 'ISR000002', 'ISR000003', 'ISR000004',
            'ISR000005', 'ISR000006', 'ISR000007', 'ISR000008'],
  ISR_NAMES: {
    'ISR000001': '中华人民共和国财政部',
    'ISR000002': '国家开发银行',
    'ISR000003': '中国工商银行股份有限公司',
    'ISR000004': '中国农业发展银行',
    'ISR000005': '万科企业股份有限公司',
    'ISR000006': '华能新能源股份有限公司',
    'ISR000007': '招商银行股份有限公司',
    'ISR000008': '中国平安保险(集团)股份有限公司'
  },

  // 交易对手ID池 - 5个
  CNTP_IDS: ['CNTP00001', 'CNTP00002', 'CNTP00003', 'CNTP00004', 'CNTP00005'],
  CNTP_NAMES: {
    'CNTP00001': '中信证券股份有限公司',
    'CNTP00002': '中金公司固定收益部',
    'CNTP00003': '国泰君安证券做市部',
    'CNTP00004': '兴业银行金融市场部',
    'CNTP00005': '中国银行间市场交易商协会'
  },

  // 客户ID池 - 7个（含个人和机构）
  CUSTOMER_IDS: ['CUS0000001', 'CUS0000002', 'CUS0000003', 'CUS0000004',
                 'CUS0000005', 'CUS0000006', 'CUS0000007'],
  CUSTOMER_NAMES: {
    'CUS0000001': '张明远',
    'CUS0000002': '李秀芬',
    'CUS0000003': '王建国',
    'CUS0000004': '陈雅琴',
    'CUS0000005': '深圳市前海资产管理有限公司',
    'CUS0000006': '上海浦东新区社会保险基金管理中心',
    'CUS0000007': '广东省教育基金会'
  },

  // 销售人员ID池 - 6个
  SELLER_IDS: ['SEL00001', 'SEL00002', 'SEL00003', 'SEL00004', 'SEL00005', 'SEL00006'],
  SELLER_NAMES: {
    'SEL00001': '刘洋',
    'SEL00002': '赵丽华',
    'SEL00003': '孙志强',
    'SEL00004': '周敏',
    'SEL00005': '吴晓峰',
    'SEL00006': '郑雯'
  },

  // 指数代码池 - 5个真实指数
  INDEX_CDS: ['000300.SH', '000905.SH', '399006.SZ', '000016.SH', '000985.CSI'],
  INDEX_NAMES: {
    '000300.SH': '沪深300',
    '000905.SH': '中证500',
    '399006.SZ': '创业板指',
    '000016.SH': '上证50',
    '000985.CSI': '中证全债'
  },

  // 收益率曲线ID池 - 5个
  CURVE_IDS: ['CGB', 'CDB', 'AAA_MTN', 'AAAm_NCD', 'SHIBOR'],
  CURVE_NAMES: {
    'CGB': '国债收益率曲线',
    'CDB': '国开债收益率曲线',
    'AAA_MTN': 'AAA中票收益率曲线',
    'AAAm_NCD': 'AAA-同业存单收益率曲线',
    'SHIBOR': 'SHIBOR利率曲线'
  },

  // 信用评级机构 - 4个
  RATING_AGENCIES: ['中诚信国际', '联合资信', '大公国际', '东方金诚'],

  // 资产类型枚举
  AST_TYPES: ['BOND', 'STOCK', 'FUND', 'ABS', 'NCD', 'REPO', 'CASH', 'INDEX'],
  AST_SUB_TYPES: ['CGB', 'POLICY', 'MTN', 'NCD', 'ENTERPRISE', 'ETF', 'LOF', 'A_SHARE', 'ABS_SENIOR', 'ABS_SUB'],

  // 产品类型枚举
  PORT_TYPES: ['MMF', 'BOND', 'EQUITY', 'MIXED', 'INDEX', 'FOF'],

  // 风险等级
  RISK_LVLS: ['R1', 'R2', 'R3', 'R4', 'R5'],

  // 币种
  CCYS: ['CNY', 'USD', 'EUR', 'JPY', 'HKD', 'GBP'],

  // 交易市场
  MARKETS: ['银行间', '上交所', '深交所', '交易所']
};

// 简便工具：YYYYMMDD ± N 天
ZY_KEYS.shiftDate = function (yyyymmdd, days) {
  var y = parseInt(yyyymmdd.substr(0, 4), 10);
  var m = parseInt(yyyymmdd.substr(4, 2), 10) - 1;
  var d = parseInt(yyyymmdd.substr(6, 2), 10);
  var dt = new Date(Date.UTC(y, m, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  var mm = ('0' + (dt.getUTCMonth() + 1)).slice(-2);
  var dd = ('0' + dt.getUTCDate()).slice(-2);
  return '' + dt.getUTCFullYear() + mm + dd;
};

// 通用：drop & create
ZY_KEYS.recreate = function (name, validator) {
  try { db.getCollection(name).drop(); } catch (e) { /* ignore */ }
  var opt = {};
  if (validator) opt.validator = validator;
  db.createCollection(name, opt);
  return db.getCollection(name);
};

// 通用 audit 字段
ZY_KEYS.audit = function () {
  return { etl_dt: ZY_KEYS.ETL_DT, src_sys: ZY_KEYS.SRC_SYS };
};

print('[ZY_KEYS] ready: BIZ_DT=' + ZY_KEYS.BIZ_DT
  + ', AST_CDS=' + ZY_KEYS.AST_CDS.length
  + ', PORT_IDS=' + ZY_KEYS.PORT_IDS.length
  + ', CUSTOMER_IDS=' + ZY_KEYS.CUSTOMER_IDS.length);
