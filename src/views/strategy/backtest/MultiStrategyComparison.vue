<template>
  <div class="multi-strategy-comparison">
    <h3 style="margin-bottom: 20px;">📊 多策略对比分析</h3>

    <!-- 绩效指标对比表格 -->
    <el-card shadow="never" style="margin-bottom: 20px;">
      <div slot="header">
        <span>绩效指标对比</span>
      </div>
      <el-table :data="comparisonTable" border stripe>
        <el-table-column prop="strategy_name" label="策略名称" width="200" fixed="left"></el-table-column>
        <el-table-column prop="total_return" label="总收益率" width="120" align="right">
          <template slot-scope="scope">
            <span class="metric-cell" :class="getBestClass(scope.row.total_return, 'max', 'total_return')">
              {{ formatPercent(scope.row.total_return) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="annual_return" label="年化收益率" width="120" align="right">
          <template slot-scope="scope">
            <span class="metric-cell" :class="getBestClass(scope.row.annual_return, 'max', 'annual_return')">
              {{ formatPercent(scope.row.annual_return) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="volatility" label="年化波动率" width="120" align="right">
          <template slot-scope="scope">
            <span class="metric-cell" :class="getBestClass(scope.row.volatility, 'min', 'volatility')">
              {{ formatPercent(scope.row.volatility) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="max_drawdown" label="最大回撤" width="120" align="right">
          <template slot-scope="scope">
            <span class="metric-cell" :class="getBestClass(scope.row.max_drawdown, 'max', 'max_drawdown')">
              {{ formatPercent(scope.row.max_drawdown) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="sharpe_ratio" label="夏普比率" width="120" align="right">
          <template slot-scope="scope">
            <span class="metric-cell" :class="getBestClass(scope.row.sharpe_ratio, 'max', 'sharpe_ratio')">
              {{ formatNumber(scope.row.sharpe_ratio, 3) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="calmar_ratio" label="Calmar比率" width="120" align="right">
          <template slot-scope="scope">
            <span class="metric-cell" :class="getBestClass(scope.row.calmar_ratio, 'max', 'calmar_ratio')">
              {{ formatNumber(scope.row.calmar_ratio, 3) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="trade_count" label="交易次数" width="100" align="right"></el-table-column>
      </el-table>
    </el-card>

    <!-- 净值曲线对比 -->
    <el-card shadow="never" style="margin-bottom: 20px;">
      <div slot="header">
        <span>净值曲线对比</span>
      </div>
      <div id="comparison-nav-chart" style="height: 400px;"></div>
    </el-card>

    <!-- 波动率曲线对比 -->
    <el-card shadow="never" style="margin-bottom: 20px;" v-if="Object.keys(volatilityDataAll).length > 0">
      <div slot="header">
        <span>组合波动率监控对比</span>
      </div>
      <div id="comparison-volatility-chart" style="height: 400px;"></div>
    </el-card>

    <!-- 各策略详细结果 -->
    <el-card shadow="never">
      <div slot="header">
        <span>各策略详细结果</span>
      </div>
      <el-collapse v-model="activeNames" @change="handleCollapseChange">
        <el-collapse-item
          v-for="(resultData, resultKey) in results"
          :key="resultKey"
          :title="(resultData.strategy && resultData.strategy.name) || resultKey"
          :name="resultKey"
        >
          <single-strategy-result
            :key="singleStrategyResultKey(resultKey, resultData)"
            ref="strategyResults"
            :unique-chart-id="String(resultKey)"
            :strategy-name="(resultData.strategy && resultData.strategy.name) || resultKey"
            :result="resultData.result || {}"
            :strategy="resultData.strategy"
            :remark="resultData.remark"
            :record-id="resultData.record_id != null ? String(resultData.record_id) : (resultData.result && resultData.result.record_id != null ? String(resultData.result.record_id) : null)"
            :model-id="(resultData.strategy && resultData.strategy.id) ? String(resultData.strategy.id) : null"
            :is-multi-strategy="true"
          ></single-strategy-result>
        </el-collapse-item>
      </el-collapse>
    </el-card>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import SingleStrategyResult from './SingleStrategyResult.vue';

export default {
  name: 'MultiStrategyComparison',
  components: {
    SingleStrategyResult
  },
  props: {
    results: {
      type: Object,
      required: true
    }
  },
  data() {
    return {
      activeNames: []
    };
  },
  computed: {
    comparisonTable() {
      const table = [];
      for (const [resultKey, resultData] of Object.entries(this.results)) {
        const result = resultData.result;
        const displayName = (resultData.strategy && resultData.strategy.name) || resultKey;
        table.push({
          strategy_name: displayName,
          result_key: resultKey,
          total_return: result ? (result.total_return || 0) : 0,
          annual_return: result ? (result.annual_return || 0) : 0,
          volatility: result ? (result.volatility || 0) : 0,
          max_drawdown: result ? (result.max_drawdown || 0) : 0,
          sharpe_ratio: result ? (result.sharpe_ratio || 0) : 0,
          calmar_ratio: result ? (result.calmar_ratio || 0) : 0,
          trade_count: result && result.trades ? result.trades.length : 0
        });
      }
      return table;
    },
    navDataAll() {
      const navData = {};
      for (const [resultKey, resultData] of Object.entries(this.results)) {
        const result = resultData.result;
        const displayName = (resultData.strategy && resultData.strategy.name) || resultKey;
        if (!result) continue;
        if (result.snapshots && result.snapshots.length > 0) {
          const initialValue = result.snapshots[0].total_value || 1000000;
          navData[displayName] = result.snapshots.map(s => ({
            date: this.formatDate(s.time),
            nav: s.total_value / initialValue
          }));
        } else if (result.equity_curve && result.equity_curve.length > 0) {
          navData[displayName] = result.equity_curve.map(e => ({
            date: this.formatDate(e.date),
            nav: e.unit_value != null ? e.unit_value : (1 + (e.cumulative_return || 0))
          }));
        } else {
          console.warn('[多策略对比] 策略无有效快照或净值曲线，不参与净值对比 key=', resultKey, 'displayName=', displayName);
        }
      }
      return navData;
    },
    /** 各策略波动率序列，用于波动率监控对比图（优先用 portfolio_volatility，无则用净值序列计算滚动年化波动率） */
    volatilityDataAll() {
      const out = {};
      for (const [resultKey, resultData] of Object.entries(this.results)) {
        const result = resultData.result;
        const displayName = (resultData.strategy && resultData.strategy.name) || resultKey;
        if (!result || !result.snapshots || result.snapshots.length === 0) continue;
        const snapshots = result.snapshots;
        const withVol = snapshots.filter(s => s.portfolio_volatility != null);
        const hasBackendVol = withVol.length > 0;
        const allZeros = hasBackendVol && withVol.every(s => (s.portfolio_volatility || 0) === 0);
        if (hasBackendVol && !allZeros) {
          out[displayName] = withVol.map(s => ({ date: this.formatDate(s.time), volatility: s.portfolio_volatility }));
        } else {
          const rollWindow = 21;
          const initialValue = snapshots[0].total_value || 1;
          const navs = snapshots.map(s => (s.total_value || 0) / initialValue);
          out[displayName] = snapshots.map((s, i) => {
            const start = Math.max(0, i - rollWindow);
            const slice = navs.slice(start, i + 1);
            let annVol = 0;
            if (slice.length >= 2) {
              const returns = [];
              for (let j = 1; j < slice.length; j++) {
                returns.push((slice[j] - slice[j - 1]) / slice[j - 1]);
              }
              const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
              const variance = returns.reduce((sum, r) => sum + (r - mean) * (r - mean), 0) / returns.length;
              annVol = Math.sqrt(Math.max(0, variance)) * Math.sqrt(252);
            }
            return { date: this.formatDate(s.time), volatility: annVol };
          });
        }
      }
      return out;
    }
  },
  mounted() {
    console.log('[多策略对比] 接收到回测数据 策略数=', Object.keys(this.results || {}).length, 'keys=', Object.keys(this.results || {}));
    for (const [k, v] of Object.entries(this.results || {})) {
      const snap = (v && v.result && v.result.snapshots) ? v.result.snapshots.length : 0;
      console.log('[多策略对比] 主观策略回测信息 key=', k, 'strategyName=', (v && v.strategy && v.strategy.name) || k, 'snapshots=', snap, 'hasResult=', !!(v && v.result));
    }
    // 默认展开所有策略面板，使每个策略的图表容器有宽高，避免除第一个外图表为空
    this.activeNames = Object.keys(this.results || {});
    if (Object.keys(this.navDataAll).length > 0) {
      this.$nextTick(() => {
        this.initComparisonChart();
      });
    } else {
      console.warn('[多策略对比] 无策略有有效快照，不绘制净值曲线');
    }
    if (Object.keys(this.volatilityDataAll).length > 0) {
      this.$nextTick(() => {
        this.initVolatilityComparisonChart();
      });
    }
    // 延迟触发各策略子图表的绘制（此时折叠已展开，DOM 已有尺寸，多策略需更长时间确保持仓权重图标注正确）
    this.$nextTick(() => {
      setTimeout(() => this.handleCollapseChange(this.activeNames), 500);
    });
  },
  watch: {
    navDataAll() {
      if (Object.keys(this.navDataAll).length > 0) {
        this.$nextTick(() => {
          this.initComparisonChart();
        });
      }
    },
    volatilityDataAll() {
      if (Object.keys(this.volatilityDataAll).length > 0) {
        this.$nextTick(() => {
          this.initVolatilityComparisonChart();
        });
      }
    }
  },
  methods: {
    singleStrategyResultKey(strategyName, resultData) {
      const r = resultData && resultData.result;
      const snapLen = (r && r.snapshots && Array.isArray(r.snapshots)) ? r.snapshots.length : 0;
      return `${strategyName}_${snapLen}`;
    },
    initComparisonChart() {
      const chartDom = document.getElementById('comparison-nav-chart');
      if (!chartDom) return;
      const navKeys = Object.keys(this.navDataAll);
      console.log('[多策略对比] 绘制净值曲线 参与策略数=', navKeys.length, '策略名=', navKeys);
      if (navKeys.length === 0) {
        console.warn('[多策略对比] 无策略有快照数据，跳过图表绘制');
        return;
      }
      const myChart = echarts.init(chartDom);

      // 合并所有策略的日期（取并集并排序），避免仅用第一个策略日期导致其它策略曲线被截断
      // 此前仅用第一个策略的日期会令：1) 其它策略在更长期限的收益无法展示；2) 对比表格的累计收益与净值曲线最高点不一致
      const dateSet = new Set();
      for (const navData of Object.values(this.navDataAll)) {
        navData.forEach(d => dateSet.add(d.date));
      }
      const dates = Array.from(dateSet).sort();

      // 构建系列数据：对每个日期，若无当日快照则向前取最近一次净值（forward-fill）
      const series = [];
      const colors = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399'];
      let colorIndex = 0;

      for (const [strategyName, navData] of Object.entries(this.navDataAll)) {
        const navByDate = {};
        navData.forEach(d => { navByDate[d.date] = d.nav; });
        let lastNav = null;
        const navs = dates.map(date => {
          if (navByDate[date] != null) {
            lastNav = navByDate[date];
            return lastNav;
          }
          return lastNav; // forward-fill
        });

        series.push({
          name: strategyName,
          type: 'line',
          data: navs,
          smooth: 0.3,
          lineStyle: { width: 2 },
          itemStyle: {
            color: colors[colorIndex % colors.length]
          }
        });
        colorIndex++;
      }

      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross',
            crossStyle: { color: '#999' }
          }
        },
        legend: {
          data: Object.keys(this.navDataAll),
          bottom: 0
        },
        grid: {
          left: 80,
          right: '4%',
          bottom: '15%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: dates
        },
        yAxis: {
          type: 'value',
          name: '净值',
          axisLabel: {
            formatter: '{value}'
          }
        },
        series: series
      };

      myChart.setOption(option);
      console.log('[多策略对比] 净值曲线已绘制 series数=', series.length, 'dates数=', dates.length);
      
      // 响应式调整
      window.addEventListener('resize', () => {
        myChart.resize();
      });
    },
    initVolatilityComparisonChart() {
      const chartDom = document.getElementById('comparison-volatility-chart');
      if (!chartDom) return;
      const volKeys = Object.keys(this.volatilityDataAll);
      if (volKeys.length === 0) return;
      const existingChart = echarts.getInstanceByDom(chartDom);
      if (existingChart) existingChart.dispose();
      const myChart = echarts.init(chartDom);
      const dateSet = new Set();
      for (const volData of Object.values(this.volatilityDataAll)) {
        volData.forEach(d => dateSet.add(d.date));
      }
      const dates = Array.from(dateSet).sort();
      const series = [];
      const colors = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399'];
      volKeys.forEach((strategyName, idx) => {
        const volByDate = {};
        (this.volatilityDataAll[strategyName] || []).forEach(d => { volByDate[d.date] = d.volatility; });
        let lastVol = null;
        const vols = dates.map(date => {
          if (volByDate[date] != null) {
            lastVol = volByDate[date];
            return lastVol;
          }
          return lastVol;
        });
        series.push({
          name: strategyName,
          type: 'line',
          data: vols.map(v => v != null ? v * 100 : null),
          smooth: true,
          itemStyle: { color: colors[idx % colors.length] }
        });
      });
      myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: volKeys, bottom: 0 },
        grid: { left: 80, right: '4%', bottom: '15%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: {
          type: 'value',
          name: '年化波动率(%)',
          axisLabel: { formatter: '{value}%' }
        },
        series
      });
      window.addEventListener('resize', () => { if (myChart && !myChart.isDisposed()) myChart.resize(); });
    },
    formatPercent(num) {
      if (num === null || num === undefined) return '-';
      return (num * 100).toFixed(2) + '%';
    },
    formatNumber(num, precision = 2) {
      if (num === null || num === undefined) return '-';
      return parseFloat(num).toFixed(precision);
    },
    formatDate(dateStr) {
      if (!dateStr) return '-';
      if (typeof dateStr === 'string') {
        return dateStr.substring(0, 10);
      }
      try {
        const date = new Date(dateStr);
        return date.toISOString().split('T')[0];
      } catch (e) {
        return dateStr;
      }
    },
    getBestClass(value, type, column) {
      if (!value && value !== 0) return '';
      const values = this.comparisonTable.map(row => row[column]).filter(v => v !== null && v !== undefined);
      if (values.length === 0) return '';
      
      if (type === 'max') {
        const maxVal = Math.max(...values);
        // 对于回撤，是负值，所以最大值（最接近0）是最好的
        if (column === 'max_drawdown') {
          return value === maxVal ? 'best-value' : '';
        }
        return value === maxVal ? 'best-value' : '';
      } else {
        const minVal = Math.min(...values);
        return value === minVal ? 'best-value' : '';
      }
    },
    handleCollapseChange(activeNames) {
      // 当折叠面板展开时，重新初始化图表（延迟确保已展开的 DOM 有宽高，避免主观策略持仓权重图标注不绘制或错位）
      this.$nextTick(() => {
        setTimeout(() => {
          const refs = this.$refs.strategyResults;
          const list = Array.isArray(refs) ? refs : (refs ? [refs] : []);
          list.forEach(component => {
            if (component && typeof component.initAllCharts === 'function') {
              component.initAllCharts();
            }
          });
        }, 600);
      });
    }
  }
};
</script>

<style scoped>
.multi-strategy-comparison {
  padding: 20px 0;
}

>>> .el-table th {
  background-color: #f5f7fa;
  border-bottom: 2px solid #dcdfe6;
  font-weight: 600;
  color: #303133;
}

.metric-cell {
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.best-value {
  color: #67C23A;
  font-weight: 700;
  background: rgba(103, 194, 58, 0.08);
  border-radius: 4px;
  padding: 2px 6px;
  display: inline-block;
}

#comparison-nav-chart {
  width: 100%;
}
</style>
