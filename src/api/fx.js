import request from '@/utils/request';

/**
 * 导入汇率数据（fx.xlsx 格式）
 * @param {File} file - fx.xlsx 文件
 * @returns {Promise}
 */
export function importFxRates(file) {
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/fx/import',
    method: 'post',
    data: formData,
    timeout: 120000
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
