import request from '@/utils/request'

// 获取对话列表
export function getConversations(params) {
  return request({
    url: '/api/v1/agent/conversations',
    method: 'get',
    params
  })
}

// 获取对话详情（含消息历史，支持分页）
export function getConversation(id, params = {}) {
  return request({
    url: `/api/v1/agent/conversations/${id}`,
    method: 'get',
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      ...params
    }
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

// 按 token 查询确认记录状态（断连重开后重建卡片）
export function getConfirmation(token) {
  return request({
    url: `/api/v1/agent/confirmations/${token}`,
    method: 'get'
  })
}

// 查询会话的确认记录列表（时间倒序，供历史消息重建终态卡片）
export function getConversationConfirmations(conversationId, limit = 50) {
  return request({
    url: `/api/v1/agent/conversations/${conversationId}/confirmations`,
    method: 'get',
    params: { limit }
  })
}

// 提交确认决策：decision 为 confirmed（确认执行）或 rejected（取消）
export function submitConfirmationDecision(token, decision) {
  return request({
    url: `/api/v1/agent/confirmations/${token}/decision`,
    method: 'post',
    data: { decision }
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
