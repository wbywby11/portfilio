<template>
  <div class="page-container monitor-center">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">日常监控</h2>
        <p class="page-desc">组合净值跟踪、信号检测与调仓管理（按已实盘发布的 risk_budget_target_vol + 混合动量策略实例隔离）</p>
        <p v-if="!eligibleLoading && currentStrategy" class="page-strategy-inline">
          已选策略：<strong>{{ currentStrategy.name }}</strong>
          <span class="page-strategy-meta">（{{ currentStrategy.template_code }}<template v-if="currentStrategy.selector_type === 'hybrid'"> · 混合动量</template>）</span>
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
        <el-button type="warning" icon="el-icon-s-operation" :disabled="!canOperateMonitor" @click="showInitDialog">初始化</el-button>
        <el-button type="primary" icon="el-icon-video-play" :disabled="!canOperateMonitor" @click="handleRunMonitor" :loading="running">运行监控</el-button>
      </div>
    </div>

    <el-alert
      v-if="!eligibleLoading && !hasEligibleStrategies"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 16px;"
      title="暂无准入策略"
      description="日常监控需要至少一条已实盘发布的「risk_budget_target_vol + 混合动量资产选择」策略。请先在策略模型中启用混合动量并完成实盘发布。">
    </el-alert>

    <el-alert
      v-if="!eligibleLoading && hasEligibleStrategies && !hasPublishedLiveStrategy"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px;"
      title="当前仅系统基准（config.py）"
      description="下拉中的「系统基准」对应 monitor_id=default，参数与绩效可与 app/monitor/config.py 对照。若需对比实盘发布的策略实例，请在策略模型中完成混合动量配置与实盘发布。">
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
          <span class="strategy-context-id">
            {{ currentStrategy.is_config_baseline ? '监控实例：default（app/monitor/config.py）' : '模型 ID：' + activeMonitorId }}
          </span>
        </div>
        <div class="strategy-context-status">
          <el-tag v-if="!monitorState" type="warning" effect="dark">监控未初始化</el-tag>
          <el-tag v-else type="success" effect="plain">监控已就绪 · 数据日期 {{ formatStrategyDate(monitorState.date) }}</el-tag>
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
        <div class="live-param-metrics">
          <div
            class="live-param-metric"
            :class="{ 'live-param-metric--interactive': canClickLiveParams }"
            @click.stop="canClickLiveParams && openQuickEdit('target_vol')">
            <span class="live-param-metric-label">目标波动</span>
            <span class="live-param-metric-value">{{ liveEffectiveParams.target_vol_pct }}<span class="live-param-unit">%</span></span>
          </div>
          <div
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
        <div v-if="liveEffectiveParams.asset_classes && liveEffectiveParams.asset_classes.length" class="live-asset-classes">
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
              v-if="liveEffectiveParams.min_history_momentum != null && liveEffectiveParams.min_history_momentum !== ''"
              class="live-param-metric"
              :class="{ 'live-param-metric--interactive': canClickLiveParams }"
              @click.stop="canClickLiveParams && openQuickEdit('min_history_days')">
              <span class="live-param-metric-label">动量最小历史</span>
              <span class="live-param-metric-value subtle">{{ liveEffectiveParams.min_history_momentum }} 日</span>
            </div>
            <div
              v-if="liveEffectiveParams.min_history_reversal != null && liveEffectiveParams.min_history_reversal !== ''"
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
        v-if="effectiveAssetTags.length"
        class="strategy-context-assets">
        <span class="strategy-context-assets-label">底层资产（参与计算）</span>
        <el-tag
          v-for="(nm, idx) in effectiveAssetTags"
          :key="'ctx-' + idx"
          size="small"
          type="info"
          effect="plain"
          class="strategy-context-asset-tag">
          {{ nm }}
        </el-tag>
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
          :rows="3"
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
        <Signals ref="signals" />
      </el-card>

      <!-- 区域5：主观调仓 -->
      <el-card shadow="never" class="monitor-section">
        <div slot="header" class="section-header">
          <span>主观调仓</span>
        </div>
        <SubjectiveOverride ref="subjective" />
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
import MonitorDashboard from './Index.vue';
import NavHistory from './NavHistory.vue';
import Positions from './Positions.vue';
import Signals from './Signals.vue';
import SubjectiveOverride from './SubjectiveOverride.vue';
import EventLog from './EventLog.vue';
import LivePublishRecords from './LivePublishRecords.vue';

export default {
  name: 'MonitorCenter',
  components: {
    MonitorDashboard,
    NavHistory,
    Positions,
    Signals,
    SubjectiveOverride,
    EventLog,
    LivePublishRecords
  },
  data() {
    return {
      initDialogVisible: false,
      initStartDate: '2014-02-10',
      initializing: false,
      running: false,
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
      quickEditSourceModel: null
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
      if (!p) return false;
      return !!(
        p.mom_windows ||
        p.reversal_windows ||
        p.macd_windows ||
        (p.macd_long_window != null && p.macd_long_window !== '')
      );
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
    },
    async openQuickEdit(rawKey) {
      if (!this.canClickLiveParams || !this.activeMonitorId) return;
      const key = rawKey === 'min_history_reversal_hint' ? 'reversal_windows' : rawKey;
      const meta = this.quickEditMeta(key);
      if (!meta) return;
      this.quickEditKey = key;
      this.quickEditTitle = meta.title;
      this.quickEditHint = rawKey === 'min_history_reversal_hint'
        ? '反转最小历史由「反转」两档窗口决定，请编辑反转窗口（两档、逗号分隔）。'
        : (meta.hint || '');
      this.quickEditInputType = meta.inputType;
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
          built = meta.build(s);
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
        await this.initMonitorAction({ start_date: this.initStartDate });
        this.$message.success('初始化完成');
        this.initDialogVisible = false;
        // 刷新子组件数据
        this.refreshAllComponents();
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.message) || e.message;
        this.$message.error('初始化失败: ' + msg);
      } finally {
        this.initializing = false;
      }
    },
    async handleRunMonitor() {
      this.$confirm('确认运行日常监控？', '提示', { type: 'info' }).then(async () => {
        this.running = true;
        try {
          await this.runMonitorAction({});
          this.$message.success('监控运行完成');
          // 刷新子组件数据
          this.refreshAllComponents();
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

.strategy-context-assets {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #ebeef5;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.strategy-context-assets-label {
  font-size: 13px;
  color: #909399;
  margin-right: 4px;
}

.strategy-context-asset-tag {
  margin: 0 !important;
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
