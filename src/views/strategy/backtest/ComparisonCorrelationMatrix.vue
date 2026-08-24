<template>
  <div class="comparison-correlation-matrix">
    <div ref="chartDom" style="width: 100%; height: 340px;"></div>
    <div v-if="!hasData" class="no-data-tip">策略数量不足或数据不够，无法计算相关性</div>
  </div>
</template>

<script>
import * as echarts from 'echarts';

export default {
  name: 'ComparisonCorrelationMatrix',
  props: {
    /** 相关性矩阵 { names: [策略名], matrix: [[相关系数]] } */
    correlationData: {
      type: Object,
      default: () => ({ names: [], matrix: [] })
    }
  },
  data() {
    return {
      chart: null
    };
  },
  computed: {
    hasData() {
      return this.correlationData &&
        this.correlationData.names &&
        this.correlationData.names.length >= 2 &&
        this.correlationData.matrix &&
        this.correlationData.matrix.length >= 2;
    },
    chartOption() {
      if (!this.hasData) return null;

      const { names, matrix } = this.correlationData;
      const heatData = [];
      for (let i = 0; i < names.length; i++) {
        for (let j = 0; j < names.length; j++) {
          heatData.push([j, i, matrix[i][j] != null ? parseFloat(matrix[i][j].toFixed(2)) : 0]);
        }
      }

      return {
        tooltip: {
          position: 'top',
          formatter: (params) => {
            const x = names[params.data[0]];
            const y = names[params.data[1]];
            const val = params.data[2];
            return `${y}<br/>vs ${x}<br/>相关系数: <strong>${val.toFixed(2)}</strong>`;
          }
        },
        grid: {
          left: 100,
          right: 60,
          top: 10,
          bottom: 80
        },
        xAxis: {
          type: 'category',
          data: names,
          axisLabel: {
            rotate: 30,
            fontSize: 11,
            color: '#606266',
            interval: 0,
            formatter: (val) => val.length > 6 ? val.substring(0, 6) + '…' : val
          },
          splitArea: { show: true }
        },
        yAxis: {
          type: 'category',
          data: names,
          axisLabel: {
            fontSize: 11,
            color: '#606266',
            formatter: (val) => val.length > 8 ? val.substring(0, 8) + '…' : val
          },
          splitArea: { show: true }
        },
        visualMap: {
          min: -1,
          max: 1,
          calculable: true,
          orient: 'vertical',
          right: 0,
          top: 'center',
          itemHeight: 120,
          inRange: {
            color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026']
          },
          textStyle: { fontSize: 10 }
        },
        series: [{
          type: 'heatmap',
          data: heatData,
          label: {
            show: names.length <= 6,
            fontSize: 11,
            formatter: (params) => params.data[2].toFixed(2)
          },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' }
          }
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
.comparison-correlation-matrix {
  width: 100%;
  position: relative;
}
.no-data-tip {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: #909399;
  font-size: 13px;
}
</style>
