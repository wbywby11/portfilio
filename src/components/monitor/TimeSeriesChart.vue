<template>
  <div class="time-series-chart" :style="{ height: chartHeight }">
    <div ref="chart" class="time-series-chart__canvas"></div>
    <el-empty v-if="isEmpty" :description="emptyText" :image-size="60" class="time-series-chart__empty"></el-empty>
  </div>
</template>

<script>
import * as echarts from 'echarts';

const DEFAULT_PALETTE = ['#409EFF', '#909399', '#E6A23C', '#67C23A', '#F56C6C', '#9B59B6'];

/**
 * TimeSeriesChart —— 配置驱动的时间序列图表（ECharts 封装）。
 *
 * props：
 *   xData: ['2024-01-02', ...]
 *   series: [{
 *     name, type: 'line' | 'bar', data,
 *     yAxis: 0 | 1,          // 对应 yAxis 配置索引；layout='split' 时同时决定所在子图
 *     color, lineWidth, dashed, smooth, symbol, connectNulls,
 *     area: true,            // 渐变面积
 *     areaOpacity: 0.22,
 *     barMaxWidth: 6, opacity: 0.55
 *   }]
 *   yAxis: [{ name, format: 'number' | 'percent', position, scale, min, max, unit, splitLine }]
 *   layout: 'overlay'（多轴同一图） | 'split'（主图 + 下方迷你子图）
 *   threshold: { value, label, color, width, dashed }        // 阈值线（风控红线）
 *   thresholdZone: { above, color }                          // 超出阈值区域高亮
 *   legend, dataZoom, height, emptyText
 */
export default {
  name: 'TimeSeriesChart',
  props: {
    xData: {
      type: Array,
      default: () => []
    },
    series: {
      type: Array,
      default: () => []
    },
    yAxis: {
      type: Array,
      default: () => []
    },
    layout: {
      type: String,
      default: 'overlay'
    },
    /** 显式定义多个子图（优先于 layout）；yAxis 项用 grid 指定所属子图 */
    grids: {
      type: Array,
      default: null
    },
    /** X 轴标签格式化（如按日期粒度稀疏显示） */
    xAxisLabelFormatter: {
      type: Function,
      default: null
    },
    /** X 轴标签旋转角度（类别多时可传 45） */
    xAxisRotate: {
      type: Number,
      default: 0
    },
    threshold: {
      type: Object,
      default: null
    },
    thresholdZone: {
      type: Object,
      default: null
    },
    legend: {
      type: Boolean,
      default: true
    },
    dataZoom: {
      type: Boolean,
      default: true
    },
    height: {
      type: [Number, String],
      default: 360
    },
    emptyText: {
      type: String,
      default: '暂无数据'
    }
  },
  data() {
    return {
      chart: null
    };
  },
  computed: {
    chartHeight() {
      return typeof this.height === 'number' ? this.height + 'px' : this.height;
    },
    isEmpty() {
      return !this.xData || this.xData.length === 0 || !this.series || this.series.length === 0;
    },
    isSplit() {
      return this.layout === 'split';
    },
    yAxisDefs() {
      if (this.yAxis && this.yAxis.length) return this.yAxis;
      return [{ name: '', format: 'number' }];
    },
    /** 子图布局：显式 grids > split 两图 > 单图 */
    gridDefs() {
      if (this.grids && this.grids.length) return this.grids;
      if (this.isSplit) {
        return [
          { left: '3%', right: '4%', top: 44, height: '54%', containLabel: true },
          { left: '3%', right: '4%', top: '68%', height: '14%', containLabel: true }
        ];
      }
      return [{ left: '3%', right: '4%', top: 44, bottom: this.dataZoom ? 52 : 16, containLabel: true }];
    }
  },
  watch: {
    xData: {
      deep: true,
      handler() {
        this.renderChart();
      }
    },
    series: {
      deep: true,
      handler() {
        this.renderChart();
      }
    },
    threshold: {
      deep: true,
      handler() {
        this.renderChart();
      }
    },
    thresholdZone: {
      deep: true,
      handler() {
        this.renderChart();
      }
    }
  },
  mounted() {
    window.addEventListener('resize', this.handleResize);
    this.$nextTick(() => this.renderChart());
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.handleResize);
    if (this.chart) {
      this.chart.dispose();
      this.chart = null;
    }
  },
  methods: {
    handleResize() {
      if (this.chart) {
        this.chart.resize();
      } else {
        this.renderChart();
      }
    },
    renderChart() {
      if (this.isEmpty) {
        this.disposeChart();
        return;
      }
      const el = this.$refs.chart;
      if (!el || el.clientWidth === 0 || el.clientHeight === 0) {
        // 容器尚未布局（页签懒加载）：下一帧重试
        this.$nextTick(() => {
          const retryEl = this.$refs.chart;
          if (retryEl && retryEl.clientWidth > 0) this.renderChart();
        });
        return;
      }
      if (!this.chart) this.chart = echarts.init(el);
      this.chart.setOption(this.buildOption(), true);
    },
    disposeChart() {
      if (this.chart) {
        this.chart.dispose();
        this.chart = null;
      }
    },
    buildOption() {
      const grids = this.gridDefs;
      const xAxes = grids.map((_, index) => this.buildXAxis(index, index === 0));

      return {
        animation: false,
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          formatter: params => this.formatTooltip(params)
        },
        legend: this.legend
          ? {
              top: 4,
              itemGap: 18,
              textStyle: { fontSize: 12, color: '#606266' },
              data: this.series.map(s => s.name)
            }
          : { show: false },
        grid: grids,
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        dataZoom: this.dataZoom
          ? [
              { type: 'inside', xAxisIndex: grids.map((_, i) => i), start: 0, end: 100 },
              { type: 'slider', xAxisIndex: grids.map((_, i) => i), start: 0, end: 100, bottom: 6, height: 16 }
            ]
          : [],
        xAxis: xAxes,
        yAxis: this.buildYAxes(),
        series: this.buildSeries()
      };
    },
    buildXAxis(index, showLabel) {
      let label = { color: '#909399', hideOverlap: true, rotate: this.xAxisRotate || 0 };
      if (this.xAxisLabelFormatter) label = Object.assign({}, label, { formatter: this.xAxisLabelFormatter });
      return {
        type: 'category',
        gridIndex: index,
        data: this.xData,
        boundaryGap: index !== 0,
        axisLine: showLabel ? { lineStyle: { color: '#dcdfe6' } } : { show: false },
        axisTick: { show: false },
        axisLabel: showLabel ? label : { show: false },
        splitLine: { show: false }
      };
    },
    /** yAxis 索引 → 所属子图索引 */
    gridIndexOfAxis(axisIndex) {
      const def = this.yAxisDefs[axisIndex] || {};
      if (def.grid !== undefined && def.grid !== null) return Number(def.grid);
      if (this.isSplit) return Math.min(axisIndex, this.gridDefs.length - 1);
      return 0;
    },
    buildYAxes() {
      return this.yAxisDefs.map((def, index) => {
        const isPrimary = index === 0;
        return {
          type: 'value',
          gridIndex: this.gridIndexOfAxis(index),
          name: def.name || '',
          position: def.position || (isPrimary ? 'left' : 'right'),
          scale: def.scale !== false,
          min: def.min,
          max: def.max,
          splitNumber: def.splitNumber,
          nameTextStyle: { color: '#909399', fontSize: 11 },
          nameGap: def.nameGap === undefined ? 12 : def.nameGap,
          axisLine: {
            show: def.axisLine === undefined ? isPrimary : def.axisLine,
            lineStyle: { color: '#dcdfe6' }
          },
          axisTick: { show: false },
          axisLabel: {
            color: def.labelColor || '#909399',
            fontSize: def.fontSize || (isPrimary ? 11 : 10),
            margin: def.labelMargin === undefined ? 8 : def.labelMargin,
            formatter: value => this.formatAxisValue(value, def)
          },
          splitLine: {
            show: def.splitLine !== false,
            lineStyle: { color: '#f2f4f7' }
          }
        };
      });
    },
    buildSeries() {
      return this.series.map((item, index) => {
        const color = typeof item.color === 'function'
          ? item.color
          : item.color || DEFAULT_PALETTE[index % DEFAULT_PALETTE.length];
        const yIndex = item.yAxis || 0;
        const base = {
          name: item.name,
          type: item.type || 'line',
          data: item.data,
          xAxisIndex: this.gridIndexOfAxis(yIndex),
          yAxisIndex: yIndex,
          connectNulls: item.connectNulls === true
        };
        if (item.type === 'bar') {
          base.barMaxWidth = item.barMaxWidth || 6;
          base.itemStyle = {
            color: typeof item.color === 'function' ? item.color : color,
            opacity: item.opacity === undefined ? 0.55 : item.opacity
          };
        } else {
          base.smooth = item.smooth !== false;
          base.symbol = item.symbol || 'none';
          base.lineStyle = {
            width: item.lineWidth || 2.5,
            color,
            type: item.dashed ? 'dashed' : 'solid'
          };
          if (item.area) {
            base.areaStyle = { color: this.areaGradient(color, item.areaOpacity) };
          }
        }
        if (index === 0) {
          const markLine = this.buildThresholdMarkLine(color);
          if (markLine) base.markLine = markLine;
          const markArea = this.buildThresholdZoneMarkArea();
          if (markArea) base.markArea = markArea;
        }
        return base;
      });
    },
    buildThresholdMarkLine(defaultColor) {
      if (!this.threshold || this.threshold.value === null || this.threshold.value === undefined) {
        return null;
      }
      const lineColor = this.threshold.color || '#F56C6C';
      const label = this.threshold.label || '阈值 ' + Number(this.threshold.value).toFixed(2);
      const formatter = this.threshold.labelFormatter
        ? this.threshold.labelFormatter(this.threshold.value)
        : label;
      return {
        silent: true,
        symbol: 'none',
        data: [{
          yAxis: Number(this.threshold.value),
          lineStyle: {
            color: lineColor,
            type: this.threshold.dashed === false ? 'solid' : 'dashed',
            width: this.threshold.width || 2.5
          },
          label: {
            formatter,
            position: 'insideEndTop',
            backgroundColor: lineColor,
            color: '#fff',
            padding: [3, 8],
            borderRadius: 3,
            fontSize: 11
          }
        }]
      };
    },
    buildThresholdZoneMarkArea() {
      if (!this.thresholdZone || this.thresholdZone.above === null || this.thresholdZone.above === undefined) {
        return null;
      }
      const above = Number(this.thresholdZone.above);
      const values = [];
      this.series.forEach(item => {
        if (item.type === 'bar') return;
        (item.data || []).forEach(v => {
          const n = Number(v);
          if (!Number.isNaN(n)) values.push(n);
        });
      });
      const dataMax = values.length ? Math.max.apply(null, values) : above * 2;
      const top = Math.max(dataMax, above) * 1.15;
      return {
        silent: true,
        itemStyle: { color: this.thresholdZone.color || 'rgba(245, 108, 108, 0.06)' },
        label: { show: false },
        data: [[{ yAxis: above }, { yAxis: top }]]
      };
    },
    areaGradient(color, opacity) {
      const rgb = this.hexToRgb(color);
      const top = opacity === undefined || opacity === null ? 0.22 : opacity;
      return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: 'rgba(' + rgb + ', ' + top + ')' },
        { offset: 1, color: 'rgba(' + rgb + ', 0.01)' }
      ]);
    },
    hexToRgb(color) {
      const hex = String(color || '').replace('#', '');
      if (/^[0-9a-fA-F]{6}$/.test(hex)) {
        return [
          parseInt(hex.slice(0, 2), 16),
          parseInt(hex.slice(2, 4), 16),
          parseInt(hex.slice(4, 6), 16)
        ].join(',');
      }
      return '64, 158, 255';
    },
    formatAxisValue(value, def) {
      const p = def.precision === undefined ? (def.format === 'percent' ? 1 : 2) : def.precision;
      if (def.format === 'percent') return Number(value).toFixed(p) + '%';
      if (def.format === 'number') return Number(value).toFixed(p);
      return value;
    },
    formatTooltip(params) {
      if (!params || !params.length) return '';
      let html = params[0].axisValue + '<br/>';
      params.forEach(param => {
        if (param.data === null || param.data === undefined) return;
        const def = this.yAxisDefs[(this.series[param.seriesIndex] || {}).yAxis || 0] || {};
        const value = Number(param.data);
        let text;
        if (def.format === 'percent') {
          text = value.toFixed(def.precision === undefined ? 2 : def.precision) + '%';
        } else if (def.format === 'number') {
          text = value.toFixed(def.precision === undefined ? 4 : def.precision);
        } else {
          text = param.data;
        }
        html += param.marker + param.seriesName + ': ' + text + '<br/>';
      });
      return html;
    }
  }
};
</script>

<style scoped>
.time-series-chart {
  position: relative;
  width: 100%;
  min-width: 0;
}

.time-series-chart__canvas {
  width: 100%;
  height: 100%;
}

.time-series-chart__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
