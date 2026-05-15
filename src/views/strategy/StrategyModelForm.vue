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
        label-width="120px"
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

          <el-form-item label="算法模板" prop="template_code">
            <el-select
              v-model="form.template_code"
              placeholder="请选择算法模板"
              @change="handleTemplateChange"
              style="width: 100%;"
            >
              <el-option
                v-for="tpl in templateList"
                :key="tpl.code"
                :label="`${tpl.code} - ${tpl.name}`"
                :value="tpl.code"
              >
                <span style="float: left">{{ tpl.code }} - {{ tpl.name }}</span>
                <span style="float: right; color: #8492a6; font-size: 13px">{{ tpl.description }}</span>
              </el-option>
            </el-select>
            <el-tooltip content="选择用于计算资产权重的算法模型，不同模型有不同的风险收益特征和适用场景" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
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
          </el-form-item>

          <el-form-item v-if="!isManualAllocationTemplate" label="调仓频率" prop="rebalance_frequency">
            <el-select v-model="form.rebalance_frequency" placeholder="请选择调仓频率" style="width: 200px;">
              <el-option label="日度" value="日"></el-option>
              <el-option label="周度" value="周"></el-option>
              <el-option label="月度" value="月"></el-option>
              <el-option label="季度" value="季"></el-option>
              <el-option label="年度" value="年"></el-option>
            </el-select>
            <el-tooltip content="组合权重调整的频率，日度表示每个交易日都调仓，月度表示每月第一个交易日调仓，季度表示每季度第一个交易日调仓" placement="top">
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

        <!-- 资产选择策略区域（主观配置策略无动量选择，不展示） -->
        <el-card shadow="never" class="form-card" v-if="!isManualAllocationTemplate">
          <div slot="header" class="card-header">
            <span>资产选择策略</span>
          </div>

          <el-form-item label="动量资产选择">
            <el-switch
                v-model="form.enable_momentum_selection"
                @change="handleMomentumSelectionChange"
            ></el-switch>
            <el-tooltip content="启用后将从候选池中自动筛选动量最强的TopN资产，基于多窗口夏普动量进行筛选，选择风险调整后收益最优的资产" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>

          <template v-if="form.enable_momentum_selection">
            <el-form-item label="选择器类型">
              <el-select
                  v-model="form.selector_type"
                  placeholder="请选择选择器类型"
                  style="width: 100%;"
              >
                <el-option label="动量选择器" value="momentum"></el-option>
                <el-option label="混合动量选择器" value="hybrid"></el-option>
              </el-select>
              <el-tooltip content="动量选择器基于多窗口SHARP动量筛选；混合动量选择器结合动量与反转信号" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
            </el-form-item>

            <el-form-item label="选择资产数量">
              <el-input-number
                  v-model="form.asset_selection_count"
                  :min="1"
                  :max="100"
                  :step="1"
                  controls-position="right"
                  style="width: 200px;"
              ></el-input-number>
              <el-tooltip content="从候选池中选择排名前N的资产，基于综合动量得分排序，得分相同时优先选择短期动量更高的资产" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
              <span style="margin-left: 10px; color: #909399; font-size: 13px;">个（默认：8，范围：1-100）</span>
            </el-form-item>

            <!-- 新增：最小历史数据要求（风险预算目标波动率模板固定 260 天，不展示） -->
            <el-form-item v-if="!isRiskBudgetTargetVolTemplate" label="最小历史数据要求">
              <el-input-number
                  v-model="form.min_history_days"
                  :min="100"
                  :max="500"
                  :step="10"
                  controls-position="right"
                  style="width: 200px;"
              ></el-input-number>
              <el-tooltip content="资产进入候选池的最小交易日数，默认260天，建议≥260天以支持多窗口指标计算（20/60/120/250天）" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
              <span style="margin-left: 10px; color: #909399; font-size: 13px;">天（默认：260，范围：100-500，步长：10）</span>
            </el-form-item>

            <!-- 四因子各 4 档窗口（逗号分隔）；未填则回退到 legacy「动量窗口」同值 -->
            <el-form-item label="MOM 窗口">
              <el-input
                  v-model="form.mom_windows"
                  placeholder="如：20,60,120,250"
                  style="width: 300px;"
              ></el-input>
              <el-tooltip content="简单时序动量 MOM，四个交易日窗口，逗号分隔" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
            </el-form-item>
            <el-form-item label="POSI 窗口">
              <el-input
                  v-model="form.posi_windows"
                  placeholder="如：20,60,120,250"
                  style="width: 300px;"
              ></el-input>
              <el-tooltip content="收益正负差因子 POSI，四个窗口" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
            </el-form-item>
            <el-form-item label="SMOM 窗口">
              <el-input
                  v-model="form.smom_windows"
                  placeholder="如：20,60,120,250"
                  style="width: 300px;"
              ></el-input>
              <el-tooltip content="缩放动量 SMOM，四个窗口" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
            </el-form-item>

            <el-form-item v-if="form.selector_type === 'hybrid'" label="MACD 短期窗">
              <el-input
                  v-model="form.macd_windows"
                  placeholder="如：40,80,120,160"
                  style="width: 300px;"
              ></el-input>
              <el-tooltip content="双均线 MACD 的短期均线窗口（四档），长期均线见下项" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
            </el-form-item>
            <el-form-item v-if="form.selector_type === 'hybrid'" label="MACD 长期窗">
              <el-input-number
                  v-model="form.macd_long_window"
                  :min="20"
                  :max="500"
                  :step="10"
                  controls-position="right"
                  style="width: 200px;"
              ></el-input-number>
              <span style="margin-left: 10px; color: #909399; font-size: 13px;">交易日（默认 250）</span>
            </el-form-item>

            <el-form-item v-if="form.selector_type === 'hybrid'" label="反转窗口">
              <el-input
                  v-model="form.reversal_windows"
                  placeholder="如：10,22"
                  style="width: 200px;"
              ></el-input>
              <el-tooltip content="反转因子为双窗口偏度，固定两个整数（逗号分隔），与日常监控一致" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
            </el-form-item>

            <el-form-item label="兼容：共用动量窗">
              <el-input
                  v-model="form.momentum_windows"
                  placeholder="旧版字段：未单独填 MOM/POSI/SMOM 时作默认"
                  style="width: 320px;"
              ></el-input>
              <el-tooltip content="兼容旧数据。若已填写上方 MOM/POSI/SMOM，可不填此项" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
            </el-form-item>

            <!-- 新增：并列决胜窗口（风险预算目标波动率模板固定 22 天，不展示） -->
            <el-form-item v-if="!isRiskBudgetTargetVolTemplate" label="并列决胜窗口">
              <el-input-number
                  v-model="form.tie_break_window"
                  :min="5"
                  :max="260"
                  :step="1"
                  controls-position="right"
                  style="width: 200px;"
              ></el-input-number>
              <el-tooltip content="综合得分相同时，优先选择该窗口动量更高的资产，默认22天（短期动量），用于处理并列情况" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
              <span style="margin-left: 10px; color: #909399; font-size: 13px;">天（默认：22，范围：5-260）</span>
            </el-form-item>

          </template>
        </el-card>

        <!-- 波动率阈值重置：风险预算目标波动率模板固定阈值 0.06，不展示本卡 -->
        <el-card shadow="never" class="form-card" v-if="!isRiskBudgetTargetVolTemplate">
          <div slot="header" class="card-header">
            <span>波动率阈值重置</span>
          </div>
          <div class="vol-reset-hint" style="margin-bottom: 12px; color: #909399; font-size: 13px;">
            所有策略均可选择并实际执行：当组合波动率超过阈值时将按比例缩放权重以控制风险。
          </div>
          <el-form-item label="启用波动率阈值重置">
            <el-switch v-model="form.enable_vol_reset"></el-switch>
            <el-tooltip content="启用后，当组合波动率超过设定阈值时将触发权重重置（所有策略均会实际执行）" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>
          <el-form-item v-if="form.enable_vol_reset" label="波动率重置阈值">
            <el-input-number
              v-model="form.vol_reset_threshold"
              :min="0.01"
              :max="0.5"
              :step="0.01"
              :precision="2"
              controls-position="right"
              style="width: 200px;"
            ></el-input-number>
            <span style="margin-left: 10px; color: #909399; font-size: 13px;">（默认 0.06，即 6%）</span>
          </el-form-item>
        </el-card>

        <el-card shadow="never" class="form-card" v-if="currentTemplate">
          <div slot="header" class="card-header">
            <span>模型参数</span>
            <el-button type="text" size="small" @click="resetParameters">重置为默认值</el-button>
          </div>

          <el-form-item
            v-for="param in currentTemplate.parameters"
            :key="param.name"
            :label="param.label || param.name"
            v-show="!(isManualAllocationTemplate && param.name === 'manual_weights') && param.name !== 'risk_budget_both' && param.name !== 'risk_budget_single' && !(isRiskBudgetTargetVolTemplate && isRiskBudgetTargetVolHiddenTemplateParameter(param.name)) && !(isManualAllocationTemplate && isSubjectiveMonitorHiddenSchemaParameter(param.name))"
          >
            <!-- 数字类型 -->
            <el-input-number
              v-if="param.param_type === 'number'"
              v-model="form.parameters[param.name]"
              :min="param.min_value !== null && param.min_value !== undefined ? param.min_value : undefined"
              :max="param.max_value !== null && param.max_value !== undefined ? param.max_value : undefined"
              :step="param.step || 0.01"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
            <span v-if="param.param_type === 'number'" style="margin-left: 10px; color: #909399; font-size: 13px;">
              <span v-if="param.default !== null && param.default !== undefined">默认：{{ param.default }}</span>
              <span v-if="param.min_value !== null && param.min_value !== undefined || param.max_value !== null && param.max_value !== undefined">
                <span v-if="param.default !== null && param.default !== undefined">，</span>
                范围：{{ param.min_value !== null && param.min_value !== undefined ? param.min_value : '无下限' }}-{{ param.max_value !== null && param.max_value !== undefined ? param.max_value : '无上限' }}
              </span>
              <span v-if="param.step">，步长：{{ param.step }}</span>
            </span>
            
            <!-- 滑块类型 -->
            <div v-else-if="param.param_type === 'slider'" style="display: flex; align-items: center;">
              <el-slider
                v-model="form.parameters[param.name]"
                :min="param.min_value !== null && param.min_value !== undefined ? param.min_value : 0"
                :max="param.max_value !== null && param.max_value !== undefined ? param.max_value : 100"
                :step="param.step || 1"
                style="width: 200px; margin-right: 15px;"
                show-input
              ></el-slider>
              <span style="margin-left: 10px; color: #909399; font-size: 13px;">
                <span v-if="param.default !== null && param.default !== undefined">默认：{{ param.default }}</span>
                <span v-if="param.min_value !== null && param.min_value !== undefined || param.max_value !== null && param.max_value !== undefined">
                  <span v-if="param.default !== null && param.default !== undefined">，</span>
                  范围：{{ param.min_value !== null && param.min_value !== undefined ? param.min_value : 0 }}-{{ param.max_value !== null && param.max_value !== undefined ? param.max_value : 100 }}
                </span>
                <span v-if="param.step">，步长：{{ param.step }}</span>
              </span>
            </div>
            
            <!-- 下拉选择类型 -->
            <el-select
              v-else-if="param.param_type === 'select'"
              v-model="form.parameters[param.name]"
              placeholder="请选择"
              style="width: 200px;"
            >
              <el-option
                v-for="option in getParamOptions(param)"
                :key="option"
                :label="option"
                :value="option"
              ></el-option>
            </el-select>
            
            <!-- 复选框类型 -->
            <el-switch
              v-else-if="param.param_type === 'boolean'"
              v-model="form.parameters[param.name]"
            ></el-switch>
            
            <!-- 文本类型 -->
            <el-input
              v-else-if="param.param_type === 'string'"
              v-model="form.parameters[param.name]"
              placeholder="请输入"
              style="width: 200px;"
            ></el-input>
            
            <!-- 字典类型 -->
            <el-input
              v-else-if="param.param_type === 'dict' || param.param_type === 'max_weight_dict'"
              type="textarea"
              v-model="form.parameters[param.name]"
              :rows="3"
              :placeholder="getDictPlaceholder(param)"
              style="width: 100%; max-width: 500px;"
            ></el-input>
            
            <!-- 默认使用数字输入框（向下兼容） -->
            <el-input-number
              v-else
              v-model="form.parameters[param.name]"
              :min="param.min_value !== null && param.min_value !== undefined ? param.min_value : undefined"
              :max="param.max_value !== null && param.max_value !== undefined ? param.max_value : undefined"
              :step="param.step || 0.01"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
            
            <el-tooltip v-if="param.description" :content="param.description" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
            <span v-if="!param.description" style="margin-left: 10px; color: #909399; font-size: 13px;">
              {{ param.description || '' }}
            </span>
          </el-form-item>
        </el-card>

        <el-form-item>
          <el-button type="primary" @click="handleSubmit" :loading="submitting">
            {{ submitting ? '保存中...' : '保存策略' }}
          </el-button>
          <el-button @click="handleCancel">取消</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import { getMaxWeightsByCodes } from '@/api/strategy';
import {
  isRiskBudgetTargetVolTemplateCode,
  RISK_BUDGET_TARGET_VOL_FIXED,
  isRiskBudgetTargetVolHiddenTemplateParameter,
  isManualAllocationTemplateCode,
  SUBJECTIVE_MONITOR_FIXED_PARAMETERS,
  isSubjectiveMonitorHiddenSchemaParameter as checkSubjectiveHiddenSchemaParam
} from '@/utils/strategyTemplateFlags';
import { normalizeWeightsToTwoDecimalSumOne } from '@/utils/subjectiveWeights';
import SubjectiveWeightsFormPanel from '@/components/SubjectiveWeightsFormPanel.vue';

export default {
  name: 'StrategyModelForm',
  components: { SubjectiveWeightsFormPanel },
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
        // 新增：动量资产选择相关参数（与编制规则一致）
        min_history_days: 260,
        momentum_windows: '20,60,120,250',
        mom_windows: '20,60,120,250',
        posi_windows: '20,60,120,250',
        smom_windows: '20,60,120,250',
        macd_windows: '40,80,120,160',
        macd_long_window: 250,
        reversal_windows: '10,22',
        tie_break_window: 22,
        // 波动率阈值重置（所有策略可选）
        enable_vol_reset: true,
        vol_reset_threshold: 0.06
      },
      assetOptions: [],
      submitting: false,
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
          { required: true, message: '请选择算法模板', trigger: 'change' }
        ],
        asset_codes: [
          { required: true, message: '请选择资产', trigger: 'change' }
        ]
      };
      if (!this.isManualAllocationTemplate) {
        r.rebalance_frequency = [
          { required: true, message: '请选择调仓频率', trigger: 'change' }
        ];
      }
      return r;
    },
    ...mapState('strategy', ['templateList']),
    currentTemplate() {
      if (!this.form.template_code) return null;
      return this.templateList.find(t => t.code === this.form.template_code);
    },
    isManualAllocationTemplate() {
      const code = (this.form.template_code || '').toString().toLowerCase();
      return code === 'manual_allocation' || code === 'manual_allocation_strategy';
    },
    /** 风险预算目标波动率：最小历史、波动重置阈值、回看期、并列决胜窗口固定，不在界面编辑 */
    isRiskBudgetTargetVolTemplate() {
      return isRiskBudgetTargetVolTemplateCode(this.form.template_code);
    },
    /** 仅对当前选中的资产（form.asset_codes）汇总权重，与保存校验一致 */
    manualWeightsSum() {
      if (!this.isManualAllocationTemplate || !this.form.asset_codes || !this.form.asset_codes.length) return null;
      const mw = this.form.parameters.manual_weights;
      if (!mw || typeof mw !== 'object') return null;
      return this.form.asset_codes.reduce((s, c) => s + (Number(mw[c]) || 0), 0);
    },
    maxLeverageParam() {
      if (this.isManualAllocationTemplate) return 1;
      if (!this.form.parameters) return 4;
      const v = this.form.parameters.max_leverage;
      return (v !== undefined && v !== null && !Number.isNaN(Number(v))) ? Number(v) : 4;
    },
    /** 预设调仓日期与权重列表（与回测 manual_weight_adjustments 格式一致） */
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
        // 主观策略不受指数编制规则限制，不拉取上限
        this.maxWeightDict = {};
        Object.keys(cur).forEach(c => {
          if (!newCodes.includes(c)) this.$delete(cur, c);
        });
        if (newCodes.length > 0 && Object.values(cur).every(v => !v || v === 0)) {
          this.$set(cur, newCodes[0], 1);
        }
        // 同步预设调仓日的 weights 键：新增资产补 0，移除资产删键
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
      const templateCode = this.isDialog ? this.initialTemplateCode : this.$route.query.templateId; // 兼容之前的逻辑，虽然可能叫 templateId 但存的是 code
      if (templateCode) {
        this.form.template_code = templateCode;
        // 等待模板列表加载完成后初始化参数
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

    handleMomentumSelectionChange(value) {
      if (!value) {
        // 取消勾选时重置相关字段
        this.form.selector_type = '';
        this.form.asset_selection_count = 1;
        this.form.min_history_days = 260;
        this.form.momentum_windows = '20,60,120,250';
        this.form.mom_windows = '20,60,120,250';
        this.form.posi_windows = '20,60,120,250';
        this.form.smom_windows = '20,60,120,250';
        this.form.macd_windows = '40,80,120,160';
        this.form.macd_long_window = 250;
        this.form.reversal_windows = '10,22';
        this.form.tie_break_window = 22;
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
        // 新增字段重置
        enable_momentum_selection: false,
        selector_type: '',
        asset_selection_count: 1,
        // 新增：动量资产选择相关参数重置（与编制规则一致）
        min_history_days: 260,
        momentum_windows: '20,60,120,250',
        mom_windows: '20,60,120,250',
        posi_windows: '20,60,120,250',
        smom_windows: '20,60,120,250',
        macd_windows: '40,80,120,160',
        macd_long_window: 250,
        reversal_windows: '10,22',
        tie_break_window: 22,
        enable_vol_reset: true,
        vol_reset_threshold: 0.06
      };
      if (this.$refs.form) {
        this.$refs.form.resetFields();
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
          // 新增字段加载
          enable_momentum_selection: model.enable_momentum_selection || false,
          // 兼容处理：将旧的选择器类型映射为 momentum（后端只支持 momentum）
          selector_type: (() => {
            const selectorType = model.selector_type || '';
            return (selectorType === 'reversal' || selectorType === 'momentum_reversal') ? 'momentum' : selectorType;
          })(),
          asset_selection_count: model.asset_selection_count || 1,
          // 新增：动量资产选择相关参数加载
          min_history_days: model.min_history_days !== undefined ? model.min_history_days : 260,
          momentum_windows: model.momentum_windows || '20,60,120,250',
          mom_windows: model.mom_windows || model.momentum_windows || '20,60,120,250',
          posi_windows: model.posi_windows || model.momentum_windows || '20,60,120,250',
          smom_windows: model.smom_windows || model.momentum_windows || '20,60,120,250',
          macd_windows: model.macd_windows || '40,80,120,160',
          macd_long_window: model.macd_long_window !== undefined && model.macd_long_window !== null ? model.macd_long_window : 250,
          reversal_windows: model.reversal_windows || '10,22',
          tie_break_window: model.tie_break_window !== undefined ? model.tie_break_window : 22,
          // 波动率阈值重置（从 parameters 读取，兼容旧数据）
          enable_vol_reset: (model.parameters && model.parameters.enable_vol_reset !== undefined) ? model.parameters.enable_vol_reset : true,
          vol_reset_threshold: (model.parameters && model.parameters.vol_reset_threshold !== undefined) ? model.parameters.vol_reset_threshold : 0.06
        };
        if (isRiskBudgetTargetVolTemplateCode(model.template_code)) {
          this.form.min_history_days = RISK_BUDGET_TARGET_VOL_FIXED.min_history_days;
          this.form.tie_break_window = RISK_BUDGET_TARGET_VOL_FIXED.tie_break_window;
          this.form.vol_reset_threshold = RISK_BUDGET_TARGET_VOL_FIXED.vol_reset_threshold;
          this.form.enable_vol_reset = RISK_BUDGET_TARGET_VOL_FIXED.enable_vol_reset;
          this.$set(this.form.parameters, 'lookback_days', RISK_BUDGET_TARGET_VOL_FIXED.lookback_days);
        } else if (isManualAllocationTemplateCode(model.template_code)) {
          this.applySubjectiveMonitorFixedToForm();
        }
      } catch (error) {
        this.$message.error('加载策略数据失败');
        this.$router.back();
      }
    },
    // 兼容后端返回 default_value（模板列表来自 DB）或 default（schema 接口）
    getParamDefault(param) {
      const v = param.default !== undefined && param.default !== null ? param.default : param.default_value;
      return v;
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
        if (isRiskBudgetTargetVolTemplateCode(templateCode)) {
          this.$set(this.form.parameters, 'lookback_days', RISK_BUDGET_TARGET_VOL_FIXED.lookback_days);
          this.form.min_history_days = RISK_BUDGET_TARGET_VOL_FIXED.min_history_days;
          this.form.tie_break_window = RISK_BUDGET_TARGET_VOL_FIXED.tie_break_window;
          this.form.vol_reset_threshold = RISK_BUDGET_TARGET_VOL_FIXED.vol_reset_threshold;
          this.form.enable_vol_reset = RISK_BUDGET_TARGET_VOL_FIXED.enable_vol_reset;
        }
        // 主观配置：无周期性调仓，仅按预设日调仓；初始化默认资产权重并拉取指数编制上限
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
          this.applySubjectiveMonitorFixedToForm();
        }
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
      this.form.momentum_windows = '20,60,120,250';
      this.form.mom_windows = '20,60,120,250';
      this.form.posi_windows = '20,60,120,250';
      this.form.smom_windows = '20,60,120,250';
      this.form.macd_windows = '40,80,120,160';
      this.form.macd_long_window = 250;
      this.form.reversal_windows = '10,22';
      this.form.tie_break_window = 22;
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
    /** 将后端返回的日期（YYYYMMDD 或 YYYY-MM-DD）转为 el-date-picker 需要的 YYYY-MM-DD */
    normalizeDateForPicker(val) {
      if (!val || typeof val !== 'string') return val;
      const s = String(val).replace(/-/g, '').trim().slice(0, 8);
      if (s.length === 8 && /^\d{8}$/.test(s)) {
        return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
      }
      return val;
    },
    getAssetLabel(code) {
      const asset = this.assetOptions.find(a => a.code === code);
      return asset ? `${asset.code} ${asset.name}` : code;
    },
    /** 与日常监控主观编辑一致：名称（代码） */
    subjectiveWeightsEditorLabel(code) {
      const c = String(code || '').trim();
      if (!c) return '';
      const asset = this.assetOptions.find(a => a.code === c);
      if (asset && asset.name && asset.name !== c) return `${asset.name}（${c}）`;
      return c;
    },
    /** 指数编制规则下该资产单资产权重上限；主观策略不受限制，恒为 100% */
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
    // 获取参数的选项列表
    getParamOptions(param) {
      if (!param.options) {
        return [];
      }
      // 如果options是数组，直接返回
      if (Array.isArray(param.options)) {
        return param.options;
      }
      // 如果options是字符串，按逗号分割
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

          // 所有策略均写入波动率阈值重置参数，供回测时使用
          submitParameters.enable_vol_reset = this.form.enable_vol_reset;
          submitParameters.vol_reset_threshold = this.form.vol_reset_threshold;
          if (this.isRiskBudgetTargetVolTemplate) {
            submitParameters.enable_vol_reset = RISK_BUDGET_TARGET_VOL_FIXED.enable_vol_reset;
            submitParameters.vol_reset_threshold = RISK_BUDGET_TARGET_VOL_FIXED.vol_reset_threshold;
            submitParameters.lookback_days = RISK_BUDGET_TARGET_VOL_FIXED.lookback_days;
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

          const modelData = {
            name: this.form.name,
            description: this.form.description,
            template_code: this.form.template_code,
            asset_codes: this.form.asset_codes,
            parameters: submitParameters,
            rebalance_frequency: this.form.rebalance_frequency,
            // 新增字段：资产选择策略相关
            enable_momentum_selection: this.form.enable_momentum_selection,
            selector_type: this.form.enable_momentum_selection ? this.form.selector_type : '',
            asset_selection_count: this.form.enable_momentum_selection ? this.form.asset_selection_count : 1,
            // 新增：动量资产选择相关参数提交
            min_history_days: this.form.enable_momentum_selection
              ? (this.isRiskBudgetTargetVolTemplate ? RISK_BUDGET_TARGET_VOL_FIXED.min_history_days : this.form.min_history_days)
              : 260,
            momentum_windows: this.form.enable_momentum_selection ? this.form.momentum_windows : '20,60,120,250',
            mom_windows: this.form.enable_momentum_selection ? (this.form.mom_windows || this.form.momentum_windows) : undefined,
            posi_windows: this.form.enable_momentum_selection ? (this.form.posi_windows || this.form.momentum_windows) : undefined,
            smom_windows: this.form.enable_momentum_selection ? (this.form.smom_windows || this.form.momentum_windows) : undefined,
            macd_windows: this.form.enable_momentum_selection && this.form.selector_type === 'hybrid' ? (this.form.macd_windows || '40,80,120,160') : undefined,
            macd_long_window: this.form.enable_momentum_selection && this.form.selector_type === 'hybrid' ? this.form.macd_long_window : undefined,
            reversal_windows: this.form.enable_momentum_selection && this.form.selector_type === 'hybrid' ? (this.form.reversal_windows || '10,22') : undefined,
            tie_break_window: this.form.enable_momentum_selection
              ? (this.isRiskBudgetTargetVolTemplate ? RISK_BUDGET_TARGET_VOL_FIXED.tie_break_window : this.form.tie_break_window)
              : 22
          };
          if (this.isManualAllocationTemplate) {
            modelData.enable_momentum_selection = false;
            modelData.selector_type = '';
            modelData.asset_selection_count = 1;
            modelData.min_history_days = 260;
            modelData.momentum_windows = '20,60,120,250';
            modelData.mom_windows = '20,60,120,250';
            modelData.posi_windows = '20,60,120,250';
            modelData.smom_windows = '20,60,120,250';
            modelData.macd_windows = '40,80,120,160';
            modelData.macd_long_window = 250;
            modelData.reversal_windows = '10,22';
            modelData.tie_break_window = 22;
          }

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
            this.$router.push('/strategy/model');
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

.form-card {
  margin-bottom: 20px;
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
</style>