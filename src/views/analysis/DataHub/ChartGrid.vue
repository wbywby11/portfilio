<template>
  <el-row v-if="entries.length" :gutter="16" class="charts-row">
    <el-col
      v-for="item in entries"
      :key="item.id"
      :span="12"
    >
      <el-card class="chart-card" shadow="never">
        <div slot="header" class="clearfix">
          <span><i class="el-icon-data-line"></i> {{ item.title }}</span>
        </div>
        <div :ref="'chart_' + item.id" class="chart" :data-cid="item.id"></div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script>
import * as echarts from 'echarts';

export default {
  name: 'DataHubChartGrid',
  props: {
    /** stats/overview 返回的 charts 对象 */
    charts: { type: Object, default: () => ({}) }
  },
  data() {
    return { instances: {} };
  },
  computed: {
    entries() {
      const c = this.charts || {};
      return Object.keys(c).map(id => ({ id, ...c[id] }));
    }
  },
  watch: {
    charts: {
      handler() {
        this.$nextTick(() => this.renderAll());
      },
      deep: true
    },
    entries: {
      handler() {
        this.$nextTick(() => this.renderAll());
      },
      deep: true
    }
  },
  mounted() {
    window.addEventListener('resize', this.onResize);
    this.$nextTick(() => this.renderAll());
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.onResize);
    Object.values(this.instances).forEach(ch => {
      if (ch && !ch.isDisposed()) ch.dispose();
    });
    this.instances = {};
  },
  methods: {
    onResize() {
      Object.values(this.instances).forEach(ch => {
        if (ch && !ch.isDisposed()) ch.resize();
      });
    },
    domRef(cid) {
      const r = this.$refs['chart_' + cid];
      return Array.isArray(r) ? r[0] : r;
    },
    renderAll() {
      this.entries.forEach(it => this.renderOne(it.id, it));
    },
    ringColor(label) {
      const lv = String(label || '');
      if (lv.indexOf('红') >= 0) return '#F56C6C';
      if (lv.indexOf('橙') >= 0) return '#E6A23C';
      if (lv.indexOf('黄') >= 0) return '#F7D257';
      if (lv.indexOf('蓝') >= 0 || lv.indexOf('信息') >= 0) return '#409EFF';
      if (lv.indexOf('绿') >= 0) return '#67C23A';
      return '#909399';
    },
    renderOne(id, cfg) {
      const dom = this.domRef(id);
      if (!dom || !(cfg.items && cfg.items.length)) return;
      let ch = this.instances[id];
      if (!ch) {
        ch = echarts.init(dom);
        this.instances[id] = ch;
      }
      const items = cfg.items || [];
      if ((cfg.chart_type || 'pie') === 'pie') {
        const colors = items.map((i, idx) => this.ringColor(i.label));
        ch.setOption(
          {
            tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
            legend: { bottom: 4, type: 'scroll' },
            series: [
              {
                name: cfg.title || id,
                type: 'pie',
                radius: ['38%', '68%'],
                center: ['50%', '45%'],
                avoidLabelOverlap: true,
                itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
                label: { show: true, formatter: '{b}\n{c}' },
                data: items.map((it, idx) => ({
                  name: it.label,
                  value: it.value,
                  itemStyle: { color: colors[idx] }
                }))
              }
            ]
          },
          true
        );
      } else {
        const labels = items.map(i => i.label);
        const values = items.map(i => i.value);
        ch.setOption(
          {
            tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
            grid: { top: 20, bottom: 24, left: 80, right: 16 },
            xAxis: { type: 'value' },
            yAxis: {
              type: 'category',
              data: labels,
              inverse: true,
              axisLabel: { interval: 0, fontSize: 11 }
            },
            series: [
              {
                type: 'bar',
                data: values,
                itemStyle: {
                  color: {
                    type: 'linear',
                    x: 0,
                    y: 0,
                    x2: 1,
                    y2: 0,
                    colorStops: [
                      { offset: 0, color: '#3a7bd5' },
                      { offset: 1, color: '#00d2ff' }
                    ]
                  },
                  borderRadius: [0, 4, 4, 0]
                },
                label: { show: true, position: 'right', fontSize: 11 },
                barWidth: 14
              }
            ]
          },
          true
        );
      }
      ch.resize();
    }
  }
};
</script>

<style scoped>
.charts-row {
  margin-bottom: 14px !important;
}
.chart-card {
  border: 1px solid #ebeef5;
  margin-bottom: 12px;
}
.chart {
  width: 100%;
  height: 300px;
}
</style>
