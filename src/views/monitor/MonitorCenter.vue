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
          <span class="strategy-context-id">模型 ID：{{ activeMonitorId }}</span>
        </div>
        <div class="strategy-context-status">
          <el-tag v-if="!monitorState" type="warning" effect="dark">监控未初始化</el-tag>
          <el-tag v-else type="success" effect="plain">监控已就绪 · 数据日期 {{ formatStrategyDate(monitorState.date) }}</el-tag>
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

    <template v-if="hasEligibleStrategies && activeMonitorId">
      <!-- 区域1：监控总览 -->
      <el-card shadow="never" class="monitor-section">
        <div slot="header" class="section-header">
          <span>监控总览</span>
        </div>
        <MonitorDashboard ref="dashboard" />
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
    </template>
  </div>
</template>

<script>
import { mapActions, mapGetters, mapState } from 'vuex';
import dayjs from 'dayjs';
import { getLiveEligibleForMonitor } from '@/api/strategy';
import MonitorDashboard from './Index.vue';
import NavHistory from './NavHistory.vue';
import Positions from './Positions.vue';
import Signals from './Signals.vue';
import SubjectiveOverride from './SubjectiveOverride.vue';
import EventLog from './EventLog.vue';

export default {
  name: 'MonitorCenter',
  components: {
    MonitorDashboard,
    NavHistory,
    Positions,
    Signals,
    SubjectiveOverride,
    EventLog
  },
  data() {
    return {
      initDialogVisible: false,
      initStartDate: '2014-02-10',
      initializing: false,
      running: false,
      eligibleLoading: true,
      eligibleStrategies: [],
      selectedStrategyId: null
    };
  },
  computed: {
    ...mapGetters('monitor', ['activeMonitorId']),
    ...mapState('monitor', ['monitorState']),
    hasEligibleStrategies() {
      return this.eligibleStrategies.length > 0;
    },
    canOperateMonitor() {
      return this.hasEligibleStrategies && !!this.activeMonitorId;
    },
    currentStrategy() {
      if (!this.activeMonitorId) return null;
      return this.eligibleStrategies.find(s => s.id === this.activeMonitorId) || null;
    }
  },
  async created() {
    await this.loadEligibleContext();
  },
  methods: {
    ...mapActions('monitor', ['initMonitorAction', 'runMonitorAction', 'setActiveMonitorContext']),
    formatStrategyOption(s) {
      const sel = s.selector_type === 'hybrid' ? '混合动量' : (s.selector_type || '');
      return `${s.name || s.id}（${s.template_code || ''}${sel ? ' · ' + sel : ''}）`;
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
          const firstId = this.eligibleStrategies[0].id;
          this.selectedStrategyId = firstId;
          await this.setActiveMonitorContext({ monitorId: firstId });
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
      const refs = ['dashboard', 'navHistory', 'positions', 'signals', 'subjective', 'eventLog'];
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
