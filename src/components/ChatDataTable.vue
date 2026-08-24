<template>
  <div class="chat-data-table">
    <!-- 顶部信息栏 -->
    <div class="table-header-bar">
      <span v-if="summary" class="table-summary">{{ summary }}</span>
      <!-- JOIN 来源图例 -->
      <span v-if="hasJoinSource" class="join-source-legend">
        <span
          v-for="legend in joinSourceLegend"
          :key="legend.source"
          class="join-source-tag"
          :class="'join-source-' + legend.source"
        >{{ legend.label }}</span>
      </span>
      <span class="table-record-count">
        <i class="el-icon-document"></i>
        共 {{ totalRecords }} 条记录
        <template v-if="searchKeyword && filteredCount !== totalRecords">
          <span class="table-filter-tip">匹配 {{ filteredCount }} 条</span>
        </template>
        <template v-if="isPreviewMode">
          <span class="table-preview-tip">仅预览前 {{ previewLimit }} 条，下载可获取完整数据</span>
        </template>
        <template v-if="stepKey">
          <span class="table-step-tag">{{ stepKey }}</span>
        </template>
      </span>
      <div class="table-header-actions">
        <input
          v-if="records && records.length"
          ref="tableSearchInput"
          v-model="searchInput"
          type="text"
          class="table-search-input"
          placeholder="搜索全表内容"
          @blur="onSearchBlur"
          @compositionstart="_searchComposing = true"
          @compositionend="_searchComposing = false"
          @click.stop
          @mousedown.stop
        />
        <button
          v-if="canCollapse"
          class="table-toggle-btn"
          type="button"
          @click="expanded = !expanded"
        >
          <i :class="expanded ? 'el-icon-arrow-up' : 'el-icon-arrow-down'"></i>
          {{ expanded ? '收起' : '展开全部' }}
        </button>
        <button
          v-if="canLoadFullData"
          class="table-load-full-btn"
          type="button"
          :disabled="loadingFullData"
          :title="'后端缩略展示，可一键拉取完整 ' + recordCount + ' 条同区间数据'"
          @click="loadFullData"
        >
          <i :class="loadingFullData ? 'el-icon-loading' : 'el-icon-refresh'"></i>
          {{ loadingFullData ? '加载中...' : '加载完整 ' + recordCount + ' 条' }}
        </button>
        <!-- 导出按钮暂隐藏（不生效）：后续恢复时去掉 v-if="false" 即可 -->
        <button
          v-if="false && records && records.length"
          class="table-export-btn"
          type="button"
          @click="exportCsv"
        >
          <i class="el-icon-download"></i> 导出
        </button>
      </div>
    </div>

    <!-- 涉及资产芯片区：分「代表资产」与「参考资产」两组，默认折叠 -->
    <div v-if="effectiveTraceableAssets.length" class="traceable-assets-bar">
      <span class="traceable-assets-label">
        <i class="el-icon-data-analysis"></i>
        涉及资产 ({{ effectiveTraceableAssets.length }})：
      </span>

      <!-- 代表资产：启用悬停迷你图，可点击弹窗 -->
      <asset-mini-chart
        v-for="asset in displayedRepresentativeAssets"
        :key="'chip_' + asset.code"
        :asset-code="asset.code"
        :asset-name="asset.name || asset.code"
        :disabled="asset.valid === false || asset.has_kline === false"
        :bars-override="assetBarsMap[asset.code] || null"
      >
        <span
          class="asset-chip"
          :class="{
            'asset-chip-no-kline': asset.has_kline === false,
            'asset-chip-invalid': asset.valid === false,
            'asset-chip-active': hoveredAssetCode === asset.code
          }"
          :title="asset.valid === false ? '该资产在系统中不存在' : ''"
          @click.stop="asset.valid === false ? null : handleAssetClick(asset)"
          @mouseenter="handleChipMouseEnter(asset)"
          @mouseleave="handleChipMouseLeave"
        >
          <span class="asset-chip-code">{{ asset.code }}</span>
          <span v-if="asset.name && asset.name !== asset.code" class="asset-chip-sep">·</span>
          <span v-if="asset.name && asset.name !== asset.code" class="asset-chip-name">{{ asset.name }}</span>
          <i v-if="asset.valid !== false" class="el-icon-data-line asset-chip-icon"></i>
          <i v-else class="el-icon-warning-outline asset-chip-icon"></i>
        </span>
      </asset-mini-chart>

      <!-- 代表折叠展开按钮 -->
      <button
        v-if="hiddenRepresentativeCount > 0"
        class="asset-chip-toggle"
        type="button"
        @click.stop.prevent="toggleChipsExpanded"
      >
        {{ chipsExpanded ? '收起' : '+' + hiddenRepresentativeCount + ' 个代表' }}
      </button>

      <!-- 参考资产：全部折叠为一个折叠块，点开后以纯文本展示，仅点击才调起弹窗 -->
      <span v-if="referenceAssets.length" class="asset-reference-block">
        <button
          class="asset-chip-toggle asset-chip-toggle-ref"
          type="button"
          @click.stop.prevent="toggleReferenceExpanded"
        >
          <i :class="referenceExpanded ? 'el-icon-arrow-up' : 'el-icon-arrow-down'"></i>
          参考资产 ({{ referenceAssets.length }})
        </button>
        <!-- 关键：用 :style 显式控制 display，避免 v-show 被 CSS 覆盖；同时 displayedReferenceAssets 在折叠时返回 [] 顶多会销毁子节点 -->
        <span :style="{ display: referenceExpanded ? 'inline-flex' : 'none' }" class="asset-reference-list">
          <span
            v-for="asset in displayedReferenceAssets"
            :key="'ref_' + asset.code"
            class="asset-chip asset-chip-reference"
            :class="{
              'asset-chip-invalid': asset.valid === false,
              'asset-chip-active': hoveredAssetCode === asset.code
            }"
            :title="asset.valid === false ? '该资产在系统中不存在，仅供参考' : '点击查看详情'"
            @click.stop="asset.valid === false ? null : handleAssetClick(asset)"
            @mouseenter="handleChipMouseEnter(asset)"
            @mouseleave="handleChipMouseLeave"
          >
            <span class="asset-chip-code">{{ asset.code }}</span>
            <span v-if="asset.name && asset.name !== asset.code" class="asset-chip-sep">·</span>
            <span v-if="asset.name && asset.name !== asset.code" class="asset-chip-name">{{ asset.name }}</span>
          </span>
          <button
            v-if="remainingReferenceCount > 0"
            class="asset-chip-toggle asset-chip-toggle-ref"
            type="button"
            @click.stop.prevent="showMoreReference"
          >
            查看更多 ({{ remainingReferenceCount }})
          </button>
        </span>
      </span>
    </div>

    <!-- 涉及策略芯片区：展示回测记录关联的策略，悬停显示迷你权重变化图，点击弹出回测详情 -->
    <div v-if="traceableBacktests && traceableBacktests.length" class="traceable-backtests-bar">
      <span class="traceable-assets-label">
        <i class="el-icon-s-data"></i>
        涉及策略 ({{ traceableBacktests.length }})：
      </span>

      <backtest-mini-chart
        v-for="bt in displayedBacktests"
        :key="'bt_' + bt.record_id"
        :strategy-name="bt.strategy_name"
        :template-code="bt.template_code"
        :metrics="bt.metrics || {}"
        :weight-snapshots="bt.weight_snapshots || []"
      >
        <span
          class="backtest-chip"
          @click.stop="handleBacktestClick(bt)"
        >
          <span class="backtest-chip-name">{{ bt.strategy_name }}</span>
          <el-tag size="mini" type="info" class="backtest-chip-tag">{{ bt.template_code }}</el-tag>
          <i class="el-icon-data-line backtest-chip-icon"></i>
        </span>
      </backtest-mini-chart>

      <!-- 超过限额时的展开/折叠按钮 -->
      <button
        v-if="hiddenBacktestCount > 0"
        class="asset-chip-toggle"
        type="button"
        @click.stop.prevent="backtestChipsExpanded = !backtestChipsExpanded"
      >
        {{ backtestChipsExpanded ? '收起' : '+' + hiddenBacktestCount + ' 个策略' }}
      </button>
    </div>

    <!-- 表格 -->
    <el-table
      :data="pagedData"
      :max-height="isPreviewMode ? null : 360"
      border
      size="mini"
      @sort-change="handleSortChange"
      style="width: 100%"
      :header-cell-style="headerCellStyle"
      :cell-class-name="getJoinCellClassName"
      :row-class-name="getRowClassName"
    >
      <el-table-column
        v-for="col in columns"
        :key="col.prop"
        :prop="col.prop"
        :label="col.label"
        sortable="custom"
        :min-width="col.minWidth"
        :align="col.align"
      >
        <template slot-scope="{ row, $index }">
          <!-- 使用 v-for="[m] in [...]" 模式创建局部变量，将每个单元格的 cellMeta 调用从 5-6 次降为 1 次 -->
          <template v-for="m in [cellMeta(row, col, $index)]">
          <asset-mini-chart
            v-if="m.asset"
            :key="'ta_' + col.prop + '_' + $index"
            :asset-code="m.asset.code"
            :asset-name="m.asset.name || m.text"
            :bars-override="assetBarsMap[m.asset.code] || null"
          >
            <span class="traceable-asset-cell" @click.stop="handleAssetClick(m.asset)">
              {{ m.text }}
              <i class="el-icon-data-line traceable-asset-icon"></i>
            </span>
          </asset-mini-chart>
          <!-- 含 Markdown 内联语法（**加粗**、*斜体*、`code`）的单元格使用 v-html，
               使 LLM 输出的 `**大盘蓝筹**` 能被渲染为加粗而非保留字面星号 -->
          <span
            v-else-if="m.md"
            class="cell-md"
            v-html="m.md"
          ></span>
          <span
            v-else
            :class="[
              col.type === 'number' ? 'cell-number' : '',
              col.source === 'left' ? 'cell-join-left' : '',
              col.source === 'right' ? 'cell-join-right' : ''
            ].filter(Boolean)"
          >
            {{ m.text }}
          </span>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div v-if="expanded && filteredCount > pageSize" class="table-pagination">
      <el-pagination
        small
        layout="prev, pager, next, total"
        :page-size="pageSize"
        :total="filteredCount"
        :current-page.sync="currentPage"
      />
    </div>
  </div>
</template>

<script>
/**
 * 常见英文字段 → 中文标题映射
 */
const COLUMN_LABEL_MAP = {
  name: '名称',
  code: '代码',
  date: '日期',
  price: '价格',
  return: '收益率',
  value: '值',
  weight: '权重',
  amount: '金额',
  volume: '成交量',
  change: '涨跌幅',
  open: '开盘价',
  close: '收盘价',
  high: '最高价',
  low: '最低价',
  market_cap: '市值',
  pe_ratio: '市盈率',
  asset_name: '资产名称',
  asset_code: '资产代码',
  start_date: '开始日期',
  end_date: '结束日期',
  total_return: '总收益率',
  annual_return: '年化收益率',
  annualized_return: '年化收益率',
  sharpe_ratio: '夏普比率',
  max_drawdown: '最大回撤',
  volatility: '波动率',
  benchmark: '基准',
  strategy: '策略',
  type: '类型',
  status: '状态',
  description: '描述',
  currency: '货币',
  country: '国家',
  sector: '行业',
  index: '序号',
  id: 'ID',
  count: '数量',
  ratio: '比率',
  rate: '费率',
  fee: '费用',
  nav: '净值',
  pnl: '盈亏',
  turnover: '换手率',
  correlation: '相关性',
  beta: 'Beta',
  alpha: 'Alpha',
  std_dev: '标准差',
  skewness: '偏度',
  kurtosis: '峰度',
  trade_date: '交易日期',
  settle_date: '结算日期',
  ticker: '代码',
  symbol: '标的'
}

/** 日期正则 */
const DATE_RE = /^\d{4}[-/]\d{1,2}[-/]\d{1,2}/

/** 百分比字段关键词 */
const PERCENT_KEYWORDS = [
  'return', 'rate', 'ratio', 'change', 'drawdown',
  'volatility', 'yield', 'pct', 'percent', 'weight'
]

/**
 * 检测列数据类型
 * @param {Array} values 列值数组
 * @returns {'number'|'date'|'string'}
 */
function detectColumnType(values) {
  const sample = values.filter(v => v != null && v !== '').slice(0, 20)
  if (!sample.length) return 'string'

  const allNumber = sample.every(v =>
    typeof v === 'number' || (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v)))
  )
  if (allNumber) return 'number'

  const allDate = sample.every(v => typeof v === 'string' && DATE_RE.test(v))
  if (allDate) return 'date'

  return 'string'
}

/**
 * 判断字段是否为百分比类型
 * @param {string} key 字段名
 * @returns {boolean}
 */
function isPercentField(key) {
  const lower = key.toLowerCase()
  return PERCENT_KEYWORDS.some(k => lower.includes(k))
}

import AssetMiniChart, { prefetchAssetKline } from './AssetMiniChart.vue'
import BacktestMiniChart from './BacktestMiniChart.vue'
import { getAssetKline } from '@/api/asset'

// 检测是否含常见的 Markdown 内联语法（加粗/斜体/代码/删除线）
// 用非贪婪匹配避免跨标记越界；含 \*\*x\*\*、__x__、`x`、~~x~~、*x*
const MD_INLINE_RE = /(\*\*.+?\*\*)|(__.+?__)|(`.+?`)|(~~.+?~~)|(\*[^*\s].*?\*)/

// 模块级 inline markdown 渲染结果 LRU 缓存：表格频繁重渲染时（搜索/排序/翻页）
// 避免同一单元格重复执行 marked.parseInline + sanitizeHtml。上限 ≈1000 条。
const MD_INLINE_CACHE = new Map()
const MD_INLINE_CACHE_LIMIT = 1000

/**
 * 轻量 inline markdown 解析器（替代 marked.parseInline 处理中文/符号场景下强调解析失效）
 * - 将 **x** → <strong>x>，__x__ → <strong>x>，`x` → <code>x</code>
 * - 将 ~~x~~ → <del>x</del>，*x* → <em>x</em>
 * - 安全转义 HTML 特殊字符
 * - 覆盖场景：\"**+1.89%**\"、\"**跑赢大盘**\" 等中文/符号紧贴标记
 */
function renderInlineMarkdownRaw(raw) {
  let s = String(raw)
  // 先转义 HTML 安全字符
  s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  // **加粗**（先于 *斜体*，避免被截断）
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // __加粗__
  s = s.replace(/__(.+?)__/g, '<strong>$1</strong>')
  // `代码`
  s = s.replace(/`(.+?)`/g, '<code>$1</code>')
  // ~~删除线~~
  s = s.replace(/~~(.+?)~~/g, '<del>$1</del>')
  // *斜体*（此时剩余的 * 才属于斜体，避免与 ** 冲突）
  s = s.replace(/\*([^*]+?)\*/g, '<em>$1</em>')
  return s
}

function renderInlineMarkdownCached(raw) {
  if (MD_INLINE_CACHE.has(raw)) {
    // LRU：命中后重新插入提升领先度
    const v = MD_INLINE_CACHE.get(raw)
    MD_INLINE_CACHE.delete(raw)
    MD_INLINE_CACHE.set(raw, v)
    return v
  }
  const html = renderInlineMarkdownRaw(raw)
  MD_INLINE_CACHE.set(raw, html)
  if (MD_INLINE_CACHE.size > MD_INLINE_CACHE_LIMIT) {
    // 删除最早插入的一项
    const firstKey = MD_INLINE_CACHE.keys().next().value
    MD_INLINE_CACHE.delete(firstKey)
  }
  return html
}

// 模块级展开状态缓存：按 segId/指纹缓存各组件实例的「参考资产展开」与「代表资产展开」状态。
// 主要防御 vue-virtual-scroller / DynamicScrollerItem 重测尺寸时可能触发
// ChatDataTable 重建导致 data 重置，展开状态丢失。
const expandStateCache = new Map()
function buildExpandKey(records, traceableAssets) {
  const headers = records && records.length ? Object.keys(records[0]).join('|') : ''
  const len = (records && records.length) || 0
  const taLen = (traceableAssets && traceableAssets.length) || 0
  return `${headers}::${len}::${taLen}`
}

/**
 * 模块级单元格渲染元数据缓存：
 * 当虚拟滚动销毁/重建组件时，同一 records 引用的表格可直接复用已计算的 Meta Map，
 * 避免每次重建都重新计算 rows×cols 个单元格的资产检测+Markdown解析+格式化。
 * 使用 WeakMap 以 records 数组为键，确保不影响 GC。
 */
const _cellMetaModuleCache = new WeakMap()

/**
 * 模块级 columns 缓存：避免虚拟滚动重建时重复计算列类型检测。
 * WeakMap 以 records 引用为键，相同数据不重新采样检测。
 */
const _columnsModuleCache = new WeakMap()

export default {
  name: 'ChatDataTable',
  components: { AssetMiniChart, BacktestMiniChart },
  props: {
    records: { type: Array, required: true },
    summary: { type: String, default: '' },
    recordCount: { type: Number, default: 0 },
    dataShape: { type: String, default: 'table' },
    stepKey: { type: String, default: '' },
    /** 缩略展示的行数：超过此阈值默认只显示前 previewLimit 行 */
    previewLimit: { type: Number, default: 10 },
    /** 可追踪的资产列表，用于单元格交互高亮 */
    traceableAssets: { type: Array, default: () => [] },
    /** 可追踪的回测记录列表，用于展示涉及策略芯片 */
    traceableBacktests: { type: Array, default: () => [] }
  },
  data() {
    return {
      currentPage: 1,
      pageSize: 20,
      sortProp: '',
      sortOrder: '',
      /** 是否已展开全部数据（默认展开，避免需手动展开才能翻页查看） */
      expanded: true,
      /** 表内搜索「输入框绑定值」：用户按键即时反映，保证输入连续不卸载表格 */
      searchInput: '',
      /** 表内搜索关键字（全字段模糊匹配）：受防抖控制，需要过滤表格时才同步 */
      searchKeyword: '',
      /** 搜索防抖定时器 */
      _searchDebounceTimer: null,
      /** 最后一次输入时间戳（用于 blur 后判断是否“仍在输入会话”，进而补回焦点） */
      _lastInputTs: 0,
      /** 是否在 IME 拼音合成中（拼音期间不跳防抖也不补焦点） */
      _searchComposing: false,
      /** 代表资产芯片是否全部展开（默认折叠：超出 chipDisplayLimit 部分隐藏） */
      chipsExpanded: false,
      /** 参考资产是否展开（默认折叠，避免一次性铺满大量同类资产，影响阅读） */
      referenceExpanded: false,
      /** 已发送的参考资产「分批渲染」限额：避免一次性 mount 上百个芯片阻塞主线程 */
      referenceRenderLimit: 60,
      /** 默认代表芯片显示上限（超出需点展开） */
      chipDisplayLimit: 12,
      /** 回测策略芯片是否全部展开 */
      backtestChipsExpanded: false,
      /** 默认回测芯片显示上限 */
      backtestChipDisplayLimit: 6,
      /** === 全量数据补拉状态（后端缩略场景下手动/自动拉取完整区间数据）=== */
      /** 补拉后的全量 records，覆盖 props.records 作为表格数据源 */
      internalRecords: null,
      /** 全量数据拉取中 */
      loadingFullData: false,
      /** 全量数据拉取失败 */
      fullDataLoadFailed: false,
      /** === 资产芯片悬停高亮表格行状态 === */
      /** 当前悬停的资产代码，表格中匹配的行会高亮 */
      hoveredAssetCode: ''
    }
  },
  computed: {
    /**
     * 表头样式：JOIN 场景下左表列浅蓝、右表列浅绿；非 JOIN 场景保持默认灰色
     * el-table 的 header-cell-style 支持函数，参数为 { columnIndex, column }
     */
    headerCellStyle() {
      // 将 sourceMap 捕获进闭包，避免 el-table 回调时 this 不指向组件实例
      const sourceMap = this.columnSourceMap
      return ({ column }) => {
        const src = column && sourceMap[column.property]
        if (src === 'left') {
          return {
            background: '#e8f4fd',
            color: '#1a5276',
            fontWeight: '600',
            fontSize: '12px',
            borderBottom: '2px solid #409EFF'
          }
        }
        if (src === 'right') {
          return {
            background: '#e8f5e9',
            color: '#1b5e20',
            fontWeight: '600',
            fontSize: '12px',
            borderBottom: '2px solid #67C23A'
          }
        }
        return {
          background: '#f5f7fa',
          color: '#606266',
          fontWeight: '600',
          fontSize: '12px'
        }
      }
    },

    /** 是否存在 JOIN 列（至少有一列标记为 left 或 right）*/
    hasJoinSource() {
      return this.columns.some(c => c.source === 'left' || c.source === 'right')
    },

    /** 字段 prop → source 映射，供 headerCellStyle 函数查找（el-table-column 不转发 custom props）*/
    columnSourceMap() {
      const map = {}
      for (const col of this.columns) {
        if (col.source) map[col.prop] = col.source
      }
      return map
    },

    /** JOIN 来源图例：返回 [{label, source}] 用于顶部图例渲染 */
    joinSourceLegend() {
      const seen = new Set()
      const legends = []
      for (const col of this.columns) {
        if (col.source && !seen.has(col.source)) {
          seen.add(col.source)
          if (col.source === 'left') {
            legends.push({ label: '左表字段', source: 'left' })
          } else if (col.source === 'right') {
            legends.push({ label: '右表字段', source: 'right' })
          }
        }
      }
      return legends
    },

    totalRecords() {
      // 补拉后以补拉后的实际条数为准，避免「全量后端缩略记录数」不一致
      if (this.internalRecords && this.internalRecords.length) {
        return this.internalRecords.length
      }
      return this.recordCount || this.records.length
    },

    /**
     * 实际生效的 records：补拉后优先使用 internalRecords，其他计算均安此展开。
     */
    effectiveRecords() {
      if (this.internalRecords && this.internalRecords.length) {
        return this.internalRecords
      }
      return this.records
    },

    /** 后端缩略检测：recordCount > 实际下发条数（且尚未补拉） */
    isTruncated() {
      if (this.internalRecords) return false
      const total = this.recordCount || 0
      const actual = (this.records && this.records.length) || 0
      return total > 0 && actual > 0 && total > actual
    },

    /** 从 records 推断区间资产代码：仅当能唯一确定资产时才可补拉 */
    inferredAssetForRefetch() {
      const records = this.records
      if (!records || !records.length) return null
      // 1. 先从 records 推断：若存在 code/asset_code 列且仅一个唯一值
      const codeKeys = ['code', 'asset_code', 'symbol', 'ticker']
      const codeKey = codeKeys.find(k => Object.prototype.hasOwnProperty.call(records[0], k))
      if (codeKey) {
        const codes = new Set()
        for (const row of records) {
          const c = row && row[codeKey]
          if (c != null && String(c).trim()) codes.add(String(c).trim())
        }
        if (codes.size === 1) {
          const code = Array.from(codes)[0]
          const fromTraceable = (this.traceableAssets || []).find(a => a.code === code)
          return fromTraceable || { code, name: code }
        }
        // 多资产场景：暂不支持一键补拉（需后端配合批量接口）
        return null
      }
      // 2. 无 code 列：若 traceableAssets 仅一个，则表格必为单资产行情
      const ta = this.traceableAssets || []
      if (ta.length === 1) return ta[0]
      return null
    },

    /** 从 records 推断表格覆盖的日期区间 */
    inferredDateRange() {
      const records = this.records
      if (!records || !records.length) return null
      const dateKeys = ['date', 'trade_date', '日期', 'day']
      const dateKey = dateKeys.find(k => Object.prototype.hasOwnProperty.call(records[0], k))
      if (!dateKey) return null
      const dates = []
      for (const row of records) {
        const v = row && row[dateKey]
        if (v == null) continue
        const s = String(v).trim()
        if (s) dates.push(s)
      }
      if (!dates.length) return null
      dates.sort()
      return { start: dates[0], end: dates[dates.length - 1], dateKey }
    },

    /** 是否可以拉取完整数据 */
    canLoadFullData() {
      return this.isTruncated && !!this.inferredAssetForRefetch && !!this.inferredDateRange
    },

    /**
     * 资产代码 → 该资产对应的 records 子集（供迷你图 barsOverride 使用）：
     * - 多资产表（存在 code/asset_code 列）：按 code 分组
     * - 单资产表：所有行归属唯一资产
     */
    assetBarsMap() {
      const records = this.effectiveRecords
      if (!records || !records.length) return {}
      // 快速跳过：无资产列时不需要构建
      if (!this.effectiveTraceableAssets.length && !this.codeColumnSet.size) return {}
      const codeKeys = ['code', 'asset_code', 'symbol', 'ticker']
      const firstRow = records[0]
      const codeKey = codeKeys.find(k => Object.prototype.hasOwnProperty.call(firstRow, k))
      if (codeKey) {
        const map = {}
        for (const row of records) {
          const c = row && row[codeKey]
          if (c == null) continue
          const cs = String(c).trim()
          if (!cs) continue
          if (!map[cs]) map[cs] = []
          map[cs].push(row)
        }
        return map
      }
      const ta = this.effectiveTraceableAssets
      if (ta && ta.length === 1) {
        return { [ta[0].code]: records }
      }
      return {}
    },

    columns() {
      const recs = this.effectiveRecords
      if (!recs.length) return []

      // 模块级缓存：同一 records 引用 → 直接复用已计算的 columns
      const cached = _columnsModuleCache.get(recs)
      if (cached) return cached

      const firstRow = recs[0]
      const keys = Object.keys(firstRow)

      // JOIN 来源检测：右表字段以 "{collection}." 前缀命名（见 domain_tools.py join 合并逻辑）
      const JOIN_PREFIX_RE = /^([a-z]\w+)\.([\w]+)$/
      const hasJoinColumns = keys.some(k => JOIN_PREFIX_RE.test(k))

      // 预取样：每列只取前 20 条非空值用于类型检测，避免大表全量 map
      const sampleSize = 20
      const samplesByCol = {}
      for (const key of keys) {
        const sample = []
        for (let i = 0; i < recs.length && sample.length < sampleSize; i++) {
          const v = recs[i][key]
          if (v != null && v !== '') sample.push(v)
        }
        samplesByCol[key] = sample
      }

      const result = keys.map(key => {
        const colType = detectColumnType(samplesByCol[key])
        const isPct = isPercentField(key)

        // 标记列来源：'left'（左表）/ 'right'（右表）/ null（非 JOIN 场景）
        let source = null
        let label = COLUMN_LABEL_MAP[key] || key
        if (hasJoinColumns) {
          const joinMatch = key.match(JOIN_PREFIX_RE)
          if (joinMatch) {
            // 右表字段：{collection}.{field} → 取基名查中文映射，拼接集合短名
            const rightBase = joinMatch[2]
            const rightCollection = joinMatch[1]
            source = 'right'
            label = (COLUMN_LABEL_MAP[rightBase] || rightBase) + ` [${rightCollection}]`
          } else {
            source = 'left'
          }
        }

        return {
          prop: key,
          label,
          type: colType,
          isPercent: isPct,
          align: colType === 'number' ? 'right' : 'left',
          minWidth: this.calcMinWidth(key, colType),
          source
        }
      })
      // 写入模块级缓存
      _columnsModuleCache.set(recs, result)
      return result
    },

    sortedData() {
      const base = this.filteredRecords
      if (!this.sortProp || !this.sortOrder) return base
      const prop = this.sortProp
      const asc = this.sortOrder === 'ascending'
      return [...base].sort((a, b) => {
        const va = a[prop]
        const vb = b[prop]
        if (va == null) return 1
        if (vb == null) return -1
        // 数字优先：字符串形式的数字也按数值比较
        const na = typeof va === 'number' ? va : Number(va)
        const nb = typeof vb === 'number' ? vb : Number(vb)
        const bothNum = !isNaN(na) && !isNaN(nb) && va !== '' && vb !== ''
        if (bothNum) {
          return asc ? na - nb : nb - na
        }
        return asc
          ? String(va).localeCompare(String(vb))
          : String(vb).localeCompare(String(va))
      })
    },

    /** 根据搜索关键字过滤后的记录（全字段模糊匹配，由 haystack 缓存加速） */
    filteredRecords() {
      const kw = (this.searchKeyword || '').trim().toLowerCase()
      const base = this.effectiveRecords
      if (!kw) return base
      const haystacks = this._getRowHaystacks(base)
      const out = []
      for (let i = 0; i < base.length; i++) {
        if (haystacks[i].indexOf(kw) !== -1) out.push(base[i])
      }
      return out
    },

    /** 过滤后的总条数（用于分页与提示） */
    filteredCount() {
      return this.filteredRecords.length
    },

    /**
     * 实际生效的可追踪资产列表：优先用 prop 传入的 traceableAssets，
     * 若为空则从 records 中自动推断（快速兑现，不依赖后端）。
     * 推断规则：识别 code/asset_code/symbol/ticker + name/asset_name 列，按 code 去重。
     * 同时过滤：valid===false（后端未删除时兜底）+ 形如 "6999/xh003/3/22" 的无意义 code。
     */
    effectiveTraceableAssets() {
      const raw = (this.traceableAssets && this.traceableAssets.length)
        ? this.traceableAssets
        : this._inferTraceableFromRecords()
      if (!raw || !raw.length) return []
      return raw.filter(a => {
        if (!a || !a.code) return false
        // 后端已校验：明确 valid===false 直接滤除
        if (a.valid === false) return false
        // code 格式 sanity：滤除明显无意义代码（纯数字短码、小写字母短码）
        const code = String(a.code).trim()
        if (!code || code.length < 2) return false
        // 纯数字且 < 5 位（如 22 / 3 / 6999） → 视为脏数据
        if (/^\d{1,4}$/.test(code)) return false
        // 全小写字母+短数字（如 xh003） → 视为脏数据；系统真实资产为大写字母/数字组合
        if (/^[a-z]{1,3}\d{1,4}$/.test(code)) return false
        return true
      })
    },
    /** 代表资产列表：is_representative !== false 的资产；有效性不作过滤（仅影响点击与迷你图） */
    representativeAssets() {
      return this.effectiveTraceableAssets.filter(a => a.is_representative !== false)
    },
    /** 参考资产列表：被后端标记 is_representative=false 的资产，默认折叠 */
    referenceAssets() {
      return this.effectiveTraceableAssets.filter(a => a.is_representative === false)
    },
    /** 实际渲染的参考资产列表（分批渲染，避免一次 mount 上百个 DOM 节点卡主线程） */
    displayedReferenceAssets() {
      if (!this.referenceExpanded) return []
      const limit = Math.max(0, this.referenceRenderLimit | 0)
      if (!limit || limit >= this.referenceAssets.length) return this.referenceAssets
      return this.referenceAssets.slice(0, limit)
    },
    /** 还未渲染的参考资产数量（供「查看更多」按钮显示） */
    remainingReferenceCount() {
      if (!this.referenceExpanded) return 0
      return Math.max(0, this.referenceAssets.length - this.displayedReferenceAssets.length)
    },
    /** 实际展示的代表芯片（未展开时取前 N 个） */
    displayedRepresentativeAssets() {
      if (this.chipsExpanded) return this.representativeAssets
      return this.representativeAssets.slice(0, this.chipDisplayLimit)
    },
    /** 隐藏的代表芯片数 */
    hiddenRepresentativeCount() {
      return Math.max(0, this.representativeAssets.length - this.chipDisplayLimit)
    },

    /**
     * 合法资产快查表： code / name 跨双向映射 → 资产对象
     * 在 getCellAsset / getTraceableAsset 中 O(1) 查询，避免每个单元格都走 Array.find 线性扫描。
     */
    effectiveTraceableAssetMap() {
      const map = new Map()
      for (const a of this.effectiveTraceableAssets) {
        if (!a) continue
        if (a.code) map.set(String(a.code), a)
        if (a.name && a.name !== a.code) map.set(String(a.name), a)
      }
      return map
    },

    /** 代码类列名集合（小写） */
    codeColumnSet() {
      return new Set(['code', 'asset_code', 'symbol', 'ticker'])
    },
    /** 名称类列名集合（小写） */
    nameColumnSet() {
      return new Set(['name', 'asset_name'])
    },
    /** 哪些列的 prop 属于资产列（快速 Set 查询） */
    assetColumnProps() {
      const s = new Set()
      if (!this.effectiveTraceableAssetMap.size) return s
      const codeSet = this.codeColumnSet
      const nameSet = this.nameColumnSet
      for (const col of this.columns) {
        const lower = String(col.prop || '').toLowerCase()
        if (codeSet.has(lower) || nameSet.has(lower)) s.add(col.prop)
      }
      return s
    },

    /** 表格有哪些列属于资产列（取决于列名）：避免非资产列每行都走 getCellAsset 活 */
    hasAssetCellColumn() {
      return this.assetColumnProps.size > 0
    },

    /**
     * 预计算单元格渲染元数据 Map：key = rowIndex + '|' + colProp
     * 每条记录一次性计算 asset / markdown / formatted text，
     * 模板中通过 cellMeta(row, col) 读取，消除重复函数调用。
     */
    _cellRenderMeta() {
      const meta = new Map()
      const rows = this.pagedData
      const cols = this.columns
      if (!rows.length || !cols.length) return meta
      const assetProps = this.assetColumnProps
      const assetMap = this.effectiveTraceableAssetMap

      // 模块级缓存复用：同一 records + 同一资产配置 + 同一分页 → 直接复用
      // 防御虚拟滚动重建时的重复计算
      const records = this.records // prop 原始引用
      const cacheVersion = `${this.currentPage}|${this.sortProp}|${this.sortOrder}|${this.searchKeyword}|${assetMap.size}`
      const moduleCached = _cellMetaModuleCache.get(records)
      if (moduleCached && moduleCached.v === cacheVersion) {
        return moduleCached.r
      }

      for (let i = 0; i < rows.length; i++) {
        const row = rows[i]
        for (let j = 0; j < cols.length; j++) {
          const col = cols[j]
          const val = row[col.prop]
          // 资产检测：仅对资产列执行
          let asset = null
          if (assetProps.has(col.prop) && val != null) {
            const str = String(val).trim()
            if (str) asset = assetMap.get(str) || null
          }
          // 格式化文本
          const text = this.formatCell(val, col)
          // Markdown 检测：仅对非资产、非数值/日期、字符串值执行
          let md = null
          if (!asset && val != null && val !== '' && col.type !== 'date' && col.type !== 'number' && typeof val === 'string' && MD_INLINE_RE.test(val)) {
            md = renderInlineMarkdownCached(String(text))
          }
          meta.set(i + '|' + col.prop, { asset, text, md })
        }
      }

      // 写入模块级缓存
      _cellMetaModuleCache.set(records, { v: cacheVersion, r: meta })
      return meta
    },

    pagedData() {
      let data
      // 缩略模式：只显示前 previewLimit 行（不分页）
      if (this.isPreviewMode) {
        data = this.sortedData.slice(0, this.previewLimit)
      } else {
        const start = (this.currentPage - 1) * this.pageSize
        data = this.sortedData.slice(start, start + this.pageSize)
      }
      // 冻结行数据：告知 Vue 跳过深层响应式追踪（表格数据为只读展示，无需 getter/setter）
      // 对 20+ 列 × 20+ 行的表格可减少 60%+ 的响应式开销
      for (let i = 0; i < data.length; i++) {
        if (data[i] && !Object.isFrozen(data[i])) {
          Object.freeze(data[i])
        }
      }
      return data
    },

    /** 是否可折叠（数据超过预览阈值才需要） */
    canCollapse() {
      return this.records && this.records.length > this.previewLimit
    },

    /** 是否处于缩略预览模式 */
    isPreviewMode() {
      return this.canCollapse && !this.expanded
    },

    /** 实际展示的回测策略芯片 */
    displayedBacktests() {
      if (!this.traceableBacktests || !this.traceableBacktests.length) return []
      if (this.backtestChipsExpanded) return this.traceableBacktests
      return this.traceableBacktests.slice(0, this.backtestChipDisplayLimit)
    },
    /** 隐藏的回测策略芯片数 */
    hiddenBacktestCount() {
      if (!this.traceableBacktests) return 0
      return Math.max(0, this.traceableBacktests.length - this.backtestChipDisplayLimit)
    }
  },
  watch: {
    searchInput(val) {
      // 记录输入时间戳，给 onSearchBlur 判断“是否还在输入中”提供依据
      this._lastInputTs = Date.now()
      // IME 拼音合成中不防抖，避免错误过滤中间状态
      if (this._searchComposing) return
      // 防抖：按键期间不过滤表格，用户停杯 220ms 后才实际进行过滤
      if (this._searchDebounceTimer) {
        clearTimeout(this._searchDebounceTimer)
        this._searchDebounceTimer = null
      }
      if (!val) {
        this.searchKeyword = ''
        return
      }
      this._searchDebounceTimer = setTimeout(() => {
        this.searchKeyword = val
        this._searchDebounceTimer = null
      }, 220)
    },
    searchKeyword() {
      // 过滤关键字变化时重置到第一页，避免停留在超出范围的页码
      this.currentPage = 1
      // 持久化过滤状态，避免虚拟滚动重建后表格重滚回未过滤状态
      this._persistExpandState()
      // 关键：过滤完成后主动把焦点送回 input。
      // 如果在过滤期间虚拟滚动重测导致 input 被短暂卸载重建，重建后下一个 tick 补回焦点
      const recentlyTyping = this._lastInputTs && (Date.now() - this._lastInputTs) < 800
      if (recentlyTyping) this._restoreSearchFocus()
    },
    currentPage() {
      // 分页切换同样需持久化，避免虚拟滚动重建后跳回首页
      this._persistExpandState()
    },
    // 芯片区资产变化时空闲预取 K 线，但跳过虚拟滚动重建的前 300ms（避免短暂进出视口的组件触发无效预取）
    displayedRepresentativeAssets: {
      handler(list) {
        if (!list || !list.length) return
        // 组件刚创建时不立即预取，等待稳定后再触发
        if (this._prefetchTimer) clearTimeout(this._prefetchTimer)
        this._prefetchTimer = setTimeout(() => {
          this._prefetchTimer = null
          const codes = list
            .filter(a => a && a.code && a.valid !== false && a.has_kline !== false)
            .map(a => a.code)
          prefetchAssetKline(codes)
        }, 300)
      },
      immediate: true
    }
  },
  created() {
    // 从模块缓存恢复展开状态 + 搜索词：防虚拟滚动卸载重建后状态丢失
    try {
      const key = buildExpandKey(this.records, this.traceableAssets)
      const cached = expandStateCache.get(key)
      if (cached) {
        if (typeof cached.chipsExpanded === 'boolean') this.chipsExpanded = cached.chipsExpanded
        if (typeof cached.referenceExpanded === 'boolean') this.referenceExpanded = cached.referenceExpanded
        if (typeof cached.referenceRenderLimit === 'number' && cached.referenceRenderLimit > 0) {
          this.referenceRenderLimit = cached.referenceRenderLimit
        }
        if (typeof cached.searchKeyword === 'string') {
          this.searchKeyword = cached.searchKeyword
          // 同时同步输入框显示值，避免虚拟滚动重建后输入框看起来被清空
          this.searchInput = cached.searchKeyword
        }
        if (typeof cached.currentPage === 'number' && cached.currentPage > 0) {
          this.currentPage = cached.currentPage
        }
        if (typeof cached.sortProp === 'string') this.sortProp = cached.sortProp
        if (typeof cached.sortOrder === 'string') this.sortOrder = cached.sortOrder
      }
    } catch (e) { /* 快速失败，不影响首次渲染 */ }
  },
  beforeDestroy() {
    // 避免防抖定时器在组件卸载后还回头调 setState
    if (this._searchDebounceTimer) {
      clearTimeout(this._searchDebounceTimer)
      this._searchDebounceTimer = null
    }
    // 取消预取定时器
    if (this._prefetchTimer) {
      clearTimeout(this._prefetchTimer)
      this._prefetchTimer = null
    }
    // 取消参考资产递增渲染 tick，避免组件销毁后回头调问财产被销毁的实例
    if (typeof this._cancelReferenceProgressiveRender === 'function') {
      this._cancelReferenceProgressiveRender()
    }
  },
  methods: {
    /**
     * 获取单元格预计算渲染元数据：从 _cellRenderMeta computed 中读取，
     * 模板中替代 getCellAsset / isMarkdownCell / formatCell / renderInlineMarkdown 多次调用。
     * 内部按 rowIndex 缓存当前行的列 meta Map，避免同一行多次调用重复访问 computed。
     */
    cellMeta(row, col, idx) {
      if (this._cmIdx !== idx) {
        this._cmIdx = idx
        this._cmRow = this._cellRenderMeta
      }
      const m = this._cmRow && this._cmRow.get(idx + '|' + col.prop)
      return m || { asset: null, text: '-', md: null }
    },

    /**
     * 从 records 推断可追踪资产列表（后端未提供 traceableAssets 时使用）
     */
    _inferTraceableFromRecords() {
      const records = this.effectiveRecords
      if (!records || !records.length) return []
      const codeKeys = ['asset_code', 'code', 'symbol', 'ticker']
      const nameKeys = ['asset_name', 'name']
      const firstRow = records[0] || {}
      const codeKey = codeKeys.find(k => Object.prototype.hasOwnProperty.call(firstRow, k))
      const nameKey = nameKeys.find(k => Object.prototype.hasOwnProperty.call(firstRow, k))
      if (!codeKey) return []
      const seen = new Set()
      const list = []
      for (const row of records) {
        const code = row && row[codeKey]
        if (code == null || code === '') continue
        const codeStr = String(code).trim()
        if (!codeStr || seen.has(codeStr)) continue
        seen.add(codeStr)
        const name = nameKey ? (row[nameKey] || codeStr) : codeStr
        list.push({ code: codeStr, name: String(name).trim() || codeStr })
      }
      return list
    },

    /**
     * 切换参考资产展开/折叠。
     * 重要：必须阻止事件默认行为与冒泡，避免被外层 popper / DynamicScroller 的 click 监听干扰。
     * 同时将状态写入模块级缓存，在虚拟滚动重建本组件时仍能恢复。
     */
    toggleReferenceExpanded(e) {
      if (e) {
        if (typeof e.preventDefault === 'function') e.preventDefault()
        if (typeof e.stopPropagation === 'function') e.stopPropagation()
      }
      const next = !this.referenceExpanded
      this.referenceExpanded = next
      // 关键：取消所有正在排队的 idle / timer。
      // 否则折叠后队里的 tick 可能仍会走一次 _persistExpandState，使表格重建后误读为「展开」。
      this._cancelReferenceProgressiveRender()
      // 不论展开还是折叠，都重置分批渲染限额为初始值，下次展开重新走逐步渲染路线
      this.referenceRenderLimit = 60
      this._persistExpandState()
      if (next) {
        // 展开时：如超过默认限额，后续由 idle 递增（顶部首批依然即时可见）
        this._scheduleReferenceProgressiveRender()
      }
    },
    /** 切换代表资产展开/折叠 */
    toggleChipsExpanded(e) {
      if (e) {
        if (typeof e.preventDefault === 'function') e.preventDefault()
        if (typeof e.stopPropagation === 'function') e.stopPropagation()
      }
      this.chipsExpanded = !this.chipsExpanded
      this._persistExpandState()
    },
    /** 点「查看更多参考资产」：递增渲染限额并写入模块缓存，避免虚拟滚动重建后限额被老值覆盖 */
    showMoreReference(e) {
      if (e) {
        if (typeof e.preventDefault === 'function') e.preventDefault()
        if (typeof e.stopPropagation === 'function') e.stopPropagation()
      }
      const total = this.referenceAssets.length
      // 每次纯点击递增 60 个，并控制上限，不超过总量
      const next = Math.min(total, (this.referenceRenderLimit | 0) + 60)
      if (next <= this.referenceRenderLimit) {
        // 已是最大值，仅同步一次状态即可
        this._persistExpandState()
        return
      }
      this.referenceRenderLimit = next
      // 关键：需同步写回模块缓存，避免重建时被老值覆盖导致「点了没反应」
      this._persistExpandState()
    },
    /** 空闲时渐进式填充参考资产渲染，避免主线程卡顿 */
    _scheduleReferenceProgressiveRender() {
      if (!this.referenceExpanded) return
      if (this.referenceRenderLimit >= this.referenceAssets.length) return
      const step = 60
      const tick = () => {
        // 清除句柄，表示本 tick 已被调度出去执行
        this._refRenderIdleId = null
        this._refRenderTimerId = null
        // 二次检查：折叠后不再进行任何状态变更 / 持久化
        if (!this.referenceExpanded) return
        if (this.referenceRenderLimit >= this.referenceAssets.length) return
        this.referenceRenderLimit = Math.min(this.referenceAssets.length, this.referenceRenderLimit + step)
        this._persistExpandState()
        if (this.referenceRenderLimit < this.referenceAssets.length) {
          this._scheduleReferenceProgressiveRender()
        }
      }
      if (typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function') {
        this._refRenderIdleId = window.requestIdleCallback(tick, { timeout: 600 })
      } else {
        this._refRenderTimerId = setTimeout(tick, 120)
      }
    },
    /** 取消所有正在排队的参考资产递增渲染 tick（避免折叠后被复活「误写状态」） */
    _cancelReferenceProgressiveRender() {
      if (this._refRenderIdleId != null) {
        if (typeof window !== 'undefined' && typeof window.cancelIdleCallback === 'function') {
          try { window.cancelIdleCallback(this._refRenderIdleId) } catch (e) { /* ignore */ }
        }
        this._refRenderIdleId = null
      }
      if (this._refRenderTimerId != null) {
        clearTimeout(this._refRenderTimerId)
        this._refRenderTimerId = null
      }
    },
    /** 将当前展开状态写入模块缓存 */
    _persistExpandState() {
      const key = buildExpandKey(this.records, this.traceableAssets)
      const prev = expandStateCache.get(key) || {}
      expandStateCache.set(key, Object.assign(prev, {
        chipsExpanded: this.chipsExpanded,
        referenceExpanded: this.referenceExpanded,
        referenceRenderLimit: this.referenceRenderLimit,
        searchKeyword: this.searchKeyword,
        currentPage: this.currentPage,
        sortProp: this.sortProp,
        sortOrder: this.sortOrder
      }))
    },

    /**
     * 行级 haystack 缓存：为每行预生成全字段 toLowerCase 拼接字符串，避免每次输入都重复表扫描。
     * 仅在 records 引用变化时重建。挂在非响应式实例属性上，避免触发额外 reactivity 开销。
     */
    _getRowHaystacks(records) {
      if (this._rowHaystacks && this._rowHaystacksSource === records) {
        return this._rowHaystacks
      }
      const arr = new Array(records.length)
      for (let i = 0; i < records.length; i++) {
        const row = records[i]
        let s = ''
        if (row) {
          for (const key in row) {
            if (!Object.prototype.hasOwnProperty.call(row, key)) continue
            const v = row[key]
            if (v != null) s += String(v).toLowerCase() + '\u0001'
          }
        }
        arr[i] = s
      }
      this._rowHaystacks = arr
      this._rowHaystacksSource = records
      return arr
    },

    /**
     * 计算列最小宽度
     */
    calcMinWidth(key, colType) {
      const label = COLUMN_LABEL_MAP[key] || key
      const base = label.length * 15
      if (colType === 'date') return Math.max(120, base)
      if (colType === 'number') return Math.max(100, base)
      return Math.max(120, Math.min(base, 280))
    },

    /**
     * 格式化单元格
     */
    formatCell(value, col) {
      if (value == null || value === '') return '-'
      if (col.type === 'date') return this.formatDate(value)
      if (col.type === 'number') return this.formatNumber(value, col.isPercent)
      return value
    },

    /**
     * 判断单元格是否需要 Markdown 内联渲染：
     * - 仅限字符串型、且包含加粗/斜体/代码/删除线语法的值
     * - 数值、日期、可追踪资产列走原有渲染路径
     */
    isMarkdownCell(value, col) {
      if (value == null || value === '') return false
      if (col.type === 'date' || col.type === 'number') return false
      if (typeof value !== 'string') return false
      return MD_INLINE_RE.test(value)
    },

    /**
     * 对单元格内容运行 marked.parseInline，再走 DOMPurify 消毒，
     * 输出安全 HTML（<strong>/<em>/<code>/<del> 等）。
     */
    renderInlineMarkdown(value, col) {
      const formatted = this.formatCell(value, col)
      if (formatted == null || formatted === '-') return formatted
      return renderInlineMarkdownCached(String(formatted))
    },

    /**
     * 日期格式化 → YYYY-MM-DD
     */
    formatDate(value) {
      if (typeof value !== 'string') return value
      const m = value.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
      if (m) return m[1] + '-' + m[2].padStart(2, '0') + '-' + m[3].padStart(2, '0')
      return value
    },

    /**
     * 数值格式化
     */
    formatNumber(value, isPercent) {
      const num = typeof value === 'number' ? value : Number(value)
      if (isNaN(num)) return value
      if (isPercent) {
        if (Math.abs(num) > 0 && Math.abs(num) < 1) {
          return (num * 100).toFixed(2) + '%'
        }
        return num.toFixed(2) + '%'
      }
      if (Number.isInteger(num)) return num.toLocaleString()
      const abs = Math.abs(num)
      if (abs >= 1000) return num.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
      if (abs >= 1) return num.toFixed(2)
      return num.toFixed(4)
    },

    /**
     * 排序切换
     */
    handleSortChange({ prop, order }) {
      this.sortProp = prop
      this.sortOrder = order
      this.currentPage = 1
      this._persistExpandState()
    },

    /**
     * 搜索框 blur 事件处理：
     * 虚拟滚动重测可能会短暂把本 item 的 active 切为 false→true，期间 input 被卸载重建、原生焦点丢失。
     * 若检测到“刚刚还在输入”（< 600ms），立刻补回焦点并把光标置于末尾，实现「连续输入不断」。
     */
    onSearchBlur() {
      // IME 拼音中的 blur 不补焦点（避免与拼音面板冲突）
      if (this._searchComposing) return
      const now = Date.now()
      const recentlyTyping = this._lastInputTs && (now - this._lastInputTs) < 600
      if (!recentlyTyping) return
      this._restoreSearchFocus()
    },

    /**
     * 补回搜索框焦点：跨多个 tick 尝试 focus + 光标置末尾，覆盖
     * - vue-virtual-scroller ResizeObserver 中间帧闪烁
     * - el-table doLayout 重渲染
     * - 虚拟滚动短暂将 item active 切为 false 导致 input 卸载重建
     */
    _restoreSearchFocus() {
      const tryFocus = () => {
        const el = this.$refs.tableSearchInput
        if (el && document.activeElement !== el) {
          try {
            el.focus({ preventScroll: true })
          } catch (e) {
            try { el.focus() } catch (_) { /* ignore */ }
          }
          try {
            const len = (el.value || '').length
            if (typeof el.setSelectionRange === 'function') el.setSelectionRange(len, len)
          } catch (e) { /* ignore */ }
        }
      }
      this.$nextTick(tryFocus)
      requestAnimationFrame(() => {
        tryFocus()
        requestAnimationFrame(tryFocus)
      })
    },

    /**
     * 检查单元格值是否匹配可追踪资产列表中的 code 或 name
     * @param {*} cellValue 单元格原始值
     * @returns {Object|null} 匹配到的资产对象或 null
     */
    getTraceableAsset(cellValue) {
      const map = this.effectiveTraceableAssetMap
      if (!map.size || cellValue == null) return null
      const str = String(cellValue).trim()
      if (!str) return null
      return map.get(str) || null
    },

    /**
     * 按列名 + 值双重判定单元格是否为资产实体：
     * - 优先依据列名是否为 code/name 类（避免误匹中日期/数值列）
     * - 其他列仅在单元格值严格等于 code/name 时匹配
     */
    getCellAsset(row, col) {
      const map = this.effectiveTraceableAssetMap
      if (!map.size || !row || !col) return null
      const val = row[col.prop]
      if (val == null) return null
      const str = String(val).trim()
      if (!str) return null
      return map.get(str) || null
    },

    /**
     * 鼠标悬浮到可追踪资产时触发
     */
    handleAssetHover(asset, event) {
      this.$emit('asset-hover', { code: asset.code, name: asset.name, event })
    },

    /**
     * 鼠标离开可追踪资产时触发
     */
    handleAssetLeave() {
      this.$emit('asset-leave')
    },

    /**
     * 点击可追踪资产时触发
     */
    handleAssetClick(asset) {
      // 携带当前表格推断出的区间与理论上可供弹窗使用的 bars，让资产详情能与表格同源
      const range = this.inferredDateRange
      const bars = (this.assetBarsMap && this.assetBarsMap[asset.code]) || null
      this.$emit('asset-click', {
        code: asset.code,
        name: asset.name,
        startDate: range ? range.start : '',
        endDate: range ? range.end : '',
        bars
      })
    },

    /**
     * 资产芯片鼠标进入 / 离开：设置/清除表格行高亮状态
     */
    handleChipMouseEnter(asset) {
      this.hoveredAssetCode = asset && asset.code ? asset.code : ''
    },
    handleChipMouseLeave() {
      this.hoveredAssetCode = ''
    },

    /**
     * el-table 行类名：当 hoveredAssetCode 匹配本行中的 code/asset_code 时高亮
     * 优化：优先使用 columns 中已识别的资产列，避免每行都遍历 codeKeys
     */
    getRowClassName({ row }) {
      if (!this.hoveredAssetCode || !row) return ''
      const hoverCode = this.hoveredAssetCode
      // 优先用资产列 props 查找
      const assetProps = this.assetColumnProps
      if (assetProps.size) {
        for (const prop of assetProps) {
          if (row[prop] != null && String(row[prop]).trim() === hoverCode) {
            return 'asset-row-highlight'
          }
        }
      }
      // 回退：尝试常见 code 列
      const codeKeys = ['code', 'asset_code', 'symbol', 'ticker']
      for (const k of codeKeys) {
        if (row[k] != null && String(row[k]).trim() === hoverCode) {
          return 'asset-row-highlight'
        }
      }
      return ''
    },

    /**
     * JOIN 场景下为 td 单元格添加来源背景色类名
     * el-table cell-class-name 回调参数为 { row, column, rowIndex, columnIndex }
     */
    getJoinCellClassName({ column }) {
      if (!column || !column.property) return ''
      const src = this.columnSourceMap[column.property]
      if (src === 'left') return 'td-join-left'
      if (src === 'right') return 'td-join-right'
      return ''
    },

    /**
     * 拉取完整区间数据（后端缩略场景）：调用 getAssetKline 获取表格区间全量行情
     */
    async loadFullData() {
      if (this.loadingFullData) return
      const asset = this.inferredAssetForRefetch
      const range = this.inferredDateRange
      if (!asset || !range) {
        this.$message && this.$message.warning('无法推断资产与区间，请重试完整查询')
        return
      }
      this.loadingFullData = true
      this.fullDataLoadFailed = false
      try {
        const res = await getAssetKline(asset.code, {
          start_date: range.start,
          end_date: range.end
        })
        const raw = res && (res.data || res)
        const arr = Array.isArray(raw) ? raw : (Array.isArray(raw && raw.records) ? raw.records : [])
        if (!arr.length) {
          this.fullDataLoadFailed = true
          this.$message && this.$message.warning('未获取到完整数据')
          return
        }
        // 以原 records[0] 的字段名为准对齐补拉数据的字段，保证列结构一致
        const aligned = this._alignRecordsSchema(arr)
        // 冻结数组和各行，避免 Vue 深层响应式追踪（数据仅用于只读展示）
        for (let i = 0; i < aligned.length; i++) {
          if (aligned[i] && !Object.isFrozen(aligned[i])) Object.freeze(aligned[i])
        }
        this.internalRecords = Object.freeze(aligned)
        this.currentPage = 1
        this.expanded = true
        this.$message && this.$message.success('已加载完整 ' + aligned.length + ' 条数据')
      } catch (e) {
        this.fullDataLoadFailed = true
        // eslint-disable-next-line no-console
        console.error('[ChatDataTable] 拉取完整数据失败:', e)
        this.$message && this.$message.error('加载完整数据失败：' + (e.message || '未知错误'))
      } finally {
        this.loadingFullData = false
      }
    },

    /**
     * 补拉数据字段对齐：将补拉返回的原始 K 线数据（date/open/high/low/close/volume）
     * 按原 records[0] 的字段名重新映射，避免补拉后表格列变动。
     */
    _alignRecordsSchema(rawList) {
      if (!this.records || !this.records.length) return rawList
      const templateKeys = Object.keys(this.records[0])
      // 字段别名映射：模板字段 -> 可能的原始字段名列表
      const ALIAS = {
        date: ['date', 'trade_date', 'day', '日期'],
        trade_date: ['trade_date', 'date', 'day', '交易日期'],
        open: ['open', 'open_price', '开盘价'],
        high: ['high', 'high_price', '最高价'],
        low: ['low', 'low_price', '最低价'],
        close: ['close', 'close_price', 'price', '收盘价'],
        volume: ['volume', 'vol', '成交量'],
        amount: ['amount', '成交额'],
        change: ['change', 'pct_change', '涨跌幅']
      }
      // 逆向查找：为每个模板 key 找到 raw 中对应的原始 key
      const sample = rawList[0] || {}
      const keyMap = {}
      for (const tk of templateKeys) {
        const lower = String(tk).toLowerCase()
        const aliases = ALIAS[lower] || [tk]
        const found = aliases.find(a => Object.prototype.hasOwnProperty.call(sample, a))
        if (found) keyMap[tk] = found
        else if (Object.prototype.hasOwnProperty.call(sample, tk)) keyMap[tk] = tk
      }
      // 按模板顺序重建每行
      return rawList.map(row => {
        const o = {}
        for (const tk of templateKeys) {
          const sourceKey = keyMap[tk]
          o[tk] = sourceKey ? row[sourceKey] : (row[tk] != null ? row[tk] : null)
        }
        return o
      })
    },

    /**
     * 点击回测策略芯片时触发
     */
    handleBacktestClick(bt) {
      this.$emit('backtest-click', bt)
    },

    /**
     * CSV 单元格转义：含逗号/双引号/换行的内容用双引号包裹，内部双引号转义为 ""
     */
    escapeCsvCell(value) {
      const text = value == null ? '' : String(value)
      if (/[",\n\r]/.test(text)) {
        return '"' + text.replace(/"/g, '""') + '"'
      }
      return text
    },

    /**
     * 将当前结构化表格导出为 CSV 文件并下载
     * 列顺序、表头、单元格格式与界面展示保持一致
     */
    exportCsv() {
      try {
        if (!this.records || !this.records.length) {
          this.$message && this.$message.warning('暂无可导出的数据')
          return
        }
        const cols = this.columns
        if (!cols.length) {
          this.$message && this.$message.warning('暂无可导出的列')
          return
        }
        const header = cols.map(c => this.escapeCsvCell(c.label)).join(',')
        const rows = this.sortedData.map(row =>
          cols.map(col => this.escapeCsvCell(this.formatCell(row[col.prop], col))).join(',')
        )
        const csvContent = '\uFEFF' + [header, ...rows].join('\n') // BOM 保证 Excel 中文兼容
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        const fileTag = this.stepKey || 'table'
        a.download = `${fileTag}_export_${Date.now()}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        this.$message && this.$message.success('表格已导出')
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error('[ChatDataTable] 导出失败:', e)
        this.$message && this.$message.error('导出失败，请稍后重试')
      }
    }
  }
}
</script>

<style scoped>
.chat-data-table {
  margin-top: 12px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.table-header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #fafbfc;
  border-bottom: 1px solid #ebeef5;
  font-size: 13px;
  color: #606266;
  gap: 12px;
  flex-wrap: wrap;
}

.table-summary {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #303133;
  font-weight: 500;
}

.table-record-count {
  flex-shrink: 0;
  color: #909399;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.table-record-count i {
  font-size: 14px;
}

.table-step-tag {
  display: inline-block;
  padding: 0 6px;
  margin-left: 4px;
  font-size: 11px;
  background: #ecf5ff;
  color: #409EFF;
  border-radius: 3px;
  line-height: 18px;
}

.cell-number {
  font-variant-numeric: tabular-nums;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 12px;
}

/* 包含内联 Markdown 的单元格：strong/em/code/del 依靠默认样式即可，仅微调 code 背景 */
.cell-md {
  display: inline;
  white-space: normal;
}
.cell-md strong {
  font-weight: 600;
  color: #303133;
}
.cell-md em {
  font-style: italic;
  color: #606266;
}
.cell-md code {
  background: #f5f7fa;
  padding: 1px 4px;
  border-radius: 3px;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 12px;
}
.cell-md del {
  color: #909399;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 8px 16px;
  border-top: 1px solid #ebeef5;
  background: #fafbfc;
}

.table-export-btn {
  flex-shrink: 0;
  padding: 2px 8px;
  font-size: 12px;
  color: #409eff;
  background: transparent;
  border: 1px solid #409eff;
  border-radius: 3px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  transition: background 0.2s;
}

.table-export-btn:hover {
  background: #ecf5ff;
}

.table-export-btn i {
  font-size: 12px;
}

/* 「加载完整数据」按钮：后端缩略场景下一键补拉区间全量数据 */
.table-load-full-btn {
  flex-shrink: 0;
  padding: 2px 8px;
  font-size: 12px;
  color: #e6a23c;
  background: #fdf6ec;
  border: 1px solid #f5dab1;
  border-radius: 3px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  transition: all 0.2s;
}
.table-load-full-btn:hover:not(:disabled) {
  color: #fff;
  background: #e6a23c;
  border-color: #e6a23c;
}
.table-load-full-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.table-load-full-btn i {
  font-size: 12px;
}

.table-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.table-toggle-btn {
  flex-shrink: 0;
  padding: 2px 8px;
  font-size: 12px;
  color: #606266;
  background: transparent;
  border: 1px solid #dcdfe6;
  border-radius: 3px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  transition: all 0.2s;
}

.table-toggle-btn:hover {
  color: #409eff;
  border-color: #409eff;
  background: #ecf5ff;
}

.table-toggle-btn i {
  font-size: 12px;
}

.table-preview-tip {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  font-size: 11px;
  color: #e6a23c;
  background: #fdf6ec;
  border-radius: 3px;
  line-height: 18px;
}

.table-filter-tip {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  font-size: 11px;
  color: #67c23a;
  background: #f0f9eb;
  border-radius: 3px;
  line-height: 18px;
}

.table-search-input {
  flex-shrink: 0;
  width: 160px;
  height: 24px;
  padding: 0 8px;
  font-size: 12px;
  color: #303133;
  border: 1px solid #dcdfe6;
  border-radius: 3px;
  outline: none;
  background: #fff;
  transition: border-color 0.2s;
}

.table-search-input:focus {
  border-color: #409eff;
}

.table-search-input::placeholder {
  color: #c0c4cc;
}

/* 可追踪资产单元格交互样式 */
.traceable-asset-cell {
  color: #409EFF;
  cursor: pointer;
  border-bottom: 1px dashed #409EFF;
  padding-bottom: 1px;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.traceable-asset-cell:hover {
  color: #66b1ff;
  border-bottom-color: #66b1ff;
  background: rgba(64, 158, 255, 0.06);
  border-radius: 2px;
}

.traceable-asset-icon {
  font-size: 12px;
  opacity: 0.7;
}

/* 涉及资产芯片区 */
.traceable-assets-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: #f5faff;
  border-bottom: 1px solid #ebeef5;
  font-size: 12px;
}

.traceable-assets-label {
  color: #606266;
  font-weight: 500;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.traceable-assets-label .el-icon-data-analysis {
  color: #409EFF;
}

.asset-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  background: #fff;
  border: 1px solid #d9ecff;
  border-radius: 12px;
  color: #409EFF;
  cursor: pointer;
  transition: all 0.18s;
  line-height: 18px;
  user-select: none;
}

.asset-chip:hover {
  background: #ecf5ff;
  border-color: #409EFF;
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.18);
}

.asset-chip-no-kline {
  color: #909399;
  border-color: #e4e7ed;
  background: #fafafa;
}

.asset-chip-no-kline:hover {
  border-color: #c0c4cc;
  box-shadow: none;
}

.asset-chip-code {
  font-weight: 600;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
}

.asset-chip-sep {
  color: #c0c4cc;
}

.asset-chip-name {
  color: #303133;
  font-size: 12px;
}

.asset-chip-no-kline .asset-chip-name {
  color: #909399;
}

.asset-chip-icon {
  font-size: 12px;
  opacity: 0.7;
  margin-left: 1px;
}

/* 不存在的资产：错误调灰调 */
.asset-chip-invalid {
  color: #c0c4cc !important;
  border-color: #f0f0f0 !important;
  background: #fafafa !important;
  cursor: not-allowed !important;
  text-decoration: line-through;
  text-decoration-color: #c0c4cc;
}
.asset-chip-invalid:hover {
  box-shadow: none !important;
  border-color: #f0f0f0 !important;
}
.asset-chip-invalid .asset-chip-name,
.asset-chip-invalid .asset-chip-code {
  color: #c0c4cc !important;
}

/* 代表/参考折叠展开按钮 */
.asset-chip-toggle {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  font-size: 12px;
  line-height: 18px;
  background: #f0f7ff;
  color: #409EFF;
  border: 1px dashed #a0cfff;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.18s;
}
.asset-chip-toggle:hover {
  background: #ecf5ff;
  border-style: solid;
}
.asset-chip-toggle-ref {
  background: #f4f4f5;
  color: #606266;
  border-color: #dcdfe6;
}
.asset-chip-toggle-ref:hover {
  background: #e9e9eb;
  color: #303133;
}

/* 参考资产区域：表现为一串小芯片，无 popover */
.asset-reference-block {
  /* 独占一行，与代表资产分开，保证布局清晰 */
  flex-basis: 100%;
  width: 100%;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 6px 4px;
  padding-top: 6px;
  margin-top: 4px;
  border-top: 1px dashed #ebeef5;
}
.asset-reference-list {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 8px;
  margin-left: 0;
  background: #fbfcfd;
  border-radius: 6px;
  flex: 1;
  min-width: 0;
}
.asset-chip-reference {
  background: #fafbfc;
  color: #606266;
  border-color: #ebeef5;
  font-size: 12px;
}
.asset-chip-reference .asset-chip-code {
  color: #606266;
  font-weight: 500;
}
.asset-chip-reference .asset-chip-name {
  color: #909399;
}
.asset-chip-reference:hover {
  background: #ecf5ff;
  border-color: #a0cfff;
  color: #409EFF;
  box-shadow: none;
}
.asset-chip-reference:hover .asset-chip-code,
.asset-chip-reference:hover .asset-chip-name {
  color: #409EFF;
}

/* 资产芯片悬停高亮起来，表示当前高亮的是哪个资产 */
.asset-chip-active {
  background: #ecf5ff !important;
  border-color: #409EFF !important;
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.18);
}
.asset-chip-reference.asset-chip-active {
  color: #409EFF !important;
}
.asset-chip-reference.asset-chip-active .asset-chip-code,
.asset-chip-reference.asset-chip-active .asset-chip-name {
  color: #409EFF !important;
}

/* el-table 资产行高亮：需使用 ::v-deep 穿透 scoped 到 element-ui 内部 */
.chat-data-table >>> .el-table__row.asset-row-highlight > td {
  background: #ecf5ff !important;
}
.chat-data-table >>> .el-table__row.asset-row-highlight:hover > td {
  background: #d9ecff !important;
}

/* 涉及策略芯片区 */
.traceable-backtests-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: #f5f8ff;
  border-bottom: 1px solid #ebeef5;
  font-size: 12px;
}

.backtest-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  background: #fff;
  border: 1px solid #b3d8ff;
  border-radius: 12px;
  color: #409EFF;
  cursor: pointer;
  transition: all 0.18s;
  line-height: 20px;
  user-select: none;
}

.backtest-chip:hover {
  background: #ecf5ff;
  border-color: #409EFF;
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.18);
}

.backtest-chip-name {
  font-weight: 600;
  font-size: 12px;
  color: #303133;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.backtest-chip-tag {
  flex-shrink: 0;
  transform: scale(0.85);
  margin-left: -2px;
}

.backtest-chip-icon {
  font-size: 12px;
  opacity: 0.7;
  color: #409EFF;
}

/* JOIN 左右表字段背景色区分 */
.cell-join-left {
  background: #e8f4fd;
  border-radius: 3px;
  padding: 1px 4px;
}
.cell-join-right {
  background: #e8f5e9;
  border-radius: 3px;
  padding: 1px 4px;
}
/* el-table td 级别背景（通过 cell-class-name 为整列 td 着色）*/
.chat-data-table >>> .el-table td.td-join-left {
  background: #f0f8ff !important;
}
.chat-data-table >>> .el-table td.td-join-right {
  background: #f0faf1 !important;
}
.chat-data-table >>> .el-table tr:hover td.td-join-left {
  background: #dceefb !important;
}
.chat-data-table >>> .el-table tr:hover td.td-join-right {
  background: #d8f0da !important;
}

/* JOIN 来源图例标签 */
.join-source-legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 8px;
}
.join-source-tag {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11px;
  border-radius: 3px;
  font-weight: 500;
  line-height: 16px;
}
.join-source-left {
  background: #e8f4fd;
  color: #1a5276;
  border: 1px solid #a9d4f5;
}
.join-source-right {
  background: #e8f5e9;
  color: #1b5e20;
  border: 1px solid #a5d6a7;
}
</style>
