<template>
  <div class="conversation-history">
    <!-- 顶部筛选栏 -->
    <div class="filter-bar">
      <el-select
        v-model="filterScene"
        placeholder="全部场景"
        clearable
        size="small"
        class="filter-select"
        @change="handleFilter"
      >
        <el-option
          v-for="s in scenes"
          :key="s.key"
          :label="s.label"
          :value="s.key"
        />
      </el-select>
      <el-date-picker
        v-model="filterDateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        size="small"
        value-format="yyyy-MM-dd"
        class="filter-date"
        @change="handleFilter"
      />
      <el-input
        v-model="filterKeyword"
        placeholder="搜索对话标题"
        prefix-icon="el-icon-search"
        clearable
        size="small"
        class="filter-input"
        @keyup.enter.native="handleFilter"
        @clear="handleFilter"
      />
      <el-button size="small" icon="el-icon-search" @click="handleFilter">搜索</el-button>
      <el-button size="small" icon="el-icon-refresh" @click="handleReset">重置</el-button>
      <div class="filter-actions">
        <el-button
          v-if="selectedIds.length"
          type="danger"
          size="small"
          icon="el-icon-delete"
          @click="handleBatchDelete"
        >批量删除 ({{ selectedIds.length }})</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <el-table
      v-loading="loading"
      :data="filteredList"
      style="width: 100%"
      @selection-change="handleSelectionChange"
      class="history-table"
    >
      <el-table-column type="selection" width="45" />
      <el-table-column prop="title" label="对话标题" min-width="200">
        <template slot-scope="{ row }">
          <span class="conv-title-link" @click="goToConversation(row)">
            {{ row.title || '新对话' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="场景" width="120">
        <template slot-scope="{ row }">
          <el-tag
            v-if="getConversationScene(row.id)"
            size="small"
            :color="getSceneColor(row.id)"
            effect="dark"
          >{{ getSceneLabel(row.id) }}</el-tag>
          <span v-else class="no-scene">—</span>
        </template>
      </el-table-column>
      <el-table-column label="消息数" width="90" align="center">
        <template slot-scope="{ row }">
          {{ row.message_count || row.msg_count || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template slot-scope="{ row }">
          {{ formatTime(row.updated_at || row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template slot-scope="{ row }">
          <el-button type="text" size="small" @click="goToConversation(row)">
            <i class="el-icon-chat-dot-round"></i> 继续
          </el-button>
          <el-button type="text" size="small" class="delete-btn" @click="handleDelete(row)">
            <i class="el-icon-delete"></i> 删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap" v-if="total > pageSize">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page.sync="currentPage"
        @current-change="fetchData"
      />
    </div>
  </div>
</template>

<script>
/**
 * 对话历史页面
 * 表格展示所有对话，支持场景/时间筛选、批量删除、点击跳转
 */
import { mapGetters, mapState } from 'vuex'
import { AGENT_SCENES, getSceneByKey } from '@/config/agentScenes'
import dayjs from 'dayjs'

export default {
  name: 'ConversationHistory',
  data() {
    return {
      scenes: AGENT_SCENES,
      loading: false,
      // 筛选条件
      filterScene: '',
      filterDateRange: null,
      filterKeyword: '',
      // 列表数据
      list: [],
      total: 0,
      currentPage: 1,
      pageSize: 20,
      // 批量选择
      selectedIds: []
    }
  },
  computed: {
    ...mapGetters('agent', ['sortedConversations']),
    ...mapState('agent', ['conversationScenes']),
    /** 前端二次筛选结果 */
    filteredList() {
      let result = this.list
      if (this.filterScene) {
        result = result.filter(c => this.conversationScenes[c.id] === this.filterScene)
      }
      if (this.filterDateRange && this.filterDateRange.length === 2) {
        const start = dayjs(this.filterDateRange[0]).startOf('day')
        const end = dayjs(this.filterDateRange[1]).endOf('day')
        result = result.filter(c => {
          const t = dayjs(c.updated_at || c.created_at)
          return t.isAfter(start) && t.isBefore(end)
        })
      }
      if (this.filterKeyword.trim()) {
        const kw = this.filterKeyword.trim().toLowerCase()
        result = result.filter(c => (c.title || '').toLowerCase().includes(kw))
      }
      return result
    }
  },
  created() {
    this.fetchData()
  },
  methods: {
    /** 获取对话列表 */
    async fetchData() {
      this.loading = true
      try {
        await this.$store.dispatch('agent/loadConversations')
        this.list = this.$store.state.agent.conversations
        this.total = this.list.length
      } catch (e) {
        this.$message.error('加载对话列表失败')
      } finally {
        this.loading = false
      }
    },

    /** 触发筛选 */
    handleFilter() {
      // 前端筛选，无需请求后端
    },

    /** 重置筛选 */
    handleReset() {
      this.filterScene = ''
      this.filterDateRange = null
      this.filterKeyword = ''
    },

    /** 选择变更 */
    handleSelectionChange(rows) {
      this.selectedIds = rows.map(r => r.id)
    },

    /** 跳转到对话 */
    goToConversation(row) {
      const sceneKey = this.conversationScenes[row.id] || 'auto'
      this.$router.push(`/agent/chat/${sceneKey}`)
      // 加载该对话
      this.$store.dispatch('agent/loadConversation', row.id)
      if (sceneKey !== this.$store.state.agent.currentScene) {
        this.$store.commit('agent/SET_CURRENT_SCENE', sceneKey)
      }
    },

    /** 单条删除 */
    handleDelete(row) {
      this.$confirm('确定删除该对话？删除后不可恢复。', '提示', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(() => {
        this.$store.dispatch('agent/deleteConversation', row.id).then(() => {
          this.$message.success('对话已删除')
          this.fetchData()
        }).catch(() => {
          this.$message.error('删除失败')
        })
      }).catch(() => {})
    },

    /** 批量删除 */
    handleBatchDelete() {
      this.$confirm(`确定删除选中的 ${this.selectedIds.length} 条对话？`, '批量删除', {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        let failCount = 0
        for (const id of this.selectedIds) {
          try {
            await this.$store.dispatch('agent/deleteConversation', id)
          } catch (e) {
            failCount++
          }
        }
        if (failCount > 0) {
          this.$message.warning(`${failCount} 条对话删除失败`)
        } else {
          this.$message.success('批量删除完成')
        }
        this.selectedIds = []
        this.fetchData()
      }).catch(() => {})
    },

    /** 获取对话关联场景 */
    getConversationScene(convId) {
      return this.conversationScenes[convId] || null
    },

    /** 场景标签 */
    getSceneLabel(convId) {
      const key = this.conversationScenes[convId]
      if (!key) return ''
      const cfg = getSceneByKey(key)
      return cfg ? cfg.label : key
    },

    /** 场景颜色 */
    getSceneColor(convId) {
      const key = this.conversationScenes[convId]
      if (!key) return '#909399'
      const cfg = getSceneByKey(key)
      return cfg ? cfg.color : '#909399'
    },

    /** 格式化时间 */
    formatTime(time) {
      if (!time) return '-'
      return dayjs(time).format('YYYY-MM-DD HH:mm')
    }
  }
}
</script>

<style scoped>
.conversation-history {
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
  padding: 20px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.filter-select {
  width: 140px;
}

.filter-date {
  width: 260px;
}

.filter-input {
  width: 200px;
}

.filter-actions {
  margin-left: auto;
}

.history-table {
  width: 100%;
}

.conv-title-link {
  color: #409EFF;
  cursor: pointer;
}

.conv-title-link:hover {
  text-decoration: underline;
}

.no-scene {
  color: #c0c4cc;
}

.delete-btn {
  color: #F56C6C !important;
}

.delete-btn:hover {
  color: #f78989 !important;
}

.pagination-wrap {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}
</style>
