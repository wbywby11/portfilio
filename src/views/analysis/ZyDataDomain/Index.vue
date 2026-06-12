<template>
  <div class="zy-data-domain-page">
    <div class="page-header">
      <div class="header-left">
        <i class="el-icon-coin"></i>
        <span class="title">ZY 数据域管理</span>
        <el-tag size="mini" type="info" v-if="domainSummary">
          共 {{ domainSummary.totalDomains }} 个域 / {{ domainSummary.totalTables }} 张表
        </el-tag>
        <el-tag size="mini" type="warning" v-if="mockMode">本地 Mock 模式</el-tag>
      </div>
      <div class="header-right">
        <el-button
          v-if="mockMode"
          size="mini"
          icon="el-icon-refresh-left"
          @click="onResetMock">
          重置 Mock 数据
        </el-button>
        <el-tooltip content="基准业务日期 BIZ_DT" placement="bottom">
          <el-tag size="mini" effect="plain">BIZ_DT: {{ bizDt }}</el-tag>
        </el-tooltip>
      </div>
    </div>

    <div class="page-body">
      <div class="page-aside">
        <DomainTablePicker
          v-model="currentCollection"
          @change="onTableChange" />
      </div>
      <div class="page-main">
        <div v-if="!currentTable" class="empty-tip">
          <i class="el-icon-arrow-left"></i>
          <span>请在左侧选择一张表开始管理</span>
        </div>
        <RecordTable
          v-else
          :table="currentTable"
          :records="records"
          :total="total"
          :loading="loading"
          :mock-mode="mockMode"
          @create="onCreate"
          @edit="onEdit"
          @delete="onDelete"
          @refresh="loadRecords"
          @page-change="onPageChange"
          @filter-change="onFilterChange" />
      </div>
    </div>

    <RecordFormDialog
      :visible.sync="dialogVisible"
      :table="currentTable"
      :record="editingRecord"
      :submitting="submitting"
      @submit="onSubmit" />
  </div>
</template>

<script>
import DomainTablePicker from './DomainTablePicker.vue';
import RecordTable from './RecordTable.vue';
import RecordFormDialog from './RecordFormDialog.vue';
import {
  listRecords,
  createRecord,
  updateRecord,
  deleteRecord,
  isMockMode,
  resetMockData
} from '@/api/zyDataDomain';
import { findTable, domainSummary, BIZ_DT } from '@/config/zyDataDomain';

export default {
  name: 'ZyDataDomainIndex',
  components: { DomainTablePicker, RecordTable, RecordFormDialog },
  data() {
    return {
      currentCollection: '',
      currentTable: null,
      currentDomain: null,
      records: [],
      total: 0,
      page: 1,
      pageSize: 20,
      filters: {},
      loading: false,
      submitting: false,
      dialogVisible: false,
      editingRecord: null,
      mockMode: false,
      bizDt: BIZ_DT,
      domainSummary: null
    };
  },
  created() {
    this.domainSummary = domainSummary();
    this.mockMode = isMockMode();
  },
  methods: {
    onTableChange(payload) {
      // DomainTablePicker @change 传递节点对象 { id, label, code, domain, isLeaf }。
      // 以前误作字符串使用，导致 currentTable 始终为 null。
      let collection = '';
      if (payload && typeof payload === 'object') {
        collection = payload.id || payload.code || payload.name || '';
      } else if (typeof payload === 'string') {
        collection = payload;
      }
      this.currentCollection = collection;
      // findTable 返回 { domain, table } 包装对象，
      // 需拆出 table 才能被 RecordTable / RecordFormDialog 正确读取 fields/pk。
      const found = collection ? findTable(collection) : null;
      this.currentTable = found ? found.table : null;
      this.currentDomain = found ? found.domain : null;
      this.page = 1;
      this.filters = {};
      this.records = [];
      this.total = 0;
      if (this.currentTable) {
        this.loadRecords();
      }
    },
    async loadRecords() {
      if (!this.currentCollection) return;
      this.loading = true;
      try {
        const res = await listRecords(this.currentCollection, {
          page: this.page,
          pageSize: this.pageSize,
          filters: this.filters
        });
        this.records = res.records || res.items || [];
        this.total = res.total || 0;
        this.mockMode = isMockMode();
      } catch (err) {
        this.$message.error('加载数据失败：' + (err.message || err));
        this.records = [];
        this.total = 0;
      } finally {
        this.loading = false;
      }
    },
    onPageChange({ page, pageSize }) {
      this.page = page;
      this.pageSize = pageSize;
      this.loadRecords();
    },
    onFilterChange(filters) {
      this.filters = filters || {};
      this.page = 1;
      this.loadRecords();
    },
    onCreate() {
      this.editingRecord = null;
      this.dialogVisible = true;
    },
    onEdit(record) {
      this.editingRecord = record;
      this.dialogVisible = true;
    },
    async onDelete(record) {
      if (!this.currentTable) return;
      const pk = (this.currentTable.pk || []).reduce((acc, k) => {
        acc[k] = record[k];
        return acc;
      }, {});
      try {
        await deleteRecord(this.currentCollection, pk, record._id);
        this.$message.success('删除成功');
        this.loadRecords();
      } catch (err) {
        this.$message.error('删除失败：' + (err.message || err));
      }
    },
    async onSubmit({ isEdit, payload, record }) {
      if (!this.currentTable) return;
      this.submitting = true;
      try {
        if (isEdit) {
          const pk = (this.currentTable.pk || []).reduce((acc, k) => {
            acc[k] = record[k];
            return acc;
          }, {});
          await updateRecord(this.currentCollection, pk, payload, record._id);
          this.$message.success('更新成功');
        } else {
          await createRecord(this.currentCollection, payload);
          this.$message.success('创建成功');
        }
        this.dialogVisible = false;
        this.mockMode = isMockMode();
        this.loadRecords();
      } catch (err) {
        this.$message.error((isEdit ? '更新' : '创建') + '失败：' + (err.message || err));
      } finally {
        this.submitting = false;
      }
    },
    onResetMock() {
      this.$confirm('确认重置本地 Mock 数据？所有自定义新增/修改/删除将丢失，数据将恢复为初始种子。', '提示', {
        type: 'warning',
        confirmButtonText: '确认重置',
        cancelButtonText: '取消'
      }).then(() => {
        resetMockData();
        this.$message.success('Mock 数据已重置');
        this.loadRecords();
      }).catch(() => {});
    }
  }
};
</script>

<style scoped>
.zy-data-domain-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-left .el-icon-coin {
  font-size: 22px;
  color: #409eff;
}
.header-left .title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.page-body {
  flex: 1;
  display: flex;
  overflow: hidden;
  padding: 12px;
  gap: 12px;
}
.page-aside {
  width: 300px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 4px;
  border: 1px solid #ebeef5;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.page-main {
  flex: 1;
  background: #fff;
  border-radius: 4px;
  border: 1px solid #ebeef5;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.empty-tip {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #909399;
  font-size: 14px;
}
.empty-tip i {
  font-size: 18px;
}
</style>
