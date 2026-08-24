<template>
  <div class="comparison-scatter-chart">
    <div ref="chartDom" style="width: 100%; height: 380px;"></div>
  </div>
</template>

<script>
import * as echarts from 'echarts';

export default {
  name: 'ComparisonScatterChart',
  props: {
    /** 可见策略列表 [{key, name, color, metrics: {annual_return, volatility, sharpe_ratio}}] */
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
    chartOption() {
      if (!this.strategies || this.strategies.length === 0) return null;

      const data = this.strategies.map(s => {
        const vol = ((s.metrics && s.metrics.volatility) || 0) * 100;
        const ret = ((s.metrics && s.metrics.annual_return) || 0) * 100;
        const sharpe = (s.metrics && s.metrics.sharpe_ratio) || 0;
        return {
          name: s.name,
          value: [vol, ret, Math.max(Math.abs(sharpe) * 15, 12)],
          itemStyle: { color: s.color },
          _sharpe: sharpe
        };
      });

      // 计算辅助线范围
      const maxVol = Math.max(...data.map(d => d.value[0]), 10);
      const rf = 2.0; // 无风险利率 2%

      return {
        tooltip: {
          trigger: 'item',
          formatter: (params) => {
            const d = params.data;
            return `<strong>${d.name}</strong><br/>` +
              `年化收益: ${d.value[1].toFixed(2)}%<br/>` +
              `年化波动: ${d.value[0].toFixed(2)}%<br/>` +
              `夏普比率: ${d._sharpe.toFixed(3)}`;
          }
        },
        grid: {
          left: 70,
          right: 40,
          top: 40,
          bottom: 60
        },
        xAxis: {
          type: 'value',
          name: '年化波动率 (%)',
          nameLocation: 'center',
          nameGap: 35,
          axisLabel: { formatter: '{value}%' },
          splitLine: { lineStyle: { type: 'dashed', color: '#eee' } }
        },
        yAxis: {
          type: 'value',
          name: '年化收益率 (%)',
          axisLabel: { formatter: '{value}%' },
          splitLine: { lineStyle: { type: 'dashed', color: '#eee' } }
        },
        series: [
          {
            type: 'scatter',
            data: data,
            symbolSize: (val) => val[2],
            label: {
              show: true,
              formatter: (params) => params.data.name,
              position: 'top',
              fontSize: 11,
              color: '#606266'
            },
            emphasis: {
              itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' }
            }
          },
          // 无风险利率水平线
          {
            type: 'line',
            markLine: {
              silent: true,
              symbol: 'none',
              lineStyle: { color: '#909399', type: 'dashed', width: 1 },
              label: { formatter: '无风险利率', position: 'insideEndTop', fontSize: 10 },
              data: [{ yAxis: rf }]
            }
          },
          // 等夏普比率射线 (Sharpe=1)
          {
            type: 'line',
            markLine: {
              silent: true,
              symbol: 'none',
              lineStyle: { color: '#67C23A', type: 'dotted', width: 1 },
              label: { formatter: 'Sharpe=1', position: 'insideEndTop', fontSize: 10 },
              data: [[{ coord: [0, rf] }, { coord: [maxVol, rf + maxVol] }]]
            }
          }
        ]
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
.comparison-scatter-chart {
  width: 100%;
}
</style>
