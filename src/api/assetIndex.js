import request from '@/utils/request';

/**
 * 大类资产指数 API
 * risk budget vol + 混合动量资产选择策略回测
 */

// 获取可选开始日期列表（从净值文件第一日提取）
export function getAssetIndexStartDates() {
  return request({
    url: '/api/v1/asset-index/start-dates',
    method: 'get'
  });
}

// 运行大类资产指数回测
export function runAssetIndexBacktest(params) {
  return request({
    url: '/api/v1/asset-index/backtest',
    method: 'get',
    params: {
      vol_threshold: params.volThreshold,
      start_date: params.startDate,
      end_date: params.endDate
    },
    timeout: 120000
  });
}
