<template>
  <div class="chat-data-table">
    <!-- 顶部信息栏 -->
    <div class="table-header-bar">
      <span v-if="summary" class="table-summary">{{ summary }}</span>
      <span class="table-record-count">
        <i class="el-icon-document"></i>
        共 {{ totalRecords }} 条记录
        <template v-if="stepKey">
          <span class="table-step-tag">{{ stepKey }}</span>
        </template>
      </span>
    </div>

    <!-- 表格 -->
    <el-table
      :data="pagedData"
      :max-height="360"
      border
      size="mini"
      @sort-change="handleSortChange"
      style="width: 100%"
      :header-cell-style="headerCellStyle"
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
        <template slot-scope="{ row }">
          <span :class="{ 'cell-number': col.type === 'number' }">
            {{ formatCell(row[col.prop], col) }}
          </span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div v-if="totalRecords > pageSize" class="table-pagination">
      <el-pagination
        small
        layout="prev, pager, next, total"
        :page-size="pageSize"
        :total="totalRecords"
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

export default {
  name: 'ChatDataTable',
  props: {
    records: { type: Array, required: true },
    summary: { type: String, default: '' },
    recordCount: { type: Number, default: 0 },
    dataShape: { type: String, default: 'table' },
    stepKey: { type: String, default: '' }
  },
  data() {
    return {
      currentPage: 1,
      pageSize: 20,
      sortProp: '',
      sortOrder: ''
    }
  },
  computed: {
    headerCellStyle() {
      return {
        background: '#f5f7fa',
        color: '#606266',
        fontWeight: '600',
        fontSize: '12px'
      }
    },

    totalRecords() {
      return this.recordCount || this.records.length
    },

    columns() {
      if (!this.records.length) return []
      const firstRow = this.records[0]
      const keys = Object.keys(firstRow)
      return keys.map(key => {
        const values = this.records.map(r => r[key])
        const colType = detectColumnType(values)
        const isPct = isPercentField(key)
        return {
          prop: key,
          label: COLUMN_LABEL_MAP[key] || key,
          type: colType,
          isPercent: isPct,
          align: colType === 'number' ? 'right' : 'left',
          minWidth: this.calcMinWidth(key, colType)
        }
      })
    },

    sortedData() {
      if (!this.sortProp || !this.sortOrder) return this.records
      const prop = this.sortProp
      const asc = this.sortOrder === 'ascending'
      return [...this.records].sort((a, b) => {
        const va = a[prop]
        const vb = b[prop]
        if (va == null) return 1
        if (vb == null) return -1
        if (typeof va === 'number' && typeof vb === 'number') {
          return asc ? va - vb : vb - va
        }
        return asc
          ? String(va).localeCompare(String(vb))
          : String(vb).localeCompare(String(va))
      })
    },

    pagedData() {
      const start = (this.currentPage - 1) * this.pageSize
      return this.sortedData.slice(start, start + this.pageSize)
    }
  },
  methods: {
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

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 8px 16px;
  border-top: 1px solid #ebeef5;
  background: #fafbfc;
}
</style>
