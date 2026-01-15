<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">策略详情</h2>
      <el-button @click="$router.back()">返回</el-button>
    </div>

    <div class="page-content">
      <el-descriptions title="基本信息" :column="2" border>
        <el-descriptions-item label="策略名称">{{ strategy.name }}</el-descriptions-item>
        <el-descriptions-item label="算法模型">{{ getTemplateName(strategy.templateId) }}</el-descriptions-item>
        <el-descriptions-item label="创建人">{{ strategy.creator }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(strategy.createTime) }}</el-descriptions-item>
      </el-descriptions>

      <el-divider></el-divider>

      <h3>模型参数</h3>
      <el-table :data="parameterData" style="width: 100%; margin-top: 10px;" size="small">
        <el-table-column prop="name" label="参数名称" width="200"></el-table-column>
        <el-table-column prop="value" label="参数值"></el-table-column>
      </el-table>

      <el-divider></el-divider>

      <h3>资产配置</h3>
      <el-table :data="strategy.assets" style="width: 100%; margin-top: 10px;" size="small">
        <el-table-column prop="code" label="资产代码" width="120"></el-table-column>
        <el-table-column prop="name" label="资产名称" width="150"></el-table-column>
        <el-table-column label="权重" width="150">
          <template slot-scope="scope">
            {{ strategy.result && strategy.result.weights ? formatPercent(strategy.result.weights[scope.row.code]) : '-' }}
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';

export default {
  name: 'StrategyDetail',
  data() {
    return {
      strategy: {}
    };
  },
  computed: {
    ...mapState('strategy', ['templateList']),
    parameterData() {
      if (!this.strategy.parameters) return [];
      return Object.keys(this.strategy.parameters).map(key => ({
        name: key,
        value: this.strategy.parameters[key]
      }));
    }
  },
  created() {
    this.loadData();
  },
  methods: {
    loadData() {
      const id = this.$route.params.id;
      this.strategy = this.$store.getters['strategy/getStrategyById'](id) || {};
    },
    getTemplateName(id) {
      const template = this.templateList.find(t => t.id === id);
      return template ? template.name : id;
    },
    formatDate(date) {
      return dayjs(date).format('YYYY-MM-DD HH:mm:ss');
    },
    formatPercent(num) {
      return (parseFloat(num) * 100).toFixed(2) + '%';
    }
  }
};
</script>

<style scoped>
h3 {
  margin: 20px 0 10px;
  font-size: 16px;
  font-weight: 600;
}
</style>
