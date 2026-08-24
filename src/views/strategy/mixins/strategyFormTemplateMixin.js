/**
 * 策略表单 - 模板切换与参数重置 Mixin
 * 包含：模板变更三层联动、参数重置、主观策略固定参数
 */
import {
  RISK_BUDGET_TARGET_VOL_FIXED,
  SUBJECTIVE_MONITOR_FIXED_PARAMETERS
} from '@/utils/strategyTemplateFlags';

export default {
  methods: {
    handleTemplateChange(templateCode) {
      const template = this.templateList.find(t => t.code === templateCode);
      if (template && template.parameters) {
        // 初始化参数默认值（与 investmentA 一致，来自模板 schema）
        const parameters = {};
        template.parameters.forEach(param => {
          const defVal = this.getParamDefault(param);
          if (param.param_type === 'dict' || param.param_type === 'max_weight_dict') {
            parameters[param.name] = defVal !== undefined && defVal !== null
              ? (typeof defVal === 'object' ? JSON.stringify(defVal, null, 2) : String(defVal))
              : '{}';
          } else {
            parameters[param.name] = defVal;
          }
        });
        this.form.parameters = parameters;

        // 三层解耦：如果模板的 composition 声明了默认选择器，自动启用资产选择
        if (template.composition && template.composition.selector) {
          const defaultSelector = template.composition.selector;
          this.form.enable_momentum_selection = true;
          this.form.selector_code = 'sel_' + defaultSelector;
          this.form.selector_type = defaultSelector;
          // 初始化选择器参数默认值（从对应的 selection 模板获取）
          this.initSelectorParameters('sel_' + defaultSelector);
        } else if (template.composition
                   && ((template.composition.multi_signal && template.composition.multi_signal.length > 0)
                       || (template.composition.internal_selectors && template.composition.internal_selectors.length > 0))) {
          // multi_signal 复合分配器：内部选择器由 composition 声明，执行层
          // （Pipeline._run_multi_signal）不消费顶层 selector，因此开关保持关闭，
          // 只初始化各内部选择器的信号参数默认值（由选择卡独立渲染）
          let internalSels = [];
          if (template.composition.multi_signal) {
            internalSels = template.composition.multi_signal.map(s => s.selector);
          } else {
            internalSels = template.composition.internal_selectors;
          }
          this.form.enable_momentum_selection = false;
          this.form.selector_code = '';
          this.form.selector_type = '';
          this.form.selector_parameters = {};
          internalSels.forEach(selCode => {
            const extraTpl = this.templateList.find(t => t.code === 'sel_' + selCode);
            if (extraTpl && extraTpl.parameters) {
              extraTpl.parameters.forEach(param => {
                const defVal = param.default !== undefined && param.default !== null
                  ? param.default
                  : (param.default_value !== undefined && param.default_value !== null ? param.default_value : undefined);
                this.$set(this.form.selector_parameters, param.name, defVal);
              });
            }
          });
        } else {
          // 模板无默认选择器，重置选择状态
          this.form.enable_momentum_selection = false;
          this.form.selector_code = '';
          this.form.selector_type = '';
          this.form.selector_parameters = {};
        }

        // 三层解耦：如果模板的 composition 声明了默认控制器，自动启用风险控制
        if (template.composition && template.composition.controller) {
          const defaultController = template.composition.controller;
          this.form.enable_control = true;
          this.form.controller_code = 'ctrl_' + defaultController;
          this.initControllerParameters('ctrl_' + defaultController);
        } else {
          this.form.enable_control = false;
          this.form.controller_code = '';
          this.form.controller_parameters = {};
        }

        // 主观配置：初始化默认资产权重并拉取指数编制上限
        const isManual = (templateCode || '').toString().toLowerCase() === 'manual_allocation' || (templateCode || '').toString().toLowerCase() === 'manual_allocation_strategy';
        if (isManual) {
          const codes = this.form.asset_codes || [];
          const mw = {};
          codes.forEach((c, i) => { mw[c] = i === 0 ? 1 : 0; });
          this.$set(this.form.parameters, 'manual_weights', mw);
          if (!Array.isArray(this.form.parameters.manual_weight_adjustments)) {
            this.$set(this.form.parameters, 'manual_weight_adjustments', []);
          }
          // 主观策略不受指数编制规则限制
          this.maxWeightDict = {};
        }
      }
    },

    resetParameters() {
      if (this.currentTemplate && this.currentTemplate.parameters) {
        const parameters = {};
        this.currentTemplate.parameters.forEach(param => {
          const defVal = this.getParamDefault(param);
          if (param.param_type === 'dict' || param.param_type === 'max_weight_dict') {
            parameters[param.name] = defVal !== undefined && typeof defVal === 'object'
              ? JSON.stringify(defVal, null, 2) : (defVal !== undefined && defVal !== null ? String(defVal) : '{}');
          } else {
            parameters[param.name] = defVal;
          }
        });
        if (this.isManualAllocationTemplate && this.form.asset_codes && this.form.asset_codes.length > 0) {
          const mw = {};
          this.form.asset_codes.forEach((c, i) => { mw[c] = i === 0 ? 1 : 0; });
          parameters.manual_weights = mw;
        }
        this.form.parameters = parameters;
        if (this.isRiskBudgetTargetVolTemplate) {
          this.$set(this.form.parameters, 'lookback_days', RISK_BUDGET_TARGET_VOL_FIXED.lookback_days);
        }
        this.$message.success('参数已重置为默认值');
      }
    },

    /** 主观模板：与实盘监控无关的参数字段固定为产品默认（与后端 enforce 一致） */
    applySubjectiveMonitorFixedToForm() {
      Object.assign(this.form.parameters, SUBJECTIVE_MONITOR_FIXED_PARAMETERS);
      this.form.enable_vol_reset = SUBJECTIVE_MONITOR_FIXED_PARAMETERS.enable_vol_reset;
      this.form.vol_reset_threshold = SUBJECTIVE_MONITOR_FIXED_PARAMETERS.vol_reset_threshold;
      this.form.enable_momentum_selection = false;
      this.form.selector_type = '';
      this.form.asset_selection_count = 1;
      this.form.min_history_days = 260;
    }
  }
};
