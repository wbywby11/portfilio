<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">模拟交易</h2>
      <p class="page-desc">选择模型驱动的组合，进入模拟交易面板进行逐日推进和跟踪评估</p>
    </div>

    <div class="page-content">
      <el-table :data="portfolios" style="width: 100%" v-loading="loading" @row-click="handleRowClick">
        <el-table-column prop="name" label="组合名称" min-width="160">
          <template slot-scope="scope">
            <span style="color: #409EFF; cursor: pointer;">{{ scope.row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="portfolio_type" label="类型" width="100">
          <template slot-scope="scope">
            <el-tag :type="scope.row.portfolio_type === '模型驱动' ? 'success' : 'info'" size="small">
              {{ scope.row.portfolio_type || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="latest_unit_value" label="最新净值" width="110" align="right">
          <template slot-scope="scope">
            {{ scope.row.latest_unit_value ? scope.row.latest_unit_value.toFixed(4) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="total_return" label="累计收益率" width="120" align="right">
          <template slot-scope="scope">
            <span :style="{ color: (scope.row.total_return || 0) >= 0 ? '#67c23a' : '#f56c6c' }">
              {{ scope.row.total_return ? (scope.row.total_return * 100).toFixed(2) + '%' : '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="inception_date" label="建仓日期" width="120">
          <template slot-scope="scope">
            {{ formatDate(scope.row.inception_date) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template slot-scope="scope">
            <el-button
              type="primary" size="small" plain
              @click.stop="enterSimTrade(scope.row)"
              :disabled="scope.row.portfolio_type !== '模型驱动'"
            >
              进入模拟交易
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && portfolios.length === 0" description="暂无模型驱动组合，请先从策略模型创建组合"></el-empty>
    </div>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import * as portfolioApi from '@/api/portfolio';

export default {
  name: 'SimTradeSelector',
  data() {
    return {
      loading: false,
      portfolios: [],
    };
  },
  created() {
    this.fetchData();
  },
  methods: {
    async fetchData() {
      this.loading = true;
      try {
        const res = await portfolioApi.getPortfolioList();
        const list = res.data || [];
        // 优先展示模型驱动的组合
        this.portfolios = list.sort((a, b) => {
          if (a.portfolio_type === '模型驱动' && b.portfolio_type !== '模型驱动') return -1;
          if (a.portfolio_type !== '模型驱动' && b.portfolio_type === '模型驱动') return 1;
          return 0;
        });
      } catch (e) {
        this.$message.error('加载组合列表失败: ' + (e.message || e));
      } finally {
        this.loading = false;
      }
    },
    handleRowClick(row) {
      this.enterSimTrade(row);
    },
    enterSimTrade(row) {
      if (row.portfolio_type !== '模型驱动') {
        this.$message.warning('仅模型驱动组合支持模拟交易');
        return;
      }
      this.$router.push({ name: 'SimTradeDashboard', params: { id: row.id } });
    },
    formatDate(d) {
      return d ? dayjs(d).format('YYYY-MM-DD') : '-';
    },
  },
};
</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.page-desc { margin: 4px 0 0; color: #909399; font-size: 13px; }
</style>
