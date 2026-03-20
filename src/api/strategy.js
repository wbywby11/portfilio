import request from '@/utils/request';

/**
 * 策略模型相关API
 */

// 获取模型模板列表
export function getTemplateList() {
  return request({
    url: '/api/v1/model-templates/',
    method: 'get'
  });
}

// 获取单个模板
export function getTemplate(code) {
  return request({
    url: `/api/v1/model-templates/${code}`,
    method: 'get'
  });
}

// 创建模型模板
export function createTemplate(data) {
  return request({
    url: '/api/v1/model-templates/',
    method: 'post',
    data
  });
}

// 更新模型模板
export function updateTemplate(templateId, data) {
  return request({
    url: `/api/v1/model-templates/${templateId}`,
    method: 'put',
    data
  });
}

// 验证模板有效性
export function validateTemplate(data) {
  return request({
    url: '/api/v1/model-templates/validate',
    method: 'post',
    data
  });
}

// 创建策略模型
export function createStrategyModel(data) {
  return request({
    url: '/api/v1/strategy-models/',
    method: 'post',
    data
  });
}

// 获取策略模型列表
export function getStrategyModelList(params) {
  // 过滤掉空值参数，避免后端参数验证失败
  const filteredParams = {};
  if (params) {
    Object.keys(params).forEach(key => {
      if (params[key] !== '' && params[key] !== null && params[key] !== undefined) {
        filteredParams[key] = params[key];
      }
    });
  }
  return request({
    url: '/api/v1/strategy-models/',
    method: 'get',
    params: filteredParams
  });
}

// 获取单个策略模型
export function getStrategyModel(modelId) {
  return request({
    url: `/api/v1/strategy-models/${modelId}`,
    method: 'get'
  });
}

// 运行回测（混合动量等计算量大，超时设为 5 分钟）
export function runBacktest(modelId, data) {
  return request({
    url: `/api/v1/backtests/run-by-model/${modelId}`,
    method: 'post',
    data,
    timeout: 300000
  });
}

// 更新回测记录备注
export function updateBacktestRemark(modelId, recordId, remark) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/backtests/${recordId}`,
    method: 'patch',
    data: { remark: remark || '' }
  });
}

// 基于快照切片计算绩效指标（多策略步进对比时用，保证与净值曲线数据源一致）
export function computeMetricsFromSnapshots(snapshots, cutoffDate) {
  return request({
    url: '/api/v1/backtests/compute-metrics-from-snapshots',
    method: 'post',
    data: {
      snapshots: Array.isArray(snapshots) ? snapshots : [],
      cutoff_date: String(cutoffDate || '').replace(/-/g, '').slice(0, 8)
    }
  });
}

// 按指数编制规则获取资产权重上限（供权重初始化、预设调仓、步进输入限制与提示）
export function getMaxWeightsByCodes(thscodes) {
  const codes = Array.isArray(thscodes) ? thscodes.join(',') : (thscodes || '');
  if (!codes) return Promise.resolve({ data: { data: {} } });
  return request({
    url: '/api/v1/backtests/max-weights',
    method: 'get',
    params: { thscodes: codes }
  });
}

// 发布模型
export function publishModel(modelId) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/publish`,
    method: 'post'
  });
}

// 删除策略模型
export function deleteStrategyModel(modelId) {
  return request({
    url: `/api/v1/strategy-models/${modelId}`,
    method: 'delete'
  });
}

// 更新策略模型
export function updateStrategyModel(modelId, data) {
  return request({
    url: `/api/v1/strategy-models/${modelId}`,
    method: 'put',
    data
  });
}

// 计算策略（算法优化计算）
export function calculateStrategy(data) {
  return request({
    url: '/api/v1/algorithms/calculate',
    method: 'post',
    data
  });
}

// 业绩基准相关API

// 获取业绩基准列表
export function getBenchmarkList() {
  return request({
    url: '/api/v1/benchmarks/',
    method: 'get'
  });
}

// 获取单个业绩基准
export function getBenchmark(benchmarkId) {
  return request({
    url: `/api/v1/benchmarks/${benchmarkId}`,
    method: 'get'
  });
}

// 根据代码获取业绩基准
export function getBenchmarkByCode(code) {
  return request({
    url: `/api/v1/benchmarks/by-code/${code}`,
    method: 'get'
  });
}

// 创建业绩基准
export function createBenchmark(data) {
  return request({
    url: '/api/v1/benchmarks/',
    method: 'post',
    data
  });
}

// 更新业绩基准
export function updateBenchmark(benchmarkId, data) {
  return request({
    url: `/api/v1/benchmarks/${benchmarkId}`,
    method: 'put',
    data
  });
}

// 删除业绩基准
export function deleteBenchmark(benchmarkId) {
  return request({
    url: `/api/v1/benchmarks/${benchmarkId}`,
    method: 'delete'
  });
}
