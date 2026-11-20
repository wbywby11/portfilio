<template>
  <div class="dashboard-container">
    <template v-if="!monitorState">
      <el-empty :image-size="80">
        <template slot="description">
          <p style="color: #606266; font-size: 14px;">尚未建立本策略的日常监控数据</p>
          <p style="color: #909399; font-size: 13px;">请在页面顶部点击「初始化」，完成后再查看监控数据。</p>
        </template>
      </el-empty>
    </template>
    <template v-else>
      <!-- 时间段选择器 -->
      <div class="period-bar">
        <span class="period-label">绩效区间</span>
        <el-radio-group v-model="selectedPeriod" size="small" @change="onPeriodChange">
          <el-radio-button label="1m">近1月</el-radio-button>
          <el-radio-button label="3m">近3月</el-radio-button>
          <el-radio-button label="6m">近6月</el-radio-button>
          <el-radio-button label="1y">近1年</el-radio-button>
          <el-radio-button label="all">全部</el-radio-button>
        </el-radio-group>
        <span class="period-range">{{ periodRangeLabel }}</span>
      </div>

      <!-- 核心指标：完全由 overview_metrics 配置驱动，指标增减只改配置 -->
      <div class="metrics-grid" :style="gridStyle">
        <MetricCard
          v-for="metric in overviewMetrics"
          :key="metric.key"
          :metric="metric" />
      </div>

      <!-- 策略自定义插槽：如期权希腊字母、因子暴露表等，未声明时不渲染 -->
      <DynamicSlots v-if="overviewSlots.length" :slots="overviewSlots" class="overview-dynamic-slots" />
    </template>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import { mapState, mapActions } from 'vuex';
import MetricCard from '@/components/monitor/MetricCard.vue';
import DynamicSlots from '@/components/monitor/DynamicSlots.vue';
import { buildMetrics, resolveGridColumns, resolveCustomComponents } from '@/config/monitor';

export default {
  name: 'MonitorIndex',
  components: { MetricCard, DynamicSlots },
  props: {
    strategyContext: {
      type: Object,
      default: null
    }
  },
  data() {
    return {
      loading: false,
      selectedPeriod: 'all'
    };
  },
  computed: {
    ...mapState('monitor', ['monitorState', 'navHistory', 'performance', 'signals']),
    /** 区间基准日：取监控状态的当前日，避免历史实例按自然今天切出空区间 */
    periodBaseDate() {
      const d = this.monitorState && this.monitorState.date;
      return d ? dayjs(d) : dayjs();
    },
    /** 区间起始日（YYYY-MM-DD），全部区间为 null */
    periodStartDate() {
      if (this.selectedPeriod === 'all') return null;
      const monthsMap = { '1m': 1, '3m': 3, '6m': 6, '1y': 12 };
      const months = monthsMap[this.selectedPeriod];
      if (!months) return null;
      return this.periodBaseDate.subtract(months, 'month').format('YYYY-MM-DD');
    },
    /** 按选定区间过滤后的净值序列（仅用于展示区间边界标签） */
    filteredNavHistory() {
      if (!this.navHistory || !this.navHistory.length) return [];
      const start = this.periodStartDate;
      if (!start) return this.navHistory;
      return this.navHistory.filter(h => dayjs(h.date).format('YYYY-MM-DD') >= start);
    },
    /** 区间标签 */
    periodRangeLabel() {
      const data = this.filteredNavHistory;
      if (!data.length) return '';
      const s = dayjs(data[0].date).format('YYYY-MM-DD');
      const e = dayjs(data[data.length - 1].date).format('YYYY-MM-DD');
      return `${s} ~ ${e}`;
    },
    /** 下次调仓日期文本（后端无下次调仓日时返回 null，不再拼中文占位） */
    nextRebalanceDateLabel() {
      if (!this.signals) return '';
      const raw = (this.signals.pending_rebalance && this.signals.pending_rebalance.execute_date)
        || (this.signals.monthly_rebalance && this.signals.monthly_rebalance.next_date)
        || null;
      if (!raw) return '';
      const d = dayjs(raw);
      return d.isValid() ? d.format('YYYY-MM-DD') : '';
    },
    /** 主观配置：仪表盘不展示「相对重置阈值」口径 */
    isManualAllocationDashboard() {
      const ctx = this.strategyContext;
      const p = ctx && ctx.live_effective_params;
      return !!(p && p.is_manual_allocation);
    },
    currentNav() {
      if (!this.monitorState || this.monitorState.nav === undefined || this.monitorState.nav === null) {
        return null;
      }
      return this.monitorState.nav;
    },
    // 总杠杆 = target_weights 绝对值之和（与后端 monitor 一致：小数权重，非百分比）
    totalLeverage() {
      const weights = (this.monitorState && this.monitorState.target_weights) ? this.monitorState.target_weights : {};
      return Object.values(weights).reduce((s, w) => s + Math.abs(Number(w) || 0), 0);
    },
    // 当前波动率（统一为百分点数字，与 signal 接口一致）
    currentVolatility() {
      if (this.signals && this.signals.vol_reset && this.signals.vol_reset.current_volatility !== undefined) {
        return this.normalizeMonitorVolPercent(this.signals.vol_reset.current_volatility);
      }
      return null;
    },
    // 当日损益额
    dailyPnL() {
      if (this.navHistory && this.navHistory.length >= 2) {
        const latestNav = this.navHistory[this.navHistory.length - 1].nav;
        const prevNav = this.navHistory[this.navHistory.length - 2].nav;
        return latestNav - prevNav;
      }
      return null;
    },
    // 当日收益率（小数形式）
    dailyReturnPct() {
      if (this.navHistory && this.navHistory.length >= 2) {
        const latestNav = this.navHistory[this.navHistory.length - 1].nav;
        const prevNav = this.navHistory[this.navHistory.length - 2].nav;
        return (latestNav / prevNav) - 1;
      }
      return null;
    },
    // 当前回撤（小数，与 formatPct 口径一致：-0.05 表示 -5%）
    currentDrawdown() {
      if (!this.navHistory || this.navHistory.length < 2) return null;
      const navValues = this.navHistory.map(h => h.nav);
      const currentNav = navValues[navValues.length - 1];
      let peak = navValues[0];
      for (const nav of navValues) {
        if (nav > peak) peak = nav;
      }
      return (currentNav / peak) - 1;
    },
    // 持仓资产数（后端 /monitor/performance 单源产出：非零权重计数，与绩效页持仓表同口径）
    positionCount() {
      return (this.performance && this.performance.position_count) || 0;
    },
    // 波动率重置阈值（百分点，如 6 表示 6%）
    volResetThreshold() {
      if (this.signals && this.signals.vol_reset && this.signals.vol_reset.threshold !== undefined) {
        return this.normalizeMonitorVolPercent(this.signals.vol_reset.threshold);
      }
      return 6;
    },
    // 指标卡上下文：只负责取数，展示规则全部在 @/config/monitor/metrics 中
    metricContext() {
      const perf = this.performance || {};
      return {
        nav: this.currentNav,
        date: this.monitorState && this.monitorState.date
          ? dayjs(this.monitorState.date).format('YYYY-MM-DD')
          : '',
        periodReturn: perf.cumulative_return,
        tradingDays: perf.trading_days,
        annualReturn: perf.annual_return,
        annualReturn365: perf.annual_return_365,
        annualVol: perf.annual_volatility,
        annualVol365: perf.annual_volatility_365,
        sharpe: perf.sharpe_ratio,
        sharpe365: perf.sharpe_ratio_365,
        maxDrawdown: perf.max_drawdown,
        dailyReturn: this.dailyReturnPct === null ? null : this.dailyReturnPct * 100,
        currentDrawdown: this.currentDrawdown === null ? null : this.currentDrawdown * 100,
        leverage: this.totalLeverage,
        positionCount: this.positionCount,
        daysToRebalance: this.daysToNextRebalance,
        nextRebalanceDate: this.nextRebalanceDateLabel,
        volatility: this.currentVolatility,
        volThreshold: this.volResetThreshold,
        isManualAllocation: this.isManualAllocationDashboard
      };
    },
    /** 指标卡数组：由配置决定展示哪些指标、顺序与格式 */
    overviewMetrics() {
      return buildMetrics('overview', this.metricContext, this.strategyContext);
    },
    /** 栅格列数：由配置决定（默认 6 列，策略可覆盖） */
    overviewColumns() {
      return resolveGridColumns('overview', this.strategyContext);
    },
    gridStyle() {
      // 用 CSS 变量而非内联列定义，保证窄屏媒体查询仍能覆盖列数
      return { '--monitor-grid-cols': this.overviewColumns };
    },
    /** 策略自定义插槽：未声明时为空数组，页面不渲染 */
    overviewSlots() {
      return resolveCustomComponents('overview', this.strategyContext);
    },
    // 计算距下次调仓天数
    daysToNextRebalance() {
      if (!this.signals) return null;
      
      // 如果有 pending，优先计算 pending 的天数
      if (this.signals.pending_rebalance && this.signals.pending_rebalance.execute_date) {
        var pendingDate = new Date(this.signals.pending_rebalance.execute_date);
        var today = this.monitorState && this.monitorState.date ? new Date(this.monitorState.date) : new Date();
        var diff = Math.ceil((pendingDate - today) / (1000 * 60 * 60 * 24));
        if (Number.isNaN(diff)) return null;
        return diff >= 0 ? diff : 0;
      }
      
      // 否则用月度调仓的 days_until（后端已计算好）
      if (this.signals.monthly_rebalance && this.signals.monthly_rebalance.days_until !== undefined
        && this.signals.monthly_rebalance.days_until !== null) {
        return this.signals.monthly_rebalance.days_until;
      }
      
      // 回退：自己计算
      var nextDate = (this.signals.monthly_rebalance && this.signals.monthly_rebalance.next_date) 
        ? this.signals.monthly_rebalance.next_date : null;
      if (!nextDate || !this.monitorState || !this.monitorState.date) return null;
      var todayDate = new Date(this.monitorState.date);
      var target = new Date(nextDate);
      var diffTime = target - todayDate;
      if (Number.isNaN(diffTime)) return null;
      return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    }
  },
  mounted() {
    this.loadData();
  },
  methods: {
    ...mapActions('monitor', [
      'fetchMonitorState',
      'fetchNavHistory',
      'fetchPerformance',
      'fetchSignals'
    ]),
    normalizeMonitorVolPercent(val) {
      if (val === undefined || val === null) return null;
      const n = Number(val);
      if (Number.isNaN(n)) return null;
      if (Math.abs(n) > 1 || n === 0) return n;
      return n * 100;
    },
    async loadData() {
      this.loading = true;
      try {
        // 先取监控状态：区间基准日依赖 monitorState.date
        await this.fetchMonitorState();
        await Promise.all([
          this.fetchPerformance({ start: this.periodStartDate }),
          this.fetchSignals(),
          this.fetchNavHistory({})
        ]);
      } catch (error) {
        this.$message.error('加载数据失败：' + ((error.response && error.response.data && error.response.data.message) ? error.response.data.message : error.message));
      } finally {
        this.loading = false;
      }
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '-';
    },
    async onPeriodChange() {
      // 指标由后端按区间重算，前端只切换请求参数
      await this.fetchPerformance({ start: this.periodStartDate });
    }
  }
};
</script>

<style scoped>
.dashboard-container {
  padding: 0;
}

/* ── 时间段选择栏 ── */
.period-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 16px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}

.period-label {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  white-space: nowrap;
}

.period-range {
  font-size: 12px;
  color: #909399;
  margin-left: auto;
}

/* ── 指标网格：列数由配置变量控制，各排等高、边缘对齐 ── */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(var(--monitor-grid-cols, 6), minmax(0, 1fr));
  grid-auto-rows: 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.overview-dynamic-slots {
  margin-top: 12px;
}

/* ── 窄屏自适应 ── */
@media (max-width: 1400px) {
  .metrics-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
