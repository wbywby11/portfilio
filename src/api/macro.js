import request from '@/utils/request';

const BASE = '/api/v1/macro';

/**
 * 导入宏观与估值序列（Excel）
 * @param {File} file - 数据表：第一列日期，后续列名为序列代码；可带「序列说明」工作表
 * @param {Object} [options]
 * @param {'replace'|'incremental'} [options.mode] - replace 按序列覆盖；incremental 只补缺失 (序列, 日期)
 * @returns {Promise}
 */
export function importMacroSeries(file, options = {}) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('mode', options.mode === 'incremental' ? 'incremental' : 'replace');
  return request({
    url: `${BASE}/import`,
    method: 'post',
    data: formData,
    timeout: 180000
  });
}

/**
 * 集合级统计：总条数、序列数、日期范围、按序列类型分组
 * @returns {Promise}
 */
export function getMacroStats() {
  return request({
    url: `${BASE}/stats`,
    method: 'get'
  });
}

/**
 * 列出库内全部序列
 * @param {Object} [params] - { seriesType }
 * @returns {Promise}
 */
export function listMacroSeries(params = {}) {
  return request({
    url: `${BASE}/series`,
    method: 'get',
    params: { series_type: params.seriesType }
  });
}

/**
 * 取单条序列的逐日取值（图表用）
 * @param {string} code - 序列代码
 * @param {Object} [params] - { startDate, endDate }
 * @returns {Promise}
 */
export function getMacroSeriesData(code, params = {}) {
  return request({
    url: `${BASE}/data`,
    method: 'get',
    params: { code, start_date: params.startDate, end_date: params.endDate }
  });
}

/**
 * 下载导入模板（数据 sheet + 序列说明 sheet）
 * @returns {Promise<Blob>}
 */
export function downloadMacroTemplate() {
  return request({
    url: `${BASE}/template/download`,
    method: 'get',
    responseType: 'blob'
  });
}
