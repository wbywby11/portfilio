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
            <div class="metric-value large">{{ formatNumber(currentNav, 4) }}</div>
            <div class="metric-sub">更新: {{ formatDate(monitorState && monitorState.date) }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">日涨跌幅</div>
            <div class="metric-value" :style="{ color: getReturnColor(performance && performance.daily_return) }">
              {{ formatPercent(performance && performance.daily_return) }}
            </div>
            <div class="metric-sub">较前日</div>
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
      </el-row>

      <el-row :gutter="20" style="margin-top: 20px;">
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
            <div class="metric-label">当日年化收益</div>
            <div class="metric-value" :style="{ color: getReturnColor(dailyAnnualReturn) }">
              {{ dailyAnnualReturn !== null ? formatSignedPercent(dailyAnnualReturn) : '-' }}
            </div>
            <div class="metric-sub">年化因子: 260</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">当日波动率</div>
            <div class="metric-value" :class="{ 'warning-text': isVolatilityHigh }">
              {{ currentVolatility !== null ? formatPercent(currentVolatility) : '-' }}
            </div>
            <div class="metric-sub">阈值: 6.00%</div>
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
      </el-row>

      <el-row :gutter="20" style="margin-top: 15px;">
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">距下次调仓</div>
            <div class="metric-value">{{ daysToNextRebalance != null ? daysToNextRebalance : '-' }}</div>
            <div class="metric-sub">天</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="metric-card">
            <div class="metric-label">波动率状态</div>
            <div class="metric-value">
              <el-tag :type="volatilityStatusType" size="small">{{ volatilityStatusText }}</el-tag>
            </div>
            <div class="metric-sub">vs 阈值 6%</div>
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
    // 计算总杠杆：target_weights 所有值的绝对值之和
    totalLeverage() {
      const weights = (this.monitorState && this.monitorState.target_weights) ? this.monitorState.target_weights : {};
      return Object.values(weights).reduce((sum, w) => sum + Math.abs(w), 0);
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
    // 当日年化收益率（小数形式）
    dailyAnnualReturn() {
      if (this.dailyReturnPct !== null) {
        return this.dailyReturnPct * 260;  // 年化因子
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
    // 持仓资产数（权重大于0的资产数量）
    positionCount() {
      const weights = this.monitorState && this.monitorState.target_weights ? this.monitorState.target_weights : {};
      return Object.values(weights).filter(w => Math.abs(w) > 0.0001).length;
    },
    // 波动率是否预警
    isVolatilityHigh() {
      return this.currentVolatility !== null && this.currentVolatility > 0.06;
    },
    // 波动率状态类型
    volatilityStatusType() {
      if (this.currentVolatility === null) return 'info';
      return this.currentVolatility > 0.06 ? 'danger' : 'success';
    },
    // 波动率状态文本
    volatilityStatusText() {
      if (this.currentVolatility === null) return '-';
      return this.currentVolatility > 0.06 ? '预警' : '正常';
    },
    // 计算距下次调仓天数
    daysToNextRebalance() {
      const nextDate = (this.signals && this.signals.monthly_rebalance && this.signals.monthly_rebalance.next_date) 
        ? this.signals.monthly_rebalance.next_date : null;
      if (!nextDate) return null;
      const today = new Date();
      const target = new Date(nextDate);
      const diffTime = target - today;
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
          this.fetchNavHistory()
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
      return (num * 100).toFixed(2) + '%';
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

.warning-text {
  color: #E6A23C !important;
}
</style>
