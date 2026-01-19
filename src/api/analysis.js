import request from '@/utils/request';

/**
 * 资产分析相关API
 */

// 获取资产指标
export function getAssetMetrics(data) {
  return request({
    url: '/api/v1/analysis/asset-metrics',
    method: 'post',
    data
  });
}

// 获取相关性矩阵
export function getCorrelationMatrix(data, method = 'pearson') {
  return request({
    url: '/api/v1/analysis/correlation-matrix',
    method: 'post',
    params: { method },
    data
  });
}

// 获取时间序列数据
export function getTimeSeriesData(data) {
  return request({
    url: '/api/v1/analysis/timeseries',
    method: 'post',
    data
  });
}

// 获取仪表盘数据
export function getDashboardData(data) {
  return request({
    url: '/api/v1/analysis/dashboard',
    method: 'post',
    data
  });
}
