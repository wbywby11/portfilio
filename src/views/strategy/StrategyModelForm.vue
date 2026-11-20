<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑策略' : '新建策略' }}</h2>
    </div>

    <div :class="{'page-content': !isDialog}">
      <el-form
        ref="form"
        :model="form"
        :rules="rules"
        label-width="140px"
        class="strategy-form"
      >
        <el-card shadow="never" class="form-card">
          <div slot="header" class="card-header">
            <span>基本信息</span>
          </div>

          <el-form-item label="策略名称" prop="name">
            <el-input
              v-model="form.name"
              placeholder="请输入策略名称"
              maxlength="50"
              show-word-limit
            ></el-input>
          </el-form-item>

          <el-form-item label="策略描述" prop="description">
            <el-input
              type="textarea"
              v-model="form.description"
              :rows="3"
              placeholder="请输入策略描述（可选）"
              maxlength="200"
              show-word-limit
            ></el-input>
          </el-form-item>
        </el-card>

        <el-card shadow="never" class="form-card">
          <div slot="header" class="card-header">
            <span>策略配置</span>
          </div>

          <el-form-item label="策略模板" prop="template_code">
            <div class="field-row">
              <el-select
                v-model="form.template_code"
                class="field-row__control"
                placeholder="请选择策略模板"
                @change="handleTemplateChange"
              >
                <el-option
                  v-for="tpl in allocationTemplateList"
                  :key="tpl.code"
                  :label="`${tpl.code} - ${tpl.name}`"
                  :value="tpl.code"
                ></el-option>
              </el-select>
              <el-tooltip content="选择资产配置策略，不同策略有不同的风险收益特征" placement="top">
                <i class="el-icon-question field-row__icon"></i>
              </el-tooltip>
            </div>
            <!-- 描述单独成行：塞进 option 会把下拉面板按内容宽度撑到弹窗之外 -->
            <div v-if="currentTemplate && currentTemplate.description" class="template-desc">
              {{ currentTemplate.description }}
            </div>
          </el-form-item>

          <el-form-item label="选择资产" prop="asset_codes">
            <el-select
              v-model="form.asset_codes"
              multiple
              filterable
              placeholder="请选择资产（可多选）"
              style="width: 100%;"
            >
              <el-option
                v-for="asset in assetOptions"
                :key="asset.code"
                :label="`${asset.code} - ${asset.name}`"
                :value="asset.code"
              ></el-option>
            </el-select>
            <el-tooltip content="选择参与策略计算的资产池，如启用资产选择，则从该池中筛选TopN资产" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
            <div v-if="form.asset_codes.length > 0" style="margin-top: 10px;">
              <el-tag
                v-for="code in form.asset_codes"
                :key="code"
                closable
                @close="removeAsset(code)"
                style="margin-right: 8px; margin-bottom: 8px;"
              >
                {{ getAssetLabel(code) }}
              </el-tag>
            </div>
            <!-- 原型预设来源：应用即快照，标签后续变更不会自动同步 -->
            <div v-if="form.preset_code" class="preset-source">
              <i class="el-icon-collection-tag"></i>
              <span>
                来自预设 {{ presetSourceName }}
                <template v-if="isPresetTagPool">（标签池，应用时快照）</template>
                <template v-else>（应用时快照）</template>
                ，标签后续变更不会自动同步
              </span>
              <el-tag v-if="presetModified" size="mini" type="warning" class="preset-source__flag">已调整</el-tag>
              <el-tag v-if="presetOutdated" size="mini" type="info" class="preset-source__flag">基于旧版预设</el-tag>
            </div>
          </el-form-item>

          <el-form-item v-if="!isManualAllocationTemplate" label="调仓频率" prop="rebalance_frequency">
            <el-select v-model="form.rebalance_frequency" placeholder="请选择调仓频率" style="width: 200px;">
              <el-option label="日度" value="日"></el-option>
              <el-option label="周度" value="周"></el-option>
              <el-option label="月度" value="月"></el-option>
              <el-option label="季度" value="季"></el-option>
              <el-option label="年度" value="年"></el-option>
            </el-select>
            <el-tooltip content="调仓频率：日=每日、周=每周、月=每月、季=每季度、年=每年" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>
        </el-card>

        <!-- 主观配置：与日常监控相同的权重编辑（滑块 + 条形示意 + 归一化） -->
        <el-card shadow="never" class="form-card manual-weights-card" v-if="isManualAllocationTemplate">
          <div slot="header" class="card-header">
            <span>主观配置权重</span>
            <el-tooltip
              content="默认权重用于期初建仓；预设调仓用于指定日期的目标权重。交互与日常监控页「实盘生效参数」一致，支持归一化到 100%。主观策略无周期性调仓，总仓位不超过 100%（实盘固定杠杆上限 1 倍）。"
              placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </div>
          <el-form-item label-width="0" class="manual-weights-form-item">
            <SubjectiveWeightsFormPanel
              :asset-codes="form.asset_codes || []"
              :manual-weights="form.parameters.manual_weights"
              :manual-weight-adjustments="presetRebalanceList"
              :resolve-label="subjectiveWeightsEditorLabel"
              @add-preset="addPresetRebalance"
              @remove-preset="removePresetRebalance"
            />
          </el-form-item>
        </el-card>

        <!-- 资产选择策略区域（子组件）；打包独立策略的选样在策略包内，不渲染 -->
        <strategy-selection-card
          v-if="!isStandaloneTemplate"
          :form="form"
          :selection-template-list="selectionTemplateList"
          :template-list="templateList"
          :current-template="currentTemplate"
          @selector-code-change="handleSelectorCodeChange"
          @reset-selector-params="resetSelectorParameters"
        />

        <!-- 风险控制策略（子组件）；打包独立策略的日度风控在策略包内，不渲染 -->
        <strategy-control-card
          v-if="!isStandaloneTemplate"
          :form="form"
          :control-template-list="controlTemplateList"
          :template-list="templateList"
          @controller-code-change="handleControllerCodeChange"
          @reset-controller-params="resetControllerParameters"
        />

        <!-- 模型参数（子组件） -->
        <strategy-allocator-params-card
          :form="form"
          :current-template="currentTemplate"
          :asset-options="selectedAssetOptions"
          :is-manual-allocation="isManualAllocationTemplate"
          :is-sharpe-risk-budget="isSharpeRiskBudgetTemplate"
          :is-risk-budget-target-vol="isRiskBudgetTargetVolTemplate"
          :presets="presetList"
          :preset-loading="presetApplying"
          @reset-params="resetParameters"
          @apply-preset="previewPreset"
          @param-change="handleAllocatorParamChange"
        />

        <el-form-item>
          <el-button type="primary" @click="handleSubmit" :loading="submitting">
            {{ submitting ? '保存中...' : '保存策略' }}
          </el-button>
          <el-button @click="handleCancel">取消</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 预设展开/校验结果：blocking 阻断应用，data 允许保存但禁用回测，warning 仅提示 -->
    <el-dialog
      title="预设校验结果"
      :visible.sync="presetIssuesVisible"
      width="680px"
      append-to-body
      @close="closePresetDialog"
    >
      <div v-if="pendingPreset" class="preset-dialog">
        <div class="preset-dialog__summary">
          <span class="preset-dialog__name">{{ pendingPreset.name }}</span>
          <span class="preset-dialog__meta">
            资产 {{ (pendingPreset.asset_codes || []).length }} 只 · 预设版本 {{ pendingPreset.preset_version }}
          </span>
        </div>

        <div
          v-for="section in presetIssueSections"
          :key="section.level"
          class="preset-issue-section"
          :class="'is-' + section.level"
        >
          <div class="preset-issue-section__title">{{ section.title }}（{{ section.items.length }}）</div>
          <div v-for="(issue, idx) in section.items" :key="section.level + idx" class="preset-issue">
            <div class="preset-issue__msg">{{ issue.message }}</div>
            <div v-if="issue.hint" class="preset-issue__hint">{{ issue.hint }}</div>
            <div v-if="issue.assets && issue.assets.length" class="preset-issue__assets">
              {{ issue.assets.join('、') }}
            </div>
          </div>
        </div>

        <div v-if="!pendingPreset.issues || pendingPreset.issues.length === 0" class="preset-dialog__ok">
          <i class="el-icon-circle-check"></i> 校验通过，可直接应用。
        </div>

        <div class="preset-dialog__note">
          预设校验不包含单日跳变与价格非正检查，这两项在回测时由引擎校验。
        </div>
      </div>
      <span slot="footer">
        <el-button size="small" @click="closePresetDialog">取消</el-button>
        <el-button
          size="small"
          type="primary"
          :disabled="!pendingPreset || pendingPreset.applicable === false"
          @click="applyPendingPreset"
        >{{ pendingPreset && pendingPreset.applicable === false ? '存在阻断问题' : '应用' }}</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import { getMaxWeightsByCodes } from '@/api/strategy';
import {
  isRiskBudgetTargetVolTemplateCode,
  isRiskBudgetTargetVolHiddenTemplateParameter,
  isManualAllocationTemplateCode,
  isSubjectiveMonitorHiddenSchemaParameter as checkSubjectiveHiddenSchemaParam,
  isSharpeRiskBudgetTemplateCode,
  SHARPE_RISK_BUDGET_FIXED,
  isSharpeRiskBudgetHiddenSchemaParameter as checkSharpeHiddenSchemaParam
} from '@/utils/strategyTemplateFlags';
import SubjectiveWeightsFormPanel from '@/components/SubjectiveWeightsFormPanel.vue';
import KeyValueEditor from '@/components/KeyValueEditor.vue';
import StrategySelectionCard from './components/StrategySelectionCard.vue';
import StrategyControlCard from './components/StrategyControlCard.vue';
import StrategyAllocatorParamsCard from './components/StrategyAllocatorParamsCard.vue';
import strategyFormLoadMixin from './mixins/strategyFormLoadMixin';
import strategyFormTemplateMixin from './mixins/strategyFormTemplateMixin';
import strategyFormSubmitMixin from './mixins/strategyFormSubmitMixin';

export default {
  name: 'StrategyModelForm',
  mixins: [strategyFormLoadMixin, strategyFormTemplateMixin, strategyFormSubmitMixin],
  components: { SubjectiveWeightsFormPanel, KeyValueEditor, StrategySelectionCard, StrategyControlCard, StrategyAllocatorParamsCard },
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    id: {
      type: String,
      default: ''
    },
    initialTemplateCode: {
      type: String,
      default: ''
    },
    initialSelectorCode: {
      type: String,
      default: ''
    },
    initialControllerCode: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      isEdit: false,
      currentModelId: null,
      form: {
        name: '',
        description: '',
        template_code: '',
        asset_codes: [],
        parameters: {},
        rebalance_frequency: '月',
        // 新增字段
        enable_momentum_selection: false,
        selector_type: '',
        asset_selection_count: 1,
        // 最小历史天数（仅 sharpe/momentum_reversal 选择器需要）
        min_history_days: 260,
        // 波动率阈值重置（仅当模板 schema 声明时生效，默认关闭）
        enable_vol_reset: false,
        vol_reset_threshold: 0.06,
        // 动态选择器/控制器
        selector_code: '',
        selector_parameters: {},
        enable_control: false,
        controller_code: '',
        controller_parameters: {},
        // 原型预设来源（preset_version / preset_applied_at / snapshot 由后端写入）
        preset_code: '',
        preset_version: '',
        preset_applied_at: null,
        asset_selection_snapshot: null
      },
      assetOptions: [],
      submitting: false,
      advancedCollapse: [], // 高级参数折叠状态
      maxWeightDict: {} // 指数编制规则下各资产权重上限（新建/编辑策略-默认资产权重）
    };
  },
  computed: {
    rules() {
      const r = {
        name: [
          { required: true, message: '请输入策略名称', trigger: 'blur' }
        ],
        template_code: [
          { required: true, message: '请选择策略模板', trigger: 'change' }
        ],
        asset_codes: [
          { required: true, message: '请选择资产', trigger: 'change' }
        ],
      };
      if (!this.isManualAllocationTemplate) {
        r.rebalance_frequency = [
          { required: true, message: '请选择调仓频率', trigger: 'change' }
        ];
      }
      return r;
    },
    ...mapState('strategy', ['templateList']),
    /** 仅显示 allocation 类型的模板列表（策略模板下拉） */
    allocationTemplateList() {
      return this.templateList.filter(t => !t.category || t.category === 'allocation');
    },
    /** selection 类型的模板列表（选择器策略下拉） */
    selectionTemplateList() {
      return this.templateList.filter(t => t.category === 'selection');
    },
    /** control 类型的模板列表（控制器策略下拉） */
    controlTemplateList() {
      return this.templateList.filter(t => t.category === 'control');
    },
    /** 当前选中的选择器模板 */
    selectedSelectorTemplate() {
      if (!this.form.selector_code) return null;
      return this.templateList.find(t => t.code === this.form.selector_code);
    },
    /** 当前选择器类型（去掉 sel_ 前缀后的原始类型） */
    selectorType() {
      if (!this.form.selector_code) return '';
      return this.form.selector_code.startsWith('sel_')
        ? this.form.selector_code.slice(4)
        : this.form.selector_code;
    },
    /** 当前选择器是否需要「选择资产数量」参数 */
    selectorNeedsAssetCount() {
      return ['sharpe', 'etf_rotation', 'cross_sectional_momentum'].includes(this.selectorType);
    },
    /** 当前选择器是否需要「最小历史数据要求」参数 */
    selectorNeedsMinHistory() {
      return ['sharpe', 'momentum_reversal'].includes(this.selectorType);
    },
    /** 复合分配器的额外内部选择器模板（排除主选择器已展示的） */
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
      return internalList.slice(1).map(code => {
        return this.templateList.find(t => t.code === 'sel_' + code);
      }).filter(Boolean);
    },
    /** 当前选中的控制器模板 */
    selectedControllerTemplate() {
      if (!this.form.controller_code) return null;
      return this.templateList.find(t => t.code === this.form.controller_code);
    },
    currentTemplate() {
      if (!this.form.template_code) return null;
      return this.templateList.find(t => t.code === this.form.template_code);
    },
    isManualAllocationTemplate() {
      const code = (this.form.template_code || '').toString().toLowerCase();
      return code === 'manual_allocation' || code === 'manual_allocation_strategy';
    },
    /** 打包独立形态策略：选样/赋权/约束/风控全在策略包内，
     *  composition 三层均为 null，不渲染「资产选择策略」与「风险控制策略」
     *  两张卡片；选样数量、分组、风控阈值等全部走模型参数区（core/advanced） */
    isStandaloneTemplate() {
      const tpl = this.currentTemplate;
      return !!tpl && tpl.strategy_form === 'standalone';
    },
    /** 当前预设是否走标签池（决定来源说明的括号内容） */
    isPresetTagPool() {
      const snap = this.form.asset_selection_snapshot;
      if (!snap) return false;
      const mode = String(snap.mode || '').toLowerCase();
      return mode === 'tags' || mode === 'hybrid';
    },
    /** 风险预算目标波动率 */
    isRiskBudgetTargetVolTemplate() {
      return isRiskBudgetTargetVolTemplateCode(this.form.template_code);
    },
    /** 夏普率风险预算策略 */
    isSharpeRiskBudgetTemplate() {
      return isSharpeRiskBudgetTemplateCode(this.form.template_code);
    },
    /** 仅对当前选中的资产汇总权重 */
    manualWeightsSum() {
      if (!this.isManualAllocationTemplate || !this.form.asset_codes || !this.form.asset_codes.length) return null;
      const mw = this.form.parameters.manual_weights;
      if (!mw || typeof mw !== 'object') return null;
      return this.form.asset_codes.reduce((s, c) => s + (Number(mw[c]) || 0), 0);
    },
    /** 已选资产列表 */
    selectedAssetOptions() {
      const codes = this.form.asset_codes || [];
      if (!codes.length) return [];
      return this.assetOptions.filter(a => codes.includes(a.code));
    },
    /** 核心参数（group != 'advanced'） */
    coreParams() {
      if (!this.currentTemplate || !this.currentTemplate.parameters) return [];
      return this.currentTemplate.parameters.filter(p => (p.group || 'core') !== 'advanced');
    },
    /** 高级参数（group == 'advanced'） */
    advancedParams() {
      if (!this.currentTemplate || !this.currentTemplate.parameters) return [];
      return this.currentTemplate.parameters.filter(p => p.group === 'advanced');
    },
    maxLeverageParam() {
      if (this.isManualAllocationTemplate) return 1;
      if (!this.form.parameters) return 4;
      const v = this.form.parameters.max_leverage;
      return (v !== undefined && v !== null && !Number.isNaN(Number(v))) ? Number(v) : 4;
    },
    /** 预设调仓日期与权重列表 */
    presetRebalanceList() {
      let list = this.form.parameters.manual_weight_adjustments;
      if (typeof list === 'string') {
        try { list = list.trim() ? JSON.parse(list) : []; } catch (_) { list = []; }
      }
      if (!Array.isArray(list)) return [];
      return list;
    }
  },
  watch: {
    'form.asset_codes': {
      handler(newCodes) {
        if (!this.isManualAllocationTemplate || !newCodes || !Array.isArray(newCodes)) {
          this.maxWeightDict = {};
          return;
        }
        const mw = this.form.parameters.manual_weights;
        if (typeof mw !== 'object') this.$set(this.form.parameters, 'manual_weights', {});
        const cur = this.form.parameters.manual_weights;
        newCodes.forEach(c => {
          if (cur[c] === undefined) this.$set(cur, c, 0);
        });
        this.maxWeightDict = {};
        Object.keys(cur).forEach(c => {
          if (!newCodes.includes(c)) this.$delete(cur, c);
        });
        if (newCodes.length > 0 && Object.values(cur).every(v => !v || v === 0)) {
          this.$set(cur, newCodes[0], 1);
        }
        const presetList = this.form.parameters.manual_weight_adjustments;
        if (Array.isArray(presetList)) {
          presetList.forEach(adj => {
            if (adj && adj.weights && typeof adj.weights === 'object') {
              newCodes.forEach(c => { if (adj.weights[c] === undefined) this.$set(adj.weights, c, 0); });
              Object.keys(adj.weights).forEach(c => { if (!newCodes.includes(c)) this.$delete(adj.weights, c); });
            }
          });
        }
      },
      deep: true
    },
    id(newVal) {
      if (this.isDialog) {
        this.isEdit = !!newVal;
        this.currentModelId = newVal;
        if (this.isEdit) {
          this.loadModel();
        } else {
          this.resetForm();
        }
      }
    }
  },
  created() {
    const id = this.isDialog ? this.id : this.$route.params.id;
    this.isEdit = !!id;
    if (this.isEdit) {
      this.currentModelId = id;
      this.loadModel();
    } else {
      const templateCode = this.isDialog ? this.initialTemplateCode : this.$route.query.templateId;
      const selectorCode = this.isDialog ? this.initialSelectorCode : '';
      const controllerCode = this.isDialog ? this.initialControllerCode : '';

      if (selectorCode) {
        this.form.selector_code = selectorCode;
        this.form.enable_momentum_selection = true;
        this.form.selector_type = selectorCode;
        this.$store.dispatch('strategy/fetchTemplateList').then(() => {
          this.initSelectorParameters(selectorCode);
        });
      } else if (controllerCode) {
        this.form.enable_control = true;
        this.form.controller_code = controllerCode;
        this.$store.dispatch('strategy/fetchTemplateList').then(() => {
          this.initControllerParameters(controllerCode);
        });
      } else if (templateCode) {
        this.form.template_code = templateCode;
        this.$store.dispatch('strategy/fetchTemplateList').then(() => {
          this.handleTemplateChange(templateCode);
        });
      }
    }
    this.loadInitialData();
  },
  methods: {
    isRiskBudgetTargetVolHiddenTemplateParameter,
    isSubjectiveMonitorHiddenSchemaParameter(name) {
      return checkSubjectiveHiddenSchemaParam(name);
    },
    isSharpeRiskBudgetHiddenSchemaParameter(name) {
      return checkSharpeHiddenSchemaParam(name);
    },

    /** 选择器参数条件可见性判断 */
    isSelectorParamVisible(param) {
      if (!param.condition) return true;
      const condField = param.condition.field;
      const condValue = param.condition.value;
      const currentVal = this.form.selector_parameters[condField];
      return currentVal === condValue;
    },

    /** 分配器参数条件可见性判断 */
    isAllocatorParamVisible(param) {
      if (!param.condition) return true;
      const condField = param.condition.field;
      const condValue = param.condition.value;
      const currentVal = this.form.parameters[condField];
      return currentVal === condValue || String(currentVal) === String(condValue);
    },

    /** 统一参数可见性判断（condition + hidden + 旧模板兼容） */
    isParamShown(param) {
      if (param.hidden) return false;
      if (!this.isAllocatorParamVisible(param)) return false;
      if (this.isManualAllocationTemplate && param.name === 'manual_weights') return false;
      if (param.name === 'risk_budget_both' || param.name === 'risk_budget_single') return false;
      if (this.isRiskBudgetTargetVolTemplate && isRiskBudgetTargetVolHiddenTemplateParameter(param.name)) return false;
      if (this.isSharpeRiskBudgetTemplate && checkSharpeHiddenSchemaParam(param.name)) return false;
      return true;
    },

    /** 分配器参数变更处理（联动约束） */
    handleAllocatorParamChange(param) {
      if (param.name === 'combo_weight_tf') {
        const tf = Number(this.form.parameters.combo_weight_tf) || 0;
        this.$set(this.form.parameters, 'combo_weight_cs', Math.round((1 - tf) * 100) / 100);
      } else if (param.name === 'combo_weight_cs') {
        const cs = Number(this.form.parameters.combo_weight_cs) || 0;
        this.$set(this.form.parameters, 'combo_weight_tf', Math.round((1 - cs) * 100) / 100);
      }
    },

    getOptionValue(option) {
      if (Array.isArray(option)) return option[0];
      return option;
    },

    getOptionLabel(option) {
      if (Array.isArray(option)) return option[1] || option[0];
      return option;
    },

    getParamPrecision(param) {
      const step = param.step;
      if (step !== null && step !== undefined && Number.isInteger(step) && step >= 1) {
        return 0;
      }
      return 4;
    },

    handleMomentumSelectionChange(value) {
      if (!value) {
        this.form.selector_code = '';
        this.form.selector_type = '';
        this.form.selector_parameters = {};
        this.form.asset_selection_count = 1;
      }
    },

    handleControlToggle(value) {
      if (!value) {
        this.form.controller_code = '';
        this.form.controller_parameters = {};
      }
    },

    handleSelectorCodeChange(code) {
      this.form.selector_code = code || '';
      if (!code) {
        this.form.selector_type = '';
        this.form.selector_parameters = {};
        return;
      }
      this.form.selector_type = code;
      this.initSelectorParameters(code);
    },

    initSelectorParameters(code) {
      const tpl = this.templateList.find(t => t.code === code);
      if (!tpl || !tpl.parameters) return;
      const params = {};
      tpl.parameters.forEach(param => {
        const defVal = param.default !== undefined && param.default !== null
          ? param.default
          : (param.default_value !== undefined && param.default_value !== null ? param.default_value : undefined);
        params[param.name] = defVal;
      });
      this.$set(this.form, 'selector_parameters', params);
    },

    handleControllerCodeChange(code) {
      this.form.controller_code = code || '';
      if (!code) {
        this.form.controller_parameters = {};
        return;
      }
      this.initControllerParameters(code);
    },

    initControllerParameters(code) {
      const tpl = this.templateList.find(t => t.code === code);
      if (!tpl || !tpl.parameters) return;
      const params = {};
      tpl.parameters.forEach(param => {
        const defVal = param.default !== undefined && param.default !== null
          ? param.default
          : (param.default_value !== undefined && param.default_value !== null ? param.default_value : undefined);
        params[param.name] = defVal;
      });
      this.$set(this.form, 'controller_parameters', params);
    },

    resetSelectorParameters() {
      if (this.form.selector_code) {
        this.initSelectorParameters(this.form.selector_code);
        this.$message.success('选择器参数已重置为默认值');
      }
    },

    resetControllerParameters() {
      if (this.form.controller_code) {
        this.initControllerParameters(this.form.controller_code);
        this.$message.success('控制器参数已重置为默认值');
      }
    },

    resetForm() {
      this.form = {
        name: '',
        description: '',
        template_code: '',
        asset_codes: [],
        parameters: {},
        rebalance_frequency: '月',
        enable_momentum_selection: false,
        selector_type: '',
        asset_selection_count: 1,
        min_history_days: 260,
        enable_vol_reset: false,
        vol_reset_threshold: 0.06,
        selector_code: '',
        selector_parameters: {},
        enable_control: false,
        controller_code: '',
        controller_parameters: {},
        preset_code: '',
        preset_version: '',
        preset_applied_at: null,
        asset_selection_snapshot: null
      };
      this.presetBaseline = '';
      this.presetModified = false;
      this.presetOutdated = false;
      if (this.$refs.form) {
        this.$refs.form.resetFields();
      }
    },

    removeAsset(code) {
      const index = this.form.asset_codes.indexOf(code);
      if (index > -1) {
        this.form.asset_codes.splice(index, 1);
      }
    },

    ensurePresetRebalanceList() {
      if (!this.form.parameters.manual_weight_adjustments || !Array.isArray(this.form.parameters.manual_weight_adjustments)) {
        this.$set(this.form.parameters, 'manual_weight_adjustments', []);
      }
    },

    addPresetRebalance() {
      this.ensurePresetRebalanceList();
      const codes = this.form.asset_codes || [];
      const weights = {};
      codes.forEach(c => { weights[c] = 0; });
      if (codes.length > 0) weights[codes[0]] = 1;
      this.form.parameters.manual_weight_adjustments.push({
        date: '',
        weights,
        auto_normalize: false
      });
    },

    removePresetRebalance(idx) {
      this.ensurePresetRebalanceList();
      this.form.parameters.manual_weight_adjustments.splice(idx, 1);
    },

    getAssetLabel(code) {
      const asset = this.assetOptions.find(a => a.code === code);
      return asset ? `${asset.code} ${asset.name}` : code;
    },

    subjectiveWeightsEditorLabel(code) {
      const c = String(code || '').trim();
      if (!c) return '';
      const asset = this.assetOptions.find(a => a.code === c);
      if (asset && asset.name && asset.name !== c) return `${asset.name}（${c}）`;
      return c;
    },

    effectiveMaxWeight(code) {
      if (this.isManualAllocationTemplate) return 1;
      const v = this.maxWeightDict[code];
      if (v === undefined || v === null) return 1;
      const n = Number(v);
      if (Number.isNaN(n) || n <= 0) return 1;
      return Math.min(1, n);
    },

    getMaxWeightTooltip(code) {
      const maxVal = this.effectiveMaxWeight(code);
      const maxPct = (maxVal * 100).toFixed(0);
      if (this.isManualAllocationTemplate) {
        return `主观策略不受指数编制规则限制，单资产权重上限 ${maxPct}%。`;
      }
      const fromApi = this.maxWeightDict[code] != null && Number(this.maxWeightDict[code]) >= 0.1;
      if (fromApi) {
        return `指数编制规则：该资产单资产权重上限 ${maxPct}%。右侧「指数上限」即本上限。`;
      }
      return `单资产权重上限 ${maxPct}%（未配置指数编制规则时默认 100%）。`;
    },

    getMaxWeightHint(code) {
      const maxVal = this.effectiveMaxWeight(code);
      const pct = (maxVal * 100).toFixed(0);
      if (this.isManualAllocationTemplate) return `上限 ${pct}%`;
      const fromApi = this.maxWeightDict[code] != null && Number(this.maxWeightDict[code]) >= 0.1;
      return fromApi ? `指数上限 ${pct}%` : `上限 ${pct}%`;
    },

    getParamOptions(param) {
      if (!param.options) {
        return [];
      }
      if (Array.isArray(param.options)) {
        return param.options;
      }
      if (typeof param.options === 'string') {
        return param.options.split(',').map(o => o.trim()).filter(o => o);
      }
      return [];
    },

    getDictPlaceholder(param) {
      if (param.param_type === 'max_weight_dict') {
        return '请输入JSON字符串，如：{"ZZ000001": 0.6, "HSTECH": 0.5}';
      }
      return '请输入JSON字符串，如：{"key": "value"}';
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}

.page-header {
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #303133;
  margin: 0;
}

.page-content {
  max-width: 900px;
}

.strategy-form {
  background: #fff;
}

.strategy-form .el-form-item__label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.form-card {
  margin-bottom: 20px;
}

/* 下拉框与右侧说明图标同一行，避免 100% 宽度把图标挤到下一行 */
.field-row {
  display: flex;
  align-items: center;
}

.field-row__control {
  flex: 1;
  min-width: 0;
}

.field-row__icon {
  flex-shrink: 0;
  margin-left: 6px;
  color: #909399;
  cursor: help;
}

/* 模板描述：受表单内容宽度约束自动换行，不再撑宽下拉面板 */
.template-desc {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}

/* 原型预设来源：应用即快照，与「已调整」「基于旧版预设」两个标记同行 */
.preset-source {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}

.preset-source__flag {
  margin-left: 2px;
}

/* 预设校验结果弹窗：blocking 红 / data 黄 / warning 灰 */
.preset-dialog__summary {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding-bottom: 10px;
  border-bottom: 1px solid #ebeef5;
}

.preset-dialog__name {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}

.preset-dialog__meta {
  font-size: 12px;
  color: #909399;
}

.preset-issue-section {
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: 4px;
  border-left: 3px solid transparent;
}

.preset-issue-section.is-blocking_error {
  background: #fef0f0;
  border-left-color: #f56c6c;
}

.preset-issue-section.is-data_error {
  background: #fdf6ec;
  border-left-color: #e6a23c;
}

.preset-issue-section.is-warning {
  background: #f4f4f5;
  border-left-color: #909399;
}

.preset-issue-section__title {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 6px;
}

.preset-issue + .preset-issue {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #dcdfe6;
}

.preset-issue__msg {
  font-size: 13px;
  color: #303133;
  line-height: 1.6;
}

.preset-issue__hint,
.preset-issue__assets {
  margin-top: 2px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  word-break: break-all;
}

.preset-dialog__ok {
  margin-top: 14px;
  padding: 10px 12px;
  font-size: 13px;
  color: #67c23a;
  background: #f0f9eb;
  border-radius: 4px;
}

.preset-dialog__note {
  margin-top: 14px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

.manual-weights-card .el-card__body {
  padding: 20px 24px;
}

.manual-weights-form-item {
  margin-bottom: 0;
}

.manual-weights-form-item >>> .el-form-item__content {
  margin-left: 0 !important;
  line-height: normal;
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
