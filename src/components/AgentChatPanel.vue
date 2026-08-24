<template>
  <div class="chat-panel">
    <!-- 消息列表 -->
    <div
      ref="messageList"
      class="message-list"
    >
        <!-- 加载更早的消息 -->
        <div v-if="hasMoreMessages" class="load-more-wrapper">
          <el-button
            size="mini"
            :loading="loadingMore"
            @click="loadMoreMessages"
          >
            加载更早的消息
          </el-button>
        </div>

        <!-- 空状态 -->
        <ChatEmptyState
          v-if="!messages.length && !showStreamingUI"
          :welcomeTitle="welcomeTitle"
          :welcomeDescription="welcomeDescription"
        />

        <div
          v-for="(item, index) in displayMessages"
          :key="item.id"
          :data-index="index"
        >
          <!-- 用户消息：右对齐圆角气泡，无头像 -->
          <div v-if="item.role === 'user'" class="message-item message-user">
            <div class="message-content-wrap user-wrap">
              <div class="message-bubble user">
                <div class="message-text">{{ item.content }}</div>
              </div>
            </div>
          </div>

          <!-- AI 消息：全宽无气泡，顶部标识行 + 复制按钮 -->
          <div v-else class="message-item message-assistant">
            <!-- 内容：使用 v-for="[rd] in [...]" 模式创建局部变量，避免模板中 7 次独立方法调用 -->
            <template v-for="rd in [_getMsgRender(item)]">
            <div class="message-content-wrap ai-wrap" :class="{ 'has-charts': rd.hasChartsOrTables }">
              <div class="ai-header">
                <span class="ai-avatar-dot"><i class="el-icon-s-opportunity"></i></span>
                <button
                  class="msg-copy-btn"
                  title="复制原文"
                  @click="copyMessageContent(item)"
                ><i class="el-icon-document-copy"></i><span>复制</span></button>
              </div>
              <div class="message-body assistant">
                <!-- AI 消息：按 segments 顺序渲染，表格走 ChatDataTable（可查询/排序/导出），echarts 围栏走 ChatChartRenderer -->
                <template v-for="(seg, sIdx) in rd.segments">
                  <div
                    v-if="seg.type === 'html'"
                    :key="'seg_html_' + item.id + '_' + sIdx"
                    class="message-text markdown-body"
                    v-html="seg.content"
                  ></div>
                  <ChatChartRenderer
                    v-else-if="seg.type === 'chart'"
                    :key="'seg_chart_' + item.id + '_' + sIdx"
                    :charts="[seg.chart]"
                    :refPrefix="'seg_chart_' + item.id + '_' + sIdx"
                  />
                  <ChatDataTable
                    v-else
                    :key="'seg_table_' + item.id + '_' + (seg.segId || sIdx)"
                    :records="seg.records"
                    :recordCount="seg.records.length"
                    :preview-limit="50"
                    dataShape="table"
                    :traceable-assets="seg.traceableAssets || []"
                    :traceable-backtests="seg.traceableBacktests || _cachedTraceableBacktests(item)"
                    @asset-click="handleAssetClick"
                    @backtest-click="handleBacktestClick"
                  />
                </template>
              </div>
              <!-- 写操作确认卡片（含历史重建的终态卡片） -->
              <ChatConfirmCard
                v-for="(card, kIdx) in rd.confirmations"
                :key="'confirm_' + item.id + '_' + (card.token || kIdx)"
                :card="card"
                @decide="handleConfirmDecision(card, $event)"
              />
              <!-- 数据表格 -->
              <ChatDataTable v-for="(table, tIdx) in rd.dataTables" :key="'table_' + item.id + '_' + tIdx"
                :records="table.records" :summary="table.summary" :recordCount="table.recordCount"
                :dataShape="table.dataShape" :stepKey="table.toolName"
                :preview-limit="50"
                :traceable-assets="table.traceableAssets || []"
                :traceable-backtests="table.traceableBacktests || []"
                @asset-click="handleAssetClick"
                @backtest-click="handleBacktestClick" />
              <!-- 数据导入卡片 -->
              <DataImportCards
                v-for="(card, cIdx) in rd.importCards"
                :key="'import_card_' + item.id + '_' + cIdx"
                :card-type="card.cardType"
                :data="card.data"
              />
              <!-- 图表区域 -->
              <ChatChartRenderer
                v-if="rd.charts.length > 0"
                :charts="rd.charts"
                :refPrefix="'msg_chart_' + index"
                :key="'chart_renderer_' + item.id"
              />
            </div>
            </template>
          </div>
        </div>
        <!-- 流式输出中（仅当前查看的会话与流归属一致时显示） -->
        <div v-if="showStreamingUI && (streamingContent || streamingCharts.length > 0 || streamingTables.length > 0 || streamingConfirmations.length > 0)" class="message-item message-assistant">
          <div class="message-content-wrap ai-wrap" :class="{ 'has-charts': streamingCharts.length > 0 || streamingTables.length > 0 }">
            <div class="ai-header">
              <span class="ai-avatar-dot"><i class="el-icon-s-opportunity"></i></span>
            </div>
            <div class="message-body assistant">
              <!-- 流式内容也按 segments 渲染，使表格一出现即具查询/排序/导出能力 -->
              <template v-for="(seg, sIdx) in _cachedParseSegments(_streamingSegmentsMsg)">
                <div
                  v-if="seg.type === 'html'"
                  :key="'stream_seg_html_' + sIdx"
                  class="message-text markdown-body"
                  v-html="seg.content"
                ></div>
                <ChatChartRenderer
                  v-else-if="seg.type === 'chart'"
                  :key="'stream_seg_chart_' + sIdx"
                  :charts="[seg.chart]"
                  :refPrefix="'stream_seg_chart_' + sIdx"
                />
                <ChatDataTable
                  v-else
                  :key="'stream_seg_table_' + (seg.segId || sIdx)"
                  :records="seg.records"
                  :recordCount="seg.records.length"
                  :preview-limit="50"
                  dataShape="table"
                  :traceable-assets="seg.traceableAssets || []"
                  :traceable-backtests="seg.traceableBacktests || streamingTraceableBacktests"
                  @asset-click="handleAssetClick"
                  @backtest-click="handleBacktestClick"
                />
              </template>
            </div>
            <!-- 流式表格 -->
            <ChatDataTable v-for="(table, tIdx) in streamingTables" :key="'stream_table_' + tIdx"
              :records="table.records" :summary="table.summary" :recordCount="table.recordCount"
              :dataShape="table.dataShape" :stepKey="table.toolName"
              :preview-limit="50"
              :traceable-assets="table.traceableAssets || []"
              :traceable-backtests="table.traceableBacktests || []"
              @asset-click="handleAssetClick"
              @backtest-click="handleBacktestClick" />
            <!-- 流式数据导入卡片 -->
            <DataImportCards
              v-for="(card, cIdx) in streamingImportCards"
              :key="'stream_import_card_' + cIdx"
              :card-type="card.cardType"
              :data="card.data"
            />
            <!-- 流式确认卡片：写工具返回 pending_confirmation 时由 confirm_request 事件推送 -->
            <ChatConfirmCard
              v-for="(card, kIdx) in streamingConfirmations"
              :key="'stream_confirm_' + (card.token || kIdx)"
              :card="card"
              @decide="handleConfirmDecision(card, $event)"
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
          <div class="message-content-wrap ai-wrap">
            <div class="ai-header">
              <span class="ai-avatar-dot"><i class="el-icon-s-opportunity"></i></span>
            </div>
            <div class="message-body assistant">
              <ChatToolProgress :completedSteps="completedToolSteps" :currentLabel="currentToolLabel" />
            </div>
          </div>
        </div>

        <!-- 加载指示（等待首次响应） -->
        <div v-if="showStreamingUI && !streamingContent && streamingCharts.length === 0 && streamingTables.length === 0 && streamingConfirmations.length === 0 && !isInToolPhase" class="message-item message-assistant">
          <div class="message-content-wrap ai-wrap">
            <div class="ai-header">
              <span class="ai-avatar-dot"><i class="el-icon-s-opportunity"></i></span>
            </div>
            <div class="message-body assistant">
              <span class="typing-indicator">
                <span></span><span></span><span></span>
              </span>
            </div>
          </div>
        </div>
    </div>

    <!-- 输入区域 -->
    <ChatInputBox :isLoading="isStreaming" @send="handleSend" ref="chatInput" />

    <!-- 资产详情弹窗 -->
    <AssetChartDialog
      :visible.sync="assetChartDialogVisible"
      :asset-code="currentChartAssetCode"
      :asset-name="currentChartAssetName"
      :start-date="currentChartStartDate"
      :end-date="currentChartEndDate"
    />

    <!-- 回测详情弹窗 -->
    <BacktestDetailDialog
      v-if="selectedBacktestRecord"
      v-model="backtestDialogVisible"
      :record="selectedBacktestRecord"
    />
  </div>
</template>

<script>
import { sendMessageStream, submitConfirmationDecision, getConversationConfirmations } from '@/api/agent'
import { getSceneByKey, AGENT_SCENES } from '@/config/agentScenes'
import { debounce } from 'lodash'
import { renderMarkdown, parseMessageSegments, getMessageCharts, getMessageDataTables, parseToolResult, throttle } from './chatUtils'
import ChatEmptyState from './ChatEmptyState.vue'
import ChatChartRenderer from './ChatChartRenderer.vue'
import ChatDataTable from './ChatDataTable.vue'
import ChatToolProgress from './ChatToolProgress.vue'
import ChatInputBox from './ChatInputBox.vue'
import ChatConfirmCard from './ChatConfirmCard.vue'
import DataImportCards from './DataImportCards.vue'
import AssetChartDialog from './AssetChartDialog.vue'
import BacktestDetailDialog from './BacktestDetailDialog.vue'

/** 写工具名 → 中文操作名（确认决策后的本地镜像消息） */
const CONFIRM_TOOL_LABELS = {
  'run_backtest': '执行回测',
  'create_portfolio': '创建组合',
  'adjust_portfolio': '调整组合',
  'update_monitor_config': '更新监控配置',
  'trigger_data_sync': '触发数据同步',
  'save_report': '保存报告'
}

export default {
  name: 'AgentChatPanel',
  components: { ChatEmptyState, ChatChartRenderer, ChatDataTable, ChatToolProgress, ChatInputBox, ChatConfirmCard, DataImportCards, AssetChartDialog, BacktestDetailDialog },
  props: {
    conversationId: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      loadingMore: false,
      streamingContent: '',
      streamingToolCalls: [],
      streamingCharts: [],
      /** 本轮流中收到的写操作确认卡片（confirm_request 事件） */
      streamingConfirmations: [],
      isStreaming: false,
      pendingText: '',
      isInToolPhase: false,
      toolNameMap: {
        'search_knowledge': '正在检索知识库...',
        'read_knowledge': '正在阅读知识文档...',
        'manage_memory': '正在更新记忆...',
        'read_tool_result': '正在读取完整工具结果...',
        'query_strategies': '正在查询策略...',
        'query_backtests': '正在查询回测记录...',
        'run_backtest': '正在执行回测...',
        'query_portfolios': '正在查询组合...',
        'create_portfolio': '正在准备创建组合...',
        'adjust_portfolio': '正在准备调整组合...',
        'query_monitors': '正在查询监控状态...',
        'update_monitor_config': '正在准备更新监控配置...',
        'query_assets': '正在盘点数据资产...',
        'check_data_quality': '正在检查数据质量...',
        'query_import_logs': '正在查询导入历史...',
        'query_data_connectors': '正在查询数据连接器...',
        'trigger_data_sync': '正在准备触发数据同步...',
        'query_dataset': '正在查询数据集...',
        'save_report': '正在生成报告...',
        'query_reports': '正在查询历史报告...'
      },
      completedToolSteps: [],
      currentToolLabel: '',
      /** 本次发送开始前 store 中的 conversationId */
      _sendSnapshotConvId: undefined,
      /** 发送时是否为「尚无会话 id」的新建对话 */
      _wasNullConvAtSend: false,
      /** 当前 SSE 请求归属的会话 id（与左侧当前选中会话严格对应，防串话） */
      _sseOwnerConversationId: null,
      _streamAbortController: null,
      /** 已为切换会话等行为主动中止 SSE，完成后禁止把助手消息写入 store */
      _streamAborted: false,
      /** 资产详情弹窗状态 */
      assetChartDialogVisible: false,
      currentChartAssetCode: '',
      currentChartAssetName: '',
      /** 表格推断出的区间，随弹窗一同传递给 AssetChartDialog -> AssetQuote */
      currentChartStartDate: '',
      currentChartEndDate: '',
      /** 回测详情弹窗状态 */
      backtestDialogVisible: false,
      selectedBacktestRecord: null
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
    messages() {
      return this.$store.state.agent.messages
    },
    hasMoreMessages() {
      return this.$store.state.agent.messageHasMore
    },
    displayMessages() {
      // 性能关键：避免每次都 spread 新对象导致虚拟滚动器 diff 失效
      // 仅对缺少 id 的消息补丁，其余返回原始引用
      const msgs = this.messages
      let needsPatch = false
      for (let i = 0; i < msgs.length; i++) {
        if (!msgs[i].id) { needsPatch = true; break }
      }
      if (!needsPatch) return msgs
      return msgs.map((msg, idx) => {
        if (msg.id) return msg
        return { ...msg, id: `msg-${idx}` }
      })
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
    },
    /** 从流式工具调用结果中提取所有可追踪资产 */
    streamingTraceableAssets() {
      return this.getMessageTraceableAssets({ tool_calls: this.streamingToolCalls })
    },
    /** 从流式工具调用结果中提取所有可追踪回测记录 */
    streamingTraceableBacktests() {
      return this.getMessageTraceableBacktests({ tool_calls: this.streamingToolCalls })
    },
    /** 流式 segments 的缓存键对象：携带 _cacheId 使 _cachedParseSegments 能正确命中缓存 */
    _streamingSegmentsMsg() {
      return {
        id: '__streaming__',
        content: this.streamingContent,
        tool_calls: this.streamingToolCalls
      }
    }
  },
  watch: {
    conversationId(newId, oldId) {
      // 会话切换时清理消息缓存，避免旧消息的缓存占用内存
      if (newId !== oldId) {
        this._clearMsgCache()
        this._confirmAttachedConvId = null
      }
      // 新建对话初始化（null/undefined -> 新ID）时不应中止流
      if (oldId == null) {
        if (newId && this.$store.state.agent.currentConversationId !== newId) {
          this.$store.dispatch('agent/loadConversation', newId)
            .then(() => this.attachHistoryConfirmations(newId))
        } else if (newId) {
          this.attachHistoryConfirmations(newId)
        }
        return
      }
      // 用户主动切换到不同对话时才中止
      if (newId && newId !== oldId) {
        this.cancelStreaming()
        if (this.$store.state.agent.currentConversationId !== newId) {
          this.$store.dispatch('agent/loadConversation', newId)
            .then(() => this.attachHistoryConfirmations(newId))
        } else {
          this.attachHistoryConfirmations(newId)
        }
      }
    },
    'messages.length': {
      handler() {
        this.$nextTick(() => {
          this.debouncedScrollToBottom()
        })
      }
    },
    /** 首次拿到当前会话的消息后，拉取确认记录重建终态卡片 */
    messages: {
      handler(msgs) {
        const convId = this.currentConvId
        if (!convId || !msgs || !msgs.length) return
        if (this._confirmAttachedConvId === convId) return
        this._confirmAttachedConvId = convId
        this.attachHistoryConfirmations(convId)
      }
    },
    streamingContent() {
      this.$nextTick(() => this.debouncedScrollToBottom())
    },
    'streamingCharts.length'() {
      this.$nextTick(() => this.debouncedScrollToBottom())
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
      const scroller = this.$refs.messageList
      if (scroller) {
        scroller.scrollTop = scroller.scrollHeight
      }
    }, 80)
    this.debouncedScrollToBottom = debounce(this.scrollToBottom, 100)

    // ── 消息级 memoization 缓存 ──
    // 模板中的 parseMessageSegments / getMessageDataTables 等函数每次渲染都会重复执行，
    // 多表场景下开销巨大。用 Map<msgId, {version, result}> 做版本化缓存，
    // 同一消息 + 同一数据指纹（content长度 / tool_calls数量）直接复用上次结果。
    this._msgCache = {
      segments: new Map(),
      dataTables: new Map(),
      charts: new Map(),
      traceableAssets: new Map(),
      traceableBacktests: new Map(),
      importCards: new Map()
    }
    // 合并渲染数据缓存：单次方法调用替代模板 7 次 _cached* 调用
    this._renderCache = new Map()
  },
  mounted() {
    // 表格导出按钮采用事件委托：按钮随 v-html 一起渲染，避免闪烁/跳动
    if (this.$el && this.$el.addEventListener) {
      this.$el.addEventListener('click', this.handleTableExportClick)
    }
    // 带会话进入（消息已在 store）时 watcher 不会触发，主动重建一次终态卡片
    const convId = this.currentConvId || this.conversationId
    if (convId && this.messages.length) {
      this._confirmAttachedConvId = convId
      this.attachHistoryConfirmations(convId)
    }
  },
  beforeDestroy() {
    this.cancelStreaming()
    this._clearMsgCache()
    if (this.$el && this.$el.removeEventListener) {
      this.$el.removeEventListener('click', this.handleTableExportClick)
    }
  },
  methods: {
    /**
     * 加载更早的历史消息（分页）
     */
    async loadMoreMessages() {
      this.loadingMore = true
      const scroller = this.$refs.messageList
      const el = scroller || null
      const scrollHeightBefore = el ? el.scrollHeight : 0

      try {
        await this.$store.dispatch('agent/loadMoreMessages')
        // 更早的历史消息可能承载更早的确认卡片，补充一次重建（token 去重）
        this.attachHistoryConfirmations(this.currentConvId)

        // 恢复滚动位置（避免加载后跳到顶部）
        this.$nextTick(() => {
          if (el) {
            const scrollHeightAfter = el.scrollHeight
            el.scrollTop = scrollHeightAfter - scrollHeightBefore
          }
        })
      } finally {
        this.loadingMore = false
      }
    },

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
      this.streamingConfirmations = []
      this.pendingText = ''
      this.isInToolPhase = false
      this.completedToolSteps = []
      this.currentToolLabel = ''
      this._sseOwnerConversationId = null
      this._sendSnapshotConvId = undefined
      this._wasNullConvAtSend = false
      // 清理流式缓存条目，避免下次流式命中过期缓存
      if (this._msgCache) {
        for (const map of Object.values(this._msgCache)) {
          map.delete('__streaming__')
        }
      }
      if (this._renderCache) this._renderCache.delete('__streaming__')
    },

    renderMarkdown,
    parseMessageSegments,
    getMessageCharts,
    getMessageDataTables,

    /**
     * ─── 消息级 memoization：缓存包装方法 ───
     * 通过 msgId + 数据指纹 构建 version key，命中则直接返回缓存结果。
     * 多表场景下避免模板重复调用带来的 N 倍开销。
     */
    _cacheGet(cacheMap, msg, version, fn) {
      const key = msg.id || msg._cacheId
      if (!key) return fn() // 无 id 时不缓存（流式合成对象）
      const cached = cacheMap.get(key)
      if (cached && cached.v === version) return cached.r
      const result = fn()
      cacheMap.set(key, { v: version, r: result })
      return result
    },

    _cachedParseSegments(msg) {
      const content = msg.content || ''
      const assets = this._cachedTraceableAssets(msg)
      const v = (content.length | 0) + '::' + assets.length
      return this._cacheGet(this._msgCache.segments, msg, v, () =>
        parseMessageSegments(content, { traceable_assets: assets })
      )
    },

    _cachedDataTables(msg) {
      const tc = msg.tool_calls
      const v = (tc && tc.length) || 0
      return this._cacheGet(this._msgCache.dataTables, msg, v, () =>
        getMessageDataTables(msg)
      )
    },

    _cachedCharts(msg) {
      const tc = msg.tool_calls
      const v = (tc && tc.length) || 0
      return this._cacheGet(this._msgCache.charts, msg, v, () =>
        getMessageCharts(msg)
      )
    },

    _cachedTraceableAssets(msg) {
      const tc = msg.tool_calls
      const v = (tc && tc.length) || 0
      return this._cacheGet(this._msgCache.traceableAssets, msg, v, () =>
        this.getMessageTraceableAssets(msg)
      )
    },

    _cachedTraceableBacktests(msg) {
      const tc = msg.tool_calls
      const v = (tc && tc.length) || 0
      return this._cacheGet(this._msgCache.traceableBacktests, msg, v, () =>
        this.getMessageTraceableBacktests(msg)
      )
    },

    _cachedImportCards(msg) {
      const tc = msg.tool_calls
      const v = (tc && tc.length) || 0
      return this._cacheGet(this._msgCache.importCards, msg, v, () =>
        this.getMessageImportCards(msg)
      )
    },
    /** ─── end memoization ─── */

    /**
     * 合并渲染数据：单次方法调用替代模板中 7 次 _cached* 独立调用。
     * 每条消息只在模板中调用 1 次，通过 v-for="[rd] in [_getMsgRender(item)]" 绑定局部变量。
     * 内部复用已有的 _cached* 方法，确保缓存一致性。
     */
    _getMsgRender(msg) {
      const key = msg.id
      if (!key) return this._buildMsgRender(msg)
      const content = msg.content || ''
      const tc = msg.tool_calls
      const cf = msg.confirmations
      const v = (content.length | 0) + '|' + ((tc && tc.length) || 0) + '|' + ((cf && cf.length) || 0)
      const cached = this._renderCache.get(key)
      if (cached && cached.v === v) return cached.r
      const r = this._buildMsgRender(msg)
      this._renderCache.set(key, { v, r })
      return r
    },
    _buildMsgRender(msg) {
      const segments = this._cachedParseSegments(msg)
      const dataTables = this._cachedDataTables(msg)
      const charts = this._cachedCharts(msg)
      const importCards = this._cachedImportCards(msg)
      return {
        segments,
        dataTables,
        charts,
        importCards,
        confirmations: msg.confirmations || [],
        hasChartsOrTables: charts.length > 0 || dataTables.length > 0
      }
    },

    /** 清空所有消息级缓存（会话切换 / 销毁时调用）*/
    _clearMsgCache() {
      if (!this._msgCache) return
      for (const map of Object.values(this._msgCache)) {
        map.clear()
      }
      if (this._renderCache) this._renderCache.clear()
    },

    /**
     * 从消息的 tool_calls 中提取所有可追踪资产（去重）
     * @param {Object} msg 消息对象
     * @returns {Array} traceable_assets 数组
     */
    getMessageTraceableAssets(msg) {
      if (!msg.tool_calls || !msg.tool_calls.length) return []
      const assets = []
      const seen = new Set()
      for (const tool of msg.tool_calls) {
        const result = parseToolResult(tool)
        if (!result) continue
        const ta = result.traceable_assets
          || (result.data && result.data.traceable_assets)
          || (result.metadata && result.metadata.traceable_assets)
          || []
        for (const a of ta) {
          if (a && a.code && !seen.has(a.code)) {
            seen.add(a.code)
            assets.push(a)
          }
        }
      }
      return assets
    },

    /**
     * 处理资产点击：打开资产详情弹窗
     * 从 ChatDataTable 传来的 payload 额外携带表格推断出的区间（startDate / endDate），
     * 使资产详情弹窗默认展示与表格同源区间的行情，避免“表格一个区间、弹窗另一个区间”的脱节。
     */
    handleAssetClick(payload) {
      const { code, name, startDate, endDate } = payload || {}
      this.currentChartAssetCode = code
      this.currentChartAssetName = name
      this.currentChartStartDate = startDate || ''
      this.currentChartEndDate = endDate || ''
      this.assetChartDialogVisible = true
    },

    /**
     * 复制 AI 消息的原始 Markdown 文本（纯前端，不依赖后端）
     * @param {Object} item 消息对象
     */
    copyMessageContent(item) {
      const text = (item && item.content) || ''
      if (!text) {
        this.$message.info('该消息暂无可复制的文本内容')
        return
      }
      const onSuccess = () => this.$message.success('已复制到剪贴板')
      const onFail = () => this.$message.error('复制失败，请手动选择文本复制')
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(onSuccess).catch(() => {
          this.fallbackCopy(text) ? onSuccess() : onFail()
        })
      } else {
        this.fallbackCopy(text) ? onSuccess() : onFail()
      }
    },

    /** 剪贴板降级方案（非 HTTPS / 旧浏览器） */
    fallbackCopy(text) {
      try {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        return ok
      } catch (e) {
        return false
      }
    },

    /**
     * 从消息中提取所有可追踪回测记录（去重）
     * 优先使用后端显式提供的 traceable_backtests，
     * 若无则尝试从回测类工具结果中自动推断。
     */
    getMessageTraceableBacktests(msg) {
      if (!msg.tool_calls || !msg.tool_calls.length) return []
      const backtests = []
      const seen = new Set()
      // 回测相关工具名集合
      const BACKTEST_TOOLS = ['execute_backtest', 'compare_strategies', 'recommend_strategy', 'run_backtest', 'query_backtests']

      for (const tool of msg.tool_calls) {
        const result = parseToolResult(tool)
        if (!result) continue

        // 1. 显式提供的 traceable_backtests
        const tb = result.traceable_backtests
          || (result.data && result.data.traceable_backtests)
          || (result.metadata && result.metadata.traceable_backtests)
          || []
        for (const b of tb) {
          if (b && b.record_id && !seen.has(b.record_id)) {
            seen.add(b.record_id)
            backtests.push(b)
          }
        }

        // 2. 若无显式数据，从回测工具结果中推断
        if (backtests.length === 0 && BACKTEST_TOOLS.includes(tool.name)) {
          const inferred = this._inferBacktestFromToolResult(result, tool.name)
          for (const b of inferred) {
            if (b && b.record_id && !seen.has(b.record_id)) {
              seen.add(b.record_id)
              backtests.push(b)
            }
          }
        }
      }
      return backtests
    },

    /**
     * 从回测工具返回结果中推断 traceable_backtests 结构
     * 支持单策略回测和多策略对比两种结果格式
     */
    _inferBacktestFromToolResult(result, toolName) {
      const list = []

      // --- 多策略对比模式： result.results 是一个对象，每个 key 对应一个策略回测 ---
      const multiResults = result.results || (result.data && result.data.results)
      if (multiResults && typeof multiResults === 'object' && !Array.isArray(multiResults)) {
        for (const [key, val] of Object.entries(multiResults)) {
          const entry = this._buildBacktestEntry(val, key, result)
          if (entry) list.push(entry)
        }
        if (list.length) return list
      }

      // --- 单策略回测模式 ---
      const entry = this._buildBacktestEntry(result, toolName, result)
      if (entry) list.push(entry)
      return list
    },

    /**
     * 从单个回测结果对象中构建 traceable_backtest 条目
     */
    _buildBacktestEntry(obj, fallbackName, rootResult) {
      if (!obj || typeof obj !== 'object') return null

      // 探测各层级可能的数据位置
      const data = obj.data || obj
      const meta = obj.metadata || rootResult.metadata || {}
      const strategy = obj.strategy || data.strategy || {}
      const btResult = data.result || obj.result || {}

      // 提取 record_id
      const recordId = data.record_id || obj.record_id || meta.record_id
        || btResult.record_id || ''

      // 提取策略名称
      const strategyName = data.strategy_name || obj.strategy_name
        || strategy.name || meta.strategy_name || ''

      // 提取模板代码
      const templateCode = data.template_code || obj.template_code
        || strategy.template_code || meta.template_code || ''

      // 必须至少有策略名称或 record_id 才有意义
      if (!strategyName && !recordId) return null

      // 提取日期
      const startDate = data.start_date || obj.start_date || meta.start_date || ''
      const endDate = data.end_date || obj.end_date || meta.end_date || ''

      // 提取指标
      const metrics = data.metrics || obj.metrics || meta.metrics || {}
      if (!metrics.total_return && btResult.total_return != null) {
        metrics.total_return = btResult.total_return
      }
      if (!metrics.annual_return && btResult.annual_return != null) {
        metrics.annual_return = btResult.annual_return
      }
      if (!metrics.max_drawdown && btResult.max_drawdown != null) {
        metrics.max_drawdown = btResult.max_drawdown
      }
      if (!metrics.sharpe_ratio && btResult.sharpe_ratio != null) {
        metrics.sharpe_ratio = btResult.sharpe_ratio
      }

      // 提取权重快照
      const weightSnapshots = data.weight_snapshots || obj.weight_snapshots
        || btResult.weight_snapshots || btResult.weight_changes || []

      return {
        record_id: recordId || ('inferred_' + (strategyName || fallbackName) + '_' + Date.now()),
        strategy_name: strategyName || fallbackName || '回测策略',
        template_code: templateCode,
        start_date: startDate,
        end_date: endDate,
        initial_capital: data.initial_capital || obj.initial_capital || meta.initial_capital || 1000000,
        created_at: data.created_at || obj.created_at || '',
        metrics,
        weight_snapshots: Array.isArray(weightSnapshots) ? weightSnapshots : [],
        result: btResult
      }
    },

    /**
     * 处理回测策略芯片点击：打开回测详情弹窗
     */
    handleBacktestClick(bt) {
      this.selectedBacktestRecord = {
        id: bt.record_id || '',
        start_date: bt.start_date || '',
        end_date: bt.end_date || '',
        initial_capital: bt.initial_capital || 1000000,
        created_at: bt.created_at || '',
        result: bt.result || {}
      }
      this.backtestDialogVisible = true
    },

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
     * 事件委托：点击 Markdown 表格上的导出按钮时导出对应表格
     */
    handleTableExportClick(e) {
      const target = e.target
      if (!target || !target.closest) return
      const btn = target.closest('.table-export-btn')
      if (!btn || !this.$el.contains(btn)) return
      const wrapper = btn.closest('.table-wrapper')
      if (!wrapper) return
      const table = wrapper.querySelector('table')
      if (!table) return
      this.exportTable(table)
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


    /**
     * 发送消息 —— 使用 SSE 流式接收 AI 回复
     * @param {string} text 用户输入文本
     */
    async handleSend(text) {
      const msg = typeof text === 'string' ? text.trim() : ''
      if (!msg || this.isStreaming) return

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
      this.streamingConfirmations = []
      this.pendingText = ''
      this.isInToolPhase = false

      const conversationId = this.currentConvId || this.conversationId

      try {
        const sceneKey = this.$store.state.agent.currentScene || 'auto'
        const scene = sceneKey === 'auto' ? null : sceneKey

        const payload = {
          message: msg,
          conversation_id: conversationId,
          scene
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
        const hasContent = this.streamingContent || this.streamingToolCalls.length || this.streamingConfirmations.length
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
          // 确认卡片随消息落库：重开会话时由历史重建逻辑按确认记录状态渲染终态卡片
          if (this.streamingConfirmations.length) {
            aiMsg.confirmations = JSON.parse(JSON.stringify(this.streamingConfirmations))
          }
          this.$store.commit('agent/ADD_MESSAGE', aiMsg)
        }

        if (!this._streamAborted) {
          this.$store.dispatch('agent/loadConversations', { silent: true })
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
        this.streamingConfirmations = []
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

        case 'confirm_request': {
          // M3 确认协议：写工具进入待确认，渲染确认卡片（决策走独立 HTTP，不依赖 SSE）
          if (data.token) {
            const exists = this.streamingConfirmations.some(c => c.token === data.token)
            if (!exists) {
              this.streamingConfirmations.push({
                token: data.token,
                tool_name: data.tool_name || '',
                preview: data.preview || {},
                status: 'pending',
                reused: !!data.reused
              })
              this.streamingConfirmations = [...this.streamingConfirmations]
            }
          }
          break
        }

        case 'conversation_id':
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
    },

    /**
     * 提交确认卡片决策（confirmed / rejected），决策为独立 HTTP 请求
     * @param {Object} card 卡片状态对象（流式中或消息上的 confirmations 项）
     * @param {string} decision 'confirmed' | 'rejected'
     */
    async handleConfirmDecision(card, decision) {
      if (!card || card._busy) return
      if (!(card.status === 'pending' || card.status === 'pending_confirmation')) return
      this.$set(card, '_busy', true)
      try {
        const res = await submitConfirmationDecision(card.token, decision)
        const outcome = (res && res.data) || {}
        this.$set(card, 'status', outcome.status || (decision === 'confirmed' ? 'confirmed' : 'rejected'))
        if (outcome.result !== undefined && outcome.result !== null) {
          let text
          try {
            text = typeof outcome.result === 'string' ? outcome.result : JSON.stringify(outcome.result)
          } catch (e) {
            text = String(outcome.result)
          }
          this.$set(card, 'result_summary', text.length > 200 ? text.slice(0, 200) + '…' : text)
        }
        if (outcome.error) this.$set(card, 'error', outcome.error)
        // 后端已将执行结果/取消消息写入会话历史，此处本地镜像一条，
        // 使当前会话无需刷新即可看到结果（重开页面时以后端数据为准）
        const toolLabel = CONFIRM_TOOL_LABELS[card.tool_name] || card.tool_name || '写操作'
        let content
        if (decision === 'rejected') {
          content = `[操作已取消] 已取消${toolLabel}操作，未产生任何变更。`
        } else if (outcome.error) {
          content = `[${toolLabel}执行失败] ${outcome.error}`
        } else {
          content = `[${toolLabel}操作执行结果] 操作已执行完成。`
        }
        this.$store.commit('agent/ADD_MESSAGE', {
          role: 'assistant',
          content,
          created_at: new Date().toISOString()
        })
      } catch (e) {
        console.error('提交确认决策失败:', e)
        this.$message.error('提交确认决策失败: ' + ((e && e.message) || '未知错误'))
      } finally {
        this.$set(card, '_busy', false)
      }
    },

    /**
     * 历史消息重建：拉取会话确认记录，按时间就近挂到 assistant 消息上渲染终态卡片
     * @param {string} convId 会话 id
     */
    async attachHistoryConfirmations(convId) {
      if (!convId) return
      try {
        const res = await getConversationConfirmations(convId, 50)
        const payload = (res && res.data) || {}
        const items = Array.isArray(payload.items) ? payload.items
          : Array.isArray(payload) ? payload : []
        if (!items.length || this.currentConvId !== convId) return
        const msgs = this.$store.state.agent.messages
        for (const rec of items) {
          if (!rec || !rec.token) continue
          const duplicated = msgs.some(m =>
            m.confirmations && m.confirmations.some(c => c.token === rec.token))
          if (duplicated) continue
          const target = this._findCardHostMessage(msgs, rec)
          if (!target) continue
          if (!target.confirmations) this.$set(target, 'confirmations', [])
          target.confirmations.push(this._buildCardFromRecord(rec))
        }
      } catch (e) {
        console.warn('[Confirm] 加载会话确认记录失败:', e)
      }
    },

    /** 找与确认记录创建时间最接近（±5 分钟）的 assistant 消息作为卡片宿主 */
    _findCardHostMessage(msgs, rec) {
      const recTime = Date.parse(rec.created_at)
      if (!recTime || isNaN(recTime)) return null
      let best = null
      let bestDelta = Infinity
      for (const m of msgs) {
        if (m.role !== 'assistant') continue
        const t = Date.parse(m.created_at)
        if (!t || isNaN(t)) continue
        const delta = Math.abs(t - recTime)
        if (delta < bestDelta) {
          bestDelta = delta
          best = m
        }
      }
      return bestDelta <= 5 * 60 * 1000 ? best : null
    },

    /** 后端确认记录 → 前端卡片状态 */
    _buildCardFromRecord(rec) {
      const card = {
        token: rec.token,
        tool_name: rec.tool_name || '',
        preview: rec.preview || {},
        status: rec.status || 'pending'
      }
      if (rec.status === 'confirmed' && rec.result !== undefined && rec.result !== null) {
        let text
        try {
          text = typeof rec.result === 'string' ? rec.result : JSON.stringify(rec.result)
        } catch (e) {
          text = ''
        }
        card.result_summary = text.length > 200 ? text.slice(0, 200) + '…' : text
      }
      if (rec.error) card.error = rec.error
      return card
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
  background: #f7f8fa;
}

/* 消息列表：浅灰背景 + 全宽铺开，用户贴右、AI贴左 */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px 16px;
  background: #f7f8fa;
  display: flex;
  flex-direction: column;
}

/* 自定义滚动条：细轨道、圆角、淡色 */
.message-list::-webkit-scrollbar {
  width: 6px;
}
.message-list::-webkit-scrollbar-track {
  background: transparent;
}
.message-list::-webkit-scrollbar-thumb {
  background: #d4d8e0;
  border-radius: 3px;
}
.message-list::-webkit-scrollbar-thumb:hover {
  background: #b8bec8;
}

/* 加载更多按钮 */
.load-more-wrapper {
  text-align: center;
  padding: 8px 0 16px;
}

.message-list > * {
  width: 100%;
}

/* 消息间距 */
.message-item {
  display: flex;
  margin-bottom: 30px;
}

/* ===== 用户消息：右对齐圆角气泡，无头像 ===== */
.message-user {
  justify-content: flex-end;
}

.user-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  max-width: 78%;
  min-width: 0;
}

.message-bubble.user {
  padding: 12px 16px;
  border-radius: 18px 18px 4px 18px;
  background: linear-gradient(135deg, #e9f2ff 0%, #d9e8ff 100%);
  color: #1f2937;
  font-size: 14px;
  line-height: 1.65;
  word-break: break-word;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

/* ===== AI 消息：全宽无气泡 ===== */
.message-assistant {
  width: 100%;
}

.ai-wrap {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
}

/* AI 标识行：渐变圆标 + 弱化名称 + 复制按钮 */
.ai-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.ai-avatar-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: linear-gradient(135deg, #409EFF 0%, #7C6CF0 100%);
  color: #fff;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(64, 158, 255, 0.35);
}

/* 复制按钮：hover 时浮现 */
.msg-copy-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #909399;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.18s ease, background 0.18s ease, color 0.18s ease;
}

.message-assistant:hover .msg-copy-btn,
.msg-copy-btn:focus {
  opacity: 1;
}

.msg-copy-btn:hover {
  background: #eef1f6;
  color: #409EFF;
}

/* AI 内容主体：全宽铺开，无气泡背景 */
.message-body.assistant {
  color: #303133;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

/* 表格 / 图表 / 导入卡片：白底卡片 + 细边框 + 12px 圆角 */
.ai-wrap .chat-data-table,
.ai-wrap .message-charts,
.ai-wrap .data-import-card {
  margin-top: 14px;
  background: #fff;
  border: 1px solid #e8ebf0;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}

.message-text {
  white-space: pre-wrap;
}

.message-text.markdown-body {
  white-space: normal;
}

/* 打字指示器（调小） */
.typing-indicator {
  display: inline-flex;
  gap: 4px;
  padding: 6px 0;
}

.typing-indicator span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #a5b4fc;
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
