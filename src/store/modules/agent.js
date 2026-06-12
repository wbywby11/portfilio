import {
  getConversations,
  getConversation,
  deleteConversation as deleteConversationApi,
  updateConversationTitle
} from '@/api/agent'

const state = {
  conversations: [],       // 对话列表
  currentConversationId: null, // 当前对话ID
  messages: [],            // 当前对话的消息列表
  messageTotal: 0,         // 消息总数
  messageHasMore: false,   // 是否有更多历史消息
  messagePage: 1,          // 当前已加载的页码
  isStreaming: false,       // 是否正在流式接收
  streamingContent: '',     // 流式累积内容
  loading: false,           // 加载状态
  currentScene: 'auto',    // 当前场景 key
  conversationScenes: {}   // conversationId -> sceneKey 映射
}

const mutations = {
  SET_CONVERSATIONS(state, conversations) {
    state.conversations = conversations
  },
  SET_CURRENT_CONVERSATION_ID(state, id) {
    state.currentConversationId = id
  },
  SET_MESSAGES(state, payload) {
    // 兼容旧的直接传数组的调用方式
    let msgs
    if (Array.isArray(payload)) {
      msgs = payload
      state.messageTotal = payload.length
      state.messageHasMore = false
      state.messagePage = 1
    } else {
      msgs = payload.messages || []
      state.messageTotal = payload.total || 0
      state.messageHasMore = payload.has_more || false
      state.messagePage = payload.page || 1
    }
    // 性能优化：冻结只读嵌套对象，避免 Vue 深层响应式追踪
    for (let i = 0; i < msgs.length; i++) {
      const m = msgs[i]
      if (m.lineageSummary && !Object.isFrozen(m.lineageSummary)) {
        Object.freeze(m.lineageSummary)
      }
    }
    state.messages = msgs
  },
  PREPEND_MESSAGES(state, { messages, total, has_more, page }) {
    // 向前追加历史消息（去重）
    const existingIds = new Set(state.messages.map(m => m.id))
    const newMessages = messages.filter(m => !existingIds.has(m.id))
    // 性能优化：冻结只读嵌套对象
    for (let i = 0; i < newMessages.length; i++) {
      const m = newMessages[i]
      if (m.lineageSummary && !Object.isFrozen(m.lineageSummary)) {
        Object.freeze(m.lineageSummary)
      }
    }
    state.messages = [...newMessages, ...state.messages]
    state.messageTotal = total
    state.messageHasMore = has_more
    state.messagePage = page
  },
  ADD_MESSAGE(state, message) {
    state.messages.push(message)
  },
  UPDATE_LAST_MESSAGE(state, payload) {
    if (state.messages.length > 0) {
      const last = state.messages[state.messages.length - 1]
      Object.assign(last, payload)
    }
  },
  SET_STREAMING(state, val) {
    state.isStreaming = val
  },
  SET_STREAMING_CONTENT(state, content) {
    state.streamingContent = content
  },
  APPEND_STREAMING_CONTENT(state, content) {
    state.streamingContent += content
  },
  SET_LOADING(state, val) {
    state.loading = val
  },
  REMOVE_CONVERSATION(state, id) {
    state.conversations = state.conversations.filter(c => c.id !== id)
  },
  SET_CURRENT_SCENE(state, sceneKey) {
    state.currentScene = sceneKey
  },
  SET_CONVERSATION_SCENE(state, { conversationId, sceneKey }) {
    state.conversationScenes = { ...state.conversationScenes, [conversationId]: sceneKey }
  }
}

const actions = {
  // 加载对话列表
  // options.silent=true 时不触发 loading 状态（用于发送消息后的静默刷新）
  async loadConversations({ commit }, options) {
    const silent = options && options.silent
    if (!silent) {
      commit('SET_LOADING', true)
    }
    try {
      const res = await getConversations()
      // 后端返回 { code, data: { items, total, ... } }
      const payload = res.data || res
      const list = Array.isArray(payload) ? payload
        : Array.isArray(payload.items) ? payload.items
        : Array.isArray(payload.conversations) ? payload.conversations
        : []
      console.log('[Store] loadConversations: 获取到', list.length, '条对话')
      commit('SET_CONVERSATIONS', list)
    } catch (e) {
      console.error('加载对话列表失败:', e)
    } finally {
      if (!silent) {
        commit('SET_LOADING', false)
      }
    }
  },

  // 加载指定对话的消息（支持分页）
  async loadConversation({ commit, state }, payload) {
    // 兼容旧调用方式：直接传 id 字符串
    const id = typeof payload === 'string' ? payload : payload.id
    const page = (typeof payload === 'object' && payload.page) || 1
    const prepend = (typeof payload === 'object' && payload.prepend) || false

    // 首次加载时阻止重复加载；追加历史时不阻止
    if (!prepend && state.loading) return

    if (!prepend) {
      commit('SET_LOADING', true)
      // 先切换对话ID并清空旧消息，防止残留
      commit('SET_CURRENT_CONVERSATION_ID', id)
      commit('SET_MESSAGES', [])
    }

    try {
      const res = await getConversation(id, { page, page_size: 20 })
      const data = res.data || res
      const messages = data.messages || []
      console.log('[Store] loadConversation:', id, 'page:', page, '获取到', messages.length, '条消息')
      // 确认仍然是同一个对话（防止快速切换竞态）
      if (state.currentConversationId === id) {
        if (prepend) {
          commit('PREPEND_MESSAGES', {
            messages,
            total: data.total,
            has_more: data.has_more,
            page: data.page || page
          })
        } else {
          commit('SET_MESSAGES', {
            messages,
            total: data.total,
            has_more: data.has_more,
            page: data.page || page
          })
        }
      }
      return data
    } catch (e) {
      console.error('加载对话消息失败:', e)
    } finally {
      if (!prepend) {
        commit('SET_LOADING', false)
      }
    }
  },

  // 加载更多历史消息
  async loadMoreMessages({ state, dispatch }) {
    if (!state.messageHasMore || !state.currentConversationId) return
    const nextPage = state.messagePage + 1
    await dispatch('loadConversation', {
      id: state.currentConversationId,
      page: nextPage,
      prepend: true
    })
  },

  // 创建新对话（清空当前状态）
  createConversation({ commit }) {
    commit('SET_CURRENT_CONVERSATION_ID', null)
    commit('SET_MESSAGES', [])
    commit('SET_STREAMING_CONTENT', '')
    commit('SET_STREAMING', false)
  },

  // 删除对话
  async deleteConversation({ commit, state: s }, id) {
    try {
      await deleteConversationApi(id)
      commit('REMOVE_CONVERSATION', id)
      if (s.currentConversationId === id) {
        commit('SET_CURRENT_CONVERSATION_ID', null)
        commit('SET_MESSAGES', [])
      }
    } catch (e) {
      console.error('删除对话失败:', e)
      throw e
    }
  },

  // 更新对话标题
  async renameConversation(_, { id, title }) {
    await updateConversationTitle(id, title)
  },

  // 追加流式内容
  appendStreamContent({ commit }, content) {
    commit('APPEND_STREAMING_CONTENT', content)
  },

  // 完成流式接收
  finishStreaming({ commit, state: s }) {
    if (s.streamingContent) {
      commit('UPDATE_LAST_MESSAGE', { content: s.streamingContent })
    }
    commit('SET_STREAMING', false)
    commit('SET_STREAMING_CONTENT', '')
  }
}

const getters = {
  sortedConversations: state => {
    return [...state.conversations].sort((a, b) => {
      return new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at)
    })
  }
}

export default {
  namespaced: true,
  state,
  mutations,
  actions,
  getters
}
