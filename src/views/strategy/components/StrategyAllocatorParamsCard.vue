<template>
  <el-card shadow="never" class="form-card" v-if="currentTemplate">
    <div slot="header" class="card-header">
      <span>{{ isSharpeRiskBudget ? '权重参数' : '模型参数' }}</span>
      <el-dropdown trigger="click" size="small" @command="handlePresetCommand">
        <el-button type="text" size="small" :loading="presetLoading">
          重置为默认值<i class="el-icon-arrow-down el-icon--right"></i>
        </el-button>
        <el-dropdown-menu slot="dropdown">
          <el-dropdown-item command="__template_default__" icon="el-icon-refresh-left">
            模板默认值
          </el-dropdown-item>
          <template v-for="group in presetGroups">
            <el-dropdown-item
              :key="'h_' + group.tag"
              divided
              disabled
              class="preset-group-title"
            >{{ group.tag }} 版本</el-dropdown-item>
            <el-dropdown-item
              v-for="item in group.items"
              :key="item.code"
              :command="item.code"
            >{{ item.name }}</el-dropdown-item>
          </template>
        </el-dropdown-menu>
      </el-dropdown>
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
    isRiskBudgetTargetVol: { type: Boolean, default: false },
    // 当前模板可用的原型预设（摘要），按 version_tag 分组展示
    presets: { type: Array, default: () => [] },
    presetLoading: { type: Boolean, default: false }
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
    },
    presetGroups() {
      // 按 version_tag 串组，保持预设声明顺序（后端已按版本排好）
      const groups = [];
      const index = {};
      (this.presets || []).forEach(item => {
        const tag = item.version_tag || '其他';
        if (index[tag] === undefined) {
          index[tag] = groups.length;
          groups.push({ tag, items: [] });
        }
        groups[index[tag]].items.push(item);
      });
      return groups;
    }
  },
  methods: {
    handlePresetCommand(command) {
      if (command === '__template_default__') {
        this.$emit('reset-params');
        return;
      }
      this.$emit('apply-preset', command);
    },
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
.preset-group-title {
  font-size: 12px;
  color: #909399;
  cursor: default;
}
</style>
