<template>
  <div class="data-asset-container">
    <!-- 顶部统计卡片 -->
    <el-row :gutter="16" class="summary-cards">
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num">{{ summary.total || 0 }}</div>
          <div class="stat-label">总资产数</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num active">{{ summary.active || 0 }}</div>
          <div class="stat-label">活跃</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num api">{{ summary.api_upstream || 0 }}</div>
          <div class="stat-label">API类型</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num local">{{ summary.local_import || 0 }}</div>
          <div class="stat-label">本地导入</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num danger">{{ summary.sync_failed || 0 }}</div>
          <div class="stat-label">同步失败</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num muted">{{ summary.last_sync_at ? formatTime(summary.last_sync_at) : '-' }}</div>
          <div class="stat-label">最近同步</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选栏 -->
    <el-card class="filter-card" shadow="never">
      <el-form :inline="true" size="small">
        <el-form-item label="类型">
          <el-select v-model="filters.asset_type" clearable placeholder="全部" style="width:130px">
            <el-option label="API上游" value="api_upstream"/>
            <el-option label="本地导入" value="local_import"/>
            <el-option label="计算衍生" value="computed"/>
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width:110px">
            <el-option label="活跃" value="active"/>
            <el-option label="已废弃" value="deprecated"/>

          </el-select>
        </el-form-item>
        <el-form-item label="搜索">
          <el-input v-model="filters.keyword" placeholder="名称/描述" clearable style="width:180px" @keyup.enter.native="fetchList"/>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="el-icon-search" @click="fetchList">查询</el-button>
          <el-button icon="el-icon-refresh-left" @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 操作栏 -->
    <div class="action-bar">
      <el-button type="primary" size="small" icon="el-icon-plus" @click="showCreateDialog">新增资产</el-button>
      <el-button size="small" icon="el-icon-refresh" @click="handleSeed" :loading="seedLoading">从连接器同步</el-button>
    </div>

    <!-- 数据表格 -->
    <el-table :data="tableData" v-loading="loading" border stripe style="width:100%">
      <el-table-column prop="name" label="资产名称" min-width="150" show-overflow-tooltip/>
      <el-table-column prop="asset_type" label="类型" width="100" align="center">
        <template slot-scope="{row}">
          <el-tag :type="typeTagColor(row.asset_type)" size="small">{{ typeLabel(row.asset_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target_collection" label="目标集合" width="180" show-overflow-tooltip/>
      <el-table-column prop="status" label="状态" width="80" align="center">
        <template slot-scope="{row}">
          <el-tag :type="statusTagColor(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="total_records" label="记录数" width="100" align="right"/>
      <el-table-column prop="last_sync_at" label="最近同步" width="160" align="center">
        <template slot-scope="{row}">
          {{ row.last_sync_at ? formatTime(row.last_sync_at) : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="last_sync_status" label="同步状态" width="100" align="center">
        <template slot-scope="{row}">
          <el-tag :type="syncStatusColor(row.last_sync_status)" size="mini">{{ row.last_sync_status || 'never' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right" align="center">
        <template slot-scope="{row}">
          <el-button size="mini" @click="showDetail(row)">详情</el-button>
          <el-button size="mini" type="warning" @click="handleSync(row)">同步</el-button>
          <el-button size="mini" @click="handleRefresh(row)">刷新</el-button>
          <el-button size="mini" type="info" @click="showEditDialog(row)">编辑</el-button>

        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <el-pagination
      class="pagination-wrap"
      @current-change="handlePageChange"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
    />

    <!-- 新建/编辑对话框 -->
    <el-dialog :title="dialogTitle" :visible.sync="dialogVisible" width="620px" :close-on-click-modal="false">
      <el-form :model="formData" label-width="100px" size="small">
        <el-form-item label="资产名称" required>
          <el-input v-model="formData.name" placeholder="请输入资产名称"/>
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="formData.asset_type" placeholder="请选择类型" style="width:100%">
            <el-option label="API上游" value="api_upstream"/>
            <el-option label="本地导入" value="local_import"/>
            <el-option label="计算衍生" value="computed"/>
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input type="textarea" v-model="formData.description" :rows="3" placeholder="资产描述信息"/>
        </el-form-item>
        <el-form-item label="上游URL" v-if="formData.asset_type === 'api_upstream'">
          <el-input v-model="formData.source_url" placeholder="数据源URL"/>
        </el-form-item>
        <el-form-item label="上游资源" v-if="formData.asset_type === 'api_upstream'">
          <el-input v-model="formData.source_resource" placeholder="资源标识"/>
        </el-form-item>
        <el-form-item label="目标集合" required>
          <el-input v-model="formData.target_collection" placeholder="MongoDB集合名"/>
        </el-form-item>
        <el-form-item label="同步策略">
          <el-select v-model="formData.sync_strategy" placeholder="请选择" style="width:100%">
            <el-option label="手动" value="manual"/>
            <el-option label="定时" value="scheduled"/>
            <el-option label="实时" value="realtime"/>
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="formData.tags_input" placeholder="逗号分隔多个标签"/>
        </el-form-item>
        <el-form-item label="负责人">
          <el-input v-model="formData.owner" placeholder="负责人姓名"/>
        </el-form-item>
      </el-form>
      <span slot="footer" class="dialog-footer">
        <el-button size="small" @click="dialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="submitLoading" @click="submitForm">确定</el-button>
      </span>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog title="资产详情" :visible.sync="detailVisible" width="700px">
      <el-descriptions v-if="detailData" :column="2" border size="small">
        <el-descriptions-item label="资产名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ typeLabel(detailData.asset_type) }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusLabel(detailData.status) }}</el-descriptions-item>
        <el-descriptions-item label="目标集合">{{ detailData.target_collection }}</el-descriptions-item>
        <el-descriptions-item label="同步策略">{{ detailData.sync_strategy || '-' }}</el-descriptions-item>
        <el-descriptions-item label="记录数">{{ detailData.total_records || 0 }}</el-descriptions-item>
        <el-descriptions-item label="上游URL" :span="2">{{ detailData.source_url || '-' }}</el-descriptions-item>
        <el-descriptions-item label="上游资源">{{ detailData.source_resource || '-' }}</el-descriptions-item>
        <el-descriptions-item label="负责人">{{ detailData.owner || '-' }}</el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">{{ detailData.description || '-' }}</el-descriptions-item>
        <el-descriptions-item label="标签" :span="2">
          <el-tag v-for="tag in (detailData.tags || [])" :key="tag" size="mini" style="margin-right:4px">{{ tag }}</el-tag>
          <span v-if="!detailData.tags || !detailData.tags.length">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="最近同步时间">{{ detailData.last_sync_at ? formatTime(detailData.last_sync_at) : '-' }}</el-descriptions-item>
        <el-descriptions-item label="最近同步状态">{{ detailData.last_sync_status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ detailData.created_at ? formatTime(detailData.created_at) : '-' }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ detailData.updated_at ? formatTime(detailData.updated_at) : '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script>
import {
  listDataAssets,
  getDataAssetSummary,
  getDataAsset,
  createDataAsset,
  updateDataAsset,
  syncDataAsset,
  refreshDataAssetStats,
  seedDataAssets
} from '@/api/dataAsset';

const TYPE_LABELS = { api_upstream: 'API上游', local_import: '本地导入', computed: '计算衍生' };
const STATUS_LABELS = { active: '活跃', deprecated: '已废弃' };

export default {
  name: 'DataAssetManage',
  data() {
    return {
      // 表格
      tableData: [],
      loading: false,
      page: 1,
      pageSize: 20,
      total: 0,
      // 汇总
      summary: {},
      // 筛选
      filters: {
        asset_type: '',
        status: '',
        keyword: ''
      },
      // 对话框
      dialogVisible: false,
      dialogTitle: '新增数据资产',
      isEdit: false,
      editId: null,
      submitLoading: false,
      formData: {
        name: '',
        asset_type: 'api_upstream',
        description: '',
        source_url: '',
        source_resource: '',
        target_collection: '',
        sync_strategy: 'manual',
        tags_input: '',
        owner: ''
      },
      // 详情
      detailVisible: false,
      detailData: null,
      // seed
      seedLoading: false
    };
  },
  mounted() {
    this.fetchList();
    this.fetchSummary();
  },
  methods: {
    // ---- 数据获取 ----
    async fetchList() {
      this.loading = true;
      try {
        var params = { page: this.page, page_size: this.pageSize };
        if (this.filters.asset_type) params.asset_type = this.filters.asset_type;
        if (this.filters.status) params.status = this.filters.status;
        if (this.filters.keyword) params.keyword = this.filters.keyword;
        var res = await listDataAssets(params);
        var data = res && res.data !== undefined ? res.data : res;
        this.tableData = data.items || data.results || [];
        this.total = data.total || 0;
      } catch (e) {
        this.$message.error('获取数据资产列表失败');
        this.tableData = [];
      } finally {
        this.loading = false;
      }
    },
    async fetchSummary() {
      try {
        var res = await getDataAssetSummary();
        var data = res && res.data !== undefined ? res.data : res;
        this.summary = data || {};
      } catch (e) {
        this.summary = {};
      }
    },

    // ---- 筛选 ----
    resetFilters() {
      this.filters = { asset_type: '', status: '', keyword: '' };
      this.page = 1;
      this.fetchList();
    },
    handlePageChange(val) {
      this.page = val;
      this.fetchList();
    },

    // ---- 同步 & 刷新 ----
    async handleSync(row) {
      try {
        await syncDataAsset(row.asset_id);
        this.$message.success('同步任务已触发');
        this.fetchList();
        this.fetchSummary();
      } catch (e) {
        this.$message.error('同步失败：' + (e.message || '未知错误'));
      }
    },
    async handleRefresh(row) {
      try {
        await refreshDataAssetStats(row.asset_id);
        this.$message.success('统计已刷新');
        this.fetchList();
      } catch (e) {
        this.$message.error('刷新失败');
      }
    },
    async handleSeed() {
      this.seedLoading = true;
      try {
        await seedDataAssets();
        this.$message.success('从连接器同步完成');
        this.fetchList();
        this.fetchSummary();
      } catch (e) {
        this.$message.error('连接器同步失败');
      } finally {
        this.seedLoading = false;
      }
    },


    // ---- 详情 ----
    async showDetail(row) {
      try {
        var res = await getDataAsset(row.asset_id);
        var data = res && res.data !== undefined ? res.data : res;
        this.detailData = data;
        this.detailVisible = true;
      } catch (e) {
        this.$message.error('获取详情失败');
      }
    },

    // ---- 新建/编辑 ----
    showCreateDialog() {
      this.dialogTitle = '新增数据资产';
      this.isEdit = false;
      this.editId = null;
      this.formData = {
        name: '',
        asset_type: 'api_upstream',
        description: '',
        source_url: '',
        source_resource: '',
        target_collection: '',
        sync_strategy: 'manual',
        tags_input: '',
        owner: ''
      };
      this.dialogVisible = true;
    },
    showEditDialog(row) {
      this.dialogTitle = '编辑数据资产';
      this.isEdit = true;
      this.editId = row.asset_id;
      this.formData = {
        name: row.name || '',
        asset_type: row.asset_type || 'api_upstream',
        description: row.description || '',
        source_url: row.source_url || '',
        source_resource: row.source_resource || '',
        target_collection: row.target_collection || '',
        sync_strategy: row.sync_strategy || 'manual',
        tags_input: (row.tags || []).join(','),
        owner: row.owner || ''
      };
      this.dialogVisible = true;
    },
    async submitForm() {
      if (!this.formData.name) {
        this.$message.warning('请输入资产名称');
        return;
      }
      if (!this.formData.target_collection) {
        this.$message.warning('请输入目标集合');
        return;
      }
      this.submitLoading = true;
      try {
        var payload = Object.assign({}, this.formData);
        // 处理标签
        payload.tags = payload.tags_input ? payload.tags_input.split(',').map(function (t) { return t.trim(); }).filter(Boolean) : [];
        delete payload.tags_input;

        if (this.isEdit) {
          await updateDataAsset(this.editId, payload);
          this.$message.success('更新成功');
        } else {
          await createDataAsset(payload);
          this.$message.success('创建成功');
        }
        this.dialogVisible = false;
        this.fetchList();
        this.fetchSummary();
      } catch (e) {
        this.$message.error((this.isEdit ? '更新' : '创建') + '失败：' + (e.message || '未知错误'));
      } finally {
        this.submitLoading = false;
      }
    },

    // ---- 工具方法 ----
    typeLabel(val) {
      return TYPE_LABELS[val] || val || '-';
    },
    typeTagColor(val) {
      var map = { api_upstream: '', local_import: 'success', computed: 'warning' };
      return map[val] || 'info';
    },
    statusLabel(val) {
      return STATUS_LABELS[val] || val || '-';
    },
    statusTagColor(val) {
      var map = { active: 'success', deprecated: 'warning' };
      return map[val] || 'info';
    },
    syncStatusColor(val) {
      var map = { success: 'success', failed: 'danger', running: 'warning', never: 'info' };
      return map[val] || 'info';
    },
    formatTime(val) {
      if (!val) return '-';
      var d = new Date(val);
      if (isNaN(d.getTime())) return val;
      var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
  }
};
</script>

<style scoped>
.data-asset-container {
  padding: 16px;
}
.summary-cards {
  margin-bottom: 16px;
}
.stat-card {
  text-align: center;
  padding: 12px 0;
}
.stat-card .stat-num {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}
.stat-card .stat-num.active { color: #67c23a; }
.stat-card .stat-num.api { color: #409eff; }
.stat-card .stat-num.local { color: #e6a23c; }
.stat-card .stat-num.danger { color: #f56c6c; }
.stat-card .stat-num.muted { font-size: 13px; color: #909399; }
.stat-card .stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.filter-card {
  margin-bottom: 12px;
}
.action-bar {
  margin-bottom: 12px;
}
.pagination-wrap {
  margin-top: 16px;
  text-align: right;
}
</style>
