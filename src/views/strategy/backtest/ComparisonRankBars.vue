<template>
  <div class="comparison-rank-bars">
    <el-row :gutter="16">
      <el-col :span="8" v-for="metric in rankMetrics" :key="metric.key" style="margin-bottom: 16px;">
        <div class="rank-chart-wrapper">
          <div class="rank-chart-title">{{ metric.label }}</div>
          <div :ref="'rankChart_' + metric.key" style="width: 100%; height: 160px;"></div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script>
import * as echarts from 'echarts';

export default {
  name: 'ComparisonRankBars',
  props: {
    /** 可见策略列表 [{key, name, color, metrics}] */
    strategies: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      charts: {}
    };
  },
  computed: {
    /** 需要排名的指标（数据驱动） */
    rankMetrics() {
      return [
        { key: 'annual_return', label: '年化收益率', format: v => (v * 100).toFixed(2) + '%', better: 'max' },
        { key: 'sharpe_ratio', label: '夏普比率', format: v => v.toFixed(3), better: 'max' },
        { key: 'calmar_ratio', label: 'Calmar比率', format: v => v.toFixed(3), better: 'max' },
        { key: 'volatility', label: '年化波动率', format: v => (v * 100).toFixed(2) + '%', better: 'min' },
        { key: 'max_drawdown', label: '最大回撤', format: v => (v * 100).toFixed(2) + '%', better: 'max' },
        { key: 'win_rate', label: '胜率', format: v => v != null ? (v * 100).toFixed(1) + '%' : '-', better: 'max' }
      ];
    }
  },
  watch: {
    strategies: {
      handler() {
        this.$nextTick(() => this.renderAllCharts());
      },
      deep: true
    }
  },
  mounted() {
    this.$nextTick(() => this.renderAllCharts());
    this._resizeHandler = () => {
      Object.values(this.charts).forEach(c => { if (c && !c.isDisposed()) c.resize(); });
    };
    window.addEventListener('resize', this._resizeHandler);
  },
  beforeDestroy() {
    window.removeEventListener('resize', this._resizeHandler);
    Object.values(this.charts).forEach(c => { if (c) c.dispose(); });
    this.charts = {};
  },
  methods: {
    renderAllCharts() {
      this.rankMetrics.forEach(metric => {
        this.renderSingleChart(metric);
      });
    },
    renderSingleChart(metric) {
      const refKey = 'rankChart_' + metric.key;
      const doms = this.$refs[refKey];
      const dom = Array.isArray(doms) ? doms[0] : doms;
      if (!dom || dom.offsetWidth === 0) return;

      let chart = this.charts[metric.key];
      if (!chart || chart.isDisposed()) {
        chart = echarts.init(dom);
        this.charts[metric.key] = chart;
      }

      // 构建排序数据
      const items = this.strategies
        .map(s => ({
          name: s.name,
          value: (s.metrics && s.metrics[metric.key]) || 0,
          color: s.color
        }))
        .filter(item => item.value != null);

      // 排序：better=max 时降序（最大在上），better=min 时升序（最小在上）
      items.sort((a, b) => {
        if (metric.better === 'min') return a.value - b.value;
        return b.value - a.value;
      });

      // 颜色：最优绿色，最差红色，中间用策略自身颜色
      const barColors = items.map((item, idx) => {
        if (items.length <= 1) return item.color;
        if (idx === 0) return '#67C23A'; // 最优
        if (idx === items.length - 1) return '#F56C6C'; // 最差
        return item.color;
      });

      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params) => {
            const p = params[0];
            return `${p.name}: ${metric.format(p.value)}`;
          }
        },
        grid: {
          left: 10,
          right: 60,
          top: 5,
          bottom: 5,
          containLabel: true
        },
        xAxis: {
          type: 'value',
          show: false
        },
        yAxis: {
          type: 'category',
          data: items.map(i => i.name),
          inverse: true,
          axisLabel: {
            fontSize: 11,
            color: '#606266',
            width: 80,
            overflow: 'truncate'
          },
          axisTick: { show: false },
          axisLine: { show: false }
        },
        series: [{
          type: 'bar',
          data: items.map((item, idx) => ({
            value: metric.key === 'volatility' || metric.key === 'win_rate' || metric.key === 'max_drawdown' || metric.key === 'annual_return'
              ? item.value * 100
              : item.value,
            itemStyle: { color: barColors[idx], borderRadius: [0, 3, 3, 0] }
          })),
          barWidth: 14,
          label: {
            show: true,
            position: 'right',
            fontSize: 10,
            color: '#909399',
            formatter: (params) => {
              const raw = items[params.dataIndex] ? items[params.dataIndex].value : 0;
              return metric.format(raw);
            }
          }
        }]
      };

      chart.setOption(option, true);
    }
  }
};
</script>

<style scoped>
.comparison-rank-bars {
  width: 100%;
}
.rank-chart-wrapper {
  background: #fafafa;
  border-radius: 6px;
  padding: 10px 8px 4px;
  border: 1px solid #f0f0f0;
}
.rank-chart-title {
  font-size: 12px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
  padding-left: 4px;
}
</style>
