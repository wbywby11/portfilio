import request from '@/utils/request'

// 非流式对话
export function sendMessage(data) {
  return request({
    url: '/api/v1/agent/chat',
    method: 'post',
    data,
    timeout: 300000  // AI 对话可能较慢，5分钟超时
  })
}

// 获取对话列表
export function getConversations(params) {
  return request({
    url: '/api/v1/agent/conversations',
    method: 'get',
    params
  })
}

// 获取对话详情（含消息历史）
export function getConversation(id) {
  return request({
    url: `/api/v1/agent/conversations/${id}`,
    method: 'get'
  })
}

// 删除对话
export function deleteConversation(id) {
  return request({
    url: `/api/v1/agent/conversations/${id}`,
    method: 'delete'
  })
}

// 更新对话标题
export function updateConversationTitle(id, title) {
  return request({
    url: `/api/v1/agent/conversations/${id}/title`,
    method: 'put',
    data: { title }
  })
}

// 获取记忆列表
export function getMemories(params) {
  return request({
    url: '/api/v1/agent/memories',
    method: 'get',
    params
  })
}

// 删除指定记忆
export function deleteMemory(id) {
  return request({
    url: `/api/v1/agent/memories/${id}`,
    method: 'delete'
  })
}

// 搜索记忆
export function searchMemories(data) {
  return request({
    url: '/api/v1/agent/memories/search',
    method: 'post',
    data
  })
}

// 流式对话 - 使用原生 fetch 处理 SSE
// data.scene: 场景标识，null 时使用智能匹配
// options.signal: AbortSignal，切换对话时中止，避免回复串入其他会话
export function sendMessageStream(data, options = {}) {
  const baseUrl = process.env.VUE_APP_BASE_URL || 'http://127.0.0.1:8000'
  // 构建请求体，scene 为 null 时不传（后端走智能匹配）
  // 防御性保证 message 不为 null/undefined
  const payload = { ...data, message: data.message || '' }
  if (payload.scene === null || payload.scene === undefined) {
    delete payload.scene
  }
  const fetchOpts = {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${localStorage.getItem('token') || ''}`
    },
    body: JSON.stringify(payload)
  }
  if (options.signal) {
    fetchOpts.signal = options.signal
  }
  return fetch(`${baseUrl}/api/v1/agent/chat/stream`, fetchOpts)
    .then(response => {
      if (!response.ok) {
        return response.text().then(text => {
          throw new Error(text || `HTTP ${response.status}: ${response.statusText}`)
        })
      }
      if (!response.body) {
        throw new Error('流式响应体为空')
      }
      return response
    })
}

// 报告管理
export function getReports(params) {
  return request({ url: '/api/v1/agent/reports', method: 'get', params })
}

export function getReport(reportId) {
  return request({ url: `/api/v1/agent/reports/${reportId}`, method: 'get' })
}

export function deleteReport(reportId) {
  return request({ url: `/api/v1/agent/reports/${reportId}`, method: 'delete' })
}

export function exportReport(reportId) {
  return request({ url: `/api/v1/agent/reports/${reportId}/export`, method: 'get' })
}

// 分析模板管理
export function getAnalysisTemplates(params) {
  return request({ url: '/api/v1/agent/analysis-templates', method: 'get', params })
}

export function createAnalysisTemplate(data) {
  return request({ url: '/api/v1/agent/analysis-templates', method: 'post', data })
}

export function getAnalysisTemplate(templateId) {
  return request({ url: `/api/v1/agent/analysis-templates/${templateId}`, method: 'get' })
}

export function updateAnalysisTemplate(templateId, data) {
  return request({ url: `/api/v1/agent/analysis-templates/${templateId}`, method: 'put', data })
}

export function deleteAnalysisTemplate(templateId) {
  return request({ url: `/api/v1/agent/analysis-templates/${templateId}`, method: 'delete' })
}

export function executeAnalysisTemplate(templateId, params) {
  return request({ url: `/api/v1/agent/analysis-templates/${templateId}/execute`, method: 'post', data: { params } })
}

/** 上传对话附件 */
export function uploadAttachment(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request({
    url: '/api/v1/agent/upload-attachment',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000
  })
}
