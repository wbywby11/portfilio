<template>
  <div class="agent-workspace">
    <!-- 左栏：对话列表 -->
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

    <!-- 右栏：场景信息 + 快捷问题 -->
    <div :class="['info-panel', { collapsed: infoPanelCollapsed }]">
      <div class="info-toggle" @click="infoPanelCollapsed = !infoPanelCollapsed">
        <i :class="infoPanelCollapsed ? 'el-icon-arrow-left' : 'el-icon-arrow-right'"></i>
      </div>
      <template v-if="!infoPanelCollapsed">
        <div class="info-section">
          <div class="info-section-title">
            <i :class="activeSceneConfig.icon" :style="{ color: activeSceneConfig.color }"></i>
            <span>{{ activeSceneConfig.label }}</span>
          </div>
          <p class="info-desc">{{ activeSceneConfig.description }}</p>
        </div>
        <div class="info-section" v-if="activeSceneConfig.quickQuestions && activeSceneConfig.quickQuestions.length">
          <div class="info-section-title">
            <i class="el-icon-chat-line-round"></i>
            <span>快捷问题</span>
          </div>
          <div class="quick-question-list">
            <div
              v-for="(q, idx) in activeSceneConfig.quickQuestions"
              :key="idx"
              class="quick-question-item"
              @click="handleQuickQuestion(q)"
            >{{ quickQuestionLabel(q) }}</div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
/**
 * 数智平台AI助手 — 工作区主页面
 * 三栏布局：左对话列表 + 中间场景选择&聊天 + 右场景信息
 */
import { mapState, mapGetters } from 'vuex'
import AgentChatPanel from '@/components/AgentChatPanel.vue'
import SceneSelector from '@/components/SceneSelector.vue'
import { AGENT_SCENES, getSceneByKey } from '@/config/agentScenes'
import { quickQuestionLabel } from '@/config/creditRatingQuickAddons'

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
      infoPanelCollapsed: false
    }
  },
  computed: {
    ...mapState('agent', ['currentConversationId', 'currentScene', 'conversationScenes']),
    ...mapGetters('agent', ['sortedConversations']),
    sidebarLoading() {
      return this.$store.state.agent.loading
    },
    /** 当前激活的场景配置对象 */
    activeSceneConfig() {
      return getSceneByKey(this.currentScene) || AGENT_SCENES[0]
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
    quickQuestionLabel(q) {
      return quickQuestionLabel(q)
    },

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

    /** 快捷问题：直接发送（与中间栏空状态快捷问题一致，须传入文案给 handleSend） */
    handleQuickQuestion(question) {
      const panel = this.$refs.chatPanel
      if (!panel || !question) return
      const inputRef = panel.$refs.chatInput
      const label = quickQuestionLabel(question)
      if (inputRef && typeof inputRef.setText === 'function') {
        inputRef.setText(label)
      }
      panel.handleSend(question)
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
  font-size: 11px;
  padding: 0 4px;
  height: 18px;
  line-height: 18px;
  border: none;
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
}

.chat-panel-wrapper {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ===== 右侧信息面板 ===== */
.info-panel {
  width: 240px;
  min-width: 240px;
  border-left: 1px solid #ebeef5;
  background: #fafbfc;
  display: flex;
  flex-direction: column;
  position: relative;
  transition: width 0.25s ease, min-width 0.25s ease;
  overflow: hidden;
}

.info-panel.collapsed {
  width: 32px;
  min-width: 32px;
}

.info-toggle {
  position: absolute;
  top: 12px;
  left: 8px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #909399;
  font-size: 14px;
  z-index: 1;
  border-radius: 50%;
  transition: background 0.2s;
}

.info-toggle:hover {
  background: #ebeef5;
  color: #606266;
}

.info-panel.collapsed .info-toggle {
  left: 6px;
}

.info-section {
  padding: 16px;
  border-bottom: 1px solid #ebeef5;
}

.info-panel.collapsed .info-section {
  display: none;
}

.info-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.info-section-title i {
  font-size: 16px;
}

.info-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin: 0;
}

.quick-question-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quick-question-item {
  font-size: 13px;
  color: #409EFF;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 4px;
  background: #ecf5ff;
  line-height: 1.4;
  transition: background 0.2s;
}

.quick-question-item:hover {
  background: #d9ecff;
}
</style>
