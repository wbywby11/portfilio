<template>
  <div class="message-charts">
    <div
      v-for="(chart, cIdx) in charts"
      :key="refPrefix + '_' + cIdx"
      :class="['message-chart-wrapper', getChartSizeClass(chart)]"
    >
      <div class="message-chart-title" v-if="chart.title">{{ chart.title }}</div>
      <div
        :ref="refPrefix + '_' + cIdx"
        class="message-chart"
        :style="{ width: '100%', height: getChartHeight(chart) }"
      >
        <!-- 图表加载骨架屏 -->
        <div class="chart-skeleton" v-if="!isChartRendered(refPrefix + '_' + cIdx)">
          <div class="skeleton-shimmer"></div>
          <i class="el-icon-data-line skeleton-icon"></i>
          <span class="skeleton-text">图表加载中...</span>
        </div>
      </div>
      <!-- 图表渲染失败 fallback -->
      <div class="chart-error-fallback" v-if="isChartError(refPrefix + '_' + cIdx)">
        <i class="el-icon-warning-outline"></i>
        <span>图表渲染失败</span>
      </div>
    </div>
  </div>
</template>

<script>
// 统一调色板：与 Element-UI 主调友好，高对比但不刺眼
const CHAT_CHART_PALETTE = [
  '#5B8FF9', '#5AD8A6', '#F6BD16', '#E8684A', '#6DC8EC',
  '#9270CA', '#FF9D4D', '#269A99', '#FF99C3', '#5D7092'
]

/**
 * 对后端下发的 echarts_option 做一次「可视化与交互增强」：
 * - tooltip 加 confine，避免遮挡轴/柱子；半透明柔化背景
 * - legend 默认放顶部、横向滚动，避免名称占据多行
 * - xAxis 过密时自动 rotate，并留出足够的 grid.bottom
 * - line：去掉 marker 点、圈选高亮当前系列
 * - bar：合理 barGap、圆角顶部
 * - title：顶部与轴不重叠
 * - color：未设置时使用统一调色板
 */
function enhanceEchartsOption(rawOption, chartType, containerWidth) {
  if (!rawOption || typeof rawOption !== 'object') return rawOption
  // 深拷贝，避免污染后端返回的原始对象
  let option
  try { option = JSON.parse(JSON.stringify(rawOption)) } catch (e) { option = Object.assign({}, rawOption) }

  // 1) 调色板
  if (!option.color || (Array.isArray(option.color) && option.color.length === 0)) {
    option.color = CHAT_CHART_PALETTE
  }

  // 2) 标题：顶部与轴不重叠
  if (option.title) {
    const titles = Array.isArray(option.title) ? option.title : [option.title]
    titles.forEach(t => {
      if (!t || typeof t !== 'object') return
      if (t.left == null) t.left = 12
      if (t.top == null) t.top = 8
      t.textStyle = Object.assign({ fontSize: 14, fontWeight: 600, color: '#303133' }, t.textStyle || {})
      if (t.subtextStyle) {
        t.subtextStyle = Object.assign({ fontSize: 12, color: '#909399' }, t.subtextStyle)
      }
    })
  }

  // 3) tooltip 优化：confine + 柔和背景 + 跨轴十字线
  const trigger = (rawOption.tooltip && rawOption.tooltip.trigger)
    || (chartType === 'pie' ? 'item' : 'axis')
  option.tooltip = Object.assign({
    trigger,
    confine: true,
    backgroundColor: 'rgba(255, 255, 255, 0.96)',
    borderColor: '#e4e7ed',
    borderWidth: 1,
    padding: [8, 12],
    extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.12); border-radius: 6px;',
    textStyle: { color: '#303133', fontSize: 12 }
  }, option.tooltip || {})
  if (trigger === 'axis') {
    option.tooltip.axisPointer = Object.assign({
      type: 'cross',
      lineStyle: { color: '#c0c4cc', width: 1, type: 'dashed' },
      crossStyle: { color: '#c0c4cc', width: 1, type: 'dashed' },
      label: { backgroundColor: '#606266' }
    }, option.tooltip.axisPointer || {})
  }

  // 4) legend 优化：顶部中间、滚动、不奌下方轴
  const legendsRaw = option.legend
    ? (Array.isArray(option.legend) ? option.legend : [option.legend])
    : []
  const seriesArr = Array.isArray(option.series) ? option.series : (option.series ? [option.series] : [])
  const seriesCount = seriesArr.length
  // 推荐默认 legend
  const defaultLegend = {
    type: 'scroll',
    top: option.title ? 32 : 8,
    left: 'center',
    right: 40,
    icon: 'roundRect',
    itemWidth: 12,
    itemHeight: 8,
    itemGap: 14,
    textStyle: { color: '#606266', fontSize: 12 },
    pageIconColor: '#909399',
    pageIconInactiveColor: '#dcdfe6',
    pageTextStyle: { color: '#909399', fontSize: 11 }
  }
  if (!legendsRaw.length && seriesCount > 1) {
    option.legend = defaultLegend
  } else if (legendsRaw.length) {
    legendsRaw.forEach(lg => {
      if (!lg || typeof lg !== 'object') return
      // 转换为顶部滚动，避免与 xAxis 标签重叠
      if (lg.bottom != null && lg.top == null) {
        delete lg.bottom
      }
      if (lg.top == null) lg.top = option.title ? 32 : 8
      if (lg.type == null) lg.type = 'scroll'
      if (lg.left == null) lg.left = 'center'
      if (lg.icon == null) lg.icon = 'roundRect'
      if (lg.itemWidth == null) lg.itemWidth = 12
      if (lg.itemHeight == null) lg.itemHeight = 8
      if (lg.itemGap == null) lg.itemGap = 14
      lg.textStyle = Object.assign({ color: '#606266', fontSize: 12 }, lg.textStyle || {})
      lg.pageIconColor = lg.pageIconColor || '#909399'
      lg.pageIconInactiveColor = lg.pageIconInactiveColor || '#dcdfe6'
      lg.pageTextStyle = Object.assign({ color: '#909399', fontSize: 11 }, lg.pageTextStyle || {})
    })
  }

  // 5) grid：为顶部 title+legend 与底部标签留足够空间
  const hasLegend = (Array.isArray(option.legend) ? option.legend.length : !!option.legend)
  const topPad = (option.title ? 56 : 32) + (hasLegend ? 4 : 0)
  const grids = option.grid
    ? (Array.isArray(option.grid) ? option.grid : [option.grid])
    : [{}]

  // 6) xAxis 过密标签优化（需在 grid.bottom 计算前完成，才能推出准确高度）
  const xAxes = option.xAxis
    ? (Array.isArray(option.xAxis) ? option.xAxis : [option.xAxis])
    : []
  // 记录所有 xAxis 中「旋转后指令要求」的最大底部预留，后面 grid.bottom 取这个与默认值的最大值
  let xLabelBottomNeed = 0
  // 最大可接受的单标签宽度（px）：超出会被 echarts 截断为 ...
  const MAX_LABEL_WIDTH = 120
  xAxes.forEach(xa => {
    if (!xa || typeof xa !== 'object') return
    xa.axisLine = Object.assign({ lineStyle: { color: '#dcdfe6' } }, xa.axisLine || {})
    xa.axisTick = Object.assign({ alignWithLabel: true, lineStyle: { color: '#dcdfe6' } }, xa.axisTick || {})
    const dataArr = Array.isArray(xa.data) ? xa.data : []
    const dataLen = dataArr.length
    // 计算标签原始需要的渲染宽度（估算）
    let maxChars = 0
    for (const d of dataArr) {
      const s = (d && d.value != null ? d.value : d)
      const len = (s == null) ? 0 : String(s).length
      if (len > maxChars) maxChars = len
    }
    // 中文 / 字母混排，取 7px/char 估算原始宽
    const rawWidthEstimate = maxChars * 7
    const labelWidth = Math.min(MAX_LABEL_WIDTH, Math.max(40, rawWidthEstimate))

    xa.axisLabel = Object.assign({
      color: '#606266',
      fontSize: 11,
      hideOverlap: true,
      margin: 12,
      // 关键：使用 echarts 原生「宽度限制+截断」避免超长标签占据过多底部空间
      // 仅在需要倾斜/数据量大时才设置 width+truncate，避免少量条目时误截断
      width: dataLen > 6 || maxChars > 12 ? labelWidth : undefined,
      overflow: dataLen > 6 || maxChars > 12 ? 'truncate' : undefined,
      ellipsis: dataLen > 6 || maxChars > 12 ? '...' : undefined
    }, xa.axisLabel || {})
    // 根据数据量与可用宽度自动 rotate
    // 策略：优先水平排（rotate=0），只有在水平排不下才倾斜。
    // 重要：即使后端显式设了 rotate（例如默认 35°），只要水平能排下也强制改为 0。
    {
      // 优先使用实测容器宽度；fallback 1200
      const containerW = (containerWidth && containerWidth > 200) ? containerWidth : 1200
      const gridLeft = 48
      const gridRight = 24
      const availableW = containerW - gridLeft - gridRight
      // 标签水平间隔 ≈ 40px（itemGap 默认）
      const itemGap = 40
      // 水平排列所需宽度，按实际原始宽度估算（不受 labelWidth 限制）
      const rawLabelW = Math.max(40, rawWidthEstimate)
      const horizontalW = dataLen <= 1 ? rawLabelW + gridLeft + gridRight : dataLen * rawLabelW + (dataLen - 1) * itemGap
      if (horizontalW <= availableW) {
        // 完全排得下：强制水平排（覆盖后端可能设的 rotate）
        xa.axisLabel.rotate = 0
      } else if (xa.axisLabel.rotate == null) {
        // 后端未设置且水平排不下：按量递增倾斜
        if (dataLen > 12 || maxChars > 12) {
          xa.axisLabel.rotate = 35
        } else if (dataLen > 6 || maxChars > 8) {
          xa.axisLabel.rotate = 20
        } else {
          // 少量条目但标签太长：尝试 15-45°
          let found = false
          for (const angle of [15, 20, 25, 30, 35, 40, 45]) {
            const rad = angle * Math.PI / 180
            const projectedW = dataLen * itemGap + labelWidth * Math.cos(rad)
            if (projectedW <= availableW) {
              xa.axisLabel.rotate = angle
              found = true
              break
            }
          }
          if (!found) xa.axisLabel.rotate = 45
        }
      }
      // 否则保留后端原始 rotate
    }
    if (xa.axisLabel.interval == null && dataLen > 30) {
      xa.axisLabel.interval = 'auto'
    }
    xa.splitLine = xa.splitLine || { show: false }

    // 根据旋转角 + 标签宽度推算需要的底部高度
    const rotate = Number(xa.axisLabel.rotate) || 0
    if (rotate > 0) {
      const rad = rotate * Math.PI / 180
      // 旋转后垂直高度 = labelWidth * sin(rad) + 轴刻度与边距
      const projected = Math.ceil(labelWidth * Math.sin(rad)) + 28
      if (projected > xLabelBottomNeed) xLabelBottomNeed = projected
    } else if (maxChars > 0) {
      // 不旋转也需预留 fontSize 标签高度 + tick + 边距
      if (xLabelBottomNeed < 36) xLabelBottomNeed = 36
    }
  })
  if (xAxes.length) option.xAxis = Array.isArray(option.xAxis) ? xAxes : xAxes[0]

  // 现在才设置 grid.bottom，根据上面推算的预留高度取默认 56 与推算值的最大值
  const baseBottom = Math.max(56, xLabelBottomNeed)
  grids.forEach(g => {
    if (!g || typeof g !== 'object') return
    if (g.top == null) g.top = topPad
    if (g.left == null) g.left = 48
    if (g.right == null) g.right = 24
    if (g.bottom == null) g.bottom = baseBottom
    else if (typeof g.bottom === 'number' && g.bottom < baseBottom) g.bottom = baseBottom
    if (g.containLabel == null) g.containLabel = true
  })
  option.grid = Array.isArray(option.grid) ? grids : grids[0]

  // 7) yAxis
  const yAxes = option.yAxis
    ? (Array.isArray(option.yAxis) ? option.yAxis : [option.yAxis])
    : []
  yAxes.forEach(ya => {
    if (!ya || typeof ya !== 'object') return
    ya.axisLabel = Object.assign({ color: '#606266', fontSize: 11 }, ya.axisLabel || {})
    ya.axisLine = Object.assign({ show: false }, ya.axisLine || {})
    ya.axisTick = Object.assign({ show: false }, ya.axisTick || {})
    ya.splitLine = Object.assign({ lineStyle: { color: '#f0f2f5', type: 'dashed' } }, ya.splitLine || {})
    if (ya.nameTextStyle) {
      ya.nameTextStyle = Object.assign({ color: '#909399', fontSize: 11, padding: [0, 0, 6, 0] }, ya.nameTextStyle)
    } else if (ya.name) {
      ya.nameTextStyle = { color: '#909399', fontSize: 11, padding: [0, 0, 6, 0] }
    }
  })
  if (yAxes.length) option.yAxis = Array.isArray(option.yAxis) ? yAxes : yAxes[0]

  // 8) series 优化
  seriesArr.forEach(s => {
    if (!s || typeof s !== 'object') return
    if (s.type === 'line') {
      if (s.smooth == null) s.smooth = false
      if (s.symbol == null) s.symbol = 'none'
      if (s.symbolSize == null) s.symbolSize = 6
      if (s.showSymbol == null) s.showSymbol = false
      s.lineStyle = Object.assign({ width: 1.6 }, s.lineStyle || {})
      s.emphasis = Object.assign({
        focus: 'series',
        lineStyle: { width: 2.4 }
      }, s.emphasis || {})
    } else if (s.type === 'bar') {
      if (s.barMaxWidth == null) s.barMaxWidth = 24
      s.itemStyle = Object.assign({ borderRadius: [3, 3, 0, 0] }, s.itemStyle || {})
      s.emphasis = Object.assign({ focus: 'series' }, s.emphasis || {})
    } else if (s.type === 'pie') {
      if (s.radius == null) s.radius = ['38%', '66%']
      if (s.center == null) s.center = ['50%', '56%']
      if (s.avoidLabelOverlap == null) s.avoidLabelOverlap = true
      s.itemStyle = Object.assign({ borderColor: '#fff', borderWidth: 1 }, s.itemStyle || {})
      s.label = Object.assign({ fontSize: 11, color: '#606266' }, s.label || {})
    }
  })

  // 9) dataZoom 在 line/bar 且数据量较大时选性启用
  const xa0 = Array.isArray(option.xAxis) ? option.xAxis[0] : option.xAxis
  const xa0Len = (xa0 && Array.isArray(xa0.data) ? xa0.data.length : 0)
  if (!option.dataZoom && (chartType === 'line' || chartType === 'area_stack') && xa0Len > 60) {
    option.dataZoom = [
      { type: 'inside', start: 0, end: 100, throttle: 50 },
      { type: 'slider', height: 16, bottom: 8, start: 0, end: 100,
        borderColor: 'transparent', backgroundColor: '#f5f7fa',
        fillerColor: 'rgba(91,143,249,0.18)', handleStyle: { color: '#5B8FF9' },
        textStyle: { color: '#909399', fontSize: 10 } }
    ]
    // 需预留 slider 高度
    grids.forEach(g => { g.bottom = Math.max(g.bottom || 0, 56) })
  }

  return option
}

export default {
  name: 'ChatChartRenderer',
  props: {
    charts: {
      type: Array,
      default: () => []
    },
    refPrefix: {
      type: String,
      required: true
    }
  },
  data() {
    return {
      chartInstances: [],
      renderedRefs: {},
      errorRefs: {}
    }
  },
  mounted() {
    this._resizeHandler = () => this.resizeAll()
    window.addEventListener('resize', this._resizeHandler)
    // 延迟初始化：避免虚拟滚动重建时立即初始化 ECharts，
    // 给组件 200ms 稳定时间确保它真正“停留在视口”而非短暂闪过
    this._initTimer = setTimeout(() => {
      this._initTimer = null
      this.renderCharts()
    }, 200)
  },
  beforeDestroy() {
    if (this._initTimer) {
      clearTimeout(this._initTimer)
      this._initTimer = null
    }
    this.disposeAll()
    if (this._resizeHandler) {
      window.removeEventListener('resize', this._resizeHandler)
    }
  },
  watch: {
    charts: {
      handler() {
        // 仅浅比较：移除 deep:true 避免 Vue 对巨大 echarts_option 树做递归观察
        this.$nextTick(() => {
          setTimeout(() => this.renderCharts(), 100)
        })
      }
    }
  },
  methods: {
    getChartHeight(chart) {
      const type = chart.chart_type
      // 多系列场景需预留顶部 legend 高度，适当加高
      const seriesCount = (chart.echarts_option && Array.isArray(chart.echarts_option.series))
        ? chart.echarts_option.series.length : 1
      const extraForLegend = seriesCount > 6 ? 24 : 0
      // 根据 xAxis 最长标签估算是否需要额外底部高度（中文/長资产名代码 + 旋转后需更多空间）
      let extraForXLabel = 0
      try {
        const opt = chart.echarts_option
        const xa = opt && (Array.isArray(opt.xAxis) ? opt.xAxis[0] : opt.xAxis)
        const arr = xa && Array.isArray(xa.data) ? xa.data : []
        if (arr.length) {
          let maxChars = 0
          for (const d of arr) {
            const s = (d && d.value != null ? d.value : d)
            const len = (s == null) ? 0 : String(s).length
            if (len > maxChars) maxChars = len
          }
          if (maxChars > 18) extraForXLabel = 80
          else if (maxChars > 10) extraForXLabel = 50
          else if (maxChars > 6) extraForXLabel = 24
        }
      } catch (e) { /* ignore */ }
      if (type === 'heatmap') return (440 + extraForLegend + extraForXLabel) + 'px'
      if (type === 'line') return (420 + extraForLegend + extraForXLabel) + 'px'
      if (type === 'area_stack') return (420 + extraForLegend + extraForXLabel) + 'px'
      if (type === 'bar') return (380 + extraForLegend + extraForXLabel) + 'px'
      if (type === 'pie') return '380px'
      return (380 + extraForXLabel) + 'px'
    },

    getChartSizeClass(chart) {
      if (!this.charts || this.charts.length <= 1) return 'chart-full'
      const pieCharts = this.charts.filter(c => c.chart_type === 'pie')
      if (chart.chart_type === 'pie' && pieCharts.length >= 2) return 'chart-half'
      return 'chart-full'
    },

    isChartRendered(refKey) {
      return !!this.renderedRefs[refKey]
    },

    isChartError(refKey) {
      return !!this.errorRefs[refKey]
    },

    renderCharts() {
      this.$nextTick(() => {
        this.charts.forEach((chartData, cIdx) => {
          const refKey = this.refPrefix + '_' + cIdx
          const el = this.$refs[refKey]
          const dom = Array.isArray(el) ? el[0] : el
          if (!dom || dom._echarts_instance_) return
          if (!chartData || !chartData.echarts_option) {
            console.warn('[Charts] chartData 不可用, ref:', refKey)
            return
          }

          try {
            console.log('[Charts] 初始化图表:', refKey, 'dom 尺寸:', dom.offsetWidth, 'x', dom.offsetHeight)
            const instance = this.$echarts.init(dom)
            const option = enhanceEchartsOption(chartData.echarts_option, chartData.chart_type, dom.clientWidth || dom.offsetWidth)
            instance.setOption(option, true)
            instance.resize()
            this.chartInstances.push(instance)
            this.$set(this.renderedRefs, refKey, true)
            // 双重保险：确保容器尺寸已确定后 resize
            setTimeout(() => { if (!instance.isDisposed()) instance.resize() }, 200)
          } catch (e) {
            console.error('图表渲染失败:', refKey, e)
            this.$set(this.errorRefs, refKey, true)
          }
        })
      })
    },

    resizeAll() {
      this.chartInstances.forEach(inst => {
        if (inst && !inst.isDisposed()) {
          inst.resize()
        }
      })
    },

    disposeAll() {
      this.chartInstances.forEach(inst => {
        if (inst && !inst.isDisposed()) {
          inst.dispose()
        }
      })
      this.chartInstances = []
    }
  }
}
</script>

<style scoped>
.message-charts {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  width: 100%;
  box-sizing: border-box;
}

.message-chart-wrapper {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  padding: 0;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
  transition: box-shadow 0.25s ease, transform 0.25s ease;
  overflow: hidden;
  box-sizing: border-box;
  position: relative;
}

.message-chart-wrapper::before {
  content: '';
  position: absolute;
  left: 0; top: 0;
  width: 3px; height: 100%;
  background: linear-gradient(180deg, #5B8FF9, #6DC8EC);
  opacity: 0.85;
}

.message-chart-wrapper:hover {
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.08);
}

.message-chart-wrapper.chart-full {
  flex: 1 1 100%;
  min-width: 0;
}

.message-chart-wrapper.chart-half {
  flex: 0 0 calc(50% - 7px);
  min-width: 0;
}

@media (max-width: 768px) {
  .message-chart-wrapper.chart-half {
    flex: 0 0 100%;
  }
}

.message-chart-title {
  padding: 12px 18px 10px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  border-bottom: 1px solid #f2f3f5;
  background: linear-gradient(180deg, #fafbfc 0%, #ffffff 100%);
  margin-bottom: 0;
  letter-spacing: 0.2px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.message-chart-title::before {
  content: '';
  width: 4px;
  height: 14px;
  background: #5B8FF9;
  border-radius: 2px;
  display: inline-block;
}

.message-chart {
  width: 100%;
  min-height: 200px;
  position: relative;
  padding: 8px 10px 12px;
  box-sizing: border-box;
}

.chart-skeleton {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #fafafa;
  border-radius: 4px;
  overflow: hidden;
  z-index: 1;
}

.skeleton-shimmer {
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.6), transparent);
  animation: shimmer 1.8s infinite;
}

@keyframes shimmer {
  0% { left: -100%; }
  100% { left: 100%; }
}

.skeleton-icon {
  font-size: 30px;
  color: #c0c4cc;
  margin-bottom: 6px;
  z-index: 2;
}

.skeleton-text {
  font-size: 12px;
  color: #c0c4cc;
  z-index: 2;
}

.chart-error-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 14px;
  color: #F56C6C;
  font-size: 13px;
  background: #fef0f0;
  border-radius: 6px;
  margin: 8px 12px 12px;
  border: 1px dashed #fbc4c4;
}

.chart-error-fallback i {
  font-size: 16px;
}
</style>
