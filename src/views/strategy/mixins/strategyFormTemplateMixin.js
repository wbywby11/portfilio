/**
 * 策略表单 - 模板切换与参数重置 Mixin
 * 包含：模板变更三层联动、参数重置、主观策略固定参数、原型预设应用
 */
import {
  RISK_BUDGET_TARGET_VOL_FIXED,
  SUBJECTIVE_MONITOR_FIXED_PARAMETERS
} from '@/utils/strategyTemplateFlags';
import { getStrategyPresets, resolveStrategyPreset } from '@/api/strategy';

export default {
  data() {
    return {
      // 原型预设：当前模板可选项、待应用结果、问题弹窗、应用基准
      presetList: [],
      presetApplying: false,
      pendingPreset: null,
      presetIssuesVisible: false,
      presetBaseline: '',
      presetModified: false,
      presetOutdated: false
    };
  },
  computed: {
    /** 待应用预设的问题按三级分组 */
    pendingPresetIssues() {
      const issues = (this.pendingPreset && this.pendingPreset.issues) || [];
      return {
        blocking: issues.filter(i => i.level === 'blocking_error'),
        data: issues.filter(i => i.level === 'data_error'),
        warning: issues.filter(i => i.level === 'warning')
      };
    },
    /** 待应用预设的问题分段（按阻断 → 数据 → 提示排列，模板直接循环） */
    presetIssueSections() {
      const groups = this.pendingPresetIssues;
      const sections = [];
      if (groups.blocking.length) {
        sections.push({
          level: 'blocking_error',
          title: '阻断问题 · 应用后必然跑不通，不可应用',
          items: groups.blocking
        });
      }
      if (groups.data.length) {
        sections.push({
          level: 'data_error',
          title: '数据缺口 · 可保存，但未通过数据门禁，禁止回测',
          items: groups.data
        });
      }
      if (groups.warning.length) {
        sections.push({ level: 'warning', title: '提示', items: groups.warning });
      }
      return sections;
    },
    /** 当前表单配置指纹（键排序后序列化），与预设应用基准比对 */
    currentConfigSignature() {
      const params = this.form.parameters || {};
      const ordered = {};
      Object.keys(params).sort().forEach(k => { ordered[k] = params[k]; });
      const codes = Array.isArray(this.form.asset_codes)
        ? this.form.asset_codes.slice().sort()
        : [];
      return JSON.stringify({ asset_codes: codes, parameters: ordered });
    },
    /** 当前模型所基于的预设名称（未应用预设时为空） */
    presetSourceName() {
      if (!this.form.preset_code) return '';
      const item = this.presetList.find(p => p.code === this.form.preset_code);
      return item ? item.name : this.form.preset_code;
    }
  },
  watch: {
    /** 模板切换时重新拉取该模板的预设清单；
     *  覆盖新建、编辑回填、手动切换三条入口 */
    'form.template_code'(code) {
      this.loadPresets(code);
    },
    currentConfigSignature(signature) {
      // 编辑模式由后端给 preset_modified（前端算不了指纹 hash）；
      // 只有应用过预设（存在 baseline）后才由前端接管实时判定
      if (!this.presetBaseline) return;
      this.presetModified = signature !== this.presetBaseline;
    }
  },
  methods: {
    /** 拉取当前模板的原型预设（失败不阻断手动配置） */
    async loadPresets(templateCode) {
      this.presetList = [];
      if (!templateCode) return;
      try {
        const res = await getStrategyPresets(templateCode);
        this.presetList = (res && res.data) || [];
      } catch (error) {
        console.error('加载策略预设失败:', error);
        this.presetList = [];
      }
    },

    /** 点击预设：先确认覆盖，再展开并弹出门禁结果 */
    async previewPreset(presetCode) {
      if (!presetCode) return;

      if (this.formAlreadyEdited()) {
        try {
          await this.$confirm(
            '当前表单已有修改，应用预设会覆盖参数与资产池，是否继续？',
            '覆盖确认',
            { confirmButtonText: '继续应用', cancelButtonText: '取消', type: 'warning' }
          );
        } catch (e) {
          return;
        }
      }

      this.presetApplying = true;
      try {
        const res = await resolveStrategyPreset(presetCode);
        const data = (res && res.data) || null;
        if (!data) {
          this.$message.error('预设展开结果为空');
          return;
        }
        this.pendingPreset = data;
        this.presetIssuesVisible = true;
      } catch (error) {
        const detail = error && error.response && error.response.data && error.response.data.detail;
        this.$message.error(detail || error.message || '预设展开失败');
      } finally {
        this.presetApplying = false;
      }
    },

    /** 确认应用（仅 blocking 阻断） */
    applyPendingPreset() {
      const data = this.pendingPreset;
      if (!data) return;
      if (data.applicable === false) {
        this.$message.error('预设存在阻断问题，无法应用');
        return;
      }
      this.writePresetToForm(data);
      this.presetIssuesVisible = false;
      this.pendingPreset = null;
      this.$message.success(`已应用预设：${data.name || ''}`);
    },

    /** 关闭问题弹窗（不应用） */
    closePresetDialog() {
      this.presetIssuesVisible = false;
      this.pendingPreset = null;
    },

    /** 把展开结果写入表单 */
    writePresetToForm(data) {
      // 参数先用模板 schema 默认值打底，避免预设漏给的键变 undefined
      const parameters = {};
      const specs = (this.currentTemplate && this.currentTemplate.parameters) || [];
      specs.forEach(param => {
        const defVal = this.getParamDefault(param);
        if (param.param_type === 'dict' || param.param_type === 'max_weight_dict') {
          parameters[param.name] = defVal !== undefined && defVal !== null
            ? (typeof defVal === 'object' ? JSON.stringify(defVal, null, 2) : String(defVal))
            : '{}';
        } else {
          parameters[param.name] = defVal;
        }
      });

      const incoming = data.parameters || {};
      Object.keys(incoming).forEach(key => {
        const spec = specs.find(p => p.name === key);
        const type = spec ? (spec.param_type || spec.type) : '';
        const raw = incoming[key];
        if ((type === 'dict' || type === 'max_weight_dict') && raw !== null && typeof raw === 'object') {
          parameters[key] = JSON.stringify(raw, null, 2);
        } else {
          parameters[key] = raw;
        }
      });

      this.form.asset_codes = Array.isArray(data.asset_codes) ? data.asset_codes.slice() : [];
      this.form.parameters = parameters;
      if (data.rebalance_frequency && !this.isManualAllocationTemplate) {
        this.form.rebalance_frequency = data.rebalance_frequency;
      }
      if (data.min_history_days !== null && data.min_history_days !== undefined) {
        this.form.min_history_days = data.min_history_days;
      }
      this.form.preset_code = data.preset_code || '';
      this.form.preset_version = data.preset_version || '';
      this.form.asset_selection_snapshot = data.asset_selection_snapshot || null;

      // 基准指纹与 currentConfigSignature 同口径，用于识别应用后的手动调整
      this.$nextTick(() => {
        this.presetBaseline = this.currentConfigSignature;
        this.presetModified = false;
        this.presetOutdated = false;
      });
    },

    /** 当前表单是否已偏离模板默认值（决定应用预设前是否弹覆盖确认） */
    formAlreadyEdited() {
      if (Array.isArray(this.form.asset_codes) && this.form.asset_codes.length > 0) {
        return true;
      }
      const specs = (this.currentTemplate && this.currentTemplate.parameters) || [];
      return specs.some(param => {
        const def = this.getParamDefault(param);
        const cur = (this.form.parameters || {})[param.name];
        const isDict = param.param_type === 'dict' || param.param_type === 'max_weight_dict';
        if (isDict) {
          const defText = def !== undefined && def !== null
            ? (typeof def === 'object' ? JSON.stringify(def, null, 2) : String(def))
            : '{}';
          return cur !== undefined && cur !== defText;
        }
        if (def !== null && typeof def === 'object') {
          return JSON.stringify(cur) !== JSON.stringify(def);
        }
        return cur !== undefined && cur !== def;
      });
    },
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

      // 换模板等于换语义：旧预设来源与「已调整」基准全部失效
      this.form.preset_code = '';
      this.form.preset_version = '';
      this.form.preset_applied_at = null;
      this.form.asset_selection_snapshot = null;
      this.presetBaseline = '';
      this.presetModified = false;
      this.presetOutdated = false;
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
