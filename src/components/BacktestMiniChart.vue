<template>
  <el-popover
    placement="top"
    trigger="hover"
    :width="300"
    popper-class="backtest-mini-chart-popover"
    :disabled="disabled || !hasWeightData"
    :open-delay="80"
    @show="renderChart"
  >
    <span slot="reference" class="backtest-mini-chart-ref">
      <slot></slot>
    </span>

    <div class="bt-mini-container">
      <!-- 标题栏 -->
      <div class="bt-mini-header">
        <span class="bt-mini-title">{{ strategyName || '策略' }}</span>
        <el-tag v-if="templateCode" size="mini" type="info" class="bt-mini-tag">{{ templateCode }}</el-tag>
      </div>

      <!-- 区间 -->
      <div v-if="dateRangeText" class="bt-mini-range">{{ dateRangeText }}</div>

      <!-- 权重变化迷你图 -->
      <div v-if="hasWeightData" ref="btMiniChart" class="bt-mini-canvas"></div>
      <div v-else class="bt-mini-empty">
        <i class="el-icon-warning-outline"></i> 暂无权重数据
      </div>

      <!-- 指标摘要行 -->
      <div v-if="hasMetrics" class="bt-mini-metrics">
        <span v-if="metrics.total_return != null" class="bt-metric-item">
          <span class="bt-metric-label">总收益</span>
          <span class="bt-metric-value" :style="{ color: getReturnColor(metrics.total_return) }">
            {{ formatPercent(metrics.total_return) }}
          </span>
        </span>
        <span v-if="metrics.sharpe_ratio != null" class="bt-metric-item">
          <span class="bt-metric-label">夏普</span>
          <span class="bt-metric-value">{{ formatNum(metrics.sharpe_ratio, 2) }}</span>
        </span>
        <span v-if="metrics.max_drawdown != null" class="bt-metric-item">
          <span class="bt-metric-label">最大回撤</span>
          <span class="bt-metric-value" style="color: #f56c6c;">{{ formatPercent(metrics.max_drawdown) }}</span>
        </span>
      </div>

      <!-- 底部提示 -->
      <div class="bt-mini-footer">
        <span class="bt-mini-hint">点击查看完整回测详情</span>
      </div>
    </div>
  </el-popover>
</template>

<script>
/**
 * BacktestMiniChart — 回测权重变化迷你图（悬停弹出）
 * 仿 AssetMiniChart 的 el-popover + slot 模式，展示堆叠面积图反映权重演变。
 */

import { createDateAxisLabelFormatter } from '@/utils/dateAxis'

// 调色板：最多 10 种资产配色
const WEIGHT_COLORS = [
  '#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399',
  '#00C9A7', '#845EC2', '#FF6F91', '#FFC75F', '#0081CF'
]

export default {
  name: 'BacktestMiniChart',
  props: {
    strategyName: { type: String, default: '' },
    templateCode: { type: String, default: '' },
    /** 核心指标：{ total_return, annual_return, max_drawdown, sharpe_ratio } */
    metrics: { type: Object, default: () => ({}) },
    /** 权重快照数组：[{ date, weights: { code: weight } }] */
    weightSnapshots: { type: Array, default: () => [] },
    disabled: { type: Boolean, default: false }
  },
  data() {
    return {
      chartInstance: null
    }
  },
  beforeDestroy() {
    if (this.chartInstance) {
      this.chartInstance.dispose()
      this.chartInstance = null
    }
  },
  computed: {
    hasWeightData() {
      return Array.isArray(this.weightSnapshots) && this.weightSnapshots.length > 0
    },
    hasMetrics() {
      return this.metrics && (
        this.metrics.total_return != null ||
        this.metrics.sharpe_ratio != null ||
        this.metrics.max_drawdown != null
      )
    },
    /** 降采样后的权重快照（最多 30 个点用于迷你图） */
    sampledSnapshots() {
      const snaps = this.weightSnapshots
      if (!snaps || snaps.length <= 30) return snaps || []
      const step = (snaps.length - 1) / 29
      const result = []
      for (let i = 0; i < 30; i++) {
        result.push(snaps[Math.round(i * step)])
      }
      return result
    },
    dateRangeText() {
      if (!this.hasWeightData) return ''
      const first = this.weightSnapshots[0]
      const last = this.weightSnapshots[this.weightSnapshots.length - 1]
      if (!first || !last) return ''
      const d1 = first.date || ''
      const d2 = last.date || ''
      if (!d1 || !d2) return ''
      if (d1 === d2) return d1
      return d1 + ' ~ ' + d2
    }
  },
  methods: {
    formatPercent(val) {
      if (val == null) return '-'
      const num = Number(val)
      if (isNaN(num)) return '-'
      // 若 abs < 1 视为小数比例，乘 100
      if (Math.abs(num) > 0 && Math.abs(num) < 1) {
        return (num * 100).toFixed(2) + '%'
      }
      return num.toFixed(2) + '%'
    },
    formatNum(val, digits) {
      if (val == null) return '-'
      const num = Number(val)
      if (isNaN(num)) return '-'
      return num.toFixed(digits || 2)
    },
    getReturnColor(val) {
      if (val == null) return '#909399'
      return Number(val) >= 0 ? '#67C23A' : '#F56C6C'
    },

    renderChart() {
      this.$nextTick(() => {
        if (!this.$refs.btMiniChart || !this.hasWeightData) return

        const echarts = this.$echarts
        if (!echarts) {
          console.warn('[BacktestMiniChart] ECharts 未全局注册')
          return
        }

        // 复用 / 初始化实例
        if (this.chartInstance && this.chartInstance.getDom() !== this.$refs.btMiniChart) {
          this.chartInstance.dispose()
          this.chartInstance = null
        }
        if (!this.chartInstance) {
          this.chartInstance = echarts.init(this.$refs.btMiniChart)
        } else {
          this.chartInstance.clear()
        }

        const snaps = this.sampledSnapshots
        if (!snaps.length) return

        // 收集所有资产 code
        const assetSet = new Set()
        for (const s of snaps) {
          if (s.weights) {
            for (const code of Object.keys(s.weights)) assetSet.add(code)
          }
        }
        const assetCodes = Array.from(assetSet)

        // 日期轴（保留完整日期，轴标签按跨度自适应显示年份）
        const dates = snaps.map(s => s.date || '')

        // 构建 series
        const series = assetCodes.map((code, idx) => ({
          name: code,
          type: 'line',
          stack: 'weight',
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 0 },
          areaStyle: {
            color: WEIGHT_COLORS[idx % WEIGHT_COLORS.length],
            opacity: 0.7
          },
          emphasis: { focus: 'series' },
          data: snaps.map(s => {
            const w = (s.weights && s.weights[code]) || 0
            // 权重值：若 < 1 直接使用，若 >= 1 视为百分比除以 100
            return w >= 1 ? w / 100 : w
          })
        }))

        const option = {
          grid: { top: 8, right: 8, bottom: 20, left: 8 },
          xAxis: {
            type: 'category',
            data: dates,
            boundaryGap: false,
            axisLabel: { fontSize: 9, color: '#999', interval: 'auto', formatter: createDateAxisLabelFormatter(dates) },
            axisLine: { show: false },
            axisTick: { show: false }
          },
          yAxis: {
            type: 'value',
            show: false,
            max: 1
          },
          tooltip: {
            trigger: 'axis',
            textStyle: { fontSize: 10 },
            confine: true,
            formatter: (params) => {
              let tip = params[0].axisValue + '<br/>'
              for (const p of params) {
                if (p.value > 0) {
                  const color = p.color || '#333'
                  tip += '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'
                    + color + ';margin-right:4px;"></span>'
                    + p.seriesName + ': ' + (p.value * 100).toFixed(1) + '%<br/>'
                }
              }
              return tip
            }
          },
          series
        }

        this.chartInstance.setOption(option)
      })
    }
  }
}
</script>

<style scoped>
.bt-mini-container {
  padding: 4px 0;
}

.bt-mini-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.bt-mini-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

.bt-mini-tag {
  flex-shrink: 0;
}

.bt-mini-range {
  font-size: 11px;
  color: #909399;
  margin-bottom: 6px;
  font-variant-numeric: tabular-nums;
}

.bt-mini-canvas {
  width: 280px;
  height: 120px;
}

.bt-mini-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 80px;
  font-size: 12px;
  color: #909399;
  gap: 4px;
}

.bt-mini-metrics {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 0 2px;
  border-top: 1px solid #f0f0f0;
  margin-top: 4px;
}

.bt-metric-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.bt-metric-label {
  font-size: 10px;
  color: #909399;
  line-height: 14px;
}

.bt-metric-value {
  font-size: 12px;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
  line-height: 18px;
}

.bt-mini-footer {
  text-align: center;
  margin-top: 4px;
}

.bt-mini-hint {
  font-size: 11px;
  color: #409EFF;
  cursor: pointer;
}
</style>

<!-- 非scoped: popover被append-to-body，需要全局样式 -->
<style>
.backtest-mini-chart-popover {
  z-index: 3000 !important;
  padding: 8px 12px;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}
</style>
