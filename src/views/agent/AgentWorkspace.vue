<template>
  <div class="agent-workspace">
    <!-- 左栏：对话列表（可折叠） -->
    <div :class="['sidebar-panel', { collapsed: sidebarCollapsed }]">
      <div class="sidebar-header">
        <el-button
          v-show="!sidebarCollapsed"
          icon="el-icon-plus"
          size="small"
          class="new-chat-btn"
          @click="handleNewChat"
        >新建对话</el-button>
        <button
          class="collapse-btn"
          :title="sidebarCollapsed ? '展开对话列表' : '收起对话列表'"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <i :class="sidebarCollapsed ? 'el-icon-s-unfold' : 'el-icon-s-fold'"></i>
        </button>
      </div>

      <div v-show="!sidebarCollapsed" class="conversation-list" v-loading="sidebarLoading">
        <div v-for="group in groupedConversations" :key="group.label" class="conv-group">
          <div class="conv-group-label">{{ group.label }}</div>
          <div
            v-for="conv in group.items"
            :key="conv.id"
            :class="['conversation-item', { active: conv.id === currentConversationId }]"
            @click="handleSelectConversation(conv)"
          >
            <div class="conv-info">
              <div class="conv-top-row">
                <span class="conv-title" :title="conv.title || '新对话'">
                  {{ conv.title || '新对话' }}
                </span>
                <el-tag
                  v-if="getConversationScene(conv.id)"
                  size="mini"
                  :color="getSceneColor(conv.id)"
                  effect="dark"
                  class="conv-scene-tag"
                >{{ getSceneLabel(conv.id) }}</el-tag>
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
        </div>

        <!-- 空状态 -->
        <div v-if="!sortedConversations.length && !sidebarLoading" class="no-conversations">
          <i class="el-icon-chat-line-square" style="font-size: 32px; color: #c0c4cc;"></i>
          <p>暂无对话记录</p>
        </div>
      </div>
    </div>

    <!-- 中间栏：场景选择 + 聊天面板 -->
    <div class="workspace-main">
      <SceneSelector
        :scenes="scenes"
        :current-scene="currentScene"
        @change="handleSceneChange"
      />
      <div class="chat-panel-wrapper">
        <AgentChatPanel
          ref="chatPanel"
          :conversation-id="currentConversationId"
          @conversation-created="onConversationCreated"
        />
      </div>
    </div>
  </div>
</template>

<script>
/**
 * 数智平台AI助手 — 工作区主页面
 * 两栏布局：左对话列表 + 中间场景选择&聊天
 */
import { mapState, mapGetters } from 'vuex'
import AgentChatPanel from '@/components/AgentChatPanel.vue'
import SceneSelector from '@/components/SceneSelector.vue'
import { AGENT_SCENES, getSceneByKey } from '@/config/agentScenes'

export default {
  name: 'AgentWorkspace',
  components: { AgentChatPanel, SceneSelector },
  props: {
    /** 路由参数：场景 key，来自 /agent/chat/:scene */
    scene: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      scenes: AGENT_SCENES,
      sidebarCollapsed: false
    }
  },
  computed: {
    ...mapState('agent', ['currentConversationId', 'currentScene', 'conversationScenes']),
    ...mapGetters('agent', ['sortedConversations']),
    sidebarLoading() {
      return this.$store.state.agent.loading
    },
    /** 对话按时间分组（今天/昨天/更早），仅用于展示 */
    groupedConversations() {
      const groups = [
        { label: '今天', items: [] },
        { label: '昨天', items: [] },
        { label: '更早', items: [] }
      ]
      const now = new Date()
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
      const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000
      for (const conv of this.sortedConversations) {
        const t = new Date(conv.updated_at || conv.created_at).getTime()
        if (Number.isNaN(t)) {
          groups[2].items.push(conv)
        } else if (t >= startOfToday) {
          groups[0].items.push(conv)
        } else if (t >= startOfYesterday) {
          groups[1].items.push(conv)
        } else {
          groups[2].items.push(conv)
        }
      }
      return groups.filter(g => g.items.length)
    }
  },
  watch: {
    /** 路由 :scene 参数变化时同步到 store */
    scene: {
      handler(newScene) {
        if (newScene && newScene !== this.currentScene) {
          this.$store.commit('agent/SET_CURRENT_SCENE', newScene)
        }
      },
      immediate: true
    }
  },
  created() {
    this.$store.dispatch('agent/loadConversations')
    // 如果有路由 scene 参数，同步到 store
    if (this.scene && this.scene !== this.currentScene) {
      this.$store.commit('agent/SET_CURRENT_SCENE', this.scene)
    }
  },
  methods: {
    /** 切换场景：更新 store，不清空对话 */
    handleSceneChange(sceneKey) {
      this.$store.commit('agent/SET_CURRENT_SCENE', sceneKey)
      // 如果当前有对话，关联场景
      if (this.currentConversationId) {
        this.$store.commit('agent/SET_CONVERSATION_SCENE', {
          conversationId: this.currentConversationId,
          sceneKey
        })
      }
    },

    /** 新建对话 */
    handleNewChat() {
      if (this.$refs.chatPanel && typeof this.$refs.chatPanel.cancelStreaming === 'function') {
        this.$refs.chatPanel.cancelStreaming()
      }
      this.$store.dispatch('agent/createConversation')
    },

    /** 切换到指定对话 */
    handleSelectConversation(conv) {
      if (conv.id === this.currentConversationId) return
      if (this.$refs.chatPanel && typeof this.$refs.chatPanel.cancelStreaming === 'function') {
        this.$refs.chatPanel.cancelStreaming()
      }
      this.$store.dispatch('agent/loadConversation', conv.id)
      // 恢复该对话关联的场景
      const sceneKey = this.conversationScenes[conv.id]
      if (sceneKey && sceneKey !== this.currentScene) {
        this.$store.commit('agent/SET_CURRENT_SCENE', sceneKey)
      }
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

    /** SSE 回调：后端返回 conversation_id 时 */
    onConversationCreated(id) {
      // 关联场景
      if (this.currentScene) {
        this.$store.commit('agent/SET_CONVERSATION_SCENE', {
          conversationId: id,
          sceneKey: this.currentScene
        })
      }
      this.$store.dispatch('agent/loadConversations', { silent: true })
    },

    /** 获取对话关联场景的配置对象 */
    getConversationScene(convId) {
      return this.conversationScenes[convId] || null
    },

    /** 获取对话场景标签 */
    getSceneLabel(convId) {
      const key = this.conversationScenes[convId]
      if (!key) return ''
      const cfg = getSceneByKey(key)
      return cfg ? cfg.label : key
    },

    /** 获取对话场景颜色 */
    getSceneColor(convId) {
      const key = this.conversationScenes[convId]
      if (!key) return '#909399'
      const cfg = getSceneByKey(key)
      return cfg ? cfg.color : '#909399'
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
.agent-workspace {
  display: flex;
  height: calc(100vh - 100px);
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

/* ===== 左侧对话列表（可折叠） ===== */
.sidebar-panel {
  width: 280px;
  min-width: 280px;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  background: #fafbfc;
  transition: width 0.25s ease, min-width 0.25s ease;
}

.sidebar-panel.collapsed {
  width: 48px;
  min-width: 48px;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  gap: 8px;
}

.sidebar-panel.collapsed .sidebar-header {
  padding: 16px 8px;
  justify-content: center;
}

.collapse-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #606266;
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.2s, color 0.2s;
}

.collapse-btn:hover {
  background: #eef1f6;
  color: #409eff;
}

.new-chat-btn {
  width: 100%;
  border: 1px dashed #c3d0e5;
  background: #fff;
  color: #409eff;
  border-radius: 10px;
  transition: all 0.2s ease;
}

.new-chat-btn:hover,
.new-chat-btn:focus {
  border-color: #409eff;
  background: #f0f6ff;
  color: #409eff;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

/* 侧栏自定义滚动条 */
.conversation-list::-webkit-scrollbar {
  width: 5px;
}
.conversation-list::-webkit-scrollbar-track {
  background: transparent;
}
.conversation-list::-webkit-scrollbar-thumb {
  background: #dcdfe6;
  border-radius: 3px;
}
.conversation-list::-webkit-scrollbar-thumb:hover {
  background: #c0c4cc;
}

.conv-group-label {
  font-size: 11px;
  font-weight: 600;
  color: #98a2b3;
  padding: 10px 12px 4px;
  letter-spacing: 0.5px;
}

.conv-group:first-child .conv-group-label {
  padding-top: 4px;
}

.conversation-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s ease;
  margin-bottom: 2px;
}

.conversation-item:hover {
  background: #f0f2f5;
}

.conversation-item.active {
  background: #e8f1ff;
  box-shadow: inset 3px 0 0 0 #409eff;
}

.conv-info {
  flex: 1;
  min-width: 0;
}

.conv-top-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.conv-title {
  font-size: 14px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
  flex: 1;
  min-width: 0;
}

.conv-scene-tag {
  flex-shrink: 0;
  font-size: 10px;
  padding: 0 4px;
  height: 16px;
  line-height: 16px;
  border: none;
  opacity: 0.7;
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

/* ===== 中间主区域 ===== */
.workspace-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}

.chat-panel-wrapper {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
