<template>
  <div class="risk-alerts" v-loading="loading">
    <div class="risk-alerts__toolbar">
      <div class="risk-alerts__summary">
        <el-tag v-if="counts.red" size="mini" type="danger" effect="dark">严重 {{ counts.red }}</el-tag>
        <el-tag v-if="counts.yellow" size="mini" type="warning">关注 {{ counts.yellow }}</el-tag>
        <el-tag v-if="counts.green" size="mini" type="success">正常 {{ counts.green }}</el-tag>
        <el-tag v-if="counts.info" size="mini" type="info">提示 {{ counts.info }}</el-tag>
        <span v-if="updatedDate" class="risk-alerts__date-hint">信号日 {{ updatedDate }}</span>
      </div>
      <el-button size="mini" icon="el-icon-refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <!-- 主列表：red 置顶、yellow 次之（后端按 severity 排序，同级按信号日倒序） -->
    <div
      v-for="row in mainAlerts"
      :key="row.alert_id"
      class="risk-alert-row"
      :class="'risk-alert-row--' + row.severity">
      <el-tag :type="severityTagType(row.severity)" size="mini" effect="dark" class="risk-alert-row__sev">
        {{ severityLabel(row.severity) }}
      </el-tag>
      <el-tag size="mini" class="risk-alert-row__kind">{{ kindLabel(row.monitor_kind) }}</el-tag>
      <span class="risk-alert-row__assets" :title="row.asset_codes.join('、')">{{ assetsText(row) }}</span>
      <span class="risk-alert-row__metric">{{ metricLabel(row) }}<strong>{{ metricValue(row) }}</strong></span>
      <span class="risk-alert-row__threshold">阈值 {{ numText(row.threshold) }}</span>
      <span class="risk-alert-row__window">{{ windowText(row) }}</span>
      <span class="risk-alert-row__date">{{ row.signal_date }}</span>
    </div>

    <!-- 折叠区：绿色与提示（含停更跳过汇总） -->
    <el-collapse v-if="foldedItems.length || staleSkip" v-model="foldedOpen" class="risk-alerts__folded">
      <el-collapse-item name="folded">
        <template slot="title">
          <span class="risk-alerts__folded-title">绿色与提示（{{ foldedItems.length + (staleSkip ? 1 : 0) }} 项）</span>
        </template>

        <!-- 停更跳过：不静默丢弃，明确告知哪些资产未参与检测 -->
        <div v-if="staleSkip" class="risk-alerts__stale-tip">
          <i class="el-icon-info"></i>
          <span>{{ staleSkipCount }} 个资产因行情停更未参与检测</span>
          <span class="risk-alerts__stale-assets">{{ (staleSkip.asset_codes || []).join('、') }}</span>
        </div>

        <div
          v-for="row in foldedItems"
          :key="row.alert_id"
          class="risk-alert-row risk-alert-row--small"
          :class="'risk-alert-row--' + row.severity">
          <el-tag :type="severityTagType(row.severity)" size="mini" class="risk-alert-row__sev">
            {{ severityLabel(row.severity) }}
          </el-tag>
          <el-tag size="mini" class="risk-alert-row__kind">{{ kindLabel(row.monitor_kind) }}</el-tag>
          <span class="risk-alert-row__assets" :title="row.asset_codes.join('、')">{{ assetsText(row) }}</span>
          <span class="risk-alert-row__metric">{{ metricLabel(row) }}<strong>{{ metricValue(row) }}</strong></span>
          <span class="risk-alert-row__threshold">阈值 {{ numText(row.threshold) }}</span>
          <span class="risk-alert-row__window">{{ windowText(row) }}</span>
          <span class="risk-alert-row__date">{{ row.signal_date }}</span>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- 空态：无预警时统一文案；加载失败不渲染错误信息，按无预警展示 -->
    <el-empty
      v-if="!loading && !mainAlerts.length && !foldedItems.length && !staleSkip"
      description="暂无风险预警"
      :image-size="60" />
  </div>
</template>

<script>
import { getRiskAlerts } from '@/api/monitor';

export default {
  name: 'RiskAlerts',
  props: {
    monitorId: {
      type: String,
      default: ''
    },
    /** 当前展示批次；为空时后端回落到最新 completed 批次 */
    batchId: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      loading: false,
      items: [],
      counts: { red: 0, yellow: 0, green: 0, info: 0 },
      foldedOpen: [],
      requestSeq: 0
    };
  },
  computed: {
    /** 主列表：red + yellow（保持后端排序） */
    mainAlerts() {
      return this.items.filter(r => r.severity === 'red' || r.severity === 'yellow');
    },
    /** 折叠区：green + 非 stale_skip 的 info */
    foldedItems() {
      return this.items.filter(
        r => r.severity === 'green' || (r.severity === 'info' && r.signal_type !== 'stale_skip')
      );
    },
    /** 停更跳过汇总（同一批次只取最新一条） */
    staleSkip() {
      return this.items.find(r => r.signal_type === 'stale_skip') || null;
    },
    staleSkipCount() {
      return this.staleSkip ? Number(this.staleSkip.trigger_value || 0) : 0;
    },
    /** 最新信号日（列表首条即按信号日倒序） */
    updatedDate() {
      return this.items.length ? this.items[0].signal_date : '';
    }
  },
  watch: {
    monitorId: {
      immediate: true,
      handler() {
        this.load();
      }
    },
    // 预警按批次归档，切换批次要重拉对应快照；本组件不在 refreshAllComponents 的 ref 列表里，只能靠 prop watcher
    batchId() {
      this.load();
    }
  },
  methods: {
    async load() {
      if (!this.monitorId) {
        this.items = [];
        this.counts = { red: 0, yellow: 0, green: 0, info: 0 };
        return;
      }
      const seq = ++this.requestSeq;
      this.loading = true;
      try {
        const res = await getRiskAlerts({
          monitor_id: this.monitorId,
          limit: 200,
          batch_id: this.batchId || undefined
        });
        // 快速切换实例时丢弃过期响应
        if (seq !== this.requestSeq) return;
        const data = res.data || res || {};
        this.items = Array.isArray(data.items) ? data.items : [];
        this.counts = data.counts || { red: 0, yellow: 0, green: 0, info: 0 };
      } catch (error) {
        if (seq !== this.requestSeq) return;
        // 空态优先：请求失败不显示错误态，避免「加载失败」干扰风控页
        console.warn('RiskAlerts 加载风险预警失败:', error.message);
        this.items = [];
        this.counts = { red: 0, yellow: 0, green: 0, info: 0 };
      } finally {
        if (seq === this.requestSeq) this.loading = false;
      }
    },
    severityTagType(severity) {
      return { red: 'danger', yellow: 'warning', green: 'success', info: 'info' }[severity] || 'info';
    },
    severityLabel(severity) {
      return { red: '严重', yellow: '关注', green: '正常', info: '提示' }[severity] || severity;
    },
    kindLabel(kind) {
      return { strategy: '策略', portfolio: '组合' }[kind] || kind || '-';
    },
    assetsText(row) {
      const codes = row.asset_codes || [];
      if (!codes.length) return '-';
      return codes.length > 2 ? `${codes.slice(0, 2).join('、')} 等${codes.length}个` : codes.join('、');
    },
    metricLabel(row) {
      return {
        corr_reversal: '相关性',
        vol_compare: '波动率比',
        stale_skip: '跳过数'
      }[row.signal_type] || '指标';
    },
    metricValue(row) {
      return this.numText(row.trigger_value);
    },
    numText(value) {
      const n = Number(value);
      return Number.isFinite(n) ? n.toFixed(2) : '-';
    },
    windowText(row) {
      const w = row.window_pair || {};
      if (w.short && w.long) return `${w.short}/${w.long}日`;
      if (w.window && w.baseline_window) return `${w.window}日/中枢${w.baseline_window}日`;
      return '-';
    }
  }
};
</script>

<style scoped>
.risk-alerts {
  min-height: 80px;
}

.risk-alerts__toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.risk-alerts__summary {
  display: flex;
  align-items: center;
  gap: 8px;
}

.risk-alerts__date-hint {
  font-size: 12px;
  color: #909399;
  margin-left: 4px;
}

.risk-alert-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-left: 3px solid #dcdfe6;
  border-radius: 2px;
  background: #fafafa;
  margin-bottom: 6px;
  font-size: 13px;
  color: #303133;
}

.risk-alert-row--red {
  border-left-color: #f56c6c;
  background: #fef0f0;
}

.risk-alert-row--yellow {
  border-left-color: #e6a23c;
  background: #fdf6ec;
}

.risk-alert-row--green {
  border-left-color: #67c23a;
}

.risk-alert-row--small {
  font-size: 12px;
  padding: 6px 10px;
  margin-bottom: 4px;
}

.risk-alert-row__assets {
  min-width: 120px;
  font-weight: 500;
}

.risk-alert-row__metric strong {
  margin-left: 4px;
  font-weight: 600;
}

.risk-alert-row__threshold,
.risk-alert-row__window {
  color: #606266;
}

.risk-alert-row__date {
  margin-left: auto;
  color: #909399;
  white-space: nowrap;
}

.risk-alerts__folded {
  margin-top: 4px;
}

.risk-alerts__folded-title {
  font-size: 13px;
  color: #606266;
}

.risk-alerts__stale-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #909399;
  padding: 6px 10px;
  margin-bottom: 6px;
  background: #f4f4f5;
  border-radius: 2px;
}

.risk-alerts__stale-assets {
  color: #c0c4cc;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
