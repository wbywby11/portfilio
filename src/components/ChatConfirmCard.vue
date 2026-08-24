<template>
  <div class="confirm-card" :class="'status-' + statusKey">
    <div class="confirm-card-header">
      <i class="confirm-card-icon" :class="headerIcon"></i>
      <span class="confirm-card-title">{{ toolLabel }}</span>
      <span class="confirm-status-badge" :class="'badge-' + statusKey">{{ statusLabel }}</span>
    </div>

    <!-- 操作预览：目标对象与关键参数 -->
    <div class="confirm-card-body" v-if="previewRows.length">
      <div class="confirm-preview-title">操作预览</div>
      <table class="confirm-preview-table">
        <tbody>
          <tr v-for="(row, idx) in previewRows" :key="'pv_' + idx">
            <td class="preview-key">{{ row.key }}</td>
            <td class="preview-value">{{ row.value }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 执行结果 / 失败原因（终态） -->
    <div class="confirm-card-result" :class="{ 'is-error': !!card.error }" v-if="resultText">
      <i :class="card.error ? 'el-icon-warning-outline' : 'el-icon-success'"></i>
      <span>{{ resultText }}</span>
    </div>

    <!-- 待确认时的操作按钮 -->
    <div class="confirm-card-footer" v-if="isPending">
      <el-button
        size="mini"
        :disabled="!!card._busy"
        @click="$emit('decide', 'rejected')"
      >取消</el-button>
      <el-button
        size="mini"
        type="primary"
        :loading="!!card._busy"
        @click="$emit('decide', 'confirmed')"
      >确认执行</el-button>
    </div>
  </div>
</template>

<script>
/** 写工具名 → 中文操作名（卡片标题） */
const TOOL_LABELS = {
  'run_backtest': '执行回测',
  'create_portfolio': '创建组合',
  'adjust_portfolio': '调整组合',
  'update_monitor_config': '更新监控配置',
  'trigger_data_sync': '触发数据同步',
  'save_report': '保存报告'
}

const STATUS_META = {
  pending: { label: '待确认', icon: 'el-icon-s-check' },
  confirmed: { label: '已执行', icon: 'el-icon-circle-check' },
  rejected: { label: '已取消', icon: 'el-icon-remove-outline' },
  expired: { label: '已过期', icon: 'el-icon-time' },
  failed: { label: '执行失败', icon: 'el-icon-warning' }
}

/** 预览值序列化：对象/数组转紧凑 JSON，超长截断 */
function formatPreviewValue(v) {
  if (v === null || v === undefined) return '-'
  let text
  if (typeof v === 'object') {
    try { text = JSON.stringify(v) } catch (e) { text = String(v) }
  } else {
    text = String(v)
  }
  return text.length > 200 ? text.slice(0, 200) + '…' : text
}

export default {
  name: 'ChatConfirmCard',
  props: {
    card: {
      type: Object,
      required: true
    }
  },
  computed: {
    statusKey() {
      const s = this.card.status
      if (s === 'pending_confirmation' || s === 'pending') return 'pending'
      if (STATUS_META[s]) return s
      return 'pending'
    },
    isPending() {
      return this.statusKey === 'pending'
    },
    statusLabel() {
      return STATUS_META[this.statusKey].label
    },
    headerIcon() {
      return STATUS_META[this.statusKey].icon
    },
    toolLabel() {
      const name = this.card.tool_name || ''
      return TOOL_LABELS[name] || name || '写操作'
    },
    previewRows() {
      const preview = this.card.preview
      if (!preview || typeof preview !== 'object') return []
      return Object.keys(preview).map(key => ({
        key,
        value: formatPreviewValue(preview[key])
      }))
    },
    resultText() {
      if (this.isPending) return ''
      if (this.card.error) return this.card.error
      if (this.card.result_summary) return this.card.result_summary
      if (this.statusKey === 'confirmed') return '操作已执行完成'
      if (this.statusKey === 'rejected') return '已取消该操作，未产生任何变更'
      if (this.statusKey === 'expired') return '确认已过期（超过 30 分钟），请重新发起操作'
      return ''
    }
  }
}
</script>

<style scoped>
.confirm-card {
  margin-top: 14px;
  background: #fff;
  border: 1px solid #e8ebf0;
  border-left: 3px solid #e6a23c;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}

.confirm-card.status-confirmed { border-left-color: #67c23a; }
.confirm-card.status-rejected { border-left-color: #909399; }
.confirm-card.status-expired { border-left-color: #c0c4cc; }
.confirm-card.status-failed { border-left-color: #f56c6c; }

.confirm-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: linear-gradient(180deg, #fafbfc 0%, #ffffff 100%);
  border-bottom: 1px solid #f2f3f5;
}

.confirm-card-icon {
  font-size: 16px;
  color: #e6a23c;
}

.status-confirmed .confirm-card-icon { color: #67c23a; }
.status-rejected .confirm-card-icon { color: #909399; }
.status-expired .confirm-card-icon { color: #c0c4cc; }
.status-failed .confirm-card-icon { color: #f56c6c; }

.confirm-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.confirm-status-badge {
  margin-left: auto;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 18px;
}

.badge-pending { background: #fdf6ec; color: #e6a23c; border: 1px solid #faecd8; }
.badge-confirmed { background: #f0f9eb; color: #67c23a; border: 1px solid #e1f3d8; }
.badge-rejected { background: #f4f4f5; color: #909399; border: 1px solid #e9e9eb; }
.badge-expired { background: #f4f4f5; color: #c0c4cc; border: 1px solid #ebeef5; }
.badge-failed { background: #fef0f0; color: #f56c6c; border: 1px solid #fde2e2; }

.confirm-card-body {
  padding: 10px 16px 4px;
}

.confirm-preview-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.confirm-preview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.confirm-preview-table td {
  padding: 5px 8px;
  border-bottom: 1px solid #f5f7fa;
  vertical-align: top;
}

.preview-key {
  width: 140px;
  color: #909399;
  white-space: nowrap;
}

.preview-value {
  color: #303133;
  word-break: break-all;
}

.confirm-card-result {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 10px 16px;
  font-size: 13px;
  color: #67c23a;
  background: #fbfdf9;
}

.confirm-card-result.is-error {
  color: #f56c6c;
  background: #fefaf9;
}

.confirm-card-result i {
  margin-top: 2px;
  font-size: 14px;
}

.confirm-card-result span {
  word-break: break-all;
}

.confirm-card-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 16px 14px;
}
</style>
