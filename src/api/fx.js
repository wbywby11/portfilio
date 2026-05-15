import request from '@/utils/request';

/**
 * 导入汇率数据（fx.xlsx 格式）
 * @param {File} file - fx.xlsx 文件
 * @param {Object} [options]
 * @param {'replace'|'incremental'} [options.mode] - replace 全量覆盖；incremental 仅填补缺失日期与空字段
 * @returns {Promise}
 */
export function importFxRates(file, options = {}) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('mode', options.mode === 'incremental' ? 'incremental' : 'replace');
  return request({
    url: '/api/v1/fx/import',
    method: 'post',
    data: formData,
    timeout: 120000
  });
}

/**
 * 手动录入单日汇率（对人民币，大于 0 的字段会写入，其余列保留库中原值）
 * @param {Object} data - { date: 'YYYY-MM-DD', EUR?, USD?, HKD?, CNH? }
 */
export function saveFxManualRates(data) {
  return request({
    url: '/api/v1/fx/manual',
    method: 'post',
    data
  });
}

/**
 * 获取汇率数据统计
 * @returns {Promise}
 */
export function getFxStats() {
  return request({
    url: '/api/v1/fx/stats',
    method: 'get'
  });
}

/**
 * 获取汇率时序数据（用于图表展示）
 * @param {Object} params - { startDate, endDate }
 * @returns {Promise}
 */
export function getFxRates(params = {}) {
  return request({
    url: '/api/v1/fx/rates',
    method: 'get',
    params: { start_date: params.startDate, end_date: params.endDate }
  });
}
