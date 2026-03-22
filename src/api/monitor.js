import request from '@/utils/request';

/**
 * 监控相关API
 */

// ========== 状态查询 ==========

// 获取监控状态
export function getMonitorState(monitorId = 'default') {
  return request({
    url: '/api/v1/monitor/state',
    method: 'get',
    params: { monitor_id: monitorId },
    skipGlobal404Message: true
  });
}

// 获取净值历史
export function getNavHistory(params = {}) {
  return request({
    url: '/api/v1/monitor/nav-history',
    method: 'get',
    params: {
      monitor_id: (params && params.monitor_id) || 'default',
      start: params && params.start,
      end: params && params.end
    },
    skipGlobal404Message: true
  });
}

// 获取监控事件日志
export function getMonitorEvents(params = {}) {
  return request({
    url: '/api/v1/monitor/events',
    method: 'get',
    params: {
      monitor_id: (params && params.monitor_id) || 'default',
      type: params && params.type,
      limit: params && params.limit
    }
  });
}

// 获取持仓明细
export function getMonitorPositions(monitorId = 'default') {
  return request({
    url: '/api/v1/monitor/positions',
    method: 'get',
    params: { monitor_id: monitorId }
  });
}

// 获取绩效指标
export function getMonitorPerformance(monitorId = 'default') {
  return request({
    url: '/api/v1/monitor/performance',
    method: 'get',
    params: { monitor_id: monitorId },
    skipGlobal404Message: true
  });
}

// 获取信号状态
export function getMonitorSignals(monitorId = 'default') {
  return request({
    url: '/api/v1/monitor/signals',
    method: 'get',
    params: { monitor_id: monitorId },
    skipGlobal404Message: true
  });
}

// ========== 运行控制 ==========

// 运行监控（单日）
export function runMonitor(data) {
  return request({
    url: '/api/v1/monitor/run',
    method: 'post',
    params: {
      monitor_id: data.monitor_id || 'default',
      target_date: data.target_date
    }
  });
}

// 初始化监控
export function initMonitor(data) {
  return request({
    url: '/api/v1/monitor/init',
    method: 'post',
    params: {
      monitor_id: data.monitor_id || 'default',
      start_date: data.start_date || undefined
    },
    timeout: 600000  // 初始化操作耗时较长，超时设为 10 分钟
  });
}

// 运行监控（日期范围）
export function runMonitorRange(data) {
  return request({
    url: '/api/v1/monitor/run-range',
    method: 'post',
    params: {
      monitor_id: data.monitor_id || 'default',
      from_date: data.from_date,
      to_date: data.to_date
    },
    timeout: 300000  // 范围运行可能较慢，超时设为 5 分钟
  });
}

// ========== 日报 ==========

// 获取指定日期日报
export function getMonitorReport(date, monitorId = 'default') {
  return request({
    url: `/api/v1/monitor/reports/${date}`,
    method: 'get',
    params: { monitor_id: monitorId }
  });
}

// 获取日报列表
export function getMonitorReportList(params = {}) {
  return request({
    url: '/api/v1/monitor/reports',
    method: 'get',
    params: {
      monitor_id: (params && params.monitor_id) || 'default',
      skip: params && params.skip,
      limit: params && params.limit
    }
  });
}

// ========== 主观调仓 ==========

// 获取主观调仓指令列表
export function getSubjectiveOverrides(params = {}) {
  return request({
    url: '/api/v1/monitor/subjective',
    method: 'get',
    params: {
      monitor_id: (params && params.monitor_id) || 'default',
      status: params && params.status
    }
  });
}

// 添加主观调仓指令
export function addSubjectiveOverride(data) {
  return request({
    url: '/api/v1/monitor/subjective',
    method: 'post',
    data: {
      monitor_id: data.monitor_id || 'default',
      weights: data.weights,  // 后端期望 weights 字段
      execute_date: data.execute_date,
      description: data.description
    }
  });
}

// 取消主观调仓指令
export function cancelSubjectiveOverride(overrideId) {
  return request({
    url: `/api/v1/monitor/subjective/${overrideId}/cancel`,
    method: 'put'
  });
}

// ========== 资产分析 ==========

// 获取底层资产相关性矩阵
export function getPositionsCorrelationMatrix(data) {
  return request({
    url: '/api/v1/analysis/correlation-matrix',
    method: 'post',
    data: {
      thscodes: data.thscodes || [],
      start_date: data.start_date,
      end_date: data.end_date
    }
  });
}

// 获取底层资产波动率指标
export function getPositionsAssetMetrics(data) {
  return request({
    url: '/api/v1/analysis/asset-metrics',
    method: 'post',
    data: {
      thscodes: data.thscodes || [],
      start_date: data.start_date,
      end_date: data.end_date
    }
  });
}

// 获取当日损益归因
export function getDailyAttribution(params = {}) {
  return request({
    url: '/api/v1/monitor/daily-attribution',
    method: 'get',
    params: {
      monitor_id: (params && params.monitor_id) || 'default',
      date: params && params.date
    }
  });
}
