import request from '@/utils/request';

/**
 * 导入交易日历（Excel 文件上传）
 * @param {File} file - 交易日历 Excel 文件
 * @param {Object} [options]
 * @param {'replace'|'incremental'} [options.mode] - 导入模式
 * @returns {Promise}
 */
export function importTradeCalendar(file, options = {}) {
  const formData = new FormData();
  formData.append('file', file);
  if (options.mode) formData.append('mode', options.mode);
  return request({
    url: '/api/v1/trade-calendar/import',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000
  });
}

/**
 * 手动添加交易日期
 * @param {Object} data - { date: 'YYYY-MM-DD', ... }
 * @returns {Promise}
 */
export function addTradeDate(data) {
  return request({
    url: '/api/v1/trade-calendar/manual',
    method: 'post',
    data
  });
}

/**
 * 删除交易日期
 * @param {string} date - 待删除的交易日期（YYYY-MM-DD）
 * @returns {Promise}
 */
export function deleteTradeDate(date) {
  return request({
    url: `/api/v1/trade-calendar/${date}`,
    method: 'delete'
  });
}

/**
 * 获取交易日历统计信息
 * @returns {Promise}
 */
export function getTradeCalendarStats() {
  return request({
    url: '/api/v1/trade-calendar/stats',
    method: 'get'
  });
}

/**
 * 获取交易日期列表（支持年份过滤）
 * @param {Object} params - 查询参数（如 { year }）
 * @returns {Promise}
 */
export function getTradeCalendarDates(params) {
  return request({
    url: '/api/v1/trade-calendar/dates',
    method: 'get',
    params
  });
}
