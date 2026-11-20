<template>
  <div class="asset-analysis" v-loading="loading">
    <template v-if="analysis">
      <div v-if="hasCorrelation" class="risk-grid">
        <div class="risk-block">
          <div class="risk-title">
            相关性矩阵
            <span class="risk-hint">皮尔逊相关系数，越接近 1 同向性越强</span>
          </div>
          <div ref="correlationChart" class="risk-chart"></div>
        </div>
        <div class="risk-block">
          <div class="risk-title">
            年化波动率
            <span class="risk-hint">按波动率降序，红色高于 75 分位</span>
          </div>
          <el-table
            :data="volatilityRows"
            size="mini"
            border
            stripe
            style="width: 100%;">
            <el-table-column type="index" label="#" width="42" align="center"></el-table-column>
            <el-table-column prop="name" label="资产名称" min-width="120" show-overflow-tooltip></el-table-column>
            <el-table-column label="年化波动率（260日）" width="130" align="right">
              <template slot-scope="scope">
                <span :class="{ 'over-p75': scope.row.annual_volatility >= percentile75 }">
                  {{ formatPct(scope.row.annual_volatility) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="年化波动率（365日）" width="130" align="right">
              <template slot-scope="scope">
                {{ formatPct(scope.row.annual_volatility_365) }}
              </template>
            </el-table-column>
            <el-table-column label="年化收益（260日）" width="120" align="right">
              <template slot-scope="scope">
                <span :class="returnClass(scope.row.annual_return)">
                  {{ formatPct(scope.row.annual_return) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="年化收益（365日）" width="120" align="right">
              <template slot-scope="scope">
                {{ formatPct(scope.row.annual_return_365) }}
              </template>
            </el-table-column>
            <el-table-column label="最大回撤" width="90" align="right">
              <template slot-scope="scope">
                <span class="number-negative">{{ formatPct(scope.row.max_drawdown) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
      <el-empty
        v-else
        description="区间内有效样本不足，无法计算相关性"
        :image-size="80" />
    </template>
    <el-empty
      v-else
      description="暂无底层资产分析数据，请先运行监控初始化或日常运行"
      :image-size="80" />
  </div>
</template>

<script>
import * as echarts from 'echarts';
import { mapGetters, mapState } from 'vuex';

/** 资产可读上限：超过 50 项仅展示前 50 项 */
const MAX_ASSETS = 50;

export default {
  name: 'MonitorAssetAnalysis',
  data() {
    return {
      correlationChart: null
    };
  },
  computed: {
    ...mapState('monitor', ['performancePanel']),
    ...mapGetters('monitor', ['isLoading']),
    loading() {
      return this.isLoading && !this.performancePanel;
    },
    analysis() {
      return (this.performancePanel && this.performancePanel.asset_analysis) || null;
    },
    assetInfo() {
      const info = this.analysis && this.analysis.correlation && this.analysis.correlation.asset_info;
      return Array.isArray(info) ? info : [];
    },
    displayAssets() {
      return this.assetInfo.slice(0, MAX_ASSETS);
    },
    hasCorrelation() {
      const matrix = this.analysis && this.analysis.correlation && this.analysis.correlation.matrix;
      return !!(matrix && Object.keys(matrix).length > 0 && this.displayAssets.length >= 2);
    },
    /** 波动率表：仅展示当前资产，按波动率降序 */
    volatilityRows() {
      const rows = (this.analysis && this.analysis.metrics) || [];
      const allowed = {};
      this.displayAssets.forEach(item => { allowed[item.thscode] = item.name; });
      return rows
        .filter(item => allowed[item.thscode])
        .map(item => ({ ...item, name: allowed[item.thscode] || item.name }))
        .sort((a, b) => (b.annual_volatility || 0) - (a.annual_volatility || 0));
    },
    /** 波动率 75 分位（用于高亮） */
    percentile75() {
      const values = this.volatilityRows
        .map(item => Number(item.annual_volatility))
        .filter(value => !Number.isNaN(value))
        .sort((a, b) => a - b);
      if (!values.length) return null;
      return values[Math.min(values.length - 1, Math.floor(values.length * 0.75))];
    }
  },
  watch: {
    performancePanel() {
      this.$nextTick(() => {
        this.$nextTick(() => this.renderCorrelationHeatmap());
      });
    }
  },
  mounted() {
    window.addEventListener('resize', this.handleResize);
    this.$nextTick(() => this.renderCorrelationHeatmap());
  },
  beforeDestroy() {
    if (this.correlationChart) {
      this.correlationChart.dispose();
      this.correlationChart = null;
    }
    window.removeEventListener('resize', this.handleResize);
  },
  methods: {
    handleResize() {
      if (this.correlationChart) {
        this.correlationChart.resize();
      } else {
        this.renderCorrelationHeatmap();
      }
    },
    renderCorrelationHeatmap() {
      if (!this.hasCorrelation) {
        if (this.correlationChart) {
          this.correlationChart.dispose();
          this.correlationChart = null;
        }
        return;
      }
      const el = this.$refs.correlationChart;
      if (!el || el.clientWidth === 0 || el.clientHeight === 0) return;
      if (this.correlationChart) this.correlationChart.dispose();
      const chart = echarts.init(el);
      this.correlationChart = chart;

      const assets = this.displayAssets;
      const names = assets.map(item => item.name);
      const matrix = this.analysis.correlation.matrix;
      const data = [];
      for (let i = 0; i < assets.length; i++) {
        for (let j = 0; j < assets.length; j++) {
          const row = matrix[assets[i].thscode] || {};
          const value = row[assets[j].thscode];
          data.push([j, i, value != null ? Number(value) : 0]);
        }
      }
      // 资产多时轴标签自动抽稀，避免重叠成一团
      const labelInterval = assets.length > 30 ? Math.ceil(assets.length / 24) - 1 : 0;

      chart.setOption({
        tooltip: {
          trigger: 'item',
          formatter: params => {
            const value = Number(params.value[2]) || 0;
            return `${names[params.value[1]]} - ${names[params.value[0]]}<br/>相关系数: ${value.toFixed(3)}`;
          }
        },
        grid: { left: 8, right: 76, top: 8, bottom: 8, containLabel: true },
        xAxis: {
          type: 'category',
          data: names,
          splitArea: { show: true },
          axisLabel: { rotate: 45, interval: labelInterval, fontSize: 9, width: 80, overflow: 'truncate' }
        },
        yAxis: {
          type: 'category',
          data: names,
          splitArea: { show: true },
          axisLabel: { interval: labelInterval, fontSize: 9, width: 80, overflow: 'truncate' }
        },
        visualMap: {
          min: -1,
          max: 1,
          calculable: true,
          orient: 'vertical',
          right: 8,
          top: 'center',
          itemHeight: 140,
          itemWidth: 12,
          precision: 1,
          text: ['1.0', '-1.0'],
          textStyle: { fontSize: 10 },
          inRange: {
            color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026']
          }
        },
        series: [{
          name: '相关系数',
          type: 'heatmap',
          data,
          label: {
            show: assets.length <= 10,
            formatter: params => Number(params.value[2]).toFixed(2),
            fontSize: 9
          },
          emphasis: { itemStyle: { borderColor: '#333', borderWidth: 1 } }
        }]
      }, true);
    },
    formatPct(num) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      return `${(Number(num) * 100).toFixed(2)}%`;
    },
    returnClass(value) {
      if (value === null || value === undefined || value === 0) return 'number-neutral';
      return value > 0 ? 'number-positive' : 'number-negative';
    }
  }
};
</script>

<style scoped>
.risk-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 16px;
}

.risk-block {
  min-width: 0;
}

.risk-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
}

.risk-hint {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
}

.risk-chart {
  width: 100%;
  height: 460px;
}

.over-p75 {
  color: #F56C6C;
  font-weight: 600;
}

@media (max-width: 1400px) {
  .risk-grid {
    grid-template-columns: 1fr;
  }
}
</style>
