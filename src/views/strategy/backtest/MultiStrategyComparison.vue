<template>
  <div class="multi-strategy-comparison">
    <!-- 顶部控制栏：周期选择 + 策略Toggle -->
    <div class="control-bar">
      <div class="period-selector">
        <el-radio-group v-model="activePeriod" size="small" @change="handlePeriodChange">
          <el-radio-button label="1m">近1月</el-radio-button>
          <el-radio-button label="3m">近3月</el-radio-button>
          <el-radio-button label="6m">近6月</el-radio-button>
          <el-radio-button label="1y">近1年</el-radio-button>
          <el-radio-button label="all">全部</el-radio-button>
        </el-radio-group>
      </div>
      <div class="strategy-chips">
        <span
          v-for="s in strategyList"
          :key="s.key"
          class="strategy-chip"
          :class="{ hidden: hiddenStrategies.includes(s.key) }"
          :style="{ borderColor: s.color, background: hiddenStrategies.includes(s.key) ? '#f5f5f5' : s.color + '18' }"
          @click="toggleStrategy(s.key)"
        >
          <span class="chip-dot" :style="{ background: hiddenStrategies.includes(s.key) ? '#c0c4cc' : s.color }"></span>
          {{ s.name }}
        </span>
      </div>
    </div>

    <!-- 概览卡片 -->
    <el-row :gutter="16" class="summary-cards" v-if="summaryCards.length > 0">
      <el-col :span="6" v-for="card in summaryCards" :key="card.label">
        <div class="summary-card">
          <div class="card-label">{{ card.label }}</div>
          <div class="card-value" :style="{ color: card.color }">{{ card.display }}</div>
          <div class="card-strategy">{{ card.strategyName }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- 绩效对比表格 -->
    <el-card shadow="never" class="section-card">
      <div slot="header"><span class="section-title">绩效指标对比</span></div>
      <el-table :data="comparisonTable" border stripe size="small" :default-sort="{ prop: 'sharpe_ratio', order: 'descending' }">
        <el-table-column prop="strategy_name" label="策略名称" min-width="160" fixed="left">
          <template slot-scope="scope">
            <span class="strategy-name-link" @click="openDrawer(scope.row)">
              <span class="name-dot" :style="{ background: scope.row._color }"></span>
              {{ scope.row.strategy_name }}
            </span>
          </template>
        </el-table-column>
        <el-table-column
          v-for="col in metricColumns"
          :key="col.key"
          :prop="col.key"
          :label="col.label"
          width="120"
          align="right"
          sortable
        >
          <template slot-scope="scope">
            <span
              class="metric-cell"
              :class="{ 'best-value': isBestValue(scope.row, col) }"
              :style="getCellStyle(scope.row, col)"
            >
              {{ formatMetric(scope.row[col.key], col.format) }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 净值曲线 + 回撤对比 -->
    <el-card shadow="never" class="section-card" v-if="visibleStrategies.length > 0">
      <div slot="header"><span class="section-title">净值走势与回撤对比</span></div>
      <el-row :gutter="20">
        <el-col :span="12">
          <div ref="navChart" style="width: 100%; height: 380px;"></div>
        </el-col>
        <el-col :span="12">
          <div ref="drawdownChart" style="width: 100%; height: 380px;"></div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 雷达图 + 散点图 -->
    <el-card shadow="never" class="section-card" v-if="visibleStrategies.length >= 2">
      <div slot="header"><span class="section-title">多维对比分析</span></div>
      <el-row :gutter="20">
        <el-col :span="12">
          <div class="sub-section-title">策略特征雷达图</div>
          <comparison-radar-chart :strategies="visibleStrategies"></comparison-radar-chart>
        </el-col>
        <el-col :span="12">
          <div class="sub-section-title">风险-收益散点图</div>
          <comparison-scatter-chart :strategies="visibleStrategies"></comparison-scatter-chart>
        </el-col>
      </el-row>
    </el-card>

    <!-- 指标排名条形图 -->
    <el-card shadow="never" class="section-card" v-if="visibleStrategies.length >= 2">
      <div slot="header"><span class="section-title">指标排名</span></div>
      <comparison-rank-bars :strategies="visibleStrategies"></comparison-rank-bars>
    </el-card>

    <!-- 相关性矩阵 + 波动率走势 -->
    <el-card shadow="never" class="section-card" v-if="visibleStrategies.length >= 2">
      <div slot="header"><span class="section-title">相关性与波动率</span></div>
      <el-row :gutter="20">
        <el-col :span="12">
          <div class="sub-section-title">策略收益相关性矩阵</div>
          <comparison-correlation-matrix :correlation-data="correlationData"></comparison-correlation-matrix>
        </el-col>
        <el-col :span="12">
          <div class="sub-section-title">滚动波动率走势</div>
          <div ref="volChart" style="width: 100%; height: 340px;"></div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 组合持仓穿透 -->
    <el-card shadow="never" class="section-card" v-if="portfolioRebalanceWeights">
      <div slot="header">
        <span class="section-title">组合资产持仓穿透（调仓日）</span>
        <span class="section-subtitle">穿透分析：策略权重 x 子策略内资产权重 = 组合实际资产持仓</span>
      </div>
      <div ref="positionChart" style="width: 100%; height: 420px;"></div>
    </el-card>

    <!-- 策略详情抽屉 -->
    <comparison-drawer
      :visible.sync="drawerVisible"
      :strategy-data="drawerStrategy"
    ></comparison-drawer>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import { downsampleMultiSeries } from '@/utils/downsample';
import ComparisonRadarChart from './ComparisonRadarChart.vue';
import ComparisonScatterChart from './ComparisonScatterChart.vue';
import ComparisonRankBars from './ComparisonRankBars.vue';
import ComparisonCorrelationMatrix from './ComparisonCorrelationMatrix.vue';
import ComparisonDrawer from './ComparisonDrawer.vue';

const PALETTE = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#48b8d0'
];

export default {
  name: 'MultiStrategyComparison',
  components: {
    ComparisonRadarChart,
    ComparisonScatterChart,
    ComparisonRankBars,
    ComparisonCorrelationMatrix,
    ComparisonDrawer
  },
  props: {
    results: {
      type: Object,
      required: true
    }
  },
  data() {
    return {
      activePeriod: 'all',
      hiddenStrategies: [],
      drawerVisible: false,
      drawerStrategy: null,
      charts: {},
      metricColumns: [
        { key: 'total_return', label: '总收益率', format: 'percent', better: 'max' },
        { key: 'annual_return', label: '年化收益率', format: 'percent', better: 'max' },
        { key: 'volatility', label: '年化波动率', format: 'percent', better: 'min' },
        { key: 'max_drawdown', label: '最大回撤', format: 'percent', better: 'max' },
        { key: 'sharpe_ratio', label: '夏普比率', format: 'number', better: 'max' },
        { key: 'calmar_ratio', label: 'Calmar', format: 'number', better: 'max' },
        { key: 'win_rate', label: '胜率', format: 'percent', better: 'max' },
        { key: 'trade_count', label: '交易次数', format: 'integer', better: null }
      ]
    };
  },
  computed: {
    /** 从 results 提取策略列表 */
    strategyList() {
      const list = [];
      let idx = 0;
      for (const [key, resultData] of Object.entries(this.results || {})) {
        if (!resultData || (!resultData.result && !resultData.strategy)) continue;
        list.push({
          key,
          name: (resultData.strategy && resultData.strategy.name) || key,
          color: PALETTE[idx % PALETTE.length],
          result: resultData.result || {},
          strategy: resultData.strategy || null,
          remark: resultData.remark || '',
          recordId: resultData.record_id != null ? String(resultData.record_id) : (resultData.result && resultData.result.record_id != null ? String(resultData.result.record_id) : null),
          modelId: (resultData.strategy && resultData.strategy.id) ? String(resultData.strategy.id) : null
        });
        idx++;
      }
      return list;
    },
    /** 可见策略（过滤隐藏的） */
    visibleStrategies() {
      return this.strategyList
        .filter(s => !this.hiddenStrategies.includes(s.key))
        .map(s => ({ ...s, metrics: this.getStrategyMetrics(s) }));
    },
    /** 所有策略日期的范围 */
    allDateRange() {
      let min = null, max = null;
      for (const s of this.strategyList) {
        const snaps = (s.result && s.result.snapshots) || [];
        if (snaps.length === 0) continue;
        const first = this.formatDate(snaps[0].time);
        const last = this.formatDate(snaps[snaps.length - 1].time);
        if (!min || first < min) min = first;
        if (!max || last > max) max = last;
      }
      return { start: min, end: max };
    },
    /** 根据 activePeriod 计算起始日期 */
    periodStartDate() {
      const { end } = this.allDateRange;
      if (!end || this.activePeriod === 'all') return null;
      const endDate = new Date(end);
      const map = { '1m': 1, '3m': 3, '6m': 6, '1y': 12 };
      const months = map[this.activePeriod];
      if (!months) return null;
      const start = new Date(endDate);
      start.setMonth(start.getMonth() - months);
      return start.toISOString().split('T')[0];
    },
    /** 绩效对比表格数据 */
    comparisonTable() {
      return this.visibleStrategies.map(s => {
        const m = s.metrics;
        return {
          strategy_name: s.name,
          _key: s.key,
          _color: s.color,
          _strategyData: s,
          total_return: m.total_return,
          annual_return: m.annual_return,
          volatility: m.volatility,
          max_drawdown: m.max_drawdown,
          sharpe_ratio: m.sharpe_ratio,
          calmar_ratio: m.calmar_ratio,
          win_rate: m.win_rate,
          trade_count: m.trade_count
        };
      });
    },
    /** 概览卡片 */
    summaryCards() {
      if (this.visibleStrategies.length === 0) return [];
      const cards = [];
      const findBest = (key, better) => {
        let best = null;
        this.visibleStrategies.forEach(s => {
          const v = s.metrics[key];
          if (v == null) return;
          if (!best || (better === 'max' ? v > best.metrics[key] : v < best.metrics[key])) best = s;
        });
        return best;
      };
      const bestReturn = findBest('annual_return', 'max');
      const bestSharpe = findBest('sharpe_ratio', 'max');
      const lowestVol = findBest('volatility', 'min');
      const smallestDD = findBest('max_drawdown', 'max');
      if (bestReturn) cards.push({ label: '最高年化收益', display: this.formatMetric(bestReturn.metrics.annual_return, 'percent'), strategyName: bestReturn.name, color: '#F56C6C' });
      if (bestSharpe) cards.push({ label: '最优夏普比率', display: this.formatMetric(bestSharpe.metrics.sharpe_ratio, 'number'), strategyName: bestSharpe.name, color: '#409EFF' });
      if (lowestVol) cards.push({ label: '最低波动率', display: this.formatMetric(lowestVol.metrics.volatility, 'percent'), strategyName: lowestVol.name, color: '#67C23A' });
      if (smallestDD) cards.push({ label: '最小回撤', display: this.formatMetric(smallestDD.metrics.max_drawdown, 'percent'), strategyName: smallestDD.name, color: '#E6A23C' });
      return cards;
    },
    /** 净值序列（日期并集 + forward-fill） */
    navSeriesData() {
      const dateSet = new Set();
      const strategyNavs = {};
      for (const s of this.visibleStrategies) {
        const snaps = this.getFilteredSnapshots(s);
        if (snaps.length === 0) continue;
        const initialValue = snaps[0].total_value || 1;
        const navByDate = {};
        snaps.forEach(snap => {
          const d = this.formatDate(snap.time);
          dateSet.add(d);
          navByDate[d] = snap.total_value / initialValue;
        });
        strategyNavs[s.key] = { name: s.name, color: s.color, navByDate };
      }
      const dates = Array.from(dateSet).sort();
      if (this.periodStartDate) {
        const filtered = dates.filter(d => d >= this.periodStartDate);
        return { dates: filtered, strategyNavs };
      }
      return { dates, strategyNavs };
    },
    /** 相关性矩阵数据 */
    correlationData() {
      const strategies = this.visibleStrategies.filter(s => {
        const snaps = this.getFilteredSnapshots(s);
        return snaps.length > 10;
      });
      if (strategies.length < 2) return { names: [], matrix: [] };

      // 提取各策略日收益率
      const returnsByStrategy = {};
      const dateSet = new Set();
      strategies.forEach(s => {
        const snaps = this.getFilteredSnapshots(s);
        const initialValue = snaps[0].total_value || 1;
        const navByDate = {};
        snaps.forEach(snap => {
          const d = this.formatDate(snap.time);
          navByDate[d] = snap.total_value / initialValue;
          dateSet.add(d);
        });
        returnsByStrategy[s.key] = { name: s.name, navByDate };
      });

      const dates = Array.from(dateSet).sort();
      // 仅取所有策略均有净值的公共日期，保证各策略收益率序列按日期严格对齐
      // （避免各策略缺失日期不同时，按索引截断导致相关系数计算在错位数据上）
      const commonDates = dates.filter(d => strategies.every(s => returnsByStrategy[s.key].navByDate[d] != null));
      // 计算日收益率（基于公共日期，天然等长对齐）
      const returnsMap = {};
      strategies.forEach(s => {
        const { navByDate } = returnsByStrategy[s.key];
        const returns = [];
        let prevNav = null;
        commonDates.forEach(d => {
          const nav = navByDate[d];
          if (prevNav != null && prevNav > 0) {
            returns.push((nav - prevNav) / prevNav);
          }
          prevNav = nav;
        });
        returnsMap[s.key] = returns;
      });

      // 收益率长度 = 公共日期数 - 1，至少需要 5 个收益率样本
      if (commonDates.length < 6) return { names: [], matrix: [] };

      const names = strategies.map(s => s.name);
      const alignedReturns = strategies.map(s => returnsMap[s.key]);

      // 计算 Pearson 相关系数
      const matrix = [];
      for (let i = 0; i < alignedReturns.length; i++) {
        matrix.push([]);
        for (let j = 0; j < alignedReturns.length; j++) {
          matrix[i].push(this.pearsonCorrelation(alignedReturns[i], alignedReturns[j]));
        }
      }
      return { names, matrix };
    },
    /** 组合持仓穿透数据 */
    portfolioRebalanceWeights() {
      for (const s of this.strategyList) {
        const tplCode = s.strategy && s.strategy.template_code;
        if (tplCode !== 'PORTFOLIO') continue;
        const snapshots = (s.result && s.result.snapshots) || [];
        const rebalanceSnapshots = snapshots.filter(snap => snap.is_rebalance_day && snap.weights);
        if (rebalanceSnapshots.length === 0) return null;
        return {
          dates: rebalanceSnapshots.map(snap => this.formatDate(snap.time)),
          weights: rebalanceSnapshots.map(snap => snap.weights)
        };
      }
      return null;
    }
  },
  watch: {
    visibleStrategies() {
      this.$nextTick(() => {
        this.renderNavChart();
        this.renderDrawdownChart();
        this.renderVolChart();
      });
    },
    portfolioRebalanceWeights(val) {
      if (val) this.$nextTick(() => this.renderPositionChart());
    }
  },
  mounted() {
    this.$nextTick(() => {
      setTimeout(() => {
        this.renderNavChart();
        this.renderDrawdownChart();
        this.renderVolChart();
        if (this.portfolioRebalanceWeights) this.renderPositionChart();
      }, 200);
    });
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
    // ─── 工具方法 ───
    formatDate(dateStr) {
      if (!dateStr) return '';
      if (typeof dateStr === 'string') return dateStr.substring(0, 10);
      try { return new Date(dateStr).toISOString().split('T')[0]; } catch (e) { return String(dateStr); }
    },
    formatMetric(value, format) {
      if (value == null) return '-';
      if (format === 'percent') return (value * 100).toFixed(2) + '%';
      if (format === 'number') return parseFloat(value).toFixed(3);
      if (format === 'integer') return String(Math.round(value));
      return String(value);
    },
    /** 获取策略在周期内的快照 */
    getFilteredSnapshots(strategy) {
      const snaps = (strategy.result && strategy.result.snapshots) || [];
      if (!this.periodStartDate) return snaps;
      return snaps.filter(s => this.formatDate(s.time) >= this.periodStartDate);
    },
    /** 计算策略指标（支持周期内重算） */
    getStrategyMetrics(strategy) {
      const snaps = this.getFilteredSnapshots(strategy);
      const result = strategy.result || {};
      if (snaps.length < 2) {
        return {
          total_return: result.total_return || 0,
          annual_return: result.annual_return || 0,
          volatility: result.volatility || 0,
          max_drawdown: result.max_drawdown || 0,
          sharpe_ratio: result.sharpe_ratio || 0,
          calmar_ratio: result.calmar_ratio || 0,
          win_rate: result.win_rate != null ? result.win_rate : null,
          trade_count: result.trades ? result.trades.length : 0
        };
      }
      // 从快照重算
      const initialValue = snaps[0].total_value || 1;
      const endValue = snaps[snaps.length - 1].total_value || initialValue;
      const totalReturn = endValue / initialValue - 1;
      const nDays = snaps.length;
      const annualReturn = totalReturn > -1 ? Math.pow(1 + totalReturn, 252 / nDays) - 1 : -1;
      // 日收益率
      const dailyReturns = [];
      for (let i = 1; i < snaps.length; i++) {
        const prev = snaps[i - 1].total_value || 1;
        const curr = snaps[i].total_value || 1;
        dailyReturns.push((curr - prev) / prev);
      }
      const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
      const variance = dailyReturns.reduce((sum, r) => sum + (r - mean) * (r - mean), 0) / dailyReturns.length;
      const volatility = Math.sqrt(variance) * Math.sqrt(252);
      // 最大回撤
      let peak = -Infinity, maxDD = 0;
      snaps.forEach(s => {
        const nav = s.total_value / initialValue;
        if (nav > peak) peak = nav;
        const dd = (nav - peak) / peak;
        if (dd < maxDD) maxDD = dd;
      });
      const sharpe = volatility > 1e-8 ? (annualReturn - 0.02) / volatility : 0;
      const calmar = maxDD < -1e-8 ? annualReturn / Math.abs(maxDD) : 0;
      return {
        total_return: totalReturn,
        annual_return: annualReturn,
        volatility,
        max_drawdown: maxDD,
        sharpe_ratio: sharpe,
        calmar_ratio: calmar,
        win_rate: result.win_rate != null ? result.win_rate : null,
        trade_count: result.trades ? result.trades.length : 0
      };
    },
    pearsonCorrelation(x, y) {
      const n = Math.min(x.length, y.length);
      if (n < 2) return 0;
      let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0, sumY2 = 0;
      for (let i = 0; i < n; i++) {
        sumX += x[i]; sumY += y[i];
        sumXY += x[i] * y[i];
        sumX2 += x[i] * x[i]; sumY2 += y[i] * y[i];
      }
      const denom = Math.sqrt((n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY));
      if (denom < 1e-12) return 0;
      return (n * sumXY - sumX * sumY) / denom;
    },
    // ─── 交互方法 ───
    handlePeriodChange() {
      this.$nextTick(() => {
        this.renderNavChart();
        this.renderDrawdownChart();
        this.renderVolChart();
      });
    },
    toggleStrategy(key) {
      const idx = this.hiddenStrategies.indexOf(key);
      if (idx >= 0) this.hiddenStrategies.splice(idx, 1);
      else this.hiddenStrategies.push(key);
    },
    openDrawer(row) {
      const s = row._strategyData;
      if (!s) return;
      this.drawerStrategy = {
        key: s.key,
        name: s.name,
        result: s.result,
        strategy: s.strategy,
        remark: s.remark,
        recordId: s.recordId,
        modelId: s.modelId
      };
      this.drawerVisible = true;
    },
    isBestValue(row, col) {
      if (!col.better) return false;
      const values = this.comparisonTable.map(r => r[col.key]).filter(v => v != null);
      if (values.length === 0) return false;
      const best = col.better === 'max' ? Math.max(...values) : Math.min(...values);
      return row[col.key] === best;
    },
    getCellStyle(row, col) {
      if (!col.better) return {};
      const values = this.comparisonTable.map(r => r[col.key]).filter(v => v != null);
      if (values.length < 2) return {};
      const min = Math.min(...values);
      const max = Math.max(...values);
      if (max === min) return {};
      const ratio = (row[col.key] - min) / (max - min);
      // better=max: 高值绿色; better=min: 低值绿色
      const greenness = col.better === 'max' ? ratio : 1 - ratio;
      const alpha = greenness * 0.12;
      return { background: `rgba(103, 194, 58, ${alpha.toFixed(3)})` };
    },
    // ─── 图表渲染 ───
    getChart(key, dom) {
      if (!dom || dom.offsetWidth === 0) return null;
      let chart = this.charts[key];
      // 缓存实例若绑定在已被 v-if 移除的旧 DOM 上，先废弃再重建，避免图表渲染到脱离文档的节点而空白
      if (chart && !chart.isDisposed() && chart.getDom() !== dom) {
        chart.dispose();
        chart = null;
      }
      if (!chart || chart.isDisposed()) {
        chart = echarts.init(dom);
        this.charts[key] = chart;
      }
      return chart;
    },
    renderNavChart() {
      const dom = this.$refs.navChart;
      const chart = this.getChart('nav', dom);
      if (!chart) return;
      const { dates, strategyNavs } = this.navSeriesData;
      if (dates.length === 0) return;

      const seriesMap = {};
      const series = [];
      for (const [key, { name, color, navByDate }] of Object.entries(strategyNavs)) {
        let lastNav = null;
        const navs = dates.map(d => {
          if (navByDate[d] != null) { lastNav = navByDate[d]; return lastNav; }
          return lastNav;
        });
        seriesMap[name] = navs;
        series.push({ name, type: 'line', data: navs, smooth: 0.3, lineStyle: { width: 2, color }, itemStyle: { color }, symbol: 'none' });
      }
      // 降采样
      const sampled = downsampleMultiSeries(dates, seriesMap, 500);
      series.forEach(s => { s.data = sampled.series[s.name]; });

      chart.setOption({
        title: { text: '净值曲线', left: 'center', textStyle: { fontSize: 13 } },
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: Object.keys(strategyNavs).map(k => strategyNavs[k].name), bottom: 0, type: 'scroll' },
        grid: { left: 60, right: 20, top: 40, bottom: 50 },
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 28 }],
        xAxis: { type: 'category', boundaryGap: false, data: sampled.dates },
        yAxis: { type: 'value', name: '净值', scale: true },
        series
      }, true);
    },
    renderDrawdownChart() {
      const dom = this.$refs.drawdownChart;
      const chart = this.getChart('drawdown', dom);
      if (!chart) return;
      const { dates, strategyNavs } = this.navSeriesData;
      if (dates.length === 0) return;

      const seriesMap = {};
      const series = [];
      for (const [key, { name, color, navByDate }] of Object.entries(strategyNavs)) {
        let lastNav = null;
        let peak = -Infinity;
        const dds = dates.map(d => {
          if (navByDate[d] != null) lastNav = navByDate[d];
          if (lastNav == null) return 0;
          if (lastNav > peak) peak = lastNav;
          return peak > 0 ? ((lastNav - peak) / peak) * 100 : 0;
        });
        seriesMap[name] = dds;
        series.push({
          name, type: 'line', data: dds, smooth: 0.3, symbol: 'none',
          lineStyle: { width: 1.5, color },
          areaStyle: { color, opacity: 0.08 },
          itemStyle: { color }
        });
      }
      const sampled = downsampleMultiSeries(dates, seriesMap, 500);
      series.forEach(s => { s.data = sampled.series[s.name]; });

      chart.setOption({
        title: { text: '回撤走势', left: 'center', textStyle: { fontSize: 13 } },
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, formatter: (params) => { let h = params[0].axisValue + '<br/>'; params.forEach(p => { h += `${p.marker}${p.seriesName}: ${p.value != null ? p.value.toFixed(2) : '-'}%<br/>`; }); return h; } },
        legend: { data: Object.keys(strategyNavs).map(k => strategyNavs[k].name), bottom: 0, type: 'scroll' },
        grid: { left: 60, right: 20, top: 40, bottom: 50 },
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 28 }],
        xAxis: { type: 'category', boundaryGap: false, data: sampled.dates },
        yAxis: { type: 'value', name: '回撤(%)', axisLabel: { formatter: '{value}%' } },
        series
      }, true);
    },
    renderVolChart() {
      const dom = this.$refs.volChart;
      const chart = this.getChart('vol', dom);
      if (!chart) return;
      if (this.visibleStrategies.length === 0) return;

      const dateSet = new Set();
      const volByStrategy = {};
      const rollWindow = 21;
      for (const s of this.visibleStrategies) {
        const snaps = this.getFilteredSnapshots(s);
        if (snaps.length < 5) continue;
        const initialValue = snaps[0].total_value || 1;
        const navs = snaps.map(snap => snap.total_value / initialValue);
        const vols = snaps.map((snap, i) => {
          const start = Math.max(0, i - rollWindow);
          const slice = navs.slice(start, i + 1);
          let annVol = 0;
          if (slice.length >= 2) {
            const returns = [];
            for (let j = 1; j < slice.length; j++) returns.push((slice[j] - slice[j - 1]) / slice[j - 1]);
            const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
            const variance = returns.reduce((sum, r) => sum + (r - mean) * (r - mean), 0) / returns.length;
            annVol = Math.sqrt(Math.max(0, variance)) * Math.sqrt(252) * 100;
          }
          const d = this.formatDate(snap.time);
          dateSet.add(d);
          return { date: d, vol: annVol };
        });
        volByStrategy[s.key] = { name: s.name, color: s.color, vols };
      }
      const dates = Array.from(dateSet).sort();
      const seriesMap = {};
      const series = [];
      for (const [, { name, color, vols }] of Object.entries(volByStrategy)) {
        const volByDate = {};
        vols.forEach(v => { volByDate[v.date] = v.vol; });
        let last = null;
        const data = dates.map(d => { if (volByDate[d] != null) last = volByDate[d]; return last; });
        seriesMap[name] = data;
        series.push({ name, type: 'line', data, smooth: true, symbol: 'none', lineStyle: { width: 1.5, color }, itemStyle: { color } });
      }
      const sampled = downsampleMultiSeries(dates, seriesMap, 500);
      series.forEach(s => { s.data = sampled.series[s.name]; });

      chart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: Object.keys(volByStrategy).map(k => volByStrategy[k].name), bottom: 0, type: 'scroll' },
        grid: { left: 60, right: 20, top: 20, bottom: 50 },
        xAxis: { type: 'category', boundaryGap: false, data: sampled.dates },
        yAxis: { type: 'value', name: '年化波动率(%)', axisLabel: { formatter: '{value}%' } },
        series
      }, true);
    },
    renderPositionChart() {
      const dom = this.$refs.positionChart;
      const chart = this.getChart('position', dom);
      if (!chart || !this.portfolioRebalanceWeights) return;
      const { dates, weights } = this.portfolioRebalanceWeights;
      const allKeys = new Set();
      weights.forEach(w => Object.keys(w).forEach(k => allKeys.add(k)));
      const keyAvg = {};
      allKeys.forEach(k => { const vals = weights.map(w => Math.abs(w[k] || 0)); keyAvg[k] = vals.reduce((a, b) => a + b, 0) / vals.length; });
      const keys = Array.from(allKeys).sort((a, b) => keyAvg[a] - keyAvg[b]);
      const colors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#48b8d0', '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#06B6D4'];
      const series = keys.map((key, idx) => ({
        name: key, type: 'line', stack: 'total', areaStyle: { opacity: 0.85 },
        emphasis: { focus: 'series' }, data: weights.map(w => ((w[key] || 0) * 100).toFixed(2)),
        itemStyle: { color: colors[idx % colors.length] }, lineStyle: { width: 0.5 }, symbol: 'none'
      }));
      chart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, formatter: (params) => { const sorted = [...params].sort((a, b) => parseFloat(b.value) - parseFloat(a.value)); let html = `<strong>${sorted[0].axisValue}</strong><br/>`; sorted.forEach(p => { const v = parseFloat(p.value); if (v > 0) html += `${p.marker}${p.seriesName}: ${v.toFixed(2)}%<br/>`; }); return html; } },
        legend: { data: keys, bottom: 0, type: 'scroll' },
        grid: { left: 60, right: 20, top: 20, bottom: 60 },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: { type: 'value', name: '权重(%)', max: 100, axisLabel: { formatter: '{value}%' } },
        series
      }, true);
    }
  }
};
</script>

<style scoped>
.multi-strategy-comparison { padding: 16px 0; }
.control-bar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.strategy-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.strategy-chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 12px; border-radius: 16px; border: 1.5px solid;
  font-size: 12px; cursor: pointer; transition: all 0.2s; user-select: none;
}
.strategy-chip.hidden { opacity: 0.5; text-decoration: line-through; }
.chip-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.summary-cards { margin-bottom: 16px; }
.summary-card { background: #fafbfc; border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 16px; text-align: center; }
.card-label { font-size: 12px; color: #909399; margin-bottom: 6px; }
.card-value { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.card-strategy { font-size: 12px; color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.section-card { margin-bottom: 16px; }
.section-title { font-weight: 600; font-size: 15px; }
.section-subtitle { font-size: 12px; color: #909399; margin-left: 12px; }
.sub-section-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; text-align: center; }
.strategy-name-link { cursor: pointer; display: inline-flex; align-items: center; gap: 6px; color: #409EFF; }
.strategy-name-link:hover { text-decoration: underline; }
.name-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.metric-cell { font-variant-numeric: tabular-nums; padding: 2px 6px; border-radius: 3px; display: inline-block; }
.best-value { color: #67C23A; font-weight: 700; border: 1px solid rgba(103, 194, 58, 0.4); }
::v-deep .el-table th { background-color: #f5f7fa; font-weight: 600; color: #303133; }
</style>
