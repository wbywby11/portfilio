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

// 运行回测
export function runBacktest(modelId, data) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/backtest`,
    method: 'post',
    data
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
