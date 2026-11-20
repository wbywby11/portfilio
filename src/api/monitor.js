import request from '@/utils/request';

/**
 * 监控相关API
 *
 * 批次口径（后端批次化改造后的统一约定）：
 * - 所有展示类 GET 都支持可选 ``batch_id``；不传表示读最新 completed 批次，
 *   传了就读该批次的版本化快照。缓存/快照缺失后端直接 404，不再触发重算。
 * - 所有运行类 POST（run / init / run-range）都是「提交后台任务」，立即返回
 *   ``{task_id, batch_id, status: 'pending'}``，进度靠 getMonitorTask 轮询。
 */

// ========== 状态查询 ==========

// 获取监控状态
export function getMonitorState(monitorId = 'default', batchId) {
  return request({
    url: '/api/v1/monitor/state',
    method: 'get',
    params: { monitor_id: monitorId, batch_id: batchId || undefined },
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
      end: params && params.end,
      batch_id: (params && params.batch_id) || undefined
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
      limit: params && params.limit,
      batch_id: (params && params.batch_id) || undefined
    },
    skipGlobal404Message: true
  });
}

// 获取持仓明细
export function getMonitorPositions(monitorId = 'default', batchId) {
  return request({
    url: '/api/v1/monitor/positions',
    method: 'get',
    params: { monitor_id: monitorId, batch_id: batchId || undefined },
    skipGlobal404Message: true
  });
}

// 获取绩效指标（可选区间，后端裁剪净值序列后交统一内核计算）
export function getMonitorPerformance(monitorId = 'default', params = {}) {
  return request({
    url: '/api/v1/monitor/performance',
    method: 'get',
    params: { monitor_id: monitorId, ...params },
    skipGlobal404Message: true
  });
}

// 获取信号状态（读该批次跑批时物化的信号快照）
export function getMonitorSignals(monitorId = 'default', batchId) {
  return request({
    url: '/api/v1/monitor/signals',
    method: 'get',
    params: { monitor_id: monitorId, batch_id: batchId || undefined },
    skipGlobal404Message: true
  });
}

// 获取风险预警记录（波动率对比 / 相关性反转 / 停更跳过；策略与组合共用）
export function getRiskAlerts(params = {}) {
  return request({
    url: '/api/v1/monitor/risk-alerts',
    method: 'get',
    params: {
      monitor_id: params && params.monitor_id,
      severity: params && params.severity,
      signal_type: params && params.signal_type,
      monitor_kind: params && params.monitor_kind,
      start_date: params && params.start_date,
      end_date: params && params.end_date,
      limit: (params && params.limit) || 50,
      offset: (params && params.offset) || 0,
      batch_id: (params && params.batch_id) || undefined
    },
    skipGlobal404Message: true
  });
}

// 获取操作指令（策略维度分组，待执行置顶）
export function getMonitorOperations(params = {}) {
  return request({
    url: '/api/v1/monitor/operations',
    method: 'get',
    params: {
      monitor_id: (params && params.monitor_id) || 'default',
      status: params && params.status,
      strategy_key: params && params.strategy_key,
      batch_id: (params && params.batch_id) || undefined
    },
    skipGlobal404Message: true
  });
}

// 获取双轨绩效对比（模型口径 vs 实际口径）
export function getDualPerformance(monitorId = 'default', batchId) {
  return request({
    url: '/api/v1/monitor/performance-dual',
    method: 'get',
    params: { monitor_id: monitorId, batch_id: batchId || undefined },
    skipGlobal404Message: true
  });
}

// 获取绩效页统一数据（跑批结束时预计算的缓存，按区间纯读取）
export function getPerformancePanel(params = {}) {
  return request({
    url: '/api/v1/monitor/performance-panel',
    method: 'get',
    params: {
      monitor_id: (params && params.monitor_id) || 'default',
      start: params && params.start,
      end: params && params.end,
      batch_id: (params && params.batch_id) || undefined
    },
    skipGlobal404Message: true
  });
}

// ========== 运行控制（全部为后台任务提交）==========

/**
 * 提交类请求的超时：后端只做「建批次 + 建任务 + 丢给后台」就返回，
 * 真正的推演在任务里跑，因此不再需要改造前的 10 分钟长超时。
 */
const SUBMIT_TIMEOUT = 60000;

// 运行监控（单日）——提交后台任务，返回 {task_id, batch_id, status}
export function runMonitor(data) {
  const params = {
    monitor_id: data.monitor_id || 'default',
    target_date: data.target_date
  };
  if (data.manual_preset_step) {
    params.manual_preset_step = true;
  }
  return request({
    url: '/api/v1/monitor/run',
    method: 'post',
    params,
    timeout: SUBMIT_TIMEOUT
  });
}

// 初始化监控（后台任务：立即返回 task_id，进度通过 getMonitorTask 轮询）
export function initMonitor(data) {
  const asyncMode = data.async_mode !== false;
  const params = {
    monitor_id: data.monitor_id || 'default',
    start_date: data.start_date || undefined,
    async_mode: asyncMode
  };
  if (data.manual_preset_step) {
    params.manual_preset_step = true;
  }
  return request({
    url: '/api/v1/monitor/init',
    method: 'post',
    params,
    // async_mode=false 仅供脚本/调试同步调用，此时才需要长超时
    timeout: asyncMode ? SUBMIT_TIMEOUT : 600000
  });
}

// 查询任务进度（前端轮询；监控 init / run / run-range 与回测进度共用同一张任务表）
// options：透传给 axios 的配置；回测进度为「先轮询后建文档」，需传 skipGlobal404Message 压首轮 404
export function getMonitorTask(taskId, options = {}) {
  return request({
    url: `/api/v1/monitor/tasks/${taskId}`,
    method: 'get',
    // 后端计算繁忙时轮询请求也可能排队，超时需留足余量
    timeout: 120000,
    ...options
  });
}

// 查询监控实例当前进行中的任务（页面刷新后恢复进度）
export function getActiveMonitorTask(monitorId) {
  return request({
    url: '/api/v1/monitor/tasks/active',
    method: 'get',
    params: { monitor_id: monitorId },
    timeout: 120000
  });
}

// 运行监控（日期范围）——提交后台任务，返回 {task_id, batch_id, status}
export function runMonitorRange(data) {
  const params = {
    monitor_id: data.monitor_id || 'default',
    from_date: data.from_date,
    to_date: data.to_date
  };
  if (data.manual_preset_step) {
    params.manual_preset_step = true;
  }
  return request({
    url: '/api/v1/monitor/run-range',
    method: 'post',
    params,
    timeout: SUBMIT_TIMEOUT
  });
}

// ========== 运行批次（版本化产物）==========

// 批次列表：返回 {monitor_id, current_batch_id, items, count}
export function getMonitorBatches(params = {}) {
  return request({
    url: '/api/v1/monitor/batches',
    method: 'get',
    params: {
      monitor_id: params.monitor_id || 'default',
      limit: params.limit || 20,
      skip: params.skip || 0,
      status: params.status || undefined,
      include_deleted: params.include_deleted || undefined
    },
    skipGlobal404Message: true
  });
}

// 批次详情：运行模式 / 起止日期 / 配置快照 / 摘要指标
export function getMonitorBatch(batchId) {
  return request({
    url: `/api/v1/monitor/batches/${batchId}`,
    method: 'get',
    skipGlobal404Message: true
  });
}

// 单批次双轨净值曲线（缓存缺失时 cache_available=false，不报错）
export function getMonitorBatchNavHistory(batchId, params = {}) {
  return request({
    url: `/api/v1/monitor/batches/${batchId}/nav-history`,
    method: 'get',
    params: {
      start: params.start || undefined,
      end: params.end || undefined
    },
    skipGlobal404Message: true
  });
}

// 多批次对比（至少 2 个、最多 5 个批次号）
export function compareMonitorBatches(monitorId, batchIds) {
  return request({
    url: '/api/v1/monitor/batches/compare',
    method: 'get',
    params: {
      monitor_id: monitorId || 'default',
      batch_ids: Array.isArray(batchIds) ? batchIds.join(',') : batchIds
    },
    skipGlobal404Message: true
  });
}

// 删除批次（后端软删除：产物文档全部保留，仅不再作为展示批次）
export function deleteMonitorBatch(batchId) {
  return request({
    url: `/api/v1/monitor/batches/${batchId}`,
    method: 'delete'
  });
}

// ========== 日报 ==========

// 获取指定日期日报
export function getMonitorReport(date, monitorId = 'default', batchId) {
  return request({
    url: `/api/v1/monitor/reports/${date}`,
    method: 'get',
    params: { monitor_id: monitorId, batch_id: batchId || undefined },
    skipGlobal404Message: true
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
      limit: params && params.limit,
      batch_id: (params && params.batch_id) || undefined
    },
    skipGlobal404Message: true
  });
}

// ========== 主观调仓 ==========

// 获取主观调仓指令列表（含从上一批次继承过来的 pending 指令）
export function getSubjectiveOverrides(params = {}) {
  return request({
    url: '/api/v1/monitor/subjective',
    method: 'get',
    params: {
      monitor_id: (params && params.monitor_id) || 'default',
      status: params && params.status,
      batch_id: (params && params.batch_id) || undefined
    },
    skipGlobal404Message: true
  });
}

// 添加主观调仓指令（额外调仓；传 linked_operation_id 时为调仓日比例优化）
export function addSubjectiveOverride(data) {
  const payload = {
    monitor_id: data.monitor_id || 'default',
    weights: data.weights,  // 后端期望 weights 字段
    execute_date: data.execute_date,
    description: data.description
  };
  if (data.linked_operation_id) {
    payload.linked_operation_id = data.linked_operation_id;
  }
  if (data.record_executed) {
    payload.record_executed = true;
  }
  return request({
    url: '/api/v1/monitor/subjective',
    method: 'post',
    data: payload
  });
}

// 操作指令补充说明（remark 存独立集合，按业务键挂靠，组合通道全量重建不丢）
export function updateOperationRemark(operationId, remark) {
  return request({
    url: `/api/v1/monitor/operations/${operationId}/remark`,
    method: 'patch',
    data: { remark: remark || '' },
    skipGlobal404Message: true
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
      date: params && params.date,
      batch_id: (params && params.batch_id) || undefined
    },
    skipGlobal404Message: true
  });
}

// ========== 监测策略管理 ==========

// 列出监测策略
export function getMonitoredStrategies(params = {}) {
  return request({
    url: '/api/v1/monitor/strategies',
    method: 'get',
    params: {
      status: params.status,
      source_type: params.source_type
    }
  });
}

// 新增监测策略
export function createMonitoredStrategy(data) {
  return request({
    url: '/api/v1/monitor/strategies',
    method: 'post',
    data
  });
}

// 从研究员策略创建监测策略
export function createFromResearcher(code) {
  return request({
    url: '/api/v1/monitor/strategies/from-researcher',
    method: 'post',
    data: { code }
  });
}

// 更新监测策略（改名/状态）
export function updateMonitoredStrategy(strategyId, data) {
  return request({
    url: `/api/v1/monitor/strategies/${strategyId}`,
    method: 'put',
    data
  });
}

// 归档监测策略
export function archiveMonitoredStrategy(strategyId) {
  return request({
    url: `/api/v1/monitor/strategies/${strategyId}`,
    method: 'delete'
  });
}

// 列出可用研究员策略
export function getResearcherStrategies() {
  return request({
    url: '/api/v1/monitor/researcher-strategies',
    method: 'get'
  });
}

// 列出可添加的监控策略（研究员 + 实盘发布）
export function getAddableStrategies() {
  return request({
    url: '/api/v1/monitor/addable-strategies',
    method: 'get'
  });
}

// 从实盘发布策略创建监控条目
export function createFromLive(data) {
  return request({
    url: '/api/v1/monitor/strategies/from-live',
    method: 'post',
    data
  });
}
