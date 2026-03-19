<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">实盘监控</h2>
      <el-button type="primary" icon="el-icon-refresh" :loading="loadingList" @click="fetchLiveModels">
        刷新列表
      </el-button>
    </div>

    <el-row :gutter="20">
      <el-col :span="9">
        <el-card shadow="never">
          <div slot="header" class="card-header">
            <span>已实盘发布策略</span>
          </div>
          <el-table
            :data="liveModels"
            v-loading="loadingList"
            height="620"
            highlight-current-row
            @current-change="handleCurrentChange"
          >
            <el-table-column prop="name" label="策略名称" min-width="160" />
            <el-table-column label="实盘状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.live_publish_enabled ? 'success' : 'info'" size="small">
                  {{ row.live_publish_enabled ? '已实盘发布' : '未实盘发布' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="live_version" label="版本" width="80" />
            <el-table-column label="生效日" width="120">
              <template #default="{ row }">
                {{ formatDateShort(row.live_effective_date) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="15">
        <el-card shadow="never" v-loading="loadingDetail">
          <div slot="header" class="card-header">
            <span>{{ currentModel ? `${currentModel.name} 监控详情` : '监控详情' }}</span>
            <div>
              <el-button
                v-if="currentModel"
                size="small"
                icon="el-icon-edit-outline"
                @click="openModelDetail"
              >
                打开策略详情
              </el-button>
              <el-button
                v-if="currentModel"
                type="success"
                size="small"
                :loading="republishing"
                @click="republishLive"
              >
                发布到最新实盘
              </el-button>
            </div>
          </div>

          <div v-if="!currentModel" class="empty-block">请选择左侧实盘策略</div>
          <template v-else>
            <el-alert
              v-if="currentModel.live_snapshot_outdated"
              type="warning"
              :closable="false"
              show-icon
              title="检测到策略配置已变更，建议点击“发布到最新实盘”同步到最新版本。"
              style="margin-bottom: 16px;"
            />

            <el-form :inline="true" :model="liveConfig" class="config-form">
              <el-form-item label="调仓模式">
                <el-select v-model="liveConfig.rebalance_mode" placeholder="请选择模式" style="width: 180px;">
                  <el-option label="自动调仓" value="auto" />
                  <el-option label="手动调仓" value="manual" />
                </el-select>
              </el-form-item>
              <el-form-item label="波动率阈值">
                <el-input-number
                  v-model="liveConfig.volatility_threshold"
                  :min="0"
                  :step="0.01"
                  :precision="4"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="savingConfig" @click="saveLiveConfig">保存配置</el-button>
              </el-form-item>
              <el-form-item>
                <el-button type="danger" plain :loading="unpublishing" @click="unpublishLive">取消实盘发布</el-button>
              </el-form-item>
            </el-form>

            <el-row :gutter="12" class="metric-row" v-if="monitoringRecord && monitoringRecord.result">
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">总收益率</div>
                  <div class="metric-value">{{ toPercent(monitoringRecord.result.total_return) }}</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">年化收益率</div>
                  <div class="metric-value">{{ toPercent(monitoringRecord.result.annual_return) }}</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">年化波动率</div>
                  <div class="metric-value">{{ toPercent(monitoringRecord.result.annual_volatility) }}</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">最大回撤</div>
                  <div class="metric-value danger">{{ toPercent(monitoringRecord.result.max_drawdown) }}</div>
                </div>
              </el-col>
            </el-row>

            <el-row v-if="monitoringRecord && monitoringRecord.result" :gutter="12" class="today-section">
              <el-col :span="8">
                <el-card shadow="hover" class="today-card">
                  <div slot="header" class="today-card-header">当日净值</div>
                  <div v-if="monitoringRecord.result.today_nav" class="today-content">
                    <div class="today-row"><span class="today-label">日期</span><span>{{ monitoringRecord.result.today_nav.date }}</span></div>
                    <div class="today-row"><span class="today-label">单位净值</span><span>{{ (monitoringRecord.result.today_nav.unit_value || 0).toFixed(4) }}</span></div>
                    <div class="today-row"><span class="today-label">组合市值</span><span>{{ formatNumber(monitoringRecord.result.today_nav.total_value) }}</span></div>
                  </div>
                  <div v-else class="today-empty">暂无数据</div>
                </el-card>
              </el-col>
              <el-col :span="8">
                <el-card shadow="hover" class="today-card">
                  <div slot="header" class="today-card-header">当日权重</div>
                  <div v-if="todayWeightsList.length" class="today-content">
                    <el-table :data="todayWeightsList" size="mini" max-height="160">
                      <el-table-column prop="asset_code" label="资产" min-width="80" />
                      <el-table-column prop="asset_name" label="名称" min-width="70" />
                      <el-table-column prop="weight" label="权重" width="80">
                        <template #default="{ row }">{{ toPercent(row.weight) }}</template>
                      </el-table-column>
                    </el-table>
                  </div>
                  <div v-else class="today-empty">暂无数据</div>
                </el-card>
              </el-col>
              <el-col :span="8">
                <el-card shadow="hover" class="today-card">
                  <div slot="header" class="today-card-header">当日计划调仓</div>
                  <div v-if="monitoringRecord.result.today_planned_rebalance && monitoringRecord.result.today_planned_rebalance.is_rebalance_day" class="today-content">
                    <div class="today-row"><span class="today-label">调仓日</span><span>{{ monitoringRecord.result.today_planned_rebalance.date }}</span></div>
                    <el-table :data="plannedRebalanceList" size="mini" max-height="140">
                      <el-table-column prop="asset_code" label="资产" width="70" />
                      <el-table-column prop="current" label="当前" width="60">
                        <template #default="{ row }">{{ toPercent(row.current) }}</template>
                      </el-table-column>
                      <el-table-column prop="target" label="目标" width="60">
                        <template #default="{ row }">{{ toPercent(row.target) }}</template>
                      </el-table-column>
                      <el-table-column prop="delta" label="变化" width="60">
                        <template #default="{ row }">
                          <span :class="row.delta > 0 ? 'delta-up' : (row.delta < 0 ? 'delta-down' : '')">{{ (row.delta > 0 ? '+' : '') }}{{ toPercent(row.delta) }}</span>
                        </template>
                      </el-table-column>
                    </el-table>
                  </div>
                  <div v-else class="today-empty">{{ monitoringRecord.result.today_planned_rebalance ? '今日非调仓日' : '暂无数据' }}</div>
                </el-card>
              </el-col>
            </el-row>

            <el-divider content-position="left">手动调仓操作</el-divider>
            <div class="manual-row">
              <el-input
                v-model="manualComment"
                placeholder="可选：记录本次人工决策说明"
                maxlength="200"
                show-word-limit
              />
              <el-button
                type="success"
                :disabled="liveConfig.rebalance_mode !== 'manual'"
                :loading="manualSubmitting"
                @click="submitManualDecision('confirm')"
              >
                确认本次调仓
              </el-button>
              <el-button
                :disabled="liveConfig.rebalance_mode !== 'manual'"
                :loading="manualSubmitting"
                @click="submitManualDecision('skip')"
              >
                跳过本次调仓
              </el-button>
            </div>

            <el-collapse v-model="liveRecordsExpanded">
              <el-collapse-item name="records">
                <template slot="title">
                  <span class="section-title">实盘变更记录</span>
                  <span v-if="liveLogs.length > 0" class="section-count">（共 {{ liveLogs.length }} 条）</span>
                </template>
                <el-collapse v-if="liveLogs.length > 0" :default-active="[]">
                  <el-collapse-item
                    v-for="(item, idx) in liveLogs"
                    :key="item.id"
                    :name="String(item.id || idx)"
                  >
                    <template slot="title">
                      <span class="log-title-inline">
                        {{ getActionLabel(item.action) }}{{ (item.change_summary || formatLogDetail(item)) ? ': ' + (item.change_summary || formatLogDetail(item)) : '' }}
                      </span>
                      <span class="log-meta-inline">来源: {{ item.source }} | 用户: {{ item.operator || '-' }} | 版本: {{ item.live_version || '-' }} | {{ formatDate(item.created_at) }}</span>
                    </template>
                    <div v-if="getChangedFields(item).length" class="log-detail">
                      <pre class="log-json">{{ formatChangedContent(item) }}</pre>
                    </div>
                    <div v-else class="log-detail empty-detail">无明细变更</div>
                  </el-collapse-item>
                </el-collapse>
                <div v-else class="empty-block">暂无变更日志</div>
              </el-collapse-item>
            </el-collapse>
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
import dayjs from 'dayjs';

export default {
  name: 'LiveMonitoring',
  data() {
    return {
      loadingList: false,
      loadingDetail: false,
      savingConfig: false,
      republishing: false,
      unpublishing: false,
      manualSubmitting: false,
      liveModels: [],
      currentModel: null,
      monitoringRecord: null,
      liveLogs: [],
      manualComment: '',
      liveRecordsExpanded: ['records'],
      liveConfig: {
        rebalance_mode: 'auto',
        volatility_threshold: null
      }
    };
  },
  computed: {
    todayWeightsList() {
      const r = this.monitoringRecord?.result;
      if (!r?.today_weights || typeof r.today_weights !== 'object') return [];
      const names = r.asset_names || {};
      return Object.entries(r.today_weights)
        .map(([code, w]) => ({ asset_code: code, asset_name: names[code] || code, weight: w }))
        .sort((a, b) => b.weight - a.weight);
    },
    plannedRebalanceList() {
      const pr = this.monitoringRecord?.result?.today_planned_rebalance;
      if (!pr?.is_rebalance_day) return [];
      const all = new Set([...Object.keys(pr.current_weights || {}), ...Object.keys(pr.target_weights || {})]);
      return Array.from(all).map(code => ({
        asset_code: code,
        current: pr.current_weights?.[code] ?? 0,
        target: pr.target_weights?.[code] ?? 0,
        delta: (pr.target_weights?.[code] ?? 0) - (pr.current_weights?.[code] ?? 0)
      })).filter(x => Math.abs(x.delta) > 1e-8).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
    }
  },
  created() {
    this.fetchLiveModels();
  },
  methods: {
    async fetchLiveModels() {
      this.loadingList = true;
      try {
        const rows = await this.$store.dispatch('strategy/fetchLivePublishedModelList');
        this.liveModels = rows || [];
        if (this.liveModels.length > 0) {
          this.currentModel = this.liveModels[0];
          await this.loadDetail(this.currentModel.id);
        } else {
          this.currentModel = null;
          this.monitoringRecord = null;
          this.liveLogs = [];
        }
      } catch (error) {
        this.$message.error('加载实盘策略列表失败');
      } finally {
        this.loadingList = false;
      }
    },
    async handleCurrentChange(row) {
      if (!row || !row.id) return;
      this.currentModel = row;
      await this.loadDetail(row.id);
    },
    async loadDetail(modelId) {
      this.loadingDetail = true;
      try {
        const [monitoringResult, logsResult, configResult] = await Promise.allSettled([
          this.$store.dispatch('strategy/fetchLiveMonitoring', modelId),
          this.$store.dispatch('strategy/fetchLiveChangeLogs', { modelId }),
          this.$store.dispatch('strategy/fetchLiveConfig', modelId)
        ]);
        this.monitoringRecord = monitoringResult.status === 'fulfilled' ? monitoringResult.value : null;
        this.liveLogs = logsResult.status === 'fulfilled' ? (logsResult.value || []) : [];
        const config = configResult.status === 'fulfilled' ? configResult.value : {};
        if (monitoringResult.status === 'rejected') {
          this.$message.warning('该策略暂无可用监控数据');
        }
        const volFromConfig = config.live_volatility_threshold != null && config.live_volatility_threshold !== ''
          ? config.live_volatility_threshold
          : config.suggested_volatility_threshold;
        const volFallback = this.getVolatilityThreshold(this.currentModel);
        this.liveConfig = {
          rebalance_mode: config.live_rebalance_mode || this.currentModel?.live_rebalance_mode || 'auto',
          volatility_threshold: volFromConfig ?? volFallback ?? null
        };
      } catch (error) {
        this.$message.warning('加载详情失败');
      } finally {
        this.loadingDetail = false;
      }
    },
    async saveLiveConfig() {
      if (!this.currentModel) return;
      this.savingConfig = true;
      try {
        await this.$store.dispatch('strategy/updateLiveConfig', {
          modelId: this.currentModel.id,
          data: {
            source: 'live_monitoring',
            operator: this.$store.getters['user/userName'] || this.$store.state.user?.userInfo?.name || this.$store.state.user?.userInfo?.username || '未知',
            rebalance_mode: this.liveConfig.rebalance_mode,
            volatility_threshold: this.liveConfig.volatility_threshold
          }
        });
        this.$message.success('实盘配置已更新');
        const prevId = this.currentModel?.id;
        await this.fetchLiveModels();
        const found = this.liveModels.find(m => m.id === prevId);
        this.currentModel = found || this.liveModels[0] || null;
        if (this.currentModel) await this.loadDetail(this.currentModel.id);
      } catch (error) {
        this.$message.error(error.response?.data?.detail || error.message || '更新失败');
      } finally {
        this.savingConfig = false;
      }
    },
    async republishLive() {
      if (!this.currentModel) return;
      this.$confirm('确认将当前策略配置发布到最新实盘版本？新版本将于次交易日生效。', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        this.republishing = true;
        try {
          await this.$store.dispatch('strategy/livePublishModel', {
            modelId: this.currentModel.id,
            data: {
              source: 'live_monitoring',
              operator: this.$store.getters['user/userName'] || this.$store.state.user?.userInfo?.name || this.$store.state.user?.userInfo?.username || '未知',
              rebalance_mode: this.liveConfig.rebalance_mode,
              volatility_threshold: this.liveConfig.volatility_threshold
            }
          });
          this.$message.success('已发布到最新实盘');
          await this.fetchLiveModels();
        } catch (error) {
          this.$message.error(error.response?.data?.detail || error.message || '发布失败');
        } finally {
          this.republishing = false;
        }
      }).catch(() => {});
    },
    async unpublishLive() {
      if (!this.currentModel) return;
      this.$confirm('确认取消该策略的实盘发布状态？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        this.unpublishing = true;
        try {
          await this.$store.dispatch('strategy/liveUnpublishModel', {
            modelId: this.currentModel.id,
            params: { source: 'live_monitoring' }
          });
          this.$message.success('已取消实盘发布');
          await this.fetchLiveModels();
        } catch (error) {
          this.$message.error(error.response?.data?.detail || error.message || '操作失败');
        } finally {
          this.unpublishing = false;
        }
      }).catch(() => {});
    },
    async submitManualDecision(decision) {
      if (!this.currentModel) return;
      this.manualSubmitting = true;
      try {
        await this.$store.dispatch('strategy/confirmManualRebalance', {
          modelId: this.currentModel.id,
          data: {
            decision,
            comment: this.manualComment,
            operator: this.$store.getters['user/userName'] || this.$store.state.user?.userInfo?.name || this.$store.state.user?.userInfo?.username || '未知'
          }
        });
        this.$message.success('已记录人工调仓决策');
        this.manualComment = '';
        await this.loadDetail(this.currentModel.id);
      } catch (error) {
        this.$message.error(error.response?.data?.detail || error.message || '提交失败');
      } finally {
        this.manualSubmitting = false;
      }
    },
    openModelDetail() {
      if (!this.currentModel) return;
      this.$router.push(`/strategy/model/detail/${this.currentModel.id}`);
    },
    toPercent(value) {
      if (value === null || value === undefined) return '-';
      return `${(value * 100).toFixed(2)}%`;
    },
    formatNumber(value) {
      if (value === null || value === undefined) return '-';
      const n = Number(value);
      if (Number.isNaN(n)) return '-';
      if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿';
      if (n >= 1e4) return (n / 1e4).toFixed(2) + '万';
      return n.toLocaleString();
    },
    formatDate(value) {
      return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-';
    },
    formatDateShort(value) {
      return value ? dayjs(value).format('YYYY-MM-DD') : '-';
    },
    getActionLabel(action) {
      const map = {
        live_publish: '实盘发布',
        live_unpublish: '取消实盘发布',
        live_config_update: '参数配置修改',
        strategy_update: '策略配置更新',
        manual_rebalance_confirmed: '手动确认调仓',
        manual_rebalance_skipped: '手动跳过调仓'
      };
      return map[action] || action;
    },
    formatRebalanceModeLabel(val) {
      if (val == null || val === '') return '-';
      const s = String(val).toLowerCase();
      if (s.includes('manual') || s === 'manual') return '手动调仓';
      if (s.includes('auto') || s === 'auto') return '自动调仓';
      return val;
    },
    formatLogDetail(item) {
      if (item.action !== 'live_config_update' || !item.before || !item.after) return '';
      const parts = [];
      if (item.after.live_volatility_threshold !== undefined && item.before.live_volatility_threshold !== item.after.live_volatility_threshold) {
        parts.push(`波动率阈值: ${item.before.live_volatility_threshold ?? '-'} → ${item.after.live_volatility_threshold}`);
      }
      if (item.after.live_rebalance_mode !== undefined && item.before.live_rebalance_mode !== item.after.live_rebalance_mode) {
        parts.push(`调仓模式: ${this.formatRebalanceModeLabel(item.before.live_rebalance_mode)} → ${this.formatRebalanceModeLabel(item.after.live_rebalance_mode)}`);
      }
      return parts.join('; ');
    },
    getChangedFields(item) {
      const before = item.before || {};
      const after = item.after || {};
      const labels = {
        live_rebalance_mode: '调仓模式',
        live_volatility_threshold: '波动率阈值',
        live_publish_enabled: '实盘发布',
        live_version: '版本',
        live_effective_date: '生效日期',
        live_snapshot_outdated: '快照是否过期',
        asset_codes: '资产池',
        template_code: '模板',
        rebalance_frequency: '调仓频率',
        name: '名称',
        updated_at: '更新时间'
      };
      const paramLabels = {
        vol_reset_threshold: '波动率重置阈值',
        target_vol: '目标波动率',
        volatility_threshold: '波动率阈值'
      };
      const changed = [];
      const addParamChanges = (bObj, aObj, prefix = '') => {
        const b = bObj && typeof bObj === 'object' && !Array.isArray(bObj) ? bObj : {};
        const a = aObj && typeof aObj === 'object' && !Array.isArray(aObj) ? aObj : {};
        const allKeys = new Set([...Object.keys(b), ...Object.keys(a)]);
        for (const subK of allKeys) {
          const bv = b[subK];
          const av = a[subK];
          const same = (bv === av) || (JSON.stringify(bv) === JSON.stringify(av));
          if (!same) {
            changed.push({
              key: prefix ? `${prefix}.${subK}` : subK,
              label: paramLabels[subK] || subK,
              oldVal: bv,
              newVal: av
            });
          }
        }
      };
      const allKeys = new Set([...Object.keys(before), ...Object.keys(after)]);
      for (const k of allKeys) {
        const b = before[k];
        const a = after[k];
        if (k === 'parameters') {
          if ((b === a) || (JSON.stringify(b) === JSON.stringify(a))) continue;
          addParamChanges(b, a);
        } else if (k === 'live_snapshot' && (b !== a) && (JSON.stringify(b) !== JSON.stringify(a))) {
          const bParams = b?.parameters;
          const aParams = a?.parameters;
          if (bParams || aParams) addParamChanges(bParams, aParams);
          const otherKeys = ['name', 'template_code', 'asset_codes', 'rebalance_frequency', 'updated_at'];
          for (const sk of otherKeys) {
            const bv = b?.[sk];
            const av = a?.[sk];
            if (JSON.stringify(bv) !== JSON.stringify(av)) {
              changed.push({ key: sk, label: labels[sk] || sk, oldVal: bv, newVal: av });
            }
          }
        } else {
          const same = (b === a) || (JSON.stringify(b) === JSON.stringify(a));
          if (!same) {
            changed.push({ key: k, label: labels[k] || k, oldVal: b, newVal: a });
          }
        }
      }
      return changed;
    },
    formatChangedContent(item) {
      const fields = this.getChangedFields(item);
      if (!fields.length) return '';
      const lines = fields.map(({ key, label, oldVal, newVal }) => {
        const fmt = (v) => (key === 'live_rebalance_mode' ? this.formatRebalanceModeLabel(v) : (v != null && typeof v === 'object' && !(v instanceof Date) ? JSON.stringify(v) : v));
        return `${label}: ${fmt(oldVal)} → ${fmt(newVal)}`;
      });
      return lines.join('\n');
    },
    getVolatilityThreshold(model) {
      if (!model) return null;
      if (model.live_volatility_threshold != null && model.live_volatility_threshold !== '') {
        return Number(model.live_volatility_threshold);
      }
      let params = model.live_snapshot?.parameters || model.parameters || {};
      if (typeof params === 'string') {
        try {
          params = JSON.parse(params);
        } catch {
          return null;
        }
      }
      if (typeof params !== 'object' || params === null) return null;
      for (const key of ['vol_reset_threshold', 'target_vol', 'volatility_threshold']) {
        const v = params[key];
        if (v != null && v !== '') {
          const n = Number(v);
          if (!Number.isNaN(n)) return n;
        }
      }
      return null;
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 500;
  color: #303133;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.empty-block {
  text-align: center;
  color: #909399;
  padding: 28px 0;
}

.config-form {
  margin-bottom: 8px;
}

.metric-row {
  margin: 10px 0 6px;
}

.today-section {
  margin: 16px 0;
}

.today-card {
  min-height: 120px;
}

.today-card-header {
  font-size: 14px;
  font-weight: 500;
}

.today-content {
  font-size: 13px;
}

.today-row {
  margin-bottom: 6px;
}

.today-label {
  color: #909399;
  margin-right: 8px;
}

.today-empty {
  color: #909399;
  font-size: 13px;
  padding: 8px 0;
}

.delta-up {
  color: #67c23a;
}

.delta-down {
  color: #f56c6c;
}

.metric-card {
  background: #f5f7fa;
  border-radius: 6px;
  text-align: center;
  padding: 14px 8px;
}

.metric-label {
  color: #909399;
  font-size: 13px;
  margin-bottom: 6px;
}

.metric-value {
  color: #303133;
  font-size: 20px;
  font-weight: 600;
}

.metric-value.danger {
  color: #f56c6c;
}

.manual-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 10px;
  align-items: center;
}

.log-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.log-meta {
  color: #909399;
  font-size: 12px;
}

.section-title {
  font-weight: 500;
}

.section-count {
  color: #909399;
  font-size: 13px;
  margin-left: 4px;
}

.log-title-inline {
  font-weight: 500;
  margin-right: 12px;
}

.log-meta-inline {
  color: #909399;
  font-size: 12px;
}

.log-detail {
  padding: 8px 0;
}

.log-detail.empty-detail {
  color: #909399;
  font-size: 13px;
}

.log-section {
  margin-bottom: 12px;
}

.log-section:last-child {
  margin-bottom: 0;
}

.log-section-title {
  font-size: 13px;
  color: #606266;
  margin-bottom: 4px;
}

.log-json {
  margin: 0;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
