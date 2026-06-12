<template>
  <div class="record-table">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" size="small" icon="el-icon-plus" @click="$emit('create')">新增</el-button>
        <el-button size="small" icon="el-icon-refresh" @click="$emit('refresh')">刷新</el-button>
        <el-tooltip content="按主键字段筛选" placement="top">
          <el-input
            v-for="pkField in pkFields"
            :key="pkField.key"
            v-model="filterValues[pkField.key]"
            size="small"
            :placeholder="`筛选 ${pkField.label}`"
            class="filter-input"
            clearable
            @change="onFilterChange" />
        </el-tooltip>
      </div>
      <div class="toolbar-right">
        <el-tag v-if="mockMode" type="warning" size="mini" class="mode-tag">
          <i class="el-icon-warning"></i> Mock 模式
        </el-tag>
        <span class="record-count">共 {{ total }} 条</span>
      </div>
    </div>

    <el-table
      v-loading="loading"
      :data="records"
      stripe
      border
      size="small"
      height="100%"
      class="data-table">
      <el-table-column type="index" label="#" width="50" fixed="left" />
      <el-table-column
        v-for="field in displayFields"
        :key="field.key"
        :prop="field.key"
        :label="field.label"
        :width="field.width || 120"
        :show-overflow-tooltip="true">
        <template slot-scope="{ row }">
          <el-tag v-if="field.primary" size="mini" effect="plain" type="info">{{ row[field.key] }}</el-tag>
          <span v-else-if="field.type === 'number'">{{ formatNumber(row[field.key]) }}</span>
          <el-tag
            v-else-if="field.type === 'enum' && row[field.key] != null"
            size="mini"
            :type="enumTagType(field, row[field.key])"
            effect="plain">{{ row[field.key] }}</el-tag>
          <span v-else>{{ row[field.key] }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template slot-scope="{ row }">
          <el-button size="mini" type="text" @click="$emit('edit', row)">编辑</el-button>
          <el-popconfirm title="确认删除该记录？" @confirm="$emit('delete', row)">
            <el-button slot="reference" size="mini" type="text" style="color:#F56C6C">删除</el-button>
          </el-popconfirm>
        </template>
      </el-table-column>
      <div slot="empty" class="empty-tip">
        <i class="el-icon-folder-opened"></i>
        <p>暂无数据，可点击「新增」创建一条</p>
      </div>
    </el-table>

    <el-pagination
      class="pagination"
      :current-page.sync="innerPage"
      :page-size.sync="innerPageSize"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      layout="total, sizes, prev, pager, next, jumper"
      @current-change="onPageChange"
      @size-change="onSizeChange" />
  </div>
</template>

<script>
export default {
  name: 'RecordTable',
  props: {
    table: { type: Object, default: null },
    records: { type: Array, default: () => [] },
    total: { type: Number, default: 0 },
    page: { type: Number, default: 1 },
    pageSize: { type: Number, default: 20 },
    loading: { type: Boolean, default: false },
    mockMode: { type: Boolean, default: false }
  },
  data() {
    return {
      innerPage: this.page,
      innerPageSize: this.pageSize,
      filterValues: {}
    };
  },
  computed: {
    displayFields() {
      if (!this.table) return [];
      return this.table.fields;
    },
    pkFields() {
      if (!this.table) return [];
      return this.table.fields.filter(f => f.primary);
    }
  },
  watch: {
    page(v) { this.innerPage = v; },
    pageSize(v) { this.innerPageSize = v; },
    table() { this.filterValues = {}; }
  },
  methods: {
    formatNumber(v) {
      if (v == null || v === '') return '';
      const n = Number(v);
      if (Number.isNaN(n)) return v;
      if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(4) + ' 亿';
      if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(4) + ' 万';
      return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(4);
    },
    enumTagType(field, value) {
      const map = {
        ACTIVE: 'success', SUCCESS: 'success', CONFIRMED: 'success', NORMAL: 'success', Y: 'success',
        INACTIVE: 'info', PENDING: 'warning', PROBATION: 'warning', WATCH: 'warning', WARN: 'warning',
        FAILED: 'danger', CANCELLED: 'danger', REJECTED: 'danger', BREACH: 'danger', NEGATIVE: 'danger',
        N: 'info'
      };
      return map[value] || '';
    },
    onPageChange(p) {
      this.$emit('page-change', { page: p, pageSize: this.innerPageSize });
    },
    onSizeChange(s) {
      this.$emit('page-change', { page: 1, pageSize: s });
    },
    onFilterChange() {
      const cleaned = {};
      Object.keys(this.filterValues).forEach(k => {
        const v = this.filterValues[k];
        if (v !== '' && v != null) cleaned[k] = v;
      });
      this.$emit('filter-change', cleaned);
    }
  }
};
</script>

<style scoped>
.record-table {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #ebeef5;
  background: #f8f9fb;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-input {
  width: 160px;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.mode-tag {
  font-weight: 600;
}
.record-count {
  font-size: 13px;
  color: #606266;
}
.data-table {
  flex: 1;
  overflow: auto;
}
.pagination {
  padding: 10px 12px;
  border-top: 1px solid #ebeef5;
  text-align: right;
}
.empty-tip {
  padding: 40px 0;
  color: #909399;
  text-align: center;
}
.empty-tip i {
  font-size: 48px;
  margin-bottom: 8px;
}
</style>
