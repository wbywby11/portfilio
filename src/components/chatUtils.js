import { marked } from 'marked'
import DOMPurify from 'dompurify'

// 配置 marked — 启用 GFM 和换行
marked.setOptions({
  breaks: true,
  gfm: true
})

/**
 * 表名 → 中文显示名映射（仅收录数据库真实存在的集合）
 * 新增真实表时在此补充；enhanceRenderedHtml 对未收录表名会优雅降级为普通 <code>。
 */
export const TABLE_DISPLAY_NAMES = {
  // ─── data_hub 通用数据接入域 ───
  'subject_risk_records': '主体观点风险记录表',
  'subject_risk_import_batches': '主体风险导入批次表',
  // ─── 资产行情域 ───
  'assets': '资产列表主数据',
  'asset_prices': '资产日频K线行情',
}

/**
 * 关键字段信息映射：字段名 → { zh: 中文名, role: 角色, roleClass: CSS类 }
 * role: PK=主键, FK=外键, LINK=关联键, BIZ=业务关键字段
 */
export const KEY_FIELD_INFO = {
  // ─── 资产行情域（assets / asset_prices 真实字段）───
  'asset_code':   { zh: '证券代码',        role: 'PK',   roleClass: 'field-pk' },
  'asset_name':   { zh: '证券名称',        role: 'LINK', roleClass: 'field-link' },
  'asset_type':   { zh: '资产大类',        role: 'BIZ',  roleClass: 'field-biz' },
  'date':         { zh: '交易日期',        role: 'PK',   roleClass: 'field-pk' },
  'open':         { zh: '开盘价',          role: 'BIZ',  roleClass: 'field-biz' },
  'high':         { zh: '最高价',          role: 'BIZ',  roleClass: 'field-biz' },
  'low':          { zh: '最低价',          role: 'BIZ',  roleClass: 'field-biz' },
  'close':        { zh: '收盘价',          role: 'BIZ',  roleClass: 'field-biz' },
  'volume':       { zh: '成交量',          role: 'BIZ',  roleClass: 'field-biz' },
  'amount':       { zh: '成交额',          role: 'BIZ',  roleClass: 'field-biz' },
  // ─── data_hub 通用数据接入域（真实字段）───
  'subject_name': { zh: '主体名称',        role: 'LINK', roleClass: 'field-link' },
  'risk_signal_level': { zh: '风险信号等级', role: 'BIZ', roleClass: 'field-biz' },
  'biz_date':     { zh: '业务日期',        role: 'BIZ',  roleClass: 'field-biz' },
  'risk_id':      { zh: '风险事件ID',      role: 'PK',   roleClass: 'field-pk' },
  'rule_large':   { zh: '规则大类',        role: 'BIZ',  roleClass: 'field-biz' },
  'rule_medium':  { zh: '规则中类',        role: 'BIZ',  roleClass: 'field-biz' },
  'rule_small':   { zh: '规则小类',        role: 'BIZ',  roleClass: 'field-biz' },
  'enterprise_nature': { zh: '企业性质',   role: 'BIZ',  roleClass: 'field-biz' },
  'industry_classification_gb': { zh: '国标行业分类', role: 'BIZ', roleClass: 'field-biz' },
  'affiliated_province': { zh: '所属省份',  role: 'BIZ',  roleClass: 'field-biz' },
}

/**
 * HTML 后处理：为表名引用、关键字段、数据来源头、关联路径添加样式和 tooltip。
 * 在 marked + DOMPurify 之后调用。
 */
function enhanceRenderedHtml(html) {
  if (!html) return html

  // 1. 表名中文引用： <code>中文名(table_name)</code> → 徽章样式
  html = html.replace(/<code>([^<]*?)\(([a-z][a-z0-9_]+)\)<\/code>/g, (match, zhPart, tableName) => {
    if (TABLE_DISPLAY_NAMES[tableName]) {
      return '<code class="table-ref-badge" title="' + tableName + '">' + zhPart.trim() + '<span class="tbl-en">(' + tableName + ')</span></code>'
    }
    return match
  })

  // 2. 裸表名： <code>subject_risk_records</code> 等已知表名 → 徽章
  html = html.replace(/<code>([a-z][a-z0-9_]{4,})<\/code>/g, (match, name) => {
    if (TABLE_DISPLAY_NAMES[name]) {
      return '<code class="table-ref-badge" title="' + name + '">' + TABLE_DISPLAY_NAMES[name] + '<span class="tbl-en">(' + name + ')</span></code>'
    }
    return match
  })

  // 3. 关键字段高亮：对未被 table-ref-badge 处理的 <code> 和 <strong> 内容检测
  const fieldNames = Object.keys(KEY_FIELD_INFO)
  for (const field of fieldNames) {
    const info = KEY_FIELD_INFO[field]
    // <code>FIELD</code>（排除已有 table-ref-badge 的）
    const codeRe = new RegExp('<code(?![^>]*table-ref-badge)[^>]*>' + field.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '</code>', 'g')
    html = html.replace(codeRe,
      '<code class="key-field ' + info.roleClass + '" title="' + info.zh + ' [' + info.role + ']">' + field + '</code>')
    // <strong>FIELD</strong>（排除已有 key-field 类的）
    const strongRe = new RegExp('<strong(?![^>]*key-field)[^>]*>' + field.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '</strong>', 'g')
    html = html.replace(strongRe,
      '<strong class="key-field ' + info.roleClass + '" title="' + info.zh + ' [' + info.role + ']">' + field + '</strong>')
  }

  // 4. 数据来源头：【数据来源】... 行 → 语义化 div
  html = html.replace(/(?:<p>)?(【数据来源】[^<\n]*)(?:<\/p>)?/g,
    '<div class="data-source-header"><i class="src-icon">&#128202;</i>$1</div>')

  // 5. 激活视图头：【激活视图】... 行
  html = html.replace(/(?:<p>)?(【激活视图】[^<\n]*)(?:<\/p>)?/g,
    '<div class="active-view-header"><i class="view-icon">&#128065;</i>$1</div>')

  // 6. 关联路径增强：xxx.AAA → yyy.BBB 格式（在 <code> 内）
  html = html.replace(/<code class="table-ref-badge"[^>]*>[^<]*<span[^>]*>\(([a-z][a-z0-9_]+)\)<\/span><\/code>\s*[\.→]\s*<code[^>]*>([^<]+)<\/code>/g,
    (match, tbl, field) => {
      const info = KEY_FIELD_INFO[field]
      const zh = info ? info.zh : field
      return match + '<span class="join-arrow" title="' + TABLE_DISPLAY_NAMES[tbl] + '.' + zh + '">→</span>'
    })

  return html
}

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
 * 客户端防御过滤：移除 LLM 输出中泄露的工具调用标签和裸 JSON。
 * 覆盖 DSML（全角/ASCII竖线）、<tool_call>...</tool_call> 块、
 * 裸 JSON {"name":...,"arguments":...} 以及孤立标签。
 * @param {string} text 原始文本
 * @returns {string} 过滤后的文本
 */
const _DSML_TAG_RE = /<[/]?\s*[\uff5c|]+\s*DSML\s*[\uff5c|]+\s*\w*\s*>/gi
const _TOOL_CALL_BLOCK_RE = /\s*<\s*tool_call\s*>[\s\S]*?<\s*\/\s*tool_call\s*>\s*/gi
const _BARE_JSON_TOOL_RE = /\s*\{\s*"name"\s*:\s*"\w+"\s*,\s*"arguments"\s*:\s*\{[\s\S]*?\}\s*\}\s*/g
const _ORPHAN_TAGS = [
  /<\s*[/]?\s*tool_calls?\s*>/gi,
  /<\s*[/]?\s*function_calls\s*>/gi,
  /<\s*[/]?\s*invoke\s[^>]*>/gi,
  /<\s*[/]?\s*parameter\s[^>]*>/gi,
  /<\s*[/]?\s*task\s*>/gi,
  /<[/]?\s*[\uff5c|]\s*/g,
  /<\s*[/]?\s*(?:tasktool_call|task_function_calls)\s*>/gi,
]

export function stripToolCallLeaks(text) {
  if (!text) return text
  let c = text
  c = c.replace(_TOOL_CALL_BLOCK_RE, '')
  c = c.replace(_DSML_TAG_RE, '')
  c = c.replace(_BARE_JSON_TOOL_RE, '')
  for (const re of _ORPHAN_TAGS) {
    c = c.replace(re, '')
  }
  // 清理多余空行
  c = c.replace(/\n{3,}/g, '\n\n').trim()
  return c
}

/**
 * 将 ```echarts 围栏内的 ECharts option JSON 转为图表渲染契约对象。
 * 限 line/bar/pie 三类；非法/未知类型降级为 null（由调用方退回代码块展示）。
 * @param {Object} option 解析后的 ECharts option
 * @returns {{title:string, chart_type:string, echarts_option:Object}|null}
 */
export function buildEchartsChartEntry(option) {
  if (!option || typeof option !== 'object') return null
  const series = Array.isArray(option.series) ? option.series : (option.series ? [option.series] : [])
  const chartType = (series[0] && series[0].type) || ''
  if (!['line', 'bar', 'pie'].includes(chartType)) return null
  let title = ''
  if (option.title) {
    const t = Array.isArray(option.title) ? option.title[0] : option.title
    title = (t && t.text) || ''
  }
  return { title, chart_type: chartType, echarts_option: option }
}

/**
 * 将 Markdown 文本按顺序拆成可渲染片段：html | table | chart。
 * - html: 非表格内容走 marked + DOMPurify，由 v-html 输出
 * - table: 表格转为 { headers, records }，由 ChatDataTable 组件渲染，
 *   以获得查询/排序/导出能力。
 * - chart: ```echarts 围栏且 JSON 合法时转为图表片段，由 ChatChartRenderer 渲染；
 *   JSON 非法时降级为普通代码块（纯文本展示，不崩溃）。
 * @param {string} text 原始 Markdown 文本
 * @param {Object} [metadata] 可选元数据（含 traceable_assets 等）
 * @returns {Array<{type:'html',content:string}|{type:'table',headers:string[],records:object[],traceableAssets?:Array}|{type:'chart',chart:Object}>}
 */
export function parseMessageSegments(text, metadata) {
  if (!text) return []
  // 客户端防御：过滤可能泄露的工具调用标签文本
  const safeText = stripToolCallLeaks(text)
  if (!safeText) return []
  const pre = preprocessAlignedTextTables(safeText)
  let tokens
  try {
    tokens = marked.lexer(pre)
  } catch {
    return [{ type: 'html', content: renderMarkdown(text) }]
  }
  const links = tokens.links || {}
  const segments = []
  let buffer = []

  // 提取可追踪资产列表
  const traceableAssets = (metadata && Array.isArray(metadata.traceable_assets))
    ? metadata.traceable_assets
    : []

  const flushBuffer = () => {
    if (!buffer.length) return
    try {
      // marked.parser 需要 tokens.links 才能正确渲染参考式链接
      buffer.links = links
      const html = marked.parser(buffer)
      const sanitized = sanitizeHtml(html)
      const enhanced = enhanceRenderedHtml(sanitized)
      segments.push({ type: 'html', content: enhanced })
    } catch {
      // 降级：原样输出
      segments.push({ type: 'html', content: '' })
    }
    buffer = []
  }

  for (const tok of tokens) {
    if (tok && tok.type === 'code' && (tok.lang || '').toLowerCase() === 'echarts') {
      // echarts 围栏：JSON 校验通过转图表片段，失败降级为普通代码块
      let chartEntry = null
      try {
        chartEntry = buildEchartsChartEntry(JSON.parse(tok.text))
      } catch {
        chartEntry = null
      }
      if (chartEntry) {
        flushBuffer()
        segments.push({ type: 'chart', chart: chartEntry })
      } else {
        buffer.push(tok)
      }
      continue
    }
    if (tok && tok.type === 'table') {
      flushBuffer()
      const headerCells = Array.isArray(tok.header) ? tok.header : []
      const headers = headerCells.map((h, i) => {
        const t = (h && (h.text != null ? h.text : h)) || ''
        const s = String(t).trim()
        return s || `列${i + 1}`
      })
      const rawRows = Array.isArray(tok.rows) ? tok.rows : []
      const records = rawRows.map(row => {
        const obj = {}
        headers.forEach((h, i) => {
          const cell = row && row[i]
          const v = cell && (cell.text != null ? cell.text : cell)
          obj[h] = v == null ? '' : String(v)
        })
        return Object.freeze(obj)
      })
      const tableSegment = { type: 'table', headers, records }
      // 稳定 key：基于表头生成 segId，流式表格生长过程中表头不变，
      // 避免父组件重渲染时 v-for sIdx 漂移导致 ChatDataTable 被重建
      tableSegment.segId = headers.join('|') || ('tbl_' + segments.length)
      if (traceableAssets.length) {
        tableSegment.traceableAssets = traceableAssets
      }
      segments.push(tableSegment)
    } else {
      buffer.push(tok)
    }
  }
  flushBuffer()
  return segments
}

/**
 * 将 Markdown 文本渲染为安全 HTML，并为所有表格预先包装导出按钮。
 * 表格按钮随 HTML 一起输出，避免 v-html 重渲染时出现按钮闪烁、跳动。
 * 点击在 AgentChatPanel 层面以事件委托方式统一响应。
 * @param {string} text Markdown 源文本
 * @returns {string} 消毒后的 HTML
 */
export function renderMarkdown(text) {
  if (!text) return ''
  try {
    const safeText = stripToolCallLeaks(text)
    if (!safeText) return ''
    const pre = preprocessAlignedTextTables(safeText)
    const html = marked.parse(pre)
    const sanitized = sanitizeHtml(html)
    // 增强：表名中文徽章、关键字段高亮、数据来源头
    const enhanced = enhanceRenderedHtml(sanitized)
    // 1. 为 <table> 加 .md-table 类名；2. 包装 wrapper 与导出按钮
    return enhanced
      .replace(
        /<table>/g,
        '<div class="table-wrapper"><div class="table-actions">'
          + '<button type="button" class="table-export-btn">'
          + '<i class="el-icon-download"></i> 导出'
          + '</button></div><table class="md-table">'
      )
      .replace(/<\/table>/g, '</table></div>')
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
 * 从 result.data 中提取数据数组，支持多种常见字段名
 * @param {Object} data result.data 对象
 * @returns {Array|null} 数据数组，若无匹配则返回 null
 */
function extractDataArray(data) {
  if (!data) return null
  const arr = data.records || data.prices || data.items || data.rows
  return Array.isArray(arr) && arr.length > 0 ? arr : null
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

  // 回测相关工具名集合（用于推断 traceable_backtests）
  const BACKTEST_TOOLS = ['execute_backtest', 'compare_strategies', 'recommend_strategy', 'run_backtest', 'query_backtests']

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
    if (result && result.data) {
      const dataArray = extractDataArray(result.data)
      if (dataArray) {
        // 提取可追踪资产元数据
        const traceableAssets = (result.traceable_assets && Array.isArray(result.traceable_assets))
          ? result.traceable_assets
          : (result.data?.traceable_assets && Array.isArray(result.data.traceable_assets))
            ? result.data.traceable_assets
            : (result.metadata?.traceable_assets && Array.isArray(result.metadata.traceable_assets))
              ? result.metadata.traceable_assets
              : []
        const tableEntry = {
          // 冻结各行数据，避免 Vue 深层响应式追踪（表格数据只读展示）
          records: dataArray.map(r => (r && typeof r === 'object' && !Object.isFrozen(r)) ? Object.freeze(r) : r),
          summary: result.summary || '',
          recordCount: result.metadata?.record_count || dataArray.length,
          dataShape: result.metadata?.data_shape || 'table',
          toolName: tool.name
        }
        if (traceableAssets.length) {
          tableEntry.traceableAssets = traceableAssets
        }
        // 提取可追踪回测记录元数据
        let traceableBacktests = (result.traceable_backtests && Array.isArray(result.traceable_backtests))
          ? result.traceable_backtests
          : (result.data?.traceable_backtests && Array.isArray(result.data.traceable_backtests))
            ? result.data.traceable_backtests
            : (result.metadata?.traceable_backtests && Array.isArray(result.metadata.traceable_backtests))
              ? result.metadata.traceable_backtests
              : []
        // 若无显式数据，从回测工具结果中推断
        if (!traceableBacktests.length && BACKTEST_TOOLS.includes(tool.name)) {
          traceableBacktests = inferBacktestsFromResult(result)
        }
        if (traceableBacktests.length) {
          tableEntry.traceableBacktests = traceableBacktests
        }
        tables.push(tableEntry)
      }
    }
  }

  // 按 toolName + summary + recordCount + 首末行特征去重，
  // 避免同轮多次 tool_call 返回同一份表（同名 data_query 重复调用 /
  // 流式中间态最终被回填为独立条目等）导致 UI 重复渲染多个数据表格
  if (tables.length > 1) {
    const seen = new Set()
    const dedup = []
    for (const t of tables) {
      const recs = t.records || []
      const first = recs.length ? JSON.stringify(recs[0]) : ''
      const last = recs.length ? JSON.stringify(recs[recs.length - 1]) : ''
      const key = (t.toolName || '') + '::' + (t.summary || '') + '::' + (t.recordCount || 0) + '::' + first + '::' + last
      if (seen.has(key)) continue
      seen.add(key)
      dedup.push(t)
    }
    if (dedup.length !== tables.length) {
      // eslint-disable-next-line no-console
      console.log('[Tables] getMessageDataTables: 去重', tables.length, '->', dedup.length)
    }
    return dedup
  }
  return tables
}

/**
 * 从回测工具返回结果中推断 traceable_backtests
 * 支持单策略回测和多策略对比两种结果格式
 */
function inferBacktestsFromResult(result) {
  const list = []

  // 多策略对比模式：result.results 是一个对象，每个 key 对应一个策略
  const multiResults = result.results || (result.data && result.data.results)
  if (multiResults && typeof multiResults === 'object' && !Array.isArray(multiResults)) {
    for (const [key, val] of Object.entries(multiResults)) {
      const entry = buildBacktestEntry(val, key, result)
      if (entry) list.push(entry)
    }
    if (list.length) return list
  }

  // 单策略回测模式
  const entry = buildBacktestEntry(result, '', result)
  if (entry) list.push(entry)
  return list
}

function buildBacktestEntry(obj, fallbackName, rootResult) {
  if (!obj || typeof obj !== 'object') return null

  const data = obj.data || obj
  const meta = obj.metadata || rootResult.metadata || {}
  const strategy = obj.strategy || data.strategy || {}
  const btResult = data.result || obj.result || {}

  const recordId = data.record_id || obj.record_id || meta.record_id || btResult.record_id || ''
  const strategyName = data.strategy_name || obj.strategy_name
    || strategy.name || meta.strategy_name || ''
  const templateCode = data.template_code || obj.template_code
    || strategy.template_code || meta.template_code || ''

  if (!strategyName && !recordId) return null

  const startDate = data.start_date || obj.start_date || meta.start_date || ''
  const endDate = data.end_date || obj.end_date || meta.end_date || ''

  const metrics = data.metrics || obj.metrics || meta.metrics || {}
  if (!metrics.total_return && btResult.total_return != null) metrics.total_return = btResult.total_return
  if (!metrics.annual_return && btResult.annual_return != null) metrics.annual_return = btResult.annual_return
  if (!metrics.max_drawdown && btResult.max_drawdown != null) metrics.max_drawdown = btResult.max_drawdown
  if (!metrics.sharpe_ratio && btResult.sharpe_ratio != null) metrics.sharpe_ratio = btResult.sharpe_ratio

  const weightSnapshots = data.weight_snapshots || obj.weight_snapshots
    || btResult.weight_snapshots || btResult.weight_changes || []

  return {
    record_id: recordId || ('inferred_' + (strategyName || fallbackName) + '_' + Date.now()),
    strategy_name: strategyName || fallbackName || '回测策略',
    template_code: templateCode,
    start_date: startDate,
    end_date: endDate,
    initial_capital: data.initial_capital || obj.initial_capital || meta.initial_capital || 1000000,
    created_at: data.created_at || obj.created_at || '',
    metrics,
    weight_snapshots: Array.isArray(weightSnapshots) ? weightSnapshots : [],
    result: btResult
  }
}
