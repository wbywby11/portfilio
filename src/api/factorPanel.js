import request from '@/utils/request';

// 因子截面数据（factor_panel 集合）
// 一个数据集（dataset）的一期（as_of_date）一股（code）一行，因子值收在 factors 里。
// 本集合被多个数据集共用，除模板下载外所有接口都必须带 dataset，
// 后端对缺失或不在受控清单内的 dataset 直接返回 400。

const BASE = '/api/v1/factor-panel';

/**
 * 数据集清单（含各自行数/期数/起止期日），供下拉选择
 * @returns {Promise} data: [{ dataset, label, registered, row_count, period_count, start_date, end_date, code_count }]
 */
export function listFactorPanelDatasets() {
  return request({
    url: `${BASE}/datasets`,
    method: 'get'
  });
}

/**
 * 总览：统计、期清单、因子键清单
 * @param {string} [dataset] - 留空返回全部数据集合计
 * @returns {Promise} data: { stats, periods, factor_names }
 */
export function getFactorPanelOverview(dataset) {
  return request({
    url: `${BASE}/overview`,
    method: 'get',
    params: dataset ? { dataset } : {}
  });
}

/**
 * 导入因子截面 Excel（一个文件可含任意期数，按「日期」列自动分期）
 * @param {File} file - Excel 文件
 * @param {Object} options
 * @param {string} options.dataset - 目标数据集，必填
 * @param {'upsert'|'replace'|'incremental'} [options.mode] - 导入模式，默认 upsert
 * @param {string} [options.asOfDate] - 文件无生效日列时作为整期生效日
 * @param {boolean} [options.dryRun] - true=只预演不写库
 * @returns {Promise} data: ImportResponse + { dataset, periods, period_rows, factor_keys, warnings }
 */
export function importFactorPanel(file, options = {}) {
  if (!options.dataset) {
    return Promise.reject(new Error('缺少 dataset：因子截面导入必须指明写入哪个数据集'));
  }
  const formData = new FormData();
  formData.append('file', file);
  formData.append('dataset', options.dataset);
  if (options.mode) formData.append('mode', options.mode);
  if (options.asOfDate) formData.append('as_of_date', options.asOfDate);
  if (options.dryRun) formData.append('dry_run', 'true');
  return request({
    url: `${BASE}/import`,
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    // 券池单期数百行、多期文件上千行，解析比汇率导入慢，单独放宽
    timeout: 120000
  });
}

/**
 * 下载导入模板（模板按数据集出，因子列与说明各不相同）
 * @param {string} dataset - 数据集标识
 * @returns {Promise<Blob>}
 */
export function downloadFactorPanelTemplate(dataset) {
  return request({
    url: `${BASE}/template/download`,
    method: 'get',
    params: { dataset },
    responseType: 'blob'
  });
}

/**
 * 读取某数据集某一期的全部截面行（导入后人工核对）
 * @param {string} dataset - 数据集标识
 * @param {string} asOfDate - 期日 YYYY-MM-DD
 * @returns {Promise} data: { dataset, as_of_date, row_count, rows }
 */
export function getFactorPanelPeriod(dataset, asOfDate) {
  return request({
    url: `${BASE}/period/${dataset}/${asOfDate}`,
    method: 'get'
  });
}

/**
 * 整期删除（导错重来）；只删本数据集的该期
 * @param {string} dataset - 数据集标识
 * @param {string} asOfDate - 期日 YYYY-MM-DD
 * @returns {Promise} data: { dataset, as_of_date, deleted_count }
 */
export function deleteFactorPanelPeriod(dataset, asOfDate) {
  return request({
    url: `${BASE}/period/${dataset}/${asOfDate}`,
    method: 'delete'
  });
}
