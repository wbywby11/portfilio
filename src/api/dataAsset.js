/**
 * 数据资产管理 API（/api/v1/data-assets）
 * 基于 MongoDB 实际集合的元数据注册表
 */

import request from '@/utils/request';

const BASE = '/api/v1/data-assets';

/** 扫描数据库所有集合 */
export function scanDatabase() {
  return request({ url: BASE + '/scan', method: 'post', timeout: 120000 });
}

/** 获取汇总统计 */
export function getDataAssetSummary() {
  return request({ url: BASE + '/summary', method: 'get' });
}

/** 列出所有集合资产（分页） */
export function listDataAssets(params) {
  return request({ url: BASE, method: 'get', params });
}

/** 获取单个集合详情 */
export function getDataAsset(collectionName) {
  return request({ url: BASE + '/' + encodeURIComponent(collectionName), method: 'get' });
}

/** 更新集合描述/标签 */
export function updateDataAsset(collectionName, data) {
  return request({ url: BASE + '/' + encodeURIComponent(collectionName), method: 'put', data });
}

/** 刷新单个集合统计 */
export function refreshDataAsset(collectionName) {
  return request({ url: BASE + '/' + encodeURIComponent(collectionName) + '/refresh', method: 'post' });
}

/** 数据预览 */
export function previewDataAsset(collectionName, limit) {
  return request({ url: BASE + '/' + encodeURIComponent(collectionName) + '/preview', method: 'get', params: { limit: limit || 10 } });
}

export default {
  scanDatabase,
  getDataAssetSummary,
  listDataAssets,
  getDataAsset,
  updateDataAsset,
  refreshDataAsset,
  previewDataAsset
};
