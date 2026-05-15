<template>
  <div class="data-import-card">
    <!-- 校验结果卡片 -->
    <div v-if="cardType === 'validate'" class="validate-card">
      <div class="card-header">
        <i :class="data.valid ? 'el-icon-success text-success' : 'el-icon-error text-danger'"></i>
        <span>{{ data.valid ? '数据校验通过' : '数据校验未通过' }}</span>
      </div>
      <div class="card-body">
        <!-- 错误列表 -->
        <div v-if="data.errors && data.errors.length" class="error-list">
          <div v-for="(err, i) in data.errors" :key="'e'+i" class="error-item">
            <i class="el-icon-close text-danger"></i>
            <span>{{ err }}</span>
          </div>
        </div>
        <!-- 警告列表 -->
        <div v-if="data.warnings && data.warnings.length" class="warning-list">
          <div v-for="(w, i) in data.warnings" :key="'w'+i" class="warning-item">
            <i class="el-icon-warning text-warning"></i>
            <span>{{ w }}</span>
          </div>
        </div>
        <!-- 检测信息 -->
        <div class="info-row" v-if="data.row_count">
          <span>检测到 {{ data.row_count }} 行数据</span>
          <span v-if="data.date_range">，日期范围：{{ data.date_range }}</span>
        </div>
        <div class="info-row" v-if="data.detected_columns">
          <span>列：{{ data.detected_columns.join(', ') }}</span>
        </div>
      </div>
    </div>

    <!-- 数据预览卡片 -->
    <div v-else-if="cardType === 'preview'" class="preview-card">
      <div class="card-header">
        <i class="el-icon-view"></i>
        <span>数据预览（前 {{ (data.sample_data || []).length }} 行，共 {{ data.row_count }} 行）</span>
      </div>
      <div class="card-body">
        <el-table :data="data.sample_data || []" size="mini" border stripe max-height="200">
          <el-table-column
            v-for="col in (data.columns || [])"
            :key="col"
            :prop="col"
            :label="col"
            min-width="100"
            show-overflow-tooltip
          />
        </el-table>
      </div>
    </div>

    <!-- 导入结果卡片 -->
    <div v-else-if="cardType === 'import'" class="import-result-card">
      <div class="card-header">
        <i :class="data.success ? 'el-icon-success text-success' : 'el-icon-error text-danger'"></i>
        <span>{{ data.success ? '导入完成' : '导入失败' }}</span>
      </div>
      <div class="card-body">
        <div class="stats-grid" v-if="data.stats">
          <div class="stat-item" v-if="data.stats.inserted_count !== undefined">
            <span class="stat-value text-success">{{ data.stats.inserted_count }}</span>
            <span class="stat-label">新增</span>
          </div>
          <div class="stat-item" v-if="data.stats.updated_count !== undefined">
            <span class="stat-value text-primary">{{ data.stats.updated_count }}</span>
            <span class="stat-label">更新</span>
          </div>
          <div class="stat-item" v-if="data.stats.skipped_count !== undefined">
            <span class="stat-value text-info">{{ data.stats.skipped_count }}</span>
            <span class="stat-label">跳过</span>
          </div>
          <div class="stat-item" v-if="data.stats.error_count !== undefined">
            <span class="stat-value text-danger">{{ data.stats.error_count }}</span>
            <span class="stat-label">错误</span>
          </div>
        </div>
        <div v-if="data.message" class="result-message">{{ data.message }}</div>
      </div>
    </div>

    <!-- 模板列表卡片 -->
    <div v-else-if="cardType === 'templates'" class="templates-list-card">
      <div class="card-header">
        <i class="el-icon-menu"></i>
        <span>可用的数据更新模板</span>
      </div>
      <div class="card-body">
        <div v-for="tpl in templatesList" :key="tpl.id" class="template-item">
          <i :class="tpl.icon || 'el-icon-document'"></i>
          <div class="template-info">
            <div class="template-title">{{ tpl.name }}</div>
            <div class="template-desc">{{ tpl.description }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'DataImportCards',
  props: {
    cardType: { type: String, required: true },
    data: { type: Object, default: () => ({}) }
  },
  computed: {
    templatesList() {
      return this.data.templates || this.data || []
    }
  }
}
</script>

<style scoped>
.data-import-card {
  margin-top: 8px;
}

.validate-card,
.preview-card,
.import-result-card,
.templates-list-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  background: #fafafa;
  border-bottom: 1px solid #ebeef5;
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}

.card-header i {
  font-size: 16px;
}

.card-body {
  padding: 10px 14px;
  font-size: 13px;
  color: #606266;
}

/* 校验结果 */
.error-list,
.warning-list {
  margin-bottom: 6px;
}

.error-item,
.warning-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  line-height: 1.5;
}

.error-item i,
.warning-item i {
  flex-shrink: 0;
}

.info-row {
  padding: 3px 0;
  color: #909399;
  font-size: 12px;
}

/* 导入结果统计 */
.stats-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 50px;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

.stat-label {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}

.result-message {
  padding: 4px 0;
  color: #606266;
  font-size: 12px;
}

/* 模板列表 */
.template-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid #f2f6fc;
}

.template-item:last-child {
  border-bottom: none;
}

.template-item > i {
  font-size: 18px;
  color: #409eff;
  margin-top: 2px;
}

.template-info {
  flex: 1;
  min-width: 0;
}

.template-title {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 2px;
}

.template-desc {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}

/* 颜色辅助 */
.text-success { color: #67c23a; }
.text-danger { color: #f56c6c; }
.text-warning { color: #e6a23c; }
.text-primary { color: #409eff; }
.text-info { color: #909399; }

/* 预览表格微调 */
.preview-card .card-body {
  padding: 0;
}

.preview-card .card-body >>> .el-table {
  border-radius: 0;
}
</style>
