<template>
  <el-form-item :label="param.label || param.name">
    <!-- number -->
    <template v-if="param.param_type === 'number'">
      <el-input-number
        :value="value"
        @input="$emit('input', $event)"
        :min="effectiveMin"
        :max="effectiveMax"
        :step="param.step || 0.01"
        :precision="precision"
        style="width: 200px;"
      ></el-input-number>
      <span v-if="showDefaultHint" class="param-default-hint">
        默认：{{ defaultDisplay }}
      </span>
    </template>

    <!-- slider -->
    <div v-else-if="param.param_type === 'slider'" style="display: flex; align-items: center;">
      <el-slider
        :value="value"
        @input="$emit('input', $event)"
        @change="$emit('change', $event)"
        :min="effectiveMin || 0"
        :max="effectiveMax || 100"
        :step="param.step || 1"
        style="width: 200px; margin-right: 15px;"
        show-input
      ></el-slider>
    </div>

    <!-- select -->
    <el-select
      v-else-if="param.param_type === 'select'"
      :value="value"
      @input="$emit('input', $event)"
      @change="$emit('change', $event)"
      placeholder="请选择"
      style="width: 200px;"
    >
      <el-option
        v-for="option in paramOptions"
        :key="getOptionValue(option)"
        :label="getOptionLabel(option)"
        :value="getOptionValue(option)"
      ></el-option>
    </el-select>

    <!-- boolean -->
    <el-switch
      v-else-if="param.param_type === 'boolean'"
      :value="value"
      @input="$emit('input', $event)"
    ></el-switch>

    <!-- string -->
    <el-input
      v-else-if="param.param_type === 'string'"
      :value="value"
      @input="$emit('input', $event)"
      placeholder="请输入"
      style="width: 300px;"
    ></el-input>

    <!-- dict / max_weight_dict -->
    <key-value-editor
      v-else-if="param.param_type === 'dict' || param.param_type === 'max_weight_dict'"
      :value="value"
      @input="$emit('input', $event)"
      :title="param.param_type === 'max_weight_dict' ? '' : (param.label || param.name)"
      :key-mode="param.param_type === 'max_weight_dict' ? 'asset' : 'text'"
      value-type="number"
      :value-min="0"
      :value-max="1"
      :value-step="0.05"
      :value-precision="2"
      :asset-options="param.param_type === 'max_weight_dict' ? assetOptions : []"
      :compact="param.param_type === 'max_weight_dict'"
    ></key-value-editor>

    <!-- fallback: number -->
    <el-input-number
      v-else
      :value="value"
      @input="$emit('input', $event)"
      :min="effectiveMin"
      :max="effectiveMax"
      :step="param.step || 0.01"
      :precision="precision"
      style="width: 200px;"
    ></el-input-number>

    <!-- tooltip -->
    <el-tooltip v-if="param.description" :content="param.description" placement="top">
      <i class="el-icon-question param-tooltip-icon"></i>
    </el-tooltip>
  </el-form-item>
</template>

<script>
import KeyValueEditor from '@/components/KeyValueEditor.vue';

export default {
  name: 'ParamFieldRenderer',
  components: { KeyValueEditor },
  props: {
    /** 参数 schema 定义 {name, label, param_type, min_value, max_value, step, options, description, default, default_value} */
    param: {
      type: Object,
      required: true
    },
    /** 当前值（支持 v-model） */
    value: {
      default: undefined
    },
    /** 资产选项列表（供 max_weight_dict 使用） */
    assetOptions: {
      type: Array,
      default: () => []
    },
    /** 是否显示默认值提示（number类型） */
    showDefaultHint: {
      type: Boolean,
      default: true
    }
  },
  computed: {
    effectiveMin() {
      return this.param.min_value !== null && this.param.min_value !== undefined
        ? this.param.min_value : undefined;
    },
    effectiveMax() {
      return this.param.max_value !== null && this.param.max_value !== undefined
        ? this.param.max_value : undefined;
    },
    /** 根据 step 决定小数精度：整数 step 显示 0 位，小数 step 显示 4 位 */
    precision() {
      const step = this.param.step;
      if (step !== null && step !== undefined && Number.isInteger(step) && step >= 1) {
        return 0;
      }
      return 4;
    },
    /** 默认值（兼容 default / default_value） */
    defaultDisplay() {
      const d = this.param.default !== null && this.param.default !== undefined
        ? this.param.default
        : (this.param.default_value !== null && this.param.default_value !== undefined
          ? this.param.default_value : null);
      return d;
    },
    /** 解析 options 列表 */
    paramOptions() {
      if (!this.param.options) return [];
      if (Array.isArray(this.param.options)) return this.param.options;
      if (typeof this.param.options === 'string') {
        return this.param.options.split(',').map(o => o.trim()).filter(o => o);
      }
      return [];
    }
  },
  methods: {
    getOptionValue(option) {
      if (Array.isArray(option)) return option[0];
      return option;
    },
    getOptionLabel(option) {
      if (Array.isArray(option)) return option[1] || option[0];
      return option;
    }
  }
};
</script>

<style scoped>
.param-default-hint {
  margin-left: 10px;
  color: #909399;
  font-size: 13px;
}
.param-tooltip-icon {
  color: #909399;
  margin-left: 4px;
  cursor: help;
}
</style>
