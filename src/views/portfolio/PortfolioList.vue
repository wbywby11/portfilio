<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">组合列表</h2>
      <el-button type="primary" icon="el-icon-plus" @click="$router.push('/portfolio/create')">
        创建组合
      </el-button>
    </div>

    <div class="page-content">
      <el-table :data="portfolioList" style="width: 100%" v-loading="loading">
        <el-table-column prop="name" label="组合名称" min-width="150"></el-table-column>
        <el-table-column prop="totalValue" label="当前市值" width="150" align="right">
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
            <el-tag :type="getStatusType(scope.row.status)" size="small">
              {{ getStatusLabel(scope.row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="createTime" label="创建时间" width="180">
          <template slot-scope="scope">
            {{ formatDate(scope.row.createTime) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="small" @click="viewDetail(scope.row.id)">详情</el-button>
            <el-button type="text" size="small" @click="viewPerformance(scope.row.id)">业绩</el-button>
            <el-button type="text" size="small" @click="viewBenchmark(scope.row.id)">对比</el-button>
            <el-button type="text" size="small" @click="deletePortfolio(scope.row)" style="color: #f56c6c;">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="portfolioList.length === 0" description="暂无组合数据，点击上方按钮创建第一个组合"></el-empty>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';

export default {
  name: 'PortfolioList',
  data() {
    return {
      loading: false
    };
  },
  computed: {
    ...mapState('portfolio', ['portfolioList'])
  },
  created() {
    this.fetchData();
  },
  methods: {
    async fetchData() {
      this.loading = true;
      try {
        await this.$store.dispatch('portfolio/fetchPortfolioList');
      } finally {
        this.loading = false;
      }
    },
    formatNumber(num) {
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num || 0);
    },
    formatPercent(num) {
      return ((num || 0) * 100).toFixed(2) + '%';
    },
    formatDate(date) {
      return dayjs(date).format('YYYY-MM-DD HH:mm:ss');
    },
    getReturnClass(ret) {
      if (ret > 0) return 'number-positive';
      if (ret < 0) return 'number-negative';
      return 'number-neutral';
    },
    getStatusType(status) {
      const map = { active: 'success', paused: 'warning', archived: 'info' };
      return map[status] || 'info';
    },
    getStatusLabel(status) {
      const map = { active: '运行中', paused: '已暂停', archived: '已归档' };
      return map[status] || status;
    },
    viewDetail(id) {
      this.$router.push(`/portfolio/detail/${id}`);
    },
    viewPerformance(id) {
      this.$router.push(`/portfolio/performance/${id}`);
    },
    viewBenchmark(id) {
      this.$router.push(`/portfolio/benchmark/${id}`);
    },
    deletePortfolio(row) {
      this.$confirm(`确定要删除组合 "${row.name}" 吗?`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        await this.$store.dispatch('portfolio/deletePortfolio', row.id);
        this.$message.success('删除成功');
        this.fetchData();
      }).catch(() => {});
    }
  }
};
</script>
