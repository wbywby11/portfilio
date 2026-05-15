<template>
  <div class="swfp">
    <!-- 初始化权重 -->
    <div class="swfp-section">
      <div class="swfp-section-head">
        <span class="swfp-section-title">默认资产权重</span>
      </div>
      <p class="swfp-hint">
        为期初建仓设置各底层资产权重（0～100%）。合计建议为 100%；超过 100% 无法保存。可使用滑块或数字微调；下方条形为当前占比示意。
      </p>
      <div v-if="!assetCodes.length" class="swfp-empty">请先在上方「选择资产」中至少选择一个资产</div>
      <div v-else class="subjective-editor-body swfp-editor">
        <div v-for="code in assetCodes" :key="'swfp-init-' + code" class="swfp-init-block">
          <div class="subjective-editor-row">
            <span class="subjective-editor-label" :title="code">{{ resolveLabel(code) }}</span>
            <el-slider
              :value="weightOf(code)"
              :min="0"
              :max="1"
              :step="0.01"
              :format-tooltip="formatWeightSliderTooltip"
              class="subjective-editor-slider"
              @input="v => setInitWeight(code, v)" />
            <el-input-number
              :value="weightOf(code)"
              :min="0"
              :max="1"
              :step="0.05"
              :precision="2"
              size="small"
              controls-position="right"
              class="subjective-editor-num"
              @change="v => setInitWeight(code, v)" />
          </div>
          <div class="swfp-bar-row">
            <span class="weight-pct weight-pct--current">{{ formatPct(weightOf(code) * 100) }}</span>
            <div class="weight-bar-track">
              <div
                class="weight-bar-fill weight-bar-fill--new"
                :style="{ width: barWidth(weightOf(code)) }" />
            </div>
          </div>
        </div>
        <div class="subjective-sum-bar">
          <span :class="manualInitSumClass">权重合计：{{ manualInitSumPct }}%</span>
          <el-button type="text" size="small" @click="normalizeManualInit">归一化到 100%</el-button>
        </div>
      </div>
    </div>

    <!-- 预设调仓 -->
    <div class="swfp-section swfp-section--presets">
      <div class="swfp-section-head">
        <span class="swfp-section-title">预设调仓日期与权重</span>
      </div>
      <p class="swfp-hint">
        每个调仓日配置当日目标权重。「保存时归一化」或本条「归一化到 100%」会按当前比例缩放到合计 100%，且结果保留两位小数。至少保留一条已填日期的记录。
      </p>
      <div v-if="!assetCodes.length" class="swfp-empty">请先在上方「选择资产」中至少选择一个资产</div>
      <template v-else>
        <div
          v-for="(row, idx) in adjustments"
          :key="'swfp-preset-' + idx"
          class="subjective-preset-card">
          <div class="subjective-preset-head">
            <span class="subjective-preset-title">调仓日 {{ idx + 1 }}</span>
            <el-button type="text" class="subjective-preset-remove" @click="$emit('remove-preset', idx)">删除本条</el-button>
          </div>
          <div class="subjective-preset-toolbar">
            <el-date-picker
              v-model="row.date"
              type="date"
              placeholder="选择调仓日期"
              size="small"
              value-format="yyyy-MM-dd"
              style="width: 168px;" />
            <span class="subjective-preset-switch-label">保存时归一化</span>
            <el-switch v-model="row.auto_normalize" />
          </div>
          <div class="subjective-preset-weights">
            <div class="subjective-preset-weight-actions">
              <el-button type="text" size="small" @click="applyPresetRowNormalize(row)">归一化到 100%</el-button>
              <span class="subjective-preset-weight-actions-hint">按当前比例，保留两位小数</span>
            </div>
            <div v-for="code in assetCodes" :key="'swfp-pw-' + idx + '-' + code" class="swfp-init-block">
              <div class="subjective-editor-row subjective-editor-row--compact">
                <span class="subjective-editor-label" :title="code">{{ resolveLabel(code) }}</span>
                <el-slider
                  :value="presetWeight(row, code)"
                  :min="0"
                  :max="1"
                  :step="0.01"
                  :format-tooltip="formatWeightSliderTooltip"
                  class="subjective-editor-slider"
                  @input="v => setPresetWeight(row, code, v)" />
                <el-input-number
                  :value="presetWeight(row, code)"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :precision="4"
                  size="small"
                  controls-position="right"
                  class="subjective-editor-num"
                  @change="v => setPresetWeight(row, code, v)" />
              </div>
              <div class="swfp-bar-row swfp-bar-row--compact">
                <span class="weight-pct weight-pct--current">{{ formatPct(presetWeight(row, code) * 100) }}</span>
                <div class="weight-bar-track">
                  <div
                    class="weight-bar-fill weight-bar-fill--new"
                    :style="{ width: barWidth(presetWeight(row, code)) }" />
                </div>
              </div>
            </div>
            <div class="subjective-preset-row-sum" :class="manualPresetRowSumClass(row)">
              本条权重合计：{{ manualPresetRowSumPct(row) }}%
            </div>
          </div>
        </div>
        <el-button type="primary" plain size="small" icon="el-icon-plus" class="swfp-add-btn" @click="$emit('add-preset')">
          添加调仓日
        </el-button>
      </template>
    </div>
  </div>
</template>

<script>
import {
  normalizeWeightsToTwoDecimalSumOne,
  formatWeightSliderTooltip,
  subjectiveBarWidthPct
} from '@/utils/subjectiveWeights';

export default {
  name: 'SubjectiveWeightsFormPanel',
  props: {
    assetCodes: {
      type: Array,
      default: () => []
    },
    manualWeights: {
      type: Object,
      required: true
    },
    manualWeightAdjustments: {
      type: Array,
      required: true
    },
    resolveLabel: {
      type: Function,
      required: true
    }
  },
  computed: {
    adjustments() {
      return this.manualWeightAdjustments;
    },
    manualInitSumRatio() {
      return this.assetCodes.reduce((s, c) => s + (Number(this.manualWeights[c]) || 0), 0);
    },
    manualInitSumPct() {
      return (this.manualInitSumRatio * 100).toFixed(1);
    },
    manualInitSumClass() {
      return this.manualInitSumRatio > 1.00001 ? 'subjective-sum--warn' : '';
    }
  },
  methods: {
    formatWeightSliderTooltip,
    weightOf(code) {
      const v = this.manualWeights[code];
      return v != null && !Number.isNaN(Number(v)) ? Number(v) : 0;
    },
    setInitWeight(code, v) {
      let n = v != null && !Number.isNaN(Number(v)) ? Number(v) : 0;
      if (n < 0) n = 0;
      if (n > 1) n = 1;
      this.$set(this.manualWeights, code, n);
    },
    presetWeight(row, code) {
      if (!row || !row.weights) return 0;
      const v = row.weights[code];
      return v != null && !Number.isNaN(Number(v)) ? Number(v) : 0;
    },
    setPresetWeight(row, code, v) {
      if (!row.weights || typeof row.weights !== 'object') {
        this.$set(row, 'weights', {});
      }
      let n = v != null && !Number.isNaN(Number(v)) ? Number(v) : 0;
      if (n < 0) n = 0;
      if (n > 1) n = 1;
      this.$set(row.weights, code, n);
    },
    normalizeManualInit() {
      const t = this.manualInitSumRatio;
      if (t <= 0) {
        this.$message.warning('合计为 0，无法归一化');
        return;
      }
      this.assetCodes.forEach(c => {
        this.$set(this.manualWeights, c, (Number(this.manualWeights[c]) || 0) / t);
      });
    },
    applyPresetRowNormalize(row) {
      if (!row || !row.weights || !this.assetCodes.length) return;
      const w = {};
      this.assetCodes.forEach(c => {
        w[c] = Number(row.weights[c]) || 0;
      });
      const t = this.assetCodes.reduce((s, c) => s + w[c], 0);
      if (t <= 0) {
        this.$message.warning('本条权重合计为 0，无法归一化');
        return;
      }
      const out = normalizeWeightsToTwoDecimalSumOne(w, this.assetCodes);
      this.assetCodes.forEach(c => {
        this.$set(row.weights, c, out[c]);
      });
    },
    manualPresetRowSumRatio(row) {
      if (!row || !row.weights) return 0;
      return this.assetCodes.reduce((s, c) => s + (Number(row.weights[c]) || 0), 0);
    },
    manualPresetRowSumPct(row) {
      return (this.manualPresetRowSumRatio(row) * 100).toFixed(1);
    },
    manualPresetRowSumClass(row) {
      const r = this.manualPresetRowSumRatio(row);
      return r > 1.00001 && !row.auto_normalize ? 'subjective-sum--warn' : '';
    },
    formatPct(pct) {
      if (pct == null || Number.isNaN(Number(pct))) return '—';
      return `${Number(pct).toFixed(2)}%`;
    },
    barWidth(ratio) {
      return subjectiveBarWidthPct(ratio);
    }
  }
};
</script>

<style scoped>
.swfp {
  width: 100%;
}

.swfp-section {
  margin-bottom: 24px;
}

.swfp-section--presets {
  padding-top: 8px;
  border-top: 1px dashed #e4e7ed;
}

.swfp-section-head {
  margin-bottom: 8px;
}

.swfp-section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.swfp-hint {
  margin: 0 0 12px 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
}

.swfp-empty {
  padding: 20px 16px;
  text-align: center;
  color: #909399;
  font-size: 13px;
  background: #fafafa;
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
}

.subjective-editor-body {
  max-height: none;
  overflow: visible;
  padding-right: 0;
}

.swfp-editor {
  padding: 12px 14px 14px;
  border-radius: 8px;
  background: linear-gradient(165deg, #f8fafc 0%, #f0f2f5 100%);
  border: 1px solid #ebeef5;
}

.swfp-init-block {
  margin-bottom: 6px;
}

.swfp-init-block:last-of-type {
  margin-bottom: 0;
}

.subjective-editor-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.subjective-editor-row--compact {
  margin-bottom: 4px;
}

.subjective-editor-label {
  flex: 0 0 148px;
  font-size: 13px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subjective-editor-slider {
  flex: 1 1 auto;
  min-width: 0;
  padding: 0 6px;
}

.subjective-editor-num {
  flex: 0 0 108px;
  width: 108px !important;
}

.swfp-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 10px 160px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e8ecf1;
}

.swfp-bar-row--compact {
  margin-left: 160px;
  margin-bottom: 6px;
  padding-bottom: 6px;
}

.swfp-init-block:last-child .swfp-bar-row {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
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

.subjective-sum-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
  font-size: 13px;
  color: #606266;
}

.subjective-sum--warn {
  color: #e6a23c;
  font-weight: 600;
}

.subjective-preset-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
  background: #fafafa;
}

.subjective-preset-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.subjective-preset-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.subjective-preset-remove {
  color: #f56c6c !important;
}

.subjective-preset-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.subjective-preset-switch-label {
  font-size: 13px;
  color: #606266;
}

.subjective-preset-weights {
  padding-top: 4px;
  border-top: 1px dashed #dcdfe6;
}

.subjective-preset-weight-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.subjective-preset-weight-actions-hint {
  font-size: 12px;
  color: #909399;
}

.subjective-preset-row-sum {
  font-size: 12px;
  color: #909399;
  margin-top: 8px;
  text-align: right;
}

.swfp-add-btn {
  margin-top: 4px;
}
</style>
