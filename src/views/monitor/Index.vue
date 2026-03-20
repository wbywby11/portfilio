<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">监控仪表板</h2>
      <div>
        <el-button type="primary" icon="el-icon-refresh" @click="loadData" :loading="loading">刷新数据</el-button>
      </div>
    </div>

    <div class="page-content" v-loading="loading">
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
    </div>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import { mapState, mapActions } from 'vuex';

export default {
  name: 'MonitorIndex',
  data() {
    return {
      loading: false
    };
  },
  computed: {
    ...mapState('monitor', ['monitorState', 'navHistory', 'performance', 'signals']),
    currentNav() {
      return (this.monitorState && this.monitorState.nav) ? this.monitorState.nav : 1;
    },
    // 计算总杠杆：target_weights 所有值的绝对值之和（权重为百分比形式，需除以100）
    totalLeverage() {
      const weights = (this.monitorState && this.monitorState.target_weights) ? this.monitorState.target_weights : {};
      const sum = Object.values(weights).reduce((sum, w) => sum + Math.abs(w), 0);
      return sum / 100;
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
    // 持仓资产数（权重大于0的资产数量，权重为百分比形式，阈值用0.01过滤接近0的值）
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
          this.fetchNavHistory({ monitor_id: 'default' })
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
    getReturnColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (value > 0) return '#F56C6C';  // 涨用红色
      if (value < 0) return '#67C23A';  // 跌用绿色
      return '#909399';
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
</style>
