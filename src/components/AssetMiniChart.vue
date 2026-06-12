<template>
  <el-popover
    v-if="popoverActive"
    placement="top"
    trigger="hover"
    :width="240"
    popper-class="asset-mini-chart-popover"
    :disabled="disabled"
    :open-delay="80"
    @show="loadChartData"
  >
    <!-- mouseenter 在 popover 真正展示前就发起请求，缩短首次悬浮的「加载中…」时间 -->
    <span slot="reference" class="asset-mini-chart-ref" @mouseenter="handleRefHover">
      <slot></slot>
    </span>

    <div class="mini-chart-container">
      <div class="mini-chart-title">{{ chartTitle }}</div>
      <div v-if="!loading && !error && chartRangeText" class="mini-chart-range">
        数据区间：{{ chartRangeText }}
      </div>
      <div v-if="loading" class="mini-chart-loading">
        <i class="el-icon-loading"></i> 加载中...
      </div>
      <div v-else-if="error" class="mini-chart-error">
        <i class="el-icon-warning-outline"></i> {{ errorMsg || '暂无数据' }}
      </div>
      <div v-else ref="miniChart" class="mini-chart-canvas"></div>
      <div class="mini-chart-footer">
        <span class="mini-chart-hint">{{ footerHint }}</span>
      </div>
    </div>
  </el-popover>
  <!-- 性能关键：未激活 popover 前仅渲染轻量 span，避免虚拟滚动重建时创建大量 el-popover/popper.js 实例 -->
  <span v-else class="asset-mini-chart-ref" @mouseenter="activatePopover">
    <slot></slot>
  </span>
</template>

<script>
import { getAssetKline } from '@/api/asset'

// 模块级缓存：同一资产不重复请求（含「无数据」负面缓存，避免反复发请求）
const klineCache = new Map() // code -> Array<{date, close}>（已规范化）
const klineNoDataSet = new Set() // code集合：已确认无数据
const klineErrorSet = new Set() // code集合：请求异常
const klineLoadingPromise = new Map() // code -> Promise，并发去重

// 预取并发控制：避免一次性发起过多请求拖慢页面，同时让首屏可见资产尽快进缓存
const PREFETCH_CONCURRENCY = 4
let activePrefetchCount = 0
const prefetchQueue = []

function startPrefetch(code) {
  if (!code) return
  if (klineCache.has(code) || klineNoDataSet.has(code) || klineErrorSet.has(code)) return
  if (klineLoadingPromise.has(code)) return
  // 去掉队列中已存在的同 code（保持先进先出）
  if (prefetchQueue.indexOf(code) !== -1) return
  prefetchQueue.push(code)
  drainPrefetchQueue()
}

function drainPrefetchQueue() {
  while (activePrefetchCount < PREFETCH_CONCURRENCY && prefetchQueue.length) {
    const code = prefetchQueue.shift()
    if (klineCache.has(code) || klineNoDataSet.has(code) || klineErrorSet.has(code)) continue
    if (klineLoadingPromise.has(code)) continue
    activePrefetchCount += 1
    fetchKline(code).finally(() => {
      activePrefetchCount -= 1
      drainPrefetchQueue()
    })
  }
}

function fmtDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function fetchKline(code) {
  const endDate = fmtDate(new Date())
  const startDate = fmtDate(new Date(Date.now() - 365 * 24 * 60 * 60 * 1000))
  const promise = (async () => {
    try {
      const res = await getAssetKline(code, { start_date: startDate, end_date: endDate })
      const raw = res && (res.data || res)
      const data = normalizeBars(raw, 30)
      if (!data || data.length === 0) {
        klineNoDataSet.add(code)
      } else {
        klineCache.set(code, data)
      }
      return data
    } catch (e) {
      klineErrorSet.add(code)
      // eslint-disable-next-line no-console
      console.warn('[AssetMiniChart] 加载K线失败:', code, e)
      throw e
    } finally {
      klineLoadingPromise.delete(code)
    }
  })()
  klineLoadingPromise.set(code, promise)
  return promise
}

/**
 * 静态预取入口：供外部组件（如 ChatDataTable）在芯片区渲染后空闲预取，
 * 让用户实际悬浮前数据已进缓存，肉眼几乎感知不到「加载中」。
 */
export function prefetchAssetKline(codes) {
  if (!Array.isArray(codes) || !codes.length) return
  const run = () => {
    for (const c of codes) startPrefetch(c)
  }
  if (typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function') {
    window.requestIdleCallback(run, { timeout: 800 })
  } else {
    setTimeout(run, 0)
  }
}

// 过滤、规范化、按日期升序、取最后 N 个有效数据点
function normalizeBars(raw, recentN) {
  if (!Array.isArray(raw)) return []
  const valid = []
  for (const d of raw) {
    if (!d || typeof d !== 'object') continue
    const date = d.date || d.trade_date || d.day || ''
    if (!date) continue
    const v = d.close != null ? d.close : (d.price != null ? d.price : d.value)
    if (v == null || v === '') continue
    const num = Number(v)
    if (!Number.isFinite(num)) continue
    valid.push({ date: String(date), close: num })
  }
  valid.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  if (recentN && valid.length > recentN) {
    return valid.slice(-recentN)
  }
  return valid
}

export default {
  name: 'AssetMiniChart',
  props: {
    assetCode: {
      type: String,
      required: true
    },
    assetName: {
      type: String,
      default: ''
    },
    /** 为 true 时完全禁用 popover（不请求接口、不弹出） */
    disabled: {
      type: Boolean,
      default: false
    },
    /**
     * 行情数据覆盖：当外部（如 ChatDataTable）已拥有该资产的真实区间数据时，
     * 通过此 prop 直接传入，避免独立调用 getAssetKline 导致迷你图与表格区间/数值不一致。
     * 数据格式：原始 records 数组（含 date/close 字段，会经 normalizeBars 规范化）。
     */
    barsOverride: {
      type: Array,
      default: null
    }
  },
  data() {
    return {
      loading: false,
      error: false,
      errorMsg: '',
      chartInstance: null,
      chartData: null,
      /** 性能优化：el-popover 延迟激活。首次 hover 前不创建 popover 实例，避免虚拟滚动重建时批量创建 popper.js 实例 */
      popoverActive: false
    }
  },
  beforeDestroy() {
    if (this.chartInstance) {
      this.chartInstance.dispose()
      this.chartInstance = null
    }
  },
  watch: {
    // 资产切换时：清空当前已渲染数据，避免旧资产 K 线残留
    assetCode() {
      this.chartData = null
      this.error = false
      this.errorMsg = ''
      if (this.chartInstance) {
        this.chartInstance.clear()
      }
    },
    // 外部覆盖数据变化时：清除当前数据并标记需要重新规范化
    barsOverride() {
      // 仅在 popover 已展示时立即重渲染；否则下次 loadChartData 触发
      this.chartData = null
      this.error = false
      this.errorMsg = ''
      if (this.chartInstance) {
        this.chartInstance.clear()
      }
    }
  },
  computed: {
    /** 是否有有效数据 */
    hasValidData() {
      return Array.isArray(this.chartData) && this.chartData.length > 0
    },
    /** 走势图标题：默认「近30交易日」，数据不足时限定实际条数 */
    chartTitle() {
      const baseName = this.assetName || this.assetCode
      if (!this.hasValidData) {
        return `${baseName} 走势`
      }
      const len = this.chartData.length
      if (len >= 30) {
        return `${baseName} 近 30 个交易日走势`
      }
      return `${baseName} 近 ${len} 个交易日走势`
    },
    /** 实际数据区间文本：首末日期拼接；同一天只显示一个 */
    chartRangeText() {
      if (!this.hasValidData) return ''
      const first = this.chartData[0].date
      const last = this.chartData[this.chartData.length - 1].date
      if (!first || !last) return ''
      if (first === last) return first
      return `${first} ~ ${last}`
    },
    /** 脚注提示：数据质量说明 */
    footerHint() {
      if (!this.hasValidData) return '点击查看详情'
      const len = this.chartData.length
      if (len < 10) {
        return `仅 ${len} 个有效点 · 点击查看完整走势`
      }
      if (len < 30) {
        return `该资产近期数据较少 · 点击查看完整走势`
      }
      return '点击查看完整 K 线'
    }
  },
  methods: {
    /**
     * 性能优化：首次 hover 时激活 el-popover，之后的 hover 走正常流程。
     * 避免虚拟滚动重建时为每个资产芯片都创建 el-popover + popper.js 实例。
     */
    activatePopover() {
      if (this.disabled) return
      this.popoverActive = true
      // 下一帧 popover 已挂载，触发数据加载
      this.$nextTick(() => this.handleRefHover())
    },
    handleRefHover() {
      if (this.disabled || !this.assetCode) return
      // 已有数据 / 无数据 / 已失败：直接返回，不重复触发
      if (this.chartData) return
      // 有外部覆盖数据时，跳过模块级负面缓存（缓存针对独立请求，不适用于覆盖数据场景）
      const hasOverride = Array.isArray(this.barsOverride) && this.barsOverride.length > 0
      if (!hasOverride) {
        if (klineNoDataSet.has(this.assetCode) || klineErrorSet.has(this.assetCode)) return
      }
      this.loadChartData()
    },

    async loadChartData() {
      if (this.disabled) return
      if (this.chartData) {
        // 已有数据，直接渲染
        this.$nextTick(() => this.renderChart())
        return
      }

      // === 优先使用外部传入的覆盖数据，确保与表格行情同源 ===
      if (Array.isArray(this.barsOverride) && this.barsOverride.length) {
        const normalized = normalizeBars(this.barsOverride, 30)
        if (normalized && normalized.length) {
          this.chartData = normalized
          this.$nextTick(() => this.renderChart())
          return
        }
        // override 但无法规范化：fallback 走原有 fetch 逻辑
      }

      const cacheKey = this.assetCode
      // 负面缓存：已知无数据或已失败，不再发请求
      if (klineNoDataSet.has(cacheKey)) {
        this.error = true
        this.errorMsg = '暂无数据'
        return
      }
      if (klineErrorSet.has(cacheKey)) {
        this.error = true
        this.errorMsg = '加载失败'
        return
      }
      // 正面缓存
      if (klineCache.has(cacheKey)) {
        this.chartData = klineCache.get(cacheKey)
        this.$nextTick(() => this.renderChart())
        return
      }
      // 并发去重：同一资产同时多个芯片悬停只发一次请求（含已在预取队列中的）
      if (klineLoadingPromise.has(cacheKey)) {
        this.loading = true
        try {
          const data = await klineLoadingPromise.get(cacheKey)
          if (data && data.length) {
            this.chartData = data
            this.$nextTick(() => this.renderChart())
          } else {
            this.error = true
            this.errorMsg = '暂无数据'
          }
        } catch (e) {
          this.error = true
          this.errorMsg = '加载失败'
        } finally {
          this.loading = false
        }
        return
      }

      this.loading = true
      this.error = false
      this.errorMsg = ''

      try {
        // 复用模块级 fetchKline，与 prefetch 共享缓存与并发去重
        const data = await fetchKline(cacheKey)
        if (!data || data.length === 0) {
          this.error = true
          this.errorMsg = '暂无数据'
          return
        }
        this.chartData = data
        this.$nextTick(() => this.renderChart())
      } catch (e) {
        this.error = true
        this.errorMsg = '加载失败'
      } finally {
        this.loading = false
      }
    },

    renderChart() {
      if (!this.$refs.miniChart || !this.chartData) return

      const echarts = this.$echarts
      if (!echarts) {
        console.warn('[AssetMiniChart] ECharts 未全局注册')
        this.error = true
        return
      }

      // 复用 ECharts 实例：仅在容器变化或销毁时 dispose，避免悬浮闪烁与重复初始化耗时
      // 注意：loading/error/canvas 三个分支使用 v-if/v-else，canvas DOM 会被重建，
      // 需检查现有实例是否还挂在当前 DOM 上，否则 dispose 重建
      if (this.chartInstance && this.chartInstance.getDom() !== this.$refs.miniChart) {
        this.chartInstance.dispose()
        this.chartInstance = null
      }
      if (!this.chartInstance) {
        this.chartInstance = echarts.init(this.$refs.miniChart)
      } else {
        this.chartInstance.clear()
      }

      const prices = this.chartData.map(d => Number(d.close))
      const dates = this.chartData.map(d => d.date || '')

      const firstPrice = prices[0] || 0
      const lastPrice = prices[prices.length - 1] || 0
      const isUp = lastPrice >= firstPrice
      const lineColor = isUp ? '#67c23a' : '#f56c6c'
      const areaColorStart = isUp ? 'rgba(103, 194, 58, 0.3)' : 'rgba(245, 108, 108, 0.3)'
      const areaColorEnd = isUp ? 'rgba(103, 194, 58, 0.05)' : 'rgba(245, 108, 108, 0.05)'

      const option = {
        grid: {
          top: 8,
          right: 8,
          bottom: 8,
          left: 8
        },
        xAxis: {
          type: 'category',
          data: dates,
          show: false,
          boundaryGap: false
        },
        yAxis: {
          type: 'value',
          show: false,
          scale: true
        },
        series: [{
          type: 'line',
          data: prices,
          smooth: true,
          symbol: 'none',
          lineStyle: {
            color: lineColor,
            width: 1.5
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: areaColorStart },
                { offset: 1, color: areaColorEnd }
              ]
            }
          }
        }],
        tooltip: {
          trigger: 'axis',
          formatter: (params) => {
            const p = params[0]
            return `${p.name}<br/>${p.value}`
          },
          textStyle: { fontSize: 11 }
        }
      }

      this.chartInstance.setOption(option)
    },

    formatDate(date) {
      const y = date.getFullYear()
      const m = String(date.getMonth() + 1).padStart(2, '0')
      const d = String(date.getDate()).padStart(2, '0')
      return `${y}-${m}-${d}`
    }
  }
}
</script>

<style scoped>
.mini-chart-container {
  padding: 4px 0;
}

.mini-chart-title {
  font-size: 12px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 2px;
  text-align: center;
}

.mini-chart-range {
  font-size: 11px;
  color: #909399;
  text-align: center;
  margin-bottom: 6px;
  font-variant-numeric: tabular-nums;
}

.mini-chart-loading,
.mini-chart-error {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100px;
  font-size: 12px;
  color: #909399;
  gap: 4px;
}

.mini-chart-canvas {
  width: 220px;
  height: 100px;
}

.mini-chart-footer {
  text-align: center;
  margin-top: 4px;
}

.mini-chart-hint {
  font-size: 11px;
  color: #409EFF;
  cursor: pointer;
}
</style>

<!-- 非scoped: popover被append-to-body，需要全局样式 -->
<style>
.asset-mini-chart-popover {
  z-index: 3000 !important;
  padding: 8px 12px;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}
</style>
