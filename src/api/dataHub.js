/**
 * 通用数据接入 Hub API（/api/v1/data-hub）
 */

import request from '@/utils/request';

const BASE = '/api/v1/data-hub';

/** 连接器元数据（含 ui_import_fields / ui_filter_fields / chart_hints） */
export function listConnectors() {
  return request({ url: `${BASE}/connectors`, method: 'get', timeout: 60000 });
}

export function importDataHub(connectorId, payload) {
  const id = encodeURIComponent(connectorId);
  return request({
    url: `${BASE}/${id}/import`,
    method: 'post',
    data: payload,
    timeout: 300000
  });
}

export function queryDataHubRecords(connectorId, query = {}) {
  const id = encodeURIComponent(connectorId);
  return request({
    url: `${BASE}/${id}/records`,
    method: 'post',
    data: query,
    timeout: 60000
  });
}

export function getDataHubRecord(connectorId, pk) {
  const id = encodeURIComponent(connectorId);
  return request({
    url: `${BASE}/${id}/records/${encodeURIComponent(pk)}`,
    method: 'get',
    timeout: 60000
  });
}

export function listDataHubBatches(connectorId, params = {}) {
  const id = encodeURIComponent(connectorId);
  return request({
    url: `${BASE}/${id}/batches`,
    method: 'get',
    params: {
      page: params.page || 1,
      page_size: params.pageSize || 20
    }
  });
}

export function getDataHubBatch(connectorId, batchId) {
  const id = encodeURIComponent(connectorId);
  return request({
    url: `${BASE}/${id}/batches/${encodeURIComponent(batchId)}`,
    method: 'get',
    timeout: 60000
  });
}

export function getDataHubStats(connectorId) {
  const id = encodeURIComponent(connectorId);
  return request({ url: `${BASE}/${id}/stats/overview`, method: 'get', timeout: 60000 });
}

export function getDataHubFields(connectorId) {
  const id = encodeURIComponent(connectorId);
  return request({ url: `${BASE}/${id}/fields`, method: 'get', timeout: 60000 });
}

export function getDataHubDistinct(connectorId, field, limit = 200) {
  const id = encodeURIComponent(connectorId);
  return request({
    url: `${BASE}/${id}/distinct`,
    method: 'get',
    params: { field, limit },
    timeout: 60000
  });
}

export default {
  listConnectors,
  importDataHub,
  queryDataHubRecords,
  getDataHubRecord,
  listDataHubBatches,
  getDataHubBatch,
  getDataHubStats,
  getDataHubFields,
  getDataHubDistinct
};
