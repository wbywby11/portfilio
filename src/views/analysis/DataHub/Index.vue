<template>
  <div class="data-hub-center">
    <div class="dh-hero">
      <div class="dh-hero-left">
        <div class="dh-hero-title">
          <i class="el-icon-connection"></i>
          <span>通用数据接入中心</span>
        </div>
        <div class="dh-hero-sub">
          选择连接器，完成上游导入、分页查询与批次回溯；配置由后端注册表驱动，可扩展。
        </div>
      </div>
      <div class="dh-hero-mid">
        <span class="muted">当前数据源</span>
        <el-select
          v-model="selectedId"
          placeholder="选择连接器"
          size="small"
          filterable
          style="min-width: 220px; margin-left: 8px;"
          @change="onConnectorChange"
        >
          <el-option
            v-for="c in connectors"
            :key="c.connector_id"
            :label="c.title"
            :value="c.connector_id"
          />
        </el-select>
      </div>
      <div class="dh-hero-stats">
        <div class="stat-block">
          <div class="stat-num">{{ overview.total_records || 0 }}</div>
          <div class="stat-label">记录数</div>
        </div>
        <div class="stat-block">
          <div class="stat-num">{{ overview.total_batches || 0 }}</div>
          <div class="stat-label">导入批次</div>
        </div>
        <div class="stat-block latest">
          <div class="stat-num">
            <el-tag v-if="overview.latest_batch" :type="statusTagType(overview.latest_batch.status)" size="small">
              {{ overview.latest_batch.status }}
            </el-tag>
            <span v-else class="muted">无</span>
          </div>
          <div class="stat-label">
            最近批次
            <span v-if="overview.latest_batch" class="muted">· {{ overview.latest_batch.started_at }}</span>
          </div>
        </div>
        <el-button size="mini" icon="el-icon-refresh" type="text" @click="fetchOverview" :loading="overviewLoading">刷新</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="dh-tabs" type="border-card">
      <el-tab-pane label="数据导入" name="import" lazy>
        <keep-alive>
          <dynamic-import-panel
            v-if="activeTab === 'import' && currentConnector"
            :connector-id="selectedId"
            :connector="currentConnector"
            @imported="onImported"
          />
        </keep-alive>
      </el-tab-pane>
      <el-tab-pane label="记录查询" name="query" lazy>
        <keep-alive>
          <hub-query-panel
            v-if="activeTab === 'query' && currentConnector"
            ref="queryPanel"
            :connector-id="selectedId"
            :connector="currentConnector"
            :overview="overview"
            :badge-field="currentConnector.badge_field || ''"
            @overview-update="onOverviewPatch"
          />
        </keep-alive>
      </el-tab-pane>
      <el-tab-pane label="批次历史" name="batches" lazy>
        <keep-alive>
          <hub-batches-panel
            v-if="activeTab === 'batches'"
            ref="batchesPanel"
            :connector-id="selectedId"
            :connector="currentConnector"
            @view-records="jumpToQueryByBatch"
          />
        </keep-alive>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script>
import { listConnectors, getDataHubStats } from '@/api/dataHub';
import DynamicImportPanel from './DynamicImportPanel.vue';
import HubQueryPanel from './HubQueryPanel.vue';
import HubBatchesPanel from './HubBatchesPanel.vue';

const STATUS_MAP = {
  success: { type: 'success' },
  partial: { type: 'warning' },
  failed_network: { type: 'danger' },
  failed_upstream: { type: 'danger' },
  failed_unknown: { type: 'danger' },
  running: { type: 'info' }
};

export default {
  name: 'DataHubCenter',
  components: { DynamicImportPanel, HubQueryPanel, HubBatchesPanel },
  data() {
    return {
      connectors: [],
      selectedId: '',
      activeTab: 'import',
      overview: {},
      overviewLoading: false
    };
  },
  computed: {
    currentConnector() {
      return this.connectors.find(function (c) {
        return c.connector_id === this.selectedId;
      }.bind(this)) || null;
    }
  },
  watch: {
    '$route.query.connector': {
      handler(cid) {
        if (cid && this.connectors.some(function (x) { return x.connector_id === cid; })) {
          this.selectedId = cid;
          this.fetchOverview();
        }
      }
    }
  },
  async mounted() {
    await this.loadConnectors();
    const q = this.$route.query.connector;
    if (q && this.connectors.some(function (x) { return x.connector_id === q; })) {
      this.selectedId = q;
    }
    this.fetchOverview();
  },
  methods: {
    statusTagType(s) {
      return (STATUS_MAP[s] || { type: 'info' }).type;
    },
    async loadConnectors() {
      try {
        const res = await listConnectors();
        const z = res && res.data !== undefined ? res.data : res;
        const items = (z && z.items) ? z.items : [];
        this.connectors = items;
        if (!this.selectedId && items.length) {
          this.selectedId = items[0].connector_id;
        }
      } catch (e) {
        this.connectors = [];
        this.$message.error('加载连接器失败');
      }
    },
    onConnectorChange() {
      var q = Object.assign({}, this.$route.query || {}, { connector: this.selectedId });
      this.$router.replace({ path: this.$route.path, query: q });
      this.fetchOverview();
    },
    async fetchOverview() {
      if (!this.selectedId) return;
      this.overviewLoading = true;
      try {
        const res = await getDataHubStats(this.selectedId);
        const z = res && res.data !== undefined ? res.data : res;
        this.overview = z || {};
      } catch (e) {
        this.overview = {};
      } finally {
        this.overviewLoading = false;
      }
    },
    onOverviewPatch(data) {
      this.overview = data || {};
    },
    onImported() {
      this.fetchOverview();
    },
    jumpToQueryByBatch(batchId) {
      this.activeTab = 'query';
      this.$nextTick(function () {
        var qp = this.$refs.queryPanel;
        if (qp && qp.exposeBatchFilter) qp.exposeBatchFilter(batchId);
      }.bind(this));
    }
  }
};
</script>

<style scoped>
.data-hub-center { padding-bottom: 24px; }
.dh-hero {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 20px;
  padding: 20px 22px;
  margin-bottom: 14px;
  border-radius: 10px;
  background: linear-gradient(135deg, #e8eef8 0%, #fdfbff 48%, #e6f7ff 100%);
  border: 1px solid #ebeef5;
}
.dh-hero-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
}
.dh-hero-sub {
  font-size: 13px;
  color: #606266;
  line-height: 1.55;
}
.dh-hero-mid {
  display: flex;
  align-items: center;
}
.dh-hero-stats {
  display: flex;
  gap: 16px;
  align-items: center;
  margin-left: auto;
  flex-wrap: wrap;
}
.stat-block {
  min-width: 88px;
  text-align: center;
  padding: 8px 12px;
  background: rgba(255,255,255,0.75);
  border-radius: 8px;
}
.stat-num { font-size: 18px; font-weight: 600; color: #303133; }
.stat-label { font-size: 12px; color: #909399; margin-top: 2px; }
.muted { color: #909399; font-size: 12px; }
.dh-tabs { margin: 0 2px; }
</style>
