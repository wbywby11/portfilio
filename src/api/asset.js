import request from '@/utils/request';

/**
 * 资产管理相关API
 */

// 获取资产列表
export function getAssetList(params) {
  return request({
    url: '/api/v1/assets/',
    method: 'get',
    params: {
      asset_type: params.asset_type,
      is_active: params.is_active !== undefined ? params.is_active : true,
      skip: params.skip || 0,
      limit: params.limit || 100
    }
  });
}

// 获取资产下拉选项（精简）
export function getAssetOptions(assetType) {
  const params = {};
  if (assetType) {
    params.asset_type = assetType;
  }
  return request({
    url: '/api/v1/assets/options',
    method: 'get',
    params
  });
}

// 创建资产
export function createAsset(data) {
  return request({
    url: '/api/v1/assets/',
    method: 'post',
    data
  });
}

// 更新资产
export function updateAsset(assetId, data) {
  return request({
    url: `/api/v1/assets/${assetId}`,
    method: 'put',
    data
  });
}

// 获取资产详情
export function getAssetDetail(assetId) {
  return request({
    url: `/api/v1/assets/${assetId}`,
    method: 'get'
  });
}

// 删除资产
export function deleteAsset(assetId) {
  return request({
    url: `/api/v1/assets/${assetId}`,
    method: 'delete'
  });
}

// 获取资产K线数据（默认由后端按交易日历裁剪；需要含假期的完整序列时传 all_calendar_days: true）
export function getAssetKline(assetCode, params = {}) {
  const query = {
    start_date: params.start_date,
    end_date: params.end_date
  };
  if (params.all_calendar_days === true) {
    query.all_calendar_days = true;
  }
  return request({
    url: `/api/v1/assets/${assetCode}/kline`,
    method: 'get',
    params: query
  });
}

// 下载资产导入模板
export function downloadAssetTemplate() {
  return request({
    url: '/api/v1/assets/template/download',
    method: 'get',
    responseType: 'blob'
  });
}

// 批量从Excel导入资产
export function importAssetsFromExcel(file) {
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/import/excel',
    method: 'post',
    data: formData
    // 不要设置 Content-Type：让浏览器/axios 自动带 boundary，否则后端无法解析
  });
}

// 下载单资产纵向行情批量导入模板（与「批量导入行情」配套）
// kind: full | open | high | low | close | volume | amount | scale
export function downloadPriceTemplate(kind = 'full') {
  return request({
    url: '/api/v1/assets/prices/template/download',
    method: 'get',
    params: { kind },
    responseType: 'blob'
  });
}

// 下载多资产宽表导入模板（与「多资产Excel导入」配套）
// metric: close | open | high | low | amount | volume | scale
export function downloadMultiAssetPriceTemplate(metric = 'close') {
  return request({
    url: '/api/v1/assets/prices/template/download/multi-asset',
    method: 'get',
    params: { metric },
    responseType: 'blob'
  });
}

// 从Excel导入资产行情数据（大批量可能较慢，单独延长超时）
// onlyDate: 可选 YYYY-MM-DD，仅导入 Excel 中该日期的行（补单日）
export function importPricesFromExcel(
  assetCode,
  file,
  replaceExisting = false,
  onlyDate = null,
  onlyMissingDates = false
) {
  const params = {
    asset_code: assetCode,
    replace_existing: replaceExisting
  };
  if (onlyDate) {
    params.only_date = onlyDate;
  }
  if (onlyMissingDates) {
    params.only_missing_dates = true;
  }
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/prices/import/excel',
    method: 'post',
    params,
    data: formData,
    timeout: 600000
  });
}

/** JSON 导入行情（可单条补录） */
export function importPricesJson(payload) {
  return request({
    url: '/api/v1/assets/prices/import',
    method: 'post',
    data: {
      asset_code: payload.asset_code,
      replace_existing: !!payload.replace_existing,
      only_missing_dates: !!payload.only_missing_dates,
      prices: payload.prices || []
    },
    timeout: 600000
  });
}

/** 区间内相对交易日历缺失的行情日期 */
export function getPriceCoverageGaps(params) {
  return request({
    url: '/api/v1/assets/prices/coverage-gaps',
    method: 'get',
    params: {
      asset_code: params.asset_code,
      start_date: params.start_date,
      end_date: params.end_date
    }
  });
}

// ========== 多资产行情导入（大类资产底层数据-含插件.xlsx 格式） ==========

// 多资产导入预览（解析冲突信息）
export function previewMultiAssetImport(file, metric = 'close') {
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/prices/import/multi-asset/preview',
    method: 'post',
    data: formData,
    params: { metric },
    timeout: 600000
  });
}

// 多资产Excel解析（返回完整资产+行情，供逐条导入）
export function parseMultiAssetExcel(file, metric = 'close') {
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/prices/import/multi-asset/parse',
    method: 'post',
    data: formData,
    params: { metric },
    timeout: 600000
  });
}

/** 多资产分析：匹配类型 + 完整行情（推荐用于向导式导入） */
export function analyzeMultiAssetImport(file, metric = 'close') {
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/prices/import/multi-asset/analyze',
    method: 'post',
    data: formData,
    params: { metric },
    timeout: 600000
  });
}

/** 切换「将导入至」目标代码后，刷新单行库内区间与导入影响统计 */
export function getMultiAssetRowPreviewStats(payload) {
  return request({
    url: '/api/v1/assets/prices/import/multi-asset/row-preview-stats',
    method: 'post',
    data: {
      target_code: payload.target_code,
      prices: payload.prices || []
    },
    timeout: 600000
  });
}

// 单资产导入（多资产逐条调用，用于进度展示；单资产可含多年日频数据，与 analyze 一致放宽超时）
export function importSingleAssetFromMulti(data) {
  return request({
    url: '/api/v1/assets/prices/import/multi-asset/single',
    method: 'post',
    data,
    timeout: 600000
  });
}

/** 轮询单条行情导入进度（与 importSingleAssetFromMulti 的 progress_id 对应） */
export function getPriceImportProgress(progressId) {
  return request({
    url: '/api/v1/assets/prices/import/progress',
    method: 'get',
    params: { progress_id: progressId }
  });
}
