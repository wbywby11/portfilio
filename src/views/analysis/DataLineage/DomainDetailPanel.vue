<template>
  <div class="table-detail-panel">
    <div class="panel-header">
      <h4 style="margin:0">
        <span class="domain-abbr" v-if="domainAbbr">[{{ domainAbbr }}]</span>
        {{ domain ? domain.domain_name : '' }}
      </h4>
      <span class="close-btn" @click="$emit('close')" title="关闭">✕</span>
    </div>

    <div v-if="loading" class="panel-loading">
      <i class="el-icon-loading"></i> 加载中...
    </div>

    <div v-else-if="domain" class="panel-body">
      <!-- 描述 -->
      <div class="detail-section" v-if="domain.description">
        <div class="section-title">描述</div>
        <div class="info-row">{{ domain.description }}</div>
      </div>

      <!-- 核心场景 & 关键实体 -->
      <div class="detail-section" v-if="(domain.core_scenarios && domain.core_scenarios.length) || (domain.key_entities && domain.key_entities.length)">
        <div class="section-title">业务概要</div>
        <div class="info-row" v-if="domain.core_scenarios && domain.core_scenarios.length">
          <span class="info-label">核心场景：</span>
          <el-tag
            v-for="s in domain.core_scenarios"
            :key="s"
            size="mini"
            effect="plain"
            class="scenario-tag"
          >{{ s }}</el-tag>
        </div>
        <div class="info-row" v-if="domain.key_entities && domain.key_entities.length">
          <span class="info-label">关键实体：</span>
          <el-tag
            v-for="e in domain.key_entities"
            :key="e"
            size="mini"
            type="info"
            effect="plain"
            class="scenario-tag"
          >{{ e }}</el-tag>
        </div>
      </div>

      <!-- 包含表 -->
      <div class="detail-section" v-if="domain.tables && domain.tables.length">
        <div class="section-title">包含 {{ domain.table_count || domain.tables.length }} 张表</div>
        <div
          v-for="t in domain.tables"
          :key="t"
          class="table-item"
          @click="$emit('table-click', t)"
        >
          <span class="table-dot">·</span>
          <span class="table-name">{{ t }}</span>
        </div>
      </div>

      <!-- L2 域内画像 -->
      <div class="detail-section" v-if="domainProfile">
        <div class="section-title">L2 域内画像</div>
        <div class="profile-item" v-if="domainProfile.structure">
          <div class="profile-label">结构特征</div>
          <div class="profile-text">{{ domainProfile.structure }}</div>
        </div>
        <div class="profile-item" v-if="domainProfile.consistency">
          <div class="profile-label">一致性约束</div>
          <div class="profile-text">{{ domainProfile.consistency }}</div>
        </div>
        <div class="profile-item" v-if="domainProfile.distribution">
          <div class="profile-label">分布特征</div>
          <div class="profile-text">{{ domainProfile.distribution }}</div>
        </div>
        <div class="profile-item" v-if="domainProfile.anomaly">
          <div class="profile-label">异常排查</div>
          <div class="profile-text">{{ domainProfile.anomaly }}</div>
        </div>
        <div class="profile-item" v-if="domainProfile.join_keys">
          <div class="profile-label">关联键</div>
          <div class="profile-text">{{ domainProfile.join_keys }}</div>
        </div>
        <div class="profile-item" v-if="domainProfile.scenarios">
          <div class="profile-label">适用场景</div>
          <div class="profile-text">{{ domainProfile.scenarios }}</div>
        </div>
      </div>

      <!-- L5.2 域全局画像 -->
      <div class="detail-section">
        <div class="section-title">
          L5.2 域全局画像
          <el-button type="text" size="mini" @click="refreshMacro" :loading="macroGenerating">
            {{ domainMacro ? '🔄 刷新' : '⚡ 生成画像' }}
          </el-button>
        </div>
        <div v-if="macroLoading" class="macro-loading">
          <i class="el-icon-loading"></i> 正在加载...
        </div>
        <div v-else-if="domainMacro">
          <div class="profile-item"><span class="profile-label">域边界：</span><span class="profile-text">{{ domainMacro.boundary }}</span></div>
          <div class="profile-item"><span class="profile-label">宏观分布：</span><span class="profile-text">{{ domainMacro.macro_distribution }}</span></div>
          <div class="profile-item"><span class="profile-label">宏观趋势：</span><span class="profile-text">{{ domainMacro.macro_trend }}</span></div>
          <div class="profile-item"><span class="profile-label">系统预警：</span><span class="profile-text">{{ domainMacro.system_warning }}</span></div>
          <div class="computed-time">生成时间: {{ domainMacro.computed_at }}</div>
        </div>
        <div v-else class="macro-empty">
          <div class="empty-hint">域全局画像尚未生成</div>
          <el-button type="primary" size="small" @click="refreshMacro" :loading="macroGenerating">
            生成画像
          </el-button>
        </div>
      </div>

      <!-- 表级统计概要 -->
      <div class="detail-section" v-if="tablesStatsSummary && Object.keys(tablesStatsSummary).length">
        <div class="section-title">表级统计概要</div>
        <table class="tables-summary-table">
          <thead><tr><th>表名</th><th>记录数</th><th>字段数</th><th>异常率</th></tr></thead>
          <tbody>
            <tr v-for="(stat, tblName) in tablesStatsSummary" :key="tblName">
              <td class="tbl-name-cell">{{ tblName }}</td>
              <td>{{ stat.record_count != null ? stat.record_count.toLocaleString() : '-' }}</td>
              <td>{{ stat.field_count != null ? stat.field_count : '-' }}</td>
              <td :class="{'anomaly-high': stat.anomaly_ratio > 5}">
                {{ stat.anomaly_ratio != null ? stat.anomaly_ratio.toFixed(2) + '%' : '-' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 跨域联动入口 -->
      <div class="detail-section">
        <el-button type="primary" size="small" plain @click="$emit('show-resonance')">
          查看跨域联动(L5.3)
        </el-button>
      </div>
    </div>

    <div v-else class="panel-empty">
      暂无域画像数据
    </div>
  </div>
</template>

<script>
import { getDomainMacro, generateDomainMacro } from '@/api/semantic'

const DOMAIN_ABBR = {
  asset: 'AST',
  subject: 'ISR',
  product: 'PTL',
  valuation: 'VAL',
  transaction: 'TRN',
  seller: 'SALE',
  customer: 'CUS',
  risk: 'RSK',
  market: 'MKT'
}

export default {
  name: 'DomainDetailPanel',
  props: {
    domain: { type: Object, default: null },
    domainProfile: { type: Object, default: null },
    loading: { type: Boolean, default: false }
  },
  data() {
    return {
      domainMacro: null,
      tablesStatsSummary: null,
      macroLoading: false,
      macroGenerating: false
    }
  },
  computed: {
    domainAbbr() {
      if (!this.domain) return ''
      return DOMAIN_ABBR[this.domain.domain_code] || ''
    }
  },
  watch: {
    domain: {
      immediate: true,
      handler(val) {
        if (val && val.domain_code) {
          this.loadDomainMacro(val.domain_code)
        } else {
          this.domainMacro = null
        }
      }
    }
  },
  methods: {
    async loadDomainMacro(domainCode) {
      this.macroLoading = true
      try {
        const res = await getDomainMacro(domainCode)
        const data = res.data !== undefined ? res.data : res
        if (data) {
          this.domainMacro = data
          this.tablesStatsSummary = data.tables_stats_summary || null
        } else {
          // 后端返回 {data: null} 表示画像未生成
          this.domainMacro = null
          this.tablesStatsSummary = null
        }
      } catch (e) {
        this.domainMacro = null
        this.tablesStatsSummary = null
      } finally {
        this.macroLoading = false
      }
    },
    async refreshMacro() {
      if (!this.domain || !this.domain.domain_code) return
      this.macroGenerating = true
      try {
        const res = await generateDomainMacro(this.domain.domain_code)
        const data = res.data !== undefined ? res.data : res
        if (data) {
          this.domainMacro = data
          this.tablesStatsSummary = data.tables_stats_summary || null
        }
      } catch (e) {
        console.warn('生成域全局画像失败', e)
      } finally {
        this.macroGenerating = false
      }
    }
  }
}
</script>

<style scoped>
.table-detail-panel {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  position: relative;
  z-index: 10;
}
.domain-abbr {
  color: #409EFF;
  font-weight: 700;
  margin-right: 4px;
}
.close-btn {
  cursor: pointer;
  font-size: 18px;
  color: #909399;
  padding: 4px 8px;
  border-radius: 4px;
  line-height: 1;
  transition: all 0.2s;
  user-select: none;
}
.close-btn:hover {
  color: #303133;
  background: #f0f2f5;
}
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}
.panel-loading, .panel-empty {
  padding: 40px;
  text-align: center;
  color: #909399;
}
.detail-section {
  margin-bottom: 16px;
}
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #f0f2f5;
}
.info-row {
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
  line-height: 1.6;
}
.info-label {
  color: #909399;
  min-width: 50px;
  display: inline-block;
}
.scenario-tag {
  margin: 2px 4px 2px 0;
}
.profile-item {
  margin-bottom: 8px;
}
.profile-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 2px;
}
.profile-text {
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
}
.table-item {
  font-size: 12px;
  color: #409EFF;
  cursor: pointer;
  padding: 3px 0;
  line-height: 1.6;
  transition: color 0.2s;
}
.table-item:hover {
  color: #66b1ff;
  text-decoration: underline;
}
.table-dot {
  margin-right: 6px;
  color: #909399;
}
.table-name {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
}
.macro-loading {
  padding: 12px 0;
  text-align: center;
  color: #909399;
  font-size: 12px;
}
.macro-empty {
  padding: 16px 0;
  text-align: center;
  color: #909399;
  font-size: 12px;
}
.macro-empty .empty-hint {
  margin-bottom: 10px;
  font-size: 13px;
  color: #606266;
}
.computed-time {
  margin-top: 12px;
  font-size: 11px;
  color: #c0c4cc;
  border-top: 1px dashed #ebeef5;
  padding-top: 8px;
}
.tables-summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  margin-top: 4px;
}
.tables-summary-table th,
.tables-summary-table td {
  padding: 5px 6px;
  text-align: left;
  border-bottom: 1px solid #f0f2f5;
}
.tables-summary-table th {
  background: #fafafa;
  color: #909399;
  font-weight: 500;
}
.tables-summary-table td {
  color: #606266;
}
.tbl-name-cell {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 10px;
}
.anomaly-high {
  color: #f56c6c;
  font-weight: 600;
}
</style>
