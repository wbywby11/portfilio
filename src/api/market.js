/**
 * 市场行情 API（行情同步、数据维护等）
 * 同步类接口使用 SSE 流式返回进度，避免长时间请求超时。
 */

const getMarketBase = () => {
  return process.env.VUE_APP_MARKET_API || process.env.VUE_APP_BASE_URL || 'http://127.0.0.1:8000';
};

/**
 * 解析 SSE 流：每行 data: {...} 解析为 JSON，通过 onMessage 回调推送；onDone 收到 { done: true, result?, error? } 后结束。
 * @param {Response} response - fetch 返回的 response
 * @param {function(object): void} onMessage - 收到每条进度/日志时调用
 * @param {function(object): void} onDone - 收到 done 时调用，参数为 { result?, error? }
 * @returns {Promise<void>}
 */
export function parseSSEStream(response, onMessage, onDone) {
  if (!response.ok) {
    onDone({ error: `请求失败: ${response.status} ${response.statusText}` });
    return Promise.resolve();
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  function processLine(line) {
    const t = line.trim();
    if (t.startsWith('data:')) {
      const jsonStr = t.slice(5).trim();
      if (!jsonStr) return;
      try {
        const data = JSON.parse(jsonStr);
        if (data.done) {
          onDone({ result: data.result, error: data.error });
          return;
        }
        onMessage(data);
      } catch (e) {
        // 忽略非 JSON 行
      }
    }
  }

  function pump() {
    return reader.read().then(({ value, done }) => {
      if (done) {
        buf.split('\n').forEach(processLine);
        return;
      }
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      lines.forEach(processLine);
      return pump();
    });
  }
  return pump();
}

/**
 * 同步当日行情（SSE 流），拉取并展示后端进度。
 * @param {function(object): void} onMessage - 每条进度/日志
 * @param {function(object): void} onDone - 结束 { result?, error? }
 * @returns {Promise<void>}
 */
export function syncTodayStream(onMessage, onDone) {
  const base = getMarketBase();
  const url = `${base.replace(/\/$/, '')}/api/v1/market/sync-today/stream`;
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include'
  })
    .then(res => {
      if (res.status === 404) {
        onDone({ error: '当前后端未提供同步行情接口，请使用「批量导入行情」上传 Excel 补充数据。' });
        return;
      }
      return parseSSEStream(res, onMessage, onDone);
    })
    .catch(err => {
      const msg = err.message || String(err);
      onDone({ error: msg.includes('Failed to fetch') || msg.includes('NetworkError')
        ? '无法连接后端，请确认后端服务已启动（如 8000 端口）且网络正常。'
        : msg });
    });
}

/**
 * 组合数据维护（SSE 流），按分组拉取个股等并展示进度。
 * @param {string} groupId - 分组 ID
 * @param {function(object): void} onMessage - 每条进度/日志
 * @param {function(object): void} onDone - 结束 { result?, error? }
 * @returns {Promise<void>}
 */
export function maintainStream(groupId, onMessage, onDone) {
  const base = getMarketBase();
  const url = `${base.replace(/\/$/, '')}/api/v1/market/portfolio/groups/${encodeURIComponent(groupId)}/maintain/stream`;
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include'
  })
    .then(res => parseSSEStream(res, onMessage, onDone))
    .catch(err => {
      const msg = err.message || String(err);
      onDone({ error: msg.includes('Failed to fetch') || msg.includes('NetworkError')
        ? '无法连接后端，请确认行情服务已启动且网络正常。'
        : msg });
    });
}
