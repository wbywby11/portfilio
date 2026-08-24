<template>
  <div class="comparison-radar-chart">
    <div ref="chartDom" style="width: 100%; height: 380px;"></div>
  </div>
</template>

<script>
import * as echarts from 'echarts';

export default {
  name: 'ComparisonRadarChart',
  props: {
    /** 可见策略列表 [{key, name, color, metrics: {annual_return, sharpe_ratio, ...}}] */
    strategies: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      chart: null
    };
  },
  computed: {
    /** 雷达图维度定义（数据驱动，从策略指标中提取） */
    radarDimensions() {
      return [
        { key: 'annual_return', label: '年化收益', normalize: v => v },
        { key: 'sharpe_ratio', label: '夏普比率', normalize: v => v },
        { key: 'calmar_ratio', label: 'Calmar', normalize: v => v },
        { key: 'win_rate', label: '胜率', normalize: v => v },
        { key: 'max_drawdown', label: '抗回撤', normalize: v => 1 - Math.abs(v || 0) },
        { key: 'volatility', label: '低波动', normalize: v => 1 - (v || 0) }
      ];
    },
    /** 计算各维度的最大值（用于归一化） */
    dimensionMaxes() {
      const maxes = {};
      this.radarDimensions.forEach(dim => {
        let max = 0;
        this.strategies.forEach(s => {
          const raw = (s.metrics && s.metrics[dim.key]) || 0;
          const val = dim.normalize(raw);
          if (val > max) max = val;
        });
        maxes[dim.key] = max || 1;
      });
      return maxes;
    },
    chartOption() {
      if (!this.strategies || this.strategies.length === 0) return null;

      const indicator = this.radarDimensions.map(dim => ({
        name: dim.label,
        max: 1.0
      }));

      const seriesData = this.strategies.map(s => {
        const values = this.radarDimensions.map(dim => {
          const raw = (s.metrics && s.metrics[dim.key]) || 0;
          const normalized = dim.normalize(raw);
          const max = this.dimensionMaxes[dim.key] || 1;
          return Math.max(0, Math.min(1, normalized / max));
        });
        return {
          name: s.name,
          value: values,
          lineStyle: { color: s.color, width: 2 },
          itemStyle: { color: s.color },
          areaStyle: { color: s.color, opacity: 0.1 }
        };
      });

      return {
        tooltip: {
          trigger: 'item',
          formatter: (params) => {
            const s = this.strategies[params.seriesIndex];
            if (!s) return '';
            let html = `<strong>${s.name}</strong><br/>`;
            this.radarDimensions.forEach((dim, i) => {
              const raw = (s.metrics && s.metrics[dim.key]) || 0;
              const display = dim.key === 'volatility' || dim.key === 'win_rate' || dim.key === 'max_drawdown'
                ? (raw * 100).toFixed(2) + '%'
                : raw.toFixed(3);
              html += `${dim.label}: ${display}<br/>`;
            });
            return html;
          }
        },
        legend: {
          data: this.strategies.map(s => s.name),
          bottom: 0,
          type: 'scroll'
        },
        radar: {
          indicator,
          shape: 'polygon',
          splitNumber: 4,
          axisName: {
            color: '#606266',
            fontSize: 12
          },
          splitArea: {
            areaStyle: {
              color: ['rgba(64,158,255,0.02)', 'rgba(64,158,255,0.04)', 'rgba(64,158,255,0.06)', 'rgba(64,158,255,0.08)']
            }
          }
        },
        series: [{
          type: 'radar',
          data: seriesData
        }]
      };
    }
  },
  watch: {
    chartOption: {
      handler(opt) {
        if (opt) this.$nextTick(() => this.renderChart());
      },
      deep: true
    }
  },
  mounted() {
    this.$nextTick(() => this.renderChart());
    this._resizeHandler = () => { if (this.chart && !this.chart.isDisposed()) this.chart.resize(); };
    window.addEventListener('resize', this._resizeHandler);
  },
  beforeDestroy() {
    window.removeEventListener('resize', this._resizeHandler);
    if (this.chart) { this.chart.dispose(); this.chart = null; }
  },
  methods: {
    renderChart() {
      const dom = this.$refs.chartDom;
      if (!dom || dom.offsetWidth === 0) return;
      if (!this.chart || this.chart.isDisposed()) {
        this.chart = echarts.init(dom);
      }
      if (this.chartOption) {
        this.chart.setOption(this.chartOption, true);
      }
    }
  }
};
</script>

<style scoped>
.comparison-radar-chart {
  width: 100%;
}
</style>
