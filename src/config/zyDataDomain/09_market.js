/**
 * 行情域 (market) - 25 张表
 * 主键池：AST_CD / INDEX_CD / CURVE_ID / RATE_CD
 */
import K from './keys';

const f = (key, label, type, opts = {}) => ({ key, label, type, ...opts });
const T = (name, label, pk, fields) => ({ name, label, pk, fields });

export default {
  domain: 'market',
  domainName: '行情域',
  domainCode: 'MKT',
  icon: 'el-icon-data-line',
  color: '#3F51B5',
  tables: [
    T('dwd_mkt_bond', '债券行情', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('OPEN_PRC', '开盘价', 'number', { width: 100 }),
      f('HIGH_PRC', '最高价', 'number', { width: 100 }),
      f('LOW_PRC', '最低价', 'number', { width: 100 }),
      f('CLOSE_PRC', '收盘价', 'number', { width: 100 }),
      f('VOL', '成交量', 'number', { width: 130 }),
      f('AMT', '成交额', 'number', { width: 140 }),
      f('YTM', '到期收益率', 'number', { width: 110 }),
      f('CHG_BP', '涨跌BP', 'number', { width: 100 })
    ]),

    T('dwd_mkt_bond_amount', '债券存量', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('ISSUE_AMT', '发行规模', 'number', { width: 140 }),
      f('OUTSTANDING_AMT', '存量规模', 'number', { width: 140 }),
      f('REPAID_AMT', '已偿还', 'number', { width: 140 })
    ]),

    T('dwd_mkt_bond_creditrating', '债项评级', ['AST_CD', 'RATING_DT', 'AGENCY'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('RATING_DT', '评级日', 'date', { required: true, primary: true, width: 110 }),
      f('AGENCY', '评级机构', 'enum', { required: true, primary: true, options: K.RATING_AGENCIES, width: 130 }),
      f('BOND_RATING', '债项评级', 'string', { width: 100 }),
      f('ISSUER_RATING', '发行人评级', 'string', { width: 110 }),
      f('OUTLOOK', '展望', 'enum', { options: ['POSITIVE', 'STABLE', 'NEGATIVE'], width: 100 })
    ]),

    T('dwd_mkt_bond_duration', '久期凸性', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('MOD_DURATION', '修正久期', 'number', { width: 110 }),
      f('MAC_DURATION', '麦考利久期', 'number', { width: 120 }),
      f('CONVEXITY', '凸性', 'number', { width: 100 }),
      f('KEY_RATE_1Y', 'KR-1Y', 'number', { width: 100 }),
      f('KEY_RATE_3Y', 'KR-3Y', 'number', { width: 100 }),
      f('KEY_RATE_5Y', 'KR-5Y', 'number', { width: 100 }),
      f('KEY_RATE_10Y', 'KR-10Y', 'number', { width: 100 })
    ]),

    T('dwd_mkt_bond_ecl', '预期信用损失', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, primary: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('STAGE', '阶段', 'number', { width: 80 }),
      f('PD_12M', '12月违约概率', 'number', { width: 130 }),
      f('PD_LIFE', '终身违约概率', 'number', { width: 130 }),
      f('LGD', '违约损失率', 'number', { width: 110 }),
      f('EAD', '违约风险敞口', 'number', { width: 140 }),
      f('ECL_AMT', 'ECL金额', 'number', { width: 130 })
    ]),

    T('dwd_mkt_bond_market', '债券逐日成交', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'enum', { required: true, options: K.AST_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, width: 110 }),
      f('VOL', '成交量', 'number', { width: 130 }),
      f('AMT', '成交额', 'number', { width: 140 }),
      f('AVG_PRC', '加权均价', 'number', { width: 110 }),
      f('AVG_YTM', '加权YTM', 'number', { width: 110 }),
      f('TRADE_CNT', '成交笔数', 'number', { width: 110 })
    ]),

    T('dwd_mkt_calendar', '日历', ['CAL_DT', 'CAL_TYPE'], [
      f('CAL_DT', '日期', 'date', { required: true, primary: true, width: 110 }),
      f('CAL_TYPE', '日历类型', 'enum', { required: true, primary: true, options: ['IB', 'SSE', 'SZSE'], width: 100 }),
      f('IS_TRADE', '是否交易日', 'enum', { options: ['Y', 'N'], width: 100 }),
      f('WEEK_DAY', '星期', 'number', { width: 80 })
    ]),

    T('dwd_mkt_date', '日期维度', ['DT'], [
      f('DT', '日期', 'date', { required: true, primary: true, width: 110 }),
      f('YEAR', '年', 'string', { width: 80 }),
      f('QUARTER', '季度', 'string', { width: 80 }),
      f('MONTH', '月', 'string', { width: 80 }),
      f('DAY', '日', 'string', { width: 80 }),
      f('WEEK_OF_YEAR', '周', 'number', { width: 80 }),
      f('IS_MONTH_END', '月末', 'enum', { options: ['Y', 'N'], width: 80 }),
      f('IS_QUARTER_END', '季末', 'enum', { options: ['Y', 'N'], width: 80 }),
      f('IS_YEAR_END', '年末', 'enum', { options: ['Y', 'N'], width: 80 })
    ]),

    T('dwd_mkt_curve', '收益率曲线主数据', ['CURVE_ID'], [
      f('CURVE_ID', '曲线ID', 'string', { required: true, primary: true, width: 130, options: K.CURVE_IDS, allowCreate: true }),
      f('CURVE_NM', '曲线名称', 'string', { required: true, width: 220 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('SOURCE', '数据源', 'string', { width: 100 }),
      f('CURVE_TYPE', '曲线类型', 'enum', { options: ['TREASURY', 'POLICY', 'CREDIT', 'NCD', 'IRS'], width: 110 })
    ]),

    T('dwd_mkt_curve_quote', '曲线节点报价', ['CURVE_ID', 'BIZ_DT', 'TENOR'], [
      f('CURVE_ID', '曲线ID', 'enum', { required: true, primary: true, options: K.CURVE_IDS, width: 130 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('TENOR', '期限', 'enum', { required: true, primary: true, options: K.TENORS, width: 90 }),
      f('YIELD', '收益率', 'number', { width: 110 }),
      f('CHG_BP', '变动BP', 'number', { width: 100 })
    ]),

    T('dwd_mkt_exrate', '汇率', ['CCY_PAIR', 'BIZ_DT'], [
      f('CCY_PAIR', '币种对', 'string', { required: true, primary: true, width: 110 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('MID', '中间价', 'number', { width: 100 }),
      f('BID', '买入价', 'number', { width: 100 }),
      f('ASK', '卖出价', 'number', { width: 100 }),
      f('SRC', '来源', 'string', { width: 90 })
    ]),

    T('dwd_mkt_fund', '基金主数据', ['AST_CD'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('FUND_NM', '基金名称', 'string', { required: true, width: 220 }),
      f('FUND_TYPE', '基金类型', 'enum', { options: K.FUND_TYPE, width: 100 }),
      f('MGR_INST', '管理人', 'string', { width: 130 }),
      f('CUSTODY_BANK', '托管行', 'string', { width: 130 }),
      f('ESTAB_DT', '成立日', 'date', { width: 110 }),
      f('BENCHMARK', '业绩基准', 'string', { width: 200 }),
      f('AUM', '管理规模', 'number', { width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_mkt_fund_allocation', '基金资产配置', ['AST_CD', 'RPT_DT', 'AST_CLASS'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('RPT_DT', '报告期', 'date', { required: true, primary: true, width: 110 }),
      f('AST_CLASS', '资产类别', 'enum', { required: true, primary: true, options: ['STOCK', 'BOND', 'CASH', 'OTHER'], width: 110 }),
      f('MKT_VAL', '市值', 'number', { width: 140 }),
      f('RATIO', '占比', 'number', { width: 90 })
    ]),

    T('dwd_mkt_fund_derive', '基金衍生指标', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('SHARPE_1Y', '夏普1Y', 'number', { width: 100 }),
      f('SORTINO_1Y', '索提诺1Y', 'number', { width: 110 }),
      f('MAX_DD_1Y', '最大回撤1Y', 'number', { width: 120 }),
      f('VOL_1Y', '波动率1Y', 'number', { width: 110 }),
      f('BETA_1Y', 'Beta-1Y', 'number', { width: 100 }),
      f('ALPHA_1Y', 'Alpha-1Y', 'number', { width: 100 }),
      f('TRACKING_ERR', '跟踪误差', 'number', { width: 110 })
    ]),

    T('dwd_mkt_fund_market', '基金行情(净值)', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('UNIT_NAV', '单位净值', 'number', { width: 110 }),
      f('ACC_NAV', '累计净值', 'number', { width: 110 }),
      f('DAILY_RTN', '日收益率', 'number', { width: 100 }),
      f('VOL', '成交量', 'number', { width: 130 }),
      f('AMT', '成交额', 'number', { width: 140 })
    ]),

    T('dwd_mkt_fund_structure', '基金份额结构', ['AST_CD', 'RPT_DT', 'HOLDER_TYPE'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('RPT_DT', '报告期', 'date', { required: true, primary: true, width: 110 }),
      f('HOLDER_TYPE', '持有人类型', 'enum', { required: true, primary: true, options: K.HOLDER_TYPE, width: 110 }),
      f('TOT_SHR', '总份额', 'number', { width: 140 }),
      f('RATIO', '占比', 'number', { width: 90 })
    ]),

    T('dwd_mkt_fund_suspension', '基金停牌', ['AST_CD', 'SUS_DT'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('SUS_DT', '停牌日', 'date', { required: true, primary: true, width: 110 }),
      f('RES_DT', '恢复日', 'date', { width: 110 }),
      f('SUS_TYPE', '停牌类型', 'enum', { options: ['NEW_YEAR', 'BIG_SUB_LIMIT', 'OTHER'], width: 130 }),
      f('REASON', '原因', 'string', { width: 220 })
    ]),

    T('dwd_mkt_index', '指数主数据', ['INDEX_CD'], [
      f('INDEX_CD', '指数代码', 'string', { required: true, primary: true, width: 140, options: K.INDEX_CDS, allowCreate: true }),
      f('INDEX_NM', '指数名称', 'string', { required: true, width: 200 }),
      f('PUBLISHER', '发布机构', 'string', { width: 130 }),
      f('BASE_DT', '基期', 'date', { width: 110 }),
      f('BASE_VAL', '基期值', 'number', { width: 110 }),
      f('INDEX_TYPE', '指数类型', 'enum', { options: ['EQUITY', 'BOND', 'COMMODITY'], width: 100 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_mkt_index_member', '指数成分', ['INDEX_CD', 'AST_CD', 'BIZ_DT'], [
      f('INDEX_CD', '指数代码', 'enum', { required: true, primary: true, options: K.INDEX_CDS, width: 140 }),
      f('AST_CD', '成分代码', 'string', { required: true, primary: true, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('WEIGHT', '权重', 'number', { width: 100 }),
      f('IN_DT', '调入日', 'date', { width: 110 }),
      f('OUT_DT', '调出日', 'date', { width: 110 })
    ]),

    T('dwd_mkt_index_quote', '指数行情', ['INDEX_CD', 'BIZ_DT'], [
      f('INDEX_CD', '指数代码', 'enum', { required: true, primary: true, options: K.INDEX_CDS, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('OPEN_VAL', '开盘值', 'number', { width: 110 }),
      f('HIGH_VAL', '最高值', 'number', { width: 110 }),
      f('LOW_VAL', '最低值', 'number', { width: 110 }),
      f('CLOSE_VAL', '收盘值', 'number', { width: 110 }),
      f('VOL', '成交量', 'number', { width: 130 }),
      f('AMT', '成交额', 'number', { width: 140 }),
      f('DAILY_RTN', '日收益率', 'number', { width: 100 }),
      f('YTD_RTN', '年初至今', 'number', { width: 100 })
    ]),

    T('dwd_mkt_rate', '利率主数据', ['RATE_CD'], [
      f('RATE_CD', '利率代码', 'string', { required: true, primary: true, width: 130, options: K.RATE_CDS, allowCreate: true }),
      f('RATE_NM', '利率名称', 'string', { required: true, width: 240 }),
      f('SOURCE', '来源', 'string', { width: 100 }),
      f('CCY', '币种', 'enum', { options: K.CCY, width: 80 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_mkt_rate_quote', '利率报价', ['RATE_CD', 'BIZ_DT'], [
      f('RATE_CD', '利率代码', 'enum', { required: true, primary: true, options: K.RATE_CDS, width: 130 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('RATE_VAL', '利率值', 'number', { width: 110 }),
      f('CHG_BP', '变动BP', 'number', { width: 100 })
    ]),

    T('dwd_mkt_rating', '评级动作', ['ISR_ID', 'RATING_DT', 'AGENCY'], [
      f('ISR_ID', '主体ID', 'enum', { required: true, primary: true, options: K.ISR_IDS, width: 120 }),
      f('RATING_DT', '评级日', 'date', { required: true, primary: true, width: 110 }),
      f('AGENCY', '评级机构', 'enum', { required: true, primary: true, options: K.RATING_AGENCIES, width: 130 }),
      f('RATING', '当前评级', 'string', { width: 100 }),
      f('PREV_RATING', '上次评级', 'string', { width: 100 }),
      f('ACTION', '动作', 'enum', { options: ['UPGRADE', 'DOWNGRADE', 'AFFIRM', 'WATCH'], width: 100 }),
      f('OUTLOOK', '展望', 'enum', { options: ['POSITIVE', 'STABLE', 'NEGATIVE'], width: 100 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_mkt_stock', '股票主数据', ['AST_CD'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('STOCK_NM', '股票名称', 'string', { required: true, width: 200 }),
      f('EXCH', '交易所', 'enum', { options: ['SSE', 'SZSE'], width: 90 }),
      f('INDUSTRY_CD', '行业代码', 'string', { width: 110 }),
      f('INDUSTRY_NM', '行业名称', 'string', { width: 120 }),
      f('LIST_DT', '上市日', 'date', { width: 110 }),
      f('TOT_CAP', '总市值', 'number', { width: 140 }),
      f('FREE_CAP', '流通市值', 'number', { width: 140 }),
      f('ISR_ID', '关联主体', 'enum', { options: K.ISR_IDS, width: 120 }),
      f('BIZ_DT', '业务日期', 'date', { width: 110, defaultValue: K.BIZ_DT })
    ]),

    T('dwd_mkt_stock_yield', '股票收益率', ['AST_CD', 'BIZ_DT'], [
      f('AST_CD', '资产代码', 'string', { required: true, primary: true, width: 140 }),
      f('BIZ_DT', '业务日期', 'date', { required: true, primary: true, width: 110, defaultValue: K.BIZ_DT }),
      f('OPEN_PRC', '开盘价', 'number', { width: 100 }),
      f('HIGH_PRC', '最高价', 'number', { width: 100 }),
      f('LOW_PRC', '最低价', 'number', { width: 100 }),
      f('CLOSE_PRC', '收盘价', 'number', { width: 100 }),
      f('VOL', '成交量', 'number', { width: 130 }),
      f('AMT', '成交额', 'number', { width: 140 }),
      f('DAILY_RTN', '日收益率', 'number', { width: 100 }),
      f('WEEK_RTN', '周收益率', 'number', { width: 100 }),
      f('MONTH_RTN', '月收益率', 'number', { width: 100 }),
      f('YTD_RTN', '年初至今', 'number', { width: 100 }),
      f('TURNOVER', '换手率', 'number', { width: 100 }),
      f('PE_TTM', 'PE-TTM', 'number', { width: 90 }),
      f('PB_LF', 'PB-LF', 'number', { width: 90 })
    ])
  ]
};
