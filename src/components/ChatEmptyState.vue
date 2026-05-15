<template>
  <div class="empty-state">
    <i class="el-icon-chat-dot-round empty-icon"></i>
    <h3>{{ welcomeTitle }}</h3>
    <p class="empty-desc">{{ welcomeDescription }}</p>
    <div class="quick-questions">
      <el-button
        v-for="(q, idx) in quickQuestions"
        :key="idx"
        size="small"
        round
        @click="$emit('quick-question', q)"
      >{{ quickQuestionLabel(q) }}</el-button>
    </div>

    <!-- 数据更新快捷入口 -->
    <div class="data-templates-section">
      <div class="section-title">
        <i class="el-icon-upload2"></i>
        <span>数据更新快捷操作</span>
      </div>
      <div class="data-templates-grid">
        <div
          v-for="tpl in dataTemplates"
          :key="tpl.id"
          class="data-template-item"
          @click="$emit('select-template', tpl)"
        >
          <i :class="tpl.icon"></i>
          <span>{{ tpl.name }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { quickQuestionLabel } from '@/config/creditRatingQuickAddons'

export default {
  name: 'ChatEmptyState',
  props: {
    welcomeTitle: {
      type: String,
      default: ''
    },
    welcomeDescription: {
      type: String,
      default: ''
    },
    quickQuestions: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      dataTemplates: [
        { id: 'price_import', name: '导入行情数据', icon: 'el-icon-data-line',
          prompt: '请上传行情Excel文件，需包含日期和收盘价列。我会帮您校验数据格式并导入系统。',
          acceptFormats: '.xlsx,.xls,.csv' },
        { id: 'fx_import', name: '导入汇率数据', icon: 'el-icon-money',
          prompt: '请上传汇率Excel文件，需包含日期列和至少一个币种汇率列（EUR/USD/HKD/CNH）。',
          acceptFormats: '.xlsx,.xls,.csv' },
        { id: 'asset_info_import', name: '导入资产信息', icon: 'el-icon-folder-add',
          prompt: '请上传资产信息Excel，需包含资产代码和名称列。',
          acceptFormats: '.xlsx,.xls,.csv' },
        { id: 'api_sync', name: '同步API数据', icon: 'el-icon-refresh',
          prompt: '请告诉我要同步哪个数据源，我可以列出所有可用的API数据源供您选择。',
          acceptFormats: '' },
        { id: 'data_clean', name: '数据清洗修复', icon: 'el-icon-brush',
          prompt: '请告诉我要检查哪个资产或集合的数据质量，我会分析异常值和缺失情况。',
          acceptFormats: '' }
      ]
    }
  },
  methods: {
    quickQuestionLabel
  }
}
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #606266;
}

.empty-icon {
  font-size: 64px;
  color: #c0c4cc;
  margin-bottom: 16px;
}

.empty-state h3 {
  margin: 0 0 8px;
  font-size: 20px;
  color: #303133;
}

.empty-desc {
  color: #909399;
  margin-bottom: 24px;
  font-size: 14px;
}

.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  max-width: 600px;
}

.data-templates-section {
  margin-top: 24px;
  width: 100%;
  max-width: 600px;
}

.section-title {
  font-size: 13px;
  color: #909399;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: center;
}

.data-templates-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.data-template-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
  background: #fff;
}

.data-template-item:hover {
  border-color: #409eff;
  color: #409eff;
  background: #ecf5ff;
}

.data-template-item i {
  font-size: 14px;
}
</style>
