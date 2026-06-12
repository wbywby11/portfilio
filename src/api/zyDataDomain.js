/**
 * ZY 数据域通用 CRUD API
 *
 * 设计：
 *   - 优先调用后端 /api/v1/zy-data/{collection} 系列接口
 *   - 当后端返回 404/网络错误时，自动切到本地 mock（localStorage）兜底
 *   - 单次切换：一旦某 collection 被判定 404，本会话内其他 collection 也走 mock
 *
 * 后端接口契约（建议后端实现）：
 *   GET    /api/v1/zy-data/collections                列出所有可访问 collection
 *   GET    /api/v1/zy-data/{collection}              列表（query: page, pageSize, filters_json）
 *   GET    /api/v1/zy-data/{collection}/count        计数
 *   POST   /api/v1/zy-data/{collection}              新增
 *   PUT    /api/v1/zy-data/{collection}/{id}         全量更新
 *   DELETE /api/v1/zy-data/{collection}/{id}         删除
 */
import request from '@/utils/request';
import mock from './zyDataDomain.mock';

const BASE = '/api/v1/zy-data';

// 一旦命中 404，记录到此 Set；后续同 collection 直接走 mock，避免反复 404
const fallbackCollections = new Set();
let globalFallback = false;

function shouldFallback(collection, err) {
  if (globalFallback) return true;
  if (fallbackCollections.has(collection)) return true;
  const status = err && err.response && err.response.status;
  if (status === 404 || status === 405 || status === 501) {
    fallbackCollections.add(collection);
    // 若 list 接口直接 404，认为后端尚未实现整套接口，全局切 mock
    globalFallback = true;
    // eslint-disable-next-line no-console
    console.warn('[zyDataDomain] backend %s not available (HTTP %s), fallback to local mock', collection, status);
    return true;
  }
  // 网络错误（无 response）也兜底
  if (!err.response && err.request) {
    globalFallback = true;
    // eslint-disable-next-line no-console
    console.warn('[zyDataDomain] backend unreachable, fallback to local mock');
    return true;
  }
  return false;
}

/** 是否处于 mock 兜底模式 */
export function isMockMode() {
  return globalFallback;
}

/** 强制切换到 mock 模式（用于"开发期"主动开启） */
export function enableMock() {
  globalFallback = true;
  mock.seedIfNeeded();
}

/** 重置 mock 数据 */
export function resetMockData() {
  mock.reseed();
}

/**
 * 列表查询
 * @param {string} collection 集合名（如 dwd_ast_info）
 * @param {object} params { page, pageSize, filters }
 */
export async function listRecords(collection, params = {}) {
  if (globalFallback || fallbackCollections.has(collection)) {
    mock.seedIfNeeded();
    return mock.list(collection, params);
  }
  try {
    const query = {
      page: params.page || 1,
      pageSize: params.pageSize || 20
    };
    if (params.filters && Object.keys(params.filters).length) {
      query.filters_json = JSON.stringify(params.filters);
    }
    const res = await request({
      url: `${BASE}/${encodeURIComponent(collection)}`,
      method: 'get',
      params: query,
      skipGlobal404Message: true
    });
    return res;
  } catch (err) {
    if (shouldFallback(collection, err)) {
      mock.seedIfNeeded();
      return mock.list(collection, params);
    }
    throw err;
  }
}

export async function createRecord(collection, payload) {
  if (globalFallback || fallbackCollections.has(collection)) {
    mock.seedIfNeeded();
    return mock.create(collection, payload);
  }
  try {
    return await request({
      url: `${BASE}/${encodeURIComponent(collection)}`,
      method: 'post',
      data: payload,
      skipGlobal404Message: true
    });
  } catch (err) {
    if (shouldFallback(collection, err)) {
      mock.seedIfNeeded();
      return mock.create(collection, payload);
    }
    throw err;
  }
}

export async function updateRecord(collection, id, payload) {
  if (globalFallback || fallbackCollections.has(collection)) {
    mock.seedIfNeeded();
    return mock.update(collection, id, payload);
  }
  try {
    return await request({
      url: `${BASE}/${encodeURIComponent(collection)}/${encodeURIComponent(id)}`,
      method: 'put',
      data: payload,
      skipGlobal404Message: true
    });
  } catch (err) {
    if (shouldFallback(collection, err)) {
      mock.seedIfNeeded();
      return mock.update(collection, id, payload);
    }
    throw err;
  }
}

export async function deleteRecord(collection, id) {
  if (globalFallback || fallbackCollections.has(collection)) {
    mock.seedIfNeeded();
    return mock.remove(collection, id);
  }
  try {
    return await request({
      url: `${BASE}/${encodeURIComponent(collection)}/${encodeURIComponent(id)}`,
      method: 'delete',
      skipGlobal404Message: true
    });
  } catch (err) {
    if (shouldFallback(collection, err)) {
      mock.seedIfNeeded();
      return mock.remove(collection, id);
    }
    throw err;
  }
}

export async function countRecords(collection) {
  if (globalFallback || fallbackCollections.has(collection)) {
    mock.seedIfNeeded();
    return mock.count(collection);
  }
  try {
    return await request({
      url: `${BASE}/${encodeURIComponent(collection)}/count`,
      method: 'get',
      skipGlobal404Message: true
    });
  } catch (err) {
    if (shouldFallback(collection, err)) {
      mock.seedIfNeeded();
      return mock.count(collection);
    }
    throw err;
  }
}

export default {
  listRecords,
  createRecord,
  updateRecord,
  deleteRecord,
  countRecords,
  isMockMode,
  enableMock,
  resetMockData
};
