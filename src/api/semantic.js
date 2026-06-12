import request from '@/utils/request'

const BASE_URL = '/api/v1/semantic'

// 获取9域概览
export function getSemanticOverview() {
  return request({ url: `${BASE_URL}/overview`, method: 'get' })
}

// 获取图谱数据（节点+边）
export function getLineageGraph(domain) {
  const params = domain ? { domain } : {}
  return request({ url: `${BASE_URL}/graph`, method: 'get', params })
}

// 获取单表画像
export function getTableProfile(tableName) {
  return request({ url: `${BASE_URL}/table/${tableName}`, method: 'get' })
}

// 获取域内画像
export function getDomainProfile(domainCode) {
  return request({ url: `${BASE_URL}/domain/${domainCode}`, method: 'get' })
}

// 搜索画像
export function searchProfiles(query) {
  return request({ url: `${BASE_URL}/search`, method: 'get', params: { q: query } })
}

// 获取动态统计
export function getDynamicStats(tableName) {
  return request({ url: `${BASE_URL}/dynamic/${tableName}`, method: 'get' })
}

// 获取跨域画像列表
export function getCrossDomainProfiles() {
  return request({ url: `${BASE_URL}/cross-domain`, method: 'get' })
}

// 获取联动画像列表
export function getResonanceProfiles() {
  return request({ url: `${BASE_URL}/resonance`, method: 'get' })
}

// === L5 统计语义画像 ===
export function getStatsProfile(tableName) {
  return request({ url: `${BASE_URL}/stats-profile/${tableName}`, method: 'get' })
}
export function generateStatsProfile(tableName) {
  return request({ url: `${BASE_URL}/stats-profile/${tableName}/generate`, method: 'post' })
}
export function getDomainMacro(domainCode) {
  return request({ url: `${BASE_URL}/domain-macro/${domainCode}`, method: 'get' })
}
export function generateDomainMacro(domainCode) {
  return request({ url: `${BASE_URL}/domain-macro/${domainCode}/generate`, method: 'post' })
}
export function getCrossResonance() {
  return request({ url: `${BASE_URL}/cross-resonance`, method: 'get' })
}
export function getCrossResonanceDetail(scenarioId) {
  return request({ url: `${BASE_URL}/cross-resonance/${scenarioId}`, method: 'get' })
}
export function generateCrossResonance() {
  return request({ url: `${BASE_URL}/cross-resonance/generate`, method: 'post' })
}
export function getDomainFull(domainCode) {
  return request({ url: `${BASE_URL}/domain/${domainCode}/full`, method: 'get' })
}

// 获取表数据预览（小窗用）
export function getTableData(tableName, limit = 20) {
  return request({ url: `${BASE_URL}/table-data/${tableName}`, method: 'get', params: { limit } })
}
