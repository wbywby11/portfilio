<template>
  <div class="live-publish-records" v-loading="loading">
    <p v-if="!modelId" class="muted">请选择已实盘发布的策略实例后查看记录。</p>
    <el-table
      v-else
      :data="filteredRows"
      stripe
      size="small"
      style="width: 100%;"
      :empty-text="emptyText">
      <el-table-column type="expand">
        <template slot-scope="props">
          <div v-if="hasScoped(props.row)" class="expand-diff">
            <div
              v-for="key in sortedDiffKeys(props.row.monitor_scoped_changes)"
              :key="key"
              class="diff-block">
              <div class="diff-block-title">{{ fieldLabel(key) }}</div>
              <!-- 底层资产 -->
              <div v-if="key === 'resolved_asset_list'" class="diff-rich diff-assets">
                <template v-if="resolvedAssetVisual(props.row.monitor_scoped_changes[key]).mode === 'text'">
                  <div class="diff-col diff-col--old">
                    <span class="diff-col-label">变更前</span>
                    <p class="diff-text-old">{{ resolvedAssetVisual(props.row.monitor_scoped_changes[key]).oldText || '—' }}</p>
                  </div>
                  <span class="diff-arrow-lg">→</span>
                  <div class="diff-col diff-col--new">
                    <span class="diff-col-label">变更后</span>
                    <p class="diff-text-new">{{ resolvedAssetVisual(props.row.monitor_scoped_changes[key]).newText || '—' }}</p>
                  </div>
                </template>
                <template v-else>
                  <div class="diff-col diff-col--old">
                    <span class="diff-col-label">变更前</span>
                    <div v-if="resolvedAssetVisual(props.row.monitor_scoped_changes[key]).reordered" class="diff-hint">
                      仅调整顺序，无增减
                    </div>
                    <div class="tag-flow">
                      <span
                        v-for="c in resolvedAssetVisual(props.row.monitor_scoped_changes[key]).oldList"
                        :key="'o-' + c"
                        :class="[
                          'asset-chip',
                          resolvedAssetVisual(props.row.monitor_scoped_changes[key]).removed.includes(c)
                            ? 'asset-chip--out'
                            : 'asset-chip--neutral'
                        ]">
                        {{
                          resolvedAssetVisual(props.row.monitor_scoped_changes[key]).removed.includes(c) ? '− ' : ''
                        }}{{ assetLabel(c) }}
                      </span>
                    </div>
                  </div>
                  <span class="diff-arrow-lg">→</span>
                  <div class="diff-col diff-col--new">
                    <span class="diff-col-label">变更后</span>
                    <div class="tag-flow">
                      <span
                        v-for="c in resolvedAssetVisual(props.row.monitor_scoped_changes[key]).newList"
                        :key="'n-' + c"
                        :class="[
                          'asset-chip',
                          resolvedAssetVisual(props.row.monitor_scoped_changes[key]).added.includes(c)
                            ? 'asset-chip--in'
                            : 'asset-chip--neutral'
                        ]">
                        {{
                          resolvedAssetVisual(props.row.monitor_scoped_changes[key]).added.includes(c) ? '+ ' : ''
                        }}{{ assetLabel(c) }}
                      </span>
                    </div>
                  </div>
                </template>
              </div>
              <!-- 初始化权重 / 单资产上限类 dict -->
              <div
                v-else-if="key === 'manual_weights' || key === 'weight_caps' || key === 'max_weight_dict'"
                class="diff-rich">
                <p v-if="!weightsDiffRows(props.row.monitor_scoped_changes[key]).length" class="diff-hint">无逐项数值变化（或结构异常）</p>
                <div
                  v-for="row in weightsDiffRows(props.row.monitor_scoped_changes[key])"
                  :key="key + '-' + row.code"
                  class="weight-diff-row">
                  <span class="weight-diff-name">{{ assetLabel(row.code) }}</span>
                  <div class="weight-diff-bars">
                    <div class="weight-side weight-side--old">
                      <span class="weight-pct">{{ formatPct(row.oldPct) }}</span>
                      <div class="weight-bar-track">
                        <div class="weight-bar-fill weight-bar-fill--old" :style="{ width: barWidth(row.oldPct) }" />
                      </div>
                    </div>
                    <span class="weight-arrow">→</span>
                    <div class="weight-side weight-side--new">
                      <span class="weight-pct">{{ formatPct(row.newPct) }}</span>
                      <div class="weight-bar-track">
                        <div class="weight-bar-fill weight-bar-fill--new" :style="{ width: barWidth(row.newPct) }" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <!-- 预设调仓 -->
              <div v-else-if="key === 'manual_weight_adjustments'" class="diff-rich">
                <p v-if="!adjustmentDiffBlocks(props.row.monitor_scoped_changes[key], isManualAllocationSubject).length" class="diff-hint">无调仓日或权重变化</p>
                <div
                  v-for="(blk, bidx) in adjustmentDiffBlocks(props.row.monitor_scoped_changes[key], isManualAllocationSubject)"
                  :key="'adj-' + bidx + '-' + blk.date"
                  class="adj-card"
                  :class="'adj-card--' + blk.type">
                  <div class="adj-card-head">
                    <span class="adj-date">{{ blk.date }}</span>
                    <el-tag :type="blk.type === 'added' ? 'success' : blk.type === 'removed' ? 'danger' : 'warning'" size="mini" effect="plain">
                      {{ blk.type === 'added' ? '新增调仓日' : blk.type === 'removed' ? '移除调仓日' : '权重/选项变更' }}
                    </el-tag>
                  </div>
                  <template v-if="blk.type === 'removed'">
                    <div class="adj-meta">当日目标权重（已删除）</div>
                    <div class="adj-weight-list">
                      <span v-for="(pct, code) in blk.entry.weights || {}" :key="'rw-' + code" class="adj-w-item">
                        {{ assetLabel(code) }} <strong>{{ formatPct(Number(pct) * 100) }}</strong>
                      </span>
                    </div>
                  </template>
                  <template v-else-if="blk.type === 'added'">
                    <div v-if="!isManualAllocationSubject" class="adj-meta">
                      保存时归一化：{{ blk.entry.auto_normalize ? '是' : '否' }}
                    </div>
                    <div class="adj-weight-list">
                      <span v-for="(pct, code) in blk.entry.weights || {}" :key="'aw-' + code" class="adj-w-item">
                        {{ assetLabel(code) }} <strong>{{ formatPct(Number(pct) * 100) }}</strong>
                      </span>
                    </div>
                  </template>
                  <template v-else>
                    <div v-if="!isManualAllocationSubject && blk.normOld !== blk.normNew" class="adj-meta">
                      保存时归一化：<span class="strike-muted">{{ blk.normOld ? '是' : '否' }}</span>
                      → <strong>{{ blk.normNew ? '是' : '否' }}</strong>
                    </div>
                    <div v-for="rw in blk.weightRows" :key="'mrw-' + rw.code" class="weight-diff-row weight-diff-row--compact">
                      <span class="weight-diff-name">{{ assetLabel(rw.code) }}</span>
                      <div class="weight-diff-bars">
                        <div class="weight-side weight-side--old">
                          <span class="weight-pct">{{ formatPct(rw.oldPct) }}</span>
                          <div class="weight-bar-track">
                            <div class="weight-bar-fill weight-bar-fill--old" :style="{ width: barWidth(rw.oldPct) }" />
                          </div>
                        </div>
                        <span class="weight-arrow">→</span>
                        <div class="weight-side weight-side--new">
                          <span class="weight-pct">{{ formatPct(rw.newPct) }}</span>
                          <div class="weight-bar-track">
                            <div class="weight-bar-fill weight-bar-fill--new" :style="{ width: barWidth(rw.newPct) }" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </template>
                </div>
              </div>
              <!-- 其它字段：单行对比 -->
              <div v-else class="diff-row-plain">
                <span class="diff-old">{{ formatVal(props.row.monitor_scoped_changes[key].old) }}</span>
                <span class="diff-arrow">→</span>
                <span class="diff-new">{{ formatVal(props.row.monitor_scoped_changes[key].new) }}</span>
              </div>
            </div>
          </div>
          <p v-else class="muted expand-fallback">{{ props.row.change_summary || '（无结构化变更明细，为历史记录）' }}</p>
        </template>
      </el-table-column>
      <el-table-column label="实盘版本" width="88" align="center">
        <template slot-scope="scope">
          {{ scope.row.live_version != null ? scope.row.live_version : '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="修改时间" width="168" :formatter="fmtTime" />
      <el-table-column prop="operator" label="操作人" width="120">
        <template slot-scope="scope">
          {{ scope.row.operator || '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="action" label="类型" width="120">
        <template slot-scope="scope">
          {{ actionLabel(scope.row.action) }}
        </template>
      </el-table-column>
      <el-table-column prop="change_summary" label="摘要" min-width="220" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import { getLiveChangeLogs, getStrategyModel } from '@/api/strategy';
import { getAssetOptions } from '@/api/asset';
import {
  isManualAllocationTemplateCode,
  isSubjectiveMonitorHiddenScopedDiffKey
} from '@/utils/strategyTemplateFlags';

/** 不含 strategy_update：策略保存类变更不在此列表展示 */
const RECORD_ACTIONS = new Set(['live_publish', 'live_unpublish', 'live_config_update']);

const ACTION_LABELS = {
  live_publish: '实盘发布',
  live_unpublish: '取消实盘',
  live_config_update: '实盘配置'
};

const FIELD_LABELS = {
  resolved_asset_list: '底层资产',
  manual_weights: '初始化权重',
  manual_weight_adjustments: '预设调仓',
  target_vol: '目标波动',
  vol_trigger_threshold: '波动重置阈值',
  vol_reset_threshold: '波动重置阈值',
  volatility_threshold: '波动率阈值',
  max_total_leverage: '总杠杆上限',
  max_leverage: '最大杠杆',
  weight_caps: '单资产权重上限',
  max_weight_dict: '单资产权重上限',
  mom_windows: 'MOM 窗口',
  posi_windows: 'POSI 窗口',
  smom_windows: 'SMOM 窗口',
  macd_windows: 'MACD 窗口',
  macd_long_window: 'MACD 长期窗',
  reversal_windows: '反转窗口',
  momentum_windows: '动量窗口(legacy)',
  min_history_days: '最小历史长度',
  min_history_momentum: '动量最小历史',
  min_history_reversal: '反转最小历史',
  live_volatility_threshold: '实盘波动阈值',
  live_rebalance_mode: '调仓模式',
  live_publish_enabled: '实盘发布状态',
  enable_vol_reset: '启用波动重置',
  fill_missing: '缺失值填充',
  auto_normalize: '保存时归一化',
  lookback_days: '回看天数',
  tie_break_window: '并列决胜窗口',
  rebalance_frequency: '调仓频率',
  selector_type: '选择器类型'
};

const RICH_KEYS_FIRST = ['resolved_asset_list', 'manual_weights', 'manual_weight_adjustments', 'weight_caps', 'max_weight_dict'];

export default {
  name: 'LivePublishRecords',
  props: {
    modelId: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      loading: false,
      rows: [],
      emptyText: '暂无记录',
      assetNameMap: {},
      templateCode: ''
    };
  },
  computed: {
    filteredRows() {
      return (this.rows || []).filter(r => RECORD_ACTIONS.has(r.action));
    },
    isManualAllocationSubject() {
      return isManualAllocationTemplateCode(this.templateCode);
    }
  },
  watch: {
    modelId: {
      immediate: true,
      handler() {
        this.loadData();
      }
    }
  },
  methods: {
    fmtTime(row, column, cellValue) {
      if (!cellValue) return '—';
      return dayjs(cellValue).format('YYYY-MM-DD HH:mm:ss');
    },
    actionLabel(action) {
      return ACTION_LABELS[action] || action || '—';
    },
    fieldLabel(key) {
      return FIELD_LABELS[key] || key;
    },
    hasScoped(row) {
      const d = row && row.monitor_scoped_changes;
      return d && typeof d === 'object' && Object.keys(d).length > 0;
    },
    sortedDiffKeys(changes) {
      const keys = Object.keys(changes || {}).filter(k => k !== 'live_version');
      const filtered = this.isManualAllocationSubject
        ? keys.filter(k => !isSubjectiveMonitorHiddenScopedDiffKey(k))
        : keys;
      const first = RICH_KEYS_FIRST.filter(k => filtered.includes(k));
      const rest = filtered.filter(k => !RICH_KEYS_FIRST.includes(k)).sort();
      return [...first, ...rest];
    },
    formatVal(v) {
      if (v === null || v === undefined) return '—';
      if (typeof v === 'object') {
        try {
          return JSON.stringify(v);
        } catch (e) {
          return String(v);
        }
      }
      return String(v);
    },
    assetLabel(code) {
      const c = String(code || '').trim();
      if (!c) return '—';
      const candidates = [c];
      if (c.endsWith('_TEST')) candidates.push(c.slice(0, -5));
      for (const k of candidates) {
        const n = this.assetNameMap[k];
        if (n && String(n).trim() && n !== c) return `${n}（${c}）`;
      }
      const direct = this.assetNameMap[c];
      if (direct && String(direct).trim()) return direct;
      return c;
    },
    coerceCodeList(v) {
      if (!Array.isArray(v)) return [];
      return v.map(x => String(x).trim()).filter(Boolean);
    },
    /** 供模板调用：解析一次避免重复（Vue2 会多次算） */
    resolvedAssetVisual(pair) {
      if (!pair || typeof pair !== 'object') return { mode: 'text', oldText: '—', newText: '—' };
      const oldVal = pair.old;
      const newVal = pair.new;
      if (typeof oldVal === 'string' || typeof newVal === 'string') {
        return {
          mode: 'text',
          oldText: oldVal != null ? String(oldVal) : '—',
          newText: newVal != null ? String(newVal) : '—'
        };
      }
      const oldList = this.coerceCodeList(oldVal);
      const newList = this.coerceCodeList(newVal);
      const os = new Set(oldList);
      const ns = new Set(newList);
      const removed = oldList.filter(x => !ns.has(x));
      const added = newList.filter(x => !os.has(x));
      const reordered =
        !removed.length &&
        !added.length &&
        oldList.length === newList.length &&
        oldList.length > 0 &&
        oldList.some((c, i) => c !== newList[i]);
      return { mode: 'chips', removed, added, reordered, oldList, newList };
    },
    parsePlainObject(v) {
      if (v && typeof v === 'string') {
        try {
          const p = JSON.parse(v);
          if (p && typeof p === 'object' && !Array.isArray(p)) return p;
        } catch (e) {
          return null;
        }
      }
      if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
      return v;
    },
    weightsDiffRows(pair) {
      if (!pair || typeof pair !== 'object') return [];
      const o = this.parsePlainObject(pair.old) || {};
      const n = this.parsePlainObject(pair.new) || {};
      const codes = new Set([...Object.keys(o), ...Object.keys(n)]);
      const rows = [];
      codes.forEach(code => {
        const ov = o[code];
        const nv = n[code];
        let oi = ov != null && ov !== '' ? Number(ov) : 0;
        let ni = nv != null && nv !== '' ? Number(nv) : 0;
        if (Number.isNaN(oi)) oi = 0;
        if (Number.isNaN(ni)) ni = 0;
        if (Math.abs(oi - ni) < 1e-8) return;
        rows.push({ code, oldPct: oi * 100, newPct: ni * 100 });
      });
      return rows.sort((a, b) => a.code.localeCompare(b.code));
    },
    formatPct(pct) {
      if (pct == null || Number.isNaN(Number(pct))) return '—';
      const n = Number(pct);
      return `${n.toFixed(2)}%`;
    },
    barWidth(pct) {
      if (pct == null || Number.isNaN(Number(pct))) return '0%';
      const w = Math.min(100, Math.max(0, Number(pct)));
      return `${w}%`;
    },
    normAdjDate(d) {
      if (d == null || d === '') return '';
      const s = String(d);
      const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
      return m ? m[1] : s.slice(0, 10);
    },
    parseAdjustmentsList(v) {
      let arr = v;
      if (typeof v === 'string') {
        try {
          arr = JSON.parse(v);
        } catch (e) {
          return [];
        }
      }
      if (!Array.isArray(arr)) return [];
      return arr.filter(x => x && typeof x === 'object');
    },
    adjIndexByDate(arr) {
      const by = {};
      this.parseAdjustmentsList(arr).forEach(item => {
        const d = this.normAdjDate(item.date);
        if (d) by[d] = item;
      });
      return by;
    },
    weightsChangedOnly(oldW, newW) {
      const o = this.parsePlainObject(oldW) || {};
      const n = this.parsePlainObject(newW) || {};
      const codes = new Set([...Object.keys(o), ...Object.keys(n)]);
      const rows = [];
      codes.forEach(code => {
        let oi = o[code] != null && o[code] !== '' ? Number(o[code]) : 0;
        let ni = n[code] != null && n[code] !== '' ? Number(n[code]) : 0;
        if (Number.isNaN(oi)) oi = 0;
        if (Number.isNaN(ni)) ni = 0;
        if (Math.abs(oi - ni) < 1e-8) return;
        rows.push({ code, oldPct: oi * 100, newPct: ni * 100 });
      });
      return rows.sort((a, b) => a.code.localeCompare(b.code));
    },
    adjustmentDiffBlocks(pair, hideNormalizeOnlyChanges = false) {
      if (!pair || typeof pair !== 'object') return [];
      const oldArr = pair.old;
      const newArr = pair.new;
      const bo = this.adjIndexByDate(oldArr);
      const bn = this.adjIndexByDate(newArr);
      const dates = new Set([...Object.keys(bo), ...Object.keys(bn)]);
      const blocks = [];
      [...dates].sort().forEach(date => {
        const io = bo[date];
        const inn = bn[date];
        if (io && !inn) {
          blocks.push({ type: 'removed', date, entry: io });
        } else if (!io && inn) {
          blocks.push({ type: 'added', date, entry: inn });
        } else if (io && inn) {
          const normOld = !!io.auto_normalize;
          const normNew = !!inn.auto_normalize;
          const weightRows = this.weightsChangedOnly(io.weights, inn.weights);
          if (hideNormalizeOnlyChanges) {
            if (weightRows.length) {
              blocks.push({
                type: 'modified',
                date,
                oldEntry: io,
                newEntry: inn,
                weightRows,
                normOld,
                normNew
              });
            }
          } else if (normOld !== normNew || weightRows.length) {
            blocks.push({
              type: 'modified',
              date,
              oldEntry: io,
              newEntry: inn,
              weightRows,
              normOld,
              normNew
            });
          }
        }
      });
      return blocks;
    },
    mergeAssetNameMap(model, opts) {
      const m = {};
      const an = model && model.asset_names;
      if (an && typeof an === 'object') {
        Object.keys(an).forEach(k => {
          const v = an[k];
          if (v != null && String(v).trim()) m[k] = String(v).trim();
        });
      }
      const list = Array.isArray(opts) ? opts : [];
      list.forEach(o => {
        if (o && o.code && o.name) {
          if (!m[o.code]) m[o.code] = o.name;
          const bare = String(o.code).replace(/_TEST$/i, '');
          if (bare && bare !== o.code && !m[bare]) m[bare] = o.name;
        }
      });
      return m;
    },
    async loadData() {
      if (!this.modelId || this.modelId === 'default') {
        this.rows = [];
        this.assetNameMap = {};
        this.templateCode = '';
        return;
      }
      this.loading = true;
      try {
        const [logRes, modelRes, optRes] = await Promise.all([
          getLiveChangeLogs(this.modelId, { limit: 80, skip: 0 }),
          getStrategyModel(this.modelId).catch(() => null),
          getAssetOptions().catch(() => null)
        ]);
        const logBody = logRes && logRes.data !== undefined ? logRes.data : logRes;
        this.rows = Array.isArray(logBody) ? logBody : [];
        const model = modelRes && modelRes.data !== undefined ? modelRes.data : modelRes;
        const optsBody = optRes && optRes.data !== undefined ? optRes.data : optRes;
        const opts = Array.isArray(optsBody) ? optsBody : [];
        this.templateCode = (model && model.template_code) ? String(model.template_code) : '';
        this.assetNameMap = this.mergeAssetNameMap(model, opts);
      } catch (e) {
        console.error(e);
        this.rows = [];
        this.assetNameMap = {};
        this.templateCode = '';
        this.$message.error('加载实盘发布记录失败');
      } finally {
        this.loading = false;
      }
    }
  }
};
</script>

<style scoped>
.muted {
  color: #909399;
  font-size: 13px;
  margin: 0;
}
.expand-diff {
  padding: 10px 14px 14px;
  background: linear-gradient(165deg, #f8fafc 0%, #f0f2f5 100%);
  border-radius: 8px;
  max-width: 920px;
  border: 1px solid #ebeef5;
}
.diff-block {
  margin-bottom: 16px;
}
.diff-block:last-child {
  margin-bottom: 0;
}
.diff-block-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #e4e7ed;
}
.diff-rich {
  font-size: 13px;
}
.diff-assets {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 12px;
}
.diff-col {
  flex: 1 1 200px;
  min-width: 160px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #ebeef5;
}
.diff-col--old {
  border-left: 3px solid #f56c6c;
}
.diff-col--new {
  border-left: 3px solid #67c23a;
}
.diff-col-label {
  display: block;
  font-size: 11px;
  color: #909399;
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.diff-text-old {
  margin: 0;
  color: #c45656;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.diff-text-new {
  margin: 0;
  color: #529b2e;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.diff-arrow-lg {
  flex: 0 0 auto;
  align-self: center;
  color: #c0c4cc;
  font-size: 18px;
  font-weight: 300;
}
.tag-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.asset-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  border: 1px solid #dcdfe6;
  background: #fafafa;
  color: #606266;
}
.asset-chip--neutral {
  border-style: dashed;
}
.asset-chip--out {
  border-color: #fbc4c4;
  background: #fef0f0;
  color: #c45656;
}
.asset-chip--in {
  border-color: #c2e7b0;
  background: #f0f9eb;
  color: #529b2e;
}
.diff-hint {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: #909399;
}
.weight-diff-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}
.weight-diff-row:last-child {
  border-bottom: none;
}
.weight-diff-row--compact {
  padding: 6px 0;
}
.weight-diff-name {
  flex: 0 0 160px;
  font-size: 12px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.weight-diff-bars {
  flex: 1 1 280px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.weight-side {
  flex: 1 1 120px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.weight-pct {
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.weight-side--old .weight-pct {
  color: #c45656;
}
.weight-side--new .weight-pct {
  color: #529b2e;
}
.weight-bar-track {
  height: 8px;
  border-radius: 4px;
  background: #ebeef5;
  overflow: hidden;
}
.weight-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.2s ease;
  min-width: 2px;
}
.weight-bar-fill--old {
  background: linear-gradient(90deg, #f89898, #f56c6c);
}
.weight-bar-fill--new {
  background: linear-gradient(90deg, #95d475, #67c23a);
}
.weight-arrow {
  flex: 0 0 20px;
  text-align: center;
  color: #c0c4cc;
  font-size: 14px;
}
.adj-card {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #ebeef5;
}
.adj-card:last-child {
  margin-bottom: 0;
}
.adj-card--added {
  border-left: 3px solid #67c23a;
  background: #fbfff8;
}
.adj-card--removed {
  border-left: 3px solid #f56c6c;
  background: #fffbfb;
}
.adj-card--modified {
  border-left: 3px solid #e6a23c;
  background: #fffdf8;
}
.adj-card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.adj-date {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  font-variant-numeric: tabular-nums;
}
.adj-meta {
  font-size: 12px;
  color: #606266;
  margin-bottom: 6px;
}
.strike-muted {
  text-decoration: line-through;
  color: #c0c4cc;
  margin-right: 4px;
}
.adj-weight-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  font-size: 12px;
  color: #606266;
}
.adj-w-item strong {
  color: #303133;
  margin-left: 2px;
}
.diff-row-plain {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  padding: 8px 12px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
.diff-old {
  color: #c45656;
  word-break: break-all;
  flex: 1 1 120px;
}
.diff-new {
  color: #67c23a;
  word-break: break-all;
  flex: 1 1 120px;
}
.diff-arrow {
  flex: 0 0 24px;
  text-align: center;
  color: #909399;
}
.expand-fallback {
  padding: 8px 12px;
}
</style>
