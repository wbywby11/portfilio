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

      <!-- 核心绩效指标 -->
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="metric-label">当前净值</div>
          <div class="metric-value large">{{ formatNumber(currentNav, 4) }}</div>
          <div class="metric-sub">{{ formatDate(monitorState && monitorState.date) }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">区间收益率</div>
          <div class="metric-value" :style="{ color: getReturnColor(periodStats.periodReturn) }">
            {{ formatPct(periodStats.periodReturn) }}
          </div>
          <div class="metric-sub">{{ periodStats.tradingDays }} 个交易日</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">年化收益率</div>
          <div class="metric-value" :style="{ color: getReturnColor(periodStats.annualReturn) }">
            {{ formatPct(periodStats.annualReturn) }}
          </div>
          <div class="metric-sub">历史年化</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">年化波动率</div>
          <div class="metric-value">{{ formatPct(periodStats.annualVol) }}</div>
          <div class="metric-sub">历史波动</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">夏普比率</div>
          <div class="metric-value" :style="{ color: getSharpeColor(periodStats.sharpe) }">
            {{ formatNum(periodStats.sharpe, 3) }}
          </div>
          <div class="metric-sub">风险调整</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">最大回撤</div>
          <div class="metric-value" style="color: #67C23A;">
            {{ formatPct(periodStats.maxDrawdown) }}
          </div>
          <div class="metric-sub">区间最大</div>
        </div>
      </div>

      <!-- 实时状态指标 -->
      <div class="metrics-grid metrics-grid--sub">
        <div class="metric-card">
          <div class="metric-label">当日收益</div>
          <div class="metric-value" :style="{ color: getReturnColor(dailyReturnPct) }">
            {{ dailyReturnPct !== null ? formatSignedPct(dailyReturnPct) : '-' }}
          </div>
          <div class="metric-sub">较前日</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">当前回撤</div>
          <div class="metric-value" style="color: #67C23A;">
            {{ formatPct(currentDrawdown) }}
          </div>
          <div class="metric-sub">距历史高点</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">总杠杆</div>
          <div class="metric-value">{{ formatNum(totalLeverage, 2) }}</div>
          <div class="metric-sub">权重绝对值之和</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">持仓资产数</div>
          <div class="metric-value">{{ positionCount }}</div>
          <div class="metric-sub">权重 &gt; 1%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">距下次调仓</div>
          <div class="metric-value">{{ daysToNextRebalance != null ? daysToNextRebalance + ' 天' : '-' }}</div>
          <div class="metric-sub">{{ nextRebalanceDateLabel }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">监控波动率</div>
          <div class="metric-value" :style="{ color: monitoredVolatilityColor }">
            {{ formattedMonitoredVolatility }}
          </div>
          <div class="metric-sub">{{ isManualAllocationDashboard ? '主观策略无阈值' : '阈值: ' + formattedVolThreshold }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import { mapState, mapActions } from 'vuex';

export default {
  name: 'MonitorIndex',
  components: {},
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
    /** 按选定区间过滤后的净值序列 */
    filteredNavHistory() {
      if (!this.navHistory || !this.navHistory.length) return [];
      if (this.selectedPeriod === 'all') return this.navHistory;
      const monthsMap = { '1m': 1, '3m': 3, '6m': 6, '1y': 12 };
      const months = monthsMap[this.selectedPeriod];
      if (!months) return this.navHistory;
      const cutoff = dayjs().subtract(months, 'month');
      return this.navHistory.filter(h => dayjs(h.date).isAfter(cutoff));
    },
    /** 区间绩效统计 */
    periodStats() {
      const data = this.filteredNavHistory;
      const empty = { periodReturn: null, annualReturn: null, annualVol: null, sharpe: null, maxDrawdown: null, tradingDays: 0 };
      if (data.length < 2) return empty;
      const firstNav = data[0].nav || 1;
      const lastNav = data[data.length - 1].nav || 1;
      const periodReturn = (lastNav / firstNav) - 1;
      const tradingDays = data.length;
      const annualReturn = Math.pow(lastNav / firstNav, 252 / tradingDays) - 1;
      const dailyReturns = [];
      for (let i = 1; i < data.length; i++) {
        if (data[i].nav && data[i - 1].nav) {
          dailyReturns.push(data[i].nav / data[i - 1].nav - 1);
        }
      }
      let annualVol = null, sharpe = null;
      if (dailyReturns.length > 1) {
        const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
        const variance = dailyReturns.reduce((s, r) => s + Math.pow(r - mean, 2), 0) / dailyReturns.length;
        annualVol = Math.sqrt(variance * 252);
        sharpe = annualVol > 0 ? annualReturn / annualVol : 0;
      }
      let maxDrawdown = 0, peak = firstNav;
      for (const item of data) {
        if (item.nav > peak) peak = item.nav;
        const dd = (item.nav - peak) / peak;
        if (dd < maxDrawdown) maxDrawdown = dd;
      }
      return { periodReturn, annualReturn, annualVol, sharpe, maxDrawdown, tradingDays };
    },
    /** 区间标签 */
    periodRangeLabel() {
      const data = this.filteredNavHistory;
      if (!data.length) return '';
      const s = dayjs(data[0].date).format('YYYY-MM-DD');
      const e = dayjs(data[data.length - 1].date).format('YYYY-MM-DD');
      return `${s} ~ ${e}`;
    },
    /** 下次调仓日期文本 */
    nextRebalanceDateLabel() {
      if (!this.signals) return '';
      if (this.signals.pending_rebalance && this.signals.pending_rebalance.execute_date) {
        return dayjs(this.signals.pending_rebalance.execute_date).format('YYYY-MM-DD');
      }
      if (this.signals.monthly_rebalance && this.signals.monthly_rebalance.next_date) {
        return dayjs(this.signals.monthly_rebalance.next_date).format('YYYY-MM-DD');
      }
      return '';
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
    // 当前回撤（百分点形式：负数表示回撤，如 -5 表示 -5%）
    currentDrawdown() {
      if (!this.navHistory || this.navHistory.length < 2) return null;
      const navValues = this.navHistory.map(h => h.nav);
      const currentNav = navValues[navValues.length - 1];
      let peak = navValues[0];
      for (const nav of navValues) {
        if (nav > peak) peak = nav;
      }
      return ((currentNav / peak) - 1) * 100;  // 转为百分点，与 formatPercentPoints 输入口径一致
    },
    // 持仓资产数（小数权重，|w|>0.01 视为有效持仓，约 1% 以上）
    positionCount() {
      const weights = this.monitorState && this.monitorState.target_weights ? this.monitorState.target_weights : {};
      return Object.values(weights).filter(w => Math.abs(w) > 0.01).length;
    },
    // 波动率重置阈值（百分点，如 6 表示 6%）
    volResetThreshold() {
      if (this.signals && this.signals.vol_reset && this.signals.vol_reset.threshold !== undefined) {
        return this.normalizeMonitorVolPercent(this.signals.vol_reset.threshold);
      }
      return 6;
    },
    // 格式化的监控波动率
    formattedMonitoredVolatility() {
      if (this.currentVolatility === null) return '-';
      return this.currentVolatility.toFixed(2) + '%';
    },
    // 格式化的波动率阈值
    formattedVolThreshold() {
      return this.volResetThreshold.toFixed(2) + '%';
    },
    // 监控波动率颜色
    monitoredVolatilityColor() {
      if (this.currentVolatility === null) return '#909399';
      if (this.isManualAllocationDashboard) return '#303133';
      if (this.currentVolatility >= this.volResetThreshold) {
        return '#F56C6C';
      }
      return '#67C23A';
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
      if (this.signals.monthly_rebalance && this.signals.monthly_rebalance.days_until !== undefined) {
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
        await Promise.all([
          this.fetchMonitorState(),
          this.fetchPerformance(),
          this.fetchSignals(),
          this.fetchNavHistory({})
        ]);
      } catch (error) {
        this.$message.error('加载数据失败：' + ((error.response && error.response.data && error.response.data.message) ? error.response.data.message : error.message));
      } finally {
        this.loading = false;
      }
    },
    formatSignedPct(num) {
      if (num === null || num === undefined) return '-';
      const pct = num * 100;
      const sign = pct >= 0 ? '+' : '';
      return sign + pct.toFixed(2) + '%';
    },
    formatNumber(num, decimals = 2) {
      if (num === null || num === undefined) return '-';
      return num.toFixed(decimals);
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '-';
    },
    onPeriodChange() {
      // 计算属性自动响应，无需额外操作
    },
    formatPct(num) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '-';
      return (Number(num) * 100).toFixed(2) + '%';
    },
    formatNum(num, decimals = 2) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '-';
      return Number(num).toFixed(decimals);
    },
    getSharpeColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (value >= 1) return '#F56C6C';
      if (value >= 0.5) return '#E6A23C';
      if (value >= 0) return '#303133';
      return '#67C23A';
    },
    getReturnColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (value > 0) return '#F56C6C';
      if (value < 0) return '#67C23A';
      return '#909399';
    },
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
  margin-bottom: 10px;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 6px;
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

/* ── 绩效卡片网格 ── */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
  margin-bottom: 10px;
}

.metrics-grid--sub {
  margin-bottom: 0;
}

.metric-card {
  text-align: center;
  padding: 10px 8px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  transition: box-shadow 0.2s;
}

.metric-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.metric-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  letter-spacing: 0.02em;
}

.metric-value {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
  line-height: 1.3;
}

.metric-value.large {
  font-size: 22px;
}

.metric-sub {
  font-size: 11px;
  color: #c0c4cc;
}

/* ── 窄屏自适应 ── */
@media (max-width: 1400px) {
  .metrics-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
