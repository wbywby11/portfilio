<template>
  <div class="domain-overview-panel">
    <h4 style="margin:0 0 10px">业务域概览</h4>
    <div
      v-for="domain in domains"
      :key="domain.code"
      class="domain-card"
      :class="{ active: selectedDomain === domain.code }"
      @click="$emit('select-domain', domain.code === selectedDomain ? '' : domain.code)"
    >
      <div class="domain-card-header">
        <span class="domain-name">{{ domain.name }}</span>
        <el-tag size="mini" effect="plain">{{ domain.table_count }}表</el-tag>
      </div>
      <div class="domain-desc">{{ domain.description }}</div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'DomainOverviewPanel',
  props: {
    domains: { type: Array, default: () => [] },
    selectedDomain: { type: String, default: '' }
  }
}
</script>

<style scoped>
.domain-overview-panel {
  padding: 8px;
}
.domain-card {
  padding: 10px;
  margin-bottom: 8px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.domain-card:hover {
  border-color: #409EFF;
  background: #f0f7ff;
}
.domain-card.active {
  border-color: #409EFF;
  background: #ecf5ff;
}
.domain-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.domain-name {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}
.domain-desc {
  font-size: 11px;
  color: #909399;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
