<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">大类资产指数</h2>
      <p class="page-desc">基于 risk budget vol + 混合动量资产选择策略，展示大类资产指数的权重和净值</p>
    </div>

    <div class="page-content">
      <el-card shadow="never">
        <div slot="header" class="card-header">
          <span>回测参数</span>
        </div>
        <el-form :model="form" label-width="140px" inline>
          <el-form-item label="开始日期">
            <el-select
              v-model="form.startDate"
              placeholder="选择开始日期"
              style="width: 160px;"
            >
              <el-option
                v-for="opt in startDateOptions"
                :key="opt.start_date"
                :label="opt.label"
                :value="opt.start_date"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="结束日期">
            <el-date-picker
              v-model="form.endDate"
              type="date"
              value-format="yyyyMMdd"
              placeholder="选择结束日期"
              style="width: 160px;"
              :picker-options="endDatePickerOptions"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" @click="runBacktest">
              运行回测
            </el-button>
          </el-form-item>
        </el-form>
        <div class="param-note">
          <span>波动率阈值固定为 6%</span>
        </div>
      </el-card>

      <el-card v-if="result" shadow="never" class="result-card">
        <div slot="header" class="card-header">
          <span>绩效指标</span>
        </div>
        <el-row :gutter="20">
          <el-col :span="6">
            <div class="metric-item">
              <div class="metric-label">总收益率</div>
              <div class="metric-value" :class="getReturnClass(perf.total_return)">
                {{ formatPercent(perf.total_return) }}
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="metric-item">
              <div class="metric-label">年化收益率</div>
              <div class="metric-value" :class="getReturnClass(perf.annual_return)">
                {{ formatPercent(perf.annual_return) }}
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="metric-item">
              <div class="metric-label">夏普比率</div>
              <div class="metric-value">{{ formatNumber(perf.sharpe_ratio, 3) }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="metric-item">
              <div class="metric-label">最大回撤</div>
              <div class="metric-value" :class="getReturnClass(perf.max_drawdown)">
                {{ formatPercent(perf.max_drawdown) }}
              </div>
            </div>
          </el-col>
        </el-row>
        <el-row :gutter="20" style="margin-top: 20px;">
          <el-col :span="6">
            <div class="metric-item">
              <div class="metric-label">年化波动率</div>
              <div class="metric-value">{{ formatPercent(perf.volatility) }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="metric-item">
              <div class="metric-label">Calmar比率</div>
              <div class="metric-value">{{ formatNumber(perf.calmar_ratio, 3) }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="metric-item">
              <div class="metric-label">收益回撤比</div>
              <div class="metric-value">
                {{ perf.max_drawdown ? formatNumber(perf.total_return / Math.abs(perf.max_drawdown), 3) : '-' }}
              </div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <!-- 净值与回撤走势（与回测界面一致） -->
      <el-card v-if="result && result.nav_history && result.nav_history.length" shadow="never" class="result-card">
        <div slot="header" class="card-header">
          <span>净值与回撤走势</span>
        </div>
        <el-row :gutter="20">
          <el-col :span="12">
            <div ref="navChart" class="chart-container"></div>
          </el-col>
          <el-col :span="12">
            <div ref="drawdownChart" class="chart-container chart-drawdown"></div>
          </el-col>
        </el-row>
      </el-card>

      <!-- 持仓权重变化（与回测界面一致） -->
      <el-card v-if="positionData.length > 0" shadow="never" class="result-card">
        <div slot="header" class="card-header">
          <span>持仓权重变化</span>
        </div>
        <div class="position-chart-legend" style="margin-bottom: 8px; font-size: 12px; color: #606266;">
          <span style="margin-right: 16px;"><span style="display:inline-block;width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-bottom:7px solid #67C23A;vertical-align:middle;margin-right:4px;"></span> 权重初始化</span>
          <span style="margin-right: 16px;"><span style="display:inline-block;width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-bottom:7px solid #E6A23C;vertical-align:middle;margin-right:4px;"></span> 人工干预调仓</span>
          <span><span style="display:inline-block;width:6px;height:6px;background:#409EFF;border-radius:50%;vertical-align:middle;margin-right:4px;"></span> 自动调仓（周期性/波动率重置）</span>
        </div>
        <div ref="positionChart" class="chart-container chart-position"></div>
      </el-card>

      <!-- 组合波动率监控（与回测界面一致） -->
      <el-card v-if="volatilityData.length > 0" shadow="never" class="result-card">
        <div slot="header" class="card-header">
          <span>组合波动率监控</span>
        </div>
        <div class="volatility-chart-legend" style="margin-bottom: 8px; font-size: 12px; color: #606266;">
          <strong>图注：</strong>
          <span style="margin-right: 20px;"><span style="display:inline-block;width:8px;height:8px;background:#E6A23C;border-radius:50%;vertical-align:middle;margin-right:6px;"></span>橙色圆点 = 人工干预调仓日</span>
          <span style="margin-right: 20px;"><span style="display:inline-block;width:8px;height:8px;background:#409EFF;border-radius:50%;vertical-align:middle;margin-right:6px;"></span>蓝色圆点 = 波动率重置调仓日</span>
        </div>
        <div ref="volatilityChart" class="chart-container"></div>
      </el-card>

      <el-card v-if="volResetTableData.length > 0" shadow="never" class="result-card">
        <div slot="header" class="card-header">
          <span>波动率重置事件</span>
        </div>
        <el-table :data="volResetTableData" border stripe>
          <el-table-column prop="signal_date" label="信号日期" width="110">
            <template slot-scope="scope">
              {{ formatVolResetDate(scope.row.signal_date) }}
            </template>
          </el-table-column>
          <el-table-column prop="execute_date" label="执行日期" width="110">
            <template slot-scope="scope">
              {{ formatVolResetDate(scope.row.execute_date) }}
            </template>
          </el-table-column>
          <el-table-column prop="vol_trigger" label="波动率触发 (%)" width="120">
            <template slot-scope="scope">
              {{ scope.row.vol_trigger != null ? ((scope.row.vol_trigger * 100).toFixed(2) + '%') : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="scale_factor" label="缩放因子" width="120">
            <template slot-scope="scope">
              {{ scope.row.scale_factor != null ? (scope.row.scale_factor).toFixed(4) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="extra" label="其他参数" min-width="120">
            <template slot-scope="scope">
              {{ scope.row.extra || '-' }}
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<script>
import { runAssetIndexBacktest, getAssetIndexStartDates } from '@/api/assetIndex';
import * as echarts from 'echarts';

export default {
  name: 'AssetIndex',
  data() {
    return {
      form: {
        volThreshold: 0.06, // 固定 6%
        startDate: '20140210',
        endDate: '20260227'
      },
      startDateOptions: [],
      loading: false,
      result: null,
      chartInstances: {}
    };
  },
  computed: {
    // 结束日期：不可早于或等于开始日期，不可超过 2026-02-27
    endDatePickerOptions() {
      const max = new Date(2026, 1, 27); // 2026-02-27
      const sd = this.form.startDate;
      let minDate = null;
      if (sd && sd.length >= 8) {
        const y = parseInt(sd.slice(0, 4), 10);
        const m = parseInt(sd.slice(4, 6), 10) - 1;
        const d = parseInt(sd.slice(6, 8), 10);
        minDate = new Date(y, m, d);
      }
      return {
        disabledDate(time) {
          const t = new Date(time.getFullYear(), time.getMonth(), time.getDate());
          if (t > max) return true;
          if (minDate && t <= minDate) return true;
          return false;
        }
      };
    },
    navData() {
      if (!this.result || !this.result.nav_history || !this.result.nav_history.length) return [];
      return this.result.nav_history.map(r => ({
        date: this.formatDate(r.date),
        nav: r.nav || 0,
        drawdown: r.drawdown != null ? r.drawdown : 0,
        time: r.date
      }));
    },
    positionData() {
      if (!this.result || !this.result.nav_history || !this.result.nav_history.length) return [];
      return this.result.nav_history.map(r => ({
        date: this.formatDate(r.date),
        weights: r.weights || {},
        time: r.date,
        is_rebalance_day: !!r.is_rebalance_day,
        rebalance_type: r.rebalance_type,
        rebalance_reason: r.rebalance_reason
      }));
    },
    volatilityData() {
      if (!this.result || !this.result.nav_history || !this.result.nav_history.length) return [];
      const history = this.result.nav_history;
      const withVol = history.filter(r => r.volatility != null && (r.volatility || 0) !== 0);
      const hasBackendVol = withVol.length > history.length * 0.5;
      let volatilities;
      if (hasBackendVol) {
        volatilities = history.map(r => r.volatility != null ? r.volatility : 0);
      } else {
        // 无后端波动率时：按净值序列计算滚动年化波动率（21 日）
        const rollWindow = 21;
        const navs = history.map(r => r.nav || 0);
        volatilities = [];
        for (let i = 0; i < history.length; i++) {
          const start = Math.max(0, i - rollWindow);
          const slice = navs.slice(start, i + 1);
          let annVol = 0;
          if (slice.length >= 2) {
            const returns = [];
            for (let j = 1; j < slice.length; j++) {
              returns.push((slice[j] - slice[j - 1]) / (slice[j - 1] || 1));
            }
            const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
            const variance = returns.reduce((s, r) => s + (r - mean) * (r - mean), 0) / returns.length;
            annVol = Math.sqrt(Math.max(0, variance)) * Math.sqrt(252);
          }
          volatilities.push(annVol);
        }
      }
      return history.map((r, i) => ({
        date: this.formatDate(r.date),
        volatility: volatilities[i] || 0,
        time: r.date,
        isVolReset: r.rebalance_type === 'vol_reset' || (r.rebalance_reason && r.rebalance_reason.indexOf('波动率重置') >= 0),
        isRebalanceDay: !!r.is_rebalance_day,
        isManualAdjustment: r.rebalance_type === 'manual_adjustment' || (r.rebalance_reason && r.rebalance_reason.indexOf('交互式') >= 0)
      }));
    },
    targetVol() {
      return this.form.volThreshold != null ? Number(this.form.volThreshold) : 0.06;
    },
    perf() {
      if (!this.result || !this.result.performance) {
        return {
          total_return: null,
          annual_return: null,
          sharpe_ratio: null,
          max_drawdown: null,
          volatility: null,
          calmar_ratio: null
        };
      }
      return this.result.performance;
    },
    volResetTableData() {
      if (!this.result || !this.result.vol_reset_events || !this.result.vol_reset_events.length) return [];
      const stdKeys = ['signal_date', 'execute_date', 'vol_trigger', 'scale_factor'];
      return this.result.vol_reset_events.map(e => {
        const row = {
          signal_date: e.signal_date ?? e['信号日期'],
          execute_date: e.execute_date ?? e['执行日期'],
          vol_trigger: e.vol_trigger ?? e.VolTrigger ?? e['波动率触发'],
          scale_factor: e.scale_factor ?? e['缩放因子'],
          extra: null
        };
        const extra = {};
        for (const k of Object.keys(e)) {
          if (!stdKeys.includes(k) && !['信号日期', '执行日期', 'VolTrigger', '波动率触发', '缩放因子'].includes(k)) {
            extra[k] = e[k];
          }
        }
        if (Object.keys(extra).length > 0) {
          row.extra = Object.entries(extra).map(([k, v]) => `${k}: ${v}`).join('; ');
        }
        return row;
      });
    }
  },
  async mounted() {
    this.form.endDate = this.form.endDate || '20260227';
    try {
      const res = await getAssetIndexStartDates();
      const body = res.data || res;
      this.startDateOptions = Array.isArray(body) ? body : (body.data || []);
      if (this.startDateOptions.length > 0 && !this.form.startDate) {
        this.form.startDate = this.startDateOptions[0].start_date;
      }
      if (this.form.startDate && this.form.endDate && this.form.endDate <= this.form.startDate) {
        this.form.endDate = '20260227';
      }
    } catch (e) {
      this.startDateOptions = [{ start_date: '20140210', label: '2014-02-10' }];
    }
  },
  watch: {
    result() {
      this.$nextTick(() => this.initAllCharts());
    },
    'form.startDate'(newVal) {
      if (!newVal || !this.form.endDate) return;
      if (this.form.endDate <= newVal) {
        this.form.endDate = '20260227';
      }
    }
  },
  beforeDestroy() {
    Object.values(this.chartInstances).forEach(chart => {
      if (chart && chart._resizeHandler) {
        window.removeEventListener('resize', chart._resizeHandler);
      }
      if (chart && typeof chart.dispose === 'function') chart.dispose();
    });
    this.chartInstances = {};
  },
  methods: {
    formatPercent(num) {
      if (num === null || num === undefined) return '-';
      return (num * 100).toFixed(2) + '%';
    },
    formatNumber(num, precision = 2) {
      if (num === null || num === undefined) return '-';
      return parseFloat(num).toFixed(precision);
    },
    getReturnClass(ret) {
      if (ret > 0) return 'positive';
      if (ret < 0) return 'negative';
      return '';
    },
    formatVolResetDate(v) {
      if (v == null || v === undefined || v === '') return '-';
      if (typeof v === 'string') {
        if (v.length >= 10 && v.indexOf('-') >= 0) return v.substring(0, 10);
        if (v.length === 8) return `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}`;
      }
      try {
        const d = new Date(v);
        return d.toISOString().split('T')[0];
      } catch (e) {
        return String(v);
      }
    },
    async runBacktest() {
      const maxEndYmd = '20260227';
      if (this.form.endDate && this.form.endDate > maxEndYmd) {
        this.form.endDate = maxEndYmd;
      }
      if (this.form.startDate && this.form.endDate && this.form.endDate <= this.form.startDate) {
        this.form.endDate = maxEndYmd;
      }
      this.loading = true;
      this.result = null;
      const start = Date.now();
      try {
        const [res] = await Promise.all([
          runAssetIndexBacktest({
            volThreshold: this.form.volThreshold,
            startDate: this.form.startDate,
            endDate: this.form.endDate
          }),
          new Promise(r => setTimeout(r, 5000))
        ]);
        this.result = res.data || res;
        this.$nextTick(() => this.initAllCharts());
      } catch (e) {
        const elapsed = Date.now() - start;
        if (elapsed < 5000) {
          await new Promise(r => setTimeout(r, 5000 - elapsed));
        }
        this.$message.error(e.message || '回测失败');
      } finally {
        this.loading = false;
      }
    },
    formatDate(dateStr) {
      if (!dateStr) return '-';
      if (typeof dateStr === 'string') {
        if (dateStr.length >= 10 && dateStr.indexOf('-') >= 0) return dateStr.substring(0, 10);
        if (dateStr.length === 8) return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`;
      }
      return String(dateStr);
    },
    initAllCharts() {
      this.$nextTick(() => {
        if (this.navData && this.navData.length > 0) {
          this.initNavChart();
          this.initDrawdownChart();
        }
        if (this.positionData && this.positionData.length > 0) {
          this.initPositionChart();
        }
        if (this.volatilityData && this.volatilityData.length > 0) {
          this.initVolatilityChart();
        }
      });
    },
    initNavChart() {
      const el = this.$refs.navChart;
      if (!el || !this.navData.length) return;
      const existing = echarts.getInstanceByDom(el);
      if (existing) existing.dispose();
      const chart = echarts.init(el);
      this.chartInstances['nav'] = chart;
      const dates = this.navData.map(d => d.date);
      const navs = this.navData.map(d => d.nav);
      chart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: { type: 'value', name: '净值' },
        series: [{
          name: '净值',
          type: 'line',
          data: navs,
          smooth: true,
          itemStyle: { color: '#409EFF' },
          markLine: { data: [{ yAxis: 1.0, name: '基准线', lineStyle: { color: '#909399', type: 'dashed' } }] }
        }]
      });
      const resizeHandler = () => chart && !chart.isDisposed() && chart.resize();
      window.addEventListener('resize', resizeHandler);
      chart._resizeHandler = resizeHandler;
      setTimeout(() => chart.resize(), 100);
    },
    initDrawdownChart() {
      const el = this.$refs.drawdownChart;
      if (!el || !this.navData.length) return;
      const existing = echarts.getInstanceByDom(el);
      if (existing) existing.dispose();
      const chart = echarts.init(el);
      this.chartInstances['drawdown'] = chart;
      const dates = this.navData.map(d => d.date);
      const drawdowns = this.navData.map(d => (d.drawdown || 0) * 100);
      chart.setOption({
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          formatter: params => `${params[0].name}<br/>回撤: ${(params[0].value || 0).toFixed(2)}%`
        },
        title: { text: '回撤走势', left: 'center', textStyle: { fontSize: 14 } },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: { type: 'value', name: '回撤 (%)', axisLabel: { formatter: '{value}%' } },
        series: [{
          name: '回撤',
          type: 'line',
          data: drawdowns,
          smooth: true,
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(245, 108, 108, 0.3)' },
                { offset: 1, color: 'rgba(245, 108, 108, 0.1)' }
              ]
            }
          },
          itemStyle: { color: '#F56C6C' }
        }]
      });
      const resizeHandler = () => chart && !chart.isDisposed() && chart.resize();
      window.addEventListener('resize', resizeHandler);
      chart._resizeHandler = resizeHandler;
      setTimeout(() => chart.resize(), 100);
    },
    initPositionChart() {
      const el = this.$refs.positionChart;
      if (!el || !this.positionData.length) return;
      const existing = echarts.getInstanceByDom(el);
      if (existing) existing.dispose();
      const chart = echarts.init(el);
      this.chartInstances['position'] = chart;
      const allDates = this.positionData.map(p => p.date);
      const dailyWeights = this.positionData.map(p => ({
        weights: p.weights || {},
        rebalance_type: p.rebalance_type,
        rebalance_reason: p.rebalance_reason
      }));
      const allAssets = new Set();
      dailyWeights.forEach(p => Object.keys(p.weights || {}).forEach(a => allAssets.add(a)));
      const assets = Array.from(allAssets);
      const series = assets.map(asset => ({
        name: asset,
        type: 'line',
        stack: 'total',
        areaStyle: {},
        data: allDates.map((_, i) => (dailyWeights[i].weights[asset] || 0) * 100)
      }));
      const getRebalanceTypeLabel = (dayInfo) => {
        if (!dayInfo || !dayInfo.rebalance_type) return '持仓不变';
        const t = dayInfo.rebalance_type;
        const r = dayInfo.rebalance_reason || '';
        if (t === 'manual_adjustment' && (r === '期初建仓' || r.indexOf('期初建仓') >= 0)) return '权重初始化';
        if (t === 'manual_adjustment' || r.indexOf('交互式') >= 0) return '人工干预调仓';
        if (t === 'vol_reset' || r.indexOf('波动率重置') >= 0) return '自动调仓（波动率重置）';
        return '自动调仓（周期性）';
      };
      const manualAndInitDates = dailyWeights.map((p, i) => {
        const label = getRebalanceTypeLabel(p);
        if (label === '权重初始化' || label === '人工干预调仓') return { date: allDates[i], label, index: i };
        return null;
      }).filter(Boolean);
      const markLineData = manualAndInitDates.map(({ date, label }) => ({
        xAxis: date,
        lineStyle: { color: label === '权重初始化' ? '#67C23A' : '#E6A23C', type: 'solid', width: 2 },
        label: { show: false }
      }));
      const maxWeightSumPercent = dailyWeights.reduce((max, p) => {
        const sum = Object.values(p.weights || {}).reduce((s, w) => s + (Number(w) || 0), 0) * 100;
        return Math.max(max, sum);
      }, 0);
      const yAxisMax = maxWeightSumPercent <= 100 ? 100 : Math.max(100, Math.min(400, Math.ceil(maxWeightSumPercent / 5) * 5));
      chart.setOption({
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          formatter: params => {
            const date = params[0].axisValue;
            const idx = allDates.indexOf(date);
            const dayInfo = idx >= 0 ? dailyWeights[idx] : null;
            let html = `${date}<br/><strong>调仓类型：${getRebalanceTypeLabel(dayInfo)}</strong><br/>`;
            params.forEach(p => {
              const v = Array.isArray(p.value) ? p.value[p.value.length - 1] : p.value;
              html += `${p.seriesName}: ${v != null ? parseFloat(v).toFixed(2) : '-'}%<br/>`;
            });
            return html;
          }
        },
        legend: { data: assets, bottom: 0, type: 'scroll' },
        grid: { left: '3%', right: '4%', top: 40, bottom: '22%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: allDates },
        yAxis: { type: 'value', name: '权重 (%)', axisLabel: { formatter: '{value}%' }, min: 0, max: yAxisMax },
        series: series.map((s, i) => ({
          ...s,
          markLine: i === 0 && markLineData.length > 0 ? { symbol: 'none', data: markLineData } : undefined
        }))
      });
      const resizeHandler = () => chart && !chart.isDisposed() && chart.resize();
      window.addEventListener('resize', resizeHandler);
      chart._resizeHandler = resizeHandler;
      setTimeout(() => chart.resize(), 100);
    },
    initVolatilityChart() {
      const el = this.$refs.volatilityChart;
      if (!el || !this.volatilityData.length) return;
      const existing = echarts.getInstanceByDom(el);
      if (existing) existing.dispose();
      const chart = echarts.init(el);
      this.chartInstances['volatility'] = chart;
      const dates = this.volatilityData.map(d => d.date);
      const volatilities = this.volatilityData.map(d => (d.volatility || 0) * 100);
      const targetVolPercent = (this.targetVol || 0.06) * 100;
      const dateToIndex = {};
      dates.forEach((d, i) => { dateToIndex[d] = i; });
      const volResetPointsFromEvents = (this.result && this.result.vol_reset_events) ? this.result.vol_reset_events.map(e => {
        const execDate = this.formatVolResetDate(e.execute_date || e['执行日期']);
        const idx = dateToIndex[execDate];
        if (idx != null) return { name: '波动率重置', coord: [idx, volatilities[idx] || 0] };
        return null;
      }).filter(Boolean) : [];
      const volResetPointsFromNav = this.volatilityData
        .map((d, i) => (d.isVolReset ? { name: '波动率重置', coord: [i, (d.volatility || 0) * 100] } : null))
        .filter(Boolean);
      const volResetPoints = volResetPointsFromEvents.length > 0 ? volResetPointsFromEvents : volResetPointsFromNav;
      const manualPoints = this.volatilityData
        .map((d, i) => (d.isRebalanceDay && d.isManualAdjustment ? { name: '人工干预', coord: [i, (d.volatility || 0) * 100] } : null))
        .filter(Boolean);
      const getVolRebalanceLabel = (d) => {
        if (!d || !d.isRebalanceDay) return '';
        if (d.isManualAdjustment) return '人工干预调仓';
        if (d.isVolReset) return '自动调仓（波动率重置）';
        return '自动调仓（周期性）';
      };
      chart.setOption({
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          formatter: params => {
            const param = params[0];
            const idx = param.dataIndex;
            const d = this.volatilityData[idx];
            let html = `${param.name}<br/>组合波动率: ${(param.value != null ? param.value : 0).toFixed(2)}%<br/>目标波动率: ${targetVolPercent.toFixed(2)}%`;
            if (getVolRebalanceLabel(d)) html += `<br/><strong>调仓类型：${getVolRebalanceLabel(d)}</strong>`;
            return html;
          }
        },
        grid: { left: '8%', right: '14%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: { type: 'value', name: '年化波动率 (%)', axisLabel: { formatter: '{value}%' } },
        series: [{
          name: '组合波动率',
          type: 'line',
          data: volatilities,
          smooth: true,
          itemStyle: { color: '#409EFF' },
          markLine: {
            data: [{ yAxis: targetVolPercent, name: `目标波动率 (${targetVolPercent.toFixed(1)}%)`, lineStyle: { color: '#67C23A', type: 'dashed' }, label: { formatter: `目标 ${targetVolPercent.toFixed(1)}%`, position: 'end' } }]
          },
          markPoint: (volResetPoints.length > 0 || manualPoints.length > 0) ? {
            symbol: 'circle',
            symbolSize: 8,
            data: [
              ...volResetPoints.map(p => ({ ...p, name: '波动率重置', itemStyle: { color: '#409EFF' }, label: { show: false } })),
              ...manualPoints.map(p => ({ ...p, name: '人工干预', itemStyle: { color: '#E6A23C' }, label: { show: false } }))
            ],
            emphasis: { label: { show: true, formatter: '{b}' } }
          } : undefined
        }]
      });
      const resizeHandler = () => chart && !chart.isDisposed() && chart.resize();
      window.addEventListener('resize', resizeHandler);
      chart._resizeHandler = resizeHandler;
      setTimeout(() => chart.resize(), 100);
    }
  }
};
</script>

<style scoped>
.page-container { padding: 20px; }
.page-header { margin-bottom: 20px; }
.page-title { font-size: 20px; margin: 0 0 8px 0; }
.page-desc { color: #909399; font-size: 14px; margin: 0; }
.card-header {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.param-note { color: #909399; font-size: 12px; margin-top: 8px; }
.result-card {
  margin-top: 20px;
}
.result-card >>> .el-card__header {
  padding: 12px 16px;
  background: #fafbfc;
  border-bottom: 1px solid #ebeef5;
}
.result-card >>> .el-card__body {
  padding: 20px;
}

/* 指标卡片 */
.metric-item {
  background: linear-gradient(135deg, #f8f9fb 0%, #ffffff 100%);
  border: 1px solid #e8ecf1;
  border-radius: 8px;
  padding: 16px 12px;
  text-align: center;
  transition: box-shadow 0.2s;
}
.metric-item:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}
.metric-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}
.metric-value {
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #303133;
}
.metric-value.positive { color: #67C23A; }
.metric-value.negative { color: #F56C6C; }

/* 图表容器 */
.chart-container {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  height: 400px;
}

.chart-drawdown {
  height: 350px;
}
.chart-position {
  height: 450px;
}

@media (max-width: 768px) {
  .chart-container {
    height: 300px;
  }
  .chart-drawdown {
    height: 280px;
  }
  .chart-position {
    height: 350px;
  }
}
</style>
