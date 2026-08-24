<template>
  <div class="data-asset-container">
    <!-- top summary cards -->
    <el-row :gutter="16" class="summary-cards">
      <el-col :span="4" v-for="card in summaryCards" :key="card.key">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num" :class="card.cls">{{ card.value }}</div>
          <div class="stat-label">{{ card.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- filter bar -->
    <el-card class="filter-card" shadow="never">
      <el-form :inline="true" size="small">
        <el-form-item>
          <el-input v-model="filters.keyword" placeholder="搜索集合名 / 描述 / 标签" clearable style="width:220px" @keyup.enter.native="fetchList"/>
        </el-form-item>
        <el-form-item>
          <el-select v-model="filters.status" clearable placeholder="全部状态" style="width:130px">
            <el-option label="使用中" value="active"/>
            <el-option label="已废弃" value="deprecated"/>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="el-icon-search" @click="fetchList">查询</el-button>
          <el-button icon="el-icon-refresh-left" @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- action bar -->
    <div class="action-bar">
      <el-button type="primary" size="small" icon="el-icon-radar" :loading="scanLoading" @click="handleScan">扫描数据库</el-button>
    </div>

    <!-- data table -->
    <el-table :data="tableData" v-loading="loading" border stripe style="width:100%">
      <el-table-column prop="collection_name" label="集合名" min-width="160" show-overflow-tooltip>
        <template slot-scope="{row}">
          <span class="coll-name">{{ row.collection_name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="record_count" label="记录数" width="100" align="right">
        <template slot-scope="{row}">{{ formatNumber(row.record_count) }}</template>
      </el-table-column>
      <el-table-column prop="storage_size_bytes" label="存储大小" width="100" align="right">
        <template slot-scope="{row}">{{ formatBytes(row.storage_size_bytes) }}</template>
      </el-table-column>
      <el-table-column prop="field_count" label="字段数" width="80" align="center"/>
      <el-table-column label="日期范围" min-width="200" show-overflow-tooltip>
        <template slot-scope="{row}">
          <span v-if="row.date_field">
            <el-tag size="mini" type="info" style="margin-right:4px">{{ row.date_field }}</el-tag>
            {{ row.date_range ? row.date_range.min + ' ~ ' + row.date_range.max : '-' }}
          </span>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100" align="center">
        <template slot-scope="{row}">
          <el-tag :type="row.status === 'active' ? 'success' : 'warning'" size="small">
            {{ row.status === 'active' ? '使用中' : '已废弃' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip>
        <template slot-scope="{row}">{{ row.description || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right" align="center">
        <template slot-scope="{row}">
          <el-button size="mini" type="text" @click="showDetail(row)">详情</el-button>
          <el-button size="mini" type="text" @click="showPreview(row)">预览</el-button>
          <el-dropdown trigger="click" @command="cmd => handleRowCommand(cmd, row)">
            <el-button size="mini" type="text">更多<i class="el-icon-arrow-down el-icon--right"></i></el-button>
            <el-dropdown-menu slot="dropdown">
              <el-dropdown-item command="refresh" :icon="'el-icon-refresh'">刷新统计</el-dropdown-item>
              <el-dropdown-item command="edit" :icon="'el-icon-edit'">编辑元数据</el-dropdown-item>
            </el-dropdown-menu>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- pagination -->
    <el-pagination
      class="pagination-wrap"
      @current-change="handlePageChange"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
    />

    <!-- edit dialog -->
    <el-dialog title="编辑集合元数据" :visible.sync="editVisible" width="500px" :close-on-click-modal="false">
      <el-form :model="editForm" label-width="100px" size="small">
        <el-form-item label="集合名">
          <el-input :value="editForm.collection_name" disabled/>
        </el-form-item>
        <el-form-item label="描述">
          <el-input type="textarea" v-model="editForm.description" :rows="3" placeholder="填写业务描述"/>
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="editForm.tags_input" placeholder="多个标签用逗号分隔"/>
        </el-form-item>
        <el-form-item label="负责人">
          <el-input v-model="editForm.owner" placeholder="填写负责人"/>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" style="width:100%">
            <el-option label="使用中" value="active"/>
            <el-option label="已废弃" value="deprecated"/>
          </el-select>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button size="small" @click="editVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="editLoading" @click="submitEdit">保存</el-button>
      </span>
    </el-dialog>

    <!-- detail dialog -->
    <el-dialog title="集合详情" :visible.sync="detailVisible" width="700px">
      <el-descriptions v-if="detailData" :column="2" border size="small">
        <el-descriptions-item label="集合名">{{ detailData.collection_name }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detailData.status === 'active' ? '使用中' : '已废弃' }}</el-descriptions-item>
        <el-descriptions-item label="记录数">{{ formatNumber(detailData.record_count) }}</el-descriptions-item>
        <el-descriptions-item label="存储大小">{{ formatBytes(detailData.storage_size_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="字段数">{{ detailData.field_count }}</el-descriptions-item>
        <el-descriptions-item label="日期字段">{{ detailData.date_field || '-' }}</el-descriptions-item>
        <el-descriptions-item label="日期范围" :span="2">
          {{ detailData.date_range ? detailData.date_range.min + ' ~ ' + detailData.date_range.max : '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">{{ detailData.description || '-' }}</el-descriptions-item>
        <el-descriptions-item label="标签" :span="2">
          <el-tag v-for="tag in (detailData.tags || [])" :key="tag" size="mini" style="margin-right:4px">{{ tag }}</el-tag>
          <span v-if="!detailData.tags || !detailData.tags.length">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="负责人">{{ detailData.owner || '-' }}</el-descriptions-item>
        <el-descriptions-item label="最近扫描">{{ detailData.last_scanned_at || '-' }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="detailData && detailData.fields && detailData.fields.length" style="margin-top:12px">
        <div class="detail-section-title">字段列表（{{ detailData.fields.length }}）</div>
        <el-tag v-for="f in detailData.fields" :key="f" size="mini" style="margin:2px 4px">{{ f }}</el-tag>
      </div>
    </el-dialog>

    <!-- preview dialog -->
    <el-dialog title="数据预览" :visible.sync="previewVisible" width="800px">
      <div v-loading="previewLoading">
        <div v-if="previewData" style="margin-bottom:8px;color:#909399;font-size:12px">
          集合：{{ previewData.collection_name }} ｜ 共 {{ formatNumber(previewData.total) }} 条 ｜ 展示前 {{ previewData.records.length }} 条
        </div>
        <el-table v-if="previewData && previewData.records.length" :data="previewData.records" border stripe size="mini" max-height="400" style="width:100%">
          <el-table-column v-for="col in previewColumns" :key="col" :prop="col" :label="col" min-width="120" show-overflow-tooltip>
            <template slot-scope="{row}">{{ formatCellValue(row[col]) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无数据"/>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import {
  scanDatabase,
  getDataAssetSummary,
  listDataAssets,
  getDataAsset,
  updateDataAsset,
  refreshDataAsset,
  previewDataAsset
} from '@/api/dataAsset';

export default {
  name: 'DataAssetManage',
  data() {
    return {
      tableData: [],
      loading: false,
      page: 1,
      pageSize: 50,
      total: 0,
      summary: {},
      scanLoading: false,
      filters: { keyword: '', status: '' },
      editVisible: false,
      editLoading: false,
      editForm: { collection_name: '', description: '', tags_input: '', owner: '', status: 'active' },
      detailVisible: false,
      detailData: null,
      previewVisible: false,
      previewLoading: false,
      previewData: null
    };
  },
  computed: {
    summaryCards() {
      var s = this.summary;
      return [
        { key: 'total', label: '集合数', value: s.total || 0, cls: '' },
        { key: 'active', label: '使用中', value: s.active || 0, cls: 'active' },
        { key: 'records', label: '总记录数', value: this.formatNumber(s.total_records), cls: 'api' },
        { key: 'storage', label: '总存储', value: this.formatBytes(s.total_storage_bytes), cls: 'local' },
        { key: 'scanned', label: '最近扫描', value: s.scanned_at ? this.formatTime(s.scanned_at) : '-', cls: 'muted' }
      ];
    },
    previewColumns() {
      if (!this.previewData || !this.previewData.records || !this.previewData.records.length) return [];
      return Object.keys(this.previewData.records[0]);
    }
  },
  mounted() {
    this.fetchList();
    this.fetchSummary();
  },
  methods: {
    async fetchList() {
      this.loading = true;
      try {
        var params = { page: this.page, page_size: this.pageSize };
        if (this.filters.keyword) params.keyword = this.filters.keyword;
        if (this.filters.status) params.status = this.filters.status;
        var res = await listDataAssets(params);
        var data = res && res.data !== undefined ? res.data : res;
        this.tableData = (data.items || []).map(function(item) { return Object.assign({}, item, { _refreshing: false }); });
        this.total = data.total || 0;
      } catch (e) {
        this.$message.error('加载数据资产列表失败');
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
    async handleScan() {
      this.scanLoading = true;
      try {
        await scanDatabase();
        this.$message.success('数据库扫描完成');
        this.fetchList();
        this.fetchSummary();
      } catch (e) {
        this.$message.error('扫描失败：' + (e.message || '未知错误'));
      } finally {
        this.scanLoading = false;
      }
    },
    resetFilters() {
      this.filters = { keyword: '', status: '' };
      this.page = 1;
      this.fetchList();
    },
    handlePageChange(val) {
      this.page = val;
      this.fetchList();
    },
    handleRowCommand(cmd, row) {
      if (cmd === 'refresh') this.handleRefresh(row);
      else if (cmd === 'edit') this.showEditDialog(row);
    },
    async handleRefresh(row) {
      this.$set(row, '_refreshing', true);
      try {
        await refreshDataAsset(row.collection_name);
        this.$message.success(row.collection_name + ' 统计已刷新');
        this.fetchList();
        this.fetchSummary();
      } catch (e) {
        this.$message.error('刷新失败');
      } finally {
        this.$set(row, '_refreshing', false);
      }
    },
    async showDetail(row) {
      try {
        var res = await getDataAsset(row.collection_name);
        var data = res && res.data !== undefined ? res.data : res;
        this.detailData = data;
        this.detailVisible = true;
      } catch (e) {
        this.$message.error('加载详情失败');
      }
    },
    async showPreview(row) {
      this.previewVisible = true;
      this.previewLoading = true;
      this.previewData = null;
      try {
        var res = await previewDataAsset(row.collection_name, 10);
        var data = res && res.data !== undefined ? res.data : res;
        this.previewData = data;
      } catch (e) {
        this.$message.error('预览失败');
      } finally {
        this.previewLoading = false;
      }
    },
    showEditDialog(row) {
      this.editForm = {
        collection_name: row.collection_name,
        description: row.description || '',
        tags_input: (row.tags || []).join(', '),
        owner: row.owner || '',
        status: row.status || 'active'
      };
      this.editVisible = true;
    },
    async submitEdit() {
      this.editLoading = true;
      try {
        var payload = {
          description: this.editForm.description,
          tags: this.editForm.tags_input ? this.editForm.tags_input.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [],
          owner: this.editForm.owner,
          status: this.editForm.status
        };
        await updateDataAsset(this.editForm.collection_name, payload);
        this.$message.success('更新成功');
        this.editVisible = false;
        this.fetchList();
      } catch (e) {
        this.$message.error('更新失败：' + (e.message || '未知错误'));
      } finally {
        this.editLoading = false;
      }
    },
    formatNumber(val) {
      if (val === undefined || val === null) return '0';
      return Number(val).toLocaleString();
    },
    formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      var units = ['B', 'KB', 'MB', 'GB'];
      var i = 0;
      var val = bytes;
      while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
      return val.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
    },
    formatTime(val) {
      if (!val) return '-';
      var d = new Date(val);
      if (isNaN(d.getTime())) return String(val).substring(0, 19).replace('T', ' ');
      var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    },
    formatCellValue(val) {
      if (val === null || val === undefined) return '-';
      if (typeof val === 'object') return JSON.stringify(val);
      return String(val);
    }
  }
};
</script>

<style scoped>
.data-asset-container { padding: 16px; }
.summary-cards { margin-bottom: 16px; }
.stat-card { text-align: center; padding: 12px 0; }
.stat-card .stat-num { font-size: 22px; font-weight: 600; color: #303133; }
.stat-card .stat-num.active { color: #67c23a; }
.stat-card .stat-num.api { color: #409eff; }
.stat-card .stat-num.local { color: #e6a23c; }
.stat-card .stat-num.muted { font-size: 13px; color: #909399; }
.stat-card .stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.filter-card { margin-bottom: 12px; }
.action-bar { margin-bottom: 12px; }
.pagination-wrap { margin-top: 16px; text-align: right; }
.coll-name { font-weight: 500; color: #409eff; }
.text-muted { color: #c0c4cc; }
.detail-section-title { font-weight: 600; margin-bottom: 8px; color: #606266; }
</style>