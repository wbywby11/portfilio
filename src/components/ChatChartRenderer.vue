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
    // 初始渲染
    this.$nextTick(() => {
      setTimeout(() => this.renderCharts(), 100)
    })
  },
  beforeDestroy() {
    this.disposeAll()
    if (this._resizeHandler) {
      window.removeEventListener('resize', this._resizeHandler)
    }
  },
  watch: {
    charts: {
      handler() {
        this.$nextTick(() => {
          setTimeout(() => this.renderCharts(), 100)
        })
      },
      deep: true
    }
  },
  methods: {
    getChartHeight(chart) {
      const type = chart.chart_type
      if (type === 'heatmap') return '420px'
      if (type === 'line') return '400px'
      if (type === 'area_stack') return '400px'
      if (type === 'bar') return '360px'
      if (type === 'pie') return '360px'
      return '360px'
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
            instance.setOption(chartData.echarts_option)
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
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
  box-sizing: border-box;
}

.message-chart-wrapper {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transition: box-shadow 0.3s ease;
  overflow: hidden;
  box-sizing: border-box;
}

.message-chart-wrapper:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.message-chart-wrapper.chart-full {
  flex: 1 1 100%;
  min-width: 0;
}

.message-chart-wrapper.chart-half {
  flex: 0 0 calc(50% - 6px);
  min-width: 0;
}

@media (max-width: 768px) {
  .message-chart-wrapper.chart-half {
    flex: 0 0 100%;
  }
}

.message-chart-title {
  padding: 10px 16px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
  background: #fafbfc;
  margin-bottom: 0;
}

.message-chart {
  width: 100%;
  min-height: 200px;
  position: relative;
  padding: 12px;
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
  font-size: 32px;
  color: #dcdfe6;
  margin-bottom: 8px;
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
  padding: 12px;
  color: #F56C6C;
  font-size: 13px;
  background: #fef0f0;
  border-radius: 4px;
  margin-top: 4px;
}

.chart-error-fallback i {
  font-size: 16px;
}
</style>
