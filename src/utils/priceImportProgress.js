/**
 * 解析 GET /api/v1/assets/prices/import/progress 的响应（axios 拦截器已返回 body，非 axios 实例）
 */
function _looksLikeProgressSnap(obj) {
  if (!obj || typeof obj !== 'object') return false;
  return (
    Object.prototype.hasOwnProperty.call(obj, 'phase') ||
    Object.prototype.hasOwnProperty.call(obj, 'progress_id') ||
    Object.prototype.hasOwnProperty.call(obj, 'asset_code') ||
    Object.prototype.hasOwnProperty.call(obj, 'write_done')
  );
}

export function unwrapPriceImportProgressPayload(res) {
  if (!res || typeof res !== 'object') return null;
  // 拦截器已解包为 { code, message, data }；少数路径可能直接传入 data
  if (_looksLikeProgressSnap(res)) {
    return res;
  }
  const inner = res.data;
  if (!inner || typeof inner !== 'object') return null;
  if (_looksLikeProgressSnap(inner)) {
    return inner;
  }
  if (inner.data && typeof inner.data === 'object' && _looksLikeProgressSnap(inner.data)) {
    return inner.data;
  }
  return null;
}

/** 与后端 touch_progress 字段一致，拼成一行展示 */
export function formatPriceImportProgressLine(snap) {
  if (!snap || typeof snap !== 'object') return '';
  const name = snap.asset_name || '';
  const code = snap.asset_code || '';
  const metric = snap.metric_label || '行情';
  const total = Number(snap.file_line_total) || 0;
  const prep = Number(snap.prepare_done) || 0;
  const phase = String(snap.phase || '');
  const head = name && code ? `【${name}（${code}）】` : `【${code || name}】`;
  if (phase === 'done') {
    return `${head}${metric} — ${snap.message || '导入完成'}`;
  }
  if (phase === 'write') {
    const wd = Number(snap.write_done) || 0;
    const wt = Number(snap.write_total) || 0;
    // 始终用 write_done / write_total 拼进度，避免 message 与数值不同步时界面卡在 0/n
    const base = `${head}${metric} — 写入数据库 ${wd}/${wt}（文件共 ${total} 行）`;
    const msg = snap.message && String(snap.message).trim();
    if (msg && !msg.includes('写入数据库')) {
      return `${head}${metric} — ${msg}；写入数据库 ${wd}/${wt}（文件共 ${total} 行）`;
    }
    return base;
  }
  if (snap.message) return `${head}${metric} — ${snap.message}`;
  return `${head}准备${metric} ${prep}/${total || '?'}`;
}

/** 轮询间隔（毫秒）；过小导致 access log / 服务端压力偏大；单次 bulk 加大后可降低频率 */
export const PRICE_IMPORT_PROGRESS_POLL_MS = 2000;
