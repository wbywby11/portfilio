<template>
  <el-card shadow="never" class="form-card">
    <div slot="header" class="card-header">
      <span>资产选择策略</span>
    </div>

    <el-form-item label="启用资产选择">
      <el-switch :value="form.enable_momentum_selection" @change="handleToggle"></el-switch>
      <el-tooltip content="启用后将从资产池中按所选选择器策略自动筛选排名前N的资产" placement="top">
        <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
      </el-tooltip>
    </el-form-item>

    <template v-if="form.enable_momentum_selection">
      <el-form-item label="选择器策略">
        <el-select
          :value="form.selector_code"
          placeholder="请选择选择器策略"
          @change="handleSelectorCodeChange"
          style="width: 100%;"
        >
          <el-option
            v-for="tpl in selectionTemplateList"
            :key="tpl.code"
            :label="tpl.name"
            :value="tpl.code"
          >
            <span style="float: left">{{ tpl.name }}</span>
            <span style="float: right; color: #8492a6; font-size: 13px">{{ tpl.description }}</span>
          </el-option>
        </el-select>
        <el-tooltip content="从策略库中选择资产选择策略，不同选择器有不同的筛选逻辑和参数" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-form-item>

      <!-- 选择器参数 -->
      <template v-if="selectedSelectorTemplate && (selectorNeedsAssetCount || selectorNeedsMinHistory || (selectedSelectorTemplate.parameters && selectedSelectorTemplate.parameters.length > 0))">
        <el-divider content-position="left">
          {{ selectedSelectorTemplate.name }} 参数
          <el-button v-if="selectedSelectorTemplate.parameters && selectedSelectorTemplate.parameters.length > 0" type="text" size="mini" @click="$emit('reset-selector-params')" style="margin-left: 8px;">重置默认</el-button>
        </el-divider>

        <!-- 选择资产数量 -->
        <el-form-item v-if="selectorNeedsAssetCount" label="选择数量">
          <el-input-number
            v-model="form.asset_selection_count"
            :min="1"
            :max="100"
            :step="1"
            controls-position="right"
            style="width: 200px;"
          ></el-input-number>
          <el-tooltip content="从候选池中选择排名前N的资产" placement="top">
            <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
          </el-tooltip>
          <span style="margin-left: 10px; color: #909399; font-size: 13px;">个（默认：8，范围：1-100）</span>
        </el-form-item>

        <!-- 最小历史天数 -->
        <el-form-item v-if="selectorNeedsMinHistory" label="最小历史">
          <el-input-number
            v-model="minHistoryValue"
            :min="30"
            :max="1000"
            :step="10"
            controls-position="right"
            style="width: 200px;"
          ></el-input-number>
          <el-tooltip content="资产进入候选池的最小交易日数" placement="top">
            <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
          </el-tooltip>
          <span style="margin-left: 10px; color: #909399; font-size: 13px;">天（默认：260，范围：30-1000）</span>
        </el-form-item>

        <!-- 动态参数（schema 驱动）：核心参数 -->
        <template v-if="visibleCoreSelectorParams.length">
          <param-field-renderer
            v-for="param in visibleCoreSelectorParams"
            :key="'sel_' + param.name"
            :param="param"
            :value="form.selector_parameters[param.name]"
            @input="updateSelectorParam(param.name, $event)"
          />
        </template>

        <!-- 高级参数（折叠） -->
        <el-collapse v-if="visibleAdvancedSelectorParams.length" v-model="advancedCollapse" class="advanced-params-collapse">
          <el-collapse-item name="advanced">
            <template slot="title">
              <span style="font-size: 13px; color: #606266;"><i class="el-icon-setting"></i> 高级参数</span>
            </template>
            <param-field-renderer
              v-for="param in visibleAdvancedSelectorParams"
              :key="'sel_adv_' + param.name"
              :param="param"
              :value="form.selector_parameters[param.name]"
              @input="updateSelectorParam(param.name, $event)"
            />
          </el-collapse-item>
        </el-collapse>
      </template>
    </template>

    <!-- 复合分配器的内部选择器参数：multi_signal/internal_selectors 模板的信号参数
         独立于「启用资产选择」开关（复合信号由模板 composition 声明，非用户可选选择器） -->
    <div v-for="extraTpl in additionalInternalSelectorTemplates" :key="'extra_' + extraTpl.code">
      <el-divider content-position="left">
        {{ extraTpl.name }} 参数
      </el-divider>
      <param-field-renderer
        v-for="param in extraTpl.parameters"
        :key="'extra_sel_' + param.name"
        :param="param"
        :value="form.selector_parameters[param.name]"
        @input="updateSelectorParam(param.name, $event)"
      />
    </div>
  </el-card>
</template>

<script>
import ParamFieldRenderer from './ParamFieldRenderer.vue';

export default {
  name: 'StrategySelectionCard',
  components: { ParamFieldRenderer },
  props: {
    form: { type: Object, required: true },
    selectionTemplateList: { type: Array, default: () => [] },
    templateList: { type: Array, default: () => [] },
    currentTemplate: { type: Object, default: null }
  },
  data() {
    return {
      advancedCollapse: []
    };
  },
  computed: {
    selectedSelectorTemplate() {
      if (!this.form.selector_code) return null;
      return this.templateList.find(t => t.code === this.form.selector_code);
    },
    selectorType() {
      if (!this.form.selector_code) return '';
      return this.form.selector_code.startsWith('sel_')
        ? this.form.selector_code.slice(4)
        : this.form.selector_code;
    },
    selectorNeedsAssetCount() {
      return ['sharpe', 'etf_rotation', 'cross_sectional_momentum'].includes(this.selectorType);
    },
    selectorNeedsMinHistory() {
      return ['sharpe', 'momentum_reversal'].includes(this.selectorType);
    },
    /** 最小历史数据：优先读 selector_parameters，编辑时同步两处（后端以 selector_parameters 为准） */
    minHistoryValue: {
      get() {
        const sp = this.form.selector_parameters || {};
        return sp.min_history_days !== undefined && sp.min_history_days !== null
          ? sp.min_history_days : this.form.min_history_days;
      },
      set(v) {
        this.$set(this.form, 'min_history_days', v);
        if (this.form.selector_parameters) {
          this.$set(this.form.selector_parameters, 'min_history_days', v);
        }
      }
    },
    /** 条件可见的选择器参数（min_history_days 由顶层输入框接管，不重复渲染） */
    visibleSelectorParams() {
      if (!this.selectedSelectorTemplate || !this.selectedSelectorTemplate.parameters) return [];
      return this.selectedSelectorTemplate.parameters.filter(param => {
        if (param.name === 'min_history_days' && this.selectorNeedsMinHistory) return false;
        if (!param.condition) return true;
        const currentVal = this.form.selector_parameters[param.condition.field];
        return currentVal === param.condition.value;
      });
    },
    visibleCoreSelectorParams() {
      return this.visibleSelectorParams.filter(p => (p.group || 'core') !== 'advanced');
    },
    visibleAdvancedSelectorParams() {
      return this.visibleSelectorParams.filter(p => p.group === 'advanced');
    },
    additionalInternalSelectorTemplates() {
      const tpl = this.currentTemplate;
      if (!tpl || !tpl.composition) return [];
      let internalList = [];
      if (tpl.composition.multi_signal && tpl.composition.multi_signal.length > 0) {
        internalList = tpl.composition.multi_signal.map(s => s.selector);
      } else if (tpl.composition.internal_selectors) {
        internalList = tpl.composition.internal_selectors;
      } else {
        return [];
      }
      return internalList.map(code => {
        return this.templateList.find(t => t.code === 'sel_' + code);
      }).filter(Boolean);
    }
  },
  methods: {
    handleToggle(value) {
      this.form.enable_momentum_selection = value;
      if (!value) {
        this.form.selector_code = '';
        this.form.selector_type = '';
        // 保留复合模板 composition 声明的内部选择器参数（与开关无关，关掉不能丢）
        const internalKeys = new Set();
        this.additionalInternalSelectorTemplates.forEach(tpl => {
          (tpl.parameters || []).forEach(p => internalKeys.add(p.name));
        });
        const kept = {};
        Object.entries(this.form.selector_parameters || {}).forEach(([k, v]) => {
          if (internalKeys.has(k)) kept[k] = v;
        });
        this.form.selector_parameters = kept;
        this.form.asset_selection_count = 1;
      }
    },
    handleSelectorCodeChange(code) {
      this.$emit('selector-code-change', code);
    },
    updateSelectorParam(name, value) {
      this.$set(this.form.selector_parameters, name, value);
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
