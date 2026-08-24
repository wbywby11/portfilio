<template>
  <div class="batches-panel">
    <el-card class="toolbar-card" shadow="never">
      <div class="toolbar">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button label="timeline"><i class="el-icon-time"></i> 时间线</el-radio-button>
          <el-radio-button label="table"><i class="el-icon-s-grid"></i> 表格</el-radio-button>
        </el-radio-group>
        <el-button icon="el-icon-refresh" size="small" @click="reload" :loading="loading" style="margin-left: auto;">刷新</el-button>
      </div>
    </el-card>

    <el-card v-if="viewMode === 'timeline'" class="view-card" shadow="never" v-loading="loading">
      <div v-if="!batches.length && !loading" class="empty">
        <i class="el-icon-time" style="font-size: 36px; color: #c0c4cc;"></i>
        <div class="muted" style="margin-top: 10px;">暂无导入批次</div>
      </div>
      <el-timeline v-else>
        <el-timeline-item
          v-for="b in batches"
          :key="b.batch_id"
          :timestamp="b.started_at + ' (' + (b.duration_ms || 0) + 'ms)'"
          :type="timelineType(b.status)"
          placement="top"
          :hollow="b.status === 'running'"
        >
          <el-card class="timeline-card" shadow="hover" @click.native="openDetail(b)">
            <div class="tl-header">
              <el-tag :type="statusTagType(b.status)" size="small" effect="dark">{{ statusLabel(b.status) }}</el-tag>
              <span v-if="importParamStyle === 'date_range'" class="tl-params">{{ getParamMapField(b, 'startDate', '?') }} ~ {{ getParamMapField(b, 'endDate', '?') }}</span>
              <span class="batch-id muted">#{{ shortId(b.batch_id) }}</span>
            </div>
            <div v-if="b.upstream_page_msg" class="tl-page-msg muted"><i class="el-icon-warning-outline"></i> {{ shorten(b.upstream_page_msg, 120) }}</div>
            <div class="tl-stats">
              <div class="tl-stat"><span class="lbl">上游返回</span><span class="val">{{ b.total_returned || 0 }}</span></div>
              <div class="tl-stat"><span class="lbl">新增</span><span class="val success">{{ b.inserted || 0 }}</span></div>
              <div class="tl-stat"><span class="lbl">更新</span><span class="val primary">{{ b.updated || 0 }}</span></div>
              <div class="tl-stat" v-if="b.skipped_no_key"><span class="lbl">跳过</span><span class="val warn">{{ b.skipped_no_key }}</span></div>
              <div class="tl-stat" v-if="b.failed"><span class="lbl">失败</span><span class="val danger">{{ b.failed }}</span></div>
              <div class="tl-stat" v-if="b.msg_list && b.msg_list.length"><span class="lbl">告警</span><span class="val info">{{ b.msg_list.length }}</span></div>
            </div>
            <div v-if="b.error" class="tl-error"><i class="el-icon-warning"></i> {{ b.error }}</div>
          </el-card>
        </el-timeline-item>
      </el-timeline>
      <div v-if="batches.length" class="pagination-wrap">
        <el-pagination background layout="total, prev, pager, next" :current-page.sync="page" :page-size="pageSize" :total="total" @current-change="reload" />
      </div>
    </el-card>

    <el-card v-else class="view-card" shadow="never">
      <el-table v-loading="loading" :data="batches" border stripe size="mini" height="560" @row-click="openDetail" style="cursor: pointer;">
        <el-table-column prop="started_at" label="开始时间" width="180" />
        <el-table-column label="状态" width="120" fixed>
          <template v-slot="{ row }"><el-tag :type="statusTagType(row.status)" size="mini" effect="dark">{{ statusLabel(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="日期区间" min-width="220">
          <template v-slot="{ row }">
            <span>{{ getParamMapField(row, 'startDate', '-') }}</span><span class="muted"> ~ </span><span>{{ getParamMapField(row, 'endDate', '-') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="total_returned" label="返回" width="90" align="right" />
        <el-table-column prop="inserted" label="新增" width="90" align="right"><template v-slot="{ row }"><span class="num success">{{ row.inserted || 0 }}</span></template></el-table-column>
        <el-table-column prop="updated" label="更新" width="90" align="right"><template v-slot="{ row }"><span class="num primary">{{ row.updated || 0 }}</span></template></el-table-column>
        <el-table-column prop="skipped_no_key" label="跳过" width="90" align="right"><template v-slot="{ row }"><span class="num warn" v-if="row.skipped_no_key">{{ row.skipped_no_key }}</span><span v-else class="muted">-</span></template></el-table-column>
        <el-table-column prop="failed" label="失败" width="90" align="right"><template v-slot="{ row }"><span class="num danger" v-if="row.failed">{{ row.failed }}</span><span v-else class="muted">-</span></template></el-table-column>
        <el-table-column prop="duration_ms" label="耗时" width="110" align="right"><template v-slot="{ row }">{{ formatDuration(row.duration_ms) }}</template></el-table-column>
        <el-table-column label="批次 ID" width="120"><template v-slot="{ row }"><code class="batch-id">{{ shortId(row.batch_id) }}</code></template></el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template v-slot="{ row }">
            <el-button type="text" size="mini" icon="el-icon-view" @click.stop="openDetail(row)">详情</el-button>
            <el-button type="text" size="mini" icon="el-icon-search" @click.stop="viewRecords(row)">查看记录</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination background layout="total, sizes, prev, pager, next, jumper" :current-page.sync="page" :page-size.sync="pageSize" :page-sizes="[10, 20, 50]" :total="total" @size-change="reload" @current-change="reload" />
      </div>
    </el-card>

    <el-drawer :visible.sync="detailVisible" :title="detail ? '批次详情 · ' + shortId(detail.batch_id) : '批次详情'" size="48%" direction="rtl">
      <div v-if="detail" class="drawer-body" v-loading="detailLoading">
        <el-descriptions :column="2" border size="small" class="drawer-desc">
          <el-descriptions-item label="连接器"><code>{{ connectorId }}</code></el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="statusTagType(detail.status)" size="mini" effect="dark">{{ statusLabel(detail.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="批次 ID"><code>{{ detail.batch_id }}</code></el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ detail.started_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ detail.finished_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ formatDuration(detail.duration_ms) }}</el-descriptions-item>
          <el-descriptions-item label="上游 code">{{ detail.upstream_code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="日期区间" :span="2">{{ getParamMapField(detail, 'startDate', '-') }} ~ {{ getParamMapField(detail, 'endDate', '-') }}</el-descriptions-item>
          <el-descriptions-item label="上游 URL" :span="2"><code style="word-break:break-all;">{{ detail.upstream_url || '-' }}</code></el-descriptions-item>
        </el-descriptions>
        <el-row :gutter="12" class="stat-row">
          <el-col :span="4"><div class="metric"><div class="metric-num">{{ detail.total_returned || 0 }}</div><div class="metric-label">上游返回</div></div></el-col>
          <el-col :span="4"><div class="metric success"><div class="metric-num">{{ detail.inserted || 0 }}</div><div class="metric-label">新增</div></div></el-col>
          <el-col :span="4"><div class="metric primary"><div class="metric-num">{{ detail.updated || 0 }}</div><div class="metric-label">更新</div></div></el-col>
          <el-col :span="4"><div class="metric warn"><div class="metric-num">{{ detail.skipped_no_key || 0 }}</div><div class="metric-label">跳过</div></div></el-col>
          <el-col :span="4"><div class="metric danger"><div class="metric-num">{{ detail.failed || 0 }}</div><div class="metric-label">失败</div></div></el-col>
          <el-col :span="4"><div class="metric info"><div class="metric-num">{{ (detail.msg_list || []).length }}</div><div class="metric-label">告警</div></div></el-col>
        </el-row>
        <el-divider content-position="left">上游 message</el-divider>
        <el-alert :title="detail.upstream_message || '无'" :type="detail.upstream_message ? 'info' : 'success'" :closable="false" />
        <el-divider v-if="detail.msg_list && detail.msg_list.length" content-position="left">msg_list</el-divider>
        <div v-if="detail.msg_list && detail.msg_list.length" class="msg-list">
          <el-tag v-for="(m, i) in detail.msg_list" :key="i" :type="msgType(m.message_type)" effect="plain" class="msg-tag">
            <span class="msg-code">[{{ m.message_code || '?' }}]</span>{{ m.message_content || '-' }}
          </el-tag>
        </div>
        <el-divider v-if="detail.sample_errors && detail.sample_errors.length" content-position="left">样例失败</el-divider>
        <ul v-if="detail.sample_errors && detail.sample_errors.length" class="sample-errors"><li v-for="(s, i) in detail.sample_errors" :key="i">{{ s }}</li></ul>
        <el-divider content-position="left">ind_name_list</el-divider>
        <el-collapse v-if="detail.ind_name_list && detail.ind_name_list.length">
          <el-collapse-item title="展开" name="ind">
            <el-table :data="detail.ind_name_list" size="mini" stripe border max-height="320">
              <el-table-column prop="ind_name" label="字段" width="220" />
              <el-table-column prop="sourceTableLabel" label="源表列" />
            </el-table>
          </el-collapse-item>
        </el-collapse>
        <div v-else class="muted">无</div>
        <el-divider content-position="left">请求参数</el-divider>
        <pre class="json-block">{{ detailParamsJson }}</pre>
        <el-alert v-if="detail.error" :title="detail.error" type="error" :closable="false" />
        <div class="drawer-footer">
          <el-button type="primary" size="small" icon="el-icon-search" @click="viewRecords(detail)">查看该批次记录</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import { listDataHubBatches, getDataHubBatch } from '@/api/dataHub';

const STATUS_MAP = {
  success: { label: '成功', type: 'success', timeline: 'success' },
  partial: { label: '部分完成', type: 'warning', timeline: 'warning' },
  failed_network: { label: '网络失败', type: 'danger', timeline: 'danger' },
  failed_upstream: { label: '上游异常', type: 'danger', timeline: 'danger' },
  failed_unknown: { label: '未知失败', type: 'danger', timeline: 'danger' },
  running: { label: '进行中', type: 'info', timeline: 'primary' }
};

export default {
  name: 'DataHubBatchesPanel',
  props: {
    connectorId: { type: String, required: true },
    connector: { type: Object, default: () => ({}) }
  },
  data() {
    return {
      viewMode: 'timeline',
      batches: [],
      total: 0,
      page: 1,
      pageSize: 20,
      loading: false,
      detailVisible: false,
      detailLoading: false,
      detail: null
    };
  },
  computed: {
    importParamStyle() {
      return (this.connector && this.connector.import_param_style) || 'date_range';
    },
    detailParamsJson() {
      return this.detail && this.detail.params ? JSON.stringify(this.detail.params, null, 2) : '{}';
    }
  },
  watch: {
    connectorId() {
      this.page = 1;
      this.reload();
    }
  },
  mounted() {
    this.reload();
  },
  methods: {
    shorten(s, n) {
      if (!s) return '';
      var t = String(s);
      return t.length <= n ? t : t.slice(0, n) + '…';
    },
    getParamMapField(source, key, def) {
      if (!source || !source.params || !source.params.paramMaps) return def;
      const v = source.params.paramMaps[key];
      return v != null && v !== '' ? v : def;
    },
    statusTagType(status) {
      return (STATUS_MAP[status] || { type: 'info' }).type;
    },
    statusLabel(status) {
      return (STATUS_MAP[status] || { label: status || '-' }).label;
    },
    timelineType(status) {
      return (STATUS_MAP[status] || { timeline: 'info' }).timeline;
    },
    shortId(id) {
      if (!id) return '-';
      return String(id).slice(0, 8);
    },
    formatDuration(ms) {
      if (!ms && ms !== 0) return '-';
      if (ms < 1000) return ms + 'ms';
      if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
      return (ms / 60000).toFixed(1) + 'min';
    },
    msgType(t) {
      if (!t) return 'info';
      var lower = String(t).toLowerCase();
      if (lower.indexOf('error') >= 0) return 'danger';
      if (lower.indexOf('warn') >= 0) return 'warning';
      if (lower.indexOf('success') >= 0) return 'success';
      return 'info';
    },
    async reload() {
      if (!this.connectorId) return;
      this.loading = true;
      try {
        const res = await listDataHubBatches(this.connectorId, { page: this.page, pageSize: this.pageSize });
        const data = res && res.data !== undefined ? res.data : res;
        this.batches = (data && data.items) ? data.items : [];
        this.total = (data && data.total) ? data.total : 0;
      } catch (e) {
        this.batches = [];
        this.total = 0;
      } finally {
        this.loading = false;
      }
    },
    async openDetail(row) {
      if (!row || !row.batch_id) return;
      this.detail = row;
      this.detailVisible = true;
      this.detailLoading = true;
      try {
        const res = await getDataHubBatch(this.connectorId, row.batch_id);
        var d = res && res.data !== undefined ? res.data : res;
        this.detail = d || row;
      } catch (e) {
        /* keep row */
      } finally {
        this.detailLoading = false;
      }
    },
    viewRecords(row) {
      var bid = row && row.batch_id;
      if (!bid) return;
      this.detailVisible = false;
      this.$emit('view-records', bid);
    }
  }
};
</script>

<style scoped>
.batches-panel { padding: 4px; }
.toolbar-card, .view-card { border: 1px solid #ebeef5; margin-bottom: 16px; }
.toolbar { display: flex; align-items: center; gap: 12px; }
.empty { padding: 40px 0; text-align: center; }
.muted { color: #909399; }
.timeline-card { cursor: pointer; transition: transform 0.18s; border: 1px solid #ebeef5; }
.timeline-card:hover { transform: translateY(-2px); border-color: #409EFF; }
.tl-header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.tl-page-msg {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.4;
}
.tbl-hint {
  margin-top: 4px;
  font-size: 12px;
}
.tl-params { font-size: 13px; color: #303133; font-weight: 500; }
.batch-id { font-family: Menlo, Monaco, Consolas, monospace; font-size: 12px; }
.tl-stats { display: flex; gap: 22px; flex-wrap: wrap; }
.tl-stat { display: flex; align-items: baseline; gap: 6px; font-size: 12px; }
.tl-stat .lbl { color: #909399; }
.tl-stat .val { font-weight: 600; font-size: 14px; color: #303133; }
.tl-stat .val.success { color: #67C23A; }
.tl-stat .val.primary { color: #409EFF; }
.tl-stat .val.warn { color: #E6A23C; }
.tl-stat .val.danger { color: #F56C6C; }
.tl-stat .val.info { color: #909399; }
.tl-error { margin-top: 8px; padding: 6px 10px; background: #fef0f0; color: #F56C6C; font-size: 12px; border-radius: 4px; }
.pagination-wrap { margin-top: 14px; text-align: right; }
.num.success { color: #67C23A; font-weight: 600; }
.num.primary { color: #409EFF; font-weight: 600; }
.num.warn { color: #E6A23C; font-weight: 600; }
.num.danger { color: #F56C6C; font-weight: 600; }
.drawer-body { padding: 16px 20px 40px 20px; max-height: calc(100vh - 80px); overflow: auto; }
.drawer-desc { margin-bottom: 14px; }
.stat-row .metric {
  background: #f7f9fc;
  border-radius: 6px;
  padding: 12px 0;
  text-align: center;
  border: 1px solid #ebeef5;
}
.stat-row .metric-num { font-size: 18px; font-weight: 600; color: #303133; }
.stat-row .metric-label { font-size: 12px; color: #909399; margin-top: 2px; }
.stat-row .metric.success .metric-num { color: #67C23A; }
.stat-row .metric.primary .metric-num { color: #409EFF; }
.stat-row .metric.warn .metric-num { color: #E6A23C; }
.stat-row .metric.danger .metric-num { color: #F56C6C; }
.stat-row .metric.info .metric-num { color: #909399; }
.msg-list { display: flex; flex-wrap: wrap; gap: 8px; }
.msg-tag {
  max-width: 100%;
  white-space: normal;
  height: auto;
  line-height: 1.6;
  padding: 6px 10px;
}
.msg-code { font-weight: 600; margin-right: 6px; }
.sample-errors { margin: 0; padding-left: 20px; color: #606266; font-size: 12px; line-height: 1.8; }
.json-block {
  background: #f7f9fc;
  padding: 10px 14px;
  font-size: 12px;
  font-family: Menlo, Monaco, Consolas, monospace;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 220px;
  overflow: auto;
}
.drawer-footer { margin-top: 20px; text-align: right; }
</style>
