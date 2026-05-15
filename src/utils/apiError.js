/**
 * 从 axios 错误中提取后端可读文案。
 * FastAPI HTTPException: { detail: string | array }
 * 统一 Response 封装: { message: string }
 */
export function getApiErrorMessage(error) {
  if (!error) return '请求失败';
  const data = error.response && error.response.data;
  if (!data) return error.message || '请求失败';
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail) && data.detail.length) {
    const first = data.detail[0];
    if (first && typeof first.msg === 'string') return first.msg;
  }
  if (data.message) return data.message;
  return error.message || '请求失败';
}
