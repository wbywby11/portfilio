/**
 * 日常监控 —— 指标卡配置（配置驱动 UI 的唯一数据源）。
 *
 * 页面组件只负责把业务数据组装成 ctx 对象；
 * 本文件决定「展示哪些指标、如何取值、如何格式化、用什么状态色、栅格几列」。
 *
 * 扩展方式：
 *   1. 新增指标：在 METRIC_DEFS 增加一条定义；
 *   2. 挂到页面：把 key 加进 PAGE_METRICS.overview / performance / risk；
 *   3. 策略差异化：在 TEMPLATE_METRICS 里为具体 template_code 声明 key 列表（覆盖默认）。
 * 全程不改四个页签的模板。
 */

const isNum = value => value !== null && value !== undefined && value !== '' && !Number.isNaN(Number(value));

/** 收益类状态：涨红跌绿 */
function returnStatus(value) {
  if (!isNum(value)) return 'muted';
  const n = Number(value);
  if (n > 0) return 'up';
  if (n < 0) return 'down';
  return 'muted';
}

/** 夏普状态：>=1 红，>=0.5 橙，>=0 黑，<0 绿 */
function sharpeStatus(value) {
  if (!isNum(value)) return 'muted';
  const n = Number(value);
  if (n >= 1) return 'up';
  if (n >= 0.5) return 'warning';
  if (n >= 0) return 'default';
  return 'down';
}

/** 波动率状态：超过重置阈值标红，否则绿 */
function volStatus(ctx) {
  if (!isNum(ctx.volatility)) return 'muted';
  if (ctx.isManualAllocation) return 'default';
  if (!isNum(ctx.volThreshold)) return 'default';
  return Number(ctx.volatility) >= Number(ctx.volThreshold) ? 'danger' : 'success';
}

/** 百分点数值 → '12.34%'；空值 → '—' */
const fmtPct = value => (isNum(value) ? Number(value).toFixed(2) + '%' : '—');

export const METRIC_DEFS = {
  /* ═════════════ 总览：绩效指标 ═════════════ */
  nav: {
    label: '当前净值',
    value: ctx => ctx.nav,
    format: 'number',
    precision: 4,
    size: 'lg',
    sub: ctx => ctx.date || ''
  },
  periodReturn: {
    label: '区间收益率',
    value: ctx => ctx.periodReturn,
    format: 'signedPointPercent',
    status: ctx => returnStatus(ctx.periodReturn),
    sub: ctx => (isNum(ctx.tradingDays) ? ctx.tradingDays + ' 个交易日' : '')
  },
  annualReturn: {
    label: '年化收益率（260日）',
    value: ctx => ctx.annualReturn,
    format: 'signedPointPercent',
    status: ctx => returnStatus(ctx.annualReturn),
    sub: ctx => '365日：' + fmtPct(ctx.annualReturn365)
  },
  annualVol: {
    label: '年化波动率（260日）',
    value: ctx => ctx.annualVol,
    format: 'pointPercent',
    sub: ctx => '365日：' + fmtPct(ctx.annualVol365)
  },
  sharpe: {
    label: '夏普比率（260日）',
    value: ctx => ctx.sharpe,
    format: 'number',
    precision: 3,
    status: ctx => sharpeStatus(ctx.sharpe),
    sub: ctx => '365日：' + (isNum(ctx.sharpe365) ? Number(ctx.sharpe365).toFixed(3) : '—')
  },
  maxDrawdown: {
    label: '最大回撤',
    value: ctx => ctx.maxDrawdown,
    format: 'pointPercent',
    status: () => 'down',
    sub: () => '区间最大'
  },

  /* ═════════════ 总览：实时状态 ═════════════ */
  dailyReturn: {
    label: '当日收益',
    value: ctx => ctx.dailyReturn,
    format: 'signedPointPercent',
    status: ctx => returnStatus(ctx.dailyReturn),
    sub: () => '较前日'
  },
  currentDrawdown: {
    label: '当前回撤',
    value: ctx => ctx.currentDrawdown,
    format: 'pointPercent',
    status: () => 'down',
    sub: () => '距历史高点'
  },
  leverage: {
    label: '总杠杆',
    value: ctx => ctx.leverage,
    format: 'number',
    precision: 2,
    sub: () => '权重绝对值之和'
  },
  positionCount: {
    label: '持仓资产数',
    value: ctx => ctx.positionCount,
    format: 'integer',
    sub: () => '权重 ≠ 0'
  },
  daysToRebalance: {
    label: '距下次调仓',
    value: ctx => ctx.daysToRebalance,
    format: 'days',
    sub: ctx => ctx.nextRebalanceDate || ''
  },
  monitoredVol: {
    label: '监控波动率',
    value: ctx => ctx.volatility,
    format: 'pointPercent',
    status: ctx => volStatus(ctx),
    sub: ctx => {
      if (ctx.isManualAllocation) return '主观策略无阈值';
      return '阈值: ' + fmtPct(ctx.volThreshold);
    }
  },

  /* ═════════════ 绩效页（后端 metrics 为小数口径） ═════════════ */
  pfPeriodReturn: {
    label: '区间收益率',
    value: ctx => ctx.periodReturn,
    format: 'signedRatioPercent',
    status: ctx => returnStatus(ctx.periodReturn)
  },
  pfAnnualReturn: {
    label: '年化收益率（260日）',
    value: ctx => ctx.annualReturn,
    format: 'signedRatioPercent',
    status: ctx => returnStatus(ctx.annualReturn),
    sub: ctx => '365日：' + fmtPct(ctx.annualReturn365 === null || ctx.annualReturn365 === undefined ? null : ctx.annualReturn365 * 100)
  },
  pfAnnualVol: {
    label: '年化波动率（260日）',
    value: ctx => ctx.annualVol,
    format: 'ratioPercent',
    sub: ctx => '365日：' + fmtPct(ctx.annualVol365 === null || ctx.annualVol365 === undefined ? null : ctx.annualVol365 * 100)
  },
  pfMaxDrawdown: {
    label: '最大回撤',
    value: ctx => ctx.maxDrawdown,
    format: 'ratioPercent',
    status: () => 'down'
  },
  pfSharpe: {
    label: '夏普比率（260日）',
    value: ctx => ctx.sharpe,
    format: 'number',
    precision: 2,
    sub: ctx => '365日：' + (isNum(ctx.sharpe365) ? Number(ctx.sharpe365).toFixed(2) : '—')
  },
  pfTradingDays: {
    label: '交易日数',
    value: ctx => ctx.tradingDays,
    format: 'integer'
  },

  /* ═════════════ 风控页 ═════════════ */
  riskCurrentVol: {
    label: '当前组合波动率',
    value: ctx => ctx.volatility,
    format: 'pointPercent',
    size: 'lg',
    status: ctx => (ctx.abnormal ? 'danger' : 'default'),
    sub: ctx => (isNum(ctx.threshold) ? '风控阈值 ' + Number(ctx.threshold).toFixed(2) + '%' : ''),
    windows: ctx => ctx.windows || []
  }
};

/** 各页面默认展示的指标（顺序即栅格顺序） */
export const PAGE_METRICS = {
  overview: [
    'nav', 'periodReturn', 'annualReturn', 'annualVol', 'sharpe', 'maxDrawdown',
    'dailyReturn', 'currentDrawdown', 'leverage', 'positionCount', 'daysToRebalance', 'monitoredVol'
  ],
  performance: ['pfPeriodReturn', 'pfAnnualReturn', 'pfAnnualVol', 'pfMaxDrawdown', 'pfSharpe', 'pfTradingDays'],
  risk: ['riskCurrentVol']
};

/**
 * 策略模板级覆盖：只声明有差异的页面。
 * 例如某策略不需要展示杠杆与波动率，只保留核心 6 项：
 *   cta_trend: { overview: ['nav', 'periodReturn', 'annualReturn', 'annualVol', 'sharpe', 'maxDrawdown'] }
 */
export const TEMPLATE_METRICS = {
  // 预留：按 template_code 覆盖
};

/** 各页面默认栅格列数（策略可覆盖） */
export const PAGE_GRID_COLUMNS = {
  overview: 6,
  performance: 6,
  risk: 1
};

export const TEMPLATE_GRID_COLUMNS = {
  // 预留：例如 { cta_trend: { overview: 4 } }
};

/** 读取策略模板 code（兼容不同字段命名） */
export function resolveTemplateCode(strategyContext) {
  if (!strategyContext) return '';
  return strategyContext.template_code
    || strategyContext.strategy_template_code
    || (strategyContext.template && strategyContext.template.code)
    || '';
}

/** 策略级 ui_schema（若后端未来下发则优先使用，不改现有数据结构） */
function resolveUiSchema(strategyContext) {
  return (strategyContext && strategyContext.ui_schema) || {};
}

/** 解析某页面最终展示的指标 key 列表 */
export function resolveMetricKeys(page, strategyContext) {
  const uiSchema = resolveUiSchema(strategyContext);
  const fromSchema = uiSchema.metrics && uiSchema.metrics[page];
  if (Array.isArray(fromSchema) && fromSchema.length) return fromSchema;

  const code = resolveTemplateCode(strategyContext);
  const fromTemplate = code && TEMPLATE_METRICS[code] && TEMPLATE_METRICS[code][page];
  if (Array.isArray(fromTemplate) && fromTemplate.length) return fromTemplate;

  return PAGE_METRICS[page] || [];
}

/** 解析栅格列数 */
export function resolveGridColumns(page, strategyContext) {
  const uiSchema = resolveUiSchema(strategyContext);
  const fromSchema = uiSchema.grid_columns && uiSchema.grid_columns[page];
  if (fromSchema) return Number(fromSchema);

  const code = resolveTemplateCode(strategyContext);
  const fromTemplate = code && TEMPLATE_GRID_COLUMNS[code] && TEMPLATE_GRID_COLUMNS[code][page];
  if (fromTemplate) return Number(fromTemplate);

  return PAGE_GRID_COLUMNS[page] || 1;
}

/**
 * 把 ctx 数据按配置装配成 MetricCard 可直接渲染的数组。
 * 返回项：{ key, label, value, format, precision, size, status, sub, windows, tooltip, display }
 */
export function buildMetrics(page, ctx, strategyContext) {
  return resolveMetricKeys(page, strategyContext)
    .map(key => {
      const def = METRIC_DEFS[key];
      if (!def) return null;
      return {
        key,
        label: def.label,
        value: typeof def.value === 'function' ? def.value(ctx) : def.value,
        format: def.format,
        precision: def.precision,
        size: def.size,
        status: typeof def.status === 'function' ? def.status(ctx) : def.status,
        sub: typeof def.sub === 'function' ? def.sub(ctx) : def.sub,
        windows: typeof def.windows === 'function' ? def.windows(ctx) : def.windows,
        tooltip: typeof def.tooltip === 'function' ? def.tooltip(ctx) : def.tooltip
      };
    })
    .filter(Boolean);
}

/**
 * 策略自定义插槽配置：custom_components 可以是数组（全部页签）或按页签的对象。
 * 优先读策略上下文（若后端下发），其次读前端模板表。
 */
export const TEMPLATE_CUSTOM_COMPONENTS = {
  // 示例（仅声明，不注册组件时 DynamicSlots 会自动跳过）：
  // option_greeks: {
  //   overview: [{ component: 'GreeksTable', title: '期权希腊字母', span: 'full' }],
  //   risk: [{ component: 'GreeksTable', title: '期权希腊字母', span: 'full' }]
  // }
};

export function resolveCustomComponents(page, strategyContext) {
  const fromContext = strategyContext && strategyContext.custom_components;
  if (Array.isArray(fromContext)) return fromContext;
  if (fromContext && Array.isArray(fromContext[page])) return fromContext[page];

  const code = resolveTemplateCode(strategyContext);
  const fromTemplate = code && TEMPLATE_CUSTOM_COMPONENTS[code] && TEMPLATE_CUSTOM_COMPONENTS[code][page];
  return Array.isArray(fromTemplate) ? fromTemplate : [];
}

export default {
  METRIC_DEFS,
  PAGE_METRICS,
  TEMPLATE_METRICS,
  PAGE_GRID_COLUMNS,
  TEMPLATE_GRID_COLUMNS,
  resolveTemplateCode,
  resolveMetricKeys,
  resolveGridColumns,
  buildMetrics,
  resolveCustomComponents
};
