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

// 上传策略PDF文档
export function uploadTemplatePdf(templateId, formData) {
  return request({
    url: `/api/v1/model-templates/${templateId}/upload-pdf`,
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  });
}

// 获取策略PDF文档URL
export function getTemplatePdfUrl(templateId) {
  return request({
    url: `/api/v1/model-templates/${templateId}/pdf-url`,
    method: 'get'
  });
}

// 删除策略PDF文档
export function deleteTemplatePdf(templateId) {
  return request({
    url: `/api/v1/model-templates/${templateId}/pdf`,
    method: 'delete'
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
// options 可携带 skipGlobal404Message：调用方已能降级（如监控实例 id 不是策略模型 id）时静默 404
export function getStrategyModel(modelId, options = {}) {
  return request({
    url: `/api/v1/strategy-models/${modelId}`,
    method: 'get',
    ...options
  });
}

// 获取策略原型预设列表（摘要，不含展开明细）
export function getStrategyPresets(templateCode) {
  return request({
    url: '/api/v1/strategy-models/presets',
    method: 'get',
    params: templateCode ? { template_code: templateCode } : {}
  });
}

// 展开预设：返回资产池 + 参数 + 三级问题清单
export function resolveStrategyPreset(presetCode) {
  return request({
    url: `/api/v1/strategy-models/presets/${presetCode}/resolve`,
    method: 'post'
  });
}

// 校验任意一组配置（未保存也能算），用于详情页/回测页实时门禁
export function validateStrategyConfig(data) {
  return request({
    url: '/api/v1/strategy-models/presets/validate',
    method: 'post',
    data
  });
}

// 运行回测（长任务，超时放到 30 分钟）
// progressKey：前端生成的进度任务号，同时作为轮询 GET /monitor/tasks/{task_id} 的 task_id；
// 为空时后端不建进度文档，行为与不传完全一致
export function runBacktest(modelId, data, progressKey) {
  return request({
    url: `/api/v1/backtests/run-by-model/${modelId}`,
    method: 'post',
    data,
    params: progressKey ? { progress_key: progressKey } : undefined,
    timeout: 1800000
  });
}

// 获取单条回测记录详情（含净值曲线/持仓/权重变化等完整明细）
export function getBacktestDetail(recordId) {
  return request({
    url: `/api/v1/backtests/${recordId}`,
    method: 'get'
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

// 权重上限由前端策略参数配置驱动，不再从后端硬编码获取
export function getMaxWeightsByCodes(thscodes) {
  return Promise.resolve({ data: { data: {} } });
}

// 发布模型（个别环境 Mongo/网络较慢，单独放宽超时）
export function publishModel(modelId) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/publish`,
    method: 'post',
    timeout: 120000
  });
}

// 取消发布（回到草稿；已实盘发布的模型会先自动取消实盘，历史记录保留）
export function unpublishModel(modelId, params = {}) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/unpublish`,
    method: 'post',
    params,
    timeout: 120000
  });
}

// 实盘发布（T+1 生效；后端为轻量写库，超时多为 API 地址/后端未就绪，仍放宽以避免偶发慢查询）
export function livePublishModel(modelId, data = {}) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/live-publish`,
    method: 'post',
    data,
    timeout: 180000
  });
}

// 取消实盘发布
export function liveUnpublishModel(modelId, params = {}) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/live-unpublish`,
    method: 'post',
    params,
    timeout: 120000
  });
}

// 获取实盘配置（含策略参数建议值）
export function getLiveConfig(modelId) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/live-config`,
    method: 'get'
  });
}

// 更新实盘配置
export function updateLiveConfig(modelId, data) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/live-config`,
    method: 'patch',
    data
  });
}

// 获取实盘发布策略列表
export function getLivePublishedModelList(params) {
  return request({
    url: '/api/v1/strategy-models/live/published',
    method: 'get',
    params
  });
}

/** 日常监控准入：已实盘发布 + vol_scaled_budget + 混合动量 */
export function getLiveEligibleForMonitor(params) {
  return request({
    url: '/api/v1/strategy-models/live/eligible-for-monitor',
    method: 'get',
    params
  });
}

// 手动调仓确认/跳过
export function confirmManualRebalance(modelId, data) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/manual-rebalance`,
    method: 'post',
    data
  });
}

// 实盘变更日志
export function getLiveChangeLogs(modelId, params) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/live-change-logs`,
    method: 'get',
    params
  });
}

// 删除策略模型
export function deleteStrategyModel(modelId) {
  return request({
    url: `/api/v1/strategy-models/${modelId}`,
    method: 'delete'
  });
}

// 更新策略模型（可传 axios 附加配置，如 params: { source: 'live_monitoring' }）
export function updateStrategyModel(modelId, data, axiosConfig = {}) {
  return request({
    url: `/api/v1/strategy-models/${modelId}`,
    method: 'put',
    data,
    ...axiosConfig
  });
}


// ==================== 多维回测分析 ====================

// 参数敏感度分析（第5层策略验证增强）
export function runSensitivityAnalysis(data) {
  return request({
    url: '/api/v1/backtests/sensitivity',
    method: 'post',
    data,
    timeout: 300000  // 5分钟超时（多次回测耗时）
  });
}

// 情景推演
export function runScenarioAnalysis(data) {
  return request({
    url: '/api/v1/backtests/scenario',
    method: 'post',
    data,
    timeout: 180000
  });
}

// 鲁棒性检验（滑动子区间回测）
export function runRobustnessCheck(data) {
  return request({
    url: '/api/v1/backtests/robustness',
    method: 'post',
    data,
    timeout: 300000
  });
}

// 组合评估报告（Phase 3: 组合评估能力补全）
export function generatePortfolioReport(data) {
  return request({
    url: '/api/v1/backtests/portfolio-report',
    method: 'post',
    data,
    timeout: 120000
  });
}

// 获取策略参数版本列表
export function getParamVersions(modelId, { skip = 0, limit = 50 } = {}) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/param-versions`,
    method: 'get',
    params: { skip, limit }
  });
}

// 获取单个参数版本详情
export function getParamVersion(modelId, versionId) {
  return request({
    url: `/api/v1/strategy-models/${modelId}/param-versions/${versionId}`,
    method: 'get'
  });
}
