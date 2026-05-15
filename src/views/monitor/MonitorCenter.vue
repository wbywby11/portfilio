<template>
  <div class="page-container monitor-center">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">日常监控</h2>
        <p class="page-desc">组合净值跟踪、信号检测与调仓管理（按已实盘发布的混合动量或主观配置策略实例隔离）</p>
        <p v-if="!eligibleLoading && currentStrategy" class="page-strategy-inline">
          已选策略：<strong>{{ currentStrategy.name }}</strong>
          <span class="page-strategy-meta">（{{ currentStrategy.template_code }}<template v-if="currentStrategy.selector_type === 'hybrid'"> · 混合动量</template><template v-else-if="liveEffectiveParams && liveEffectiveParams.is_manual_allocation"> · 主观配置</template>）</span>
        </p>
        <p v-if="!eligibleLoading && isManualAllocationMonitor" class="manual-step-inline">
          <el-checkbox v-model="manualPresetStepOptIn">
            主观：预设调仓日步进（与回测一致，在每档调仓日当日推演完成后暂停，便于查看绩效后再继续）
          </el-checkbox>
        </p>
      </div>
      <div class="header-actions">
        <el-select
          v-if="eligibleStrategies.length > 1"
          v-model="selectedStrategyId"
          placeholder="选择监控策略"
          filterable
          style="width: 280px; margin-right: 10px;"
          @change="onStrategySelectChange">
          <el-option
            v-for="s in eligibleStrategies"
            :key="s.id"
            :label="formatStrategyOption(s)"
            :value="s.id">
          </el-option>
        </el-select>
        <el-button
          type="warning"
          icon="el-icon-s-operation"
          :disabled="!canOperateMonitor || blockInitDuringManualPresetPause"
          @click="showInitDialog">
          初始化
        </el-button>
        <el-button
          v-if="isManualAllocationMonitor"
          type="success"
          plain
          icon="el-icon-d-arrow-right"
          :disabled="!canOperateMonitor || !manualPresetStepPaused || running || initializing || continuingStep"
          :loading="continuingStep"
          @click="handleContinueManualStep">
          继续执行（步进）
        </el-button>
        <el-button
          type="primary"
          icon="el-icon-video-play"
          :disabled="!canOperateMonitor"
          @click="handleRunMonitor"
          :loading="running">
          运行监控
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!eligibleLoading && !hasEligibleStrategies"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 16px;"
      title="暂无准入策略"
      description="日常监控需要至少一条已实盘发布的准入策略：risk_budget_target_vol + 混合动量，或主观配置模板（manual_allocation / manual_allocation_strategy）。请完成配置并实盘发布。">
    </el-alert>

    <el-alert
      v-if="!eligibleLoading && hasEligibleStrategies && !hasPublishedLiveStrategy"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px;"
      title="当前仅系统基准（config.py）"
      description="下拉中的「系统基准」对应 monitor_id=default，参数与绩效可与 app/monitor/config.py 对照。若需对比实盘实例，请在策略模型中完成混合动量或主观配置并实盘发布。">
    </el-alert>

    <!-- 当前实盘策略与监控实例状态（新发布策略需先初始化才有数据） -->
    <el-card
      v-if="!eligibleLoading && hasEligibleStrategies && activeMonitorId && currentStrategy"
      shadow="never"
      class="strategy-context-card">
      <div class="strategy-context-row">
        <div class="strategy-context-main">
          <span class="strategy-context-label">当前监控策略</span>
          <span class="strategy-context-name">{{ currentStrategy.name || '（未命名）' }}</span>
          <el-tag size="small" type="info" style="margin-left: 8px;">{{ currentStrategy.template_code }}</el-tag>
          <el-tag v-if="currentStrategy.selector_type === 'hybrid'" size="small" type="success" style="margin-left: 4px;">混合动量</el-tag>
          <el-tag v-else-if="liveEffectiveParams && liveEffectiveParams.is_manual_allocation" size="small" type="warning" style="margin-left: 4px;">主观配置</el-tag>
          <span class="strategy-context-id">
            {{ currentStrategy.is_config_baseline ? '监控实例：default（app/monitor/config.py）' : '模型 ID：' + activeMonitorId }}
          </span>
        </div>
        <div class="strategy-context-status">
          <el-tag v-if="!monitorState" type="warning" effect="dark">监控未初始化</el-tag>
          <template v-else>
            <el-tag type="success" effect="plain">监控已就绪 · 数据日期 {{ formatStrategyDate(monitorState.date) }}</el-tag>
            <el-tag
              v-if="manualPresetStepPaused"
              type="warning"
              effect="dark"
              style="margin-left: 8px;">
              步进暂停 · 下一预设调仓日 {{ monitorState.manual_preset_next_date || '—' }}
            </el-tag>
          </template>
        </div>
      </div>

      <!-- 实盘可变参数：仅反映已实盘发布快照；可进详情或点单卡快捷改参并发布 -->
      <div v-if="liveEffectiveParams" class="live-effective-params">
        <div class="live-effective-params-title-row">
          <div>
            <span class="live-effective-params-title">实盘生效参数</span>
            <p class="live-effective-params-note">以下为最近一次<strong>实盘发布</strong>冻结的配置；仅在策略页保存或未点「实盘发布」的修改不会显示在此处。</p>
          </div>
          <el-button
            v-if="canClickLiveParams"
            type="text"
            class="live-effective-link"
            @click="goEditLiveParams">
            进入策略详情修改并发布 →
          </el-button>
        </div>
        <div v-if="!isManualAllocationMonitor" class="live-param-metrics">
          <div
            class="live-param-metric"
            :class="{ 'live-param-metric--interactive': canClickLiveParams }"
            @click.stop="canClickLiveParams && openQuickEdit('target_vol')">
            <span class="live-param-metric-label">目标波动</span>
            <span class="live-param-metric-value">{{ liveEffectiveParams.target_vol_pct }}<span class="live-param-unit">%</span></span>
          </div>
          <div
            v-if="!isRiskBudgetTargetVolLiveStrategy"
            class="live-param-metric"
            :class="{ 'live-param-metric--interactive': canClickLiveParams }"
            @click.stop="canClickLiveParams && openQuickEdit('vol_reset')">
            <span class="live-param-metric-label">波动重置阈值</span>
            <span class="live-param-metric-value">{{ liveEffectiveParams.vol_reset_threshold_pct }}<span class="live-param-unit">%</span></span>
          </div>
          <div
            class="live-param-metric"
            :class="{ 'live-param-metric--interactive': canClickLiveParams }"
            @click.stop="canClickLiveParams && openQuickEdit('max_leverage')">
            <span class="live-param-metric-label">总杠杆上限</span>
            <span class="live-param-metric-value">{{ liveEffectiveParams.max_total_leverage }}</span>
          </div>
        </div>
        <div
          v-if="!isManualAllocationMonitor && liveEffectiveParams.asset_classes && liveEffectiveParams.asset_classes.length"
          class="live-asset-classes">
          <span class="live-block-label">资产类别</span>
          <el-tag
            v-for="(cls, cidx) in liveEffectiveParams.asset_classes"
            :key="'cls-' + cidx"
            size="small"
            :type="assetClassTagType(cls)"
            effect="plain"
            class="live-class-tag">
            {{ cls }}
          </el-tag>
        </div>

        <div
          id="monitor-subjective-live-params"
          v-if="isManualAllocationMonitor"
          class="live-window-section live-manual-section">
          <div class="live-effective-params-title">主观实盘参数</div>
          <p class="live-effective-params-note live-manual-snapshot-hint">
            初始化权重与预设调仓日权重均采用条形展示（与下方「实盘发布记录」及监控仪表板「本页绩效对应的实盘参数」一致）。可点击区块编辑并发布。
          </p>
          <SubjectiveManualWeightsSnapshot
            :manual-weights="liveEffectiveParams.manual_weights || {}"
            :manual-adjustments="liveEffectiveParams.manual_weight_adjustments || []"
            :resolve-label="subjectiveSnapshotResolveLabel"
            :interactive-init="canClickLiveParams"
            :interactive-presets="canClickLiveParams"
            @init-click="onSubjectiveSnapshotInitClick"
            @presets-click="onSubjectiveSnapshotPresetsClick" />
        </div>

        <div v-if="hasLiveWindowParams" class="live-window-section">
          <div class="live-effective-params-title">动量与反转窗口（交易日）</div>
          <div class="live-param-metrics">
            <div
              v-if="liveEffectiveParams.mom_windows"
              class="live-param-metric live-param-metric-wide"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('mom_windows')">
              <span class="live-param-metric-label">MOM</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.mom_windows }}</span>
            </div>
            <div
              v-if="liveEffectiveParams.posi_windows"
              class="live-param-metric live-param-metric-wide"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('posi_windows')">
              <span class="live-param-metric-label">POSI</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.posi_windows }}</span>
            </div>
            <div
              v-if="liveEffectiveParams.smom_windows"
              class="live-param-metric live-param-metric-wide"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('smom_windows')">
              <span class="live-param-metric-label">SMOM</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.smom_windows }}</span>
            </div>
            <div
              v-if="liveEffectiveParams.macd_windows"
              class="live-param-metric live-param-metric-wide"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('macd_windows')">
              <span class="live-param-metric-label">MACD 短期</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.macd_windows }}</span>
            </div>
            <div
              v-if="liveEffectiveParams.macd_long_window != null && liveEffectiveParams.macd_long_window !== ''"
              class="live-param-metric"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('macd_long_window')">
              <span class="live-param-metric-label">MACD 长期</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.macd_long_window }}</span>
            </div>
            <div
              v-if="liveEffectiveParams.reversal_windows"
              class="live-param-metric live-param-metric-wide"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('reversal_windows')">
              <span class="live-param-metric-label">反转</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.reversal_windows }}</span>
            </div>
            <div
              v-if="!isRiskBudgetTargetVolLiveStrategy && liveEffectiveParams.min_history_momentum != null && liveEffectiveParams.min_history_momentum !== ''"
              class="live-param-metric"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('min_history_days')">
              <span class="live-param-metric-label">动量最小历史</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.min_history_momentum }} 日</span>
            </div>
            <div
              v-if="!isRiskBudgetTargetVolLiveStrategy && liveEffectiveParams.min_history_reversal != null && liveEffectiveParams.min_history_reversal !== ''"
              class="live-param-metric"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('min_history_reversal_hint')">
              <span class="live-param-metric-label">反转最小历史</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.min_history_reversal }} 日</span>
            </div>
          </div>
        </div>
      </div>

      <div
        v-if="canClickLiveParams || effectiveAssetTags.length"
        class="strategy-context-assets"
        :class="{ 'strategy-context-assets--interactive': canClickLiveParams }"
        @click.stop="canClickLiveParams && openAssetsEdit()">
        <div class="strategy-context-assets-row">
          <span class="strategy-context-assets-label">底层资产（参与计算）</span>
          <span v-if="canClickLiveParams" class="strategy-context-assets-hint">点击调整并实盘发布 →</span>
        </div>
        <div class="strategy-context-asset-tags">
          <template v-if="effectiveAssetTags.length">
            <el-tag
              v-for="(nm, idx) in effectiveAssetTags"
              :key="'ctx-' + idx"
              size="small"
              type="info"
              effect="plain"
              class="strategy-context-asset-tag">
              {{ nm }}
            </el-tag>
          </template>
          <span v-else-if="canClickLiveParams" class="strategy-context-assets-empty">暂无，点击添加</span>
        </div>
      </div>
      <el-alert
        v-if="!monitorState"
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 12px;"
        title="新发布策略尚无日常监控数据"
        description="每个策略实例使用独立 monitor_id（即模型 ID）。刚完成实盘发布后，组合净值、绩效、信号等均为空属正常情况。请先点击右上角「初始化」从启动日期逐日构建监控状态，再使用「运行监控」滚动至最新交易日。">
      </el-alert>
    </el-card>

    <!-- 初始化对话框 -->
    <el-dialog
      title="初始化监控"
      :visible.sync="initDialogVisible"
      width="450px"
      :close-on-click-modal="false">
      <el-alert
        title="从指定日期开始逐日推演到最新数据日期，此操作耗时较长"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 20px;">
      </el-alert>
      <p v-if="currentStrategy" class="init-dialog-strategy">
        将为策略「{{ currentStrategy.name }}」（{{ activeMonitorId }}）创建/重建监控实例；与回测无关，仅写入日常监控库。
      </p>
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
      <span slot="footer" class="dialog-footer">
        <el-button @click="initDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmInit" :loading="initializing">确认初始化</el-button>
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

    <template v-if="hasEligibleStrategies && activeMonitorId">
      <!-- 区域1：监控总览 -->
      <el-card shadow="never" class="monitor-section">
        <div slot="header" class="section-header">
          <span>监控总览</span>
        </div>
        <MonitorDashboard ref="dashboard" :strategy-context="currentStrategy" />
      </el-card>

      <!-- 区域2：净值走势 -->
      <el-card shadow="never" class="monitor-section">
        <div slot="header" class="section-header">
          <span>净值走势</span>
        </div>
        <NavHistory ref="navHistory" />
      </el-card>

      <!-- 区域3：持仓明细 -->
      <el-card shadow="never" class="monitor-section">
        <div slot="header" class="section-header">
          <span>持仓明细</span>
        </div>
        <Positions ref="positions" />
      </el-card>

      <!-- 区域4：信号监测 -->
      <el-card shadow="never" class="monitor-section">
        <div slot="header" class="section-header">
          <span>信号监测</span>
        </div>
        <Signals ref="signals" :subjective-vol-only="shouldHideVolMonitoring" />
      </el-card>

      <!-- 区域5：主观调仓 -->
      <el-card shadow="never" class="monitor-section">
        <div slot="header" class="section-header">
          <span>主观调仓</span>
        </div>
        <SubjectiveOverride ref="subjective" :strategy-context="currentStrategy" />
      </el-card>

      <!-- 区域6：事件日志 -->
      <el-card shadow="never" class="monitor-section">
        <div slot="header" class="section-header">
          <span>事件日志</span>
        </div>
        <EventLog ref="eventLog" />
      </el-card>

      <!-- 区域7：实盘发布记录（与监控运行时一致的参数/资产/窗口变更） -->
      <el-card
        v-if="currentStrategy && !currentStrategy.is_config_baseline && activeMonitorId && activeMonitorId !== 'default'"
        shadow="never"
        class="monitor-section">
        <div slot="header" class="section-header">
          <span>实盘发布记录</span>
        </div>
        <p class="section-desc">仅展示实盘发布、取消实盘、日常监控侧实盘配置；不含策略保存类记录。「实盘发布」行内为相对<strong>上次落库快照</strong>变更的生效参数、底层资产与窗口。</p>
        <LivePublishRecords ref="publishLog" :model-id="activeMonitorId" />
      </el-card>
    </template>
  </div>
</template>

<script>
import { mapActions, mapGetters, mapState } from 'vuex';
import dayjs from 'dayjs';
import {
  getLiveEligibleForMonitor,
  getStrategyModel,
  updateStrategyModel,
  livePublishModel
} from '@/api/strategy';
import { getAssetOptions } from '@/api/asset';
import MonitorDashboard from './Index.vue';
import NavHistory from './NavHistory.vue';
import Positions from './Positions.vue';
import Signals from './Signals.vue';
import SubjectiveOverride from './SubjectiveOverride.vue';
import EventLog from './EventLog.vue';
import LivePublishRecords from './LivePublishRecords.vue';
import SubjectiveManualWeightsSnapshot from './SubjectiveManualWeightsSnapshot.vue';
import { normalizeWeightsToTwoDecimalSumOne, formatWeightSliderTooltip } from '@/utils/subjectiveWeights';
import { isRiskBudgetTargetVolTemplateCode } from '@/utils/strategyTemplateFlags';

export default {
  name: 'MonitorCenter',
  components: {
    MonitorDashboard,
    NavHistory,
    Positions,
    Signals,
    SubjectiveOverride,
    EventLog,
    LivePublishRecords,
    SubjectiveManualWeightsSnapshot
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
      selectedStrategyId: null,
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
      manualPresetCodes: []
    };
  },
  computed: {
    ...mapGetters('monitor', ['activeMonitorId']),
    ...mapState('monitor', ['monitorState']),
    hasEligibleStrategies() {
      return this.eligibleStrategies.length > 0;
    },
    /** 除 config.py 基准外是否已有实盘发布的混合动量策略 */
    hasPublishedLiveStrategy() {
      return this.eligibleStrategies.some(s => !s.is_config_baseline && s.id !== 'default');
    },
    canOperateMonitor() {
      return this.hasEligibleStrategies && !!this.activeMonitorId;
    },
    /** 策略模型可跳转编辑；系统基准不可 */
    canClickLiveParams() {
      return (
        !!this.activeMonitorId &&
        this.activeMonitorId !== 'default' &&
        !!this.currentStrategy &&
        !this.currentStrategy.is_config_baseline
      );
    },
    currentStrategy() {
      if (!this.activeMonitorId) return null;
      return this.eligibleStrategies.find(s => s.id === this.activeMonitorId) || null;
    },
    /** risk_budget_target_vol：部分实盘参数固定，不在监控页快捷编辑或展示 */
    isRiskBudgetTargetVolLiveStrategy() {
      const s = this.currentStrategy;
      return !!(s && isRiskBudgetTargetVolTemplateCode(s.template_code));
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
    /** 是否隐藏波动率监测：manual_allocation / etf_cycle_rotation / risk_parity 均隐藏 */
    shouldHideVolMonitoring() {
      if (this.isManualAllocationMonitor) return true;
      const s = this.currentStrategy;
      return !!(s && ['etf_cycle_rotation', 'risk_parity'].includes(s.template_code));
    },
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
    }
  },
  async created() {
    await this.loadEligibleContext();
  },
  methods: {
    ...mapActions('monitor', ['initMonitorAction', 'runMonitorAction', 'setActiveMonitorContext']),
    formatStrategyOption(s) {
      if (s.is_config_baseline || s.id === 'default') {
        return `${s.name || '系统基准（config.py）'} · 对比基准`;
      }
      if (s.live_effective_params && s.live_effective_params.is_manual_allocation) {
        return `${s.name || s.id}（${s.template_code || ''} · 主观配置）`;
      }
      const sel = s.selector_type === 'hybrid' ? '混合动量' : (s.selector_type || '');
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
        this.eligibleStrategies = (body && body.strategies) ? body.strategies : [];
        if (this.eligibleStrategies.length > 0) {
          const prevId = this.selectedStrategyId || this.activeMonitorId;
          const keep = prevId && this.eligibleStrategies.some(s => s.id === prevId);
          const pickId = keep ? prevId : this.eligibleStrategies[0].id;
          this.selectedStrategyId = pickId;
          await this.setActiveMonitorContext({ monitorId: pickId });
          this.$nextTick(() => this.refreshAllComponents());
        } else {
          this.selectedStrategyId = null;
          await this.setActiveMonitorContext({ monitorId: null });
        }
      } catch (e) {
        console.error(e);
        this.eligibleStrategies = [];
        await this.setActiveMonitorContext({ monitorId: null });
        this.$message.error('加载监控准入策略失败');
      } finally {
        this.eligibleLoading = false;
      }
    },
    async onStrategySelectChange(id) {
      if (!id) return;
      await this.setActiveMonitorContext({ monitorId: id });
      this.refreshAllComponents();
    },
    goEditLiveParams() {
      if (!this.canClickLiveParams) {
        this.$message.info('系统基准参数以 app/monitor/config.py 为准，请在代码库中修改。');
        return;
      }
      this.$router.push({
        path: `/strategy/model/detail/${this.activeMonitorId}`,
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
      if (!this.activeMonitorId) return;
      if (!this.assetsEditCodes.length) {
        this.$message.warning('请至少保留一个底层资产');
        return;
      }
      this.assetsEditSaving = true;
      try {
        const op = this.liveOperator();
        await updateStrategyModel(
          this.activeMonitorId,
          { asset_codes: [...this.assetsEditCodes] },
          { params: { source: 'live_monitoring', operator: op } }
        );
        await livePublishModel(this.activeMonitorId, { source: 'live_monitoring', operator: op });
        this.$message.success('已保存底层资产并提交实盘发布（次交易日生效）');
        this.assetsEditVisible = false;
        await this.loadEligibleContext();
        this.refreshAllComponents();
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.message) || e.message;
        this.$message.error('保存或实盘发布失败: ' + msg);
      } finally {
        this.assetsEditSaving = false;
      }
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
      if (!this.activeMonitorId || !this.manualInitEditorModel) return;
      if (this.manualInitSumRatio > 1.00001) {
        this.$message.warning('权重合计超过 100%，请先调低或使用「归一化到 100%」');
        return;
      }
      const manual_weights = {};
      this.manualInitRows.forEach(r => {
        manual_weights[r.code] = Number(r.weight) || 0;
      });
      this.manualInitEditorSaving = true;
      try {
        const op = this.liveOperator();
        const base = this.manualInitEditorModel.parameters || {};
        await updateStrategyModel(
          this.activeMonitorId,
          { parameters: this.patchParameters(base, { manual_weights }) },
          { params: { source: 'live_monitoring', operator: op } }
        );
        await livePublishModel(this.activeMonitorId, { source: 'live_monitoring', operator: op });
        this.$message.success('已保存初始化权重并提交实盘发布（次交易日生效）');
        this.manualInitEditorVisible = false;
        await this.loadEligibleContext();
        this.refreshAllComponents();
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.message) || e.message;
        this.$message.error('保存或实盘发布失败: ' + msg);
      } finally {
        this.manualInitEditorSaving = false;
      }
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
      if (!this.activeMonitorId || !this.manualPresetsEditorModel) return;
      const out = [];
      for (let i = 0; i < this.manualPresetRows.length; i++) {
        const row = this.manualPresetRows[i];
        const d = this.presetPickerToYmd(row.date);
        if (!d) continue;
        const weights = {};
        this.manualPresetCodes.forEach(c => {
          weights[c] = Number(row.weights[c]) || 0;
        });
        let t = this.manualPresetCodes.reduce((s, c) => s + weights[c], 0);
        if (row.auto_normalize && t > 0) {
          const out = this.normalizeWeightsToTwoDecimalSumOne(weights, this.manualPresetCodes);
          this.manualPresetCodes.forEach(c => {
            weights[c] = out[c];
          });
          t = 1;
        } else if (t > 1.00001) {
          this.$message.warning(`第 ${i + 1} 条权重合计超过 100%，请调低或开启「保存时归一化」`);
          return;
        }
        out.push({
          date: d,
          auto_normalize: !!row.auto_normalize,
          weights
        });
      }
      if (!out.length) {
        this.$message.warning('请至少填写一条调仓日');
        return;
      }
      this.manualPresetsEditorSaving = true;
      try {
        const op = this.liveOperator();
        const base = this.manualPresetsEditorModel.parameters || {};
        await updateStrategyModel(
          this.activeMonitorId,
          { parameters: this.patchParameters(base, { manual_weight_adjustments: out }) },
          { params: { source: 'live_monitoring', operator: op } }
        );
        await livePublishModel(this.activeMonitorId, { source: 'live_monitoring', operator: op });
        this.$message.success('已保存预设调仓并提交实盘发布（次交易日生效）');
        this.manualPresetsEditorVisible = false;
        await this.loadEligibleContext();
        this.refreshAllComponents();
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.message) || e.message;
        this.$message.error('保存或实盘发布失败: ' + msg);
      } finally {
        this.manualPresetsEditorSaving = false;
      }
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
      const meta = this.quickEditMeta(this.quickEditKey);
      if (!meta || !this.quickEditSourceModel || !this.activeMonitorId) {
        this.quickEditVisible = false;
        return;
      }
      let built;
      try {
        if (meta.inputType === 'text') {
          const s = (this.quickEditValue || '').trim();
          if (!s) {
            this.$message.warning('请输入有效内容');
            return;
          }
          try {
            built = meta.build(s);
          } catch (err) {
            this.$message.error('格式无效：' + (err && err.message ? err.message : '请检查 JSON'));
            return;
          }
        } else {
          const n = this.quickEditNum;
          if (n === null || n === undefined || Number.isNaN(Number(n))) {
            this.$message.warning('请输入有效数字');
            return;
          }
          built = meta.build(n);
        }
      } catch (e) {
        this.$message.error('参数无效');
        return;
      }
      const payload = {};
      if (built.parametersPatch) {
        payload.parameters = this.patchParameters(
          this.quickEditSourceModel.parameters,
          built.parametersPatch
        );
      }
      if (built.topPatch) {
        Object.assign(payload, built.topPatch);
      }
      if (!Object.keys(payload).length) {
        this.$message.warning('没有可提交的修改');
        return;
      }
      this.quickEditSaving = true;
      try {
        const op = this.liveOperator();
        await updateStrategyModel(this.activeMonitorId, payload, {
          params: { source: 'live_monitoring', operator: op }
        });
        await livePublishModel(this.activeMonitorId, { source: 'live_monitoring', operator: op });
        this.$message.success('已保存并提交实盘发布（次交易日生效）');
        this.quickEditVisible = false;
        await this.loadEligibleContext();
        this.refreshAllComponents();
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.message) || e.message;
        this.$message.error('保存或实盘发布失败: ' + msg);
      } finally {
        this.quickEditSaving = false;
      }
    },
    showInitDialog() {
      this.initDialogVisible = true;
    },
    async confirmInit() {
      this.initializing = true;
      try {
        const res = await this.initMonitorAction({
          start_date: this.initStartDate,
          manual_preset_step: this.isManualAllocationMonitor && this.manualPresetStepOptIn
        });
        this.initDialogVisible = false;
        this.refreshAllComponents();
        if (res && res.paused) {
          this.notifyManualPresetStepPause(res);
        } else {
          this.$message.success('初始化完成');
        }
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.message) || e.message;
        this.$message.error('初始化失败: ' + msg);
      } finally {
        this.initializing = false;
      }
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
          const res = await this.runMonitorAction({
            manual_preset_step: true
          });
          this.refreshAllComponents();
          if (res && res.paused) {
            this.notifyManualPresetStepPause(res);
          } else {
            this.$message.success('步进续跑完成（已推进至数据最新或本轮未再暂停）');
          }
        } catch (e) {
          const msg = (e.response && e.response.data && e.response.data.message) || e.message;
          this.$message.error('续跑失败: ' + msg);
        } finally {
          this.continuingStep = false;
        }
      }).catch(() => {});
    },
    async handleRunMonitor() {
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
          this.refreshAllComponents();
          if (res && res.paused) {
            this.notifyManualPresetStepPause(res);
          } else {
            this.$message.success('监控运行完成');
          }
        } catch (e) {
          const msg = (e.response && e.response.data && e.response.data.message) || e.message;
          this.$message.error('运行失败: ' + msg);
        } finally {
          this.running = false;
        }
      }).catch(() => {});
    },
    refreshAllComponents() {
      // 刷新所有子组件的数据
      const refs = ['dashboard', 'navHistory', 'positions', 'signals', 'subjective', 'eventLog', 'publishLog'];
      refs.forEach(refName => {
        const component = this.$refs[refName];
        if (component && typeof component.loadData === 'function') {
          component.loadData();
        }
      });
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}

.monitor-center {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-left {
  flex: 1;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.page-title {
  font-size: 20px;
  margin: 0 0 8px 0;
}

.page-desc {
  color: #909399;
  font-size: 14px;
  margin: 0;
}

.page-strategy-inline {
  margin: 8px 0 0 0;
  font-size: 14px;
  color: #606266;
}

.page-strategy-meta {
  color: #909399;
  font-weight: normal;
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

.strategy-context-assets {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #ebeef5;
}

.strategy-context-assets-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.strategy-context-assets-label {
  font-size: 13px;
  color: #909399;
}

.strategy-context-assets-hint {
  font-size: 12px;
  color: #409eff;
  font-weight: 500;
}

.strategy-context-assets--interactive {
  cursor: pointer;
  border-radius: 6px;
  margin-left: -4px;
  margin-right: -4px;
  padding-left: 4px;
  padding-right: 4px;
  transition: background-color 0.15s ease;
}

.strategy-context-assets--interactive:hover {
  background: rgba(64, 158, 255, 0.06);
}

.strategy-context-asset-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.strategy-context-assets-empty {
  font-size: 13px;
  color: #c0c4cc;
}

.strategy-context-asset-tag {
  margin: 0 !important;
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

.live-effective-params {
  margin-top: 14px;
  padding: 14px 14px 12px;
  background: linear-gradient(145deg, #f9fafb 0%, #f4f6f9 100%);
  border-radius: 8px;
  border: 1px solid #ebeef5;
}

.live-effective-params-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.live-effective-params-note {
  margin: 4px 0 0 0;
  font-size: 12px;
  color: #909399;
  line-height: 1.45;
  max-width: 720px;
}

.live-effective-link {
  flex-shrink: 0;
  padding: 0 !important;
}

.live-effective-params-title {
  font-size: 12px;
  color: #909399;
  letter-spacing: 0.06em;
  font-weight: 600;
}

.live-param-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.live-param-metric {
  min-width: 118px;
  padding: 10px 14px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.live-param-metric--interactive {
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.live-param-metric--interactive:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
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

.live-param-metric-wide {
  flex: 1 1 200px;
}

.live-param-metric-label {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.live-param-metric-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.live-param-metric-value.subtle {
  font-size: 15px;
  font-weight: 600;
}

.live-manual-snapshot-hint {
  margin: 0 0 10px 0 !important;
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

.live-param-unit {
  font-size: 13px;
  font-weight: 500;
  color: #909399;
  margin-left: 1px;
}

.live-window-section {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #e4e7ed;
}

.live-asset-classes {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #e4e7ed;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.live-block-label {
  font-size: 13px;
  color: #909399;
  margin-right: 4px;
}

.live-class-tag {
  margin: 0 !important;
}

.monitor-section {
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 16px;
  font-weight: 600;
}

.section-desc {
  margin: 0 0 14px 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
}

.strategy-context-card {
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}

.strategy-context-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.strategy-context-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.strategy-context-label {
  color: #909399;
  font-size: 13px;
}

.strategy-context-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.strategy-context-id {
  font-size: 12px;
  color: #c0c4cc;
  margin-left: 8px;
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
</style>
