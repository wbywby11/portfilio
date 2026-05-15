import request from '@/utils/request';

const BASE = '/api/v1/subject-risk';

/**
 * 从上游拉取并导入主体观点风险数据
 * @param {Object} payload - { startDate, endDate, rownum?, startrow?, resource?, timeout?, upstream_url? }
 */
export function importSubjectRisk(payload) {
  return request({
    url: `${BASE}/import`,
    method: 'post',
    data: payload,
    timeout: 300000
  });
}

/**
 * 分页查询主体观点风险记录
 * @param {Object} query
 */
export function querySubjectRiskRecords(query = {}) {
  return request({
    url: `${BASE}/records`,
    method: 'post',
    data: query,
    timeout: 60000
  });
}

/** 按 risk_id 获取单条记录 */
export function getSubjectRiskRecord(riskId) {
  return request({
    url: `${BASE}/records/${encodeURIComponent(riskId)}`,
    method: 'get'
  });
}

/** 分页查询导入批次历史 */
export function listSubjectRiskBatches(params = {}) {
  return request({
    url: `${BASE}/batches`,
    method: 'get',
    params: {
      page: params.page || 1,
      page_size: params.pageSize || 20
    }
  });
}

/** 获取批次详情 */
export function getSubjectRiskBatch(batchId) {
  return request({
    url: `${BASE}/batches/${encodeURIComponent(batchId)}`,
    method: 'get'
  });
}

/** 统计概览（用于首页/图表） */
export function getSubjectRiskStats() {
  return request({
    url: `${BASE}/stats/overview`,
    method: 'get'
  });
}

/** 字段元数据（来自最近成功批次的 ind_name_list） */
export function getSubjectRiskFields() {
  return request({
    url: `${BASE}/fields`,
    method: 'get'
  });
}

/** 字段枚举值（用于筛选下拉） */
export function getSubjectRiskDistinct(field, limit = 200) {
  return request({
    url: `${BASE}/distinct`,
    method: 'get',
    params: { field, limit }
  });
}

export default {
  importSubjectRisk,
  querySubjectRiskRecords,
  getSubjectRiskRecord,
  listSubjectRiskBatches,
  getSubjectRiskBatch,
  getSubjectRiskStats,
  getSubjectRiskFields,
  getSubjectRiskDistinct
};
