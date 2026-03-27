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

// 获取资产K线数据
export function getAssetKline(assetCode, params) {
  return request({
    url: `/api/v1/assets/${assetCode}/kline`,
    method: 'get',
    params: {
      start_date: params.start_date,
      end_date: params.end_date
    }
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

// 下载资产行情导入模板
export function downloadPriceTemplate() {
  return request({
    url: '/api/v1/assets/prices/template/download',
    method: 'get',
    responseType: 'blob'
  });
}

// 从Excel导入资产行情数据（大批量可能较慢，单独延长超时）
// onlyDate: 可选 YYYY-MM-DD，仅导入 Excel 中该日期的行（补单日）
export function importPricesFromExcel(assetCode, file, replaceExisting = false, onlyDate = null) {
  const params = {
    asset_code: assetCode,
    replace_existing: replaceExisting
  };
  if (onlyDate) {
    params.only_date = onlyDate;
  }
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/prices/import/excel',
    method: 'post',
    params,
    data: formData,
    timeout: 120000
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
      prices: payload.prices || []
    },
    timeout: 60000
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
export function previewMultiAssetImport(file) {
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/prices/import/multi-asset/preview',
    method: 'post',
    data: formData,
    timeout: 60000
  });
}

// 多资产Excel解析（返回完整资产+行情，供逐条导入）
export function parseMultiAssetExcel(file) {
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/prices/import/multi-asset/parse',
    method: 'post',
    data: formData,
    timeout: 120000
  });
}

// 单资产导入（多资产逐条调用，用于进度展示）
export function importSingleAssetFromMulti(data) {
  return request({
    url: '/api/v1/assets/prices/import/multi-asset/single',
    method: 'post',
    data,
    timeout: 120000
  });
}
