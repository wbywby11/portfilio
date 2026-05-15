<template>
  <div class="smws" :class="{ 'smws--compact': compact }">
    <div class="live-manual-snapshot">
      <div
        class="subjective-snapshot-block subjective-snapshot-block--init"
        :class="{ 'subjective-snapshot-block--interactive': interactiveInit }"
        @click="onInitClick">
        <div class="subjective-snapshot-head">
          <div class="diff-block-title subjective-snapshot-title">初始化权重</div>
          <span v-if="interactiveInit" class="subjective-edit-hint">点击调整 →</span>
        </div>
        <div class="subjective-snapshot-inner">
          <p v-if="!initRows.length" class="diff-hint">暂无初始化权重配置</p>
          <div
            v-for="row in initRows"
            :key="'smws-mw-' + row.code"
            class="weight-diff-row subjective-weight-row--single">
            <span class="weight-diff-name">{{ resolveLabel(row.code) }}</span>
            <div class="weight-diff-bars subjective-weight-bars--single">
              <span class="weight-pct weight-pct--current">{{ formatPct(row.pct) }}</span>
              <div class="weight-bar-track">
                <div
                  class="weight-bar-fill weight-bar-fill--new"
                  :style="{ width: barWidth(row.pct) }" />
              </div>
            </div>
          </div>
        </div>
      </div>
      <div
        class="subjective-snapshot-block subjective-snapshot-block--presets"
        :class="{ 'subjective-snapshot-block--interactive': interactivePresets }"
        @click="onPresetsClick">
        <div class="subjective-snapshot-head">
          <div class="diff-block-title subjective-snapshot-title">预设调仓</div>
          <span v-if="interactivePresets" class="subjective-edit-hint">点击调整 →</span>
        </div>
        <div class="subjective-snapshot-inner">
          <p v-if="!presetBlocks.length" class="diff-hint">暂无预设调仓日</p>
          <div
            v-for="blk in presetBlocks"
            :key="'smws-adj-' + blk.date"
            class="adj-card adj-card--snapshot">
            <div class="adj-card-head">
              <span class="adj-date">{{ blk.date }}</span>
            </div>
            <div class="adj-meta">
              保存时归一化：{{ blk.auto_normalize ? '是' : '否' }}
            </div>
            <div class="adj-card-bars">
              <div
                v-for="w in blk.weightItems"
                :key="'smws-adj-w-' + blk.date + '-' + w.code"
                class="weight-diff-row subjective-weight-row--single">
                <span class="weight-diff-name">{{ resolveLabel(w.code) }}</span>
                <div class="weight-diff-bars subjective-weight-bars--single">
                  <span class="weight-pct weight-pct--current">{{ formatPct(w.pct) }}</span>
                  <div class="weight-bar-track">
                    <div
                      class="weight-bar-fill weight-bar-fill--new"
                      :style="{ width: barWidth(w.pct) }" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'SubjectiveManualWeightsSnapshot',
  props: {
    manualWeights: {
      type: Object,
      default: () => ({})
    },
    manualAdjustments: {
      type: Array,
      default: () => []
    },
    resolveLabel: {
      type: Function,
      required: true
    },
    interactiveInit: {
      type: Boolean,
      default: false
    },
    interactivePresets: {
      type: Boolean,
      default: false
    },
    /** 仪表板绩效区等紧凑布局 */
    compact: {
      type: Boolean,
      default: false
    }
  },
  computed: {
    initRows() {
      const mw = this.manualWeights;
      if (!mw || typeof mw !== 'object') return [];
      return Object.keys(mw)
        .map(c => String(c).trim())
        .filter(Boolean)
        .sort((a, b) => a.localeCompare(b))
        .map(code => {
          const v = Number(mw[code]);
          const ratio = Number.isFinite(v) ? v : 0;
          return { code, pct: ratio * 100 };
        });
    },
    presetBlocks() {
      const raw = this.manualAdjustments;
      if (!Array.isArray(raw) || !raw.length) return [];
      const blocks = raw
        .map(entry => {
          if (!entry || typeof entry !== 'object') return null;
          const d = this.normAdjDate(entry.date);
          if (!d) return null;
          const w = entry.weights && typeof entry.weights === 'object' ? entry.weights : {};
          const weightItems = Object.keys(w)
            .map(c => String(c).trim())
            .filter(Boolean)
            .sort((a, b) => a.localeCompare(b))
            .map(code => {
              const v = Number(w[code]);
              const ratio = Number.isFinite(v) ? v : 0;
              return { code, pct: ratio * 100 };
            });
          return {
            date: d,
            auto_normalize: !!entry.auto_normalize,
            weightItems
          };
        })
        .filter(Boolean);
      blocks.sort((a, b) => a.date.localeCompare(b.date));
      return blocks;
    }
  },
  methods: {
    normAdjDate(d) {
      if (d == null || d === '') return '';
      const s = String(d).trim();
      const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
      return m ? m[1] : s.slice(0, 10);
    },
    formatPct(pct) {
      if (pct == null || Number.isNaN(Number(pct))) return '—';
      return `${Number(pct).toFixed(2)}%`;
    },
    barWidth(pct) {
      if (pct == null || Number.isNaN(Number(pct))) return '0%';
      const w = Math.min(100, Math.max(0, Number(pct)));
      return `${w}%`;
    },
    onInitClick() {
      if (this.interactiveInit) this.$emit('init-click');
    },
    onPresetsClick() {
      if (this.interactivePresets) this.$emit('presets-click');
    }
  }
};
</script>

<style scoped>
.smws--compact .live-manual-snapshot {
  gap: 10px;
}

.smws--compact .subjective-snapshot-block {
  min-width: 220px;
  padding: 10px 12px 12px;
}

.smws--compact .weight-diff-name {
  flex: 0 0 132px;
}

.live-manual-snapshot {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 4px;
}

.subjective-snapshot-block {
  flex: 1 1 300px;
  min-width: 260px;
  max-width: 100%;
  padding: 12px 14px 14px;
  border-radius: 8px;
  background: linear-gradient(165deg, #f8fafc 0%, #f0f2f5 100%);
  border: 1px solid #ebeef5;
}

.subjective-snapshot-block--interactive {
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.subjective-snapshot-block--interactive:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}

.subjective-snapshot-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.subjective-snapshot-title {
  margin-bottom: 0 !important;
  padding-bottom: 0 !important;
  border-bottom: none !important;
}

.subjective-snapshot-inner {
  font-size: 13px;
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

.diff-hint {
  margin: 0;
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

.subjective-weight-row--single {
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
  flex: 1 1 200px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.subjective-weight-bars--single {
  flex: 1 1 220px;
}

.weight-pct {
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.weight-pct--current {
  color: #529b2e;
  flex: 0 0 52px;
  text-align: right;
}

.weight-bar-track {
  flex: 1 1 auto;
  height: 8px;
  border-radius: 4px;
  background: #ebeef5;
  overflow: hidden;
  min-width: 40px;
}

.weight-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.2s ease;
  min-width: 2px;
}

.weight-bar-fill--new {
  background: linear-gradient(90deg, #95d475, #67c23a);
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

.adj-card--snapshot {
  border-left: 3px solid #67c23a;
  background: #fbfff8;
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

.adj-card-bars {
  margin-top: 4px;
}

.subjective-edit-hint {
  font-size: 12px;
  font-weight: 500;
  color: #409eff;
}
</style>
