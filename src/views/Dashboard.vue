<template>
  <div class="dashboard">
    <div class="welcome-card">
      <div class="welcome-content">
        <h2>欢迎回来，{{ userName }}！</h2>
        <p>今天是 {{ currentDate }}，祝您工作顺利</p>
      </div>
    </div>

    <el-row :gutter="20" class="stats-row">
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: #409eff;">
            <i class="el-icon-s-data"></i>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ portfolioCount }}</div>
            <div class="stat-label">我的组合</div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: #67c23a;">
            <i class="el-icon-data-analysis"></i>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ strategyCount }}</div>
            <div class="stat-label">我的策略</div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: #e6a23c;">
            <i class="el-icon-coin"></i>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ assetCount }}</div>
            <div class="stat-label">可用资产</div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: #f56c6c;">
            <i class="el-icon-s-marketing"></i>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ formatPercent(avgReturn) }}</div>
            <div class="stat-label">平均收益</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <el-col :span="12">
        <div class="info-card">
          <div class="info-card-title">快捷入口</div>
          <div class="quick-links">
            <el-button type="primary" icon="el-icon-plus" @click="handleCreatePortfolio">
              创建组合
            </el-button>
            <el-button type="success" icon="el-icon-data-analysis" @click="handleDevelopStrategy">
              策略开发
            </el-button>
            <el-button type="warning" icon="el-icon-coin" @click="handleAddAsset">
              新增资产
            </el-button>
            <el-button type="info" icon="el-icon-s-data" @click="$message.info('组合对比功能开发中')">
              组合对比
            </el-button>
          </div>
        </div>
      </el-col>

      <el-col :span="12">
        <div class="info-card">
          <div class="info-card-title">系统公告</div>
          <div class="notice-list">
            <div class="notice-item">
              <i class="el-icon-info"></i>
              <span>系统已更新至V1.0版本，新增多组合对比功能</span>
              <span class="notice-date">2024-01-20</span>
            </div>
            <div class="notice-item">
              <i class="el-icon-info"></i>
              <span>新增Black-Litterman资产配置模型</span>
              <span class="notice-date">2024-01-15</span>
            </div>
            <div class="notice-item">
              <i class="el-icon-info"></i>
              <span>业绩归因分析功能正式上线</span>
              <span class="notice-date">2024-01-10</span>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="info-card">
      <div class="info-card-title">最近更新的组合</div>
      <el-table :data="recentPortfolios" style="width: 100%">
        <el-table-column prop="name" label="组合名称" min-width="150"></el-table-column>
        <el-table-column prop="totalValue" label="当前市值" width="120" align="right">
          <template slot-scope="scope">
            {{ formatNumber(scope.row.totalValue) }}
          </template>
        </el-table-column>
        <el-table-column prop="totalReturn" label="累计收益率" width="120" align="right">
          <template slot-scope="scope">
            <span :class="getReturnClass(scope.row.totalReturn)">
              {{ formatPercent(scope.row.totalReturn) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template slot-scope="scope">
            <el-tag :type="scope.row.status === 'active' ? 'success' : 'info'" size="small">
              {{ scope.row.status === 'active' ? '运行中' : '已暂停' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="updateTime" label="更新时间" width="180"></el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="small" @click="handleViewPortfolio(scope.row.id)">查看</el-button>
            <el-button type="text" size="small" @click="handleAnalyzePortfolio(scope.row.id)">
              分析
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 弹窗部分 -->
    <el-dialog title="新增资产" :visible.sync="assetFormVisible" width="900px" append-to-body>
      <asset-form v-if="assetFormVisible" is-dialog @success="assetFormVisible = false; loadData()" @close="assetFormVisible = false" />
    </el-dialog>

    <el-dialog title="创建组合" :visible.sync="portfolioCreateVisible" width="1000px" append-to-body>
      <portfolio-create v-if="portfolioCreateVisible" is-dialog @success="portfolioCreateVisible = false; loadData()" @close="portfolioCreateVisible = false" />
    </el-dialog>

    <el-dialog title="策略开发" :visible.sync="strategyDevelopVisible" width="1200px" append-to-body top="5vh">
      <strategy-develop v-if="strategyDevelopVisible" is-dialog @success="strategyDevelopVisible = false; loadData()" @close="strategyDevelopVisible = false" />
    </el-dialog>

    <el-dialog title="组合详情" :visible.sync="portfolioDetailVisible" width="1200px" append-to-body top="5vh">
      <portfolio-detail v-if="portfolioDetailVisible" is-dialog :id="currentPortfolioId" />
    </el-dialog>

    <el-dialog title="业绩分析" :visible.sync="performanceVisible" width="1200px" append-to-body top="5vh">
      <performance v-if="performanceVisible" is-dialog :id="currentPortfolioId" />
    </el-dialog>
  </div>
</template>

<script>
import { mapGetters, mapState } from 'vuex';
import dayjs from 'dayjs';
import AssetForm from './asset/AssetForm.vue';
import PortfolioCreate from './portfolio/PortfolioCreate.vue';
import StrategyDevelop from './strategy/StrategyDevelop.vue';
import PortfolioDetail from './portfolio/PortfolioDetail.vue';
import Performance from './portfolio/Performance.vue';

export default {
  name: 'Dashboard',
  components: {
    AssetForm,
    PortfolioCreate,
    StrategyDevelop,
    PortfolioDetail,
    Performance
  },
  data() {
    return {
      currentDate: dayjs().format('YYYY年MM月DD日'),
      recentPortfolios: [],
      assetFormVisible: false,
      portfolioCreateVisible: false,
      strategyDevelopVisible: false,
      portfolioDetailVisible: false,
      performanceVisible: false,
      currentPortfolioId: ''
    };
  },
  computed: {
    ...mapGetters('user', ['userName']),
    ...mapState('portfolio', ['portfolioList']),
    // strategy 模块的 state 名为 strategyModelList，仅有 getter 别名 strategyList，
    // 使用 mapState('strategy', ['strategyList']) 会拿到 undefined 并在 .length 时崩溃。
    ...mapGetters('strategy', ['strategyList']),
    ...mapState('asset', ['assetList']),
    portfolioCount() {
      return (this.portfolioList || []).length;
    },
    strategyCount() {
      return (this.strategyList || []).length;
    },
    assetCount() {
      return (this.assetList || []).length;
    },
    avgReturn() {
      const list = this.portfolioList || [];
      if (list.length === 0) return 0;
      const sum = list.reduce((acc, p) => acc + (p.totalReturn || 0), 0);
      return sum / list.length;
    }
  },
  created() {
    this.loadData();
  },
  methods: {
    async loadData() {
      await this.$store.dispatch('portfolio/fetchPortfolioList');
      // strategy 模块的实际 action 名为 fetchStrategyModelList（无 fetchStrategyList）
      await this.$store.dispatch('strategy/fetchStrategyModelList');
      await this.$store.dispatch('asset/fetchAssetList');
      
      this.recentPortfolios = this.portfolioList.slice(0, 5).map(p => ({
        ...p,
        updateTime: dayjs(p.createTime).format('YYYY-MM-DD HH:mm:ss')
      }));
    },
    formatNumber(num) {
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num || 0);
    },
    formatPercent(num) {
      return (num * 100).toFixed(2) + '%';
    },
    getReturnClass(ret) {
      if (ret > 0) return 'number-positive';
      if (ret < 0) return 'number-negative';
      return 'number-neutral';
    },
    handleCreatePortfolio() {
      this.portfolioCreateVisible = true;
    },
    handleDevelopStrategy() {
      this.strategyDevelopVisible = true;
    },
    handleAddAsset() {
      this.assetFormVisible = true;
    },
    handleViewPortfolio(id) {
      this.currentPortfolioId = id;
      this.portfolioDetailVisible = true;
    },
    handleAnalyzePortfolio(id) {
      this.currentPortfolioId = id;
      this.performanceVisible = true;
    }
  }
};
</script>

<style scoped>
.dashboard {
  padding: 0;
}

.welcome-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 4px;
  padding: 30px;
  margin-bottom: 20px;
  color: #fff;
}

.welcome-content h2 {
  font-size: 24px;
  margin-bottom: 10px;
}

.welcome-content p {
  font-size: 14px;
  opacity: 0.9;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  background: #fff;
  border-radius: 4px;
  padding: 20px;
  display: flex;
  align-items: center;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 15px;
}

.stat-icon i {
  font-size: 28px;
  color: #fff;
}

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
  line-height: 1.2;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-top: 5px;
}

.quick-links {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.quick-links .el-button {
  flex: 1;
  min-width: 120px;
}

.notice-list {
  max-height: 200px;
  overflow-y: auto;
}

.notice-item {
  display: flex;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
}

.notice-item:last-child {
  border-bottom: none;
}

.notice-item i {
  color: #409eff;
  margin-right: 10px;
  font-size: 16px;
}

.notice-item span:nth-child(2) {
  flex: 1;
  font-size: 14px;
  color: #606266;
}

.notice-date {
  font-size: 12px;
  color: #909399;
}
</style>
