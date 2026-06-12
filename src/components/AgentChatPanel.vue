<template>
  <div class="chat-panel">
    <!-- 消息列表（虚拟滚动） -->
    <DynamicScroller
      ref="messageList"
      :items="displayMessages"
      :min-item-size="60"
      :buffer="800"
      key-field="id"
      class="message-list"
    >
      <template #before>
        <!-- 加载更早的消息 -->
        <div v-if="hasMoreMessages" class="load-more-wrapper" style="text-align: center; padding: 10px;">
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
          :quickQuestions="sceneQuickQuestions"
          @quick-question="handleQuickQuestion"
          @select-template="handleTemplateSelect"
        />
      </template>

      <template v-slot="{ item, index, active }">
        <DynamicScrollerItem
          :item="item"
          :active="active"
          :data-index="index"
          :size-dependencies="[item.content, item.tool_calls]"
        >
          <div
            :class="['message-item', item.role === 'user' ? 'message-user' : 'message-assistant']"
          >
            <!-- 头像 -->
            <div class="message-avatar">
              <el-avatar
                :size="36"
                :icon="item.role === 'user' ? 'el-icon-user-solid' : 'el-icon-s-opportunity'"
                :style="{ background: item.role === 'user' ? '#409EFF' : '#67C23A' }"
              ></el-avatar>
            </div>
            <!-- 内容：使用 v-for="[rd] in [...]" 模式创建局部变量，避免模板中 7 次独立方法调用 -->
            <template v-for="rd in [_getMsgRender(item)]">
            <div class="message-content-wrap" :class="{ 'has-charts': rd.hasChartsOrTables }">
              <div class="message-role">{{ item.role === 'user' ? '我' : '数智平台AI助手' }}</div>
              <div class="message-bubble" :class="item.role">
                <!-- 用户消息 -->
                <div v-if="item.role === 'user'" class="message-text">{{ item.content }}</div>
                <!-- AI 消息：按 segments 顺序渲染，表格走 ChatDataTable（可查询/排序/导出） -->
                <template v-else>
                  <template v-for="(seg, sIdx) in rd.segments">
                    <div
                      v-if="seg.type === 'html'"
                      :key="'seg_html_' + item.id + '_' + sIdx"
                      class="message-text markdown-body"
                      v-html="seg.content"
                    ></div>
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
                </template>
              </div>
              <!-- 数据溯源卡片 -->
              <LineageSummaryCard
                v-if="item.lineageSummary"
                :summary="item.lineageSummary"
                :message-id="item.id"
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
        </DynamicScrollerItem>
      </template>

      <template #after>
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
              <!-- 流式内容也按 segments 渲染，使表格一出现即具查询/排序/导出能力 -->
              <template v-for="(seg, sIdx) in _cachedParseSegments(_streamingSegmentsMsg)">
                <div
                  v-if="seg.type === 'html'"
                  :key="'stream_seg_html_' + sIdx"
                  class="message-text markdown-body"
                  v-html="seg.content"
                ></div>
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
            <!-- 流式数据溯源卡片 -->
            <LineageSummaryCard
              v-if="streamingLineageSummary"
              :summary="streamingLineageSummary"
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
      </template>
    </DynamicScroller>

    <!-- 数据更新模板快捷栏 -->
    <DataUpdateTemplates
      v-if="showTemplates"
      @select-template="handleTemplateSelect"
    />

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
import { sendMessageStream } from '@/api/agent'
import { getSceneByKey, AGENT_SCENES } from '@/config/agentScenes'
import { quickQuestionLabel } from '@/config/creditRatingQuickAddons'
import { debounce } from 'lodash'
import { renderMarkdown, parseMessageSegments, getMessageCharts, getMessageDataTables, parseToolResult, throttle } from './chatUtils'
import PlanProgress from './PlanProgress.vue'
import ChatEmptyState from './ChatEmptyState.vue'
import ChatChartRenderer from './ChatChartRenderer.vue'
import ChatDataTable from './ChatDataTable.vue'
import ChatToolProgress from './ChatToolProgress.vue'
import ChatInputBox from './ChatInputBox.vue'
import DataUpdateTemplates from './DataUpdateTemplates.vue'
import DataImportCards from './DataImportCards.vue'
import LineageSummaryCard from './LineageSummaryCard.vue'
import AssetChartDialog from './AssetChartDialog.vue'
import BacktestDetailDialog from './BacktestDetailDialog.vue'

export default {
  name: 'AgentChatPanel',
  components: { PlanProgress, ChatEmptyState, ChatChartRenderer, ChatDataTable, ChatToolProgress, ChatInputBox, DataUpdateTemplates, DataImportCards, LineageSummaryCard, AssetChartDialog, BacktestDetailDialog },
  props: {
    conversationId: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      loadingMore: false,
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
      selectedBacktestRecord: null,
      /** 流式过程中收到的 lineage_summary */
      streamingLineageSummary: null
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
      }
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
    'messages.length': {
      handler() {
        this.$nextTick(() => {
          this.debouncedScrollToBottom()
        })
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
      if (scroller && scroller.$el) {
        scroller.$el.scrollTop = scroller.$el.scrollHeight
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
      const el = scroller ? scroller.$el : null
      const scrollHeightBefore = el ? el.scrollHeight : 0

      try {
        await this.$store.dispatch('agent/loadMoreMessages')

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
      this.pendingText = ''
      this.isInToolPhase = false
      this.completedToolSteps = []
      this.currentToolLabel = ''
      this.streamingLineageSummary = null
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
      const v = (content.length | 0) + '|' + ((tc && tc.length) || 0) + '|' + (msg.lineageSummary ? '1' : '0')
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
     * 从消息中提取所有可追踪回测记录（去重）
     * 优先使用后端显式提供的 traceable_backtests，
     * 若无则尝试从回测类工具结果中自动推断。
     */
    getMessageTraceableBacktests(msg) {
      if (!msg.tool_calls || !msg.tool_calls.length) return []
      const backtests = []
      const seen = new Set()
      // 回测相关工具名集合
      const BACKTEST_TOOLS = ['execute_backtest', 'compare_strategies', 'recommend_strategy']

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
      this.streamingLineageSummary = null
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
          if (this.streamingLineageSummary) {
            aiMsg.lineageSummary = Object.freeze(JSON.parse(JSON.stringify(this.streamingLineageSummary)))
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
        this.streamingLineageSummary = null
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

        case 'lineage_summary':
          this.streamingLineageSummary = data
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
