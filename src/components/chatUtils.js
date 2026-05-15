import { marked } from 'marked'
import DOMPurify from 'dompurify'

// 配置 marked — 启用 GFM 和换行
marked.setOptions({
  breaks: true,
  gfm: true
})

/** 列分隔：制表符、全角空格、或 2 个及以上半角空格（与模型「手敲对齐」表格常见格式一致） */
const ASCII_TABLE_COL_SEP = /[\t\u3000]+|\s{2,}/

/**
 * 判断是否不应参与「空格对齐表格」识别的行
 */
function isAsciiTableBoundaryLine(line) {
  const t = line.trim()
  if (!t) return true
  if (/^#{1,6}\s/.test(t)) return true
  if (/^[-*]\s+/.test(t)) return true
  if (/^\d+\.\s+/.test(t)) return true
  if (/^\d+[、）)]\s*/.test(t)) return true
  if (/^>\s/.test(t)) return true
  if (/^<\/?[a-z]/i.test(t)) return true
  if (/^\|.*\|\s*$/.test(t)) return true
  if (t.startsWith('```')) return true
  return false
}

/**
 * 将连续多行、用多空格/制表符分列的块转为 GFM Markdown 表格（供 marked 渲染）
 */
function tryConvertAsciiTableBlock(lines) {
  if (lines.length < 2) return null
  const rows = lines.map((l) => l.trim().split(ASCII_TABLE_COL_SEP).map((c) => c.trim()))
  const lens = rows.map((r) => r.length)
  const maxC = Math.max(...lens)
  const minC = Math.min(...lens)
  if (maxC < 3) return null
  if (maxC - minC > 1) return null
  const norm = rows.map((r) => {
    const x = [...r]
    while (x.length < maxC) x.push('')
    return x.slice(0, maxC)
  })
  const esc = (s) => String(s).replace(/\|/g, '\\|')
  const head = '| ' + norm[0].map(esc).join(' | ') + ' |'
  const sep = '| ' + Array(maxC).fill('---').join(' | ') + ' |'
  const body = norm
    .slice(1)
    .map((r) => '| ' + r.map(esc).join(' | ') + ' |')
    .join('\n')
  return [head, sep, body].filter(Boolean).join('\n')
}

/**
 * 扫描全文，把空格/制表符对齐的表格块替换为 GFM pipe 表格
 */
function preprocessAlignedTextTables(text) {
  if (!text || !text.includes('\n')) return text
  const lines = text.split('\n')
  const out = []
  let inFence = false
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const trim = line.trim()
    if (trim.startsWith('```')) {
      inFence = !inFence
      out.push(line)
      i += 1
      continue
    }
    if (inFence) {
      out.push(line)
      i += 1
      continue
    }
    if (isAsciiTableBoundaryLine(line)) {
      out.push(line)
      i += 1
      continue
    }
    const rawFirst = line.trim().split(ASCII_TABLE_COL_SEP).map((c) => c.trim())
    if (rawFirst.length < 3) {
      out.push(line)
      i += 1
      continue
    }
    let j = i
    const group = []
    while (j < lines.length) {
      const L = lines[j]
      if (!L.trim()) break
      if (isAsciiTableBoundaryLine(L)) break
      const raw = L.trim().split(ASCII_TABLE_COL_SEP).map((c) => c.trim())
      if (raw.length < 3) break
      group.push(L)
      j += 1
    }
    const md = tryConvertAsciiTableBlock(group)
    if (md) {
      out.push(md)
      i = j
    } else {
      out.push(lines[i])
      i += 1
    }
  }
  return out.join('\n')
}

/**
 * 使用 DOMPurify 对 marked 输出做 XSS 消毒
 * 只允许安全的 HTML 标签和属性
 * @param {string} html 原始 HTML
 * @returns {string} 消毒后的 HTML
 */
export function sanitizeHtml(html) {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      'h1','h2','h3','h4','h5','h6','p','br','hr',
      'ul','ol','li','blockquote','pre','code',
      'table','thead','tbody','tr','th','td',
      'strong','em','del','a','img','span','div','sub','sup'
    ],
    ALLOWED_ATTR: ['href','src','alt','title','class','target','rel'],
    ALLOW_DATA_ATTR: false
  })
}

/**
 * 节流函数 —— 限制 scrollToBottom 等高频操作
 * @param {Function} fn 目标函数
 * @param {number} delay 最小间隔毫秒
 * @returns {Function} 节流后的函数
 */
export function throttle(fn, delay) {
  let last = 0
  let timer = null
  return function (...args) {
    const now = Date.now()
    const remaining = delay - (now - last)
    if (remaining <= 0) {
      if (timer) { clearTimeout(timer); timer = null }
      last = now
      fn.apply(this, args)
    } else if (!timer) {
      timer = setTimeout(() => {
        last = Date.now()
        timer = null
        fn.apply(this, args)
      }, remaining)
    }
  }
}

/**
 * 将 Markdown 文本渲染为安全 HTML
 * @param {string} text Markdown 源文本
 * @returns {string} 消毒后的 HTML
 */
export function renderMarkdown(text) {
  if (!text) return ''
  try {
    const pre = preprocessAlignedTextTables(text)
    const html = marked.parse(pre)
    const sanitized = sanitizeHtml(html)
    // 给所有 table 标签添加 md-table class，确保全局样式能命中
    return sanitized.replace(/<table>/g, '<table class="md-table">')
  } catch {
    return text
  }
}

/**
 * 解析 tool result，支持字符串和对象
 * @param {Object} tool 工具调用对象
 * @returns {Object|null} 解析后的结果
 */
export function parseToolResult(tool) {
  if (!tool || tool.result === undefined || tool.result === null) return null
  let result = tool.result
  if (typeof result === 'string') {
    try { result = JSON.parse(result) } catch { return null }
  }
  return result
}

/**
 * 从消息的 tool_calls 中提取所有 charts（按标题+类型去重）
 * @param {Object} msg 消息对象
 * @returns {Array} 图表数据数组
 */
export function getMessageCharts(msg) {
  if (!msg.tool_calls || !msg.tool_calls.length) return []
  let allCharts = []
  for (const tool of msg.tool_calls) {
    const result = parseToolResult(tool)
    if (result && Array.isArray(result.charts) && result.charts.length > 0) {
      allCharts = allCharts.concat(result.charts)
    }
  }
  // 按标题+图表类型去重，避免同名图表重复渲染
  if (allCharts.length > 1) {
    const seen = new Set()
    allCharts = allCharts.filter(chart => {
      const key = (chart.title || '') + '::' + (chart.chart_type || '')
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }
  if (allCharts.length > 0) {
    console.log('[Charts] getMessageCharts: 找到', allCharts.length, '个图表(已去重), tool_calls 数:', msg.tool_calls.length)
  }
  return allCharts
}

/**
 * 从消息的 tool_calls 中提取所有表格数据
 * @param {Object} msg 消息对象
 * @returns {Array<{records, summary, recordCount, dataShape, toolName}>}
 */
export function getMessageDataTables(msg) {
  if (!msg.tool_calls || !msg.tool_calls.length) return []

  const tables = []
  const toolNames = msg.tool_calls.map(t => t.name).filter(Boolean)
  // 检查是否有分析类工具（表示存在多步骤工作流）
  const hasAnalysisTool = toolNames.some(n =>
    ['data_analyze', 'data_transform', 'data_visualize'].includes(n)
  )
  // data_query 是否为唯一工具类型
  const onlyDataQuery = toolNames.length > 0 && toolNames.every(n => n === 'data_query')

  for (const tool of msg.tool_calls) {
    // data_query 表格仅在它是唯一工具且所有调用都完成时才展示
    if (tool.name === 'data_query') {
      if (!onlyDataQuery) continue  // 有其他工具 → 跳过 data_query 表格
      // 检查是否所有工具都已完成（防止流式中间状态闪现）
      const allDone = msg.tool_calls.every(
        t => t.status === 'done' || t.status === 'success' || t.status === 'error'
      )
      if (!allDone) continue  // 还在流式中 → 暂不展示
    }

    const result = parseToolResult(tool)
    if (result && result.data && Array.isArray(result.data.records) && result.data.records.length > 0) {
      tables.push({
        records: result.data.records,
        summary: result.summary || '',
        recordCount: result.metadata?.record_count || result.data.records.length,
        dataShape: result.metadata?.data_shape || 'table',
        toolName: tool.name
      })
    }
  }
  return tables
}
