<template>
  <div class="lineage-graph-container" ref="chartContainer"></div>
</template>

<script>
import * as echarts from 'echarts'

// 域颜色映射
const DOMAIN_COLORS = {
  asset: '#409EFF',
  subject: '#67C23A',
  product: '#E6A23C',
  valuation: '#909399',
  transaction: '#F56C6C',
  seller: '#b37feb',
  customer: '#36cfc9',
  risk: '#ff4d4f',
  market: '#1890ff',
  data_hub: '#722ed1'
}

const DOMAIN_NAMES = {
  asset: '资产域',
  subject: '主体域',
  product: '产品域',
  valuation: '估值域',
  transaction: '交易域',
  seller: '销售域',
  customer: '客户域',
  risk: '风险域',
  market: '行情域',
  data_hub: '数据接入域'
}

// 表名前缀→域映射（用于node.domain缺失时的推断兜底）
const DOMAIN_PREFIX_MAP = {
  'dwd_ast_': 'asset',
  'dwd_isr_': 'subject',
  'dwd_ptl_': 'product',
  'dwd_val_': 'valuation',
  'dwd_trn_': 'transaction',
  'dwd_sale_': 'seller',
  'dwd_cust_': 'customer',
  'dwd_rsk_': 'risk',
  'dwd_mkt_': 'market',
  'subject_risk_': 'data_hub',
  'zysc_ptl_': 'data_hub'
}

function inferDomain(nodeId) {
  if (!nodeId) return 'unknown'
  // 组合管理系统资产表显式映射
  if (nodeId === 'assets' || nodeId === 'asset_prices') return 'asset'
  for (const [prefix, domain] of Object.entries(DOMAIN_PREFIX_MAP)) {
    if (nodeId.startsWith(prefix)) return domain
  }
  return 'unknown'
}

export default {
  name: 'LineageGraph',
  props: {
    nodes: { type: Array, default: () => [] },
    edges: { type: Array, default: () => [] },
    highlightTables: { type: Array, default: () => [] },
    focusDomain: { type: String, default: '' }
  },
  data() {
    return {
      chart: null,
      nodePositionCache: {}  // nodeId -> { x, y }，缓存力布局稳定后的节点位置
    }
  },
  mounted() {
    this.initChart()
    window.addEventListener('resize', this.handleResize)
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.handleResize)
    if (this.chart) {
      this.chart.dispose()
    }
  },
  watch: {
    nodes() { this.updateChart() },
    edges() { this.updateChart() },
    highlightTables() { this.updateChart() },
    focusDomain(newVal, oldVal) {
      // 确保focusDomain变化时一定触发图表更新
      if (newVal !== oldVal) {
        this.$nextTick(() => { this.updateChart() })
      }
    }
  },
  methods: {
    initChart() {
      this.chart = echarts.init(this.$refs.chartContainer)

      // 监听力布局完成事件，缓存节点位置
      this.chart.on('finished', () => {
        if (!this.chart) return
        const opt = this.chart.getOption()
        if (opt && opt.series && opt.series[0] && opt.series[0].data) {
          const cache = {}
          opt.series[0].data.forEach(node => {
            if (node.x != null && node.y != null) {
              cache[node.id] = { x: node.x, y: node.y }
            }
          })
          if (Object.keys(cache).length > 0) {
            this.nodePositionCache = cache
          }
        }
      })

      this.chart.on('click', (params) => {
        if (params.dataType === 'node') {
          this.$emit('node-click', params.data.id)
        }
        if (params.dataType === 'edge') {
          const d = params.data._edgeData
          if (d) {
            this.$emit('edge-click', {
              source: d.source,
              target: d.target,
              source_display: d.source_display,
              target_display: d.target_display,
              relation_desc: d.relation_desc,
              source_field: d.source_field,
              target_field: d.target_field,
              field_display: d.field_display,
              target_field_display: d.target_field_display
            })
          }
        }
      })
      this.updateChart()
    },
    updateChart() {
      if (!this.chart) return

      const categories = Object.keys(DOMAIN_COLORS).map(code => ({
        name: DOMAIN_NAMES[code] || code
      }))

      const categoryIndex = Object.keys(DOMAIN_COLORS)

      // 构建节点域映射（优先用node.domain，缺失时从表名前缀推断）
      const getNodeDomain = (node) => node.domain || node.category || inferDomain(node.id)
      const nodeIdToDomain = {}
      this.nodes.forEach(n => { nodeIdToDomain[n.id] = getNodeDomain(n) })

      const hasFocus = !!(this.focusDomain && this.focusDomain.length > 0)

      const chartNodes = this.nodes.map(node => {
        const isHighlight = this.highlightTables.includes(node.id)
        const nodeDomain = getNodeDomain(node)
        const isFocused = hasFocus && nodeDomain === this.focusDomain
        const isFaded = hasFocus && nodeDomain !== this.focusDomain

        let symbolSize = isHighlight ? 45 : 30
        let itemStyle = isHighlight ? {
          borderColor: '#ff4d4f',
          borderWidth: 3,
          shadowBlur: 10,
          shadowColor: 'rgba(255,77,79,0.4)'
        } : {}
        let label = { show: true, fontSize: isHighlight ? 11 : 9 }

        if (isFocused) {
          symbolSize = 40
          const domainColor = DOMAIN_COLORS[nodeDomain] || '#409EFF'
          itemStyle = {
            color: domainColor,
            borderWidth: 3,
            borderColor: domainColor,
            shadowBlur: 12,
            shadowColor: domainColor,
            opacity: 1
          }
          label = { show: true, fontSize: 10, color: '#333' }
        } else if (isFaded) {
          symbolSize = 24
          const fadedColor = DOMAIN_COLORS[nodeDomain] || '#999'
          itemStyle = {
            color: fadedColor,
            borderColor: '#ddd',
            borderWidth: 1,
            opacity: 0.3
          }
          label = { show: true, fontSize: 8, color: '#bbb' }
        }

        // 复用缓存的节点位置，避免力布局重算导致节点跳位置和边标签布局错误
        const cached = this.nodePositionCache[node.id]
        const nodeObj = {
          id: node.id,
          name: node.name || node.id,
          category: categoryIndex.indexOf(nodeDomain),
          symbolSize,
          itemStyle,
          label
        }
        if (cached) {
          nodeObj.x = cached.x
          nodeObj.y = cached.y
        }
        return nodeObj
      })

      // 计算同源-同目标之间的平行边数量，用于分配不同 curveness
      const edgePairCount = {}
      const edgePairIndex = {}
      this.edges.forEach(edge => {
        const pairKey = [edge.source, edge.target].sort().join('||')
        edgePairCount[pairKey] = (edgePairCount[pairKey] || 0) + 1
      })
      const edgePairCurrent = {}

      const chartEdges = this.edges.map(edge => {
        const srcDomain = nodeIdToDomain[edge.source]
        const tgtDomain = nodeIdToDomain[edge.target]
        const edgeRelated = hasFocus && (srcDomain === this.focusDomain || tgtDomain === this.focusDomain)
        const edgeFaded = hasFocus && !edgeRelated

        // 平行边 curveness 分配：避免重叠
        const pairKey = [edge.source, edge.target].sort().join('||')
        const total = edgePairCount[pairKey] || 1
        edgePairCurrent[pairKey] = (edgePairCurrent[pairKey] || 0)
        const idx = edgePairCurrent[pairKey]++
        let curveness = 0.15
        if (total > 1) {
          const spread = 0.12
          curveness = 0.05 + spread * (idx - (total - 1) / 2)
        }

        let lineStyle = {
          type: edge.type === 'foreign_key' ? 'solid' : 'dashed',
          curveness
        }

        // 边上显示语义标签：中英双语 + 截断
        const fieldEn = edge.source_field || edge.label || ''
        const fieldZh = edge.field_display || ''
        // 构建双语标签：优先「中文(英文)」，回退纯英文
        let bilingualLabel = ''
        if (fieldZh && fieldZh !== fieldEn) {
          bilingualLabel = `${fieldZh}(${fieldEn})`
        } else {
          bilingualLabel = fieldEn
        }
        // 超长截断
        const maxLen = 16
        const shortLabel = bilingualLabel.length > maxLen
          ? bilingualLabel.slice(0, maxLen - 1) + '…'
          : bilingualLabel
        let edgeLabel = { show: false, formatter: '' }

        if (edgeRelated) {
          lineStyle.width = 2.5
          lineStyle.opacity = 1
          // 聚焦边：显示字段中文名，带圆角背景
          edgeLabel = {
            show: true,
            formatter: shortLabel,
            fontSize: 10,
            fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif',
            color: '#555',
            backgroundColor: 'rgba(255,255,255,0.92)',
            borderColor: 'rgba(0,0,0,0.06)',
            borderWidth: 1,
            padding: [3, 6],
            borderRadius: 4,
            distance: 8
          }
        } else if (edgeFaded) {
          lineStyle.opacity = 0.1
          lineStyle.width = 1
        } else {
          // 非聚焦模式：悬停 tooltip 展示
          lineStyle.width = 1.5
        }

        return {
          source: edge.source,
          target: edge.target,
          label: edgeLabel,
          _edgeData: edge,
          lineStyle
        }
      })

      const option = {
        tooltip: {
          trigger: 'item',
          formatter: (params) => {
            if (params.dataType === 'node') {
              const domainName = DOMAIN_NAMES[this.nodes.find(n => n.id === params.data.id)?.domain] || ''
              const domainTag = domainName ? `<span style="color:#999;font-size:11px">${domainName}</span><br/>` : ''
              return `${domainTag}<b>${params.data.name}</b><br/><span style="color:#999">${params.data.id}</span>`
            }
            if (params.dataType === 'edge') {
              const d = params.data._edgeData || {}
              const lines = []
              // 标题：表名关联方向
              lines.push(`<b style="color:#333;font-size:13px">${d.source_display || d.source} → ${d.target_display || d.target}</b>`)
              // 关系描述
              if (d.relation_desc) {
                lines.push(`<br/><span style="color:#555">${d.relation_desc}</span>`)
              }
              // 字段详情区：英文名 + 中文名 + 含义定义
              const srcField = d.source_field || d.label || ''
              const tgtField = d.target_field || ''
              const srcZh = d.field_display || ''
              const tgtZh = d.target_field_display || ''
              const srcDef = d.field_definition || ''
              const tgtDef = d.target_field_definition || ''
              // 源字段
              if (srcField) {
                const srcNamePart = srcZh && srcZh !== srcField ? `${srcZh} <span style="color:#999">(${srcField})</span>` : srcField
                lines.push(`<br/><span style="margin-top:4px;display:inline-block;padding:2px 6px;background:#f5f7fa;border-radius:3px;font-size:11px">`)
                lines.push(`🔑 源字段：${srcNamePart}`)
                if (srcDef) lines.push(`<br/><span style="color:#888;font-size:11px">&nbsp;&nbsp;${srcDef}</span>`)
                lines.push(`</span>`)
              }
              // 目标字段
              if (tgtField) {
                const tgtNamePart = tgtZh && tgtZh !== tgtField ? `${tgtZh} <span style="color:#999">(${tgtField})</span>` : tgtField
                lines.push(`<br/><span style="display:inline-block;padding:2px 6px;background:#f0f9eb;border-radius:3px;font-size:11px">`)
                lines.push(`🎯 目标字段：${tgtNamePart}`)
                if (tgtDef) lines.push(`<br/><span style="color:#888;font-size:11px">&nbsp;&nbsp;${tgtDef}</span>`)
                lines.push(`</span>`)
              }
              return lines.join('')
            }
            return ''
          }
        },
        legend: {
          data: categories.map(c => c.name),
          orient: 'horizontal',
          top: 0,
          textStyle: { fontSize: 11 }
        },
        series: [{
          type: 'graph',
          layout: 'force',
          data: chartNodes,
          links: chartEdges,
          categories: categories,
          roam: true,
          draggable: true,
          force: {
            repulsion: 500,
            edgeLength: [130, 300],
            gravity: 0.06,
            friction: 0.65
          },
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: [0, 8],
          emphasis: {
            focus: 'adjacency',
            lineStyle: { width: 3.5 },
            label: { fontSize: 12 }
          },
          lineStyle: {
            color: '#b0b0b0',
            width: 1.5,
            opacity: 0.65
          },
          label: {
            show: true,
            position: 'bottom',
            fontSize: 10,
            fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif',
            color: '#444',
            backgroundColor: 'rgba(255,255,255,0.75)',
            padding: [2, 4],
            borderRadius: 3,
            distance: 5
          },
          // ECharts 5+ 自动隐藏重叠标签
          labelLayout: {
            hideOverlap: true
          },
          animationDuration: 800,
          animationEasingUpdate: 'quinticInOut'
        }],
        color: Object.values(DOMAIN_COLORS)
      }

      this.chart.setOption(option, true)
    },
    handleResize() {
      if (this.chart) this.chart.resize()
    }
  }
}
</script>

<style scoped>
.lineage-graph-container {
  width: 100%;
  height: 100%;
  min-height: 500px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  background: #fff;
}
</style>
