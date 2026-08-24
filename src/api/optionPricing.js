import request from '@/utils/request';

/**
 * 收益凭证估值 API
 */

// ========== 产品 CRUD ==========

// 获取产品列表
export function listOptionProducts(params = {}) {
  return request({
    url: '/api/v1/options/products',
    method: 'get',
    params: {
      type: params.type,
      status: params.status,
      skip: params.skip || 0,
      limit: params.limit || 200
    }
  });
}

// 创建产品
export function createOptionProduct(data) {
  return request({
    url: '/api/v1/options/products',
    method: 'post',
    data
  });
}

// 更新产品
export function updateOptionProduct(productId, data) {
  return request({
    url: `/api/v1/options/products/${productId}`,
    method: 'put',
    data
  });
}

// 删除产品
export function deleteOptionProduct(productId) {
  return request({
    url: `/api/v1/options/products/${productId}`,
    method: 'delete'
  });
}

// ========== 市场数据 ==========

// 导入市场数据
export function importMarketData(records) {
  return request({
    url: '/api/v1/options/market-data/import',
    method: 'post',
    data: { records }
  });
}

// 获取市场数据
export function getMarketData(date) {
  return request({
    url: `/api/v1/options/market-data/${date}`,
    method: 'get'
  });
}

// 从资产库同步行情数据
export function syncMarketDataFromAssets(date) {
  return request({
    url: '/api/v1/options/market-data/sync-from-assets',
    method: 'post',
    data: { date }
  });
}

// ========== 波动率曲面 ==========

// 导入波动率曲面 (JSON)
export function importVolSurface(data) {
  return request({
    url: '/api/v1/options/vol-surface/import',
    method: 'post',
    data
  });
}

// 从Excel导入波动率曲面
export function importVolSurfaceFromExcel(file, underlying) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('underlying', underlying);
  return request({
    url: '/api/v1/options/vol-surface/import/excel',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000
  });
}

// 列出波动率曲面
export function listVolSurfaces() {
  return request({
    url: '/api/v1/options/vol-surface',
    method: 'get'
  });
}

// 获取波动率曲面
export function getVolSurface(underlying) {
  return request({
    url: `/api/v1/options/vol-surface/${underlying}`,
    method: 'get'
  });
}

// ========== 估值运行 ==========

// 运行估值
export function runValuation(data) {
  return request({
    url: '/api/v1/options/valuation/run',
    method: 'post',
    data,
    timeout: 300000  // MC模拟耗时，5分钟超时
  });
}

// 获取估值快照
export function getValuationSnapshot(date) {
  return request({
    url: `/api/v1/options/valuation/snapshot/${date}`,
    method: 'get'
  });
}

// 获取估值历史
export function getValuationHistory(params = {}) {
  return request({
    url: '/api/v1/options/valuation/history',
    method: 'get',
    params: {
      product_id: params.product_id,
      start_date: params.start_date,
      end_date: params.end_date,
      skip: params.skip || 0,
      limit: params.limit || 100
    }
  });
}

// ========== 估值版本管理 ==========

// 获取估值版本列表
export function getValuationVersions(date) {
  return request({
    url: `/api/v1/options/valuation/versions/${date}`,
    method: 'get'
  });
}

// 获取指定版本估值详情
export function getValuationVersionDetail(date, version) {
  return request({
    url: `/api/v1/options/valuation/version/${date}/${version}`,
    method: 'get'
  });
}

// 确认估值版本为最终版
export function confirmValuationVersion(date, version, confirmedBy = '') {
  return request({
    url: `/api/v1/options/valuation/confirm/${date}/${version}`,
    method: 'post',
    data: { confirmed_by: confirmedBy }
  });
}

// 获取产品估值趋势
export function getValuationTrend(productId, startDate, endDate) {
  return request({
    url: '/api/v1/options/valuation/trend',
    method: 'get',
    params: {
      product_id: productId,
      start_date: startDate,
      end_date: endDate
    }
  });
}

// 重跑估值
export function rerunValuation(date, data) {
  return request({
    url: `/api/v1/options/valuation/rerun/${date}`,
    method: 'post',
    data,
    timeout: 300000
  });
}

// ========== 会计辅助 ==========

// 生成会计分录
export function generateAccountingEntries(date) {
  return request({
    url: '/api/v1/options/accounting/generate',
    method: 'post',
    data: { date }
  });
}

// 查询会计分录
export function getAccountingEntries(params = {}) {
  return request({
    url: '/api/v1/options/accounting/entries',
    method: 'get',
    params: {
      date: params.date,
      product_id: params.product_id,
      entry_type: params.entry_type,
      skip: params.skip || 0,
      limit: params.limit || 200
    }
  });
}

// 按科目汇总
export function getAccountingSummary(date) {
  return request({
    url: '/api/v1/options/accounting/summary',
    method: 'get',
    params: { date }
  });
}

// 获取科目配置
export function getAccountingConfig() {
  return request({
    url: '/api/v1/options/accounting/config',
    method: 'get'
  });
}

// 更新科目配置
export function updateAccountingConfig(accountMap) {
  return request({
    url: '/api/v1/options/accounting/config',
    method: 'put',
    data: { account_map: accountMap }
  });
}

// 导出会计分录 Excel
export function exportAccountingEntries(date) {
  return request({
    url: `/api/v1/options/accounting/export?date=${date}`,
    method: 'get',
    responseType: 'blob'
  });
}

// ========== 风险分析 ==========

// 运行风险分析
export function runRiskAnalysis(data) {
  return request({
    url: '/api/v1/options/risk/analysis',
    method: 'post',
    data,
    timeout: 300000
  });
}

// 获取风险报告
export function getRiskReport(date) {
  return request({
    url: `/api/v1/options/risk/report/${date}`,
    method: 'get',
    skipGlobal404Message: true
  });
}

// ========== 事件日志 ==========

// 获取事件日志
export function getOptionEvents(params = {}) {
  return request({
    url: '/api/v1/options/events',
    method: 'get',
    params: {
      product_id: params.product_id,
      event_type: params.event_type,
      skip: params.skip || 0,
      limit: params.limit || 200
    }
  });
}

// ========== 估值数据管理 ==========

// 获取可用标的列表及其数据概况
export function getValuationDataAssets() {
  return request({
    url: '/api/v1/options/valuation-data/assets',
    method: 'get'
  });
}

// 获取指定标的的行情序列
export function getValuationDataPrices(code, params = {}) {
  return request({
    url: `/api/v1/options/valuation-data/prices/${code}`,
    method: 'get',
    params: {
      start_date: params.start_date,
      end_date: params.end_date,
      limit: params.limit || 100
    }
  });
}
