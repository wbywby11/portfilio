<template>
  <div class="subject-risk-center">
    <!-- 顶部概览 -->
    <div class="sr-hero">
      <div class="sr-hero-left">
        <div class="sr-hero-title">
          <i class="el-icon-warning-outline"></i>
          <span>主体观点风险</span>
        </div>
        <div class="sr-hero-sub">
          统一接入 <code>adm_subject_opinion_risk_stats</code> 上游数据，支持导入、查询与批次回溯。
        </div>
      </div>
      <div class="sr-hero-stats">
        <div class="stat-block">
          <div class="stat-num">{{ overview.total_records || 0 }}</div>
          <div class="stat-label">主体记录数</div>
        </div>
        <div class="stat-block">
          <div class="stat-num">{{ overview.total_batches || 0 }}</div>
          <div class="stat-label">历史批次</div>
        </div>
        <div class="stat-block latest">
          <div class="stat-num">
            <el-tag
              v-if="overview.latest_batch"
              :type="statusTagType(overview.latest_batch.status)"
              size="small"
            >
              {{ statusLabel(overview.latest_batch.status) }}
            </el-tag>
            <span v-else class="muted">无</span>
          </div>
          <div class="stat-label">
            最近批次
            <span v-if="overview.latest_batch" class="muted">
              · {{ overview.latest_batch.started_at }}
            </span>
          </div>
        </div>
        <el-button
          size="mini"
          icon="el-icon-refresh"
          type="text"
          @click="fetchOverview"
          :loading="overviewLoading"
        >刷新</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="sr-tabs" type="border-card">
      <el-tab-pane label="数据导入" name="import" lazy>
        <keep-alive>
          <import-panel
            v-if="activeTab === 'import'"
            @imported="onImported"
          />
        </keep-alive>
      </el-tab-pane>
      <el-tab-pane label="记录查询" name="query" lazy>
        <keep-alive>
          <query-panel
            v-if="activeTab === 'query'"
            ref="queryPanel"
            :overview="overview"
          />
        </keep-alive>
      </el-tab-pane>
      <el-tab-pane label="批次历史" name="batches" lazy>
        <keep-alive>
          <batches-panel
            v-if="activeTab === 'batches'"
            ref="batchesPanel"
            @view-records="jumpToQueryByBatch"
          />
        </keep-alive>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script>
import { getSubjectRiskStats } from '@/api/subjectRisk';
import ImportPanel from './ImportPanel.vue';
import QueryPanel from './QueryPanel.vue';
import BatchesPanel from './BatchesPanel.vue';

const STATUS_MAP = {
  success: { label: '成功', type: 'success' },
  partial: { label: '部分完成', type: 'warning' },
  failed_network: { label: '网络失败', type: 'danger' },
  failed_upstream: { label: '上游异常', type: 'danger' },
  failed_unknown: { label: '未知失败', type: 'danger' },
  running: { label: '进行中', type: 'info' }
};

export default {
  name: 'SubjectRiskCenter',
  components: { ImportPanel, QueryPanel, BatchesPanel },
  data() {
    return {
      activeTab: 'import',
      overview: {
        total_records: 0,
        total_batches: 0,
        latest_batch: null
      },
      overviewLoading: false
    };
  },
  mounted() {
    this.fetchOverview();
  },
  methods: {
    statusTagType(status) {
      return (STATUS_MAP[status] || { type: 'info' }).type;
    },
    statusLabel(status) {
      return (STATUS_MAP[status] || { label: status || '-' }).label;
    },
    async fetchOverview() {
      this.overviewLoading = true;
      try {
        const res = await getSubjectRiskStats();
        const data = res.data || res || {};
        this.overview = {
          total_records: data.total_records || 0,
          total_batches: data.total_batches || 0,
          latest_batch: data.latest_batch || null,
          risk_signal_level: data.risk_signal_level || [],
          affiliated_province_top10: data.affiliated_province_top10 || [],
          enterprise_nature_top10: data.enterprise_nature_top10 || []
        };
      } catch (e) {
        // 静默：已有全局 Message
      } finally {
        this.overviewLoading = false;
      }
    },
    onImported() {
      this.fetchOverview();
      if (this.$refs.queryPanel && this.$refs.queryPanel.reload) {
        this.$refs.queryPanel.reload();
      }
      if (this.$refs.batchesPanel && this.$refs.batchesPanel.reload) {
        this.$refs.batchesPanel.reload();
      }
    },
    jumpToQueryByBatch(batchId) {
      this.activeTab = 'query';
      this.$nextTick(() => {
        if (this.$refs.queryPanel && this.$refs.queryPanel.applyBatchFilter) {
          this.$refs.queryPanel.applyBatchFilter(batchId);
        }
      });
    }
  }
};
</script>

<style scoped>
.subject-risk-center {
  padding: 20px;
}
.sr-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, #3a7bd5 0%, #00d2ff 100%);
  color: #fff;
  border-radius: 8px;
  padding: 18px 24px;
  margin-bottom: 16px;
  box-shadow: 0 4px 16px rgba(58, 123, 213, 0.18);
}
.sr-hero-left {
  flex: 1;
}
.sr-hero-title {
  font-size: 20px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 10px;
}
.sr-hero-title i {
  font-size: 22px;
}
.sr-hero-sub {
  margin-top: 6px;
  font-size: 13px;
  opacity: 0.85;
}
.sr-hero-sub code {
  background: rgba(255, 255, 255, 0.18);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: Menlo, Monaco, Consolas, monospace;
}
.sr-hero-stats {
  display: flex;
  align-items: center;
  gap: 22px;
}
.stat-block {
  min-width: 120px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  text-align: center;
}
.stat-block.latest { min-width: 180px; }
.stat-num {
  font-size: 20px;
  font-weight: 600;
  line-height: 1.4;
}
.stat-label {
  font-size: 12px;
  opacity: 0.85;
  margin-top: 2px;
}
.muted {
  opacity: 0.7;
}
.sr-tabs >>> .el-tabs__content {
  padding: 18px;
  background: #fff;
}
.sr-tabs >>> .el-tabs__header {
  margin: 0;
}
.sr-hero-stats .el-button--text {
  color: #fff;
  opacity: 0.9;
}
.sr-hero-stats .el-button--text:hover {
  opacity: 1;
  color: #fff;
}
</style>
