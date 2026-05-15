/**
 * 解析 GET /api/v1/assets/prices/import/progress 的响应（axios 拦截器已返回 body，非 axios 实例）
 */
export function unwrapPriceImportProgressPayload(res) {
  if (!res || typeof res !== 'object') return null;
  const inner = res.data;
  if (!inner || typeof inner !== 'object') return null;
  if (
    Object.prototype.hasOwnProperty.call(inner, 'phase') ||
    Object.prototype.hasOwnProperty.call(inner, 'progress_id') ||
    Object.prototype.hasOwnProperty.call(inner, 'asset_code')
  ) {
    return inner;
  }
  if (inner.data && typeof inner.data === 'object') {
    const d = inner.data;
    if (
      Object.prototype.hasOwnProperty.call(d, 'phase') ||
      Object.prototype.hasOwnProperty.call(d, 'asset_code')
    ) {
      return d;
    }
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
    if (snap.message) return `${head}${metric} — ${snap.message}`;
    const wd = Number(snap.write_done) || 0;
    const wt = Number(snap.write_total) || 0;
    return `${head}写入${metric} ${wd}/${wt}（文件共 ${total} 行）`;
  }
  if (snap.message) return `${head}${metric} — ${snap.message}`;
  return `${head}准备${metric} ${prep}/${total || '?'}`;
}

/** 轮询间隔（毫秒）；过小会导致后端 access log 与负载偏高 */
export const PRICE_IMPORT_PROGRESS_POLL_MS = 1200;
