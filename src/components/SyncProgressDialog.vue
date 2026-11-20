<template>
  <el-dialog
    :title="title"
    :visible.sync="visible"
    width="560px"
    :close-on-click-modal="false"
    :close-on-press-escape="!loading"
    @close="handleClose"
  >
    <div class="sync-progress">
      <el-progress
        v-if="loading"
        :percentage="percent >= 0 ? percent : 0"
        :status="progressStatus"
        :stroke-width="12"
      />
      <div v-if="loading && currentPhase" class="phase-text">
        {{ currentPhase }}
      </div>
      <div class="log-box" ref="logBox">
        <div
          v-for="(line, index) in logLines"
          :key="index"
          class="log-line"
        >
          {{ line }}
        </div>
        <div v-if="loading && logLines.length === 0" class="log-placeholder">
          正在连接并拉取进度…
        </div>
      </div>
    </div>
    <span slot="footer" class="dialog-footer">
      <el-button v-if="!loading" type="primary" @click="visible = false">关闭</el-button>
      <el-button v-else disabled>同步中…</el-button>
    </span>
  </el-dialog>
</template>

<script>
import { syncTodayStream, maintainStream } from '@/api/market';

export default {
  name: 'SyncProgressDialog',
  data() {
    return {
      visible: false,
      loading: false,
      mode: 'syncToday', // 'syncToday' | 'maintain'
      groupId: '',
      title: '同步行情',
      logLines: [],
      percent: -1,
      currentPhase: '',
      // 进行中为 null：el-progress 的 status 不接受空串（会触发 prop 校验告警）
      progressStatus: null
    };
  },
  methods: {
    /** 打开「同步当日行情」 */
    openSyncToday() {
      this.mode = 'syncToday';
      this.title = '同步当日行情';
      this.groupId = '';
      this.open();
      this.runSyncToday();
    },
    /** 打开「组合数据维护」 */
    openMaintain(gid) {
      this.mode = 'maintain';
      this.title = '组合数据维护';
      this.groupId = gid || '';
      this.open();
      this.runMaintain();
    },
    open() {
      this.visible = true;
      this.loading = true;
      this.logLines = [];
      this.percent = 0;
      this.currentPhase = '连接中…';
      this.progressStatus = null;
    },
    appendLog(text) {
      if (text == null || String(text).trim() === '') return;
      this.logLines.push(String(text).trim());
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = box.scrollHeight;
      });
    },
    runSyncToday() {
      syncTodayStream(
        (data) => this.onProgress(data),
        (payload) => this.onDone(payload)
      );
    },
    runMaintain() {
      if (!this.groupId) {
        this.appendLog('缺少分组 ID');
        this.loading = false;
        return;
      }
      maintainStream(
        this.groupId,
        (data) => this.onProgress(data),
        (payload) => this.onDone(payload)
      );
    },
    onProgress(data) {
      if (data.log != null) {
        this.appendLog(data.log);
      }
      if (data.phase_label != null) {
        this.currentPhase = data.phase_label;
      }
      if (data.percent != null && data.percent >= 0) {
        this.percent = Math.min(100, data.percent);
      } else if (data.total != null && data.total > 0 && data.current != null) {
        this.percent = Math.min(100, Math.round((100 * data.current) / data.total));
      }
      if (data.message != null && data.log == null) {
        this.appendLog(data.message);
      }
      if (data.phase === 'ingest' && data.message && data.log == null) {
        this.appendLog(data.message);
      }
    },
    onDone(payload) {
      this.loading = false;
      if (payload.error) {
        this.progressStatus = 'exception';
        this.appendLog('错误: ' + payload.error);
        this.$message.error(payload.error);
        return;
      }
      this.progressStatus = 'success';
      this.percent = 100;
      const res = payload.result || {};
      if (res.skipped) {
        this.appendLog(res.message || '当日已同步，已跳过');
        this.$message.info(res.message || '当日已同步');
      } else {
        const parts = [];
        if (res.stock_ingested != null) parts.push('个股入库 ' + res.stock_ingested + ' 条');
        if (res.index_synced != null) parts.push('指数同步 ' + res.index_synced);
        if (res.sector_synced != null) parts.push('板块同步 ' + res.sector_synced);
        if (res.errors && res.errors.length) parts.push('失败 ' + res.errors.length + ' 项');
        this.appendLog('维护完成: ' + (parts.length ? parts.join('；') : '成功'));
        this.$message.success('同步完成');
      }
      this.$emit('sync-success');
    },
    handleClose() {
      if (this.loading) {
        this.appendLog('已关闭（任务可能仍在后端执行）');
      }
    }
  }
};
</script>

<style scoped>
.sync-progress {
  min-height: 120px;
}
.phase-text {
  margin: 8px 0 6px;
  color: #409eff;
  font-size: 13px;
}
.log-box {
  margin-top: 12px;
  max-height: 280px;
  overflow-y: auto;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 4px;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.5;
}
.log-line {
  word-break: break-all;
  color: #303133;
}
.log-placeholder {
  color: #909399;
}
</style>
