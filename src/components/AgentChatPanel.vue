<template>
  <div class="chat-panel">
    <!-- 消息列表 -->
    <div class="message-list" ref="messageList">
      <!-- 空状态 -->
      <ChatEmptyState
        v-if="!messages.length && !showStreamingUI"
        :welcomeTitle="welcomeTitle"
        :welcomeDescription="welcomeDescription"
        :quickQuestions="sceneQuickQuestions"
        @quick-question="handleQuickQuestion"
        @select-template="handleTemplateSelect"
      />

      <!-- 消息 -->
      <div
        v-for="(msg, idx) in displayMessages"
        :key="idx"
        :class="['message-item', msg.role === 'user' ? 'message-user' : 'message-assistant']"
      >
        <!-- 头像 -->
        <div class="message-avatar">
          <el-avatar
            :size="36"
            :icon="msg.role === 'user' ? 'el-icon-user-solid' : 'el-icon-s-opportunity'"
            :style="{ background: msg.role === 'user' ? '#409EFF' : '#67C23A' }"
          ></el-avatar>
        </div>
        <!-- 内容 -->
        <div class="message-content-wrap" :class="{ 'has-charts': getMessageCharts(msg).length > 0 || getMessageDataTables(msg).length > 0 }">
          <div class="message-role">{{ msg.role === 'user' ? '我' : '数智平台AI助手' }}</div>
          <div class="message-bubble" :class="msg.role">
            <!-- 用户消息 -->
            <div v-if="msg.role === 'user'" class="message-text">{{ msg.content }}</div>
            <!-- AI 消息 Markdown 渲染 -->
            <div
              v-else
              class="message-text markdown-body"
              v-html="renderMarkdown(msg.content || '')"
            ></div>
          </div>
          <!-- 数据表格 -->
          <ChatDataTable v-for="(table, tIdx) in getMessageDataTables(msg)" :key="'table_' + idx + '_' + tIdx"
            :records="table.records" :summary="table.summary" :recordCount="table.recordCount"
            :dataShape="table.dataShape" :stepKey="table.toolName" />
          <!-- 数据导入卡片 -->
          <DataImportCards
            v-for="(card, cIdx) in getMessageImportCards(msg)"
            :key="'import_card_' + idx + '_' + cIdx"
            :card-type="card.cardType"
            :data="card.data"
          />
          <!-- 图表区域 -->
          <ChatChartRenderer
            v-if="getMessageCharts(msg).length > 0"
            :charts="getMessageCharts(msg)"
            :refPrefix="'msg_chart_' + idx"
            :key="'chart_renderer_' + idx"
          />
        </div>
      </div>

      <!-- 计划进度展示 -->
      <PlanProgress :plan="currentPlan" />

      <!-- 流式输出中（仅当前查看的会话与流归属一致时显示） -->
      <div v-if="showStreamingUI && (streamingContent || streamingCharts.length > 0 || streamingTables.length > 0)" class="message-item message-assistant">
        <div class="message-avatar">
          <el-avatar :size="36" icon="el-icon-s-opportunity" style="background: #67C23A"></el-avatar>
        </div>
        <div class="message-content-wrap" :class="{ 'has-charts': streamingCharts.length > 0 || streamingTables.length > 0 }">
          <div class="message-role">数智平台AI助手</div>
          <div class="message-bubble assistant">
            <div class="message-text markdown-body" v-html="renderMarkdown(streamingContent)"></div>
          </div>
          <!-- 流式表格 -->
          <ChatDataTable v-for="(table, tIdx) in streamingTables" :key="'stream_table_' + tIdx"
            :records="table.records" :summary="table.summary" :recordCount="table.recordCount"
            :dataShape="table.dataShape" :stepKey="table.toolName" />
          <!-- 流式数据导入卡片 -->
          <DataImportCards
            v-for="(card, cIdx) in streamingImportCards"
            :key="'stream_import_card_' + cIdx"
            :card-type="card.cardType"
            :data="card.data"
          />
          <!-- 流式图表区域 -->
          <ChatChartRenderer
            v-if="streamingCharts.length > 0"
            :charts="streamingCharts"
            refPrefix="stream_chart"
            ref="streamChartRenderer"
          />
        </div>
      </div>

      <!-- 工具调用中的处理指示 -->
      <div v-if="showStreamingUI && isInToolPhase" class="message-item message-assistant">
        <div class="message-avatar">
          <el-avatar :size="36" icon="el-icon-s-opportunity" style="background: #67C23A"></el-avatar>
        </div>
        <div class="message-content-wrap">
          <div class="message-role">数智平台AI助手</div>
          <div class="message-bubble assistant">
            <ChatToolProgress :completedSteps="completedToolSteps" :currentLabel="currentToolLabel" />
          </div>
        </div>
      </div>

      <!-- 加载指示（等待首次响应） -->
      <div v-if="showStreamingUI && !streamingContent && streamingCharts.length === 0 && streamingTables.length === 0 && !isInToolPhase" class="message-item message-assistant">
        <div class="message-avatar">
          <el-avatar :size="36" icon="el-icon-s-opportunity" style="background: #67C23A"></el-avatar>
        </div>
        <div class="message-content-wrap">
          <div class="message-role">数智平台AI助手</div>
          <div class="message-bubble assistant">
            <span class="typing-indicator">
              <span></span><span></span><span></span>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据更新模板快捷栏 -->
    <DataUpdateTemplates
      v-if="showTemplates"
      @select-template="handleTemplateSelect"
    />

    <!-- 输入区域 -->
    <ChatInputBox :isLoading="isStreaming" @send="handleSend" ref="chatInput" />
  </div>
</template>

<script>
import { sendMessageStream } from '@/api/agent'
import { getSceneByKey, AGENT_SCENES } from '@/config/agentScenes'
import { quickQuestionLabel } from '@/config/creditRatingQuickAddons'
import { renderMarkdown, getMessageCharts, getMessageDataTables, parseToolResult, throttle } from './chatUtils'
import PlanProgress from './PlanProgress.vue'
import ChatEmptyState from './ChatEmptyState.vue'
import ChatChartRenderer from './ChatChartRenderer.vue'
import ChatDataTable from './ChatDataTable.vue'
import ChatToolProgress from './ChatToolProgress.vue'
import ChatInputBox from './ChatInputBox.vue'
import DataUpdateTemplates from './DataUpdateTemplates.vue'
import DataImportCards from './DataImportCards.vue'

export default {
  name: 'AgentChatPanel',
  components: { PlanProgress, ChatEmptyState, ChatChartRenderer, ChatDataTable, ChatToolProgress, ChatInputBox, DataUpdateTemplates, DataImportCards },
  props: {
    conversationId: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      showTemplates: true,
      streamingContent: '',
      streamingToolCalls: [],
      streamingCharts: [],
      isStreaming: false,
      pendingText: '',
      isInToolPhase: false,
      toolNameMap: {
        'query_assets': '正在查询资产信息...',
        'recommend_strategy': '正在分析资产特征并推荐策略...',
        'compare_strategies': '正在执行多策略对比回测...',
        'execute_backtest': '正在执行回测...',
        'calculate_performance_metrics': '正在计算绩效指标...',
        'calculate_correlation': '正在计算相关性矩阵...',
        'get_timeseries': '正在获取时序数据...',
        'create_strategy_model': '正在创建策略模型...',
        'list_strategy_types': '正在获取策略类型列表...',
        'compute_weights': '正在计算策略目标权重...',
        'create_portfolio': '正在创建模拟组合...',
        'get_portfolio': '正在获取组合持仓...',
        'get_rebalance_history': '正在获取调仓历史...',
        'execute_rebalance': '正在执行组合调仓...',
        'list_benchmarks': '正在查询基准列表...',
        'data_query': '正在查询数据...',
        'data_analyze': '正在进行数据分析...',
        'data_transform': '正在加工数据...',
        'data_visualize': '正在生成图表...',
        'data_template': '正在处理分析模板...',
        'query_asset_prices': '正在查询资产价格...',
        'data_import': '正在处理数据导入...'
      },
      completedToolSteps: [],
      currentToolLabel: '',
      currentPlan: null,
      /** 本次发送开始前 store 中的 conversationId */
      _sendSnapshotConvId: undefined,
      /** 发送时是否为「尚无会话 id」的新建对话 */
      _wasNullConvAtSend: false,
      /** 当前 SSE 请求归属的会话 id（与左侧当前选中会话严格对应，防串话） */
      _sseOwnerConversationId: null,
      _streamAbortController: null,
      /** 已为切换会话等行为主动中止 SSE，完成后禁止把助手消息写入 store */
      _streamAborted: false
    }
  },
  computed: {
    currentSceneConfig() {
      const sceneKey = this.$store.state.agent.currentScene || 'auto'
      return getSceneByKey(sceneKey) || AGENT_SCENES[0]
    },
    welcomeTitle() {
      const scene = this.currentSceneConfig
      if (scene.key === 'auto') return '你好，我是数智平台AI助手'
      return `你好，我是数智平台AI助手 - ${scene.label}`
    },
    welcomeDescription() {
      const scene = this.currentSceneConfig
      if (scene.key === 'auto') {
        return '我可以帮你进行数据资产管理、数据查询分析、数据加工和可视化。选择一个场景或直接告诉我你的需求。'
      }
      return scene.description
    },
    sceneQuickQuestions() {
      return this.currentSceneConfig.quickQuestions || []
    },
    messages() {
      return this.$store.state.agent.messages
    },
    displayMessages() {
      return this.messages
    },
    currentConvId() {
      return this.$store.state.agent.currentConversationId
    },
    /** 流式内容仅在本会话内进行，防止串到其他历史对话 */
    showStreamingUI() {
      if (!this.isStreaming) return false
      const owner = this._sseOwnerConversationId
      const cur = this.currentConvId
      if (owner != null) return owner === cur
      return this._sendSnapshotConvId === cur
    },
    streamingTables() {
      return getMessageDataTables({ tool_calls: this.streamingToolCalls })
    },
    streamingImportCards() {
      return this.getMessageImportCards({ tool_calls: this.streamingToolCalls })
    }
  },
  watch: {
    conversationId(newId, oldId) {
      // 新建对话初始化（null/undefined -> 新ID）时不应中止流
      if (oldId == null) {
        if (newId && this.$store.state.agent.currentConversationId !== newId) {
          this.$store.dispatch('agent/loadConversation', newId)
        }
        return
      }
      // 用户主动切换到不同对话时才中止
      if (newId && newId !== oldId) {
        this.cancelStreaming()
        this.currentPlan = null
        if (this.$store.state.agent.currentConversationId !== newId) {
          this.$store.dispatch('agent/loadConversation', newId)
        }
      }
    },
    messages: {
      handler() {
        this.$nextTick(() => {
          this.scrollToBottom()
          this.addTableExportButtons()
        })
      },
      deep: true
    },
    streamingContent() {
      this.$nextTick(() => this.scrollToBottom())
    },
    streamingCharts: {
      handler() {
        this.$nextTick(() => this.scrollToBottom())
      },
      deep: true
    },
    currentConvId: {
      handler(nid) {
        if (!this.isStreaming) return
        const owner = this._sseOwnerConversationId
        if (owner != null) {
          if (nid !== owner) this.cancelStreaming()
          return
        }
        if (this._sendSnapshotConvId != null && nid !== this._sendSnapshotConvId) {
          this.cancelStreaming()
          return
        }
        // 新对话场景：nid从null变为后端返回的conversation_id，是正常流程，不应中止
        if (this._wasNullConvAtSend && nid != null) {
          return
        }
      }
    }
  },
  created() {
    this._throttledScroll = throttle(() => {
      const el = this.$refs.messageList
      if (el) el.scrollTop = el.scrollHeight
    }, 80)
  },
  mounted() {},
  beforeDestroy() {
    this.cancelStreaming()
  },
  methods: {
    /**
     * 中止当前流式请求：切换会话或组件销毁时调用，避免回复写入错误的对话。
     */
    cancelStreaming() {
      this._streamAborted = true
      if (this._streamAbortController) {
        try {
          this._streamAbortController.abort()
        } catch (e) { /* noop */ }
        this._streamAbortController = null
      }
      this.isStreaming = false
      this.streamingContent = ''
      this.streamingToolCalls = []
      this.streamingCharts = []
      this.pendingText = ''
      this.isInToolPhase = false
      this.completedToolSteps = []
      this.currentToolLabel = ''
      this._sseOwnerConversationId = null
      this._sendSnapshotConvId = undefined
      this._wasNullConvAtSend = false
    },

    renderMarkdown,
    getMessageCharts,
    getMessageDataTables,

    /**
     * 判断 data_import 工具返回结果的卡片类型
     */
    getImportCardType(toolResult) {
      if (!toolResult) return null
      if (toolResult.templates) return 'templates'
      if (toolResult.valid !== undefined) return 'validate'
      if (toolResult.sample_data) return 'preview'
      if (toolResult.stats || toolResult.inserted_count !== undefined) return 'import'
      return null
    },

    /**
     * 从消息的 tool_calls 中提取 data_import 工具的结构化结果
     * @param {Object} msg 消息对象
     * @returns {Array<{cardType, data}>}
     */
    getMessageImportCards(msg) {
      if (!msg.tool_calls || !msg.tool_calls.length) return []
      const cards = []
      for (const tool of msg.tool_calls) {
        if (tool.name !== 'data_import') continue
        const result = parseToolResult(tool)
        if (!result) continue
        const cardType = this.getImportCardType(result)
        if (cardType) {
          cards.push({ cardType, data: result })
        }
      }
      return cards
    },

    scrollToBottom() {
      this._throttledScroll()
    },

    /**
     * 在消息渲染后为 Markdown 表格添加导出按钮
     */
    addTableExportButtons() {
      this.$nextTick(() => {
        const tables = this.$el.querySelectorAll('.md-table')
        tables.forEach(table => {
          // 避免重复添加
          if (table.parentNode && table.parentNode.classList.contains('table-wrapper')) return

          const wrapper = document.createElement('div')
          wrapper.className = 'table-wrapper'

          const actions = document.createElement('div')
          actions.className = 'table-actions'
          actions.innerHTML = '<button class="table-export-btn"><i class="el-icon-download"></i> 导出</button>'
          actions.querySelector('button').addEventListener('click', () => this.exportTable(table))

          table.parentNode.insertBefore(wrapper, table)
          wrapper.appendChild(actions)
          wrapper.appendChild(table)
        })
      })
    },

    /**
     * 将 HTML 表格导出为 CSV 文件并下载
     */
    exportTable(tableEl) {
      const rows = tableEl.querySelectorAll('tr')
      const csvData = []
      rows.forEach(row => {
        const cells = row.querySelectorAll('th, td')
        const rowData = Array.from(cells).map(cell => {
          let text = cell.textContent.trim()
          if (text.includes(',') || text.includes('"') || text.includes('\n')) {
            text = '"' + text.replace(/"/g, '""') + '"'
          }
          return text
        })
        csvData.push(rowData.join(','))
      })

      const csvContent = '\uFEFF' + csvData.join('\n') // BOM for Excel 中文兼容
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `table_export_${Date.now()}.csv`
      a.click()
      URL.revokeObjectURL(url)

      this.$message.success('表格已导出')
    },


    handleQuickQuestion(q) {
      const label = quickQuestionLabel(q)
      if (this.$refs.chatInput) {
        this.$refs.chatInput.setText(label)
      }
      this.handleSend(q)
    },

    /**
     * 处理模板选择：填充提示文本，需要文件时触发文件选择
     */
    handleTemplateSelect(tpl) {
      // 如果模板需要文件上传，触发文件选择
      if (tpl.acceptFormats) {
        this.$refs.chatInput.triggerFileSelect()
      }
      // 将模板的 prompt 填入输入框
      this.$refs.chatInput.setText(tpl.prompt)
      // 对于不需要文件的模板，直接发送
      if (!tpl.acceptFormats) {
        this.handleSend({ message: tpl.prompt, attachments: [] })
      }
    },

    /**
     * 发送消息 —— 使用 SSE 流式接收 AI 回复
     * @param {string|{message:string,attachments?:string[],system_turn_addon?:string}} textOrPayload
     */
    async handleSend(textOrPayload) {
      let msg = null
      let systemTurnAddon = undefined
      let attachmentIds = []
      if (typeof textOrPayload === 'string') {
        msg = textOrPayload.trim() || null
      } else if (textOrPayload && typeof textOrPayload === 'object') {
        msg = textOrPayload.message != null
          ? String(textOrPayload.message).trim() || null
          : null
        if (textOrPayload.system_turn_addon) {
          systemTurnAddon = String(textOrPayload.system_turn_addon)
        }
        if (Array.isArray(textOrPayload.attachments)) {
          attachmentIds = textOrPayload.attachments
        }
      }

      // 当有附件但无文本时，给一个默认 message，避免传 null 导致后端 422
      if (!msg && attachmentIds.length) {
        msg = '请处理上传的文件'
      }
      if ((!msg && !attachmentIds.length) || this.isStreaming) return

      this.isStreaming = true
      this._sendSnapshotConvId = this.currentConvId
      this._wasNullConvAtSend = !this.currentConvId
      this._sseOwnerConversationId = this.currentConvId || null
      this._streamAborted = false
      this._streamAbortController = new AbortController()

      // 添加用户消息到 store
      this.$store.commit('agent/ADD_MESSAGE', {
        role: 'user',
        content: msg,
        created_at: new Date().toISOString()
      })
      this.streamingContent = ''
      this.streamingToolCalls = []
      this.streamingCharts = []
      this.pendingText = ''
      this.isInToolPhase = false
      this.currentPlan = null

      const conversationId = this.currentConvId || this.conversationId

      try {
        const sceneKey = this.$store.state.agent.currentScene || 'auto'
        const scene = sceneKey === 'auto' ? null : sceneKey

        const payload = {
          message: msg,
          conversation_id: conversationId,
          scene
        }
        if (systemTurnAddon) {
          payload.system_turn_addon = systemTurnAddon
        }
        if (attachmentIds.length) {
          payload.attachments = attachmentIds
        }
        const response = await sendMessageStream(
          payload,
          { signal: this._streamAbortController.signal }
        )
        // sendMessageStream 已验证 response.ok 和 response.body
        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n\n')
          buffer = parts.pop()

          for (const part of parts) {
            if (part.trim()) {
              this.processSSEEvent(part)
            }
          }
        }

        if (buffer.trim()) {
          this.processSSEEvent(buffer)
        }

        if (this.pendingText && !this.streamingContent) {
          this.streamingContent = this.pendingText
          this.pendingText = ''
        }

        const owner = this._sseOwnerConversationId
        const cur = this.currentConvId
        // 对于新建对话，owner 可能来不及更新，但如果有内容且流未中止，也应该保存
        const hasContent = this.streamingContent || this.streamingToolCalls.length
        const ownerMatch = owner != null && cur === owner
        const newConvFallback = this._wasNullConvAtSend && cur != null && owner == null

        const canCommit =
          !this._streamAborted &&
          hasContent &&
          (ownerMatch || newConvFallback)

        if (canCommit) {
          const aiMsg = {
            role: 'assistant',
            content: this.streamingContent || '',
            created_at: new Date().toISOString()
          }
          if (this.streamingToolCalls.length) {
            aiMsg.tool_calls = JSON.parse(JSON.stringify(this.streamingToolCalls))
          }
          this.$store.commit('agent/ADD_MESSAGE', aiMsg)
        }

        if (!this._streamAborted) {
          this.$store.dispatch('agent/loadConversations')
        }
      } catch (err) {
        if (err.name === 'AbortError' || (err.message && String(err.message).includes('abort'))) {
          return
        }
        console.error('流式对话错误:', err)
        this.$message.error('AI 回复失败: ' + (err.message || '未知错误'))
        const owner = this._sseOwnerConversationId
        const cur = this.currentConvId
        const sameConv = owner != null && cur === owner
        if (sameConv && !this.streamingContent && !this._streamAborted) {
          this.$store.commit('agent/ADD_MESSAGE', {
            role: 'assistant',
            content: '抱歉，请求出现错误，请稍后重试。',
            created_at: new Date().toISOString()
          })
        }
      } finally {
        this._streamAbortController = null
        this.isStreaming = false
        this.streamingContent = ''
        this.streamingToolCalls = []
        this.streamingCharts = []
        this.pendingText = ''
        this.isInToolPhase = false
        this._sendSnapshotConvId = undefined
        this._wasNullConvAtSend = false
        this._sseOwnerConversationId = null
      }
    },

    /**
     * 从流式工具调用中提取所有 charts
     */
    extractStreamingCharts() {
      let allCharts = []
      for (const tool of this.streamingToolCalls) {
        const result = parseToolResult(tool)
        if (result && Array.isArray(result.charts) && result.charts.length > 0) {
          allCharts = allCharts.concat(result.charts)
        }
      }
      // 按标题+类型去重，避免多次调用同一工具产生重复图表
      if (allCharts.length > 1) {
        const seen = new Set()
        allCharts = allCharts.filter(chart => {
          const key = (chart.title || '') + '::' + (chart.chart_type || '')
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
      }
      this.streamingCharts = [...allCharts]
    },

    /**
     * 解析单条 SSE 事件并更新流式状态
     */
    processSSEEvent(eventStr) {
      const lines = eventStr.split('\n')
      let eventType = ''
      let dataLines = []

      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim())
        }
      }

      const eventData = dataLines.join('\n')
      if (!eventData) return

      let data
      try {
        data = JSON.parse(eventData)
      } catch (parseErr) {
        console.warn('[SSE] JSON 解析失败:', parseErr.message, '原始数据长度:', eventData.length, '前100字符:', eventData.substring(0, 100))
        if (eventType === 'text_delta' || !eventType) {
          this.pendingText += eventData
        }
        return
      }

      switch (eventType) {
        case 'text_delta':
          this.pendingText += (data.content || data.text || data.delta || '')
          break

        case 'text_replace':
          // 后端标记本轮脑洞文字非用户可见，直接重置 pendingText
          this.pendingText = data.content || ''
          break

        case 'tool_start': {
          this.pendingText = ''
          this.isInToolPhase = true
          const startToolName = data.tool_name || data.name || ''
          if (this.currentToolLabel) {
            this.completedToolSteps.push(this.currentToolLabel)
          }
          this.currentToolLabel = this.toolNameMap[startToolName] || '正在执行工具...'
          this.streamingToolCalls.push({
            name: startToolName || '工具',
            arguments: data.arguments || data.input || null,
            status: 'running',
            result: null,
            error: null
          })
          break
        }

        case 'tool_result': {
          this.isInToolPhase = false
          this.pendingText = ''
          if (this.currentToolLabel) {
            this.completedToolSteps.push(this.currentToolLabel)
            this.currentToolLabel = ''
          }
          const toolName = data.tool_name || data.name
          const target = [...this.streamingToolCalls].reverse().find(
            t => t.name === toolName || t.status === 'running'
          )
          if (target) {
            target.status = data.error ? 'error' : 'done'
            target.result = data.result || data.output || null
            target.error = data.error || null
          } else {
            console.warn('[SSE] 未找到匹配的 tool target for:', toolName)
          }
          this.streamingToolCalls = [...this.streamingToolCalls]
          this.extractStreamingCharts()
          break
        }

        case 'conversation_id':
        case 'message_start':
          if (data.conversation_id) {
            const cid = data.conversation_id
            this._sseOwnerConversationId = cid
            const cur = this.$store.state.agent.currentConversationId
            if (cur === null || cur === cid) {
              this.$store.commit('agent/SET_CURRENT_CONVERSATION_ID', cid)
              this.$emit('conversation-created', cid)
            }
          }
          break

        case 'message_end':
          if (this.pendingText) {
            this.streamingContent = this.pendingText
            this.pendingText = ''
          }
          this.isInToolPhase = false
          this.completedToolSteps = []
          this.currentToolLabel = ''
          break

        case 'plan_update':
          this.currentPlan = data
          break

        case 'error':
          console.error('[SSE] 收到错误事件:', data)
          this.$message.error(data.message || data.error || 'AI 返回了一个错误')
          break

        case 'heartbeat':
          // 心跳事件：保持SSE连接活跃，无需UI更新
          break

        default:
          break
      }
    }
  }
}
</script>

<!-- 全局样式：Markdown 渲染 + 表格导出按钮（不加 scoped，确保 v-html 内容能命中） -->
<style>
@import './chatMarkdown.css';
</style>

<style scoped>

.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.message-item {
  display: flex;
  margin-bottom: 20px;
  gap: 12px;
}

.message-user {
  flex-direction: row-reverse;
}

.message-user .message-content-wrap {
  align-items: flex-end;
}

.message-content-wrap {
  display: flex;
  flex-direction: column;
  max-width: 75%;
  min-width: 0;
}

.message-content-wrap.has-charts {
  max-width: 95% !important;
}

.message-role {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.message-user .message-role {
  text-align: right;
}

.message-bubble {
  padding: 12px 16px;
  border-radius: 8px;
  line-height: 1.6;
  font-size: 14px;
  word-break: break-word;
}

.message-bubble.user {
  background: #ecf5ff;
  color: #303133;
  border-top-right-radius: 2px;
}

.message-bubble.assistant {
  background: #f4f4f5;
  color: #303133;
  border-top-left-radius: 2px;
}

.message-text {
  white-space: pre-wrap;
}

.message-text.markdown-body {
  white-space: normal;
}

/* 打字指示器 */
.typing-indicator {
  display: inline-flex;
  gap: 4px;
  padding: 4px 0;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
</style>
