<template>
  <div class="data-lineage-page">
    <!-- 顶部工具栏 -->
    <div class="lineage-toolbar">
      <h3 style="margin:0">数据血缘图谱</h3>
      <el-input
        v-model="searchQuery"
        placeholder="搜索表名或关键词..."
        prefix-icon="el-icon-search"
        size="small"
        style="width: 240px"
        clearable
        @keyup.enter.native="handleSearch"
      />
      <el-select v-model="selectedDomain" placeholder="筛选域" size="small" clearable @change="handleDomainFilterChange">
        <el-option v-for="d in domains" :key="d.code" :label="d.name" :value="d.code" />
      </el-select>
    </div>

    <div class="lineage-content">
      <!-- 左侧域概览 -->
      <div class="lineage-left">
        <DomainOverviewPanel
          :domains="domains"
          :selected-domain="selectedDomain"
          @select-domain="handleDomainSelect"
        />
      </div>

      <!-- 中间图谱 -->
      <div class="lineage-center">
        <LineageGraph
          ref="graph"
          :nodes="graphNodes"
          :edges="graphEdges"
          :highlight-tables="highlightTables"
          :focus-domain="selectedDomain"
          @node-click="handleNodeClick"
          @edge-click="handleEdgeClick"
        />
      </div>

      <!-- 右侧详情（条件展示） -->
      <div class="lineage-right" v-if="selectedDomain && !selectedTable">
        <DomainDetailPanel
          :domain="currentDomainInfo"
          :domain-profile="domainProfile"
          :loading="domainProfileLoading"
          @close="handleDomainPanelClose"
          @table-click="handleNodeClick"
          @show-resonance="showResonanceDialog = true"
        />
      </div>
      <div class="lineage-right" v-else-if="selectedTable">
        <TableDetailPanel
          :table-name="selectedTable"
          :profile="selectedProfile"
          :loading="profileLoading"
          @close="selectedTable = null"
        />
      </div>
    </div>

    <!-- L5.3 跨域联动画像弹窗 -->
    <ProfileViewerDialog :visible.sync="showResonanceDialog" @close="showResonanceDialog = false" />
  </div>
</template>

<script>
import { getSemanticOverview, getLineageGraph, getTableProfile, getDomainProfile } from '@/api/semantic'
import DomainOverviewPanel from './DomainOverviewPanel.vue'
import LineageGraph from './LineageGraph.vue'
import TableDetailPanel from './TableDetailPanel.vue'
import DomainDetailPanel from './DomainDetailPanel.vue'
import ProfileViewerDialog from './ProfileViewerDialog.vue'

export default {
  name: 'DataLineage',
  components: { DomainOverviewPanel, LineageGraph, TableDetailPanel, DomainDetailPanel, ProfileViewerDialog },
  data() {
    return {
      domains: [],
      selectedDomain: '',
      graphNodes: [],
      graphEdges: [],
      selectedTable: null,
      selectedProfile: null,
      profileLoading: false,
      searchQuery: '',
      highlightTables: [],
      domainProfile: null,
      domainProfileLoading: false,
      showResonanceDialog: false
    }
  },
  computed: {
    currentDomainInfo() {
      if (!this.selectedDomain) return null
      return this.domains.find(d => d.code === this.selectedDomain || d.domain_code === this.selectedDomain) || null
    }
  },
  created() {
    this.loadOverview()
    this.loadGraph()
    // 处理DeepLink高亮参数
    const highlight = this.$route.query.highlight
    if (highlight) {
      this.highlightTables = highlight.split(',')
    }
  },
  methods: {
    async loadOverview() {
      try {
        const res = await getSemanticOverview()
        const rawDomains = res.data?.domains || res.domains || []
        // 规范化字段名：后端返回 domain_code/domain_name，前端统一使用 code/name
        this.domains = rawDomains.map(d => ({
          ...d,
          code: d.code || d.domain_code || '',
          name: d.name || d.domain_name || '',
          description: d.description || '',
          table_count: d.table_count || 0,
          tables: d.tables || [],
          core_scenarios: d.core_scenarios || [],
          key_entities: d.key_entities || []
        }))
      } catch (e) {
        console.warn('加载域概览失败', e)
      }
    },
    async loadGraph() {
      try {
        // 始终加载全量图谱，域高亮由前端focusDomain样式控制
        const res = await getLineageGraph()
        const data = res.data || res
        this.graphNodes = data.nodes || []
        this.graphEdges = data.edges || []
      } catch (e) {
        console.warn('加载图谱失败', e)
      }
    },
    handleDomainFilterChange(domain) {
      // 下拉框选域：只改高亮，不重新请求数据
      this.selectedTable = null
      this.selectedDomain = domain || ''
      if (domain) {
        this.loadDomainProfile(domain)
      } else {
        this.domainProfile = null
      }
    },
    async handleNodeClick(tableName) {
      // 保留域聚焦状态：不再清空 selectedDomain
      // 仅切换表详情，域淡化效果持续保持
      this.selectedTable = tableName
      this.profileLoading = true
      try {
        const res = await getTableProfile(tableName)
        this.selectedProfile = res.data || res
      } catch (e) {
        this.selectedProfile = null
      } finally {
        this.profileLoading = false
      }
    },
    handleEdgeClick(edgeData) {
      // 点击边时展示关联关系详情
      const srcName = edgeData.source_display || edgeData.source
      const tgtName = edgeData.target_display || edgeData.target
      const fieldInfo = edgeData.field_display !== edgeData.source_field
        ? `「${edgeData.field_display}」(${edgeData.source_field})`
        : edgeData.source_field
      const tgtFieldInfo = edgeData.target_field_display !== edgeData.target_field
        ? `「${edgeData.target_field_display}」(${edgeData.target_field})`
        : edgeData.target_field
      this.$notify({
        title: `${srcName} → ${tgtName}`,
        dangerouslyUseHTMLString: true,
        message: `
          <div style="line-height:1.8;font-size:13px">
            <div><b>关联字段：</b>${fieldInfo} → ${tgtFieldInfo}</div>
            <div style="color:#666;margin-top:4px">${edgeData.relation_desc || ''}</div>
          </div>
        `,
        type: 'info',
        duration: 5000,
        position: 'bottom-right'
      })
    },
    handleDomainSelect(domain) {
      this.selectedTable = null
      this.selectedDomain = domain
      // 不再重新loadGraph，焦点域变化通过focusDomain prop触发图谱样式更新
      this.loadDomainProfile(domain)
    },
    handleDomainPanelClose() {
      this.selectedDomain = ''
      this.domainProfile = null
    },
    async loadDomainProfile(domainCode) {
      if (!domainCode) {
        this.domainProfile = null
        return
      }
      this.domainProfileLoading = true
      try {
        const res = await getDomainProfile(domainCode)
        this.domainProfile = res.data || res
      } catch (e) {
        this.domainProfile = null
      } finally {
        this.domainProfileLoading = false
      }
    },
    handleSearch() {
      if (this.searchQuery) {
        const q = this.searchQuery.toLowerCase()
        this.highlightTables = this.graphNodes
          .filter(n => n.id.toLowerCase().includes(q) || (n.name && n.name.toLowerCase().includes(q)))
          .map(n => n.id)
      } else {
        this.highlightTables = []
      }
    }
  }
}
</script>

<style scoped>
.data-lineage-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px;
  box-sizing: border-box;
}
.lineage-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
}
.lineage-content {
  flex: 1;
  display: flex;
  gap: 12px;
  overflow: hidden;
}
.lineage-left {
  width: 220px;
  flex-shrink: 0;
  overflow-y: auto;
}
.lineage-center {
  flex: 1;
  min-width: 0;
}
.lineage-right {
  width: 340px;
  flex-shrink: 0;
  overflow-y: auto;
  position: relative;
  z-index: 10;
}
</style>
