<template>
  <div class="memory-manager">
    <!-- 顶部操作栏 -->
    <div class="toolbar">
      <el-input
        v-model="searchKeyword"
        placeholder="输入关键词搜索记忆..."
        prefix-icon="el-icon-search"
        clearable
        class="search-input"
        @keyup.enter.native="handleSearch"
        @clear="handleClearSearch"
      />
      <el-select
        v-model="selectedCategory"
        placeholder="全部分类"
        clearable
        class="category-select"
        @change="handleCategoryChange"
      >
        <el-option
          v-for="item in categoryOptions"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
      <el-button type="primary" icon="el-icon-search" @click="handleSearch">搜索</el-button>
      <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
    </div>

    <!-- 记忆卡片列表 -->
    <div v-loading="loading" class="memory-list">
      <template v-if="memories.length > 0">
        <el-card
          v-for="item in memories"
          :key="item.id"
          class="memory-card"
          shadow="hover"
        >
          <div class="card-header">
            <span class="memory-title">{{ item.title }}</span>
            <el-tag
              :type="categoryTagType(item.category)"
              size="small"
              effect="plain"
            >{{ categoryLabel(item.category) }}</el-tag>
          </div>

          <div class="memory-content">{{ truncateContent(item.content) }}</div>

          <div class="memory-keywords" v-if="item.keywords && item.keywords.length">
            <el-tag
              v-for="(kw, idx) in item.keywords"
              :key="idx"
              size="mini"
              type="info"
              class="keyword-tag"
            >{{ kw }}</el-tag>
          </div>

          <div class="card-footer">
            <span class="update-time">
              <i class="el-icon-time"></i>
              {{ formatTime(item.updated_at || item.created_at) }}
            </span>
            <span class="card-actions">
              <el-button type="text" size="small" @click="handleViewDetail(item)">
                <i class="el-icon-view"></i> 查看详情
              </el-button>
              <el-button type="text" size="small" class="delete-btn" @click="handleDelete(item)">
                <i class="el-icon-delete"></i> 删除
              </el-button>
            </span>
          </div>
        </el-card>
      </template>

      <!-- 空状态 -->
      <el-empty v-else-if="!loading" description="暂无记忆数据">
        <el-button type="primary" size="small" @click="handleReset">刷新列表</el-button>
      </el-empty>
    </div>

    <!-- 分页 -->
    <div class="pagination-wrap" v-if="total > pageSize">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page.sync="currentPage"
        @current-change="fetchMemories"
      />
    </div>

    <!-- 详情对话框 -->
    <el-dialog
      title="记忆详情"
      :visible.sync="detailVisible"
      width="600px"
      append-to-body
    >
      <div v-if="currentMemory" class="detail-dialog">
        <div class="detail-row">
          <span class="detail-label">标题：</span>
          <span class="detail-value title">{{ currentMemory.title }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">分类：</span>
          <el-tag
            :type="categoryTagType(currentMemory.category)"
            size="small"
            effect="plain"
          >{{ categoryLabel(currentMemory.category) }}</el-tag>
        </div>
        <div class="detail-row">
          <span class="detail-label">内容：</span>
          <div class="detail-content">{{ currentMemory.content }}</div>
        </div>
        <div class="detail-row" v-if="currentMemory.keywords && currentMemory.keywords.length">
          <span class="detail-label">关键词：</span>
          <div class="detail-keywords">
            <el-tag
              v-for="(kw, idx) in currentMemory.keywords"
              :key="idx"
              size="small"
              type="info"
              class="keyword-tag"
            >{{ kw }}</el-tag>
          </div>
        </div>
        <div class="detail-row">
          <span class="detail-label">创建时间：</span>
          <span>{{ formatTime(currentMemory.created_at) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">更新时间：</span>
          <span>{{ formatTime(currentMemory.updated_at) }}</span>
        </div>
      </div>
      <span slot="footer">
        <el-button @click="detailVisible = false">关闭</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { getMemories, deleteMemory, searchMemories } from '@/api/agent'
import dayjs from 'dayjs'

// 分类配置映射
const CATEGORY_MAP = {
  research_conclusion: { label: '研究结论', tagType: '' },        // 蓝色（默认）
  user_preference: { label: '用户偏好', tagType: 'success' },     // 绿色
  asset_alias: { label: '资产别名', tagType: 'warning' },         // 橙色
  strategy_insight: { label: '策略洞察', tagType: 'danger' }      // 紫红色近似
}

export default {
  name: 'MemoryManager',
  data() {
    return {
      // 搜索与筛选
      searchKeyword: '',
      selectedCategory: '',
      // 列表数据
      memories: [],
      total: 0,
      currentPage: 1,
      pageSize: 12,
      loading: false,
      // 详情对话框
      detailVisible: false,
      currentMemory: null,
      // 分类下拉选项
      categoryOptions: [
        { label: '研究结论', value: 'research_conclusion' },
        { label: '用户偏好', value: 'user_preference' },
        { label: '资产别名', value: 'asset_alias' },
        { label: '策略洞察', value: 'strategy_insight' }
      ]
    }
  },
  created() {
    this.fetchMemories()
  },
  methods: {
    /** 获取记忆列表 */
    async fetchMemories() {
      this.loading = true
      try {
        const params = {
          user_id: 'default',
          page: this.currentPage,
          page_size: this.pageSize
        }
        if (this.selectedCategory) {
          params.category = this.selectedCategory
        }
        const res = await getMemories(params)
        if (res.code === 200) {
          this.memories = res.data.memories || []
          this.total = res.data.total || 0
        }
      } catch (e) {
        this.$message.error('获取记忆列表失败')
      } finally {
        this.loading = false
      }
    },

    /** 搜索记忆 */
    async handleSearch() {
      if (!this.searchKeyword.trim()) {
        this.currentPage = 1
        this.fetchMemories()
        return
      }
      this.loading = true
      try {
        const res = await searchMemories({
          keywords: this.searchKeyword.trim().split(/\s+/),
          user_id: 'default'
        })
        if (res.code === 200) {
          let results = res.data.memories || []
          // 前端按分类二次过滤
          if (this.selectedCategory) {
            results = results.filter(m => m.category === this.selectedCategory)
          }
          this.memories = results
          this.total = results.length
        }
      } catch (e) {
        this.$message.error('搜索记忆失败')
      } finally {
        this.loading = false
      }
    },

    /** 清除搜索 */
    handleClearSearch() {
      this.searchKeyword = ''
      this.currentPage = 1
      this.fetchMemories()
    },

    /** 分类变更 */
    handleCategoryChange() {
      this.currentPage = 1
      if (this.searchKeyword.trim()) {
        this.handleSearch()
      } else {
        this.fetchMemories()
      }
    },

    /** 重置筛选条件 */
    handleReset() {
      this.searchKeyword = ''
      this.selectedCategory = ''
      this.currentPage = 1
      this.fetchMemories()
    },

    /** 查看详情 */
    handleViewDetail(item) {
      this.currentMemory = item
      this.detailVisible = true
    },

    /** 删除记忆 */
    handleDelete(item) {
      this.$confirm(`确定要删除记忆「${item.title}」吗？删除后不可恢复。`, '删除确认', {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          const res = await deleteMemory(item.id)
          if (res.code === 200) {
            this.$message.success('删除成功')
            this.fetchMemories()
          }
        } catch (e) {
          this.$message.error('删除失败')
        }
      }).catch(() => {})
    },

    /** 截断内容显示 */
    truncateContent(content) {
      if (!content) return ''
      return content.length > 200 ? content.substring(0, 200) + '...' : content
    },

    /** 格式化时间 */
    formatTime(time) {
      if (!time) return '-'
      return dayjs(time).format('YYYY-MM-DD HH:mm')
    },

    /** 获取分类中文标签 */
    categoryLabel(category) {
      return (CATEGORY_MAP[category] && CATEGORY_MAP[category].label) || category
    },

    /** 获取分类标签颜色类型 */
    categoryTagType(category) {
      return (CATEGORY_MAP[category] && CATEGORY_MAP[category].tagType) || 'info'
    }
  }
}
</script>

<style scoped>
.memory-manager {
  padding: 0;
}

/* 顶部工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  background: #fff;
  padding: 16px 20px;
  border-radius: 4px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}

.search-input {
  width: 320px;
}

.category-select {
  width: 160px;
}

/* 记忆卡片列表 */
.memory-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
  min-height: 200px;
}

.memory-card {
  transition: transform 0.2s;
}

.memory-card:hover {
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.memory-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  flex: 1;
  margin-right: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.memory-content {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 12px;
  word-break: break-all;
}

.memory-keywords {
  margin-bottom: 12px;
}

.keyword-tag {
  margin-right: 6px;
  margin-bottom: 4px;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid #ebeef5;
  padding-top: 10px;
}

.update-time {
  font-size: 12px;
  color: #909399;
}

.update-time i {
  margin-right: 4px;
}

.card-actions {
  display: flex;
  gap: 4px;
}

.delete-btn {
  color: #F56C6C !important;
}

.delete-btn:hover {
  color: #f78989 !important;
}

/* 分页 */
.pagination-wrap {
  display: flex;
  justify-content: center;
  margin-top: 24px;
  padding: 12px 0;
}

/* 详情对话框 */
.detail-dialog .detail-row {
  margin-bottom: 16px;
}

.detail-label {
  font-weight: 600;
  color: #606266;
  margin-right: 8px;
}

.detail-value.title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.detail-content {
  margin-top: 8px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-all;
}

.detail-keywords {
  display: inline;
}

/* 空状态居中 */
.memory-list .el-empty {
  grid-column: 1 / -1;
}
</style>
