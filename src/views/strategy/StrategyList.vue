<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">我的策略</h2>
      <el-button type="primary" icon="el-icon-plus" @click="handleCreate">
        新建策略
      </el-button>
    </div>

    <div class="page-content">
      <el-table :data="strategyList" style="width: 100%">
        <el-table-column prop="name" label="策略名称" min-width="150"></el-table-column>
        <el-table-column prop="templateId" label="算法模型" width="150">
          <template slot-scope="scope">
            {{ getTemplateName(scope.row.templateId) }}
          </template>
        </el-table-column>
        <el-table-column label="资产数量" width="100" align="center">
          <template slot-scope="scope">
            {{ scope.row.assets ? scope.row.assets.length : 0 }}
          </template>
        </el-table-column>
        <el-table-column label="预期收益" width="120" align="right">
          <template slot-scope="scope">
            {{ scope.row.result ? formatPercent(scope.row.result.expectedReturn) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="预期风险" width="120" align="right">
          <template slot-scope="scope">
            {{ scope.row.result ? formatPercent(scope.row.result.expectedRisk) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="creator" label="创建人" width="100"></el-table-column>
        <el-table-column prop="createTime" label="创建时间" width="180">
          <template slot-scope="scope">
            {{ formatDate(scope.row.createTime) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="small" @click="viewDetail(scope.row)">查看</el-button>
            <el-button type="text" size="small" @click="createPortfolio(scope.row)">创建组合</el-button>
            <el-button type="text" size="small" @click="deleteStrategy(scope.row)" style="color: #f56c6c;">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="strategyList.length === 0" description="暂无策略数据"></el-empty>
    </div>

    <!-- 弹窗部分 -->
    <el-dialog title="策略开发" :visible.sync="strategyDevelopVisible" width="1200px" append-to-body top="5vh">
      <strategy-develop v-if="strategyDevelopVisible" is-dialog @success="handleDevelopSuccess" @close="strategyDevelopVisible = false" />
    </el-dialog>

    <el-dialog title="策略详情" :visible.sync="strategyDetailVisible" width="900px" append-to-body>
      <strategy-detail v-if="strategyDetailVisible" is-dialog :id="currentStrategyId" />
    </el-dialog>

    <el-dialog title="创建组合" :visible.sync="portfolioCreateVisible" width="1000px" append-to-body>
      <portfolio-create v-if="portfolioCreateVisible" is-dialog :strategy-id="currentStrategyId" @success="portfolioCreateVisible = false" @close="portfolioCreateVisible = false" />
    </el-dialog>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';
import StrategyDevelop from './StrategyDevelop.vue';
import StrategyDetail from './StrategyDetail.vue';
import PortfolioCreate from '../portfolio/PortfolioCreate.vue';

export default {
  name: 'StrategyList',
  components: {
    StrategyDevelop,
    StrategyDetail,
    PortfolioCreate
  },
  data() {
    return {
      strategyDevelopVisible: false,
      strategyDetailVisible: false,
      portfolioCreateVisible: false,
      currentStrategyId: ''
    };
  },
  computed: {
    ...mapState('strategy', ['strategyList', 'templateList'])
  },
  created() {
    this.$store.dispatch('strategy/fetchStrategyList');
  },
  methods: {
    getTemplateName(id) {
      const template = this.templateList.find(t => t.id === id);
      return template ? template.name : id;
    },
    formatPercent(num) {
      return (num * 100).toFixed(2) + '%';
    },
    formatDate(date) {
      return dayjs(date).format('YYYY-MM-DD HH:mm:ss');
    },
    handleCreate() {
      this.strategyDevelopVisible = true;
    },
    viewDetail(row) {
      this.currentStrategyId = row.id;
      this.strategyDetailVisible = true;
    },
    createPortfolio(row) {
      this.currentStrategyId = row.id;
      this.portfolioCreateVisible = true;
    },
    handleDevelopSuccess() {
      this.strategyDevelopVisible = false;
      this.$store.dispatch('strategy/fetchStrategyList');
    },
    deleteStrategy(row) {
      this.$confirm(`确定要删除策略 "${row.name}" 吗?`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        await this.$store.dispatch('strategy/deleteStrategy', row.id);
        this.$message.success('删除成功');
      }).catch(() => {});
    }
  }
};
</script>
