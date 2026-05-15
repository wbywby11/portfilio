/**
 * 数据资产管理 API（/api/v1/data-assets）
 */

import request from '@/utils/request';

const BASE = '/api/v1/data-assets';

/** 获取数据资产列表 */
export function listDataAssets(params) {
  return request({ url: BASE, method: 'get', params });
}

/** 获取汇总统计 */
export function getDataAssetSummary() {
  return request({ url: `${BASE}/summary`, method: 'get' });
}

/** 获取单个资产详情 */
export function getDataAsset(assetId) {
  return request({ url: `${BASE}/${encodeURIComponent(assetId)}`, method: 'get' });
}

/** 创建数据资产 */
export function createDataAsset(data) {
  return request({ url: BASE, method: 'post', data });
}

/** 更新数据资产 */
export function updateDataAsset(assetId, data) {
  return request({ url: `${BASE}/${encodeURIComponent(assetId)}`, method: 'put', data });
}

/** 触发数据同步 */
export function syncDataAsset(assetId) {
  return request({ url: `${BASE}/${encodeURIComponent(assetId)}/sync`, method: 'post', timeout: 120000 });
}

/** 刷新统计信息 */
export function refreshDataAssetStats(assetId) {
  return request({ url: `${BASE}/${encodeURIComponent(assetId)}/refresh-stats`, method: 'post' });
}

/** 从连接器初始化 */
export function seedDataAssets() {
  return request({ url: `${BASE}/seed`, method: 'post', timeout: 120000 });
}

export default {
  listDataAssets,
  getDataAssetSummary,
  getDataAsset,
  createDataAsset,
  updateDataAsset,
  syncDataAsset,
  refreshDataAssetStats,
  seedDataAssets
};
