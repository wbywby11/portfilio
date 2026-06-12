<template>
  <div class="lineage-summary-card" v-if="summary && summary.total_tables > 0">
    <!-- 折叠头部 -->
    <div class="lineage-header" @click.stop="toggleExpand">
      <i class="el-icon-connection"></i>
      <span class="lineage-title">数据溯源</span>
      <span class="lineage-badge">{{ summary.total_domains }} 域 · {{ summary.total_tables }} 表</span>
      <!-- 画像级别徽章 -->
      <el-tag v-for="profile in summary.profiles_used" :key="profile" size="mini" type="info" class="profile-tag">
        {{ formatProfileLevel(profile) }}
      </el-tag>
      <i :class="expanded ? 'el-icon-arrow-up' : 'el-icon-arrow-down'" class="expand-icon"></i>
    </div>

    <!-- 展开详情：使用 v-if 替代 v-show，避免折叠状态下仍渲染大量内部 DOM（多个 v-for 循环） -->
    <div class="lineage-detail" :class="{ 'is-expanded': expanded }" v-if="expanded" @click.stop>
      <!-- 域标签 -->
      <div class="lineage-section">
        <span class="section-label">涉及域：</span>
        <el-tag v-for="domain in summary.domains" :key="domain" size="small" :type="getDomainTagType(domain)" class="domain-tag">
          {{ getDomainName(domain) }}
        </el-tag>
      </div>

      <!-- 表清单（按贡献度分组） -->
      <div class="lineage-section">
        <span class="section-label">数据表：</span>

        <!-- 核心贡献表 -->
        <div v-if="primaryTables.length" class="table-group table-group-primary">
          <div class="group-header">
            <span class="group-label">核心贡献表</span>
            <span class="group-count">{{ primaryTables.length }}</span>
          </div>
          <div v-for="table in primaryTables" :key="table.name" class="table-item table-item-primary">
            <el-tag size="mini" effect="plain">{{ table.domain }}</el-tag>
            <span class="contribution-badge contrib-primary" title="实际返回了数据">数据源</span>
            <span class="table-name clickable" @click="openTableData(table)">{{ getTableDisplayName(table) }}</span>
            <span class="table-records" v-if="table.records_returned">({{ table.records_returned }} 条)</span>
            <span
              v-if="table.records_returned && table.records_returned <= 5"
              class="expand-inline-btn"
              @click.stop="toggleInline(table)"
            >
              {{ inlineExpanded[table.name] ? '收起' : '展开' }}
            </span>
          </div>
        </div>

        <!-- 辅助关联表 -->
        <div v-if="secondaryTables.length" class="table-group table-group-secondary">
          <div class="group-header">
            <span class="group-label">辅助关联表</span>
            <span class="group-count">{{ secondaryTables.length }}</span>
          </div>
          <div v-for="table in secondaryTables" :key="table.name" class="table-item table-item-secondary">
            <el-tag size="mini" effect="plain">{{ table.domain }}</el-tag>
            <span class="contribution-badge contrib-secondary" title="被 join/lookup 使用">关联</span>
            <span class="table-name clickable" @click="openTableData(table)">{{ getTableDisplayName(table) }}</span>
            <span class="table-records" v-if="table.records_returned">({{ table.records_returned }} 条)</span>
          </div>
        </div>

        <!-- 路由候选表（默认折叠） -->
        <div v-if="candidateTables.length" class="table-group table-group-candidate">
          <div class="group-header group-header-collapsed" @click.stop="toggleCandidateExpand">
            <span class="group-label">路由候选</span>
            <span class="group-count">{{ candidateTables.length }} 张</span>
            <i :class="candidateExpanded ? 'el-icon-arrow-up' : 'el-icon-arrow-down'"></i>
          </div>
          <template v-if="candidateExpanded">
            <div v-for="table in candidateTables" :key="table.name" class="table-item table-item-candidate">
              <el-tag size="mini" effect="plain">{{ table.domain }}</el-tag>
              <span class="contribution-badge contrib-candidate" title="仅路由推荐，未实际查询">候选</span>
              <span class="table-name clickable" @click="openTableData(table)">{{ getTableDisplayName(table) }}</span>
            </div>
          </template>
        </div>

        <!-- 内联迷你表格 -->
        <template v-for="table in summary.tables">
          <div v-if="inlineExpanded[table.name]" :key="'inline_' + table.name" class="inline-table-wrap">
            <el-table
              v-if="inlineData[table.name] && inlineData[table.name].length"
              :data="inlineData[table.name]"
              size="mini"
              border
              max-height="200"
              class="inline-mini-table"
            >
              <el-table-column
                v-for="col in getColumnsFor(table.name)"
                :key="col"
                :prop="col"
                :label="col"
                min-width="100"
                show-overflow-tooltip
              />
            </el-table>
            <div v-else class="inline-loading">
              <i class="el-icon-loading"></i> 加载中...
            </div>
          </div>
        </template>
      </div>

      <!-- 关联路径（结构化渲染） -->
      <div class="lineage-section" v-if="hasJoinPaths">
        <span class="section-label">关联路径：</span>
        <!-- 优先使用结构化格式 -->
        <template v-if="summary.join_paths_structured && summary.join_paths_structured.length">
          <div v-for="(jp, jpIdx) in summary.join_paths_structured" :key="jpIdx" class="join-structured-block">
            <div v-for="(cond, cIdx) in jp.conditions" :key="cIdx" class="join-condition-row" :title="'SQL: ' + cond.raw">
              <span class="jc-table jc-left" :title="cond.left_table">
                <span class="jc-zh">{{ cond.left_table_zh }}</span>
                <span class="jc-en" v-if="cond.left_table_zh !== cond.left_table">({{ cond.left_table }})</span>
              </span>
              <span class="jc-field jc-left-field" :class="getFieldRoleClass(cond.left_field)" :title="getFieldZh(cond.left_field)">
                {{ getFieldZh(cond.left_field) !== cond.left_field ? getFieldZh(cond.left_field) : cond.left_field }}
              </span>
              <span class="jc-arrow">→</span>
              <span class="jc-table jc-right" :title="cond.right_table">
                <span class="jc-zh">{{ cond.right_table_zh }}</span>
                <span class="jc-en" v-if="cond.right_table_zh !== cond.right_table">({{ cond.right_table }})</span>
              </span>
              <span class="jc-field jc-right-field" :class="getFieldRoleClass(cond.right_field)" :title="getFieldZh(cond.right_field)">
                {{ getFieldZh(cond.right_field) !== cond.right_field ? getFieldZh(cond.right_field) : cond.right_field }}
              </span>
            </div>
            <div v-if="jp.conditions.length" class="join-semantic-summary">
              <i class="el-icon-connection"></i>
              <span>{{ buildJoinSummary(jp.conditions) }}</span>
            </div>
          </div>
        </template>
        <!-- fallback: 原始格式 -->
        <template v-else>
          <div v-for="(path, idx) in summary.join_paths" :key="idx" class="join-path-enhanced">
            <template v-for="(seg, sIdx) in parseJoinPath(path)">
              <span v-if="seg.type === 'table'" :key="sIdx" class="jp-table" :title="seg.raw">
                <span class="jp-table-zh">{{ seg.zh }}</span>
                <span class="jp-table-en">{{ seg.raw }}</span>
              </span>
              <span v-else-if="seg.type === 'field'" :key="sIdx" :class="['jp-field', getFieldRoleClass(seg.raw)]" :title="getFieldZh(seg.raw) + ' [' + getFieldRole(seg.raw) + ']'">
                {{ getFieldZh(seg.raw) !== seg.raw ? getFieldZh(seg.raw) : seg.raw }}
              </span>
              <span v-else-if="seg.type === 'arrow'" :key="sIdx" class="jp-arrow">→</span>
              <span v-else :key="sIdx" class="jp-sep">{{ seg.raw }}</span>
            </template>
          </div>
        </template>
      </div>

      <!-- 字段摘要（增强中文提示+角色徽章） -->
      <div class="lineage-section" v-if="summary.fields_summary && Object.keys(summary.fields_summary).length > 0">
        <span class="section-label">访问字段：</span>
        <div v-for="(fields, table) in summary.fields_summary" :key="table" class="fields-item">
          <span class="fields-table" :title="table">{{ getTableZhName(table) }}:</span>
          <span v-for="f in fields.slice(0, 10)" :key="f" :class="['field-tag-enhanced', getFieldRoleClass(f)]" :title="getFieldZh(f) + ' [' + getFieldRole(f) + ']'">
            <span class="field-role-badge" v-if="getFieldRole(f) !== '普通'">{{ getFieldRole(f) }}</span>
            <span class="field-name-text">{{ getFieldZh(f) !== f ? getFieldZh(f) : f }}</span>
            <span class="field-en-text" v-if="getFieldZh(f) !== f">({{ f }})</span>
          </span>
          <span v-if="fields.length > 10" class="more-fields">+{{ fields.length - 10 }}</span>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="lineage-actions">
        <el-button size="mini" type="primary" plain icon="el-icon-view" @click="openLineageGraph">
          查看血缘图谱
        </el-button>
      </div>
    </div>

    <!-- 数据表格弹窗 -->
    <el-dialog
      :title="dataDialogTitle"
      :visible.sync="showDataDialog"
      width="850px"
      top="5vh"
      append-to-body
      destroy-on-close
      @close="onDataDialogClose"
    >
      <el-table
        v-if="dialogTableData.length"
        :data="dialogTableData"
        border
        size="small"
        max-height="420"
        style="width: 100%"
      >
        <el-table-column
          v-for="col in dialogTableColumns"
          :key="col"
          :prop="col"
          :label="col"
          min-width="120"
          show-overflow-tooltip
        />
      </el-table>
      <div v-if="dialogLoading" class="dialog-loading">
        <i class="el-icon-loading"></i> 加载数据中...
      </div>
      <div v-if="!dialogLoading && dialogTableTotal > dialogTableData.length" class="data-tip">
        仅展示前 {{ dialogTableData.length }} 条，共 {{ dialogTableTotal }} 条
      </div>
      <div v-if="!dialogLoading && !dialogTableData.length" class="data-tip">
        暂无数据
      </div>
    </el-dialog>

    <!-- 迷你血缘图弹窗 -->
    <el-dialog
      title="数据血缘关系"
      :visible.sync="showLineageDialog"
      width="700px"
      top="8vh"
      append-to-body
      destroy-on-close
      @opened="renderMiniGraph"
      @close="onLineageDialogClose"
    >
      <div ref="miniGraphContainer" style="width: 100%; height: 380px;"></div>
      <div v-if="lineageLoading" class="dialog-loading">
        <i class="el-icon-loading"></i> 加载图谱中...
      </div>
    </el-dialog>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getTableData, getLineageGraph } from '@/api/semantic'
import { TABLE_DISPLAY_NAMES as CHAT_TABLE_NAMES, KEY_FIELD_INFO } from './chatUtils'

/**
 * 模块级缓存：持久化各消息的 expanded / candidateExpanded 状态，防止 DynamicScroller
 * 触发组件卸载重建时丢失展开状态。
 */
const _expandedCache = Object.create(null)
const _candidateExpandedCache = Object.create(null)

// 域颜色映射
const DOMAIN_COLORS = {
  asset: '#409EFF',
  subject: '#67C23A',
  product: '#E6A23C',
  valuation: '#909399',
  transaction: '#F56C6C',
  seller: '#b37feb',
  customer: '#36cfc9',
  risk: '#ff4d4f',
  market: '#1890ff',
  data_hub: '#722ed1'
}

// 中文表名映射（本地补充，与 chatUtils.TABLE_DISPLAY_NAMES 合并使用）
const TABLE_DISPLAY_NAMES = {
  'dwd_ptl_info': '产品基本信息',
  'dwd_ptl_cedetail': '产品分红明细',
  'dwd_ptl_holder_summary': '产品持有人汇总',
  'dwd_ptl_ast_hld': '产品资产持仓',
  'dwd_val_detail': '估值明细',
  'dwd_val_valtable': '估值汇总表',
  'dwd_val_asset_detail': '资产估值明细',
  'dwd_val_income': '收入明细',
  'dwd_val_expense': '费用明细',
  'dwd_val_cash_flow': '现金流明细',
  'dwd_val_fx_exposure': '外汇敲口',
  'dwd_val_duration_bucket': '久期分桶',
  'dwd_val_concentration': '集中度',
  'dwd_ast_info': '资产基础信息表',
  'dwd_ast_info_ch': '中债估值表',
  'dwd_ast_info_zg': '中证估值表',
  'dwd_ast_yield_info': '收益率信息表',
  'dwd_ast_cf_plan': '现金流计划表',
  'dwd_ast_pledge': '质押信息表',
  'dwd_ast_flow_trade': '流通交易表',
  'dwd_ast_rating': '信用评级表',
  'dwd_ast_guarantor': '担保人信息表',
  'dwd_ast_clause': '条款信息表',
  'dwd_ast_holder': '资产持有人表',
  'dwd_ast_event': '生命周期事件表',
  'dwd_ast_bond': '债券资产信息',
  'dwd_ast_fund': '基金资产信息',
  'dwd_ast_stock': '股票资产信息',
  'dwd_isr_institution': '主体机构信息',
  'dwd_isr_institution_finance': '机构财务信息',
  'dwd_isr_trd_cntp': '交易对手',
  'dwd_isr_credit_rating': '信用评级',
  'dwd_mkt_bond': '债券行情表',
  'dwd_mkt_equity': '股票行情表',
  'dwd_mkt_fund': '基金净值行情表',
  'dwd_mkt_index': '指数行情表',
  'dwd_mkt_fx': '外汇行情表',
  'dwd_mkt_ir': '利率行情表',
  'dwd_mkt_commodity': '大宗商品行情表',
  'dwd_mkt_bond_valuation': '债券估值行情',
  'dwd_mkt_fund_nav': '基金净值行情',
  'dwd_mkt_stock_price': '股票价格行情',
  'dwd_mkt_calendar': '交易日历',
  'dwd_mkt_rating_action': '评级动作',
  'dwd_mkt_credit_spread': '信用利差',
  'dwd_txn_trade_record': '交易记录',
  'dwd_txn_settlement': '结算明细',
  'dwd_trn_order': '委托订单',
  'dwd_trn_trade_ast': '资产交易明细',
  'dwd_trn_settle': '结算明细',
  'dwd_sel_channel': '销售渠道',
  'dwd_sale_psn_info': '销售人员信息',
  'dwd_cst_info': '客户信息',
  'dwd_cust_info': '客户主表',
  'dwd_cust_make_pstn_info': '客户建仓信息表',
  'dwd_crtd_main_rela_rela_info': '主体关联关系信息表',
  'dwd_crtd_agme_info': '增信措施信息表',
  'dwd_rsk_credit_position': '信用风险持仓表',
  'dwd_ast_party': '资产参与方表',
  'dwd_ast_fiveclass': '资产五级分类表',
  'dwd_rsk_exposure': '风险敲口',
  'dwd_rsk_limit': '风险限额',
  'dwd_rsk_sentiment': '舆情事件',
  'dwd_rsk_credit': '内部信用评级',
  'dwd_rsk_guarantee': '担保信息',
  'dwd_rsk_event': '风险事件',
  'assets': '资产列表主数据',
  'asset_prices': '资产日频K线行情',
  'subject_risk_records': '主体观点风险记录',
  'zysc_ptl_info_records': '产品信息记录',
  'zysc_ptl_holder_records': '产品持有人汇总',
  'subject_risk_import_batches': '风险导入批次',
  'zysc_ptl_info_import_batches': '产品信息导入批次',
  'zysc_ptl_holder_import_batches': '持有人导入批次'
}

export default {
  name: 'LineageSummaryCard',
  props: {
    summary: {
      type: Object,
      default: () => null
    },
    /** 关联消息 ID，用于持久化展开状态 */
    messageId: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      expanded: this.messageId ? !!_expandedCache[this.messageId] : false,
      candidateExpanded: this.messageId ? !!_candidateExpandedCache[this.messageId] : false,
      // 内联展开相关
      inlineExpanded: {},
      inlineData: {},
      inlineColumns: {},
      // 数据弹窗相关
      showDataDialog: false,
      dataDialogTitle: '',
      dialogTableData: [],
      dialogTableColumns: [],
      dialogTableTotal: 0,
      dialogLoading: false,
      // 血缘图弹窗相关
      showLineageDialog: false,
      lineageLoading: false,
      miniChart: null
    }
  },
  computed: {
    /** 核心贡献表：实际返回了数据的表 */
    primaryTables() {
      if (!this.summary || !this.summary.tables) return []
      return this.summary.tables.filter(t => t.contribution_level === 'primary')
    },
    /** 辅助关联表：被 join/lookup 使用的表 */
    secondaryTables() {
      if (!this.summary || !this.summary.tables) return []
      return this.summary.tables.filter(t => t.contribution_level === 'secondary')
    },
    /** 路由候选表：仅 smart_router 推荐，未实际查询 */
    candidateTables() {
      if (!this.summary || !this.summary.tables) return []
      return this.summary.tables.filter(t => t.contribution_level === 'candidate')
    },
    /** 是否有关联路径 */
    hasJoinPaths() {
      if (!this.summary) return false
      return (this.summary.join_paths_structured && this.summary.join_paths_structured.length > 0) ||
             (this.summary.join_paths && this.summary.join_paths.length > 0)
    }
  },
  watch: {
    messageId(newId) {
      this.expanded = newId ? !!_expandedCache[newId] : false
      this.candidateExpanded = newId ? !!_candidateExpandedCache[newId] : false
    }
  },
  beforeDestroy() {
    if (this.miniChart) {
      this.miniChart.dispose()
      this.miniChart = null
    }
  },
  methods: {
    toggleExpand() {
      this.expanded = !this.expanded
      if (this.messageId) {
        _expandedCache[this.messageId] = this.expanded
      }
    },
    toggleCandidateExpand() {
      this.candidateExpanded = !this.candidateExpanded
      if (this.messageId) {
        _candidateExpandedCache[this.messageId] = this.candidateExpanded
      }
    },
    getDomainName(code) {
      const map = {
        asset: '资产域', subject: '主体域', product: '产品域',
        valuation: '估值域', transaction: '交易域', seller: '销售域',
        customer: '客户域', risk: '风险域', market: '行情域',
        data_hub: '数据接入域'
      }
      return map[code] || code
    },
    getDomainTagType(domain) {
      const types = {
        asset: '', subject: 'success', product: 'warning',
        valuation: 'info', transaction: 'danger', customer: 'success',
        risk: 'danger', market: 'info', seller: '', data_hub: 'warning'
      }
      return types[domain] || ''
    },
    formatProfileLevel(profile) {
      if (profile.startsWith('l1_')) return 'L1'
      if (profile.startsWith('l2_')) return 'L2'
      if (profile.startsWith('l3_')) return 'L3'
      if (profile.startsWith('l4_')) return 'L4'
      return profile
    },
    getTableDisplayName(table) {
      // 后端 display_name 与原始表名相同时，视为未提供中文名，回退到本地映射
      const dn = table.display_name
      const hasZh = dn && dn !== table.name
      const displayName = hasZh ? dn : (TABLE_DISPLAY_NAMES[table.name] || CHAT_TABLE_NAMES[table.name])
      if (displayName && displayName !== table.name) return `${displayName}(${table.name})`
      return table.name
    },
    /** 获取表的中文名（用于字段摘要区域） */
    getTableZhName(tableName) {
      return TABLE_DISPLAY_NAMES[tableName] || CHAT_TABLE_NAMES[tableName] || tableName
    },
    /** 获取字段的中文名 */
    getFieldZh(field) {
      if (KEY_FIELD_INFO[field]) return KEY_FIELD_INFO[field].zh
      return field
    },
    /** 获取字段的角色名称 */
    getFieldRole(field) {
      if (KEY_FIELD_INFO[field]) return KEY_FIELD_INFO[field].role
      // 启发式推断
      if (field.endsWith('_id') || field.endsWith('_ID') || field.endsWith('_cd') || field.endsWith('_CD')) return 'PK'
      if (field.endsWith('_nm') || field.endsWith('_NM')) return '名称'
      return '普通'
    },
    /** 获取字段角色的 CSS 类名 */
    getFieldRoleClass(field) {
      if (KEY_FIELD_INFO[field]) return KEY_FIELD_INFO[field].roleClass
      if (field.endsWith('_id') || field.endsWith('_ID') || field.endsWith('_cd') || field.endsWith('_CD')) return 'field-pk'
      if (field.endsWith('_nm') || field.endsWith('_NM')) return 'field-link'
      return ''
    },
    /** 解析关联路径字符串为结构化段落（fallback） */
    parseJoinPath(pathStr) {
      if (!pathStr) return [{ type: 'text', raw: pathStr }]
      const segments = []
      // 分割: table.field → table.field 或 table.field -> table.field
      const parts = pathStr.split(/\s*[→\-\>]+\s*/)
      parts.forEach((part, idx) => {
        if (idx > 0) segments.push({ type: 'arrow' })
        const dotIdx = part.indexOf('.')
        if (dotIdx > 0) {
          const tbl = part.slice(0, dotIdx)
          const fld = part.slice(dotIdx + 1)
          const tblZh = TABLE_DISPLAY_NAMES[tbl] || CHAT_TABLE_NAMES[tbl] || tbl
          segments.push({ type: 'table', raw: tbl, zh: tblZh })
          segments.push({ type: 'text', raw: '.' })
          segments.push({ type: 'field', raw: fld })
        } else {
          segments.push({ type: 'text', raw: part })
        }
      })
      return segments
    },
    /** 构建 join 语义摘要（用于结构化显示下方） */
    buildJoinSummary(conditions) {
      if (!conditions || !conditions.length) return ''
      // 统计涉及的主要关联字段
      const keyFields = new Set()
      const keyTables = new Set()
      conditions.forEach(c => {
        if (c.left_field === c.right_field) {
          keyFields.add(c.left_field_zh !== c.left_field ? c.left_field_zh : c.left_field)
        }
        keyTables.add(c.left_table_zh)
        keyTables.add(c.right_table_zh)
      })
      const tablesArr = Array.from(keyTables)
      const fieldsArr = Array.from(keyFields)
      let summary = `本次分析跨 ${tablesArr.length} 张表`
      if (tablesArr.length <= 4) {
        summary += `（${tablesArr.join('、')}）`
      }
      if (fieldsArr.length > 0 && fieldsArr.length <= 5) {
        summary += `，通过 ${fieldsArr.join('、')} 关联`
      }
      summary += `，共 ${conditions.length} 条关联条件`
      return summary
    },
    getColumnsFor(tableName) {
      return this.inlineColumns[tableName] || []
    },

    // ========== 内联展开 ==========
    async toggleInline(table) {
      const name = table.name
      this.$set(this.inlineExpanded, name, !this.inlineExpanded[name])
      if (this.inlineExpanded[name] && !this.inlineData[name]) {
        await this.loadInlineData(name, table.records_returned || 5)
      }
    },
    async loadInlineData(tableName, limit) {
      try {
        const res = await getTableData(tableName, limit)
        const data = res && res.data ? res.data : res
        const records = data.records || []
        this.$set(this.inlineData, tableName, records)
        if (records.length > 0) {
          this.$set(this.inlineColumns, tableName, Object.keys(records[0]))
        }
      } catch (e) {
        console.error('[LineageSummary] 加载内联数据失败:', e)
        this.$set(this.inlineData, tableName, [])
      }
    },

    // ========== 数据表格弹窗 ==========
    async openTableData(table) {
      const displayName = table.display_name || TABLE_DISPLAY_NAMES[table.name] || ''
      this.dataDialogTitle = displayName
        ? `${displayName} (${table.name})`
        : table.name
      this.dialogTableData = []
      this.dialogTableColumns = []
      this.dialogTableTotal = 0
      this.dialogLoading = true
      this.showDataDialog = true

      try {
        const limit = (table.records_returned && table.records_returned <= 20) ? table.records_returned : 20
        const res = await getTableData(table.name, limit)
        const data = res && res.data ? res.data : res
        this.dialogTableData = data.records || []
        this.dialogTableTotal = data.total || 0
        if (this.dialogTableData.length > 0) {
          this.dialogTableColumns = Object.keys(this.dialogTableData[0])
        }
      } catch (e) {
        console.error('[LineageSummary] 加载表数据失败:', e)
        this.$message.error('加载数据失败')
      } finally {
        this.dialogLoading = false
      }
    },
    onDataDialogClose() {
      this.dialogTableData = []
      this.dialogTableColumns = []
    },

    // ========== 迷你血缘图弹窗 ==========
    openLineageGraph(e) {
      if (e) e.stopPropagation()
      this.showLineageDialog = true
      this.lineageLoading = true
    },
    async renderMiniGraph() {
      try {
        const res = await getLineageGraph()
        const graphData = res && res.data ? res.data : res
        const allNodes = graphData.nodes || []
        const allEdges = graphData.edges || []

        // 只保留本次溯源涉及的表
        const involvedTables = new Set(
          (this.summary.tables || []).map(t => t.name)
        )

        // 过滤节点
        const filteredNodes = allNodes.filter(n => involvedTables.has(n.id))
        const nodeIds = new Set(filteredNodes.map(n => n.id))

        // 过滤边：两端都在涉及表集合中
        const filteredEdges = allEdges.filter(
          e => nodeIds.has(e.source) && nodeIds.has(e.target)
        )

        this.lineageLoading = false
        this.$nextTick(() => {
          this.drawMiniChart(filteredNodes, filteredEdges)
        })
      } catch (e) {
        console.error('[LineageSummary] 加载图谱失败:', e)
        this.lineageLoading = false
      }
    },
    drawMiniChart(nodes, edges) {
      const container = this.$refs.miniGraphContainer
      if (!container) return

      if (this.miniChart) {
        this.miniChart.dispose()
      }
      this.miniChart = echarts.init(container)

      const categoryKeys = Object.keys(DOMAIN_COLORS)
      const categories = categoryKeys.map(code => ({
        name: this.getDomainName(code)
      }))

      const chartNodes = nodes.map(node => {
        const domain = node.domain || node.category || 'asset'
        const catIdx = categoryKeys.indexOf(domain)
        return {
          id: node.id,
          name: node.name || node.id,
          category: catIdx >= 0 ? catIdx : 0,
          symbolSize: 36,
          label: { show: true, fontSize: 10 },
          itemStyle: {
            borderWidth: 2,
            borderColor: DOMAIN_COLORS[domain] || '#409EFF'
          }
        }
      })

      // 计算平行边 curveness 分配
      const edgePairCount = {}
      edges.forEach(edge => {
        const pairKey = [edge.source, edge.target].sort().join('||')
        edgePairCount[pairKey] = (edgePairCount[pairKey] || 0) + 1
      })
      const edgePairCurrent = {}

      const chartEdges = edges.map(edge => {
        // 平行边 curveness 分散
        const pairKey = [edge.source, edge.target].sort().join('||')
        const total = edgePairCount[pairKey] || 1
        edgePairCurrent[pairKey] = (edgePairCurrent[pairKey] || 0)
        const idx = edgePairCurrent[pairKey]++
        let curveness = 0.15
        if (total > 1) {
          const spread = 0.12
          curveness = 0.05 + spread * (idx - (total - 1) / 2)
        }

        // 双语标签：中文(英文)
        const fieldEn = edge.source_field || edge.label || ''
        const fieldZh = edge.field_display || ''
        let bilingualLabel = ''
        if (fieldZh && fieldZh !== fieldEn) {
          bilingualLabel = `${fieldZh}(${fieldEn})`
        } else {
          bilingualLabel = fieldEn
        }
        const maxLen = 16
        const shortLabel = bilingualLabel.length > maxLen
          ? bilingualLabel.slice(0, maxLen - 1) + '…'
          : bilingualLabel

        return {
          source: edge.source,
          target: edge.target,
          _edgeData: edge,
          label: {
            show: !!shortLabel,
            formatter: shortLabel,
            fontSize: 9,
            fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif',
            color: '#666',
            backgroundColor: 'rgba(255,255,255,0.92)',
            borderColor: 'rgba(0,0,0,0.06)',
            borderWidth: 1,
            padding: [2, 5],
            borderRadius: 4,
            distance: 6
          },
          lineStyle: {
            type: edge.type === 'foreign_key' ? 'solid' : 'dashed',
            curveness,
            width: 1.5
          }
        }
      })

      const option = {
        tooltip: {
          trigger: 'item',
          formatter: (params) => {
            if (params.dataType === 'node') {
              const displayName = TABLE_DISPLAY_NAMES[params.data.id] || ''
              return displayName
                ? `<b>${displayName}</b><br/>${params.data.id}`
                : `<b>${params.data.name}</b>`
            }
            if (params.dataType === 'edge') {
              const d = params.data._edgeData || {}
              const lines = []
              lines.push(`<b style="color:#333;font-size:13px">${d.source_display || d.source} → ${d.target_display || d.target}</b>`)
              if (d.relation_desc) {
                lines.push(`<br/><span style="color:#555">${d.relation_desc}</span>`)
              }
              const srcField = d.source_field || d.label || ''
              const tgtField = d.target_field || ''
              const srcZh = d.field_display || ''
              const tgtZh = d.target_field_display || ''
              const srcDef = d.field_definition || ''
              const tgtDef = d.target_field_definition || ''
              if (srcField) {
                const srcPart = srcZh && srcZh !== srcField ? `${srcZh} <span style="color:#999">(${srcField})</span>` : srcField
                lines.push(`<br/><span style="padding:2px 6px;background:#f5f7fa;border-radius:3px;font-size:11px">🔑 源字段：${srcPart}`)
                if (srcDef) lines.push(`<br/><span style="color:#888;font-size:11px">&nbsp;&nbsp;${srcDef}</span>`)
                lines.push('</span>')
              }
              if (tgtField) {
                const tgtPart = tgtZh && tgtZh !== tgtField ? `${tgtZh} <span style="color:#999">(${tgtField})</span>` : tgtField
                lines.push(`<br/><span style="padding:2px 6px;background:#f0f9eb;border-radius:3px;font-size:11px">🎯 目标字段：${tgtPart}`)
                if (tgtDef) lines.push(`<br/><span style="color:#888;font-size:11px">&nbsp;&nbsp;${tgtDef}</span>`)
                lines.push('</span>')
              }
              return lines.join('')
            }
            return ''
          }
        },
        legend: {
          data: categories.map(c => c.name),
          orient: 'horizontal',
          top: 0,
          textStyle: { fontSize: 11 }
        },
        series: [{
          type: 'graph',
          layout: 'force',
          data: chartNodes,
          links: chartEdges,
          categories: categories,
          roam: true,
          draggable: true,
          force: {
            repulsion: 420,
            edgeLength: [110, 240],
            gravity: 0.1,
            friction: 0.55
          },
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: [0, 7],
          emphasis: {
            focus: 'adjacency',
            lineStyle: { width: 3 },
            label: { fontSize: 11 }
          },
          lineStyle: {
            color: '#b0b0b0',
            width: 1.5,
            opacity: 0.65
          },
          label: {
            show: true,
            position: 'bottom',
            fontSize: 10,
            fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif',
            color: '#444',
            backgroundColor: 'rgba(255,255,255,0.75)',
            padding: [2, 4],
            borderRadius: 3,
            distance: 5
          },
          labelLayout: {
            hideOverlap: true
          },
          animationDuration: 600,
          animationEasingUpdate: 'quinticInOut'
        }],
        color: Object.values(DOMAIN_COLORS)
      }

      this.miniChart.setOption(option, true)
    },
    onLineageDialogClose() {
      if (this.miniChart) {
        this.miniChart.dispose()
        this.miniChart = null
      }
    }
  }
}
</script>

<style scoped>
.lineage-summary-card {
  margin-top: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fafbfc;
  overflow: hidden;
}
.lineage-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  gap: 8px;
}
.lineage-header:hover {
  background: #f0f2f5;
}
.lineage-title {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}
.lineage-badge {
  font-size: 12px;
  color: #909399;
  background: #f0f2f5;
  padding: 2px 8px;
  border-radius: 10px;
}
.profile-tag {
  margin-left: 4px;
}
.expand-icon {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}
.lineage-detail {
  padding: 8px 12px 12px;
  border-top: 1px solid #ebeef5;
  will-change: auto;
}
.lineage-section {
  margin-bottom: 10px;
}
.section-label {
  font-size: 12px;
  color: #606266;
  font-weight: 500;
  display: inline-block;
  min-width: 70px;
}
.domain-tag {
  margin: 2px 4px 2px 0;
}
.table-list {
  margin-top: 4px;
}
.table-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  font-size: 12px;
}
.table-name {
  color: #303133;
}
.table-name.clickable {
  color: #409EFF;
  cursor: pointer;
  border-bottom: 1px dashed #409EFF;
}
.table-name.clickable:hover {
  color: #66b1ff;
}
.table-records {
  color: #909399;
  font-size: 11px;
}
.expand-inline-btn {
  font-size: 11px;
  color: #409EFF;
  cursor: pointer;
  margin-left: 4px;
  user-select: none;
}
.expand-inline-btn:hover {
  color: #66b1ff;
}
.inline-table-wrap {
  margin: 6px 0 8px 28px;
  border-radius: 4px;
  overflow: hidden;
}
.inline-mini-table {
  font-size: 11px;
}
.inline-loading {
  padding: 8px 12px;
  font-size: 12px;
  color: #909399;
}
.join-path {
  margin: 4px 0;
}
.join-path code {
  font-size: 11px;
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 3px;
  color: #606266;
}
/* 增强关联路径 */
.join-path-enhanced {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 3px;
  margin: 5px 0;
  padding: 6px 10px;
  background: #f8fafb;
  border-radius: 4px;
  border: 1px solid #eef1f5;
}
.jp-table {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  padding: 1px 6px;
  background: linear-gradient(135deg, #e8f4fd 0%, #f0f7ff 100%);
  border: 1px solid #bdd7f5;
  border-radius: 3px;
  cursor: help;
}
.jp-table-zh {
  font-size: 11.5px;
  color: #1a73e8;
  font-weight: 500;
}
.jp-table-en {
  font-size: 9.5px;
  color: #7bafd4;
  font-family: 'Menlo', monospace;
}
.jp-field {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
  font-family: 'Menlo', monospace;
  cursor: help;
}
.jp-field.field-pk {
  background: #fff3e0;
  color: #e65100;
  border: 1px solid #ffcc80;
  font-weight: 600;
}
.jp-field.field-link {
  background: #fce4ec;
  color: #880e4f;
  border: 1px solid #f48fb1;
}
.jp-field.field-biz {
  background: #f3e5f5;
  color: #4a148c;
  border: 1px solid #ce93d8;
}
.jp-arrow {
  color: #ff6f00;
  font-weight: 700;
  font-size: 13px;
  padding: 0 2px;
}
.jp-sep {
  color: #909399;
  font-size: 11px;
}
.fields-item {
  margin: 4px 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.fields-table {
  font-size: 11px;
  color: #909399;
  min-width: 100px;
}
.field-tag {
  margin: 1px;
}
/* 增强字段标签 */
.field-tag-enhanced {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin: 2px 3px;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  cursor: help;
  border: 1px solid #dcdfe6;
  background: #f5f7fa;
  transition: all 0.15s;
}
.field-tag-enhanced:hover {
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.field-tag-enhanced.field-pk {
  background: #fff8f0;
  border-color: #ffcc80;
}
.field-tag-enhanced.field-link {
  background: #fef0f5;
  border-color: #f48fb1;
}
.field-tag-enhanced.field-biz {
  background: #f8f0fc;
  border-color: #ce93d8;
}
.field-role-badge {
  display: inline-block;
  font-size: 9px;
  padding: 0 3px;
  border-radius: 2px;
  background: #e0e0e0;
  color: #555;
  font-weight: 600;
  line-height: 16px;
}
.field-pk .field-role-badge { background: #ffcc80; color: #e65100; }
.field-link .field-role-badge { background: #f48fb1; color: #880e4f; }
.field-biz .field-role-badge { background: #ce93d8; color: #4a148c; }
.field-name-text {
  font-size: 11px;
  color: #303133;
}
.field-en-text {
  font-size: 9.5px;
  color: #909399;
  font-family: 'Menlo', monospace;
}
.more-fields {
  font-size: 11px;
  color: #909399;
}
.lineage-actions {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #ebeef5;
}

/* ── 贡献度分组样式 ── */
.table-group {
  margin: 6px 0;
}
.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  padding: 2px 0;
}
.group-label {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
}
.group-count {
  font-size: 10px;
  color: #909399;
  background: #f0f2f5;
  padding: 1px 6px;
  border-radius: 8px;
}
.group-header-collapsed {
  cursor: pointer;
  user-select: none;
}
.group-header-collapsed:hover {
  background: #f5f7fa;
  border-radius: 4px;
}
.table-group-primary .table-item {
  border-left: 3px solid #67C23A;
  padding-left: 8px;
  margin: 3px 0;
}
.table-group-secondary .table-item {
  border-left: 3px solid #909399;
  padding-left: 8px;
  margin: 3px 0;
  opacity: 0.85;
}
.table-group-candidate {
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
  padding: 4px 8px;
  background: #fafbfc;
}
.table-group-candidate .table-item {
  margin: 2px 0;
  opacity: 0.7;
}
.table-group-candidate .table-item:hover {
  opacity: 1;
}
/* 贡献度徽章 */
.contribution-badge {
  display: inline-block;
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 500;
  line-height: 16px;
  vertical-align: middle;
}
.contrib-primary {
  background: #f0f9eb;
  color: #67C23A;
  border: 1px solid #c2e7b0;
}
.contrib-secondary {
  background: #f4f4f5;
  color: #909399;
  border: 1px solid #d3d4d6;
}
.contrib-candidate {
  background: #fafafa;
  color: #c0c4cc;
  border: 1px solid #e4e7ed;
}

/* ── 结构化关联路径样式 ── */
.join-structured-block {
  margin: 6px 0;
  padding: 8px 12px;
  background: #f8fafb;
  border-radius: 6px;
  border: 1px solid #eef1f5;
}
.join-condition-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  padding: 3px 0;
  font-size: 11px;
  border-bottom: 1px dashed #eef1f5;
}
.join-condition-row:last-child {
  border-bottom: none;
}
.jc-table {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  padding: 2px 6px;
  background: linear-gradient(135deg, #e8f4fd 0%, #f0f7ff 100%);
  border: 1px solid #bdd7f5;
  border-radius: 3px;
  cursor: help;
}
.jc-zh {
  font-size: 11.5px;
  color: #1a73e8;
  font-weight: 500;
}
.jc-en {
  font-size: 9.5px;
  color: #7bafd4;
  font-family: 'Menlo', 'Consolas', monospace;
}
.jc-field {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10.5px;
  font-family: 'Menlo', 'Consolas', monospace;
  cursor: help;
  background: #f5f7fa;
  border: 1px solid #dcdfe6;
}
.jc-field.field-pk {
  background: #fff8f0;
  color: #e65100;
  border-color: #ffcc80;
  font-weight: 600;
}
.jc-field.field-fk {
  background: #e8f5e9;
  color: #2e7d32;
  border-color: #a5d6a7;
}
.jc-field.field-link {
  background: #fce4ec;
  color: #880e4f;
  border-color: #f48fb1;
}
.jc-field.field-biz {
  background: #f3e5f5;
  color: #4a148c;
  border-color: #ce93d8;
}
.jc-arrow {
  color: #ff6f00;
  font-weight: 700;
  font-size: 14px;
  padding: 0 4px;
}
.join-semantic-summary {
  margin-top: 6px;
  padding: 4px 8px;
  background: #fff;
  border-radius: 4px;
  border-left: 3px solid #409EFF;
  font-size: 11.5px;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 6px;
}
.join-semantic-summary i {
  color: #409EFF;
  font-size: 13px;
}
.dialog-loading {
  text-align: center;
  padding: 30px;
  color: #909399;
  font-size: 14px;
}
.data-tip {
  margin-top: 10px;
  padding: 6px 0;
  text-align: center;
  font-size: 12px;
  color: #909399;
  border-top: 1px dashed #ebeef5;
}
</style>
