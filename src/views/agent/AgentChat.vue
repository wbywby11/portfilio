<template>
  <div class="agent-chat-page">
    <!-- 左侧：对话列表 -->
    <div class="sidebar-panel">
      <div class="sidebar-header">
        <el-button
          type="primary"
          icon="el-icon-plus"
          size="small"
          class="new-chat-btn"
          @click="handleNewChat"
        >新建对话</el-button>
      </div>

      <div class="conversation-list" v-loading="sidebarLoading">
        <div
          v-for="conv in sortedConversations"
          :key="conv.id"
          :class="['conversation-item', { active: conv.id === currentConversationId }]"
          @click="handleSelectConversation(conv)"
        >
          <div class="conv-info">
            <div class="conv-title" :title="conv.title || '新对话'">
              {{ conv.title || '新对话' }}
            </div>
            <div class="conv-time">{{ formatTime(conv.updated_at || conv.created_at) }}</div>
          </div>
          <el-button
            class="conv-delete-btn"
            type="text"
            icon="el-icon-delete"
            size="mini"
            @click.stop="handleDeleteConversation(conv)"
          ></el-button>
        </div>

        <!-- 空状态 -->
        <div v-if="!sortedConversations.length && !sidebarLoading" class="no-conversations">
          <i class="el-icon-chat-line-square" style="font-size: 32px; color: #c0c4cc;"></i>
          <p>暂无对话记录</p>
        </div>
      </div>
    </div>

    <!-- 右侧：对话面板 -->
    <div class="chat-main">
      <AgentChatPanel
        :conversation-id="currentConversationId"
        @conversation-created="onConversationCreated"
      />
    </div>
  </div>
</template>

<script>
/**
 * 数智平台AI助手对话主页面
 * 左右分栏：左侧对话历史列表 + 右侧对话交互区
 */
import { mapState, mapGetters } from 'vuex'
import AgentChatPanel from '@/components/AgentChatPanel.vue'

export default {
  name: 'AgentChat',
  components: { AgentChatPanel },
  computed: {
    ...mapState('agent', ['currentConversationId']),
    ...mapGetters('agent', ['sortedConversations']),
    sidebarLoading() {
      return this.$store.state.agent.loading
    }
  },
  created() {
    // 页面加载时拉取对话列表
    this.$store.dispatch('agent/loadConversations')
  },
  methods: {
    /** 新建对话：清空当前状态 */
    handleNewChat() {
      this.$store.dispatch('agent/createConversation')
    },

    /** 切换到指定对话 */
    handleSelectConversation(conv) {
      console.log('[AgentChat] 选中对话:', conv.id, conv.title)
      if (conv.id === this.currentConversationId) return
      this.$store.dispatch('agent/loadConversation', conv.id)
    },

    /** 删除对话 */
    handleDeleteConversation(conv) {
      this.$confirm('确定删除该对话？删除后不可恢复。', '提示', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(() => {
        this.$store.dispatch('agent/deleteConversation', conv.id).then(() => {
          this.$message.success('对话已删除')
        }).catch(() => {
          this.$message.error('删除失败，请稍后重试')
        })
      }).catch(() => {})
    },

    /** SSE 过程中后端返回新 conversation_id 时回调 */
    onConversationCreated(id) {
      // 重新加载对话列表以显示新对话
      this.$store.dispatch('agent/loadConversations')
    },

    /**
     * 格式化时间显示
     * @param {string} dateStr ISO 时间字符串
     * @returns {string} 友好的时间文本
     */
    formatTime(dateStr) {
      if (!dateStr) return ''
      const d = new Date(dateStr)
      const now = new Date()
      const diffMs = now - d
      const diffMin = Math.floor(diffMs / 60000)
      if (diffMin < 1) return '刚刚'
      if (diffMin < 60) return `${diffMin}分钟前`
      const diffHour = Math.floor(diffMin / 60)
      if (diffHour < 24) return `${diffHour}小时前`
      // 超过 24h 显示日期
      const month = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      const hour = String(d.getHours()).padStart(2, '0')
      const min = String(d.getMinutes()).padStart(2, '0')
      return `${month}-${day} ${hour}:${min}`
    }
  }
}
</script>

<style scoped>
.agent-chat-page {
  display: flex;
  height: calc(100vh - 100px);
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

/* ===== 左侧对话列表 ===== */
.sidebar-panel {
  width: 280px;
  min-width: 280px;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  background: #fafbfc;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #ebeef5;
}

.new-chat-btn {
  width: 100%;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  padding: 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 2px;
}

.conversation-item:hover {
  background: #edf2f7;
}

.conversation-item.active {
  background: #ecf5ff;
  border-left: 3px solid #409EFF;
  padding-left: 9px;
}

.conv-info {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 14px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

.conv-time {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.conv-delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
  color: #909399;
  padding: 4px;
}

.conversation-item:hover .conv-delete-btn {
  opacity: 1;
}

.conv-delete-btn:hover {
  color: #F56C6C;
}

.no-conversations {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding-top: 60px;
  color: #c0c4cc;
  font-size: 13px;
}

.no-conversations p {
  margin-top: 8px;
}

/* ===== 右侧对话区 ===== */
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
</style>
