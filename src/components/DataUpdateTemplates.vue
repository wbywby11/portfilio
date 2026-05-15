<template>
  <div class="data-update-templates">
    <div class="templates-header">
      <i class="el-icon-upload2"></i>
      <span>数据更新</span>
    </div>
    <div class="templates-grid">
      <div
        v-for="tpl in templates"
        :key="tpl.id"
        class="template-card"
        @click="handleSelect(tpl)"
      >
        <i :class="tpl.icon"></i>
        <span class="template-name">{{ tpl.name }}</span>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'DataUpdateTemplates',
  data() {
    return {
      templates: [
        {
          id: 'price_import',
          name: '导入行情数据',
          icon: 'el-icon-data-line',
          prompt: '请上传行情Excel文件，需包含日期和收盘价列。我会帮您校验数据格式并导入系统。',
          acceptFormats: '.xlsx,.xls,.csv'
        },
        {
          id: 'fx_import',
          name: '导入汇率数据',
          icon: 'el-icon-money',
          prompt: '请上传汇率Excel文件，需包含日期列和至少一个币种汇率列（EUR/USD/HKD/CNH）。',
          acceptFormats: '.xlsx,.xls,.csv'
        },
        {
          id: 'asset_info_import',
          name: '导入资产信息',
          icon: 'el-icon-folder-add',
          prompt: '请上传资产信息Excel，需包含资产代码和名称列。',
          acceptFormats: '.xlsx,.xls,.csv'
        },
        {
          id: 'multi_asset_price',
          name: '多资产宽表',
          icon: 'el-icon-s-grid',
          prompt: '请上传多资产宽表Excel，第一列为日期，后续列标题为资产代码。',
          acceptFormats: '.xlsx,.xls'
        },
        {
          id: 'trade_dates_import',
          name: '交易日历更新',
          icon: 'el-icon-date',
          prompt: '请上传交易日历Excel文件，需包含交易日期列。我会帮您校验格式并导入系统。',
          acceptFormats: '.xlsx,.xls,.csv'
        },
        {
          id: 'api_sync',
          name: '同步API数据',
          icon: 'el-icon-refresh',
          prompt: '请告诉我要同步哪个数据源，我可以列出所有可用的API数据源供您选择。',
          acceptFormats: ''
        },
        {
          id: 'data_clean',
          name: '数据清洗修复',
          icon: 'el-icon-brush',
          prompt: '请告诉我要检查哪个资产或集合的数据质量，我会分析异常值和缺失情况。',
          acceptFormats: ''
        }
      ]
    }
  },
  methods: {
    handleSelect(tpl) {
      this.$emit('select-template', tpl)
    }
  }
}
</script>

<style scoped>
.data-update-templates {
  padding: 8px 12px;
  border-bottom: 1px solid #ebeef5;
}
.templates-header {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.templates-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.template-card {
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
.template-card:hover {
  border-color: #409eff;
  color: #409eff;
  background: #ecf5ff;
}
.template-card i {
  font-size: 14px;
}
.template-name {
  white-space: nowrap;
}
</style>
