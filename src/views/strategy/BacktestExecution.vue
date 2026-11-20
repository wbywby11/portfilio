<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">回测执行</h2>
    </div>

    <div class="page-content">
      <el-card shadow="never">
        <div slot="header" class="card-header">
          <span>回测配置</span>
        </div>

        <el-form :model="form" :rules="rules" ref="form" label-width="120px" style="max-width: 900px;">
          <!-- 回测模式 -->
          <el-form-item>
            <span slot="label">回测模式
              <el-tooltip content="单策略回测：查看单个策略或组合的完整回测结果；多策略对比：同时运行2-10个策略/组合" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <el-radio-group v-model="form.backtest_mode">
              <el-radio-button label="single">单策略回测</el-radio-button>
              <el-radio-button label="multi">多策略对比</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <!-- 策略/组合选择 -->
          <el-form-item prop="strategy_ids">
            <span slot="label">选择策略
              <el-tooltip content="选择要回测的策略模型或投资组合，多策略对比模式下需要选择2-10个" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <!-- 单策略模式：分组下拉 -->
            <el-select
              v-if="form.backtest_mode === 'single'"
              v-model="form.strategy_ids"
              placeholder="请选择策略或组合"
              style="width: 100%;"
              @change="handleStrategyChange"
            >
              <el-option-group label="策略模型">
                <el-option
                  v-for="strategy in strategyList"
                  :key="strategy.id"
                  :label="`${strategy.name} (${strategy.template_code})`"
                  :value="strategy.id"
                >
                  <span style="float: left">{{ strategy.name }}</span>
                  <span style="float: right; color: #8492a6; font-size: 13px">
                    {{ strategy.template_code }}
                    <el-tag
                      :type="getStatusTagType(strategy.status)"
                      size="mini"
                      style="margin-left: 4px;"
                    >
                      {{ strategy.status || '草稿' }}
                    </el-tag>
                  </span>
                </el-option>
              </el-option-group>
              <el-option-group v-if="portfolioList.length > 0" label="投资组合">
                <el-option
                  v-for="p in portfolioList"
                  :key="`portfolio:${p.id}`"
                  :label="`${p.name}（组合）`"
                  :value="`portfolio:${p.id}`"
                >
                  <span style="float: left">{{ p.name }}</span>
                  <span style="float: right; color: #8492a6; font-size: 13px">
                    {{ (p.sub_strategies || []).length }}个子策略
                    <el-tag size="mini" type="success" style="margin-left: 4px;">组合</el-tag>
                  </span>
                </el-option>
              </el-option-group>
            </el-select>
            <!-- 多策略模式 - 使用多选框，策略+组合分组显示 -->
            <div v-else style="width: 100%;">
              <el-checkbox-group v-model="form.strategy_ids" @change="handleStrategyChange" style="width: 100%;">
                <div style="max-height: 360px; overflow-y: auto; border: 1px solid #DCDFE6; border-radius: 4px; padding: 10px;">
                  <!-- 策略模型分组 -->
                  <div style="font-weight: 600; color: #606266; margin-bottom: 8px; font-size: 13px;">策略模型</div>
                  <el-checkbox
                    v-for="(strategy, index) in strategyList"
                    :key="strategy.id"
                    :label="strategy.id"
                    style="display: block; margin-bottom: 10px; padding: 8px;"
                    :style="{'border-bottom': index < strategyList.length - 1 ? '1px solid #F0F0F0' : 'none'}"
                  >
                    <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                      <span style="flex: 1; font-weight: 500;">{{ strategy.name }}</span>
                      <span style="color: #8492a6; font-size: 12px; margin-right: 8px;">
                        {{ strategy.template_code }}
                      </span>
                      <el-tag
                        :type="getStatusTagType(strategy.status)"
                        size="mini"
                      >
                        {{ strategy.status || '草稿' }}
                      </el-tag>
                    </div>
                  </el-checkbox>
                  <!-- 投资组合分组 -->
                  <template v-if="portfolioList.length > 0">
                    <div style="border-top: 2px solid #E4E7ED; margin-top: 8px; padding-top: 10px; font-weight: 600; color: #606266; margin-bottom: 8px; font-size: 13px;">投资组合</div>
                    <el-checkbox
                      v-for="(p, index) in portfolioList"
                      :key="`portfolio:${p.id}`"
                      :label="`portfolio:${p.id}`"
                      style="display: block; margin-bottom: 10px; padding: 8px;"
                      :style="{'border-bottom': index < portfolioList.length - 1 ? '1px solid #F0F0F0' : 'none'}"
                    >
                      <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                        <span style="flex: 1; font-weight: 500;">{{ p.name }}</span>
                        <span style="color: #8492a6; font-size: 12px; margin-right: 8px;">
                          {{ (p.sub_strategies || []).length }}个子策略
                        </span>
                        <el-tag size="mini" type="success">组合</el-tag>
                      </div>
                    </el-checkbox>
                  </template>
                </div>
              </el-checkbox-group>
            </div>
            <div v-if="strategyList.length === 0 && portfolioList.length === 0" style="margin-top: 10px;">
              <el-alert
                title="提示"
                type="warning"
                :closable="false"
                show-icon
              >
                暂无可用策略或组合，请先创建策略模型或投资组合
              </el-alert>
            </div>
            <!-- 多策略模式下显示已选择数量 -->
            <div v-else-if="form.backtest_mode === 'multi'" style="margin-top: 10px;">
              <span v-if="selectedStrategyCount > 0" style="color: #409EFF; font-size: 13px; font-weight: 500;">
                已选择 {{ selectedStrategyCount }} 项
                <span v-if="selectedStrategyCount < 2" style="color: #F56C6C; margin-left: 10px;">
                  （至少需要选择2项）
                </span>
                <span v-else-if="selectedStrategyCount > 10" style="color: #F56C6C; margin-left: 10px;">
                  （最多只能选择10项）
                </span>
              </span>
            </div>
          </el-form-item>

          <!-- 多策略对比 -->

          <!-- 主观配置策略：只读展示策略模型预设的杠杆、权重初始化与预设调仓日 -->
          <template v-if="form.backtest_mode === 'single' && isManualAllocationStrategy">
            <el-form-item label="杠杆上限">
              <span class="preset-inline-value">{{ manualPreset.maxLeverage.toFixed(1) }} 倍（{{ (manualPreset.maxLeverage * 100).toFixed(0) }}%）</span>
              <span class="preset-inline-hint">来自策略模型，回测按模型预设执行；如需调整请编辑策略模型</span>
            </el-form-item>
            <el-form-item label="权重初始化">
              <el-card shadow="never" class="preset-card">
                <div slot="header" class="preset-card-header">
                  <i class="el-icon-s-operation"></i> 权重初始化（策略模型预设）
                </div>
                <div class="preset-desc">
                  回测在首个交易日按该权重建仓；权重来自策略模型配置，回测页不单独配置。
                </div>
                <div v-if="manualWeightRows.length > 0" class="preset-weight-grid">
                  <div v-for="row in manualWeightRows" :key="row.code" class="preset-weight-item">
                    <span class="preset-weight-label" :title="row.label">{{ row.label }}</span>
                    <span class="preset-weight-value">{{ row.percent }}</span>
                  </div>
                </div>
                <div v-else class="preset-empty">
                  策略模型未配置权重初始化，请先在策略模型「主观配置权重」中配置后再回测。
                </div>
                <div v-if="manualWeightRows.length > 0" class="preset-sum" :class="manualWeightSumClass">
                  权重和：{{ manualWeightSumPercent }}
                  <span class="preset-sum-hint">（上限 {{ (manualPreset.maxLeverage * 100).toFixed(0) }}%）</span>
                </div>
              </el-card>
            </el-form-item>
            <el-form-item label="预设调仓日期与权重">
              <el-card shadow="never" class="preset-card preset-card-date">
                <div slot="header" class="preset-card-header preset-card-header-date">
                  <i class="el-icon-date"></i> 预设调仓日期与权重（策略模型预设）
                </div>
                <div class="preset-desc">
                  主观策略不设周期性调仓，仅在下列日期按预设权重重配；未预设调仓日时，回测按权重初始化建仓并全周期持有。
                </div>
                <SubjectiveWeightsMatrixTable
                  v-if="manualPreset.adjustments.length > 0"
                  readonly
                  :asset-codes="(selectedStrategyInfo && selectedStrategyInfo.asset_codes) || []"
                  :resolve-label="resolveSingleAssetLabel"
                  :adjustments="manualPreset.adjustments"
                  :max-leverage="manualPreset.maxLeverage"
                />
                <div v-else class="preset-empty">
                  策略模型未预设调仓日，回测将按权重初始化建仓并全周期持有。
                </div>
              </el-card>
            </el-form-item>
          </template>

          <!-- 多策略对比：只读展示各主观策略模型预设的权重与预设调仓日 -->
          <template v-if="form.backtest_mode === 'multi' && selectedStrategiesWithManual.length > 0">
            <el-form-item label="主观策略预设">
              <el-card shadow="never" class="preset-card preset-card-date">
                <div slot="header" class="preset-card-header preset-card-header-date">
                  <i class="el-icon-date"></i> 主观策略的权重初始化与预设调仓日（策略模型预设）
                </div>
                <div class="preset-desc">
                  下列内容来自各策略模型配置，回测按模型预设执行；如需调整请编辑对应策略模型。
                </div>
                <el-collapse v-model="multiPresetActiveNames">
                  <el-collapse-item
                    v-for="s in selectedStrategiesWithManual"
                    :key="s.id"
                    :name="s.id"
                  >
                    <template slot="title">
                      <span style="font-weight: 500;">{{ s.name || s.id }}</span>
                    </template>
                    <div class="preset-block">
                      <div class="preset-block-title">权重初始化</div>
                      <div v-if="getMultiPresetWeightRows(s).length > 0" class="preset-weight-grid">
                        <div v-for="row in getMultiPresetWeightRows(s)" :key="'init-' + row.code" class="preset-weight-item">
                          <span class="preset-weight-label" :title="row.label">{{ row.label }}</span>
                          <span class="preset-weight-value">{{ row.percent }}</span>
                        </div>
                      </div>
                      <div v-else class="preset-empty">该策略模型未配置权重初始化。</div>
                      <div v-if="getMultiPresetWeightRows(s).length > 0" class="preset-sum" :class="getMultiPresetWeightSumClass(s)">
                        权重和：{{ getMultiPresetWeightSumPercent(s) }}
                        <span class="preset-sum-hint">（上限 {{ (getMultiPreset(s).maxLeverage * 100).toFixed(0) }}%）</span>
                      </div>
                    </div>
                    <div class="preset-block">
                      <div class="preset-block-title">预设调仓日期与权重</div>
                      <SubjectiveWeightsMatrixTable
                        v-if="getMultiPreset(s).adjustments.length > 0"
                        readonly
                        :asset-codes="s.asset_codes || []"
                        :resolve-label="(code) => resolveMultiAssetLabel(s, code)"
                        :adjustments="getMultiPreset(s).adjustments"
                        :max-leverage="getMultiPreset(s).maxLeverage"
                      />
                      <div v-else class="preset-empty">未预设调仓日，回测按权重初始化建仓并全周期持有。</div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </el-card>
            </el-form-item>
          </template>

          <!-- 回测时间 -->
          <el-form-item prop="date_range">
            <span slot="label">回测时间
              <el-tooltip content="回测的时间区间，系统将从开始日期到结束日期进行模拟交易" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <el-date-picker
              v-model="form.date_range"
              type="daterange"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              style="width: 100%;"
            ></el-date-picker>
          </el-form-item>

          <!-- 交易成本 -->
          <el-divider content-position="left">交易成本</el-divider>
          
          <el-form-item prop="commission_rate">
            <span slot="label">手续费率
              <el-tooltip content="交易手续费率，默认 0（不计成本），包含买卖双向成本；范围0-0.01，步长0.0001" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <el-input-number
              v-model="form.commission_rate"
              :min="0"
              :max="0.01"
              :step="0.0001"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
          </el-form-item>

          <el-form-item prop="slippage">
            <span slot="label">滑点
              <el-tooltip content="市场冲击成本（滑点），默认 0（不计成本），用于模拟大额交易对价格的影响；范围0-0.01，步长0.0001" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <el-input-number
              v-model="form.slippage"
              :min="0"
              :max="0.01"
              :step="0.0001"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
          </el-form-item>

          <!-- 操作按钮 -->
          <el-form-item>
            <el-tooltip :disabled="!backtestBlocked" :content="backtestBlockedTip" placement="top">
              <span class="execute-btn-wrap">
                <el-button
                  type="primary"
                  @click="handleExecute"
                  :loading="executing"
                  :disabled="backtestBlocked"
                  size="medium"
                >
                  <i class="el-icon-video-play"></i> {{ executing ? '回测中...' : '执行回测' }}
                </el-button>
              </span>
            </el-tooltip>
            <el-button @click="handleReset" size="medium">重置</el-button>
            <el-button @click="handleViewHistory" size="medium">历史记录</el-button>
            <div v-if="backtestBlocked" class="backtest-gate-tip">
              <i class="el-icon-warning-outline"></i> {{ backtestBlockedTip }}
            </div>
          </el-form-item>
        </el-form>

        <!-- 提示信息 -->
        <el-alert
          v-if="!executing && !backtestResults"
          title="请配置回测参数后点击执行回测"
          type="info"
          :closable="false"
          show-icon
          style="margin-top: 20px;"
        ></el-alert>

        <!-- 进度框被收起后保留一条横幅，随时可回到进度 -->
        <div v-if="executing && progressUserClosed" class="backtest-progress-bar">
          <i class="el-icon-loading"></i>
          <span class="backtest-progress-bar__text">{{ progressBannerText }}</span>
          <el-button type="text" size="mini" @click="reopenProgress">查看进度</el-button>
        </div>
      </el-card>

      <!-- 回测结果展示 -->
      <backtest-result
        v-if="backtestResults"
        :results="backtestResults"
        :mode="form.backtest_mode"
        :config="form"
        :model-id="backtestModelId"
      ></backtest-result>

      <!-- 策略多维验证：敏感度 / 情景推演 / 鲁棒性（单策略模型，按上方区间独立重跑） -->
      <strategy-analysis-panel
        v-if="form.backtest_mode === 'single'"
        :strategy="selectedStrategyInfo"
        :is-portfolio="isSelectedPortfolio"
        :date-range="form.date_range"
        :initial-cash="form.initial_cash"
      ></strategy-analysis-panel>

      <!-- 回测进度：与日常监控跑批共用同一张任务表与同一个进度面板 -->
      <el-dialog
        :title="progressDialogTitle"
        :visible.sync="progressDialogVisible"
        width="480px"
        :close-on-click-modal="false"
        append-to-body
        @close="progressUserClosed = true"
      >
        <task-progress-panel :task="progressTask"></task-progress-panel>
        <div v-if="!progressTask" class="backtest-progress-wait">正在启动回测任务…</div>
        <span slot="footer">
          <el-button v-if="executing" size="small" @click="progressDialogVisible = false">后台运行</el-button>
          <el-button v-else type="primary" size="small" @click="progressDialogVisible = false">关闭</el-button>
        </span>
      </el-dialog>



    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';
import BacktestResult from './BacktestResult.vue';
import StrategyAnalysisPanel from './components/StrategyAnalysisPanel.vue';
import SubjectiveWeightsMatrixTable from '@/components/SubjectiveWeightsMatrixTable.vue';
import TaskProgressPanel from '@/components/TaskProgressPanel.vue';
import { validateStrategyConfig } from '@/api/strategy';
import { getMonitorTask } from '@/api/monitor';
import {
  isTaskActive,
  taskKindLabel as resolveTaskKindLabel,
  taskBannerProgressText as resolveTaskBannerProgressText
} from '@/utils/taskProgress';

/** 进度轮询间隔：与监控跑批同一节奏 */
const PROGRESS_POLL_INTERVAL_MS = 2000;
/** 超过该时长仍未结束才弹进度框：快回测不打扰用户 */
const PROGRESS_DIALOG_DELAY_MS = 3000;

export default {
  name: 'BacktestExecution',
  components: {
    BacktestResult,
    StrategyAnalysisPanel,
    SubjectiveWeightsMatrixTable,
    TaskProgressPanel
  },
  data() {
    return {
      form: {
        backtest_mode: 'single',
        strategy_ids: null, // 单策略模式为单个值，多策略模式为数组
        initial_cash: 1000000,
        rebalance_freq: 'monthly',
        date_range: [
          dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
          dayjs().format('YYYY-MM-DD')
        ],
        commission_rate: 0,
        slippage: 0,
        // 波动率阈值重置（所有策略可选）
        enable_vol_reset: false,  // 所有策略默认关闭波动率重置
        vol_reset_threshold: 0.06,
        // 多策略对比：各主观策略从模型带出的只读预设 { [strategyId]: { weights, adjustments, maxLeverage } }
        multiManualPresets: {}
      },
      executing: false,
      backtestResults: null,
      backtestModelId: null,
      selectedStrategyInfo: null,
      // 多策略预设：默认展开已选择的主观策略面板，直接看到模型权重
      multiPresetActiveNames: [],
      // 调仓日期禁用：节假日列表（YYYY-MM-DD），可从接口扩展；空则仅禁用周末
      rebalanceHolidayDates: [],
      // 回测实时门禁：blocking_error / data_error 两级问题（warning 不阻断）
      backtestGateIssues: [],
      // 组合回测
      portfolioList: [],
      // 回测进度：progressKey 由前端生成，后端建同 id 的进度任务，页面并行轮询
      progressDialogVisible: false,
      progressTask: null,
      progressSubject: '',
      progressKey: '',
      progressTimer: null,
      progressOpenTimer: null,
      progressPolling: false,
      // 用户点过「后台运行 / 关闭」后，本轮不再自动弹出进度框
      progressUserClosed: false
    };
  },
  computed: {
    ...mapState('strategy', ['strategyModelList']),
    // 为了兼容性，提供 strategyList 作为 strategyModelList 的别名
    strategyList() {
      return this.strategyModelList || [];
    },
    /** 进度框标题：任务文档未建好前按「回测」兜底 */
    progressDialogTitle() {
      const kind = this.progressTask ? resolveTaskKindLabel(this.progressTask) : '回测';
      return this.progressSubject ? `${kind}进度：${this.progressSubject}` : `${kind}进度`;
    },
    /** 横幅文案：主体名 + 百分比（无总量时为「引擎计算中」） */
    progressBannerText() {
      const name = this.progressSubject ? `「${this.progressSubject}」` : '';
      const detail = this.progressTask ? resolveTaskBannerProgressText(this.progressTask) : '启动中';
      return `正在回测${name} ${detail}`;
    },
    /** 回测实时门禁：blocking 与数据缺口都禁用「执行回测」（与 resolve 的 backtest_ready 同口径） */
    backtestBlocked() {
      return this.backtestGateIssues.length > 0;
    },
    /** 门禁提示：首条问题 + 其余条数 */
    backtestBlockedTip() {
      const first = this.backtestGateIssues[0];
      if (!first) return '';
      const prefix = first.level === 'blocking_error' ? '配置阻断' : '数据缺口';
      const rest = this.backtestGateIssues.length > 1
        ? `（另有 ${this.backtestGateIssues.length - 1} 项问题）` : '';
      return `${prefix}：${first.message}${rest}`;
    },
    selectedStrategies() {
      if (!this.form.strategy_ids) return [];
      const ids = Array.isArray(this.form.strategy_ids) ? this.form.strategy_ids : [this.form.strategy_ids];
      return ids.map(id => this.strategyList.find(s => s.id === id)).filter(Boolean);
    },
    // 多策略模式下选中的主观配置策略（需配置预设调仓日与权重）
    selectedStrategiesWithManual() {
      if (this.form.backtest_mode !== 'multi') return [];
      return this.selectedStrategies.filter(s => this.isStrategyManual(s));
    },
    // 表单校验规则（主观策略下不校验调仓频率，因其被隐藏；数值类用 validator 避免类型误判）
    rules() {
      return {
        strategy_ids: [
          {
            validator: (rule, value, callback) => {
              const ids = value === null || value === undefined ? ([]).concat(value) : (Array.isArray(value) ? value : [value]);
              if (!ids.length || ids.every(id => id === null || id === undefined || id === '')) return callback(new Error('请选择策略'));
              callback();
            },
            trigger: 'change'
          }
        ],
        date_range: [
          {
            validator: (rule, value, callback) => {
              if (!value || !Array.isArray(value) || value.length !== 2) return callback(new Error('请选择回测时间'));
              if (!value[0] || !value[1]) return callback(new Error('请选择完整的回测时间范围'));
              callback();
            },
            trigger: 'change'
          }
        ],
        commission_rate: [
          {
            validator: (rule, value, callback) => {
              if (value === undefined || value === null || value === '') return callback(new Error('请输入手续费率'));
              const n = Number(value);
              if (!Number.isFinite(n) || n < 0) return callback(new Error('手续费率不能为负'));
              callback();
            },
            trigger: 'blur'
          }
        ],
        slippage: [
          {
            validator: (rule, value, callback) => {
              if (value === undefined || value === null || value === '') return callback(new Error('请输入滑点'));
              const n = Number(value);
              if (!Number.isFinite(n) || n < 0) return callback(new Error('滑点不能为负'));
              callback();
            },
            trigger: 'blur'
          }
        ]
      };
    },
    // 计算已选择的策略数量（正确处理单策略和多策略模式）
    selectedStrategyCount() {
      if (!this.form.strategy_ids) return 0;
      if (this.form.backtest_mode === 'single') {
        // 单策略模式：strategy_ids 是单个值或 null
        return this.form.strategy_ids ? 1 : 0;
      } else {
        // 多策略模式：strategy_ids 是数组
        return Array.isArray(this.form.strategy_ids) ? this.form.strategy_ids.length : 0;
      }
    },
    // 资产池列表（用于手动选择资产）
    assetPoolForSelection() {
      if (!this.selectedStrategyInfo || !this.selectedStrategyInfo.asset_codes) {
        return [];
      }
      // 返回资产池中的资产，带名称（若有）
      return this.selectedStrategyInfo.asset_codes.map(code => ({
        code,
        name: this.selectedStrategyInfo.asset_names?.[code] || code
      }));
    },
    // 资产池大小
    assetPoolSize() {
      return this.assetPoolForSelection.length || 100;
    },
    /** 当前选择是否为投资组合（组合不支持按单策略模型做多维验证） */
    isSelectedPortfolio() {
      const ids = this.form.strategy_ids;
      const single = Array.isArray(ids) ? ids[0] : ids;
      return String(single || '').startsWith('portfolio:');
    },
    // 是否为主观配置策略（支持权重初始化与交互式权重调整）
    isManualAllocationStrategy() {
      if (!this.selectedStrategyInfo) return false;
      const code = (this.selectedStrategyInfo.template_code || '').toString();
      return code === 'manual_allocation' || code === 'manual_allocation_strategy'
        || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
    },
    // 策略模型中的权重初始化、预设调仓日与杠杆上限（回测只读执行，不覆盖模型配置）
    manualPreset() {
      const s = this.selectedStrategyInfo;
      if (!s) return { weights: {}, adjustments: [], maxLeverage: 4 };
      const params = s.parameters || s.strategy_params || {};
      const codes = s.asset_codes || [];
      return {
        weights: this.parseWeightDict(params.manual_weights, codes),
        adjustments: this.parsePresetAdjustments(params.manual_weight_adjustments, codes),
        maxLeverage: this.getMaxLeverageForStrategy(s)
      };
    },
    manualWeightRows() {
      const s = this.selectedStrategyInfo;
      if (!s) return [];
      const codes = (s.asset_codes && s.asset_codes.length)
        ? s.asset_codes
        : Object.keys(this.manualPreset.weights);
      return codes.map(code => {
        const weight = Number(this.manualPreset.weights[code] || 0);
        return {
          code,
          label: this.resolveSingleAssetLabel(code),
          weight,
          percent: (weight * 100).toFixed(2) + '%'
        };
      });
    },
    manualWeightSum() {
      return this.manualWeightRows.reduce((sum, row) => sum + row.weight, 0);
    },
    manualWeightSumPercent() {
      return (this.manualWeightSum * 100).toFixed(2) + '%';
    },
    manualWeightSumClass() {
      if (this.manualWeightSum > this.manualPreset.maxLeverage + 1e-6) return 'is-over';
      return Math.abs(this.manualWeightSum - 1) < 0.001 ? 'is-ok' : 'is-under';
    }
  },
  watch: {
    'form.strategy_ids': {
      handler() {
        this.updateSelectedStrategyInfo();
        this.$nextTick(() => {
          if (this.isManualAllocationStrategy && this.$refs.form) this.$refs.form.clearValidate();
        });
        // 多策略模式：从各主观策略模型加载只读预设
        if (this.form.backtest_mode === 'multi') {
          this.$nextTick(() => {
            this.initMultiStrategyManualPresets();
          });
        }
      },
      deep: true
    },
    'form.backtest_mode'(newMode) {
      // 切换模式时重置策略选择
      if (newMode === 'single') {
        // 切换到单策略模式：如果当前是数组，取第一个；如果是单个值，保持不变
        if (Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids.length > 0 ? this.form.strategy_ids[0] : null;
        }
      } else {
        // 切换到多策略模式：如果当前是单个值，转为数组
        if (!Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids ? [this.form.strategy_ids] : [];
        }
      }
      this.updateSelectedStrategyInfo();
      if (newMode === 'multi') {
        this.$nextTick(() => this.initMultiStrategyManualPresets());
      }
    }
  },
  created() {
    this.loadStrategyList();
    this.loadPortfolioList();  // 加载组合列表（用于组合回测模式）
    // 初始化时更新策略信息
    this.$nextTick(() => {
      this.updateSelectedStrategyInfo();
    });
  },
  beforeDestroy() {
    this.stopProgressPolling();
  },
  methods: {
    async loadStrategyList() {
      try {
        // 加载所有策略（包括草稿和已发布的），不筛选状态
        // 这样新创建的策略也可以用于回测
        const list = await this.$store.dispatch('strategy/fetchStrategyModelList', {
          // 不传 status 参数，加载所有状态的策略
        });
        console.log('策略列表加载成功，共', list?.length || 0, '个策略');
        console.log('策略列表详情:', list);
        // 检查是否有已发布的策略
        const published = list?.filter(s => s.status === '已发布' || s.status === 'published') || [];
        console.log('已发布的策略数量:', published.length);
        if (published.length > 0) {
          console.log('已发布的策略:', published.map(s => ({ id: s.id, name: s.name, status: s.status })));
        }
      } catch (error) {
        console.error('加载策略列表失败:', error);
        this.$message.error('加载策略列表失败：' + (error.response?.data?.detail || error.message || '未知错误'));
      }
    },
    // 加载组合列表（用于组合回测模式）
    async loadPortfolioList() {
      try {
        const { getPortfolioList } = await import('@/api/portfolio');
        const res = await getPortfolioList();
        this.portfolioList = res.data || [];
      } catch (error) {
        console.error('加载组合列表失败:', error);
        this.portfolioList = [];
      }
    },
    /** 解析模型权重字典；兼容 JSON 字符串，仅保留资产池内资产 */
    parseWeightDict(raw, codes) {
      let mw = raw;
      if (typeof mw === 'string') {
        mw = this.parseJsonLoose(mw, {});
      }
      if (!mw || typeof mw !== 'object' || Array.isArray(mw)) return {};
      const out = {};
      const keys = (codes && codes.length) ? codes : Object.keys(mw);
      keys.forEach(code => {
        const v = mw[code];
        const n = Number(v);
        if (v !== undefined && v !== null && Number.isFinite(n)) out[code] = n;
      });
      return out;
    },
    /** 解析模型预设调仓日；只展示模型真实配置，不生成默认行 */
    parsePresetAdjustments(raw, codes) {
      let list = raw;
      if (typeof list === 'string') {
        list = this.parseJsonLoose(list, []);
      }
      if (!Array.isArray(list)) return [];
      return list
        .filter(adj => adj && adj.date)
        .map(adj => {
          const weights = {};
          const src = adj.weights || {};
          const keys = (codes && codes.length) ? codes : Object.keys(src);
          keys.forEach(code => {
            const n = Number(src[code]);
            weights[code] = Number.isFinite(n) ? n : 0;
          });
          return {
            date: this.normalizeDateForPicker(String(adj.date)) || '',
            weights,
            auto_normalize: !!adj.auto_normalize
          };
        })
        .filter(adj => adj.date);
    },
    /** 宽松 JSON 解析：兼容单引号形式的历史数据，失败时返回 fallback */
    parseJsonLoose(text, fallback) {
      const s = String(text || '').trim();
      if (!s) return fallback;
      try { return JSON.parse(s); } catch (_) { /* 继续尝试单引号兼容 */ }
      try { return JSON.parse(s.replace(/'/g, '"')); } catch (_) { return fallback; }
    },
    /** 将后端返回的日期（YYYYMMDD 或 YYYY-MM-DD）转为 YYYY-MM-DD */
    normalizeDateForPicker(val) {
      if (!val || typeof val !== 'string') return val;
      const s = String(val).replace(/-/g, '').trim().slice(0, 8);
      if (s.length === 8 && /^\d{8}$/.test(s)) {
        return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
      }
      return val;
    },
    isStrategyManual(strategy) {
      if (!strategy) return false;
      const code = (strategy.template_code || '').toString();
      return code === 'manual_allocation' || code === 'manual_allocation_strategy'
        || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
    },
    /** 多策略：从各主观策略模型加载只读预设（权重初始化、预设调仓日、杠杆上限） */
    async initMultiStrategyManualPresets() {
      if (this.form.backtest_mode !== 'multi') return;
      for (const s of this.selectedStrategiesWithManual || []) {
        let full = s;
        const p = s.parameters || {};
        const needsFull = Object.keys(p).length === 0
          || p.manual_weights == null
          || !Array.isArray(p.manual_weight_adjustments);
        if (needsFull) {
          try {
            full = (await this.$store.dispatch('strategy/fetchStrategyModel', s.id)) || s;
          } catch (e) {
            console.error('获取主观策略模型失败:', s.id, e);
            full = s;
          }
        }
        const params = full.parameters || full.strategy_params || {};
        const codes = full.asset_codes || s.asset_codes || [];
        this.$set(this.form.multiManualPresets, s.id, {
          weights: this.parseWeightDict(params.manual_weights, codes),
          adjustments: this.parsePresetAdjustments(params.manual_weight_adjustments, codes),
          maxLeverage: this.getMaxLeverageForStrategy(full)
        });
      }
      // 默认展开全部已选主观策略，无需额外点击即可看到模型预设权重
      this.multiPresetActiveNames = (this.selectedStrategiesWithManual || []).map(s => s.id);
    },
    /** 多策略：单个策略的只读预设（未加载完成时回退为空） */
    getMultiPreset(s) {
      const preset = this.form.multiManualPresets && this.form.multiManualPresets[s.id];
      return preset || { weights: {}, adjustments: [], maxLeverage: this.getMaxLeverageForStrategy(s) };
    },
    getMultiPresetWeightRows(s) {
      const preset = this.getMultiPreset(s);
      const codes = (s.asset_codes && s.asset_codes.length)
        ? s.asset_codes
        : Object.keys(preset.weights);
      return codes.map(code => {
        const weight = Number(preset.weights[code] || 0);
        return {
          code,
          label: this.resolveMultiAssetLabel(s, code),
          weight,
          percent: (weight * 100).toFixed(2) + '%'
        };
      });
    },
    getMultiPresetWeightSum(s) {
      return this.getMultiPresetWeightRows(s).reduce((sum, row) => sum + row.weight, 0);
    },
    getMultiPresetWeightSumPercent(s) {
      return (this.getMultiPresetWeightSum(s) * 100).toFixed(2) + '%';
    },
    getMultiPresetWeightSumClass(s) {
      const sum = this.getMultiPresetWeightSum(s);
      if (sum > this.getMultiPreset(s).maxLeverage + 1e-6) return 'is-over';
      return Math.abs(sum - 1) < 0.001 ? 'is-ok' : 'is-under';
    },
    /** 单策略主观：解析资产代码到展示名称 */
    resolveSingleAssetLabel(code) {
      const s = this.selectedStrategyInfo;
      if (s && s.asset_names && s.asset_names[code]) {
        return code + ' - ' + s.asset_names[code];
      }
      return code;
    },
    /** 多策略主观：解析资产代码到展示名称 */
    resolveMultiAssetLabel(strategy, code) {
      if (strategy && strategy.asset_names && strategy.asset_names[code]) {
        return code + ' - ' + strategy.asset_names[code];
      }
      return code;
    },
    /** 从策略模型取最大杠杆（默认 4 = 400%） */
    getMaxLeverageForStrategy(strategy) {
      if (!strategy) return 4;
      const p = strategy.parameters || strategy.strategy_params || {};
      const v = p.max_leverage;
      return (v !== undefined && v !== null && !Number.isNaN(Number(v))) ? Number(v) : 4;
    },
    handleStrategyChange() {
      // 策略选择变化时的处理
      if (this.form.backtest_mode === 'multi') {
        // 确保 strategy_ids 是数组
        if (!Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids ? [this.form.strategy_ids] : [];
        }
        
        // 限制最多选择10个策略
        if (this.form.strategy_ids && this.form.strategy_ids.length > 10) {
          this.$message.warning('多策略对比最多选择10个策略，已自动保留前10个');
          this.form.strategy_ids = this.form.strategy_ids.slice(0, 10);
        }
        
        // 为多策略模式的所有策略构建 asset_names 映射
        this.$nextTick(async () => {
          const strategies = this.selectedStrategies || [];
          for (const strategy of strategies) {
            await this.buildAssetNamesForStrategy(strategy);
          }
        });
      } else {
        // 单策略模式：确保 strategy_ids 是单个值
        if (Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids.length > 0 ? this.form.strategy_ids[0] : null;
        }
      }
      this.updateSelectedStrategyInfo();
    },
    async updateSelectedStrategyInfo() {
      // 更新选中的策略信息(用于显示资产池和参数等)
      let strategyId = null;
          
      if (this.form.backtest_mode === 'single') {
        // 单策略模式
        strategyId = Array.isArray(this.form.strategy_ids) 
          ? (this.form.strategy_ids.length > 0 ? this.form.strategy_ids[0] : null)
          : this.form.strategy_ids;
      } else {
        // 多策略模式显示第一个策略的信息
        if (this.form.strategy_ids && Array.isArray(this.form.strategy_ids) && this.form.strategy_ids.length > 0) {
          strategyId = this.form.strategy_ids[0];
        }
      }
          
      if (strategyId) {
        // 组合ID：不需要加载策略详情
        if (String(strategyId).startsWith('portfolio:')) {
          this.selectedStrategyInfo = null;
          return;
        }
        // 先从列表中查找
        const strategy = this.strategyList.find(s => s.id === strategyId);
        const code = strategy && (strategy.template_code || '').toString();
        const isManual = code === 'manual_allocation' || code === 'manual_allocation_strategy'
          || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
        const hasManualWeights = strategy && strategy.parameters && typeof strategy.parameters.manual_weights === 'object' && strategy.parameters.manual_weights !== null;
        // 列表信息不完整,或为主观配置策略时拉取完整策略(保证权重初始化与预设调仓日能带出)
        const needFull = strategy && (
          !strategy.parameters ||
          !strategy.parameter_labels ||
          isManual
        );
        if (needFull) {
          try {
            const fullStrategy = await this.$store.dispatch('strategy/fetchStrategyModel', strategyId);
            this.selectedStrategyInfo = fullStrategy;
            // 构建 asset_names 映射
            await this.buildAssetNamesForStrategy(this.selectedStrategyInfo);
          } catch (error) {
            console.error('获取策略详情失败:', error);
            this.selectedStrategyInfo = strategy;
            // 构建 asset_names 映射
            await this.buildAssetNamesForStrategy(this.selectedStrategyInfo);
          }
        } else {
          this.selectedStrategyInfo = strategy;
          // 构建 asset_names 映射
          await this.buildAssetNamesForStrategy(this.selectedStrategyInfo);
        }
      } else {
        this.selectedStrategyInfo = null;
      }

      // 波动率阈值重置：若已选策略模型配置过，则表单默认使用模型配置值（单策略用该策略，多策略用第一个策略）
      this.applyVolResetDefaultsFromStrategy(this.selectedStrategyInfo);

      // 多策略模式：清理已取消选择的策略的只读预设
      if (this.form.backtest_mode === 'multi') {
        this.cleanupDeselectedStrategies();
      }

      // 单策略模式下实时算门禁，决定「执行回测」是否可点
      await this.refreshBacktestGate();
    },
    /** 单策略回测的实时门禁：与预设 resolve 共用同一套校验（check_static_contract + 价格聚合）
     *
     * 详情页与回测页都不能依赖「保存时校验」的结果：模型可能被直接改库或
     * 数据在保存后才补齐，所以每次选择策略都重新算一遍。
     * 校验接口失败时放行（不阻断用户），后端回测前仍有 enforce_static_contract。
     */
    async refreshBacktestGate() {
      const strategy = this.selectedStrategyInfo;
      if (!strategy || this.form.backtest_mode !== 'single') {
        this.backtestGateIssues = [];
        return;
      }
      // 组合伪策略不参与策略门禁
      if (String(strategy.id || '').startsWith('portfolio:')) {
        this.backtestGateIssues = [];
        return;
      }
      try {
        const res = await validateStrategyConfig({
          template_code: strategy.template_code,
          asset_codes: strategy.asset_codes || [],
          parameters: strategy.parameters || {},
          min_history_days: strategy.min_history_days
        });
        const data = (res && res.data) || {};
        const issues = data.issues || [];
        this.backtestGateIssues = issues.filter(
          i => i.level === 'blocking_error' || i.level === 'data_error'
        );
      } catch (error) {
        console.error('回测门禁校验失败:', error);
        this.backtestGateIssues = [];
      }
    },
    /** 为策略构建 asset_names 映射(从资产库获取名称) */
    async buildAssetNamesForStrategy(strategy) {
      if (!strategy || !strategy.asset_codes || strategy.asset_codes.length === 0) {
        return;
      }
      // 如果已有 asset_names,跳过
      if (strategy.asset_names && Object.keys(strategy.asset_names).length > 0) {
        return;
      }
      try {
        // 从资产库获取所有资产选项
        const assetOptions = await this.$store.dispatch('asset/fetchAssetOptions');
        // 构建 code -> name 映射
        const assetNames = {};
        strategy.asset_codes.forEach(code => {
          const asset = assetOptions.find(a => a.code === code);
          assetNames[code] = asset ? asset.name : code;
        });
        // 设置到策略对象上
        this.$set(strategy, 'asset_names', assetNames);
      } catch (error) {
        console.error('获取资产名称失败:', error);
        // 失败时使用 code 作为 name
        const assetNames = {};
        strategy.asset_codes.forEach(code => {
          assetNames[code] = code;
        });
        this.$set(strategy, 'asset_names', assetNames);
      }
    },
    /** 格式化回测 snapshot 的 time 为 YYYY-MM-DD */
    formatSnapshotDate(t) {
      if (!t) return '';
      return dayjs(t).format('YYYY-MM-DD');
    },
    formatPercent(v) {
      if (v == null || v === undefined) return '-';
      const p = Number(v);
      if (Number.isNaN(p)) return '-';
      return (p * 100).toFixed(2) + '%';
    },
    formatMetric(v) {
      if (v == null || v === undefined) return '-';
      const n = Number(v);
      if (Number.isNaN(n)) return '-';
      return n.toFixed(2);
    },
    formatNav(v) {
      if (v == null || v === undefined) return '-';
      const n = Number(v);
      if (Number.isNaN(n)) return '-';
      return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    /** 从策略模型的 parameters 中取 enable_vol_reset / vol_reset_threshold 作为回测表单默认值 */
    applyVolResetDefaultsFromStrategy(strategy) {
      if (!strategy || !strategy.parameters) return;
      const p = strategy.parameters;
      if (p.enable_vol_reset !== undefined && p.enable_vol_reset !== null) {
        this.form.enable_vol_reset = !!p.enable_vol_reset;
      }
      if (p.vol_reset_threshold !== undefined && p.vol_reset_threshold !== null) {
        const v = Number(p.vol_reset_threshold);
        if (!Number.isNaN(v) && v >= 0.01 && v <= 0.5) {
          this.form.vol_reset_threshold = v;
        }
      }
    },
    // ========== 多策略模式的资产选择方法 ==========
    // 获取指定策略的资产池（多策略模式）
    getStrategyAssetPool(strategyId) {
      const strategy = this.strategyList.find(s => s.id === strategyId);
      if (!strategy || !strategy.asset_codes) {
        return [];
      }
      return strategy.asset_codes.map(code => ({
        code,
        name: strategy.asset_names?.[code] || code
      }));
    },
    // 获取指定策略的资产池大小（多策略模式）
    getStrategyAssetPoolSize(strategyId) {
      const strategy = this.strategyList.find(s => s.id === strategyId);
      return strategy?.asset_codes?.length || 100;
    },
    // ========== 多策略模式的资产选择方法（已移除，选择器参数由策略模型配置） ==========
    // 清理已取消选择的策略的只读预设
    cleanupDeselectedStrategies() {
      const selectedStrategies = this.selectedStrategies;
      Object.keys(this.form.multiManualPresets || {}).forEach(strategyId => {
        if (!selectedStrategies.find(s => s.id === strategyId)) {
          this.$delete(this.form.multiManualPresets, strategyId);
        }
      });
    },
    /** 基础回测参数校验，返回错误信息（无错则为空） */
    baseValidationMessage() {
      const f = this.form;
      if (!f.strategy_ids && f.strategy_ids !== 0) return '请选择策略';
      if (!f.date_range || !Array.isArray(f.date_range) || f.date_range.length !== 2 || !f.date_range[0] || !f.date_range[1]) {
        return '请选择完整的回测时间范围';
      }
      const nComm = Number(f.commission_rate);
      if (f.commission_rate === undefined || f.commission_rate === null || f.commission_rate === '' || !Number.isFinite(nComm) || nComm < 0) {
        return '请输入手续费率';
      }
      const nSlip = Number(f.slippage);
      if (f.slippage === undefined || f.slippage === null || f.slippage === '' || !Number.isFinite(nSlip) || nSlip < 0) {
        return '请输入滑点';
      }
      return '';
    },
    /** 主观策略自检：仅校验基础参数与模型预设是否足以建仓 */
    validateManualStrategyForm() {
      return new Promise((resolve) => {
        if (this.$refs.form) this.$refs.form.clearValidate();
        const baseMsg = this.baseValidationMessage();
        if (baseMsg) {
          this.$message.warning(baseMsg);
          return resolve(false);
        }
        const preset = this.manualPreset;
        if ((!preset.adjustments || preset.adjustments.length === 0) && this.manualWeightSum <= 1e-6) {
          this.$message.warning('策略模型未配置权重初始化，请先在策略模型「主观配置权重」中配置后再回测');
          return resolve(false);
        }
        resolve(true);
      });
    },
    /** 多策略含主观策略自检：仅校验基础参数与各模型预设是否足以建仓 */
    validateMultiStrategyWithManualForm() {
      return new Promise((resolve) => {
        if (this.$refs.form) this.$refs.form.clearValidate();
        const baseMsg = this.baseValidationMessage();
        if (baseMsg) {
          this.$message.warning(baseMsg);
          return resolve(false);
        }
        for (const s of this.selectedStrategiesWithManual || []) {
          const preset = this.getMultiPreset(s);
          if ((!preset.adjustments || preset.adjustments.length === 0) && this.getMultiPresetWeightSum(s) <= 1e-6) {
            this.$message.warning(`主观策略「${s.name || s.id}」的模型未配置权重初始化，请先编辑策略模型后再回测`);
            return resolve(false);
          }
        }
        resolve(true);
      });
    },
    handleExecute() {
      // 预设门禁未通过（配置阻断或数据缺口）时不进入回测流程，
      // 直接提示首条问题并中止（后端回测前仍有 enforce_static_contract 兜底）
      if (this.backtestBlocked) {
        this.$message.warning(this.backtestBlockedTip);
        return;
      }
      const runValidation = () => {
        // 主观策略（单策略或多策略含主观）时用自检避免 el-form 对预设调仓区块误报
        if (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) {
          return this.validateManualStrategyForm();
        }
        if (this.form.backtest_mode === 'multi' && this.selectedStrategiesWithManual.length > 0) {
          return this.validateMultiStrategyWithManualForm();
        }
        return new Promise((resolve) => {
          this.$refs.form.validate((valid) => resolve(valid));
        });
      };
      runValidation().then(async (valid) => {
        if (!valid) return;

        // 验证策略选择并规范化 strategy_ids
        let strategyIds = [];
        if (this.form.backtest_mode === 'multi') {
          // 多策略模式：确保是数组
          if (!Array.isArray(this.form.strategy_ids)) {
            strategyIds = this.form.strategy_ids ? [this.form.strategy_ids] : [];
          } else {
            strategyIds = [...this.form.strategy_ids]; // 创建副本
          }
          
          if (strategyIds.length === 0) {
            this.$message.warning('请至少选择一个策略');
            return;
          }
          if (strategyIds.length < 2) {
            this.$message.warning('多策略对比模式需要选择至少2个策略');
            return;
          }
          if (strategyIds.length > 10) {
            this.$message.warning('多策略对比最多选择10个策略');
            return;
          }
        } else {
          // 单策略模式：确保是单个值
          if (Array.isArray(this.form.strategy_ids)) {
            strategyIds = this.form.strategy_ids.length > 0 ? [this.form.strategy_ids[0]] : [];
          } else {
            strategyIds = this.form.strategy_ids ? [this.form.strategy_ids] : [];
          }
          
          if (strategyIds.length === 0) {
            this.$message.warning('请选择一个策略或组合');
            return;
          }
        }

        // 验证日期范围
        if (!this.form.date_range || this.form.date_range.length !== 2) {
          this.$message.warning('请选择完整的回测时间范围');
          return;
        }

        if (new Date(this.form.date_range[0]) >= new Date(this.form.date_range[1])) {
          this.$message.warning('起始日期必须早于结束日期');
          return;
        }

        // 主观策略：展示值来自模型预设，仅做杠杆上限提示（后端会再次校验）
        if (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) {
          const maxLev = this.manualPreset.maxLeverage;
          if (this.manualWeightSum > maxLev + 1e-6) {
            this.$message.warning(`权重初始化总和 ${this.manualWeightSumPercent} 超过模型杠杆上限 ${(maxLev * 100).toFixed(0)}%，请先调整策略模型`);
            return;
          }
          for (const adj of this.manualPreset.adjustments) {
            const sumAdj = Object.values(adj.weights || {}).reduce((sum, v) => sum + (Number(v) || 0), 0);
            if (sumAdj > maxLev + 1e-6) {
              this.$message.warning(`预设调仓日 ${adj.date} 的权重总和超过模型杠杆上限 ${(maxLev * 100).toFixed(0)}%，请先调整策略模型`);
              return;
            }
          }
        }

        // 多策略：各主观策略模型预设的杠杆上限提示（后端会再次校验）
        if (this.form.backtest_mode === 'multi') {
          for (const s of this.selectedStrategiesWithManual || []) {
            const preset = this.getMultiPreset(s);
            if (this.getMultiPresetWeightSum(s) > preset.maxLeverage + 1e-6) {
              this.$message.warning(`主观策略「${s.name || s.id}」权重初始化总和超过模型杠杆上限 ${(preset.maxLeverage * 100).toFixed(0)}%，请先调整策略模型`);
              return;
            }
            for (const adj of preset.adjustments) {
              const sumAdj = Object.values(adj.weights || {}).reduce((sum, v) => sum + (Number(v) || 0), 0);
              if (sumAdj > preset.maxLeverage + 1e-6) {
                this.$message.warning(`主观策略「${s.name || s.id}」预设调仓日 ${adj.date} 的权重总和超过模型杠杆上限 ${(preset.maxLeverage * 100).toFixed(0)}%，请先调整策略模型`);
                return;
              }
            }
          }
        }

        // 动量选择器由策略模型配置，回测时由选择器自动选资产，无需在回测页配置「选择资产数量」与「具体资产」

        this.executing = true;
        this.backtestResults = null;
        // 新一轮回测：重置「用户已收起进度框」标记，允许进度框重新自动弹出
        this.progressUserClosed = false;

        try {
          const results = {};
          // 多策略时先跑非主观策略（一次性到结束日），再跑主观策略（可能步进暂停），保证对比结果包含所有策略
          const isMulti = this.form.backtest_mode === 'multi';
          // 组合ID不参与主观策略分类，始终作为非主观项处理
          const nonManualIds = isMulti ? strategyIds.filter(id => {
            if (String(id).startsWith('portfolio:')) return true; // 组合视为非主观
            const s = this.strategyList.find(r => r.id === id);
            return s && !this.isStrategyManual(s);
          }) : [];
          const manualIds = isMulti ? strategyIds.filter(id => {
            if (String(id).startsWith('portfolio:')) return false; // 组合不参与主观分类
            const s = this.strategyList.find(r => r.id === id);
            return s && this.isStrategyManual(s);
          }) : [];
          const runOrder = isMulti ? [...nonManualIds, ...manualIds] : strategyIds;

          for (const strategyId of runOrder) {
            // 组合ID：调用组合回测API
            if (String(strategyId).startsWith('portfolio:')) {
              const portfolioId = String(strategyId).replace(/^portfolio:/, '');
              const portfolio = this.portfolioList.find(p => p.id === portfolioId);
              try {
                const { runPortfolioBacktest } = await import('@/api/portfolio');
                const startDate = this.form.date_range[0].replace(/-/g, '');
                const endDate = this.form.date_range[1].replace(/-/g, '');
                const freqMapping = {
                  '每日': 'daily', '每周': 'weekly', '每月': 'monthly',
                  '每季度': 'quarterly', '每年': 'yearly',
                  'daily': 'daily', 'weekly': 'weekly', 'monthly': 'monthly',
                  'quarterly': 'quarterly', 'yearly': 'yearly'
                };
                const progressKey = this.startProgress(portfolio ? portfolio.name : `组合${portfolioId}`);
                const res = await runPortfolioBacktest(portfolioId, {
                  start_date: startDate,
                  end_date: endDate,
                  initial_nav: this.form.initial_cash,
                  rebalance_freq: freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly',
                  mother_vol_target: this.form.enable_vol_reset ? this.form.vol_reset_threshold : null,
                  // 子策略与母层同一组成本参数，否则组合层成交只计入零成本
                  commission_rate: Number(this.form.commission_rate),
                  slippage: Number(this.form.slippage)
                }, progressKey);
                const data = res.data || res;
                // 组合回测结果转换为与策略回测相同的结构
                const portfolioName = portfolio ? portfolio.name : `组合${portfolioId}`;
                results[strategyId] = {
                  result: {
                    total_return: data.total_return,
                    annual_return: data.annual_return,
                    annual_volatility: data.annual_volatility,
                    // SingleStrategyResult 读的是 volatility 字段（单策略后端 BacktestResultOut 的命名），组合后端返回 annual_volatility，需映射
                    volatility: data.annual_volatility,
                    sharpe_ratio: data.sharpe_ratio,
                    max_drawdown: data.max_drawdown,
                    calmar_ratio: data.calmar_ratio,
                    // 365 口径（自然日/年）：组合后端字段名与单策略不同，同值双写
                    annual_return_365: data.annual_return_365,
                    annual_volatility_365: data.annual_volatility_365,
                    volatility_365: data.annual_volatility_365,
                    sharpe_ratio_365: data.sharpe_ratio_365,
                    calmar_ratio_365: data.calmar_ratio_365,
                    // 携带交易明细与胜率，避免交易次数/胜率为空
                    trades: data.trades || [],
                    win_rate: data.win_rate != null ? data.win_rate : null,
                    // 组合层成本统计（后端统一口径）与子策略成本明细
                    n_trades: data.n_trades != null ? data.n_trades : null,
                    total_commission: data.total_commission != null ? data.total_commission : null,
                    total_slippage: data.total_slippage != null ? data.total_slippage : null,
                    turnover: data.turnover != null ? data.turnover : null,
                    sub_strategies: data.sub_strategies || [],
                    // 后端如实上报的数据质量告警与子策略归因
                    warnings: data.warnings || [],
                    attribution: data.attribution || null,
                    snapshots: (data.equity_curve || []).map(pt => ({
                      time: pt.date,
                      total_value: pt.value,
                      // 携带后端已算好的回撤/调仓/穿透权重，避免 SingleStrategyResult 回撤图全为0、持仓图为空
                      drawdown: pt.drawdown != null ? pt.drawdown : 0,
                      is_rebalance_day: !!pt.is_rebalance_day,
                      weights: pt.weights || {}
                    }))
                  },
                  strategy: {
                    id: strategyId,
                    name: portfolioName,
                    template_code: 'PORTFOLIO',
                    status: '已发布'
                  },
                  record_id: data.backtest_record_id || null,
                  remark: ''
                };
              } catch (error) {
                console.error(`组合 ${portfolioId} 回测失败:`, error);
                this.$message.error(`组合回测失败：${error.response?.data?.detail || error.message || '未知错误'}`);
              } finally {
                this.stopProgressPolling();
              }
              continue; // 跳过后续策略回测逻辑
            }

            const strategy = this.strategyList.find(s => s.id === strategyId);
            if (!strategy) continue;

            try {
              // 调仓频率映射：中文 -> 英文
              const freqMapping = {
                '每日': 'daily',
                '每周': 'weekly',
                '每月': 'monthly',
                '每季度': 'quarterly',
                '每年': 'yearly',
                'daily': 'daily',
                'weekly': 'weekly',
                'monthly': 'monthly',
                'quarterly': 'quarterly',
                'yearly': 'yearly'
              };
              
              const rebalanceFreq = freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly';
              
              // 构建回测请求数据
              const backtestData = {
                start_date: this.form.date_range[0].replace(/-/g, ''),
                end_date: this.form.date_range[1].replace(/-/g, ''),
                initial_cash: this.form.initial_cash,
                rebalance_freq: rebalanceFreq,
                commission_rate: this.form.commission_rate,
                slippage: this.form.slippage,
                lookback_days: 252,  // 自然日（≈169 交易日）；后端按策略 min_history_days 反推并取更大值
                enable_vol_reset: this.form.enable_vol_reset,
                vol_reset_threshold: this.form.vol_reset_threshold
              };
              // 主观策略的权重初始化与预设调仓日由后端直接读取策略模型配置，不在此覆盖

              // 资产选择器：仅标记启用，具体参数由策略模型配置决定（后端从 model_data 读取）
              if (strategy.enable_momentum_selection === true) {
                backtestData.enable_momentum_selection = true;
                backtestData.asset_selection_count = strategy.asset_selection_count || (strategy.asset_codes && strategy.asset_codes.length) || 5;
              }
              
              // 进度任务号随请求带给后端，页面同时开始轮询该任务
              const progressKey = this.startProgress(strategy.name);
              const result = await this.$store.dispatch('strategy/runBacktest', {
                modelId: strategyId,
                data: backtestData,
                progressKey
              });

              // 处理返回结果（统一解包 code/data 结构，保证 record_id 可用）
              const resultData = (result && result.data !== undefined) ? result.data : result;
              let recordId = resultData && (resultData.record_id != null ? String(resultData.record_id) : (result && result.data && result.data.record_id != null ? String(result.data.record_id) : null));
              console.log('[BacktestRecord] 回测返回 raw_result_keys=', result ? Object.keys(result) : [], 'resultData_record_id=', resultData && resultData.record_id, 'recordId=', recordId);
              // 若响应中无 record_id，则查询该策略最新回测记录进行关联（先保存再查询关联）
              if (!recordId && strategyId) {
                try {
                  const history = await this.$store.dispatch('strategy/fetchBacktestHistory', { modelId: strategyId, skip: 0, limit: 5 });
                  const list = Array.isArray(history) ? history : (history && history.data) ? history.data : [];
                  const latest = list[0];
                  if (latest && (latest.id || latest._id)) {
                    recordId = String(latest.id || latest._id);
                    if (resultData && typeof resultData === 'object') resultData.record_id = recordId;
                    console.log('[BacktestRecord] 通过查询历史记录关联 record_id=', recordId);
                  } else {
                    console.warn('[BacktestRecord] 查询历史记录无最新记录 modelId=', strategyId, 'list_length=', list.length);
                  }
                } catch (e) {
                  console.warn('[BacktestRecord] 查询历史记录失败', e);
                }
              }

              const rid = recordId != null ? String(recordId) : (resultData && resultData.record_id != null ? String(resultData.record_id) : (resultData && resultData.result && resultData.result.record_id != null ? String(resultData.result.record_id) : null));
              const resultKey = isMulti ? String(strategyId) : strategy.name;
              results[resultKey] = {
                result: resultData,
                strategy: strategy,
                remark: resultData.remark != null ? resultData.remark : '',
                record_id: rid
              };
              if (this.form.backtest_mode === 'single') {
                this.backtestModelId = strategyId;
              }
              const snapCount = (resultData && resultData.snapshots && Array.isArray(resultData.snapshots)) ? resultData.snapshots.length : 0;
              console.log('[BacktestRecord] 结果写入 key=', resultKey, 'strategyName=', strategy.name, 'record_id=', rid, 'snapshots=', snapCount, 'backtestModelId=', this.form.backtest_mode === 'single' ? strategyId : undefined);
            } catch (error) {
              console.error(`策略 ${strategy.name} 回测失败:`, error);
              console.error('完整错误信息:', error.response);
              
              // 提取详细错误信息
              let errorDetail = '未知错误';
              if (error.response) {
                if (error.response.data) {
                  if (error.response.data.detail) {
                    errorDetail = error.response.data.detail;
                  } else if (error.response.data.message) {
                    errorDetail = error.response.data.message;
                  } else if (typeof error.response.data === 'string') {
                    errorDetail = error.response.data;
                  }
                } else if (error.response.statusText) {
                  errorDetail = `${error.response.status} ${error.response.statusText}`;
                }
              } else if (error.message) {
                errorDetail = error.message;
              }
              
              // 如果是多行错误信息，使用换行符分隔
              const errorMsg = typeof errorDetail === 'string' && errorDetail.includes('\n')
                ? errorDetail.split('\n').join('<br/>')
                : errorDetail;
              
              // 显示错误消息
              // 对于数据不足的错误，使用更友好的显示方式
              let displayMessage = `策略 "${strategy.name}" 回测失败：${errorMsg}`;
              
              // 如果是数据不足的错误，使用对话框显示完整信息
              if (errorDetail.includes('没有资产满足最小历史数据要求') || 
                  errorDetail.includes('可用数据情况') || 
                  errorDetail.includes('建议：')) {
                this.$alert(
                  displayMessage,
                  '回测失败 - 数据不足',
                  {
                    confirmButtonText: '确定',
                    type: 'error',
                    dangerouslyUseHTMLString: true,
                    customClass: 'backtest-error-dialog'
                  }
                );
              } else {
                this.$message({
                  message: displayMessage,
                  type: 'error',
                  duration: 10000, // 延长显示时间
                  dangerouslyUseHTMLString: true,
                  showClose: true
                });
              }
              
              // 如果是500错误，提供更多帮助信息
              if (error.response && error.response.status === 500) {
                console.warn('回测500错误，可能的原因：');
                console.warn('1. 策略参数配置错误');
                console.warn('2. 策略算法实现问题');
                console.warn('3. 数据格式不匹配');
                console.warn('4. 请查看后端日志获取详细错误堆栈');
              }
            } finally {
              this.stopProgressPolling();
            }
          }

          if (Object.keys(results).length > 0) {
            this.backtestResults = results;
            const keys = Object.keys(results);
            console.log('[多策略] 回测完成 策略数=', keys.length, 'keys=', keys);
            keys.forEach(k => {
              const r = results[k];
              const snap = (r && r.result && r.result.snapshots) ? r.result.snapshots.length : 0;
              console.log('[多策略] 主观策略回测数据 key=', k, 'strategyName=', (r && r.strategy && r.strategy.name) || k, 'snapshots=', snap, 'hasResult=', !!(r && r.result));
            });
            this.$message.success(`回测完成！共运行 ${keys.length} 个策略`);
            
            // 滚动到结果区域
            this.$nextTick(() => {
              const resultElement = document.querySelector('.backtest-result');
              if (resultElement) {
                resultElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }
            });
          } else {
            this.$message.error('所有策略回测均失败');
          }
        } catch (error) {
          console.error('回测执行失败:', error);
          this.$message.error('回测执行失败：' + (error.response?.data?.detail || error.message));
        } finally {
          this.executing = false;
          this.endProgress();
        }
      });
    },
    handleReset() {
      this.$refs.form.resetFields();
      this.form = {
        backtest_mode: 'single',
        strategy_ids: null, // 单策略模式为 null，多策略模式为 []
        initial_cash: 1000000,
        rebalance_freq: 'monthly',
        date_range: [
          dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
          dayjs().format('YYYY-MM-DD')
        ],
        commission_rate: 0,
        slippage: 0,
        enable_vol_reset: false,  // 所有策略默认关闭波动率重置
        vol_reset_threshold: 0.06,
        multiManualPresets: {}
      };
      this.backtestResults = null;
      this.backtestModelId = null;
      this.selectedStrategyInfo = null;
      this.multiPresetActiveNames = [];
    },
    handleViewHistory() {
      this.$message.info('历史记录功能开发中...');
      // TODO: 跳转到历史记录页面
    },
    // ===== 回测进度：与日常监控共用 monitor_tasks 与 GET /monitor/tasks/{task_id} =====
    /** 生成进度任务号（后端 task_id 上限 64 字符） */
    newProgressKey() {
      const part = () => Math.floor(Math.random() * 4294967296).toString(16);
      return `bt${Date.now().toString(16)}${part()}${part()}${part()}${part()}`.slice(0, 64);
    },
    /**
     * 开启一次回测的进度上报：生成 key、重置面板、启动轮询。
     * 返回的 key 要随回测请求一起传给后端，轮询与回测请求并行发出，
     * 后端一建好进度文档前端就能读到。
     */
    startProgress(subject) {
      this.stopProgressPolling();
      this.progressSubject = subject || '';
      this.progressTask = null;
      this.progressKey = this.newProgressKey();
      // 几秒内结束的快回测不弹框，避免遮挡表单与结果区
      if (!this.progressUserClosed) {
        this.progressOpenTimer = setTimeout(() => {
          if (this.executing && !this.progressUserClosed) {
            this.progressDialogVisible = true;
          }
        }, PROGRESS_DIALOG_DELAY_MS);
      }
      this.progressTimer = setInterval(this.pollProgress, PROGRESS_POLL_INTERVAL_MS);
      // 不在这里立即拉一次：进度文档是后端收到本次回测请求后才建的，
      // 请求尚未发出就轮询必然 404（浏览器网络面板会留一条红色失败记录）。
      // 首个轮询放到一个间隔之后，此时后端已完成建文档。
      return this.progressKey;
    },
    /** 单次拉取：失败静默保留上一次状态，任务到终态即停轮询 */
    async pollProgress() {
      const key = this.progressKey;
      if (!key || this.progressPolling) return;
      this.progressPolling = true;
      try {
        const res = await getMonitorTask(key, { skipGlobal404Message: true });
        const task = res.data || res;
        // 已切到下一个策略时丢弃旧响应，避免多策略对比时进度串台
        if (!task || !task.task_id || key !== this.progressKey) return;
        this.progressTask = task;
        if (!isTaskActive(task)) this.stopProgressPolling();
      } catch (e) {
        // 进度只读失败不影响回测本身
      } finally {
        this.progressPolling = false;
      }
    },
    stopProgressPolling() {
      if (this.progressTimer) {
        clearInterval(this.progressTimer);
        this.progressTimer = null;
      }
      if (this.progressOpenTimer) {
        clearTimeout(this.progressOpenTimer);
        this.progressOpenTimer = null;
      }
    },
    /** 整轮回测结束：停轮询并收起进度框，让位给下方结果区 */
    endProgress() {
      this.stopProgressPolling();
      this.progressDialogVisible = false;
      this.progressKey = '';
    },
    reopenProgress() {
      this.progressUserClosed = false;
      this.progressDialogVisible = true;
    },
    getStatusTagType(status) {
      // 根据策略状态返回对应的标签类型
      const statusMap = {
        '草稿': 'info',
        '已发布': 'success',
        '已归档': 'warning'
      };
      return statusMap[status] || 'info';
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
  max-width: 1200px;
  margin: 0 auto;
}

/* 回测门禁：禁用时 tooltip 需要包一层 span 才能触发 */
.execute-btn-wrap {
  display: inline-block;
  margin-right: 10px;
}

.backtest-gate-tip {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: #e6a23c;
}

.card-header {
  font-weight: 500;
  font-size: 16px;
}

.el-form {
  max-width: 800px;
}

/* 资产选择标签样式 */
.asset-selection-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.asset-tag {
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}

.asset-tag:hover {
  transform: scale(1.05);
}

.asset-tag-selected {
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.4);
}

/* 主观策略模型预设（只读展示） */
.preset-card {
  background-color: #fafafa;
  border: 1px solid #e4e7ed;
}
.preset-card-date {
  background-color: #f7fbff;
  border-color: #d9ecff;
}
.preset-card-header {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}
.preset-card-header-date {
  color: #409EFF;
}
.preset-desc {
  margin-bottom: 12px;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}
.preset-inline-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.preset-inline-hint {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.preset-weight-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px 16px;
}
.preset-weight-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}
.preset-weight-label {
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.preset-weight-value {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
}
.preset-sum {
  margin-top: 10px;
  font-size: 12px;
}
.preset-sum.is-ok {
  color: #67C23A;
}
.preset-sum.is-under {
  color: #E6A23C;
}
.preset-sum.is-over {
  color: #F56C6C;
}
.preset-sum-hint {
  color: #909399;
}
.preset-block + .preset-block {
  margin-top: 16px;
}
.preset-block-title {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}
.preset-empty {
  padding: 12px;
  color: #909399;
  font-size: 12px;
  background: #fff;
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
}

/* 预设调仓日对话框：当前绩效指标 */
.metric-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.metric-label {
  font-size: 12px;
  color: #909399;
}
.metric-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

/* 回测进度：收起进度框后的页面横幅 */
.backtest-progress-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
  padding: 8px 12px;
  color: #606266;
  font-size: 13px;
  background: #f4f4f5;
  border-radius: 4px;
}
.backtest-progress-bar__text {
  flex: 1;
}
/* 进度文档尚未建好时的占位文案 */
.backtest-progress-wait {
  color: #909399;
  font-size: 13px;
}
</style>
