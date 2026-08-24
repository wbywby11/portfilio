<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">模拟交易面板</h2>
        <p class="page-desc" v-if="portfolio.name">{{ portfolio.name }} — 逐日推进 &amp; 跟踪评估</p>
      </div>
      <div>
        <el-button @click="$router.push({ name: 'SimTradeSelector' })">返回列表</el-button>
        <el-button type="primary" icon="el-icon-refresh" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <div class="page-content" v-loading="loading">
      <!-- 顶部：组合信息 + 推进操作 -->
      <el-row :gutter="20">
        <el-col :span="16">
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>组合概览</span>
              <el-tag :type="portfolio.portfolio_type === '模型驱动' ? 'success' : 'info'" size="small">
                {{ portfolio.portfolio_type || '-' }}
              </el-tag>
            </div>
            <el-descriptions :column="3" border size="medium">
              <el-descriptions-item label="初始资金">¥{{ fmtNum(portfolio.initial_capital) }}</el-descriptions-item>
              <el-descriptions-item label="当前资金">¥{{ fmtNum(portfolio.current_capital) }}</el-descriptions-item>
              <el-descriptions-item label="建仓日期">{{ fmtDate(portfolio.inception_date) }}</el-descriptions-item>
              <el-descriptions-item label="最新净值">
                {{ latestSnapshot ? latestSnapshot.nav.toFixed(4) : '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="累计收益">
                <span :style="{ color: getRetColor(latestSnapshot ? latestSnapshot.cumulative_return : 0) }">
                  {{ latestSnapshot ? (latestSnapshot.cumulative_return * 100).toFixed(2) + '%' : '-' }}
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="已推进天数">
                {{ snapshots.length }} 天
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="never" class="info-card advance-card">
            <div slot="header" class="card-header"><span>推进操作</span></div>
            <div class="advance-form">
              <el-date-picker
                v-model="targetDate"
                type="date"
                placeholder="选择目标日期"
                format="yyyy-MM-dd"
                value-format="yyyy-MM-dd"
                :picker-options="{ disabledDate: d => d.getTime() < Date.now() - 86400000 }"
                style="width: 100%; margin-bottom: 12px;"
              />
              <el-button type="primary" :loading="advancing" style="width: 100%;" @click="handleAdvance" :disabled="!targetDate">
                <i class="el-icon-video-play"></i> 推进到目标日期
              </el-button>
              <el-button type="warning" :loading="batchAdvancing" style="width: 100%; margin-top: 8px;" plain @click="handleBatchAdvance">
                <i class="el-icon-s-operation"></i> 批量推进所有组合
              </el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 中部：NAV 对比曲线 + 跟踪误差统计 -->
      <el-row :gutter="20">
        <el-col :span="16">
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>NAV 对比曲线</span>
              <span style="color: #909399; font-size: 12px;">模拟 NAV vs 回测 NAV</span>
            </div>
            <div ref="navChart" style="width: 100%; height: 400px;"></div>
            <el-empty v-if="snapshots.length === 0" description="暂无快照数据，请先推进模拟交易" :image-size="80"></el-empty>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header"><span>跟踪误差统计</span></div>
            <div v-if="tracking" class="metrics-container">
              <div class="metric-item">
                <div class="metric-label">年化跟踪误差</div>
                <div class="metric-value">{{ fmtPct(tracking.annualized_error) }}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">信息比率</div>
                <div class="metric-value">{{ tracking.information_ratio ? tracking.information_ratio.toFixed(3) : '-' }}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">最大偏离</div>
                <div class="metric-value" style="color: #f56c6c;">{{ fmtPct(tracking.max_deviation) }}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">平均日偏离</div>
                <div class="metric-value">{{ fmtPct(tracking.mean_daily_error) }}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">样本天数</div>
                <div class="metric-value">{{ tracking.sample_days || '-' }}</div>
              </div>
            </div>
            <el-empty v-else description="暂无跟踪数据" :image-size="80"></el-empty>
          </el-card>

          <!-- 绩效归因 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header"><span>Brinson 绩效归因</span></div>
            <div v-if="attribution" class="metrics-container">
              <div class="metric-item">
                <div class="metric-label">配置效应</div>
                <div class="metric-value" :style="{ color: getRetColor(attribution.allocation_effect) }">
                  {{ fmtPct(attribution.allocation_effect) }}
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-label">选择效应</div>
                <div class="metric-value" :style="{ color: getRetColor(attribution.selection_effect) }">
                  {{ fmtPct(attribution.selection_effect) }}
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-label">交互效应</div>
                <div class="metric-value" :style="{ color: getRetColor(attribution.interaction_effect) }">
                  {{ fmtPct(attribution.interaction_effect) }}
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-label">总超额收益</div>
                <div class="metric-value" :style="{ color: getRetColor(attribution.total_excess) }">
                  {{ fmtPct(attribution.total_excess) }}
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无归因数据" :image-size="80"></el-empty>
          </el-card>
        </el-col>
      </el-row>

      <!-- 下部：成交记录表格 -->
      <el-card shadow="never" class="info-card">
        <div slot="header" class="card-header">
          <span>成交记录</span>
          <div>
            <el-date-picker v-model="tradeDateRange" type="daterange" range-separator="至"
              start-placeholder="开始日期" end-placeholder="结束日期" format="yyyy-MM-dd"
              value-format="yyyy-MM-dd" size="small" style="margin-right: 10px;"
              @change="loadTrades" />
            <el-button size="small" icon="el-icon-refresh" @click="loadTrades">刷新</el-button>
          </div>
        </div>

        <el-table :data="trades" border style="width: 100%;" v-loading="tradesLoading">
          <el-table-column prop="trade_date" label="成交日期" width="110">
            <template slot-scope="scope">{{ fmtDate(scope.row.trade_date) }}</template>
          </el-table-column>
          <el-table-column prop="asset_code" label="资产代码" width="110"></el-table-column>
          <el-table-column prop="asset_name" label="资产名称" width="130"></el-table-column>
          <el-table-column prop="side" label="方向" width="70" align="center">
            <template slot-scope="scope">
              <el-tag :type="scope.row.side === 'buy' ? 'success' : 'danger'" size="mini">
                {{ scope.row.side === 'buy' ? '买入' : '卖出' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="100" align="right">
            <template slot-scope="scope">{{ scope.row.quantity.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="price" label="价格" width="100" align="right">
            <template slot-scope="scope">{{ scope.row.price.toFixed(4) }}</template>
          </el-table-column>
          <el-table-column prop="gross_amount" label="成交金额" width="120" align="right">
            <template slot-scope="scope">¥{{ fmtNum(scope.row.gross_amount) }}</template>
          </el-table-column>
          <el-table-column prop="commission" label="手续费" width="90" align="right">
            <template slot-scope="scope">{{ scope.row.commission.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="slippage_cost" label="滑点成本" width="90" align="right">
            <template slot-scope="scope">{{ scope.row.slippage_cost.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="trigger_reason" label="触发原因" min-width="120">
            <template slot-scope="scope">
              <el-tag size="mini" type="info">{{ reasonLabel(scope.row.trigger_reason) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!tradesLoading && trades.length === 0" description="暂无成交记录"></el-empty>

        <div v-if="totalTrades > tradePageSize" style="text-align: right; margin-top: 12px;">
          <el-pagination background layout="prev, pager, next"
            :total="totalTrades" :page-size="tradePageSize" :current-page.sync="tradePage"
            @current-change="loadTrades" />
        </div>
      </el-card>
    </div>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import * as echarts from 'echarts';
import * as portfolioApi from '@/api/portfolio';
import * as simTradeApi from '@/api/simTrade';

export default {
  name: 'SimTradeDashboard',
  data() {
    return {
      loading: false,
      advancing: false,
      batchAdvancing: false,
      tradesLoading: false,
      portfolioId: null,
      portfolio: {},
      snapshots: [],
      trades: [],
      tracking: null,
      attribution: null,
      targetDate: '',
      tradeDateRange: null,
      tradePage: 1,
      tradePageSize: 20,
      totalTrades: 0,
      navChart: null
    };
  },
  computed: {
    latestSnapshot() {
      return this.snapshots.length > 0 ? this.snapshots[this.snapshots.length - 1] : null;
    }
  },
  created() {
    this.portfolioId = this.$route.params.id;
    this.loadAll();
  },
  mounted() {
    this.$nextTick(() => this.initChart());
  },
  beforeDestroy() {
    if (this.navChart) this.navChart.dispose();
  },
  methods: {
    async loadAll() {
      this.loading = true;
      try {
        await Promise.all([this.loadPortfolio(), this.loadSnapshots(), this.loadTrades(), this.loadTracking(), this.loadAttribution()]);
      } finally {
        this.loading = false;
      }
    },

    async loadPortfolio() {
      try {
        const res = await portfolioApi.getPortfolio(this.portfolioId);
        this.portfolio = res.data || {};
      } catch (e) {
        this.$message.error('加载组合信息失败');
      }
    },

    async loadSnapshots() {
      try {
        const res = await simTradeApi.getSimSnapshots(this.portfolioId, { limit: 1000 });
        this.snapshots = res.data || [];
        this.$nextTick(() => this.renderNavChart());
      } catch (e) {
        console.warn('快照加载失败:', e);
      }
    },

    async loadTrades() {
      this.tradesLoading = true;
      try {
        const params = {
          skip: (this.tradePage - 1) * this.tradePageSize,
          limit: this.tradePageSize
        };
        if (this.tradeDateRange && this.tradeDateRange.length === 2) {
          params.start_date = this.tradeDateRange[0];
          params.end_date = this.tradeDateRange[1];
        }
        const res = await simTradeApi.getSimTrades(this.portfolioId, params);
        this.trades = res.data || [];
        this.totalTrades = res.total || this.trades.length;
      } catch (e) {
        console.warn('成交记录加载失败:', e);
      } finally {
        this.tradesLoading = false;
      }
    },

    async loadTracking() {
      try {
        const res = await simTradeApi.getTrackingReport(this.portfolioId);
        this.tracking = res.data || null;
      } catch (e) {
        console.warn('跟踪报告加载失败:', e);
      }
    },

    async loadAttribution() {
      try {
        const res = await simTradeApi.getAttributionReport(this.portfolioId);
        this.attribution = res.data || null;
      } catch (e) {
        console.warn('归因报告加载失败:', e);
      }
    },

    async handleAdvance() {
      if (!this.targetDate) return;
      this.advancing = true;
      try {
        const res = await simTradeApi.advanceSimTrade(this.portfolioId, { target_date: this.targetDate });
        const msg = res.data ? `推进完成，新增 ${res.data.trades_generated || 0} 笔成交` : '推进完成';
        this.$message.success(msg);
        this.targetDate = '';
        await Promise.all([this.loadSnapshots(), this.loadTrades(), this.loadTracking(), this.loadAttribution(), this.loadPortfolio()]);
      } catch (e) {
        this.$message.error('推进失败: ' + (e.response?.data?.message || e.message));
      } finally {
        this.advancing = false;
      }
    },

    async handleBatchAdvance() {
      this.batchAdvancing = true;
      try {
        const res = await simTradeApi.batchAdvanceSimTrade();
        this.$message.success('批量推进完成: ' + (res.data?.message || ''));
        await this.loadAll();
      } catch (e) {
        this.$message.error('批量推进失败: ' + (e.response?.data?.message || e.message));
      } finally {
        this.batchAdvancing = false;
      }
    },

    initChart() {
      if (this.$refs.navChart && !this.navChart) {
        this.navChart = echarts.init(this.$refs.navChart);
      }
    },

    renderNavChart() {
      this.initChart();
      if (!this.navChart || this.snapshots.length === 0) return;

      const dates = this.snapshots.map(s => dayjs(s.date).format('YYYY-MM-DD'));
      const simNav = this.snapshots.map(s => s.nav);
      const btNav = this.snapshots.map(s => s.backtest_nav || null);
      const trackingErr = this.snapshots.map(s => s.tracking_error != null ? s.tracking_error * 100 : null);

      const option = {
        tooltip: {
          trigger: 'axis',
          formatter(params) {
            let tip = params[0].axisValue;
            params.forEach(p => {
              if (p.value != null) {
                tip += `<br/>${p.marker} ${p.seriesName}: ${typeof p.value === 'number' ? p.value.toFixed(4) : p.value}`;
              }
            });
            return tip;
          }
        },
        legend: { data: ['模拟 NAV', '回测 NAV', '跟踪误差 (%)'], top: 5 },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: dates, boundaryGap: false },
        yAxis: [
          { type: 'value', name: 'NAV', axisLabel: { formatter: '{value}' } },
          { type: 'value', name: '误差 %', axisLabel: { formatter: '{value}%' }, splitLine: { show: false } }
        ],
        series: [
          {
            name: '模拟 NAV', type: 'line', data: simNav, smooth: true, symbol: 'none',
            lineStyle: { width: 2, color: '#409EFF' },
            areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(64,158,255,0.2)' }, { offset: 1, color: 'rgba(64,158,255,0.02)' }] } }
          },
          {
            name: '回测 NAV', type: 'line', data: btNav, smooth: true, symbol: 'none',
            lineStyle: { width: 2, color: '#67C23A', type: 'dashed' }
          },
          {
            name: '跟踪误差 (%)', type: 'bar', yAxisIndex: 1, data: trackingErr, barWidth: '40%',
            itemStyle: {
              color(params) { return params.value >= 0 ? 'rgba(103,194,58,0.5)' : 'rgba(245,108,108,0.5)'; }
            }
          }
        ]
      };
      this.navChart.setOption(option, true);
    },

    // ---- 格式化工具 ----
    fmtNum(v) { return new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0); },
    fmtPct(v) { return ((v || 0) * 100).toFixed(2) + '%'; },
    fmtDate(d) { return d ? dayjs(d).format('YYYY-MM-DD') : '-'; },
    getRetColor(v) { return v > 0 ? '#67c23a' : v < 0 ? '#f56c6c' : '#909399'; },
    reasonLabel(r) {
      const map = { periodic_rebalance: '定期调仓', vol_reset: '波动率重置', manual_adjust: '手动调整' };
      return map[r] || r || '-';
    }
  }
};
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
.info-card { margin-bottom: 20px; }
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}
.advance-card { min-height: 180px; }
.advance-form { padding: 4px 0; }
.metrics-container { display: flex; flex-direction: column; gap: 12px; }
.metric-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 4px;
}
.metric-label { font-size: 14px; color: #606266; }
.metric-value { font-size: 18px; font-weight: 600; color: #303133; }
</style>
