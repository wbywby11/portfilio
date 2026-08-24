<template>
  <el-drawer
    :visible.sync="drawerVisible"
    :title="null"
    direction="rtl"
    size="65%"
    :destroy-on-close="true"
    :wrapper-closable="true"
    class="comparison-drawer"
  >
    <div class="drawer-header" slot="title">
      <span class="drawer-title">{{ strategyData ? strategyData.name : '策略详情' }}</span>
      <el-tag v-if="strategyData && strategyData.strategy && strategyData.strategy.template_code" size="small" type="info" style="margin-left: 10px;">
        {{ strategyData.strategy.template_code }}
      </el-tag>
    </div>
    <div class="drawer-body" v-if="strategyData">
      <single-strategy-result
        :strategy-name="strategyData.name"
        :result="strategyData.result || {}"
        :strategy="strategyData.strategy"
        :remark="strategyData.remark || ''"
        :record-id="strategyData.recordId"
        :model-id="strategyData.modelId"
        :unique-chart-id="'drawer_' + (strategyData.key || 'default')"
        :is-multi-strategy="true"
      ></single-strategy-result>
    </div>
  </el-drawer>
</template>

<script>
import SingleStrategyResult from './SingleStrategyResult.vue';

export default {
  name: 'ComparisonDrawer',
  components: {
    SingleStrategyResult
  },
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    /** { key, name, result, strategy, remark, recordId, modelId } */
    strategyData: {
      type: Object,
      default: null
    }
  },
  computed: {
    drawerVisible: {
      get() { return this.visible; },
      set(val) { this.$emit('update:visible', val); }
    }
  }
};
</script>

<style scoped>
.drawer-header {
  display: flex;
  align-items: center;
}
.drawer-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.drawer-body {
  padding: 0 20px 20px;
  overflow-y: auto;
}
</style>

<style>
.comparison-drawer .el-drawer__header {
  margin-bottom: 0;
  padding: 16px 20px;
  border-bottom: 1px solid #ebeef5;
}
.comparison-drawer .el-drawer__body {
  overflow-y: auto;
}
</style>
