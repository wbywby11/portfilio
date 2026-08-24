<template>
  <div class="dashboard">
    <!-- 统计概览 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="8">
        <div class="stat-card" @click="$router.push({ name: 'PortfolioList' })">
          <div class="stat-icon blue"><i class="el-icon-s-data"></i></div>
          <div class="stat-content">
            <div class="stat-value">{{ portfolioCount }}</div>
            <div class="stat-label">我的组合</div>
          </div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="stat-card" @click="$router.push({ name: 'StrategyModelList' })">
          <div class="stat-icon green"><i class="el-icon-data-analysis"></i></div>
          <div class="stat-content">
            <div class="stat-value">{{ strategyCount }}</div>
            <div class="stat-label">我的策略</div>
          </div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="stat-card" @click="$router.push({ name: 'AssetList' })">
          <div class="stat-icon orange"><i class="el-icon-coin"></i></div>
          <div class="stat-content">
            <div class="stat-value">{{ assetTotal }}</div>
            <div class="stat-label">可用资产</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 两列：最近策略 + 最近组合 -->
    <el-row :gutter="16" type="flex">
      <el-col :span="12">
        <div class="section-card equal-height">
          <div class="section-header">
            <span class="section-title">最近策略</span>
            <el-button type="text" @click="$router.push({ name: 'StrategyModelList' })">查看全部</el-button>
          </div>
          <el-table
            v-if="recentStrategies.length"
            :data="recentStrategies"
            size="small"
            style="width: 100%"
          >
            <el-table-column prop="name" label="策略名称" min-width="120" show-overflow-tooltip>
              <template slot-scope="scope">
                <a class="link-text" @click="goStrategy(scope.row.id)">{{ scope.row.name }}</a>
              </template>
            </el-table-column>
            <el-table-column prop="template_code" label="模板" width="130" show-overflow-tooltip></el-table-column>
            <el-table-column label="年化收益" width="90" align="right">
              <template slot-scope="scope">
                <span v-if="getBacktestMetric(scope.row, 'annual_return') != null"
                      :class="returnClass(getBacktestMetric(scope.row, 'annual_return'))">
                  {{ formatPercent(getBacktestMetric(scope.row, 'annual_return')) }}
                </span>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="empty-tip">
            <i class="el-icon-data-analysis"></i>
            <p>暂无策略，</p>
            <a class="link-text" @click="$router.push({ name: 'StrategyTemplate' })">从策略库开始</a>
          </div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="section-card equal-height">
          <div class="section-header">
            <span class="section-title">最近组合</span>
            <el-button type="text" @click="$router.push({ name: 'PortfolioList' })">查看全部</el-button>
          </div>
          <el-table
            v-if="recentPortfolios.length"
            :data="recentPortfolios"
            size="small"
            style="width: 100%"
          >
            <el-table-column prop="name" label="组合名称" min-width="120" show-overflow>
              <template slot-scope="scope">
                <a class="link-text" @click="goPortfolio(scope.row.id)">{{ scope.row.name }}</a>
              </template>
            </el-table-column>
            <el-table-column label="当前市值" width="100" align="right">
              <template slot-scope="scope">
                {{ formatMoney(scope.row.current_capital) }}
              </template>
            </el-table-column>
            <el-table-column label="累计收益" width="90" align="right">
              <template slot-scope="scope">
                <span v-if="getPortfolioReturn(scope.row) != null"
                      :class="returnClass(getPortfolioReturn(scope.row))">
                  {{ formatPercent(getPortfolioReturn(scope.row)) }}
                </span>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="90">
              <template slot-scope="scope">
                {{ sourceLabel(scope.row.source) }}
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="empty-tip">
            <i class="el-icon-folder-opened"></i>
            <p>暂无组合，</p>
            <a class="link-text" @click="$router.push({ name: 'PortfolioList' })">创建组合</a>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 功能模块导航 -->
    <div class="section-card">
      <div class="section-header">
        <span class="section-title">功能模块</span>
      </div>
      <el-row :gutter="12">
        <el-col :span="6" v-for="nav in navItems" :key="nav.name">
          <div class="nav-card" @click="$router.push({ name: nav.name })">
            <i :class="nav.icon" class="nav-icon"></i>
            <div class="nav-info">
              <span class="nav-label">{{ nav.label }}</span>
              <span class="nav-desc">{{ nav.desc }}</span>
            </div>
          </div>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script>
import { mapGetters, mapState } from 'vuex';

export default {
  name: 'Dashboard',
  data() {
    return {
      navItems: [
        { label: '策略库', icon: 'el-icon-notebook-2', name: 'StrategyTemplate', desc: '内置策略模板' },
        { label: '回测执行', icon: 'el-icon-video-play', name: 'BacktestExecution', desc: '策略回测验证' },
        { label: '资产分析', icon: 'el-icon-data-line', name: 'Analysis', desc: '数据统计与可视化' },
        { label: '智能对话', icon: 'el-icon-chat-dot-round', name: 'AgentWorkspace', desc: 'AI 辅助分析' },
        { label: '资产行情', icon: 'el-icon-trend-charts', name: 'AssetQuote', desc: 'K线与行情导入' },
        { label: '数据接入', icon: 'el-icon-connection', name: 'DataHubCenter', desc: '外部数据同步' },
        { label: '估值工作台', icon: 'el-icon-trophy', name: 'ValuationWorkbench', desc: '收益凭证估值' },
        { label: '日常监控', icon: 'el-icon-monitor', name: 'MonitorCenter', desc: '组合运行监控' }
      ]
    };
  },
  computed: {
    ...mapGetters('user', ['userName']),
    ...mapState('portfolio', ['portfolioList']),
    ...mapGetters('strategy', ['strategyList']),
    ...mapState('asset', ['assetList', 'total']),
    portfolioCount() {
      return (this.portfolioList || []).length;
    },
    strategyCount() {
      return (this.strategyList || []).length;
    },
    assetTotal() {
      // asset store 的 total 字段反映数据库真实总数（分页不受影响）
      return this.total || (this.assetList || []).length;
    },
    recentStrategies() {
      return (this.strategyList || []).slice(0, 5);
    },
    recentPortfolios() {
      return (this.portfolioList || []).slice(0, 5);
    }
  },
  created() {
    this.loadData();
  },
  methods: {
    async loadData() {
      await Promise.all([
        this.$store.dispatch('portfolio/fetchPortfolioList'),
        this.$store.dispatch('strategy/fetchStrategyModelList'),
        this.$store.dispatch('asset/fetchAssetList', { pageSize: 1 })
      ]);
    },
    statusTagType(status) {
      return { '已发布': 'success', '草稿': 'info', '已归档': 'warning' }[status] || 'info';
    },
    sourceLabel(source) {
      return {
        manual: '手工创建',
        single_strategy: '单策略驱动',
        portfolio_model: '组合模型'
      }[source] || source || '—';
    },
    // 从策略的 latest_backtest_summary 中提取指标（后端字段 snake_case）
    getBacktestMetric(row, metric) {
      const summary = row.latest_backtest_summary;
      if (!summary) return null;
      // 后端 annual_return / annual_vol / sharpe / max_drawdown / total_return
      const val = summary[metric];
      return val != null ? val : null;
    },
    // 组合的累计收益：优先 total_return，回退到 latest_backtest_summary.total_return
    getPortfolioReturn(row) {
      if (row.total_return != null) return row.total_return;
      const summary = row.latest_backtest_summary;
      if (summary && summary.total_return != null) return summary.total_return;
      return null;
    },
    // 百分比格式化（后端值为小数，如 0.12 表示 12%）
    formatPercent(val) {
      if (val == null) return '—';
      return (val * 100).toFixed(2) + '%';
    },
    // 金额格式化（后端值为元）
    formatMoney(val) {
      if (val == null) return '—';
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
      }).format(val);
    },
    // 收益颜色
    returnClass(val) {
      if (val == null) return '';
      if (val > 0) return 'text-positive';
      if (val < 0) return 'text-negative';
      return 'text-muted';
    },
    goStrategy(id) {
      this.$router.push({ name: 'StrategyModelDetail', params: { id } });
    },
    goPortfolio(id) {
      this.$router.push({ name: 'PortfolioDetail', params: { id } });
    }
  }
};
</script>

<style scoped>
.dashboard {
  height: 100%;
}

/* 统计卡片 */
.stats-row {
  margin-bottom: 16px;
}

.stat-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  cursor: pointer;
  transition: box-shadow 0.2s;
  border: 1px solid #ebeef5;
}

.stat-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon i {
  font-size: 22px;
  color: #fff;
}

.stat-icon.blue { background: #409eff; }
.stat-icon.green { background: #67c23a; }
.stat-icon.orange { background: #e6a23c; }

.stat-value {
  font-size: 26px;
  font-weight: 600;
  color: #1f2937;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 2px;
}

/* 通用区块卡片 */
.section-card {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  padding: 20px;
  margin-bottom: 16px;
}

.section-card.equal-height {
  height: calc(100% - 16px);
  box-sizing: border-box;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
}

/* 空状态 */
.empty-tip {
  text-align: center;
  padding: 32px 0;
  color: #909399;
  font-size: 14px;
}

.empty-tip i {
  font-size: 32px;
  display: block;
  margin-bottom: 8px;
}

.empty-tip p {
  margin: 0 0 4px;
}

.link-text {
  color: #409eff;
  cursor: pointer;
}

.link-text:hover {
  text-decoration: underline;
}

/* 收益颜色 */
.text-positive { color: #f56c6c; }
.text-negative { color: #67c23a; }
.text-muted { color: #c0c4cc; }

/* 模块导航 */
.nav-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 12px;
}

.nav-card:hover {
  border-color: #c6dcff;
  background: #f5f8ff;
}

.nav-icon {
  font-size: 20px;
  color: #409eff;
  flex-shrink: 0;
}

.nav-info {
  display: flex;
  flex-direction: column;
}

.nav-label {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
}

.nav-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
</style>