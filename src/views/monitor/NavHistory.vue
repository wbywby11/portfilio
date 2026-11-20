<template>
  <div class="nav-history" v-loading="loading">
    <div class="nav-toolbar">
      <span class="range-hint">{{ rangeText }}</span>
      <el-button
        type="text"
        size="small"
        icon="el-icon-download"
        :disabled="navRows.length === 0"
        @click="handleExport">导出净值数据</el-button>
    </div>

    <!-- 区间绩效指标：配置驱动，与总览页共用 MetricCard -->
    <div class="stats-row" :style="statsGridStyle">
      <MetricCard
        v-for="metric in performanceMetrics"
        :key="metric.key"
        :metric="metric" />
    </div>

    <!-- 主图：净值曲线（渐变面积）；副图：日收益率独立迷你子图 -->
    <TimeSeriesChart
      v-if="navRows.length > 0"
      :x-data="dates"
      :series="chartSeries"
      :y-axis="chartYAxes"
      :grids="chartGrids"
      :height="chartHeight"
      :x-axis-label-formatter="axisLabelFormatter" />
    <el-empty
      v-else
      description="暂无净值数据，请先运行监控初始化或日常运行"
      :image-size="80" />
  </div>
</template>

<script>
import dayjs from 'dayjs';
import { mapGetters, mapState } from 'vuex';
import { createDateAxisLabelFormatter } from '@/utils/dateAxis';
import MetricCard from '@/components/monitor/MetricCard.vue';
import TimeSeriesChart from '@/components/monitor/TimeSeriesChart.vue';
import { buildMetrics, resolveGridColumns } from '@/config/monitor';

export default {
  name: 'MonitorNavHistory',
  components: { MetricCard, TimeSeriesChart },
  props: {
    /** 策略上下文：指标集合与栅格列数可按策略覆盖 */
    strategyContext: { type: Object, default: null }
  },
  data() {
    return {};
  },
  computed: {
    ...mapState('monitor', ['performancePanel']),
    ...mapGetters('monitor', ['isLoading']),
    loading() {
      return this.isLoading && !this.performancePanel;
    },
    panel() {
      return this.performancePanel || null;
    },
    navRows() {
      return (this.panel && this.panel.nav_history) || [];
    },
    modelRows() {
      return (this.panel && this.panel.nav_history_model) || [];
    },
    hasModelTrack() {
      return !!(this.panel && this.panel.has_model_track && this.modelRows.length);
    },
    metrics() {
      return (this.panel && this.panel.metrics) || {};
    },
    rangeText() {
      const range = (this.panel && this.panel.range) || {};
      if (!range.start || !range.end) return '暂无数据区间';
      const suffix = range.clamped ? '（已裁剪至数据范围）' : '';
      return `数据区间：${range.start} 至 ${range.end}，共 ${this.navRows.length} 个交易日${suffix}`;
    },
    /** 指标卡上下文：只取数，展示规则在 @/config/monitor/metrics */
    performanceMetricContext() {
      const m = this.metrics;
      return {
        periodReturn: m.period_return,
        annualReturn: m.annual_return,
        annualReturn365: m.annual_return_365,
        annualVol: m.annual_volatility,
        annualVol365: m.annual_volatility_365,
        maxDrawdown: m.max_drawdown,
        sharpe: m.sharpe_ratio,
        sharpe365: m.sharpe_ratio_365,
        tradingDays: m.trading_days
      };
    },
    performanceMetrics() {
      return buildMetrics('performance', this.performanceMetricContext, this.strategyContext);
    },
    statsGridStyle() {
      return { '--monitor-grid-cols': resolveGridColumns('performance', this.strategyContext) };
    },

    /* ── 图表数据：全部由后端序列派生，图表组件只负责渲染 ── */
    dates() {
      return this.navRows.map(item => item.date);
    },
    navValues() {
      return this.navRows.map(item => item.nav);
    },
    dailyReturns() {
      return this.navRows.map(item => (
        item.daily_return === null || item.daily_return === undefined
          ? 0
          : Number((item.daily_return * 100).toFixed(4))
      ));
    },
    /** 模型口径序列对齐实际净值日期轴 */
    modelValues() {
      if (!this.hasModelTrack) return [];
      const modelMap = {};
      this.modelRows.forEach(item => { modelMap[item.date] = item.nav; });
      return this.dates.map(d => (modelMap[d] != null ? modelMap[d] : null));
    },
    /** 「实际 − 模型」差值：同日对齐，任一侧缺值则为空 */
    gapValues() {
      if (!this.hasModelTrack) return [];
      const modelMap = {};
      this.modelRows.forEach(item => { modelMap[item.date] = item.nav; });
      const navMap = {};
      this.dates.forEach((d, i) => { navMap[d] = this.navValues[i]; });
      return this.dates.map(d => (
        modelMap[d] != null && navMap[d] != null
          ? Number((navMap[d] - modelMap[d]).toFixed(4))
          : null
      ));
    },
    chartGrids() {
      if (this.hasModelTrack) {
        return [
          { left: '3%', right: '4%', top: 44, height: '42%', containLabel: true },
          { left: '3%', right: '4%', top: '54%', height: '14%', containLabel: true },
          { left: '3%', right: '4%', top: '72%', height: '20%', containLabel: true }
        ];
      }
      return [
        { left: '3%', right: '4%', top: 44, height: '50%', containLabel: true },
        { left: '3%', right: '4%', top: '60%', height: '22%', containLabel: true }
      ];
    },
    chartYAxes() {
      const navAxis = { name: '净值', format: 'number', precision: 4, position: 'left', grid: 0 };
      // scale:false 保证 0 轴始终在副图内，正负柱有共同基准；splitNumber 收敛到 3 档避免右缘密集
      const dailyAxis = {
        name: '日收益',
        format: 'percent',
        precision: 1,
        position: 'right',
        splitLine: false,
        scale: false,
        fontSize: 11,
        splitNumber: 3,
        axisLine: true,
        labelMargin: 10
      };
      if (this.hasModelTrack) {
        return [
          navAxis,
          { name: '实际−模型', format: 'number', precision: 2, position: 'right', grid: 1, splitLine: false },
          Object.assign({}, dailyAxis, { grid: 2 })
        ];
      }
      return [navAxis, Object.assign({}, dailyAxis, { grid: 1 })];
    },
    chartSeries() {
      const series = [
        { name: '净值', type: 'line', data: this.navValues, yAxis: 0, area: true, lineWidth: 2.5, color: '#409EFF' }
      ];
      if (this.hasModelTrack) {
        series.push(
          { name: '模型口径净值', type: 'line', data: this.modelValues, yAxis: 0, dashed: true, lineWidth: 2, color: '#909399', connectNulls: false },
          { name: '实际−模型', type: 'line', data: this.gapValues, yAxis: 1, lineWidth: 1.6, color: '#722ED1', area: true, areaOpacity: 0.26, connectNulls: false }
        );
      }
      series.push({
        name: '日收益率',
        type: 'bar',
        data: this.dailyReturns,
        yAxis: this.hasModelTrack ? 2 : 1,
        color: params => (params.data >= 0 ? '#F56C6C' : '#67C23A'),
        opacity: 0.8
      });
      return series;
    },
    chartHeight() {
      return this.hasModelTrack ? 640 : 560;
    },
    axisLabelFormatter() {
      return createDateAxisLabelFormatter(this.dates);
    }
  },
  methods: {
    handleExport() {
      if (this.navRows.length === 0) {
        this.$message.warning('暂无数据可导出');
        return;
      }
      const headers = ['日期', '净值', '日收益率', '区间累计收益率', '区间回撤', '调仓日'];
      const rows = this.navRows.map(item => [
        item.date,
        item.nav != null ? Number(item.nav).toFixed(4) : '',
        item.daily_return != null ? `${(item.daily_return * 100).toFixed(4)}%` : '',
        item.cumulative_return != null ? `${(item.cumulative_return * 100).toFixed(2)}%` : '',
        item.drawdown != null ? `${(item.drawdown * 100).toFixed(2)}%` : '',
        item.is_rebalance ? '是' : ''
      ]);
      const csvContent = [headers.join(','), ...rows.map(row => row.join(','))].join('\n');
      const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      const range = this.panel.range || {};
      link.download = `净值数据_${range.start || ''}_${range.end || dayjs().format('YYYY-MM-DD')}.csv`;
      link.click();
      URL.revokeObjectURL(link.href);
      this.$message.success(`已导出 ${this.navRows.length} 条净值记录`);
    },
  }
};
</script>

<style scoped>
.nav-history {
  min-height: 300px;
}

.nav-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.range-hint {
  font-size: 12px;
  color: #909399;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(var(--monitor-grid-cols, 6), minmax(0, 1fr));
  grid-auto-rows: 1fr;
  gap: 12px;
  margin-bottom: 14px;
}

@media (max-width: 1400px) {
  .stats-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
