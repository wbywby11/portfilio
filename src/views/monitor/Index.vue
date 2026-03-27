<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">监控仪表板</h2>
      <div>
        <el-button type="primary" icon="el-icon-refresh" @click="loadData" :loading="loading">刷新数据</el-button>
      </div>
    </div>

    <div class="page-content" v-loading="loading">
      <template v-if="!monitorState">
        <el-empty :image-size="100">
          <template slot="description">
            <p class="empty-desc-title">尚未建立本策略的日常监控数据</p>
            <p class="empty-desc-line">该策略实例（monitor_id = 模型 ID）还未执行过「初始化」。</p>
            <p class="empty-desc-line">实盘发布仅完成准入，不会产生净值/绩效/信号；请在页面顶部点击「初始化」，完成后再使用「运行监控」滚动至最新交易日。</p>
          </template>
        </el-empty>
      </template>
      <template v-else>
      <el-alert
        v-if="performanceMismatch"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
        title="绩效与下方曲线可能与顶部「当前实盘生效参数」不一致"
        description="下方指标基于「最近一次初始化」时冻结的实盘快照；若已修改策略或再次实盘发布但未重新初始化，请重新执行初始化后再查看。">
      </el-alert>
      <div v-if="monitorState && monitorState.performance_basis" class="perf-basis-block">
        <div class="section-title">
          <span>本页绩效对应的实盘参数</span>
        </div>
        <p class="perf-basis-line muted">
          {{ performanceBasisMeta }}
        </p>
        <p v-if="perfBasisSummary" class="perf-basis-summary">{{ perfBasisSummary }}</p>
        <div v-if="perfBasisParams" class="perf-basis-metrics">
          <div class="perf-basis-metric">
            <span class="lbl">目标波动</span>
            <span class="val">{{ perfBasisParams.target_vol_pct }}%</span>
          </div>
          <div class="perf-basis-metric">
            <span class="lbl">波动重置阈值</span>
            <span class="val">{{ perfBasisParams.vol_reset_threshold_pct }}%</span>
          </div>
          <div class="perf-basis-metric">
            <span class="lbl">总杠杆上限</span>
            <span class="val">{{ perfBasisParams.max_total_leverage }}</span>
          </div>
        </div>
        <div
          v-if="perfBasisParams && perfBasisParams.asset_classes && perfBasisParams.asset_classes.length"
          class="perf-basis-asset-classes">
          <span class="perf-basis-block-label">资产类别</span>
          <el-tag
            v-for="(cls, cidx) in perfBasisParams.asset_classes"
            :key="'pb-cls-' + cidx"
            size="small"
            :type="assetClassTagType(cls)"
            effect="plain"
            class="perf-basis-class-tag">
            {{ cls }}
          </el-tag>
        </div>
        <div v-if="hasPerfBasisWindowParams" class="perf-basis-window-block">
          <div class="perf-basis-subtitle">动量与反转窗口（交易日）</div>
          <div class="perf-basis-metrics perf-basis-metrics--wrap">
            <div v-if="perfBasisParams.mom_windows" class="perf-basis-metric perf-basis-metric--wide">
              <span class="lbl">MOM</span>
              <span class="val val--subtle">{{ perfBasisParams.mom_windows }}</span>
            </div>
            <div v-if="perfBasisParams.posi_windows" class="perf-basis-metric perf-basis-metric--wide">
              <span class="lbl">POSI</span>
              <span class="val val--subtle">{{ perfBasisParams.posi_windows }}</span>
            </div>
            <div v-if="perfBasisParams.smom_windows" class="perf-basis-metric perf-basis-metric--wide">
              <span class="lbl">SMOM</span>
              <span class="val val--subtle">{{ perfBasisParams.smom_windows }}</span>
            </div>
            <div v-if="perfBasisParams.macd_windows" class="perf-basis-metric perf-basis-metric--wide">
              <span class="lbl">MACD 短期</span>
              <span class="val val--subtle">{{ perfBasisParams.macd_windows }}</span>
            </div>
            <div
              v-if="perfBasisParams.macd_long_window != null && perfBasisParams.macd_long_window !== ''"
              class="perf-basis-metric">
              <span class="lbl">MACD 长期</span>
              <span class="val val--subtle">{{ perfBasisParams.macd_long_window }}</span>
            </div>
            <div v-if="perfBasisParams.reversal_windows" class="perf-basis-metric perf-basis-metric--wide">
              <span class="lbl">反转</span>
              <span class="val val--subtle">{{ perfBasisParams.reversal_windows }}</span>
            </div>
            <div
              v-if="perfBasisParams.min_history_days != null && perfBasisParams.min_history_days !== ''"
              class="perf-basis-metric">
              <span class="lbl">最小历史天数</span>
              <span class="val val--subtle">{{ perfBasisParams.min_history_days }} 日</span>
            </div>
            <div
              v-if="perfBasisParams.min_history_momentum != null && perfBasisParams.min_history_momentum !== ''"
              class="perf-basis-metric">
              <span class="lbl">动量最小历史</span>
              <span class="val val--subtle">{{ perfBasisParams.min_history_momentum }} 日</span>
            </div>
            <div
              v-if="perfBasisParams.min_history_reversal != null && perfBasisParams.min_history_reversal !== ''"
              class="perf-basis-metric">
              <span class="lbl">反转最小历史</span>
              <span class="val val--subtle">{{ perfBasisParams.min_history_reversal }} 日</span>
            </div>
          </div>
        </div>
      </div>
      <el-alert
        v-else
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
        title="未记录绩效对应的参数快照"
        description="请重新执行页面顶部「初始化」后，此处将展示与净值曲线一致的实盘参数说明。">
      </el-alert>
      <!-- 策略表现指标卡片区 -->
      <div class="section-title">
        <span>策略表现</span>
      </div>
      <el-row :gutter="20" class="metrics-row">
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card primary">
            <div class="metric-label">当前净值</div>
            <div class="metric-value large">{{ formatNumber(currentNav, 2) }}</div>
            <div class="metric-sub">更新: {{ formatDate(monitorState && monitorState.date) }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">总杠杆</div>
            <div class="metric-value">{{ formatNumber(totalLeverage, 2) }}</div>
            <div class="metric-sub">目标: 1.00</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">年化收益率</div>
            <div class="metric-value" :style="{ color: getReturnColor(performance && performance.annual_return) }">
              {{ formatPercent(performance && performance.annual_return) }}
            </div>
            <div class="metric-sub">历史年化</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">年化波动率</div>
            <div class="metric-value">{{ formatPercent(performance && performance.annual_volatility) }}</div>
            <div class="metric-sub">历史波动</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">夏普比率</div>
            <div class="metric-value">{{ formatNumber(performance && performance.sharpe_ratio, 3) }}</div>
            <div class="metric-sub">风险调整</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">最大回撤</div>
            <div class="metric-value" style="color: #67C23A;">
              {{ formatPercent(performance && performance.max_drawdown) }}
            </div>
            <div class="metric-sub">历史最大</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 当日表现指标区域 -->
      <div class="section-title" style="margin-top: 25px;">
        <span>当日表现</span>
      </div>
      <el-row :gutter="20" class="metrics-row">
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">当日收益额</div>
            <div class="metric-value" :style="{ color: getReturnColor(dailyPnL) }">
              {{ dailyPnL !== null ? (dailyPnL >= 0 ? '+' : '') + formatNumber(dailyPnL, 4) : '-' }}
            </div>
            <div class="metric-sub">净值变动</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">当日收益率</div>
            <div class="metric-value" :style="{ color: getReturnColor(dailyReturnPct) }">
              {{ dailyReturnPct !== null ? formatSignedPercent(dailyReturnPct) : '-' }}
            </div>
            <div class="metric-sub">较前日</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">当前回撤</div>
            <div class="metric-value" style="color: #67C23A;">
              {{ formatPercent(currentDrawdown) }}
            </div>
            <div class="metric-sub">距离高点</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">持仓资产数</div>
            <div class="metric-value">{{ positionCount }}</div>
            <div class="metric-sub">权重 > 0</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">距下次调仓</div>
            <div class="metric-value">{{ daysToNextRebalance != null ? daysToNextRebalance : '-' }}</div>
            <div class="metric-sub">天</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">监测波动率</div>
            <div class="metric-value" :style="{ color: monitoredVolatilityColor }">
              {{ formattedMonitoredVolatility }}
            </div>
            <div class="metric-sub">阈值: {{ formattedVolThreshold }}</div>
          </el-card>
        </el-col>
      </el-row>
      </template>
    </div>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import { mapState, mapActions } from 'vuex';

export default {
  name: 'MonitorIndex',
  props: {
    strategyContext: {
      type: Object,
      default: null
    }
  },
  data() {
    return {
      loading: false
    };
  },
  computed: {
    ...mapState('monitor', ['monitorState', 'navHistory', 'performance', 'signals']),
    perfBasisParams() {
      const pb = this.monitorState && this.monitorState.performance_basis;
      if (!pb || !pb.live_effective_params) return null;
      return pb.live_effective_params;
    },
    perfBasisSummary() {
      const pb = this.monitorState && this.monitorState.performance_basis;
      return pb && pb.live_effective_summary ? pb.live_effective_summary : '';
    },
    performanceBasisMeta() {
      const pb = this.monitorState && this.monitorState.performance_basis;
      if (!pb) return '';
      const v = pb.live_version != null ? `v${pb.live_version}` : '—';
      const cap = pb.captured_at ? this.formatPerfCaptured(pb.captured_at) : '—';
      return `初始化快照 · 实盘版本 ${v} · 记录时间 ${cap}`;
    },
    performanceMismatch() {
      const pb = this.monitorState && this.monitorState.performance_basis;
      const cur = this.strategyContext;
      if (!pb || !cur || cur.is_config_baseline) return false;
      const pv = pb.live_version;
      const cv = cur.live_version;
      if (pv == null || cv == null) return false;
      return Number(pv) !== Number(cv);
    },
    /** 与日常监控顶部「实盘生效参数」窗口块一致，用于绩效说明区展示 */
    hasPerfBasisWindowParams() {
      const p = this.perfBasisParams;
      if (!p) return false;
      return !!(
        p.mom_windows ||
        p.posi_windows ||
        p.smom_windows ||
        p.reversal_windows ||
        p.macd_windows ||
        (p.macd_long_window != null && p.macd_long_window !== '') ||
        (p.min_history_days != null && p.min_history_days !== '') ||
        (p.min_history_momentum != null && p.min_history_momentum !== '') ||
        (p.min_history_reversal != null && p.min_history_reversal !== '')
      );
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
    // 当前波动率
    currentVolatility() {
      if (this.signals && this.signals.vol_reset && this.signals.vol_reset.current_volatility !== undefined) {
        return this.signals.vol_reset.current_volatility;
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
    // 当前回撤
    currentDrawdown() {
      if (!this.navHistory || this.navHistory.length < 2) return null;
      const navValues = this.navHistory.map(h => h.nav);
      const currentNav = navValues[navValues.length - 1];
      let peak = navValues[0];
      for (const nav of navValues) {
        if (nav > peak) peak = nav;
      }
      return (currentNav / peak) - 1;  // 负数表示回撤
    },
    // 持仓资产数（小数权重，|w|>0.01 视为有效持仓，约 1% 以上）
    positionCount() {
      const weights = this.monitorState && this.monitorState.target_weights ? this.monitorState.target_weights : {};
      return Object.values(weights).filter(w => Math.abs(w) > 0.01).length;
    },
    // 波动率阈值（百分比数字，如 6 表示 6%）
    volResetThreshold() {
      if (this.signals && this.signals.vol_reset && this.signals.vol_reset.threshold !== undefined) {
        return this.signals.vol_reset.threshold;
      }
      return 6;  // 默认 6%
    },
    // 格式化的监测波动率
    formattedMonitoredVolatility() {
      if (this.currentVolatility === null) return '-';
      return this.currentVolatility.toFixed(2) + '%';
    },
    // 格式化的波动率阈值
    formattedVolThreshold() {
      return this.volResetThreshold.toFixed(2) + '%';
    },
    // 监测波动率颜色
    monitoredVolatilityColor() {
      if (this.currentVolatility === null) return '#909399';
      if (this.currentVolatility >= this.volResetThreshold) {
        return '#F56C6C';  // 红色 - 预警
      }
      return '#67C23A';  // 绿色 - 正常
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
    formatNumber(num, decimals = 2) {
      if (num === null || num === undefined) return '-';
      return num.toFixed(decimals);
    },
    formatPercent(num) {
      if (num === null || num === undefined) return '-';
      return num.toFixed(2) + '%';
    },
    formatSignedPercent(num) {
      if (num === null || num === undefined) return '-';
      const pct = num * 100;
      const sign = pct >= 0 ? '+' : '';
      return sign + pct.toFixed(2) + '%';
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '-';
    },
    formatPerfCaptured(iso) {
      if (!iso) return '—';
      const d = dayjs(iso);
      return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : String(iso);
    },
    getReturnColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (value > 0) return '#F56C6C';  // 涨用红色
      if (value < 0) return '#67C23A';  // 跌用绿色
      return '#909399';
    },
    assetClassTagType(assetClass) {
      const map = { '权益': 'primary', '固定收益': 'success', '大宗商品': 'warning', '其他': 'info' };
      return map[assetClass] || 'info';
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 500;
}

.page-content {
  min-height: 400px;
}

.section-title {
  margin-bottom: 15px;
}

.section-title span {
  font-size: 15px;
  font-weight: 500;
  color: #303133;
}

.metrics-row {
  margin-bottom: 0;
}

.metric-card {
  text-align: center;
  padding: 15px;
}

.metric-card.primary {
  background: linear-gradient(135deg, #409EFF 0%, #66b1ff 100%);
  color: #fff;
}

.metric-card.primary .metric-label,
.metric-card.primary .metric-sub {
  color: rgba(255, 255, 255, 0.85);
}

.metric-card.primary .metric-value {
  color: #fff;
}

.metric-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.metric-value {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 5px;
}

.metric-value.large {
  font-size: 32px;
}

.metric-sub {
  font-size: 12px;
  color: #c0c4cc;
}

.perf-basis-block {
  margin-bottom: 20px;
  padding: 12px 14px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
}

.perf-basis-line.muted {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: #909399;
}

.perf-basis-summary {
  margin: 0 0 10px 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}

.perf-basis-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.perf-basis-metric {
  min-width: 100px;
  padding: 8px 12px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.perf-basis-metric .lbl {
  display: block;
  font-size: 11px;
  color: #909399;
  margin-bottom: 4px;
}

.perf-basis-metric .val {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
}

.perf-basis-metric .val.val--subtle {
  font-size: 14px;
  font-weight: 600;
  word-break: break-all;
}

.perf-basis-metric--wide {
  flex: 1 1 200px;
  min-width: 160px;
}

.perf-basis-metrics--wrap {
  margin-top: 6px;
}

.perf-basis-asset-classes {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e4e7ed;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.perf-basis-block-label {
  font-size: 12px;
  color: #909399;
  margin-right: 4px;
}

.perf-basis-class-tag {
  margin: 0 !important;
}

.perf-basis-window-block {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e4e7ed;
}

.perf-basis-subtitle {
  font-size: 12px;
  color: #909399;
  font-weight: 600;
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}

.empty-desc-title {
  font-weight: 600;
  color: #303133;
  margin: 0 0 10px 0;
  font-size: 15px;
}

.empty-desc-line {
  margin: 6px 0;
  color: #606266;
  font-size: 14px;
  line-height: 1.6;
  max-width: 520px;
  margin-left: auto;
  margin-right: auto;
  text-align: left;
}
</style>
