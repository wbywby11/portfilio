<template>
  <div class="agent-result-card">
    <el-collapse v-model="activeNames" @change="handleCollapseChange">
      <el-collapse-item
        v-for="(tool, idx) in toolCalls"
        :key="idx"
        :name="idx"
      >
        <template slot="title">
          <div class="tool-header">
            <i
              :class="tool.status === 'running' ? 'el-icon-loading' : tool.status === 'error' ? 'el-icon-circle-close' : 'el-icon-circle-check'"
              :style="{ color: tool.status === 'running' ? '#E6A23C' : tool.status === 'error' ? '#F56C6C' : '#67C23A' }"
            ></i>
            <span class="tool-name">{{ tool.name || '工具调用' }}</span>
            <el-tag size="mini" :type="statusTagType(tool.status)" class="tool-status-tag">
              {{ statusLabel(tool.status) }}
            </el-tag>
            <el-tag v-if="hasCharts(tool)" size="mini" type="" class="tool-chart-tag">
              <i class="el-icon-data-line"></i> {{ getCharts(tool).length }}个图表
            </el-tag>
          </div>
        </template>
        <div class="tool-body">
          <!-- 参数 -->
          <div v-if="tool.arguments" class="tool-section">
            <div class="tool-section-title">调用参数</div>
            <pre class="tool-code-block">{{ formatJson(tool.arguments) }}</pre>
          </div>
          <!-- 报告卡片 -->
          <div v-if="isReportResult(tool)" class="report-result-card">
            <div class="report-card-header">
              <i class="el-icon-document" style="font-size: 20px; color: #409EFF;"></i>
              <div>
                <div class="report-card-title">{{ getReportData(tool).title }}</div>
                <div style="margin-top: 4px;">
                  <el-tag size="mini" type="info">{{ getReportData(tool).typeLabel }}</el-tag>
                  <span v-if="getReportData(tool).contentLength" style="color: #909399; font-size: 12px; margin-left: 8px;">
                    {{ getReportData(tool).contentLength }} 字符
                  </span>
                </div>
              </div>
            </div>
            <div v-if="getReportData(tool).summary" style="color: #606266; font-size: 13px; margin: 8px 0;">
              {{ getReportData(tool).summary }}
            </div>
            <el-button size="small" type="primary" plain icon="el-icon-download" @click="downloadReportMd(tool)">
              下载 Markdown
            </el-button>
          </div>
          <!-- 结构化表格数据（含资产交互） -->
          <div v-else-if="hasTableData(tool)" class="tool-section">
            <div class="tool-section-title">执行结果</div>
            <ChatDataTable
              :records="getTableData(tool).records"
              :summary="getTableData(tool).summary"
              :recordCount="getTableData(tool).recordCount"
              :dataShape="getTableData(tool).dataShape"
              :stepKey="tool.name"
              :traceable-assets="getTableData(tool).traceableAssets || []"
              @asset-click="handleAssetClick"
            />
          </div>
          <!-- 结果（非报告时显示默认 JSON） -->
          <div v-else-if="tool.result !== undefined && tool.result !== null" class="tool-section">
            <div class="tool-section-title">执行结果</div>
            <pre class="tool-code-block">{{ formatResult(tool.result) }}</pre>
          </div>
          <!-- 图表渲染区域 -->
          <div v-if="hasCharts(tool)" class="agent-charts-container">
            <div class="tool-section-title"><i class="el-icon-data-line"></i> 图表</div>
            <div
              v-for="(chart, chartIdx) in getCharts(tool)"
              :key="chartIdx"
              class="agent-chart-wrapper"
            >
              <div class="agent-chart-title" v-if="chart.title">{{ chart.title }}</div>
              <div
                :ref="'chart_' + idx + '_' + chartIdx"
                class="agent-chart"
                :style="{ width: '100%', height: getChartHeight(chart) }"
              ></div>
            </div>
          </div>
          <!-- 执行中 -->
          <div v-if="tool.status === 'running'" class="tool-section">
            <i class="el-icon-loading"></i>
            <span style="margin-left: 6px; color: #909399;">正在执行...</span>
          </div>
          <!-- 错误 -->
          <div v-if="tool.error" class="tool-section tool-error">
            <div class="tool-section-title">错误信息</div>
            <pre class="tool-code-block error-block">{{ tool.error }}</pre>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script>
import ChatDataTable from './ChatDataTable.vue'

export default {
  name: 'AgentResultCard',
  components: { ChatDataTable },
  props: {
    toolCalls: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      activeNames: []
    }
  },
  watch: {
    toolCalls: {
      handler() {
        // 数据变化时，自动展开含图表的面板并渲染图表
        this.autoExpandChartPanels()
        this.$nextTick(() => this.renderCharts())
      },
      deep: true
    }
  },
  mounted() {
    this.autoExpandChartPanels()
    this.$nextTick(() => this.renderCharts())

    // 监听窗口 resize，自适应图表尺寸
    this._resizeHandler = () => {
      this.resizeAllCharts()
    }
    window.addEventListener('resize', this._resizeHandler)
  },
  beforeDestroy() {
    // 销毁所有 ECharts 实例，防止内存泄漏
    this.disposeAllCharts()
    if (this._resizeHandler) {
      window.removeEventListener('resize', this._resizeHandler)
    }
  },
  methods: {
    statusTagType(status) {
      if (status === 'running') return 'warning'
      if (status === 'error') return 'danger'
      return 'success'
    },
    statusLabel(status) {
      if (status === 'running') return '执行中'
      if (status === 'error') return '失败'
      return '完成'
    },
    formatJson(obj) {
      if (typeof obj === 'string') {
        try {
          return JSON.stringify(JSON.parse(obj), null, 2)
        } catch {
          return obj
        }
      }
      try {
        return JSON.stringify(obj, null, 2)
      } catch {
        return String(obj)
      }
    },
    formatResult(result) {
      if (typeof result === 'string') return result
      return this.formatJson(result)
    },

    // ========== 报告卡片相关方法 ==========

    isReportResult(tool) {
      if (!tool || !tool.result) return false
      try {
        const result = typeof tool.result === 'string' ? JSON.parse(tool.result) : tool.result
        if (tool.name === 'report_builder' && result.success && result.data && result.data.report_id) return true
        if (tool.name === 'report_review' && result.success && result.data && result.data.content) return true
      } catch (e) { return false }
      return false
    },

    getReportData(tool) {
      const result = typeof tool.result === 'string' ? JSON.parse(tool.result) : tool.result
      const typeLabels = {
        periodic: '定期报告',
        due_diligence: '尽职调查',
        investment_decision: '投资决策',
        product_review: '产品运作',
        compliance: '合规检查'
      }
      return {
        title: result.data?.title || '报告',
        typeLabel: typeLabels[result.data?.template_type] || '报告',
        contentLength: result.data?.content_length,
        content: result.data?.content || result.data?.rendered_content || '',
        summary: result.summary || '',
        reportId: result.data?.report_id
      }
    },

    downloadReportMd(tool) {
      const data = this.getReportData(tool)
      const content = data.content
      if (!content) {
        this.$message.warning('报告内容为空，无法下载')
        return
      }
      const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = (data.title || '报告') + '.md'
      a.click()
      URL.revokeObjectURL(url)
    },

    // ========== 图表相关方法 ==========

    /**
     * 解析 tool result，支持字符串和对象
     */
    parseResult(tool) {
      if (!tool || tool.result === undefined || tool.result === null) return null
      let result = tool.result
      if (typeof result === 'string') {
        try {
          result = JSON.parse(result)
        } catch {
          return null
        }
      }
      return result
    },

    /**
     * 检查 tool result 中是否包含 charts 数组
     */
    hasCharts(tool) {
      const result = this.parseResult(tool)
      return result && Array.isArray(result.charts) && result.charts.length > 0
    },

    /**
     * 获取 tool result 中的 charts 数组
     */
    getCharts(tool) {
      const result = this.parseResult(tool)
      return (result && Array.isArray(result.charts)) ? result.charts : []
    },

    /**
     * 根据图表类型返回合适的默认高度
     */
    getChartHeight(chart) {
      if (chart.chart_type === 'heatmap') return '400px'
      if (chart.chart_type === 'pie') return '350px'
      return '300px'
    },

    /**
     * 自动展开含有图表的折叠面板
     */
    autoExpandChartPanels() {
      const expanded = [...this.activeNames]
      this.toolCalls.forEach((tool, idx) => {
        if (this.hasCharts(tool) && !expanded.includes(idx)) {
          expanded.push(idx)
        }
      })
      this.activeNames = expanded
    },

    /**
     * 遍历所有图表 ref，初始化 ECharts 实例并设置 option
     */
    renderCharts() {
      this.$nextTick(() => {
        Object.keys(this.$refs).forEach(refKey => {
          if (!refKey.startsWith('chart_')) return

          const el = this.$refs[refKey]
          const dom = Array.isArray(el) ? el[0] : el
          if (!dom || dom._echarts_instance_) return

          // 从 ref key 解析 callIdx 和 chartIdx
          const parts = refKey.split('_')
          const callIdx = parseInt(parts[1], 10)
          const chartIdx = parseInt(parts[2], 10)

          const tool = this.toolCalls[callIdx]
          if (!tool) return

          const charts = this.getCharts(tool)
          const chartData = charts[chartIdx]
          if (!chartData || !chartData.echarts_option) return

          const instance = this.$echarts.init(dom)
          instance.setOption(chartData.echarts_option)
        })
      })
    },

    /**
     * 折叠面板展开/收起时触发图表 resize
     * ECharts 在 display:none 时无法正确计算尺寸
     */
    handleCollapseChange() {
      this.$nextTick(() => {
        this.renderCharts()
        this.resizeAllCharts()
      })
    },

    /**
     * resize 所有已初始化的图表实例
     */
    resizeAllCharts() {
      Object.keys(this.$refs).forEach(refKey => {
        if (!refKey.startsWith('chart_')) return
        const el = this.$refs[refKey]
        const dom = Array.isArray(el) ? el[0] : el
        if (dom && dom._echarts_instance_) {
          this.$echarts.getInstanceByDom(dom).resize()
        }
      })
    },

    /**
     * 销毁所有 ECharts 实例
     */
    disposeAllCharts() {
      Object.keys(this.$refs).forEach(refKey => {
        if (!refKey.startsWith('chart_')) return
        const el = this.$refs[refKey]
        const dom = Array.isArray(el) ? el[0] : el
        if (dom && dom._echarts_instance_) {
          this.$echarts.getInstanceByDom(dom).dispose()
        }
      })
    },

    /**
     * 从 result.data 中提取数据数组，支持多种常见字段名
     */
    _extractDataArray(data) {
      if (!data) return null
      const arr = data.records || data.prices || data.items || data.rows
      return Array.isArray(arr) && arr.length > 0 ? arr : null
    },

    /**
     * 检查 tool result 中是否包含结构化表格数据
     */
    hasTableData(tool) {
      const result = this.parseResult(tool)
      if (!result || !result.data) return false
      return !!this._extractDataArray(result.data)
    },

    /**
     * 从 tool result 中提取表格数据（含可追踪资产）
     */
    getTableData(tool) {
      const result = this.parseResult(tool)
      if (!result || !result.data) return null
      const dataArray = this._extractDataArray(result.data)
      if (!dataArray) return null
      const traceableAssets = result.traceable_assets
        || result.data.traceable_assets
        || (result.metadata && result.metadata.traceable_assets)
        || []
      return {
        records: dataArray,
        summary: result.summary || '',
        recordCount: (result.metadata && result.metadata.record_count) || dataArray.length,
        dataShape: (result.metadata && result.metadata.data_shape) || 'table',
        traceableAssets
      }
    },

    /**
     * 处理资产点击：向上冒泡给父组件
     */
    handleAssetClick(payload) {
      this.$emit('asset-click', payload)
    }
  }
}
</script>

<style scoped>
.agent-result-card {
  margin: 8px 0;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-name {
  font-weight: 500;
  font-size: 13px;
  color: #303133;
}

.tool-status-tag {
  margin-left: 4px;
}

.tool-body {
  padding: 4px 0;
}

.tool-section {
  margin-bottom: 10px;
}

.tool-section-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
  font-weight: 500;
}

.tool-code-block {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  max-height: 300px;
  overflow-y: auto;
  margin: 0;
}

.error-block {
  background: #fef0f0;
  border-color: #fde2e2;
  color: #F56C6C;
}

.tool-error .tool-section-title {
  color: #F56C6C;
}

/* 图表标签 */
.tool-chart-tag {
  margin-left: 4px;
}

/* 图表容器 */
.agent-charts-container {
  margin-top: 12px;
}

.agent-charts-container > .tool-section-title {
  margin-bottom: 8px;
}

.agent-chart-wrapper {
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  background: #fff;
}

.agent-chart-title {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 8px;
  text-align: center;
}

.agent-chart {
  width: 100%;
}

/* 报告卡片 */
.report-result-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 16px;
  background: #fafbfc;
  margin-bottom: 10px;
}

.report-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.report-card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
</style>
