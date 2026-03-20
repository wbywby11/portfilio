<template>
  <div class="page-container monitor-center">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">日常监控</h2>
        <p class="page-desc">组合净值跟踪、信号检测与调仓管理</p>
      </div>
      <div class="header-actions">
        <el-button type="warning" icon="el-icon-s-operation" @click="showInitDialog">初始化</el-button>
        <el-button type="primary" icon="el-icon-video-play" @click="handleRunMonitor" :loading="running">运行监控</el-button>
      </div>
    </div>

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
  </div>
</template>

<script>
import { mapActions } from 'vuex';
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
      running: false
    };
  },
  methods: {
    ...mapActions('monitor', ['initMonitorAction', 'runMonitorAction']),
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

/* 移除子组件的外层padding和header，避免重复 */
.monitor-section >>> .page-container {
  padding: 0;
}

.monitor-section >>> .page-header {
  display: none;
}
</style>
