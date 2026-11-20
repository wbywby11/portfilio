/**
 * 组合指令看板 → 交易单 Excel。
 *
 * 后端只返回权重与预估价格，不落绝对金额；金额与数量由看板按用户输入的
 * 模拟规模算好后传进来，本模块只做「行整理 + 落表 + 触发下载」，
 * 不参与任何业务口径计算，避免同一份换算逻辑在两处漂移。
 */
import * as XLSX from 'xlsx';

/** 表头：权重类的单位写在列名里，单元格保持纯数值，便于 Excel 侧继续求和排序 */
export const TRADE_SHEET_HEADERS = [
  '资产代码',
  '资产名称',
  '所属策略',
  '策略内权重（%）',
  '组合穿透权重（%）',
  '变动比例（%）',
  '动作',
  '预估价格',
  '价格日期',
  '变动金额（元）',
  '变动数量'
];

const ACTION_LABEL = { buy: '买入', sell: '卖出', hold: '不变' };

/** 小数权重 → 百分点数值；空值留空而不是写 0 */
function pctValue(ratio) {
  if (ratio == null || ratio === '') return '';
  const n = Number(ratio);
  if (!Number.isFinite(n)) return '';
  return Math.round(n * 100 * 10000) / 10000;
}

/** 数值保留两位；空值留空 */
function moneyValue(v) {
  if (v == null || v === '') return '';
  const n = Number(v);
  if (!Number.isFinite(n)) return '';
  return Math.round(n * 100) / 100;
}

/**
 * 树行 → 工作表二维数组（只取资产行，策略行是分组汇总，不构成交易指令）。
 *
 * @param {Array<Object>} treeRows 看板树：策略行带 children，资产行是叶子
 * @returns {Array<Array>} 含表头的二维数组
 */
export function buildTradeSheetRows(treeRows) {
  const rows = [];
  (treeRows || []).forEach(group => {
    (group.children || []).forEach(asset => {
      rows.push([
        asset.code || '',
        asset.name || '',
        group.name || '',
        pctValue(asset.strategyWeight),
        pctValue(asset.targetWeight),
        pctValue(asset.changeWeight),
        ACTION_LABEL[asset.action] || '',
        asset.price == null ? '' : Number(asset.price),
        asset.priceDate || '',
        moneyValue(asset.changeAmount),
        asset.changeQty == null ? '' : Number(asset.changeQty)
      ]);
    });
  });
  return [TRADE_SHEET_HEADERS, ...rows];
}

/** 文件名里的日期/策略名去掉 Windows 不允许的字符 */
function safeName(text) {
  return String(text || '').replace(/[\\/:*?"<>|]/g, '_').trim();
}

/**
 * 生成并下载交易单。
 *
 * @param {Object} options
 * @param {Array<Array>} options.rows   buildTradeSheetRows 的输出
 * @param {string} options.strategyLabel 策略/组合展示名，用于文件名与工作表名
 * @param {string} options.executeDate   本指令执行日
 * @param {number} options.scale         模拟管理规模（元），写入页脚口径说明
 */
export function downloadTradeSheet({ rows, strategyLabel, executeDate, scale }) {
  const sheet = XLSX.utils.aoa_to_sheet(rows || []);
  // 列宽贴着内容给：资产名与所属策略最长，其余是数字列
  sheet['!cols'] = [
    { wch: 14 }, { wch: 22 }, { wch: 20 },
    { wch: 14 }, { wch: 16 }, { wch: 12 },
    { wch: 8 }, { wch: 12 }, { wch: 13 },
    { wch: 16 }, { wch: 12 }
  ];

  const workbook = XLSX.utils.book_new();
  // 工作表名上限 31 字符，超长会被 Excel 拒绝
  XLSX.utils.book_append_sheet(workbook, sheet, safeName(strategyLabel).slice(0, 28) || '交易单');

  const name = `交易单_${safeName(strategyLabel) || '组合'}_${executeDate || ''}.xlsx`
    .replace(/__+/g, '_');
  XLSX.writeFile(workbook, name);

  return { file_name: name, row_count: Math.max(0, (rows || []).length - 1), scale };
}
