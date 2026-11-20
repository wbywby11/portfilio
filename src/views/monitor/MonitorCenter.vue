<template>
  <div class="page-container monitor-center">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">日常监控</h2>
        <p v-if="!eligibleLoading && isManualAllocationMonitor" class="manual-step-inline">
          <el-checkbox v-model="manualPresetStepOptIn">
            主观：预设调仓日步进（与回测一致，在每档调仓日当日推演完成后暂停，便于查看绩效后再继续）
          </el-checkbox>
        </p>
      </div>
      <!-- 批次口径：每次运行产出一份版本化快照，此处选定要展示哪一份 -->
      <div v-if="activeMonitorId" class="header-right batch-bar">
        <span class="batch-bar__label">当前批次</span>
        <el-select
          :value="currentBatchId || ''"
          size="small"
          class="batch-bar__select"
          placeholder="最新完成批次"
          :loading="batchesLoading"
          :disabled="isTaskActive"
          @change="handleBatchChange">
          <el-option label="最新完成批次（自动跟随）" value="" />
          <el-option
            v-for="b in batchList"
            :key="b.batch_id"
            :label="batchOptionLabel(b)"
            :value="b.batch_id" />
        </el-select>
        <span v-if="currentBatchHint" class="batch-bar__hint">{{ currentBatchHint }}</span>
      </div>
    </div>






    <!-- 运行任务对话框（后台任务：提交后可关闭，进度在页面横幅与弹窗内均可查看） -->
    <el-dialog
      :title="taskDialogTitle"
      :visible.sync="initDialogVisible"
      width="480px"
      :close-on-click-modal="false"
      @closed="handleInitDialogClosed">
      <task-progress-panel v-if="runTask" :task="runTask">
        <div
          v-if="runTask.status === 'completed' && runTask.result"
          slot="result"
          class="init-task-result">
          <div>最终日期：{{ runTask.result.date || '—' }}</div>
          <div>净值：{{ runTask.result.nav != null ? Number(runTask.result.nav).toFixed(2) : '—' }}</div>
          <div>交易日数：{{ runTask.result.day_count != null ? runTask.result.day_count : '—' }}</div>
        </div>
      </task-progress-panel>
      <template v-else>
        <el-alert
          title="初始化在后台运行，可关闭弹窗或切换页面；完成后本页自动刷新"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 20px;" />
        <el-form label-width="100px">
          <el-form-item label="启动日期">
            <el-date-picker
              v-model="initStartDate"
              type="date"
              value-format="yyyy-MM-dd"
              placeholder="选择启动日期"
              style="width: 100%;">
            </el-date-picker>
          </el-form-item>
        </el-form>
      </template>
      <span slot="footer" class="dialog-footer">
        <el-button v-if="!runTask" @click="initDialogVisible = false">取消</el-button>
        <el-button v-if="!runTask" type="primary" @click="confirmInit" :loading="initializing">确认初始化</el-button>
        <el-button v-else-if="isTaskActive" type="primary" plain @click="initDialogVisible = false">后台运行</el-button>
        <el-button v-else type="primary" @click="closeInitDialogAndRefresh">关闭</el-button>
      </span>
    </el-dialog>

    <!-- 单参数快捷修改并实盘发布 -->
    <el-dialog
      :title="quickEditTitle"
      :visible.sync="quickEditVisible"
      width="480px"
      :close-on-click-modal="false"
      @closed="resetQuickEdit">
      <div v-loading="quickEditLoading" class="quick-edit-body">
        <p v-if="quickEditHint" class="quick-edit-hint">{{ quickEditHint }}</p>
        <el-input
          v-if="quickEditInputType === 'text'"
          v-model="quickEditValue"
          type="textarea"
          :rows="quickEditTextareaRows"
          placeholder="逗号分隔的交易日窗口，如 20,60,120,250" />
        <el-input-number
          v-else-if="quickEditInputType === 'int'"
          v-model="quickEditNum"
          :min="1"
          :max="10000"
          :step="1"
          controls-position="right"
          style="width: 100%;" />
        <el-input-number
          v-else
          v-model="quickEditNum"
          :min="quickEditNumMin"
          :max="quickEditNumMax"
          :step="quickEditStep"
          :precision="quickEditPrecision"
          controls-position="right"
          style="width: 100%;" />
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="quickEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="quickEditSaving" @click="submitQuickEdit">保存并实盘发布</el-button>
      </span>
    </el-dialog>

    <!-- 底层资产快捷调整并实盘发布 -->
    <el-dialog
      title="调整底层资产"
      :visible.sync="assetsEditVisible"
      width="520px"
      :close-on-click-modal="false"
      @closed="resetAssetsEdit">
      <div v-loading="assetsEditLoading" class="assets-edit-body">
        <p class="quick-edit-hint">
          从资产池选择并加入列表，或移除标签；至少保留一个资产。保存后将更新策略的「选择资产」并执行<strong>实盘发布</strong>（次交易日生效）。
        </p>
        <div class="assets-edit-pick">
          <el-select
            v-model="assetPickCodes"
            multiple
            filterable
            clearable
            collapse-tags
            placeholder="可多选资产后加入列表"
            style="width: 100%;">
            <el-option
              v-for="o in selectableAssetOptions"
              :key="o.code"
              :label="formatAssetOptionLabel(o)"
              :value="o.code" />
          </el-select>
          <el-button
            type="primary"
            plain
            style="margin-left: 8px;"
            :disabled="!assetPickCodes || !assetPickCodes.length"
            @click="addPickedAssets">
            加入
          </el-button>
        </div>
        <div class="assets-edit-tags">
          <span v-if="!assetsEditCodes.length" class="assets-edit-no-tags">列表为空，请至少添加一个资产</span>
          <template v-else>
            <el-tag
              v-for="code in assetsEditCodes"
              :key="'ae-' + code"
              closable
              disable-transitions
              type="info"
              effect="plain"
              class="assets-edit-tag"
              @close="removeAssetCode(code)">
              {{ assetCodeLabel(code) }}
            </el-tag>
          </template>
        </div>
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="assetsEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="assetsEditSaving" @click="submitAssetsEdit">保存并实盘发布</el-button>
      </span>
    </el-dialog>

    <!-- 主观：初始化权重（按底层资产） -->
    <el-dialog
      title="编辑初始化权重"
      :visible.sync="manualInitEditorVisible"
      width="580px"
      custom-class="subjective-editor-dialog"
      :append-to-body="false"
      :close-on-click-modal="false"
      @closed="resetManualInitEditor">
      <div v-loading="manualInitEditorLoading" class="subjective-editor-body">
        <p class="quick-edit-hint">
          为期初建仓设置各底层资产权重（0～100%）。合计建议为 100%；超过 100% 无法保存。可使用滑块或右侧数字微调。
        </p>
        <div v-if="!manualInitRows.length" class="assets-edit-no-tags">无底层资产，请先在上方调整底层资产。</div>
        <div v-for="row in manualInitRows" :key="'mw-' + row.code" class="subjective-editor-row">
          <span class="subjective-editor-label" :title="row.code">{{ subjectiveEditorLabel(row.code) }}</span>
          <el-slider
            v-model="row.weight"
            :min="0"
            :max="1"
            :step="0.01"
            :format-tooltip="formatWeightSliderTooltip"
            class="subjective-editor-slider" />
          <el-input-number
            v-model="row.weight"
            :min="0"
            :max="1"
            :step="0.05"
            :precision="2"
            size="small"
            controls-position="right"
            class="subjective-editor-num" />
        </div>
        <div v-if="manualInitRows.length" class="subjective-sum-bar">
          <span :class="manualInitSumClass">权重合计：{{ manualInitSumPct }}%</span>
          <el-button type="text" size="small" @click="normalizeManualInitRows">归一化到 100%</el-button>
        </div>
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="manualInitEditorVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualInitEditorSaving" @click="submitManualInitEditor">保存并实盘发布</el-button>
      </span>
    </el-dialog>

    <!-- 主观：预设调仓日及权重 -->
    <el-dialog
      title="编辑预设调仓"
      :visible.sync="manualPresetsEditorVisible"
      width="720px"
      custom-class="subjective-editor-dialog"
      :append-to-body="false"
      :close-on-click-modal="false"
      @closed="resetManualPresetsEditor">
      <div v-loading="manualPresetsEditorLoading" class="subjective-editor-body">
        <p class="quick-edit-hint">
          每个调仓日配置当日目标权重；「保存时归一化」或本条内的「归一化到 100%」会按当前比例缩放到合计 100%，且<strong>结果权重保留两位小数</strong>。手动输入、未归一化保存时不做小数位限制。至少保留一条<strong>已选日期</strong>的记录。
        </p>
        <div v-if="!manualPresetCodes.length" class="assets-edit-no-tags">无底层资产，请先在上方调整底层资产。</div>
        <div
          v-for="(row, idx) in manualPresetRows"
          v-else
          :key="'mp-' + idx"
          class="subjective-preset-card">
          <div class="subjective-preset-head">
            <span class="subjective-preset-title">调仓日 {{ idx + 1 }}</span>
            <el-button type="text" class="subjective-preset-remove" @click="removeManualPresetRow(idx)">删除本条</el-button>
          </div>
          <div class="subjective-preset-toolbar">
            <el-date-picker
              v-model="row.date"
              type="date"
              placeholder="选择交易日"
              size="small"
              clearable
              style="width: 168px;" />
            <span class="subjective-preset-switch-label">保存时归一化</span>
            <el-switch v-model="row.auto_normalize" />
          </div>
          <div class="subjective-preset-weights">
            <div class="subjective-preset-weight-actions">
              <el-button type="text" size="small" @click="applyPresetRowNormalize(row)">归一化到 100%</el-button>
              <span class="subjective-preset-weight-actions-hint">按当前比例，保留两位小数</span>
            </div>
            <div v-for="code in manualPresetCodes" :key="'mpw-' + idx + '-' + code" class="subjective-editor-row subjective-editor-row--compact">
              <span class="subjective-editor-label" :title="code">{{ subjectiveEditorLabel(code) }}</span>
              <el-slider
                v-model="row.weights[code]"
                :min="0"
                :max="1"
                :step="0.01"
                :format-tooltip="formatWeightSliderTooltip"
                class="subjective-editor-slider" />
              <el-input-number
                v-model="row.weights[code]"
                :min="0"
                :max="1"
                :step="0.05"
                :precision="4"
                size="small"
                controls-position="right"
                class="subjective-editor-num" />
            </div>
            <div class="subjective-preset-row-sum" :class="manualPresetRowSumClass(row)">
              本条权重合计：{{ manualPresetRowSumPct(row) }}%
            </div>
          </div>
        </div>
        <el-button
          v-if="manualPresetCodes.length"
          type="primary"
          plain
          size="small"
          icon="el-icon-plus"
          style="margin-top: 8px;"
          @click="addManualPresetRow">
          添加调仓日
        </el-button>
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="manualPresetsEditorVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualPresetsEditorSaving" @click="submitManualPresetsEditor">保存并实盘发布</el-button>
      </span>
    </el-dialog>

    <!-- 区域0：监控策略管理（可折叠，常驻页面顶部） -->
    <el-card shadow="never" class="monitor-section monitor-section--full">
      <div slot="header" class="section-header section-header--toggle" @click="strategyListCollapsed = !strategyListCollapsed">
        <span>监控策略管理</span>
        <i :class="strategyListCollapsed ? 'el-icon-arrow-down' : 'el-icon-arrow-up'" style="color:#909399;margin-left:8px;" />
      </div>
      <div v-show="!strategyListCollapsed">
        <div v-if="isTaskActive" class="init-running-banner">
          <i class="el-icon-loading" />
          <span>{{ taskMonitorName }} {{ taskKindLabel }}进行中：{{ taskBannerProgressText }}（{{ runTask.current_date || taskPhaseLabel }}）</span>
          <el-button type="text" @click="initDialogVisible = true">查看进度</el-button>
        </div>
        <MonitoredStrategyList
          ref="strategyList"
          :selected-id="activeMonitorId || ''"
          @view="handleStrategyView"
          @init="handleStrategyInit"
          @run="handleStrategyRun"
          @archive="handleStrategyArchive"
        />
      </div>
    </el-card>

    <!-- 点开策略「查看」后：页签承载 总览 / 操作 / 绩效 / 风控 -->
    <el-tabs v-if="activeMonitorId" v-model="activeTab" type="border-card" class="monitor-tabs">
      <!-- 页签1：总览 -->
      <el-tab-pane name="overview">
        <span slot="label">总览</span>
        <div class="tab-body">
          <!-- 区域1：监控总览 -->
          <el-card shadow="never" class="monitor-section monitor-section--full monitor-section--last">
            <div slot="header" class="section-header">
              <span>监控总览</span>
              <el-select
                v-if="monitoredStrategyOptions.length > 1"
                :value="activeMonitorId"
                size="small"
                style="width: 200px; margin-left: 16px;"
                @change="handleStrategySwitch"
              >
                <el-option
                  v-for="s in monitoredStrategyOptions"
                  :key="s._id"
                  :label="s.display_name"
                  :value="s._id"
                />
              </el-select>
            </div>
            <MonitorDashboard ref="dashboard" :strategy-context="currentStrategy" />
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 页签2：操作 = 操作指令 + 主观调仓 -->
      <el-tab-pane name="operation" lazy>
        <span slot="label">
          操作
          <el-tag v-if="pendingSubjectiveCount > 0" type="warning" size="mini" class="tab-badge">
            {{ pendingSubjectiveCount }}
          </el-tag>
        </span>
        <div class="tab-body">
          <el-card shadow="never" class="monitor-section monitor-section--full monitor-section--last">
            <div slot="header" class="section-header">
              <span>操作指令</span>
            </div>
            <OperationPanel
              ref="operationPanel"
              :strategy-context="currentStrategy"
              @override-added="handleOverrideAdded"
            />
            <div class="op-subjective-divider"></div>
            <div class="section-subtitle section-subtitle--toggle" @click="subjectiveCollapsed = !subjectiveCollapsed">
              <span>主观调仓</span>
              <el-tag v-if="pendingSubjectiveCount > 0" type="warning" size="mini" class="subjective-pending-tag">
                {{ pendingSubjectiveCount }} 条待执行
              </el-tag>
              <i :class="subjectiveCollapsed ? 'el-icon-arrow-down' : 'el-icon-arrow-up'" style="color:#909399;margin-left:8px;" />
            </div>
            <div v-show="!subjectiveCollapsed">
              <SubjectiveOverride ref="subjective" :strategy-context="currentStrategy" />
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 页签3：绩效 = 统一周期 + 净值走势 + 持仓 / 每日收益 / 归因 / 底层资产风险 -->
      <el-tab-pane name="performance" lazy>
        <span slot="label">绩效</span>
        <div class="tab-body" v-loading="performanceLoading">
          <!-- 页面级统一周期：本页所有数据均按此周期展示 -->
          <div class="period-bar">
            <span class="period-label">选择周期</span>
            <el-date-picker
              v-model="performanceStart"
              type="date"
              value-format="yyyy-MM-dd"
              placeholder="开始日期"
              size="small"
              :picker-options="startPickerOptions"
              style="width: 150px;"
              @change="handlePerformanceRangeChange" />
            <span class="period-separator">至</span>
            <el-date-picker
              v-model="performanceEnd"
              type="date"
              value-format="yyyy-MM-dd"
              placeholder="结束日期"
              size="small"
              :picker-options="endPickerOptions"
              style="width: 150px;"
              @change="handlePerformanceRangeChange" />
            <el-button-group class="period-quick">
              <el-button size="mini" :type="performanceQuick === '1m' ? 'primary' : ''" @click="applyQuickRange('1m')">近1月</el-button>
              <el-button size="mini" :type="performanceQuick === '3m' ? 'primary' : ''" @click="applyQuickRange('3m')">近3月</el-button>
              <el-button size="mini" :type="performanceQuick === '1y' ? 'primary' : ''" @click="applyQuickRange('1y')">近1年</el-button>
              <el-button size="mini" :type="performanceQuick === 'all' ? 'primary' : ''" @click="applyQuickRange('all')">全部</el-button>
            </el-button-group>
            <span v-if="performanceRangeHint" class="period-hint">{{ performanceRangeHint }}</span>
          </div>
          <!-- 首次进入/缓存重建期间只显示加载态，避免子组件把加载中误渲染成「暂无数据」 -->
          <div v-if="!performancePanel" class="performance-state">
            <i v-if="performanceLoading" class="el-icon-loading"></i>
            <span>{{ performanceLoading ? '正在加载绩效数据…' : '暂无可展示的绩效数据；若尚未初始化，请先运行监控初始化或日常运行' }}</span>
          </div>
          <template v-else>
          <!-- 净值走势（实际口径实线 + 模型口径虚线） -->
          <el-card shadow="never" class="monitor-section monitor-section--full">
            <div slot="header" class="section-header">
              <span>净值走势</span>
              <span v-if="performancePanel && performancePanel.has_model_track" class="section-header__hint">
                模型口径为灰色虚线
              </span>
            </div>
            <NavHistory ref="navHistory" :strategy-context="currentStrategy" />
          </el-card>

          <div class="monitor-grid monitor-grid--performance">
            <!-- 行1左：持仓明细 -->
            <el-card shadow="never" class="monitor-section performance-card--row1">
              <div slot="header" class="section-header">
                <span>持仓明细</span>
                <span class="section-header__hint">{{ positionsSnapshotHint }}</span>
              </div>
              <Positions ref="positions" />
            </el-card>

            <!-- 行1右：每日收益统计 -->
            <el-card shadow="never" class="monitor-section performance-card--row1">
              <div slot="header" class="section-header">
                <span>每日收益统计</span>
                <span class="section-header__hint">
                  共 {{ performanceTradingDays }} 个交易日 · 最新在前 · 每页 20 条
                </span>
              </div>
              <ReturnsTable ref="returnsTable" />
            </el-card>

            <!-- 行2：收益归因（所选周期累计） -->
            <el-card shadow="never" class="monitor-section monitor-section--span2">
              <div slot="header" class="section-header">
                <span>收益归因</span>
                <span class="section-header__hint">{{ attributionHeaderHint }}</span>
              </div>
              <AttributionPanel ref="attributionPanel" />
            </el-card>

            <!-- 行3：底层资产风险（相关性 + 波动率） -->
            <el-card shadow="never" class="monitor-section monitor-section--span2">
              <div slot="header" class="section-header">
                <span>底层资产风险</span>
                <span class="section-header__hint">{{ assetRiskHeaderHint }}</span>
              </div>
              <AssetAnalysis ref="assetAnalysis" />
            </el-card>
          </div>

          <!-- 策略自定义插槽：绩效页专属组件（如因子暴露、希腊字母），未声明时不渲染 -->
          <DynamicSlots v-if="performanceSlots.length" :slots="performanceSlots" class="performance-dynamic-slots" />
          </template>
        </div>
      </el-tab-pane>

      <!-- 页签4：风控 = 信号监控 + 事件日志 + 实盘发布记录 -->
      <el-tab-pane name="signals" lazy>
        <span slot="label">风控</span>
        <div class="tab-body">
          <!-- 信号监控 -->
          <el-card shadow="never" class="monitor-section monitor-section--full">
            <div slot="header" class="section-header">
              <span>信号监控</span>
            </div>
            <Signals ref="signals" :strategy-context="currentStrategy" />
          </el-card>

          <!-- 风险预警：波动率对比 / 相关性反转 / 停更跳过（策略与组合共用） -->
          <el-card shadow="never" class="monitor-section monitor-section--full">
            <div slot="header" class="section-header">
              <span>风险预警</span>
              <span class="section-header__hint">波动率异常、相关性反转与行情停更提示</span>
            </div>
            <RiskAlerts ref="riskAlerts" :monitor-id="activeMonitorId || ''" :batch-id="currentBatchId || ''" />
          </el-card>

          <div class="monitor-grid">
            <!-- 事件日志：无实盘发布记录时占满整行 -->
            <el-card
              shadow="never"
              class="monitor-section"
              :class="{ 'monitor-section--span2': !showPublishRecords }">
              <div slot="header" class="section-header">
                <span>事件日志</span>
              </div>
              <EventLog ref="eventLog" />
            </el-card>

            <!-- 实盘发布记录（研究员策略无实盘发布，不渲染以避免用 monitor_id 请求策略模型） -->
            <el-card v-if="showPublishRecords" shadow="never" class="monitor-section">
              <div slot="header" class="section-header">
                <span>实盘发布记录</span>
              </div>
              <LivePublishRecords ref="publishLog" :model-id="activeMonitorId" />
            </el-card>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script>
import { mapActions, mapGetters, mapState } from 'vuex';
import dayjs from 'dayjs';
import { getLiveEligibleForMonitor, getStrategyModel } from '@/api/strategy';
import { getAssetOptions } from '@/api/asset';
import MonitorDashboard from './Index.vue';
import NavHistory from './NavHistory.vue';
import Positions from './Positions.vue';
import ReturnsTable from './ReturnsTable.vue';
import AttributionPanel from './AttributionPanel.vue';
import Signals from './Signals.vue';
import RiskAlerts from './RiskAlerts.vue';
import SubjectiveOverride from './SubjectiveOverride.vue';
import OperationPanel from './OperationPanel.vue';
import AssetAnalysis from './AssetAnalysis.vue';
import EventLog from './EventLog.vue';
import LivePublishRecords from './LivePublishRecords.vue';
import SubjectiveManualWeightsSnapshot from './SubjectiveManualWeightsSnapshot.vue';
import MonitoredStrategyList from './MonitoredStrategyList.vue';
import DynamicSlots from '@/components/monitor/DynamicSlots.vue';
import TaskProgressPanel from '@/components/TaskProgressPanel.vue';
import { resolveCustomComponents } from '@/config/monitor';
import { normalizeWeightsToTwoDecimalSumOne, formatWeightSliderTooltip } from '@/utils/subjectiveWeights';
import { isRiskBudgetTargetVolTemplateCode } from '@/utils/strategyTemplateFlags';
import {
  taskKindLabel as resolveTaskKindLabel,
  taskPhaseLabel as resolveTaskPhaseLabel,
  taskBannerProgressText as resolveTaskBannerProgressText
} from '@/utils/taskProgress';

/** 批次触发方式（与后端 BatchRunMode 同值） */
const RUN_MODE_LABEL = {
  init: '初始化',
  daily: '日常推进',
  range: '区间推演'
};

/** 批次状态（与后端 BatchStatus 同值） */
const BATCH_STATUS_LABEL = {
  pending: '等待执行',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  interrupted: '已中断'
};

export default {
  name: 'MonitorCenter',
  components: {
    MonitorDashboard,
    NavHistory,
    Positions,
    ReturnsTable,
    AttributionPanel,
    Signals,
    RiskAlerts,
    SubjectiveOverride,
    OperationPanel,
    AssetAnalysis,
    EventLog,
    LivePublishRecords,
    SubjectiveManualWeightsSnapshot,
    MonitoredStrategyList,
    DynamicSlots,
    TaskProgressPanel
  },
  data() {
    return {
      initDialogVisible: false,
      initStartDate: '2014-02-10',
      /** 主观策略：与回测一致，在每档调仓日当日完成后暂停以便查看绩效 */
      manualPresetStepOptIn: true,
      initializing: false,
      running: false,
      continuingStep: false,
      eligibleLoading: true,
      eligibleStrategies: [],
      quickEditVisible: false,
      quickEditLoading: false,
      quickEditSaving: false,
      quickEditKey: null,
      quickEditTitle: '',
      quickEditHint: '',
      quickEditInputType: 'number',
      quickEditValue: '',
      quickEditNum: 0,
      quickEditNumMin: 0,
      quickEditNumMax: 100,
      quickEditStep: 0.01,
      quickEditPrecision: 4,
      quickEditSourceModel: null,
      quickEditTextareaRows: 3,
      assetsEditVisible: false,
      assetsEditLoading: false,
      assetsEditSaving: false,
      assetsEditCodes: [],
      assetOptionsList: [],
      assetPickCodes: [],
      manualInitEditorVisible: false,
      manualInitEditorLoading: false,
      manualInitEditorSaving: false,
      manualInitEditorModel: null,
      manualInitRows: [],
      subjectiveOptsCache: [],
      manualPresetsEditorVisible: false,
      manualPresetsEditorLoading: false,
      manualPresetsEditorSaving: false,
      manualPresetsEditorModel: null,
      manualPresetRows: [],
      manualPresetCodes: [],
      selectedMonitoredStrategy: null,
      /** 当前页签：总览 / 操作 / 绩效 / 信号与记录 */
      activeTab: 'overview',
      /** 绩效页快捷周期标记：1m / 3m / 1y / all / custom */
      performanceQuick: 'all',
      performanceLoading: false,
      strategyListCollapsed: false,
      /** 主观调仓区默认折叠，无操作时直接看到绩效；存在待执行指令时自动展开一次 */
      subjectiveCollapsed: true,
      subjectiveAutoExpanded: false
    };
  },
  computed: {
    ...mapGetters('monitor', [
      'activeMonitorId', 'currentBatchId', 'batchList',
      'runTask', 'isTaskActive', 'lastFinishedTask'
    ]),
    ...mapState('monitor', [
      'monitorState', 'subjectiveOverrides', 'performancePanel', 'performanceRange',
      'batchesLoading', 'taskFinishedAt'
    ]),
    /** 统一周期：开始/结束日期存 store，切换策略时自动清空 */
    performanceStart: {
      get() {
        return this.performanceRange.start;
      },
      set(val) {
        this.$store.commit('monitor/SET_PERFORMANCE_RANGE', {
          start: val || null,
          end: this.performanceRange.end
        });
      }
    },
    performanceEnd: {
      get() {
        return this.performanceRange.end;
      },
      set(val) {
        this.$store.commit('monitor/SET_PERFORMANCE_RANGE', {
          start: this.performanceRange.start,
          end: val || null
        });
      }
    },
    /** 开始日期不得晚于结束日期 */
    startPickerOptions() {
      const end = this.performanceRange.end;
      return end ? { disabledDate: d => dayjs(d).format('YYYY-MM-DD') > end } : {};
    },
    /** 结束日期不得早于开始日期 */
    endPickerOptions() {
      const start = this.performanceRange.start;
      return start ? { disabledDate: d => dayjs(d).format('YYYY-MM-DD') < start } : {};
    },
    performanceRangeHint() {
      const r = this.performancePanel && this.performancePanel.range;
      if (!r || !r.start) return '';
      const clamp = r.clamped ? '（已裁剪至可用数据范围）' : '';
      return `当前展示 ${r.start} 至 ${r.end}${clamp}`;
    },
    /** 持仓卡头部：区间末快照日 + 净值 */
    positionsSnapshotHint() {
      const p = (this.performancePanel && this.performancePanel.positions) || {};
      if (!p.date) return '暂无持仓快照';
      const nav = p.nav === null || p.nav === undefined ? '—' : Number(p.nav).toFixed(4);
      return `快照 ${p.date} · 净值 ${nav}`;
    },
    performanceTradingDays() {
      const m = (this.performancePanel && this.performancePanel.metrics) || {};
      return m.trading_days || 0;
    },
    /** 收益归因卡头部：区间 + 交易日数 + 组合区间收益率 */
    attributionHeaderHint() {
      const attr = (this.performancePanel && this.performancePanel.attribution) || {};
      if (!attr.start_date) return '';
      const total = attr.total_return === null || attr.total_return === undefined
        ? ''
        : ` · 合计 ${attr.total_return >= 0 ? '+' : ''}${Number(attr.total_return).toFixed(2)}%`;
      return `${attr.start_date} 至 ${attr.end_date} · ${attr.trading_days} 个交易日${total}`;
    },
    /** 底层资产风险卡头部：区间 + 样本交易日 + 资产数 */
    assetRiskHeaderHint() {
      const analysis = (this.performancePanel && this.performancePanel.asset_analysis) || {};
      if (!analysis.start_date) return '';
      const info = (analysis.correlation && analysis.correlation.asset_info) || [];
      return `${analysis.start_date} 至 ${analysis.end_date} · 样本 ${analysis.trading_days} 个交易日 · 资产 ${info.length} 项`;
    },
    hasEligibleStrategies() {
      return this.eligibleStrategies.length > 0;
    },
    canOperateMonitor() {
      return !!this.activeMonitorId;
    },
    monitoredStrategyOptions() {
      const list = this.$refs.strategyList;
      return list ? list.strategies : [];
    },
    canClickLiveParams() {
      return (
        !!this.activeMonitorId &&
        this.activeMonitorId !== 'default' &&
        !!this.currentStrategy &&
        !this.isResearcherMonitor
      );
    },
    currentStrategy() {
      if (!this.activeMonitorId) return null;
      return this.eligibleStrategies.find(s => s.id === this.activeMonitorId)
        || this.selectedMonitoredStrategy
        || null;
    },
    /** 绩效页策略自定义插槽：由策略元数据 custom_components 声明，未声明时为空数组 */
    performanceSlots() {
      return resolveCustomComponents('performance', this.currentStrategy);
    },
    /** 研究员策略（hybrid_12 / sharpe_18）：完全独立自主，无策略模型与实盘发布，不触发任何 strategy-models 请求 */
    isResearcherMonitor() {
      const s = this.currentStrategy;
      return !!(s && s.source_type === 'researcher');
    },
    /** 目标波动率预算策略（含旧 code 兼容）：部分实盘参数固定，不在监控页快捷编辑或展示 */
    isRiskBudgetTargetVolLiveStrategy() {
      const s = this.currentStrategy;
      return !!(s && isRiskBudgetTargetVolTemplateCode(s.template_code));
    },
    /** 夏普率风险预算策略（旧 code）：实盘参数已固化，日常监控不展示 */
    isSharpeRiskBudgetLiveStrategy() {
      const s = this.currentStrategy;
      return !!(s && s.template_code === 'sharpe_risk_budget');
    },
    /** 底层资产标签：优先接口返回的展示名，与 live_effective_assets 同序 */
    effectiveAssetTags() {
      const s = this.currentStrategy;
      if (!s || !s.live_effective_assets || !s.live_effective_assets.length) {
        return [];
      }
      const assets = s.live_effective_assets;
      const labels = s.live_effective_asset_labels;
      if (Array.isArray(labels) && labels.length === assets.length) {
        return labels;
      }
      const map = s.asset_names || {};
      return assets.map(code => map[code] || code);
    },
    /** 结构化实盘参数（不含资产名单），用于监控页可视化 */
    liveEffectiveParams() {
      const s = this.currentStrategy;
      return s && s.live_effective_params ? s.live_effective_params : null;
    },
    /** 是否展示动量/反转窗口块（与接口 live_effective_params 字段一致） */
    hasLiveWindowParams() {
      const p = this.liveEffectiveParams;
      if (!p || p.is_manual_allocation) return false;
      const hideHist = this.isRiskBudgetTargetVolLiveStrategy;
      const hist = !hideHist && (
        (p.min_history_momentum != null && p.min_history_momentum !== '') ||
        (p.min_history_reversal != null && p.min_history_reversal !== '')
      );
      return !!(
        p.mom_windows ||
        p.reversal_windows ||
        p.macd_windows ||
        (p.macd_long_window != null && p.macd_long_window !== '') ||
        hist
      );
    },
    isManualAllocationMonitor() {
      const p = this.liveEffectiveParams;
      return !!(p && p.is_manual_allocation);
    },
    /** 波动率监控区的显隐由 Signals 内部按后端返回的 vol_reset.enabled 决定，
        不再在此按 template_code 维护白名单（新增模板不会再漏配） */
    /** 服务端落库的步进暂停标记：有则显示「继续执行」 */
    manualPresetStepPaused() {
      const ms = this.monitorState;
      return !!(this.isManualAllocationMonitor && ms && ms.manual_preset_step_pending);
    },
    /** 步进暂停期间禁止再次初始化，避免清空已推演状态 */
    blockInitDuringManualPresetPause() {
      return this.isManualAllocationMonitor && this.manualPresetStepPaused;
    },
    /** 供 SubjectiveManualWeightsSnapshot：箭头函数绑定本组件 this */
    subjectiveSnapshotResolveLabel() {
      return code => this.subjectiveEditorLabel(code);
    },
    selectableAssetOptions() {
      const inList = new Set(this.assetsEditCodes);
      return (this.assetOptionsList || []).filter(o => o && o.code && !inList.has(o.code));
    },
    manualInitSumRatio() {
      return this.manualInitRows.reduce((s, r) => s + (Number(r.weight) || 0), 0);
    },
    manualInitSumPct() {
      return (this.manualInitSumRatio * 100).toFixed(1);
    },
    manualInitSumClass() {
      return this.manualInitSumRatio > 1.00001 ? 'subjective-sum--warn' : '';
    },
    pendingSubjectiveCount() {
      const list = this.subjectiveOverrides || [];
      return list.filter(o => o.status === 'pending').length;
    },
    /** 实盘发布记录卡片是否展示：研究员策略无实盘发布，不渲染以避免用 monitor_id 请求策略模型 */
    showPublishRecords() {
      return !!(
        this.currentStrategy &&
        this.activeMonitorId &&
        this.activeMonitorId !== 'default' &&
        !this.isResearcherMonitor
      );
    },
    /** 后台任务类型文案：init / run / run-range 共用同一套进度展示 */
    taskKindLabel() {
      return resolveTaskKindLabel(this.runTask);
    },
    /** 弹窗标题：无任务时是初始化表单，有任务时是进度详情（可能是日常运行） */
    taskDialogTitle() {
      return this.runTask ? `${this.taskKindLabel}进度` : '初始化监控';
    },
    /** 页面横幅进度文案：引擎类路径无总量时不给百分比，避免长期停在 0% */
    taskBannerProgressText() {
      return resolveTaskBannerProgressText(this.runTask);
    },
    taskPhaseLabel() {
      return resolveTaskPhaseLabel(this.runTask);
    },
    taskMonitorName() {
      const s = this.selectedMonitoredStrategy;
      return (s && (s.name || s.id)) || '当前策略';
    },
    /** 当前展示批次的摘要（批次切换器右侧提示用） */
    currentBatchSummary() {
      const id = this.currentBatchId;
      if (!id) return null;
      return (this.batchList || []).find(b => b.batch_id === id) || null;
    },
    currentBatchHint() {
      const b = this.currentBatchSummary;
      if (!b) {
        // 未锁定到具体批次时，展示端点读的是后端解析出的最新 completed 批次
        return this.currentBatchId ? '' : '跟随最新完成批次';
      }
      const parts = [
        RUN_MODE_LABEL[b.run_mode] || b.run_mode,
        (b.start_date && b.end_date) ? `${b.start_date} ~ ${b.end_date}` : (b.data_date || ''),
        BATCH_STATUS_LABEL[b.status] || b.status,
        b.duration_ms != null ? `耗时 ${Math.max(1, Math.round(Number(b.duration_ms) / 1000))} 秒` : ''
      ];
      return parts.filter(Boolean).join(' · ');
    }
  },
  watch: {
    /** 首次加载后若存在待执行主观指令则自动展开（仅一次，之后尊重手动折叠） */
    pendingSubjectiveCount: {
      immediate: true,
      handler(n) {
        if (!this.subjectiveAutoExpanded && n > 0) {
          this.subjectiveCollapsed = false;
          this.subjectiveAutoExpanded = true;
        }
      }
    },
    /** 切页签后重算图表尺寸：隐藏页签内 ECharts 容器宽度为 0，需按可见宽度重绘 */
    activeTab(tab) {
      this.$nextTick(() => {
        window.dispatchEvent(new Event('resize'));
      });
      if (tab === 'performance') {
        this.loadPerformancePanel();
      }
    },
    /** 切换监控策略时 store 会清空统一周期，快捷项同步回到「全部」 */
    activeMonitorId() {
      this.performanceQuick = 'all';
    },
    /**
     * 后台任务到达终态：store 已先一步把展示批次切到新批次并刷新了批次列表，
     * 此处只负责重载各展示区并给出结果反馈。时间戳而非 status 作为触发源，
     * 连续两次 completed 也能触发。
     */
    taskFinishedAt(seq) {
      if (!seq) return;
      this.onTaskFinished();
    }
  },
  async created() {
    await this.loadEligibleContext();
  },
  beforeDestroy() {
    // 任务在服务端继续跑，离开页面只停本地轮询；回来时由 resumeActiveTaskAction 接上
    this.stopTaskPolling();
  },
  methods: {
    ...mapActions('monitor', [
      'initMonitorAction', 'runMonitorAction', 'setActiveMonitorContext',
      'fetchPerformancePanel', 'fetchBatches', 'setCurrentBatchId',
      'resumeActiveTaskAction', 'stopTaskPolling'
    ]),
    formatStrategyOption(s) {
      if (s.live_effective_params && s.live_effective_params.is_manual_allocation) {
        return `${s.name || s.id}（${s.template_code || ''} · 主观配置）`;
      }
      const selMap = { 'hybrid': '混合动量', 'sharpe': '夏普率选择器' };
      const sel = selMap[s.selector_type] || s.selector_type || '';
      return `${s.name || s.id}（${s.template_code || ''}${sel ? ' · ' + sel : ''}）`;
    },
    assetClassTagType(assetClass) {
      const map = { '权益': 'primary', '固定收益': 'success', '大宗商品': 'warning', '其他': 'info' };
      return map[assetClass] || 'info';
    },
    formatStrategyDate(d) {
      return d ? dayjs(d).format('YYYY-MM-DD') : '-';
    },
    async loadEligibleContext() {
      this.eligibleLoading = true;
      try {
        const res = await getLiveEligibleForMonitor();
        const body = res && res.data !== undefined ? res.data : res;
        const all = (body && body.strategies) ? body.strategies : [];
        // 过滤掉旧的 config 基线
        this.eligibleStrategies = all.filter(s => !s.is_config_baseline && s.id !== 'default');
      } catch (e) {
        console.error(e);
        this.eligibleStrategies = [];
      } finally {
        this.eligibleLoading = false;
      }
    },

    goEditLiveParams() {
      if (!this.canClickLiveParams) return;
      this.$router.push({
        name: 'StrategyModelDetail',
        params: { id: this.activeMonitorId },
        query: { fromMonitor: '1' }
      });
    },
    /** 与策略详情实盘操作一致，供变更日志、实盘记录写入操作人 */
    liveOperator() {
      return (
        this.$store.getters['user/userName'] ||
        this.$store.state.user?.userInfo?.name ||
        this.$store.state.user?.userInfo?.username ||
        '未知'
      );
    },
    cloneDeep(obj) {
      if (obj === null || typeof obj !== 'object') return obj;
      return JSON.parse(JSON.stringify(obj));
    },
    patchParameters(baseParams, patch) {
      const p = this.cloneDeep(baseParams || {});
      Object.keys(patch).forEach(k => {
        p[k] = patch[k];
      });
      if (Array.isArray(p.items)) {
        Object.keys(patch).forEach(key => {
          const idx = p.items.findIndex(it => it && it.name === key);
          const row = { name: key, value: patch[key] };
          if (idx >= 0) p.items[idx] = { ...p.items[idx], ...row };
          else p.items.push(row);
        });
      }
      return p;
    },
    resetQuickEdit() {
      this.quickEditKey = null;
      this.quickEditHint = '';
      this.quickEditSourceModel = null;
      this.quickEditTextareaRows = 3;
    },
    resetAssetsEdit() {
      this.assetsEditCodes = [];
      this.assetPickCodes = [];
    },
    formatAssetOptionLabel(o) {
      if (!o) return '';
      const n = o.name || o.code || '';
      const c = o.code || '';
      return c && n !== c ? `${n}（${c}）` : (n || c);
    },
    assetCodeLabel(code) {
      const c = String(code || '').trim();
      if (!c) return '';
      const o = (this.assetOptionsList || []).find(x => x && x.code === c);
      if (o && o.name && o.name !== c) return `${o.name}（${c}）`;
      return c;
    },
    addPickedAssets() {
      const picked = Array.isArray(this.assetPickCodes) ? [...this.assetPickCodes] : [];
      if (!picked.length) return;
      const seen = new Set(this.assetsEditCodes.map(x => String(x).trim()));
      picked.forEach(c => {
        const s = c != null ? String(c).trim() : '';
        if (s && !seen.has(s)) {
          this.assetsEditCodes.push(s);
          seen.add(s);
        }
      });
      this.assetPickCodes = [];
    },
    removeAssetCode(code) {
      const c = String(code || '').trim();
      if (!c) return;
      const i = this.assetsEditCodes.findIndex(x => String(x).trim() === c);
      if (i >= 0) this.assetsEditCodes.splice(i, 1);
    },
    /** 发布即冻结的统一阻断提示：配置变更必须回到策略模型页完成 */
    blockLiveConfigEdit() {
      this.$message.warning(
        '策略已发布，配置已冻结：请到「策略模型」页取消发布，修改后重新发布并实盘发布，日常监控才会运行新逻辑'
      );
    },
    async openAssetsEdit() {
      if (!this.canClickLiveParams || !this.activeMonitorId) return;
      this.assetsEditVisible = true;
      this.assetsEditLoading = true;
      this.assetPickCodes = [];
      try {
        const [modelRes, optRes] = await Promise.all([
          getStrategyModel(this.activeMonitorId),
          getAssetOptions()
        ]);
        const model = modelRes && modelRes.data !== undefined ? modelRes.data : modelRes;
        const opts = optRes && optRes.data !== undefined ? optRes.data : optRes;
        this.assetOptionsList = Array.isArray(opts) ? opts : [];
        let codes = [];
        if (model && Array.isArray(model.asset_codes) && model.asset_codes.length) {
          codes = model.asset_codes.map(x => String(x).trim()).filter(Boolean);
        } else if (this.currentStrategy && Array.isArray(this.currentStrategy.live_effective_assets)) {
          codes = this.currentStrategy.live_effective_assets.map(x => String(x).trim()).filter(Boolean);
        }
        this.assetsEditCodes = [...codes];
      } catch (e) {
        console.error(e);
        this.$message.error('加载策略或资产列表失败');
        this.assetsEditVisible = false;
      } finally {
        this.assetsEditLoading = false;
      }
    },
    async submitAssetsEdit() {
      // 发布即冻结：底层资产属于发布快照内容，监控页不再直接改写
      this.blockLiveConfigEdit();
    },
    formatWeightSliderTooltip,
    subjectiveEditorLabel(code) {
      const c = String(code || '').trim();
      if (!c) return '';
      const s = this.currentStrategy;
      const map = s && s.asset_names;
      if (map && map[c]) return `${map[c]}（${c}）`;
      const list =
        this.subjectiveOptsCache && this.subjectiveOptsCache.length
          ? this.subjectiveOptsCache
          : this.assetOptionsList;
      const o = (list || []).find(x => x && x.code === c);
      if (o && o.name && o.name !== c) return `${o.name}（${c}）`;
      return c;
    },
    onSubjectiveSnapshotInitClick() {
      if (!this.canClickLiveParams) return;
      this.openManualInitEditor();
    },
    onSubjectiveSnapshotPresetsClick() {
      if (!this.canClickLiveParams) return;
      this.openManualPresetsEditor();
    },
    normalizeManualInitRows() {
      const t = this.manualInitSumRatio;
      if (t <= 0) {
        this.$message.warning('合计为 0，无法归一化');
        return;
      }
      this.manualInitRows.forEach(r => {
        r.weight = (Number(r.weight) || 0) / t;
      });
    },
    resetManualInitEditor() {
      this.manualInitEditorModel = null;
      this.manualInitRows = [];
    },
    async openManualInitEditor() {
      if (!this.canClickLiveParams || !this.activeMonitorId) return;
      this.manualInitEditorVisible = true;
      this.manualInitEditorLoading = true;
      try {
        const [modelRes, optRes] = await Promise.all([
          getStrategyModel(this.activeMonitorId),
          getAssetOptions()
        ]);
        const model = modelRes && modelRes.data !== undefined ? modelRes.data : modelRes;
        const opts = optRes && optRes.data !== undefined ? optRes.data : optRes;
        this.subjectiveOptsCache = Array.isArray(opts) ? opts : [];
        if (!model) {
          this.$message.error('无法加载策略模型');
          this.manualInitEditorVisible = false;
          return;
        }
        this.manualInitEditorModel = model;
        let codes = [];
        if (Array.isArray(model.asset_codes) && model.asset_codes.length) {
          codes = model.asset_codes.map(x => String(x).trim()).filter(Boolean);
        } else if (this.currentStrategy && Array.isArray(this.currentStrategy.live_effective_assets)) {
          codes = this.currentStrategy.live_effective_assets.map(x => String(x).trim()).filter(Boolean);
        }
        const mw = (model.parameters && model.parameters.manual_weights) || {};
        this.manualInitRows = codes.map(c => ({
          code: c,
          weight: mw[c] != null ? Number(mw[c]) : 0
        }));
      } catch (e) {
        console.error(e);
        this.$message.error('加载策略失败');
        this.manualInitEditorVisible = false;
      } finally {
        this.manualInitEditorLoading = false;
      }
    },
    async submitManualInitEditor() {
      // 发布即冻结：初始化权重属于发布快照内容，监控页不再直接改写
      this.blockLiveConfigEdit();
    },
    mergePresetWeights(src, codes) {
      const w = {};
      codes.forEach(c => {
        w[c] = src && src[c] != null ? Number(src[c]) : 0;
      });
      return w;
    },
    normalizeWeightsToTwoDecimalSumOne,
    applyPresetRowNormalize(row) {
      if (!row || !row.weights || !this.manualPresetCodes.length) return;
      const w = {};
      this.manualPresetCodes.forEach(c => {
        w[c] = Number(row.weights[c]) || 0;
      });
      const t = this.manualPresetCodes.reduce((s, c) => s + w[c], 0);
      if (t <= 0) {
        this.$message.warning('本条权重合计为 0，无法归一化');
        return;
      }
      const out = this.normalizeWeightsToTwoDecimalSumOne(w, this.manualPresetCodes);
      this.manualPresetCodes.forEach(c => {
        this.$set(row.weights, c, out[c]);
      });
    },
    buildEmptyPresetRow(codes) {
      return { date: null, auto_normalize: false, weights: this.mergePresetWeights({}, codes) };
    },
    /** 后端日期可能是 ISO/含时间等，转为本地 Date 供 el-date-picker（不用 value-format 时绑定 Date，避免无法改选） */
    presetDateToPicker(val) {
      if (val == null || val === '') return null;
      if (val instanceof Date && !Number.isNaN(val.getTime())) return val;
      const s = String(val).trim();
      const ymd = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
      if (ymd) {
        const y = parseInt(ymd[1], 10);
        const mo = parseInt(ymd[2], 10) - 1;
        const da = parseInt(ymd[3], 10);
        return new Date(y, mo, da);
      }
      const d = dayjs(s);
      return d.isValid() ? d.toDate() : null;
    },
    presetPickerToYmd(val) {
      if (val == null || val === '') return '';
      if (val instanceof Date && !Number.isNaN(val.getTime())) {
        const y = val.getFullYear();
        const m = String(val.getMonth() + 1).padStart(2, '0');
        const d = String(val.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
      }
      const s = String(val).trim();
      const ymd = s.match(/^(\d{4}-\d{2}-\d{2})/);
      return ymd ? ymd[1] : '';
    },
    manualPresetRowSumRatio(row) {
      if (!row || !row.weights) return 0;
      return this.manualPresetCodes.reduce((s, c) => s + (Number(row.weights[c]) || 0), 0);
    },
    manualPresetRowSumPct(row) {
      return (this.manualPresetRowSumRatio(row) * 100).toFixed(1);
    },
    manualPresetRowSumClass(row) {
      const r = this.manualPresetRowSumRatio(row);
      return r > 1.00001 && !row.auto_normalize ? 'subjective-sum--warn' : '';
    },
    addManualPresetRow() {
      this.manualPresetRows.push(this.buildEmptyPresetRow(this.manualPresetCodes));
    },
    removeManualPresetRow(idx) {
      if (idx < 0 || idx >= this.manualPresetRows.length) return;
      this.manualPresetRows.splice(idx, 1);
      if (!this.manualPresetRows.length && this.manualPresetCodes.length) {
        this.manualPresetRows.push(this.buildEmptyPresetRow(this.manualPresetCodes));
      }
    },
    resetManualPresetsEditor() {
      this.manualPresetsEditorModel = null;
      this.manualPresetRows = [];
      this.manualPresetCodes = [];
    },
    async openManualPresetsEditor() {
      if (!this.canClickLiveParams || !this.activeMonitorId) return;
      this.manualPresetsEditorVisible = true;
      this.manualPresetsEditorLoading = true;
      try {
        const [modelRes, optRes] = await Promise.all([
          getStrategyModel(this.activeMonitorId),
          getAssetOptions()
        ]);
        const model = modelRes && modelRes.data !== undefined ? modelRes.data : modelRes;
        const opts = optRes && optRes.data !== undefined ? optRes.data : optRes;
        this.subjectiveOptsCache = Array.isArray(opts) ? opts : [];
        if (!model) {
          this.$message.error('无法加载策略模型');
          this.manualPresetsEditorVisible = false;
          return;
        }
        let codes = [];
        if (Array.isArray(model.asset_codes) && model.asset_codes.length) {
          codes = model.asset_codes.map(x => String(x).trim()).filter(Boolean);
        } else if (this.currentStrategy && Array.isArray(this.currentStrategy.live_effective_assets)) {
          codes = this.currentStrategy.live_effective_assets.map(x => String(x).trim()).filter(Boolean);
        }
        this.manualPresetsEditorModel = model;
        this.manualPresetCodes = codes;
        const raw = model.parameters && model.parameters.manual_weight_adjustments;
        const list = Array.isArray(raw) ? this.cloneDeep(raw) : [];
        if (list.length) {
          this.manualPresetRows = list.map(item => ({
            date: this.presetDateToPicker(item.date),
            auto_normalize: !!item.auto_normalize,
            weights: this.mergePresetWeights((item.weights && typeof item.weights === 'object' ? item.weights : {}) || {}, codes)
          }));
        } else {
          this.manualPresetRows = [this.buildEmptyPresetRow(codes)];
        }
      } catch (e) {
        console.error(e);
        this.$message.error('加载策略失败');
        this.manualPresetsEditorVisible = false;
      } finally {
        this.manualPresetsEditorLoading = false;
      }
    },
    async submitManualPresetsEditor() {
      // 发布即冻结：预设调仓属于发布快照内容，监控页不再直接改写
      this.blockLiveConfigEdit();
    },
    async openQuickEdit(rawKey) {
      if (!this.canClickLiveParams || !this.activeMonitorId) return;
      if (
        this.isRiskBudgetTargetVolLiveStrategy &&
        (rawKey === 'vol_reset' || rawKey === 'min_history_days' || rawKey === 'min_history_reversal_hint')
      ) {
        return;
      }
      const key = rawKey === 'min_history_reversal_hint' ? 'reversal_windows' : rawKey;
      const meta = this.quickEditMeta(key);
      if (!meta) return;
      this.quickEditKey = key;
      this.quickEditTitle = meta.title;
      this.quickEditHint = rawKey === 'min_history_reversal_hint'
        ? '反转最小历史由「反转」两档窗口决定，请编辑反转窗口（两档、逗号分隔）。'
        : (meta.hint || '');
      this.quickEditInputType = meta.inputType;
      this.quickEditTextareaRows = meta.textareaRows != null ? meta.textareaRows : 3;
      this.quickEditVisible = true;
      this.quickEditLoading = true;
      try {
        const res = await getStrategyModel(this.activeMonitorId);
        const model = res && res.data !== undefined ? res.data : res;
        if (!model) {
          this.$message.error('无法加载策略模型');
          this.quickEditVisible = false;
          return;
        }
        this.quickEditSourceModel = model;
        if (meta.inputType === 'text') {
          this.quickEditValue = meta.readString(model) || '';
        } else if (meta.inputType === 'int') {
          const n = meta.readInt(model);
          this.quickEditNum = n != null && n !== '' ? Number(n) : 260;
        } else {
          const n = meta.readNumber(model);
          this.quickEditNum = n != null ? Number(n) : 0;
          this.quickEditNumMin = meta.min != null ? meta.min : 0;
          this.quickEditNumMax = meta.max != null ? meta.max : 100;
          this.quickEditStep = meta.step != null ? meta.step : 0.01;
          this.quickEditPrecision = meta.precision != null ? meta.precision : 4;
        }
      } catch (e) {
        console.error(e);
        this.$message.error('加载策略失败');
        this.quickEditVisible = false;
      } finally {
        this.quickEditLoading = false;
      }
    },
    quickEditMeta(key) {
      const top = (m, f) => (m[f] != null && m[f] !== '' ? m[f] : (m.parameters && m.parameters[f] != null ? m.parameters[f] : ''));
      const paramNum = (m, f) => {
        const v = m.parameters && m.parameters[f] != null ? m.parameters[f] : null;
        return v != null ? Number(v) : null;
      };
      const map = {
        target_vol: {
          title: '目标波动（%）',
          hint: '与策略表单一致，存为小数（此处按百分比编辑）；保存后将执行实盘发布。',
          inputType: 'number',
          min: 0.01,
          max: 100,
          step: 0.1,
          precision: 2,
          readNumber: m => {
            const v = paramNum(m, 'target_vol');
            return v != null ? v * 100 : 5;
          },
          build: num => ({ parametersPatch: { target_vol: Number(num) / 100 } })
        },
        vol_reset: {
          title: '波动重置阈值（%）',
          hint: '对应参数 vol_reset_threshold（小数）；此处按百分比编辑。',
          inputType: 'number',
          min: 0.01,
          max: 100,
          step: 0.1,
          precision: 2,
          readNumber: m => {
            const v = paramNum(m, 'vol_reset_threshold');
            if (v == null) return 6;
            return v * 100;
          },
          build: num => ({ parametersPatch: { vol_reset_threshold: Number(num) / 100 } })
        },
        max_leverage: {
          title: '总杠杆上限',
          inputType: 'number',
          min: 0.1,
          max: 100,
          step: 0.01,
          precision: 4,
          readNumber: m => {
            const v = paramNum(m, 'max_total_leverage');
            return v != null ? v : 1;
          },
          build: num => ({ parametersPatch: { max_total_leverage: Number(num) } })
        },
        mom_windows: {
          title: 'MOM 窗口（交易日）',
          inputType: 'text',
          readString: m => String(top(m, 'mom_windows') || ''),
          build: str => ({ topPatch: { mom_windows: String(str).trim() } })
        },
        posi_windows: {
          title: 'POSI 窗口（交易日）',
          inputType: 'text',
          readString: m => String(top(m, 'posi_windows') || ''),
          build: str => ({ topPatch: { posi_windows: String(str).trim() } })
        },
        smom_windows: {
          title: 'SMOM 窗口（交易日）',
          inputType: 'text',
          readString: m => String(top(m, 'smom_windows') || ''),
          build: str => ({ topPatch: { smom_windows: String(str).trim() } })
        },
        macd_windows: {
          title: 'MACD 短期窗口（交易日）',
          inputType: 'text',
          readString: m => String(top(m, 'macd_windows') || ''),
          build: str => ({ topPatch: { macd_windows: String(str).trim() } })
        },
        macd_long_window: {
          title: 'MACD 长期窗口',
          inputType: 'int',
          readInt: m => {
            const v = top(m, 'macd_long_window');
            if (v === '' || v == null) return 250;
            return parseInt(v, 10);
          },
          build: num => ({ topPatch: { macd_long_window: parseInt(num, 10) } })
        },
        reversal_windows: {
          title: '反转窗口（两档，逗号分隔）',
          inputType: 'text',
          readString: m => String(top(m, 'reversal_windows') || ''),
          build: str => ({ topPatch: { reversal_windows: String(str).trim() } })
        },
        min_history_days: {
          title: '最小历史长度 min_history_days',
          hint: '策略顶层字段；展示页「动量最小历史」还会与窗口上限取较大值。',
          inputType: 'int',
          readInt: m => {
            const v = top(m, 'min_history_days');
            if (v === '' || v == null) return 260;
            return parseInt(v, 10);
          },
          build: num => ({ topPatch: { min_history_days: parseInt(num, 10) } })
        }
      };
      return map[key] || null;
    },
    async submitQuickEdit() {
      // 发布即冻结：参数属于发布快照内容，监控页不再直接改写
      this.blockLiveConfigEdit();
    },
    async showInitDialog() {
      // 已有进行中的任务时不清空：弹窗直接展示它的进度
      if (!this.isTaskActive) {
        this.$store.commit('monitor/SET_RUN_TASK', null);
      }
      this.initDialogVisible = true;
      await this.resumeActiveTask();
    },
    async confirmInit() {
      this.initializing = true;
      try {
        const res = await this.initMonitorAction({
          start_date: this.initStartDate,
          manual_preset_step: this.isManualAllocationMonitor && this.manualPresetStepOptIn
        });
        if (res && res.task_id) {
          // 后台任务：store 已记下句柄并开始轮询，完成后自动切批次并刷新本页
          this.$message.success('初始化任务已提交，后台运行中');
          return;
        }
        // 同步兜底（后端 async_mode=false，仅脚本/调试使用）
        this.initDialogVisible = false;
        await this.refreshAfterRun();
        if (res && res.paused) {
          this.notifyManualPresetStepPause(res);
        } else {
          this.$message.success('初始化完成');
        }
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.message) || e.message;
        this.$message.error('初始化任务提交失败: ' + msg);
      } finally {
        this.initializing = false;
      }
    },
    /**
     * 任务到达终态（由 store 的 taskFinishedAt 触发）：重载各展示区并按状态反馈。
     * 展示批次已由 store 切到新批次，此处不需再管批次口径。
     */
    onTaskFinished() {
      const task = this.lastFinishedTask || {};
      this.refreshAllComponents();
      const label = this.taskKindLabel;
      if (task.status === 'completed') {
        const batch = task.batch_id ? `，批次 ${String(task.batch_id).slice(0, 8)}` : '';
        this.$message.success(`${label}完成${batch}`);
      } else if (task.status === 'paused') {
        this.notifyManualPresetStepPause(task.result || {});
      } else if (task.status === 'interrupted') {
        this.$message.warning(`${label}被服务重启中断，请重新发起`);
      } else {
        const msg = (task.error && task.error.message) || task.message || '未知错误';
        this.$message.error(`${label}失败: ${msg}`);
      }
    },
    closeInitDialogAndRefresh() {
      this.initDialogVisible = false;
      this.$store.commit('monitor/SET_RUN_TASK', null);
      this.refreshAllComponents();
    },
    handleInitDialogClosed() {
      // 任务结束后关闭弹窗即清空任务槽；进行中则保留，便于横幅继续展示进度
      if (this.runTask && !this.isTaskActive) {
        this.$store.commit('monitor/SET_RUN_TASK', null);
      }
    },
    /** 页面刷新/切换策略后恢复进行中的任务（store 内部续接轮询） */
    async resumeActiveTask() {
      const id = this.activeMonitorId;
      if (!id) return;
      await this.resumeActiveTaskAction(id);
    },
    /** 同步兜底路径的刷新：先对齐批次列表，再重载展示区 */
    async refreshAfterRun() {
      if (this.activeMonitorId) {
        await this.fetchBatches({ monitor_id: this.activeMonitorId });
      }
      this.refreshAllComponents();
    },
    notifyManualPresetStepPause(res) {
      const perf = (res && res.performance) || {};
      const cr = perf.cumulative_return;
      const crTxt =
        cr != null && !Number.isNaN(Number(cr)) ? `${Number(cr).toFixed(2)}%` : '—';
      this.$message({
        type: 'warning',
        duration: 12000,
        message:
          `主观策略步进已暂停：已推演至调仓日 ${res.as_of_date}` +
          (res.next_preset_date
            ? `，下一预设调仓日 ${res.next_preset_date}`
            : '，后续区间内无更多预设调仓日') +
          `。区间累计收益约 ${crTxt}。请查看净值与绩效后点击「继续执行（步进）」或勾选步进后「运行监控」续跑。`
      });
    },
    async handleContinueManualStep() {
      if (!this.manualPresetStepPaused) {
        return;
      }
      this.$confirm(
        '将从当前状态按预设调仓步进续跑至下一档调仓日完成后或数据最新。是否继续？',
        '继续执行（步进）',
        { type: 'info' }
      ).then(async () => {
        this.continuingStep = true;
        try {
          const res = await this.runMonitorAction({ manual_preset_step: true });
          if (res && res.task_id) {
            this.$message.success('步进续跑任务已提交，后台运行中');
          } else {
            // 同步兜底：直接拿到运行结果
            await this.refreshAfterRun();
            if (res && res.paused) {
              this.notifyManualPresetStepPause(res);
            } else {
              this.$message.success('步进续跑完成（已推进至数据最新或本轮未再暂停）');
            }
          }
        } catch (e) {
          const msg = (e.response && e.response.data && e.response.data.message) || e.message;
          this.$message.error('续跑任务提交失败: ' + msg);
        } finally {
          this.continuingStep = false;
        }
      }).catch(() => {});
    },
    // ── 监控策略管理事件 ──
    async handleStrategyView(strategy) {
      this.selectedMonitoredStrategy = strategy;
      await this.setActiveMonitorContext({ monitorId: strategy._id });
      await this.resumeActiveTask();
      this.activeTab = 'overview';
      this.$nextTick(() => this.refreshAllComponents());
    },
    async handleStrategyInit(strategy) {
      this.selectedMonitoredStrategy = strategy;
      await this.setActiveMonitorContext({ monitorId: strategy._id });
      this.activeTab = 'overview';
      this.showInitDialog();
    },
    async handleStrategyRun(strategy) {
      this.selectedMonitoredStrategy = strategy;
      await this.setActiveMonitorContext({ monitorId: strategy._id });
      this.$nextTick(() => {
        this.refreshAllComponents();
        this.handleRunMonitor();
      });
    },
    async handleStrategySwitch(monitorId) {
      const list = this.$refs.strategyList;
      const strategy = (list ? list.strategies : []).find(s => s._id === monitorId);
      this.selectedMonitoredStrategy = strategy || null;
      await this.setActiveMonitorContext({ monitorId });
      await this.resumeActiveTask();
      this.activeTab = 'overview';
      this.$nextTick(() => this.refreshAllComponents());
    },
    /** 归档后：若归档的是当前活动策略，清除监控上下文并刷新 eligible */
    async handleStrategyArchive(archivedId) {
      if (this.activeMonitorId === archivedId) {
        this.selectedMonitoredStrategy = null;
        // setActiveMonitorContext 内部已停轮询并清空任务与批次上下文
        await this.setActiveMonitorContext({ monitorId: null });
        this.activeTab = 'overview';
      }
      await this.loadEligibleContext();
    },

    // ── 批次切换 ──
    batchOptionLabel(b) {
      const id = b.batch_id === 'legacy'
        ? 'legacy'
        : String(b.batch_id || '').slice(0, 8);
      const parts = [
        id,
        RUN_MODE_LABEL[b.run_mode] || b.run_mode,
        BATCH_STATUS_LABEL[b.status] || b.status,
        b.created_at ? dayjs(b.created_at).format('MM-DD HH:mm') : ''
      ];
      return parts.filter(Boolean).join(' · ');
    },
    /** 切批次：先写回 store（所有展示请求随之带上 batch_id），再重载已渲染的展示区 */
    async handleBatchChange(batchId) {
      const next = batchId || null;
      if (next === this.currentBatchId) return;
      this.setCurrentBatchId(next);
      await this.$nextTick();
      this.refreshAllComponents();
      const label = next ? `批次 ${String(next).slice(0, 8)}` : '最新完成批次';
      this.$message.success(`已切换到${label}的快照数据`);
    },

    async handleRunMonitor() {
      if (this.isTaskActive) {
        this.$message.warning(`当前策略${this.taskKindLabel}任务进行中，请等待任务完成`);
        return;
      }
      const stepHint =
        this.isManualAllocationMonitor && this.manualPresetStepOptIn
          ? '已开启预设调仓日步进：每完成一档调仓日当日推演后将暂停，便于查看绩效。'
          : '';
      this.$confirm(
        stepHint ? `确认运行日常监控？${stepHint}` : '确认运行日常监控？',
        '提示',
        { type: 'info' }
      ).then(async () => {
        this.running = true;
        try {
          const res = await this.runMonitorAction({
            manual_preset_step: this.isManualAllocationMonitor && this.manualPresetStepOptIn
          });
          if (res && res.task_id) {
            // 任务已交给后台：完成后 store 会切到新批次并由 taskFinishedAt 触发刷新
            this.$message.success('日常运行任务已提交，后台运行中');
          } else {
            await this.refreshAfterRun();
            if (res && res.paused) {
              this.notifyManualPresetStepPause(res);
            } else {
              this.$message.success('监控运行完成');
            }
          }
        } catch (e) {
          const msg = (e.response && e.response.data && e.response.data.message) || e.message;
          this.$message.error('运行任务提交失败: ' + msg);
        } finally {
          this.running = false;
        }
      }).catch(() => {});
    },
    /** 主观调仓提交后：净值与持仓变化，重新拉取统一绩效面板 */
    handleOverrideAdded() {
      this.loadPerformancePanel();
    },
    refreshAllComponents() {
      // 刷新所有子组件的数据（绩效页子组件统一订阅 performancePanel）
      const refs = ['dashboard', 'signals', 'subjective', 'eventLog', 'publishLog', 'operationPanel'];
      refs.forEach(refName => {
        const component = this.$refs[refName];
        if (component && typeof component.loadData === 'function') {
          component.loadData();
        }
      });
      if (this.activeTab === 'performance') {
        this.loadPerformancePanel();
      }
    },
    /** 拉取绩效页统一面板：本页所有数据都按 performanceRange 展示 */
    async loadPerformancePanel() {
      if (!this.activeMonitorId) return;
      this.performanceLoading = true;
      try {
        await this.fetchPerformancePanel({
          monitor_id: this.activeMonitorId,
          start: this.performanceRange.start || undefined,
          end: this.performanceRange.end || undefined
        });
      } finally {
        this.performanceLoading = false;
      }
    },
    handlePerformanceRangeChange() {
      this.performanceQuick = 'custom';
      this.loadPerformancePanel();
    },
    applyQuickRange(key) {
      if (key === 'all') {
        this.$store.commit('monitor/SET_PERFORMANCE_RANGE', { start: null, end: null });
        this.performanceQuick = 'all';
        this.loadPerformancePanel();
        return;
      }
      const fullEnd = (this.performancePanel && this.performancePanel.range && this.performancePanel.range.full_end)
        || (this.monitorState && this.monitorState.date)
        || null;
      if (!fullEnd) {
        this.$message.warning('暂无监控数据，无法选择周期');
        return;
      }
      const config = { '1m': [1, 'month'], '3m': [3, 'month'], '1y': [1, 'year'] }[key];
      if (!config) return;
      const start = dayjs(fullEnd).subtract(config[0], config[1]).format('YYYY-MM-DD');
      this.$store.commit('monitor/SET_PERFORMANCE_RANGE', { start, end: fullEnd });
      this.performanceQuick = key;
      this.loadPerformancePanel();
    }
  }
};
</script>

<style scoped>
.init-running-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 8px;
  border: 1px solid #b3d8ff;
  border-radius: 4px;
  background: #ecf5ff;
  color: #409eff;
  font-size: 13px;
}

.init-running-banner .el-button {
  margin-left: auto;
}

.init-task-result {
  margin-top: 12px;
  color: #303133;
  font-size: 13px;
  line-height: 24px;
}

.page-container {
  padding: 16px;
}

.monitor-center {
  width: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.header-left {
  flex: 1;
}

.header-actions {
  display: flex;
  gap: 10px;
}

/* 批次口径栏：当前展示批次号 + 切换器 + 该批次的运行摘要 */
.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.batch-bar__label {
  font-size: 13px;
  color: #909399;
}

.batch-bar__select {
  width: 250px;
}

.batch-bar__hint {
  max-width: 320px;
  font-size: 12px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 窄屏优先保住标题与切换器，摘要提示先隐 */
@media (max-width: 1280px) {
  .batch-bar__hint {
    display: none;
  }

  .batch-bar__select {
    width: 190px;
  }
}

.page-title {
  font-size: 18px;
  margin: 0;
}

.manual-step-inline {
  margin: 6px 0 0 0;
  font-size: 13px;
  color: #606266;
}

.manual-step-inline .el-checkbox {
  white-space: normal;
  line-height: 1.45;
}

/* 双列网格布局：左右对齐、紧凑排列 */
.monitor-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  align-items: stretch;
}

/* 跨 2 列全宽卡片 */
.monitor-section--span2 {
  grid-column: 1 / -1;
}

.monitor-section--full {
  margin-bottom: 12px;
}

/* 绩效页：统一周期栏 */
.period-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.period-label {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
}

.period-separator {
  font-size: 13px;
  color: #909399;
}

.period-quick {
  margin-left: 4px;
}

.period-hint {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}

/* 绩效页：首次加载占位（不渲染子组件的空态文案） */
.performance-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 240px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  color: #909399;
  font-size: 14px;
}

/* 绩效页：行内卡片等高，内容区撑满不留底部空白 */
.monitor-grid--performance {
  align-items: stretch;
}

.monitor-grid--performance > .monitor-section {
  min-width: 0;
  overflow: hidden;
}

/* 行1：持仓明细 / 每日收益统计 等高 */
.monitor-grid--performance > .performance-card--row1 {
  height: 580px;
}

/* 页签内最后一张卡片不留底部间距 */
.monitor-section--last {
  margin-bottom: 0;
}

/* 页签容器：与数据接入、汇率页面一致的 border-card 风格 */
.monitor-tabs {
  border-radius: 8px;
  overflow: hidden;
}

.monitor-tabs >>> .el-tabs__content {
  padding: 14px;
  background: #f0f2f5;
}

.monitor-tabs >>> .el-tabs__item.is-active {
  font-weight: 600;
}

.tab-badge {
  margin-left: 6px;
}

.op-subjective-divider {
  border-top: 1px dashed #dcdfe6;
  margin: 16px 0 8px 0;
}

.section-subtitle {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
}

.section-subtitle--toggle {
  display: flex;
  align-items: center;
  cursor: pointer;
  user-select: none;
}

.section-subtitle--toggle:hover {
  color: #409eff;
}

.subjective-pending-tag {
  margin-left: 8px;
}


.assets-edit-body {
  min-height: 120px;
}

.assets-edit-pick {
  display: flex;
  align-items: center;
  margin-bottom: 14px;
}

.assets-edit-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  min-height: 36px;
}

.assets-edit-tag {
  margin: 0 !important;
}

.assets-edit-no-tags {
  font-size: 13px;
  color: #909399;
}


.quick-edit-body {
  min-height: 48px;
}

.quick-edit-hint {
  margin: 0 0 12px 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
}


.subjective-editor-body {
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 4px;
}

.subjective-editor-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.subjective-editor-row--compact {
  margin-bottom: 10px;
}

.subjective-editor-label {
  flex: 0 0 132px;
  font-size: 13px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subjective-editor-slider {
  flex: 1 1 auto;
  min-width: 0;
  padding: 0 6px;
}

.subjective-editor-num {
  flex: 0 0 108px;
  width: 108px !important;
}

.subjective-sum-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid #ebeef5;
  font-size: 13px;
  color: #606266;
}

.subjective-preset-weight-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.subjective-preset-weight-actions-hint {
  font-size: 12px;
  color: #909399;
}

.subjective-sum--warn {
  color: #e6a23c;
  font-weight: 600;
}

.subjective-preset-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
  background: #fafafa;
}

.subjective-preset-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.subjective-preset-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.subjective-preset-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.subjective-preset-switch-label {
  font-size: 13px;
  color: #606266;
}

.subjective-preset-weights {
  padding-top: 4px;
  border-top: 1px dashed #dcdfe6;
}

.subjective-preset-row-sum {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
  text-align: right;
}


.monitor-section {
  margin-bottom: 0;
  min-width: 0;
  overflow: hidden;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 15px;
  font-weight: 600;
}
.section-header--toggle {
  cursor: pointer;
  user-select: none;
}
.section-header--toggle:hover {
  color: #409eff;
}

.section-header__hint {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
}


.init-dialog-strategy {
  font-size: 13px;
  color: #606266;
  margin: 0 0 16px 0;
  line-height: 1.5;
}

/* 移除子组件的外层padding和header，避免重复 */
.monitor-section >>> .page-container {
  padding: 0;
}

.monitor-section >>> .page-header {
  display: none;
}

/* 网格内卡片body自动撑满行高 */
.monitor-grid .monitor-section {
  display: flex;
  flex-direction: column;
}

.monitor-grid .monitor-section >>> .el-card__body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 窄屏回退单列 */
@media (max-width: 1200px) {
  .monitor-grid {
    grid-template-columns: 1fr;
  }
}


</style>
