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
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
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

// 从Excel导入资产行情数据
export function importPricesFromExcel(assetCode, file, replaceExisting = false) {
  const formData = new FormData();
  formData.append('file', file);
  return request({
    url: '/api/v1/assets/prices/import/excel',
    method: 'post',
    params: {
      asset_code: assetCode,
      replace_existing: replaceExisting
    },
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  });
}
