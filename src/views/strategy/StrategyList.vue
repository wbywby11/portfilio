<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">我的策略</h2>
      <el-button type="primary" icon="el-icon-plus" @click="$router.push('/strategy/develop')">
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
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';

export default {
  name: 'StrategyList',
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
    viewDetail(row) {
      this.$router.push(`/strategy/detail/${row.id}`);
    },
    createPortfolio(row) {
      this.$router.push({
        path: '/portfolio/create',
        query: { strategyId: row.id }
      });
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
