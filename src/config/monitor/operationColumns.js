/**
 * 日常监控 —— 操作面板表格列配置（配置驱动，禁止写死列）。
 *
 * 列定义直接传给 <StandardTable :columns="...">：
 *   - 数字列（target / baseline / change）不写 align，StandardTable 自动右对齐
 *   - cell: 'dataBar' 渲染横向数据条，宽度按本列最大仓位归一化
 *   - cell: 'change' 渲染红涨绿跌色块
 *   - cell: 'slot'   复杂单元格回传给页面插槽
 *
 * 策略差异化：
 *   策略元数据声明 ui_schema.operation_columns 或 template 覆盖表，
 *   追加/替换列（例如 CTA 的「对冲比例」、期权策略的「Delta」），
 *   四个主页签代码无需改动。
 */
import { resolveTemplateCode } from './metrics';

/** 最新指令：目标仓位表列 */
export const BASE_WEIGHT_COLUMNS = [
  {
    field: 'code',
    title: '资产',
    minWidth: 180,
    cell: 'slot',
    slot: 'asset'
  },
  {
    field: 'target',
    title: '目标仓位',
    width: 180,
    cell: 'dataBar',
    format: 'pct',
    dataBar: { color: 'primary', minWidth: 2 }
  },
  {
    field: 'baseline',
    title: '调整前',
    width: 100,
    cell: 'number',
    format: 'pct'
  },
  {
    field: 'change',
    title: '变动',
    width: 130,
    cell: 'change',
    format: 'signedPct',
    zeroText: '不变'
  },
  {
    field: 'logic',
    title: '仓位计算逻辑',
    minWidth: 320,
    cell: 'slot',
    slot: 'logic'
  }
];

/**
 * 组合指令看板：子策略 → 资产 两级树形列。
 *
 * 与 BASE_WEIGHT_COLUMNS 的区别：那张表是「一条指令的穿透后资产权重」平铺，
 * 这张表是「策略内权重 × 策略占组合比重」的两级展开，并带交易要素
 * （动作 / 金额 / 数量）。金额与数量在前端按模拟规模现算，后端只出权重和价格。
 */
export const BASE_DASHBOARD_COLUMNS = [
  { field: 'name', title: '资产 / 策略', minWidth: 260, align: 'left', cell: 'slot', slot: 'name' },
  { field: 'strategyWeight', title: '策略内权重', width: 110, cell: 'number', format: 'pct', placeholder: '--' },
  { field: 'targetWeight', title: '组合穿透权重', width: 130, cell: 'number', format: 'pct', placeholder: '--' },
  { field: 'changeWeight', title: '变动比例', width: 120, cell: 'change', placeholder: '--' },
  { field: 'action', title: '动作', width: 90, align: 'center', cell: 'slot', slot: 'action' },
  { field: 'price', title: '预估价格', width: 110, align: 'right', cell: 'slot', slot: 'price' },
  { field: 'changeAmount', title: '变动金额（元）', width: 150, align: 'right', cell: 'slot', slot: 'amount' },
  { field: 'changeQty', title: '变动数量', width: 120, align: 'right', cell: 'slot', slot: 'qty' }
];

/** 历史指令表列（expand + 各状态列均由插槽渲染） */
export const BASE_HISTORY_COLUMNS = [
  { type: 'expand', slot: 'expand', width: 48 },
  { field: '__groupLabel', title: '所属策略', minWidth: 120, cell: 'slot', slot: 'group', key: 'group' },
  { field: 'signal_date', title: '信号日', width: 110, align: 'center' },
  { field: 'op_type', title: '类型', width: 110, align: 'center', cell: 'slot', slot: 'opType' },
  { field: '__exposure', title: '目标敞口', width: 130, cell: 'slot', slot: 'exposure', align: 'right', headerAlign: 'right' },
  { field: 'status', title: '状态', width: 90, align: 'center', cell: 'slot', slot: 'status' },
  { field: 'source', title: '来源', width: 80, align: 'center', cell: 'slot', slot: 'source' },
  { field: 'remark', title: '补充说明', minWidth: 200, cell: 'slot', slot: 'remark' },
  { field: '__actions', title: '操作', width: 110, align: 'center', cell: 'slot', slot: 'actions', key: 'actions' }
];

/**
 * 策略级额外列（纯声明式）。
 * 示例：
 *   TEMPLATE_COLUMN_EXTENSIONS.cta_trend = {
 *     weight: [{ field: 'hedge_ratio', title: '对冲比例', width: 110, cell: 'number', format: 'pct' }],
 *     history: [{ field: 'hedge_ratio', title: '对冲比例', width: 110, cell: 'number', format: 'pct' }]
 *   }
 */
export const TEMPLATE_COLUMN_EXTENSIONS = {
  // 预留：按 template_code 追加列
};

function resolveExtensions(kind, strategyContext) {
  const uiSchema = (strategyContext && strategyContext.ui_schema) || {};
  const fromSchema = uiSchema.operation_columns && uiSchema.operation_columns[kind];
  if (Array.isArray(fromSchema)) return fromSchema;

  const code = resolveTemplateCode(strategyContext);
  const byTemplate = code && TEMPLATE_COLUMN_EXTENSIONS[code];
  return (byTemplate && byTemplate[kind]) || [];
}

/** 最新指令列：基础列 + 策略扩展列（扩展列插在「变动」之后） */
export function buildWeightColumns(strategyContext) {
  const extras = resolveExtensions('weight', strategyContext);
  const columns = BASE_WEIGHT_COLUMNS.slice();
  if (!extras.length) return columns;
  const insertAt = columns.findIndex(col => col.field === 'change') + 1;
  columns.splice(insertAt, 0, ...extras);
  return columns;
}

/** 历史指令列：基础列 + 策略扩展列（扩展列插在「目标敞口」之后），按需隐藏所属策略列 */
export function buildHistoryColumns(strategyContext, options) {
  const opts = options || {};
  let columns = BASE_HISTORY_COLUMNS.slice();
  if (!opts.unified) {
    columns = columns.filter(col => col.key !== 'group');
  }
  const extras = resolveExtensions('history', strategyContext);
  if (extras.length) {
    const insertAt = columns.findIndex(col => col.slot === 'exposure') + 1;
    columns.splice(insertAt, 0, ...extras);
  }
  return columns;
}

/** 组合指令看板列：基础列 + 策略扩展列（扩展列插在「变动比例」之后） */
export function buildDashboardColumns(strategyContext) {
  const extras = resolveExtensions('dashboard', strategyContext);
  const columns = BASE_DASHBOARD_COLUMNS.slice();
  if (!extras.length) return columns;
  const insertAt = columns.findIndex(col => col.field === 'changeWeight') + 1;
  columns.splice(insertAt, 0, ...extras);
  return columns;
}

export default {
  BASE_WEIGHT_COLUMNS,
  BASE_DASHBOARD_COLUMNS,
  BASE_HISTORY_COLUMNS,
  TEMPLATE_COLUMN_EXTENSIONS,
  buildWeightColumns,
  buildDashboardColumns,
  buildHistoryColumns
};
