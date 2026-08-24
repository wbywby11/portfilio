/**
 * 策略表单 - 数据加载 Mixin
 * 包含：模型数据加载、初始数据拉取、日期格式兼容、参数默认值获取
 */
export default {
  methods: {
    // 兼容后端返回 default_value（模板列表来自 DB）或 default（schema 接口）
    getParamDefault(param) {
      const v = param.default !== undefined && param.default !== null ? param.default : param.default_value;
      return v;
    },

    /** 将后端返回的日期（YYYYMMDD 或 YYYY-MM-DD）转为 el-date-picker 需要的 YYYY-MM-DD */
    normalizeDateForPicker(val) {
      if (!val || typeof val !== 'string') return val;
      const s = String(val).replace(/-/g, '').trim().slice(0, 8);
      if (s.length === 8 && /^\d{8}$/.test(s)) {
        return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
      }
      return val;
    },

    /** 选择器类型旧别名归一：hybrid/reversal 是动量+反转选择器的历史别名，
     * 真实模板 code 为 sel_momentum_reversal，不归一会导致模板匹配失败、参数无法回填 */
    normalizeSelectorType(type) {
      if (!type) return '';
      if (type === 'hybrid' || type === 'reversal') return 'momentum_reversal';
      return type;
    },

    /** 复合分配器（multi_signal/internal_selectors）内部选择器参数回填：
     * 内部选择器由模板 composition 声明，与顶层选择开关无关，
     * 按各内部选择器模板 schema 从 savedParams 取值，缺失用默认值 */
    fillInternalSelectorParams(templateCode, savedParams) {
      const allocTpl = this.templateList.find(t => t.code === templateCode);
      const comp = allocTpl && allocTpl.composition;
      if (!comp) return;
      let internalCodes = [];
      if (comp.multi_signal && comp.multi_signal.length) {
        internalCodes = comp.multi_signal.map(s => 'sel_' + s.selector);
      } else if (comp.internal_selectors && comp.internal_selectors.length) {
        internalCodes = comp.internal_selectors.map(c => 'sel_' + c);
      }
      if (!internalCodes.length) return;
      const selParams = { ...(this.form.selector_parameters || {}) };
      internalCodes.forEach(code => {
        const selTpl = this.templateList.find(t => t.code === code);
        if (!selTpl || !selTpl.parameters) return;
        selTpl.parameters.forEach(param => {
          const savedVal = savedParams && savedParams[param.name] !== undefined
            ? savedParams[param.name] : undefined;
          const defVal = param.default !== undefined && param.default !== null
            ? param.default
            : (param.default_value !== undefined && param.default_value !== null ? param.default_value : undefined);
          selParams[param.name] = savedVal !== undefined && savedVal !== null ? savedVal : defVal;
        });
      });
      if (Object.keys(selParams).length) {
        this.$set(this.form, 'selector_parameters', selParams);
      }
    },

    async loadInitialData() {
      try {
        // 加载模板列表
        await this.$store.dispatch('strategy/fetchTemplateList');

        // 加载资产选项
        const res = await this.$store.dispatch('asset/fetchAssetOptions');
        this.assetOptions = res;
      } catch (error) {
        console.error('加载数据失败:', error);
        this.$message.error('加载数据失败');
      }
    },

    async loadModel() {
      try {
        const model = await this.$store.dispatch('strategy/fetchStrategyModel', this.currentModelId);

        // 处理参数：缺失项用模板默认值（与 investmentA 一致）；dict/max_weight_dict 转为 JSON 字符串显示
        const parameters = { ...(model.parameters || {}) };
        const isManual = model.template_code === 'manual_allocation' || model.template_code === 'manual_allocation_strategy';
        if (model.template_code) {
          const template = this.templateList.find(t => t.code === model.template_code);
          if (template && template.parameters) {
            template.parameters.forEach(param => {
              const hasValue = parameters[param.name] !== undefined && parameters[param.name] !== null;
              if (param.name === 'manual_weights' && isManual) {
                let mw = parameters.manual_weights;
                if (typeof mw === 'string') {
                  try { mw = mw.trim() ? JSON.parse(mw) : {}; } catch (_) { mw = {}; }
                }
                if (typeof mw !== 'object' || mw === null) mw = {};
                const codes = model.asset_codes || [];
                codes.forEach(c => { if (mw[c] === undefined) mw[c] = 0; });
                Object.keys(mw).forEach(c => { if (!codes.includes(c)) delete mw[c]; });
                parameters.manual_weights = mw;
                return;
              }
              if (!hasValue) {
                // 模型未保存该参数时，使用模板默认值（与 investmentA 一致；兼容 default_value）
                const defVal = param.default !== undefined && param.default !== null ? param.default : param.default_value;
                if (param.param_type === 'dict' || param.param_type === 'max_weight_dict') {
                  parameters[param.name] = defVal !== undefined && typeof defVal === 'object'
                    ? JSON.stringify(defVal, null, 2) : (defVal !== undefined && defVal !== null ? String(defVal) : '{}');
                } else {
                  parameters[param.name] = defVal;
                }
              } else if ((param.param_type === 'dict' || param.param_type === 'max_weight_dict')
                  && typeof parameters[param.name] === 'object') {
                parameters[param.name] = JSON.stringify(parameters[param.name], null, 2);
              }
            });
            // 主观策略：解析预设调仓日 manual_weight_adjustments（非模板参数，单独处理）
            if (isManual) {
              let mwa = parameters.manual_weight_adjustments;
              if (typeof mwa === 'string') {
                try { mwa = mwa.trim() ? JSON.parse(mwa) : []; } catch (_) { mwa = []; }
              }
              if (!Array.isArray(mwa)) mwa = [];
              const codes = model.asset_codes || [];
              mwa.forEach(adj => {
                if (adj && adj.weights && typeof adj.weights === 'object') {
                  codes.forEach(c => { if (adj.weights[c] === undefined) adj.weights[c] = 0; });
                  Object.keys(adj.weights).forEach(c => { if (!codes.includes(c)) delete adj.weights[c]; });
                }
              });
              parameters.manual_weight_adjustments = mwa;
            }
          }
        }
        if (isManual && (parameters.manual_weight_adjustments === undefined || parameters.manual_weight_adjustments === null)) {
          parameters.manual_weight_adjustments = [];
        }
        // 兼容旧数据：vol_scaled_budget 分配器 vol_windows "22,65,130" -> 三个独立字段
        if (model.template_code === 'vol_scaled_budget' && parameters.vol_windows && parameters.vol_window_short === undefined) {
          const vwParts = String(parameters.vol_windows).split(',').map(Number);
          parameters.vol_window_short = vwParts[0] || 22;
          parameters.vol_window_medium = vwParts[1] || 65;
          parameters.vol_window_long = vwParts[2] || 130;
          delete parameters.vol_windows;
        }
        // 主观策略：确保预设调仓日期的格式为 YYYY-MM-DD（后端可能返回 YYYYMMDD）
        if (isManual && Array.isArray(parameters.manual_weight_adjustments)) {
          parameters.manual_weight_adjustments.forEach(adj => {
            if (adj && adj.date) {
              adj.date = this.normalizeDateForPicker(adj.date);
            }
          });
        }

        this.form = {
          name: model.name,
          description: model.description || '',
          template_code: model.template_code,
          asset_codes: model.asset_codes || [],
          parameters: parameters,
          rebalance_frequency: model.rebalance_frequency || '月',
          // 资产选择配置
          enable_momentum_selection: model.enable_momentum_selection || false,
          selector_type: this.normalizeSelectorType(model.selector_type) || '',
          asset_selection_count: model.asset_selection_count || 1,
          min_history_days: model.min_history_days !== undefined ? model.min_history_days : 260,
          // 波动率阈值重置（从 parameters 读取，兼容旧数据）
          enable_vol_reset: (model.parameters && model.parameters.enable_vol_reset !== undefined) ? model.parameters.enable_vol_reset : true,
          vol_reset_threshold: (model.parameters && model.parameters.vol_reset_threshold !== undefined) ? model.parameters.vol_reset_threshold : 0.06,
          // 动态选择器/控制器（'none' 哨兵 = 显式无控制器，按禁用展示）
          selector_code: model.selector_type ? ('sel_' + this.normalizeSelectorType(model.selector_type)) : '',
          selector_parameters: {},
          enable_control: !!model.controller_code && String(model.controller_code).toLowerCase() !== 'none',
          controller_code: (model.controller_code && String(model.controller_code).toLowerCase() !== 'none')
            ? model.controller_code : '',
          controller_parameters: model.controller_parameters || {}
        };
        // 加载选择器动态参数（优先使用后端 resolved_params，回退到旧逻辑）
        if (model.resolved_params && model.resolved_params.selector) {
          const rpSelector = model.resolved_params.selector;
          this.form.enable_momentum_selection = rpSelector.enabled || false;
          this.form.selector_type = this.normalizeSelectorType(rpSelector.type) || '';
          this.form.selector_code = rpSelector.type ? ('sel_' + this.normalizeSelectorType(rpSelector.type)) : '';
          // 从 resolved_params.selector.params 回填表单选择器参数
          if (this.form.selector_code) {
            const selTpl = this.templateList.find(t => t.code === this.form.selector_code);
            if (selTpl && selTpl.parameters) {
              const selParams = {};
              selTpl.parameters.forEach(param => {
                const savedVal = rpSelector.params && rpSelector.params[param.name] !== undefined
                  ? rpSelector.params[param.name]
                  : undefined;
                const defVal = param.default !== undefined && param.default !== null
                  ? param.default
                  : (param.default_value !== undefined && param.default_value !== null ? param.default_value : undefined);
                selParams[param.name] = savedVal !== undefined && savedVal !== null ? savedVal : defVal;
              });
              this.$set(this.form, 'selector_parameters', selParams);
            }
          }
          // 顶层选择器字段也从 resolved_params 同步
          if (rpSelector.params) {
            if (rpSelector.params.asset_selection_count != null) {
              this.form.asset_selection_count = rpSelector.params.asset_selection_count;
            }
            if (rpSelector.params.min_history_days != null) {
              this.form.min_history_days = rpSelector.params.min_history_days;
            }
          }
          // 复合分配器（multi_signal/internal_selectors）：内部选择器参数由 composition 声明，
          // 与「启用资产选择」开关无关（enabled=false 也需回填，否则编辑保存会丢失信号参数）
          if (!this.form.selector_code) {
            this.fillInternalSelectorParams(model.template_code, rpSelector.params);
          }
        } else if (this.form.selector_code) {
          // 回退：旧逻辑（无 resolved_params 时使用）
          const selTpl = this.templateList.find(t => t.code === this.form.selector_code);
          if (selTpl && selTpl.parameters) {
            const selParams = {};
            selTpl.parameters.forEach(param => {
              // 优先从模型的 selector_parameters 读取，否则从模型顶层字段读取
              const savedVal = (model.selector_parameters && model.selector_parameters[param.name] !== undefined)
                ? model.selector_parameters[param.name]
                : model[param.name];
              const defVal = param.default !== undefined && param.default !== null
                ? param.default
                : (param.default_value !== undefined && param.default_value !== null ? param.default_value : undefined);
              selParams[param.name] = savedVal !== undefined && savedVal !== null ? savedVal : defVal;
            });
            this.$set(this.form, 'selector_parameters', selParams);
          }
        } else if (model.template_code) {
          // 回退：无 resolved_params 且无顶层选择器时，复合模板内部选择器参数从 model.selector_parameters 回填
          this.fillInternalSelectorParams(model.template_code, model.selector_parameters || {});
        }
        // 加载控制器动态参数（优先使用后端 resolved_params，回退到旧逻辑）
        if (model.resolved_params && model.resolved_params.controller && model.resolved_params.controller.enabled) {
          const rpCtrl = model.resolved_params.controller;
          this.form.enable_control = true;
          this.form.controller_code = rpCtrl.code || '';
          if (this.form.controller_code) {
            const ctrlTpl = this.templateList.find(t => t.code === this.form.controller_code);
            if (ctrlTpl && ctrlTpl.parameters) {
              const ctrlParams = {};
              ctrlTpl.parameters.forEach(param => {
                const savedVal = rpCtrl.params && rpCtrl.params[param.name] !== undefined
                  ? rpCtrl.params[param.name]
                  : undefined;
                const defVal = param.default !== undefined && param.default !== null
                  ? param.default
                  : (param.default_value !== undefined && param.default_value !== null ? param.default_value : undefined);
                ctrlParams[param.name] = savedVal !== undefined && savedVal !== null ? savedVal : defVal;
              });
              this.$set(this.form, 'controller_parameters', ctrlParams);
            }
          }
        } else if (this.form.controller_code && model.controller_parameters) {
          // 回退：旧逻辑
          const ctrlTpl = this.templateList.find(t => t.code === this.form.controller_code);
          if (ctrlTpl && ctrlTpl.parameters) {
            const ctrlParams = {};
            ctrlTpl.parameters.forEach(param => {
              const savedVal = model.controller_parameters[param.name];
              const defVal = param.default !== undefined && param.default !== null
                ? param.default
                : (param.default_value !== undefined && param.default_value !== null ? param.default_value : undefined);
              ctrlParams[param.name] = savedVal !== undefined && savedVal !== null ? savedVal : defVal;
            });
            this.$set(this.form, 'controller_parameters', ctrlParams);
          }
        }
        // 兼容旧数据：vol_windows "22,65,130" -> 三个独立字段
        if (this.form.controller_code === 'ctrl_rolling_vol') {
          const cp = this.form.controller_parameters || {};
          if (cp.vol_windows && cp.vol_window_short === undefined) {
            const parts = String(cp.vol_windows).split(',').map(Number);
            this.$set(this.form.controller_parameters, 'vol_window_short', parts[0] || 22);
            this.$set(this.form.controller_parameters, 'vol_window_medium', parts[1] || 65);
            this.$set(this.form.controller_parameters, 'vol_window_long', parts[2] || 130);
            this.$delete(this.form.controller_parameters, 'vol_windows');
          }
          // 兼容旧字段名 vol_trigger_threshold -> vol_reset_threshold
          if (cp.vol_trigger_threshold !== undefined && cp.vol_reset_threshold === undefined) {
            this.$set(this.form.controller_parameters, 'vol_reset_threshold', cp.vol_trigger_threshold);
            this.$delete(this.form.controller_parameters, 'vol_trigger_threshold');
          }
        }
      } catch (error) {
        this.$message.error('加载策略数据失败');
        this.$router.back();
      }
    }
  }
};
