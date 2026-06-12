<template>
  <div class="table-detail-panel">
    <div class="panel-header">
      <h4 style="margin:0">{{ profile ? profile.display_name : tableName }}</h4>
      <span class="close-btn" @click="$emit('close')" title="关闭">✕</span>
    </div>

    <div v-if="loading" class="panel-loading">
      <i class="el-icon-loading"></i> 加载中...
    </div>

    <div v-else-if="profile" class="panel-body">
      <el-tabs v-model="activeTab" @tab-click="handleTabChange">
        <el-tab-pane label="基本画像" name="basic">
          <!-- 基本信息 -->
          <div class="detail-section">
            <div class="section-title">表信息</div>
            <div class="info-row"><span class="info-label">表名：</span>{{ profile.table_name }}</div>
            <div class="info-row"><span class="info-label">所属域：</span>{{ profile.domain }}</div>
            <div class="info-row" v-if="profile.record_count != null">
              <span class="info-label">记录数：</span>{{ profile.record_count.toLocaleString() }}
            </div>
          </div>

          <!-- 业务画像 -->
          <div class="detail-section">
            <div class="section-title">业务画像</div>
            <div class="profile-item" v-if="profile.purpose">
              <div class="profile-label">作用</div>
              <div class="profile-text">{{ profile.purpose }}</div>
            </div>
            <div class="profile-item" v-if="profile.distribution">
              <div class="profile-label">分布特征</div>
              <div class="profile-text">{{ profile.distribution }}</div>
            </div>
            <div class="profile-item" v-if="profile.trend">
              <div class="profile-label">趋势特征</div>
              <div class="profile-text">{{ profile.trend }}</div>
            </div>
            <div class="profile-item" v-if="profile.anomaly">
              <div class="profile-label">异常特征</div>
              <div class="profile-text">{{ profile.anomaly }}</div>
            </div>
          </div>

          <!-- 适用场景 -->
          <div class="detail-section" v-if="profile.scenarios && profile.scenarios.length">
            <div class="section-title">适用场景</div>
            <el-tag
              v-for="s in profile.scenarios"
              :key="s"
              size="small"
              effect="plain"
              class="scenario-tag"
            >{{ s }}</el-tag>
          </div>

          <!-- 字段画像 -->
          <div class="detail-section" v-if="profile.field_profiles && profile.field_profiles.length">
            <div class="section-title">字段画像（{{ profile.field_profiles.length }}个）</div>
            <el-collapse accordion>
              <el-collapse-item
                v-for="field in profile.field_profiles"
                :key="field.field_name"
                :title="field.display_name + ' (' + field.field_name + ')'"
              >
                <div class="field-detail">
                  <div class="info-row"><span class="info-label">类型：</span>{{ field.data_type }}</div>
                  <div class="info-row" v-if="field.definition">
                    <span class="info-label">定义：</span>{{ field.definition }}
                  </div>
                  <div class="info-row" v-if="field.unit">
                    <span class="info-label">单位：</span>{{ field.unit }}
                  </div>
                  <div class="info-row" v-if="field.references">
                    <span class="info-label">外键：</span>{{ field.references }}
                  </div>
                  <div class="field-tags">
                    <el-tag v-if="field.is_primary_key" size="mini" type="danger">主键</el-tag>
                    <el-tag v-if="field.is_foreign_key" size="mini" type="warning">外键</el-tag>
                    <el-tag v-if="field.is_time_series" size="mini" type="info">时序</el-tag>
                    <el-tag v-for="t in (field.tags || [])" :key="t" size="mini">{{ t }}</el-tag>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- 外键关联 -->
          <div class="detail-section" v-if="profile.foreign_keys && Object.keys(profile.foreign_keys).length">
            <div class="section-title">外键关联</div>
            <div v-for="(ref, fk) in profile.foreign_keys" :key="fk" class="info-row">
              <code>{{ fk }}</code> → <code>{{ ref }}</code>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="统计画像(L5)" name="stats">
          <!-- LLM画像区块 -->
          <div class="detail-section">
            <div class="section-title">
              L5.1 统计语义画像
              <el-button
                type="text"
                size="mini"
                :loading="statsLoading"
                @click="handleGenerateStats"
              >{{ statsProfile ? '🔄 刷新' : '⚡ 生成画像' }}</el-button>
            </div>
            <div v-if="statsLoading" class="stats-loading">
              <i class="el-icon-loading"></i> 正在生成画像，请稍候...
            </div>
            <div v-else-if="statsProfile" class="stats-content">
              <div class="profile-item">
                <div class="profile-label">📊 物理基础</div>
                <div class="profile-text">{{ statsProfile.physical_basis }}</div>
              </div>
              <div class="profile-item">
                <div class="profile-label">📈 截面分布</div>
                <div class="profile-text">{{ statsProfile.distribution }}</div>
              </div>
              <div class="profile-item">
                <div class="profile-label">📉 时序趋势</div>
                <div class="profile-text">{{ statsProfile.trend }}</div>
              </div>
              <div class="profile-item">
                <div class="profile-label">⚠️ 异常极值</div>
                <div class="profile-text">{{ statsProfile.anomaly }}</div>
              </div>
              <div class="computed-time">生成时间: {{ statsProfile.computed_at }}</div>
            </div>
            <div v-else class="stats-empty">
              <div class="empty-hint">画像尚未生成</div>
              <el-button type="primary" size="small" @click="handleGenerateStats" :loading="statsLoading">
                生成画像
              </el-button>
            </div>
          </div>

          <!-- 原始统计指标区块 -->
          <div class="detail-section" v-if="rawStats">
            <div class="section-title">原始统计指标</div>

            <!-- 记录数 -->
            <div class="info-row" v-if="rawStats.record_count != null">
              <span class="info-label">记录数：</span>
              <span class="raw-stat-value">{{ rawStats.record_count.toLocaleString() }}</span>
            </div>

            <!-- 字段覆盖率 -->
            <div class="raw-stat-block" v-if="rawStats.field_coverage && Object.keys(rawStats.field_coverage).length">
              <div class="raw-stat-label">字段覆盖率</div>
              <div class="coverage-tags">
                <el-tag
                  v-for="(pct, field) in rawStats.field_coverage"
                  :key="field"
                  size="mini"
                  :type="pct >= 95 ? 'success' : pct >= 80 ? '' : 'warning'"
                  effect="plain"
                  class="coverage-tag"
                >{{ field }}: {{ typeof pct === 'number' ? pct.toFixed(1) + '%' : pct }}</el-tag>
              </div>
            </div>

            <!-- 数值分布 -->
            <div class="raw-stat-block" v-if="rawStats.numeric_stats && Object.keys(rawStats.numeric_stats).length">
              <div class="raw-stat-label">数值分布</div>
              <table class="numeric-stats-table">
                <thead><tr><th>字段</th><th>min</th><th>max</th><th>mean</th></tr></thead>
                <tbody>
                  <tr v-for="(stat, field) in rawStats.numeric_stats" :key="field">
                    <td>{{ field }}</td>
                    <td>{{ stat.min != null ? Number(stat.min).toLocaleString(undefined, {maximumFractionDigits: 4}) : '-' }}</td>
                    <td>{{ stat.max != null ? Number(stat.max).toLocaleString(undefined, {maximumFractionDigits: 4}) : '-' }}</td>
                    <td>{{ stat.mean != null ? Number(stat.mean).toLocaleString(undefined, {maximumFractionDigits: 4}) : '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 分类分布 -->
            <div class="raw-stat-block" v-if="rawStats.categorical_distribution && Object.keys(rawStats.categorical_distribution).length">
              <div class="raw-stat-label">分类分布</div>
              <div v-for="(dist, field) in rawStats.categorical_distribution" :key="field" class="categorical-item">
                <span class="categorical-field">{{ field }}:</span>
                <span v-for="(val, label) in dist" :key="label" class="categorical-entry">
                  {{ label }} {{ typeof val === 'number' && val <= 1 ? (val * 100).toFixed(1) + '%' : val }}
                </span>
              </div>
            </div>

            <!-- 日期范围 -->
            <div class="info-row" v-if="rawStats.date_range">
              <span class="info-label">日期范围：</span>
              <span class="raw-stat-value">{{ rawStats.date_range.start || rawStats.date_range.min || '-' }} ~ {{ rawStats.date_range.end || rawStats.date_range.max || '-' }}</span>
            </div>

            <!-- 近期趋势 -->
            <div class="info-row" v-if="rawStats.recent_trend">
              <span class="info-label">近7日趋势：</span>
              <span class="raw-stat-value">{{ rawStats.recent_trend }}</span>
            </div>

            <!-- 异常比例 -->
            <div class="info-row" v-if="rawStats.anomaly_ratio != null">
              <span class="info-label">异常比例：</span>
              <span class="raw-stat-value" :class="{'anomaly-high': rawStats.anomaly_ratio > 5}">
                {{ typeof rawStats.anomaly_ratio === 'number' ? rawStats.anomaly_ratio.toFixed(2) + '%' : rawStats.anomaly_ratio }}
              </span>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <div v-else class="panel-empty">
      暂无画像数据
    </div>
  </div>
</template>

<script>
import { getStatsProfile, generateStatsProfile } from '@/api/semantic'

export default {
  name: 'TableDetailPanel',
  props: {
    tableName: { type: String, default: '' },
    profile: { type: Object, default: null },
    loading: { type: Boolean, default: false }
  },
  data() {
    return {
      activeTab: 'basic',
      statsProfile: null,
      rawStats: null,
      statsLoading: false
    }
  },
  watch: {
    tableName() {
      this.activeTab = 'basic'
      this.statsProfile = null
      this.rawStats = null
    }
  },
  methods: {
    handleTabChange(tab) {
      if (tab.name === 'stats' && !this.statsProfile) {
        this.loadStatsProfile()
      }
    },
    async loadStatsProfile() {
      if (!this.tableName) return
      this.statsLoading = true
      try {
        const res = await getStatsProfile(this.tableName)
        const data = res.data !== undefined ? res.data : res
        if (data) {
          this.statsProfile = data
          this.rawStats = data.raw_stats || null
        } else {
          // 后端返回 {data: null} 表示画像未生成
          this.statsProfile = null
          this.rawStats = null
        }
      } catch (e) {
        this.statsProfile = null
        this.rawStats = null
      } finally {
        this.statsLoading = false
      }
    },
    async handleGenerateStats() {
      if (!this.tableName) return
      this.statsLoading = true
      try {
        const res = await generateStatsProfile(this.tableName)
        const data = res.data !== undefined ? res.data : res
        if (data) {
          this.statsProfile = data
          this.rawStats = data.raw_stats || null
        }
      } catch (e) {
        console.warn('生成统计画像失败', e)
      } finally {
        this.statsLoading = false
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
  display: flex;
  align-items: center;
  justify-content: space-between;
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
.scenario-tag {
  margin: 2px 4px 2px 0;
}
.field-detail {
  padding: 4px 0;
}
.field-tags {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.stats-loading, .stats-empty {
  padding: 20px 0;
  text-align: center;
  color: #909399;
  font-size: 12px;
}
.stats-empty .empty-hint {
  margin-bottom: 12px;
  font-size: 13px;
  color: #606266;
}
.stats-content {
  padding-top: 4px;
}
.computed-time {
  margin-top: 12px;
  font-size: 11px;
  color: #c0c4cc;
  border-top: 1px dashed #ebeef5;
  padding-top: 8px;
}
/* 原始统计指标样式 */
.raw-stat-block {
  margin: 10px 0;
}
.raw-stat-label {
  font-size: 11px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 4px;
}
.raw-stat-value {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  color: #303133;
}
.anomaly-high {
  color: #f56c6c;
  font-weight: 600;
}
.coverage-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.coverage-tag {
  margin: 0;
}
.numeric-stats-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  margin-top: 4px;
}
.numeric-stats-table th,
.numeric-stats-table td {
  padding: 4px 6px;
  text-align: left;
  border-bottom: 1px solid #f0f2f5;
}
.numeric-stats-table th {
  background: #fafafa;
  color: #909399;
  font-weight: 500;
}
.numeric-stats-table td {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  color: #606266;
}
.categorical-item {
  font-size: 11px;
  margin-bottom: 4px;
  line-height: 1.6;
}
.categorical-field {
  font-weight: 600;
  color: #606266;
  margin-right: 6px;
}
.categorical-entry {
  color: #909399;
  margin-right: 8px;
}
</style>
