import request from '@/utils/request'

// 获取分类体系
export function getCategories() {
  return request({ url: '/api/v1/knowledge/categories', method: 'get' })
}

// 检索文档列表（分页）
export function getDocuments(params) {
  return request({ url: '/api/v1/knowledge/documents', method: 'get', params })
}

// 获取文档详情（含全文）
export function getDocument(id) {
  return request({ url: `/api/v1/knowledge/documents/${id}`, method: 'get' })
}

// 新增文档
export function createDocument(data) {
  return request({ url: '/api/v1/knowledge/documents', method: 'post', data })
}

// 更新文档
export function updateDocument(id, data) {
  return request({ url: `/api/v1/knowledge/documents/${id}`, method: 'put', data })
}

// 删除文档
export function deleteDocument(id) {
  return request({ url: `/api/v1/knowledge/documents/${id}`, method: 'delete' })
}

// 上传文件自动录入
export function uploadDocument(file, data = {}) {
  const formData = new FormData()
  formData.append('file', file)
  if (data.category) formData.append('category', data.category)
  if (data.tags) formData.append('tags', data.tags)
  if (data.related_assets) formData.append('related_assets', data.related_assets)
  return request({
    url: '/api/v1/knowledge/documents/upload',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000
  })
}

// 知识库统计
export function getKnowledgeStats() {
  return request({ url: '/api/v1/knowledge/stats', method: 'get' })
}
