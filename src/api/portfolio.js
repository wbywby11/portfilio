import request from '@/utils/request';

/**
 * 投资组合管理 API
 *
 * 支持三种来源的组合创建与管理：
 * - MANUAL: 手工创建
 * - SINGLE_STRATEGY: 单策略模型驱动
 * - PORTFOLIO_MODEL: 多策略组合模型驱动
 */

// ============================================================
// 查询
// ============================================================

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

// 获取组合完整详情（含子策略分解、相关性分析）
export function getPortfolioDetails(portfolioId) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/details`,
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

// 获取调仓记录
export function getRebalanceRecords(portfolioId) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/rebalance-records`,
    method: 'get'
  });
}

// ============================================================
// 创建
// ============================================================

// 手工创建组合
export function createPortfolio(data) {
  return request({
    url: '/api/v1/portfolios/',
    method: 'post',
    data
  });
}

// 从单策略模型创建组合
export function createFromModel(data) {
  return request({
    url: '/api/v1/portfolios/from-model',
    method: 'post',
    data,
    timeout: 300000
  });
}

// 从组合模型（多策略）创建组合
export function createFromPortfolioModel(data) {
  return request({
    url: '/api/v1/portfolios/from-portfolio-model',
    method: 'post',
    data,
    timeout: 300000
  });
}

// 从多个已发布策略直接组合创建
export function createFromStrategies(data) {
  return request({
    url: '/api/v1/portfolios/from-strategies',
    method: 'post',
    data,
    timeout: 300000
  });
}

// ============================================================
// 操作
// ============================================================

// 手动调整子策略权重
export function adjustWeights(portfolioId, data) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/weights`,
    method: 'patch',
    data
  });
}

// 更新分析笔记
export function updatePortfolioNote(portfolioId, data) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/note`,
    method: 'patch',
    data
  });
}

// 编辑组合基本信息
export function updatePortfolio(portfolioId, data) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}`,
    method: 'patch',
    data
  });
}

// 删除组合
export function deletePortfolio(portfolioId) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}`,
    method: 'delete'
  });
}

// ============================================================
// 组合回测
// ============================================================

// 执行组合回测
export function runPortfolioBacktest(portfolioId, data) {
  return request({
    url: `/api/v1/backtests/run-portfolio-by-id/${portfolioId}`,
    method: 'post',
    data,
    timeout: 600000  // 10分钟超时
  });
}

// 获取组合回测历史记录
export function getPortfolioBacktests(portfolioId, params = {}) {
  return request({
    url: `/api/v1/portfolios/${portfolioId}/backtests`,
    method: 'get',
    params
  });
}
