import request from '@/utils/request';

/**
 * 模拟交易相关 API
 */

// 推进模拟交易到指定日期
export function advanceSimTrade(portfolioId, data = {}) {
  return request({
    url: `/api/v1/sim-trade/${portfolioId}/advance`,
    method: 'post',
    data,
    timeout: 300000
  });
}

// 批量推进所有模拟组合
export function batchAdvanceSimTrade(data = {}) {
  return request({
    url: '/api/v1/sim-trade/batch-advance',
    method: 'post',
    data,
    timeout: 300000
  });
}

// 查询成交记录
export function getSimTrades(portfolioId, params = {}) {
  return request({
    url: `/api/v1/sim-trade/${portfolioId}/trades`,
    method: 'get',
    params
  });
}

// 查询逐日快照
export function getSimSnapshots(portfolioId, params = {}) {
  return request({
    url: `/api/v1/sim-trade/${portfolioId}/snapshots`,
    method: 'get',
    params
  });
}

// 跟踪误差报告
export function getTrackingReport(portfolioId) {
  return request({
    url: `/api/v1/sim-trade/${portfolioId}/tracking`,
    method: 'get'
  });
}

// 绩效归因报告
export function getAttributionReport(portfolioId) {
  return request({
    url: `/api/v1/sim-trade/${portfolioId}/attribution`,
    method: 'get'
  });
}
