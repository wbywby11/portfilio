import dayjs from 'dayjs';

/**
 * 时间轴标签格式化工具（净值/走势类图表通用）
 *
 * 背景：早期多个图表把日期轴固定格式化为 MM-DD，跨多年的序列
 * 无法区分年份，用户难以定位时间。此处按数据跨度自适应：
 * - 跨年序列：显示 YYYY-MM，保证年份可见
 * - 单年序列：显示 MM-DD，保持紧凑
 */

/** 提取日期值中的年份（兼容 YYYY-MM-DD 字符串与时间戳） */
function extractYear(d) {
  if (d == null) return null;
  const s = String(d);
  const m = s.match(/^(\d{4})[-/]/);
  if (m) return m[1];
  const y = dayjs(d).year();
  return Number.isNaN(y) ? null : String(y);
}

/** 判断日期序列是否跨越多个年份 */
export function spansMultipleYears(dates) {
  const years = new Set();
  (dates || []).forEach(d => {
    const y = extractYear(d);
    if (y != null) years.add(y);
  });
  return years.size > 1;
}

/**
 * 根据日期序列生成 xAxis.axisLabel.formatter
 * @param {Array} dates 完整日期序列（建议传入降采样前的原始序列）
 * @returns {Function} (value) => string，可直接用于 ECharts axisLabel.formatter
 */
export function createDateAxisLabelFormatter(dates) {
  const pattern = spansMultipleYears(dates) ? 'YYYY-MM' : 'MM-DD';
  return (value) => dayjs(value).format(pattern);
}
