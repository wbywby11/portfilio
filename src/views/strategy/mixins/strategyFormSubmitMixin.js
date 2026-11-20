/**
 * 策略表单 - 提交与校验 Mixin
 * 包含：表单提交（参数组装、校验、API调用）、取消操作
 */
import {
  SUBJECTIVE_MONITOR_FIXED_PARAMETERS
} from '@/utils/strategyTemplateFlags';
import { normalizeWeightsToTwoDecimalSumOne } from '@/utils/subjectiveWeights';

export default {
  methods: {
    handleSubmit() {
      this.$refs.form.validate(async (valid) => {
        if (!valid) {
          this.$message.warning('请完善必填项');
          return;
        }
        if (this.isManualAllocationTemplate) {
          const codes = this.form.asset_codes || [];
          const mw = this.form.parameters.manual_weights;
          if (!mw || typeof mw !== 'object') {
            this.$message.warning('主观配置策略请至少为一个资产配置权重大于 0');
            return;
          }
          // 确保当前资产在 manual_weights 中均有键（避免未响应式导致读不到）
          codes.forEach(c => {
            if (mw[c] === undefined) this.$set(mw, c, 0);
          });
          let sum = 0;
          let anyPositive = false;
          codes.forEach(c => {
            const val = Number(mw[c]);
            if (!Number.isNaN(val)) {
              sum += val;
              if (val > 0) anyPositive = true;
            }
          });
          if (!anyPositive || sum < 1e-6) {
            this.$message.warning('主观配置策略请至少为一个资产配置权重大于 0');
            return;
          }
          const maxLev = this.maxLeverageParam;
          if (sum > maxLev) {
            this.$message.warning(`总仓位权重 ${(sum * 100).toFixed(2)}% 超过最大杠杆 ${(maxLev * 100).toFixed(0)}%，请调整默认资产权重或下方「最大杠杆」参数`);
            return;
          }
        }

        this.submitting = true;
        try {
          // 处理参数：如果是 dict 类型或 max_weight_dict 类型，尝试从 JSON 字符串解析为对象
          const submitParameters = { ...this.form.parameters };
          if (this.currentTemplate && this.currentTemplate.parameters) {
            this.currentTemplate.parameters.forEach(param => {
              // 支持 dict 和 max_weight_dict 类型
              if ((param.param_type === 'dict' || param.param_type === 'max_weight_dict')
                  && typeof submitParameters[param.name] === 'string') {
                const paramValue = submitParameters[param.name];
                // 如果字符串为空，使用空对象
                if (!paramValue || paramValue.trim() === '') {
                  submitParameters[param.name] = {};
                } else {
                  try {
                    const parsed = JSON.parse(paramValue);
                    // 验证解析后的结果是否是对象/字典
                    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
                      submitParameters[param.name] = parsed;
                    } else {
                      // 如果解析后不是对象，说明格式错误
                      throw new Error(`参数 "${param.label || param.name}" 必须是 JSON 对象格式，如：{"key": "value"}`);
                    }
                  } catch (e) {
                    console.error(`解析参数 ${param.name} 失败:`, e);
                    // 如果解析失败，抛出错误
                    throw new Error(`参数 "${param.label || param.name}" 不是有效的 JSON 格式。请确保格式正确，如：{"ZZ000001": 0.6, "HSTECH": 0.5}`);
                  }
                }
              }
            });
          }

          // 仅当模板 schema 声明了 enable_vol_reset 时才确保控制器参数存在
          // schema 驱动的参数已在 form.parameters 中，仅对旧模板补充顶层字段
          const templateHasVolReset = this.currentTemplate?.parameters?.some(
            p => p.name === 'enable_vol_reset'
          );
          if (templateHasVolReset && submitParameters.enable_vol_reset === undefined) {
            submitParameters.enable_vol_reset = this.form.enable_vol_reset;
            submitParameters.vol_reset_threshold = this.form.vol_reset_threshold;
          }
          if (this.isManualAllocationTemplate) {
            Object.assign(submitParameters, SUBJECTIVE_MONITOR_FIXED_PARAMETERS);
            const codes = this.form.asset_codes || [];
            const adjList = submitParameters.manual_weight_adjustments;
            if (Array.isArray(adjList)) {
              for (let i = 0; i < adjList.length; i++) {
                const row = adjList[i];
                if (!row || !row.date) continue;
                const w = row.weights && typeof row.weights === 'object' ? row.weights : {};
                let t = codes.reduce((s, c) => s + (Number(w[c]) || 0), 0);
                if (row.auto_normalize && t > 0) {
                  const out = normalizeWeightsToTwoDecimalSumOne({ ...w }, codes);
                  if (!row.weights || typeof row.weights !== 'object') {
                    row.weights = {};
                  }
                  codes.forEach(c => {
                    row.weights[c] = out[c];
                  });
                } else if (t > 1.00001) {
                  this.$message.warning(
                    `预设调仓第 ${i + 1} 条（${row.date}）权重合计超过 100%，请调低或开启「保存时归一化」`
                  );
                  this.submitting = false;
                  return;
                }
              }
            }
          }

          // 从 selector_code 派生选择器类型（去掉 sel_ 前缀）
          const hasSelection = !!this.form.selector_code;
          const rawSelectorType = hasSelection
            ? (this.form.selector_code.startsWith('sel_') ? this.form.selector_code.slice(4) : this.form.selector_code)
            : '';

          // 复合分配器（multi_signal/internal_selectors）：内部选择器由 composition 声明，
          // 与「启用资产选择」开关无关，其信号参数（如 tf_lookback/cs_lookback_months）
          // 即使 hasSelection=false 也必须提交，否则复合信号退化默认参数
          const allocComposition = this.currentTemplate && this.currentTemplate.composition;
          const isCompositeSignalTemplate = !!(allocComposition
            && ((allocComposition.multi_signal && allocComposition.multi_signal.length)
              || allocComposition.internal_selectors));

          // 选择器参数统一走 parameters.selector_parameters 字典，不再发送 legacy 顶层字段
          const selParams = this.form.selector_parameters || {};
          if ((hasSelection || isCompositeSignalTemplate) && Object.keys(selParams).length > 0) {
            submitParameters.selector_parameters = selParams;
          }

          // 控制器参数 schema 净化：仅发送控制器模板 schema 声明的参数
          let cleanedControllerParams = this.form.controller_parameters || {};
          if (this.form.enable_control && this.form.controller_code) {
            const ctrlTpl = this.templateList.find(t => t.code === this.form.controller_code);
            if (ctrlTpl && ctrlTpl.parameters) {
              const schemaKeys = new Set(ctrlTpl.parameters.map(p => p.name));
              cleanedControllerParams = {};
              Object.entries(this.form.controller_parameters || {}).forEach(([k, v]) => {
                if (schemaKeys.has(k)) cleanedControllerParams[k] = v;
              });
            }
          }

          // 控制器提交码：启用且有选择 → 所选模板码；禁用但分配模板声明了默认控制器
          // → 提交 'none' 哨兵（后端 composition_builder 据此覆盖模板默认 controller）
          let submitControllerCode = (this.form.enable_control && this.form.controller_code)
            ? this.form.controller_code
            : undefined;
          if (!submitControllerCode) {
            const allocTpl = this.templateList.find(t => t.code === this.form.template_code);
            const defaultCtrl = allocTpl && allocTpl.composition && allocTpl.composition.controller;
            if (defaultCtrl) {
              submitControllerCode = 'none';
            }
          }

          const modelData = {
            name: this.form.name,
            description: this.form.description,
            template_code: this.form.template_code,
            asset_codes: this.form.asset_codes,
            parameters: submitParameters,
            rebalance_frequency: this.form.rebalance_frequency,
            // 资产选择：仅发送类型标识 + 通用参数，具体窗口由 selector_parameters 字典管理
            enable_momentum_selection: hasSelection,
            selector_type: hasSelection ? rawSelectorType : undefined,
            asset_selection_count: (hasSelection && this.selectorNeedsAssetCount)
              ? this.form.asset_selection_count : undefined,
            min_history_days: (hasSelection && this.selectorNeedsMinHistory)
              ? this.form.min_history_days : undefined,
            // 控制器
            controller_code: submitControllerCode,
            controller_parameters: submitControllerCode && submitControllerCode !== 'none'
              ? cleanedControllerParams : {},
            // 结构化参数快照（与 resolved_params 对称，供后端校验）
            structured_params: {
              allocator: { ...submitParameters },
              selector: {
                enabled: hasSelection,
                type: hasSelection ? rawSelectorType : null,
                params: (hasSelection || isCompositeSignalTemplate) ? { ...selParams } : {},
              },
              controller: {
                enabled: !!(submitControllerCode && submitControllerCode !== 'none'),
                code: submitControllerCode || null,
                params: (submitControllerCode && submitControllerCode !== 'none') ? { ...cleanedControllerParams } : {},
              },
            },
            // 原型预设留痕：只传 preset_code 与资产池快照，
            // preset_version / preset_applied_at 由后端按当前定义重算（不采信前端）
            preset_code: this.form.preset_code || null,
            asset_selection_snapshot: this.form.asset_selection_snapshot || null,
          };
          if (this.isEdit) {
            await this.$store.dispatch('strategy/updateStrategyModel', {
              modelId: this.currentModelId,
              data: modelData
            });
            this.$message.success('更新成功');
          } else {
            await this.$store.dispatch('strategy/createStrategyModel', modelData);
            this.$message.success('创建成功，策略已保存为草稿');
          }

          if (this.isDialog) {
            this.$emit('success');
          } else {
            this.$router.push({ name: 'StrategyModelList' });
          }
        } catch (error) {
          this.$message.error('保存失败：' + (error.response?.data?.detail || error.message));
        } finally {
          this.submitting = false;
        }
      });
    },

    handleCancel() {
      if (this.isDialog) {
        this.$emit('close');
      } else {
        this.$router.back();
      }
    }
  }
};
