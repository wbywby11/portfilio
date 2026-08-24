<template>
  <el-card shadow="never" class="form-card" v-if="currentTemplate">
    <div slot="header" class="card-header">
      <span>{{ isSharpeRiskBudget ? '权重参数' : '模型参数' }}</span>
      <el-button type="text" size="small" @click="$emit('reset-params')">重置为默认值</el-button>
    </div>

    <!-- 核心参数 -->
    <param-field-renderer
      v-for="param in visibleCoreParams"
      :key="param.name"
      :param="param"
      :value="form.parameters[param.name]"
      :asset-options="assetOptions"
      :show-default-hint="false"
      @input="updateParam(param.name, $event)"
      @change="handleParamChange(param)"
    />

    <!-- 高级参数（折叠） -->
    <el-collapse v-if="visibleAdvancedParams.length > 0" v-model="advancedCollapse" class="advanced-params-collapse">
      <el-collapse-item name="advanced">
        <template slot="title">
          <span style="font-size: 13px; color: #606266;"><i class="el-icon-setting"></i> 高级参数</span>
        </template>
        <param-field-renderer
          v-for="param in visibleAdvancedParams"
          :key="'adv_' + param.name"
          :param="param"
          :value="form.parameters[param.name]"
          :asset-options="assetOptions"
          :show-default-hint="false"
          @input="updateParam(param.name, $event)"
          @change="handleParamChange(param)"
        />
      </el-collapse-item>
    </el-collapse>
  </el-card>
</template>

<script>
import ParamFieldRenderer from './ParamFieldRenderer.vue';
import {
  isRiskBudgetTargetVolHiddenTemplateParameter,
  isSharpeRiskBudgetHiddenSchemaParameter
} from '@/utils/strategyTemplateFlags';

export default {
  name: 'StrategyAllocatorParamsCard',
  components: { ParamFieldRenderer },
  props: {
    form: { type: Object, required: true },
    currentTemplate: { type: Object, default: null },
    assetOptions: { type: Array, default: () => [] },
    isManualAllocation: { type: Boolean, default: false },
    isSharpeRiskBudget: { type: Boolean, default: false },
    isRiskBudgetTargetVol: { type: Boolean, default: false }
  },
  data() {
    return {
      advancedCollapse: []
    };
  },
  computed: {
    coreParams() {
      if (!this.currentTemplate || !this.currentTemplate.parameters) return [];
      return this.currentTemplate.parameters.filter(p => (p.group || 'core') !== 'advanced');
    },
    advancedParams() {
      if (!this.currentTemplate || !this.currentTemplate.parameters) return [];
      return this.currentTemplate.parameters.filter(p => p.group === 'advanced');
    },
    visibleCoreParams() {
      return this.coreParams.filter(p => this.isParamShown(p));
    },
    visibleAdvancedParams() {
      return this.advancedParams.filter(p => this.isParamShown(p));
    }
  },
  methods: {
    isParamShown(param) {
      if (param.hidden) return false;
      // condition 可见性
      if (param.condition) {
        const currentVal = this.form.parameters[param.condition.field];
        const condMet = currentVal === param.condition.value || String(currentVal) === String(param.condition.value);
        if (!condMet) return false;
      }
      // 主观策略隐藏 manual_weights（由独立面板管理）
      if (this.isManualAllocation && param.name === 'manual_weights') return false;
      // 固定隐藏字段
      if (param.name === 'risk_budget_both' || param.name === 'risk_budget_single') return false;
      // 模板特定隐藏参数
      if (this.isRiskBudgetTargetVol && isRiskBudgetTargetVolHiddenTemplateParameter(param.name)) return false;
      if (this.isSharpeRiskBudget && isSharpeRiskBudgetHiddenSchemaParameter(param.name)) return false;
      return true;
    },
    updateParam(name, value) {
      this.$set(this.form.parameters, name, value);
    },
    handleParamChange(param) {
      this.$emit('param-change', param);
    }
  }
};
</script>

<style scoped>
.form-card {
  margin-bottom: 20px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}
.advanced-params-collapse {
  border: none;
  margin-top: 8px;
}
.advanced-params-collapse >>> .el-collapse-item__header {
  height: 36px;
  line-height: 36px;
  background: transparent;
  border-bottom: none;
}
.advanced-params-collapse >>> .el-collapse-item__wrap {
  border-bottom: none;
}
.advanced-params-collapse >>> .el-collapse-item__content {
  padding-bottom: 8px;
}
</style>
