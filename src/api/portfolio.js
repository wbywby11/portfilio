import request from '@/utils/request';

/**
 * 模拟组合相关API
 */

// 获取组合列表
export function getPortfolioList() {
  return request({
    url: '/api/v1/portfolios/',
    method: 'get'
  });
}

// 获取单个组合
export function getPortfolio(portfolioId) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}`,
    method: 'get'
  });
}

// 创建模拟组合
export function createPortfolio(data) {
  return request({
    url: '/api/v1/portfolios/',
    method: 'post',
    data
  });
}

// 记录调仓
export function addRebalanceRecord(portfolioId, data) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/rebalance`,
    method: 'post',
    data
  });
}

// 获取调仓记录列表
export function getRebalanceRecords(portfolioId) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/rebalance-records`,
    method: 'get'
  });
}

// 获取组合分析数据
export function getPortfolioAnalysis(portfolioId) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/analysis`,
    method: 'get'
  });
}

// 删除组合
export function deletePortfolio(portfolioId) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}`,
    method: 'delete'
  });
}

// 获取组合详情（包含业绩和持仓）
export function getPortfolioDetails(portfolioId) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/details`,
    method: 'get'
  });
}
