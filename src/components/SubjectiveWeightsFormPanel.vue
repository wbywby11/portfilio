<template>
  <div class="swfp">
    <!-- 初始化权重 -->
    <div class="swfp-section">
      <div
        class="swfp-section-head swfp-section-head--toggle"
        :class="{ 'is-open': !initCollapsed }"
        role="button"
        tabindex="0"
        :aria-expanded="String(!initCollapsed)"
        @click="toggleInitCollapsed"
        @keydown.enter.prevent="toggleInitCollapsed"
        @keydown.space.prevent="toggleInitCollapsed">
        <div class="swfp-head-left">
          <span class="swfp-section-title">默认资产权重</span>
          <div v-if="assetCodes.length" class="swfp-summary-chips" @click.stop>
            <span class="swfp-chip swfp-chip--total">
              <i class="el-icon-coin"></i>
              <em>{{ assetCodes.length }}</em><span class="swfp-chip-unit">个资产</span>
            </span>
            <span class="swfp-chip-sep">·</span>
            <span class="swfp-chip swfp-chip--configured">
              已配置 <em>{{ manualInitConfiguredCount }}</em>
            </span>
            <span class="swfp-chip-sep">·</span>
            <span class="swfp-chip" :class="manualInitSumChipClass">
              总权重 <em>{{ manualInitSumPct }}%</em>
            </span>
            <span class="swfp-mini-meter" :title="`权重合计 ${manualInitSumPct}%`">
              <span
                class="swfp-mini-meter__fill"
                :class="manualInitSumChipClass"
                :style="{ width: miniMeterWidth }"></span>
            </span>
          </div>
        </div>
        <button type="button" class="swfp-toggle-btn" @click.stop="toggleInitCollapsed">
          <span>{{ initCollapsed ? '展开详情' : '收起' }}</span>
          <i class="el-icon-arrow-down swfp-toggle-arrow"></i>
        </button>
      </div>
      <p v-if="!initCollapsed" class="swfp-hint">
        为期初建仓设置各底层资产权重（0～100%）。合计建议为 100%；超过 100% 无法保存。可使用滑块或数字微调；下方条形为当前占比示意。
      </p>
      <el-collapse-transition>
        <div v-show="!initCollapsed">
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
      </el-collapse-transition>
    </div>

    <!-- 预设调仓 -->
    <div class="swfp-section swfp-section--presets">
      <div class="swfp-section-head">
        <span class="swfp-section-title">预设调仓日期与权重</span>
      </div>
      <p class="swfp-hint">
        以矩阵方式编辑各调仓日的目标权重（百分比）。点击单元格直接编辑，支持行内归一化、复制、等权填充等操作；至少保留一条已填日期的记录。
      </p>
      <div v-if="!assetCodes.length" class="swfp-empty">请先在上方「选择资产」中至少选择一个资产</div>
      <SubjectiveWeightsMatrixTable
        v-else
        :asset-codes="assetCodes"
        :resolve-label="resolveLabel"
        :adjustments="manualWeightAdjustments"
        :max-leverage="maxLeverage"
        @update:adjustments="onAdjustmentsUpdate"
      />
    </div>
  </div>
</template>

<script>
import {
  formatWeightSliderTooltip,
  subjectiveBarWidthPct
} from '@/utils/subjectiveWeights';
import SubjectiveWeightsMatrixTable from './SubjectiveWeightsMatrixTable.vue';

export default {
  name: 'SubjectiveWeightsFormPanel',
  components: { SubjectiveWeightsMatrixTable },
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
    },
    maxLeverage: {
      type: Number,
      default: 1
    }
  },
  computed: {
    manualInitSumRatio() {
      return this.assetCodes.reduce((s, c) => s + (Number(this.manualWeights[c]) || 0), 0);
    },
    manualInitSumPct() {
      return (this.manualInitSumRatio * 100).toFixed(1);
    },
    manualInitSumClass() {
      return this.manualInitSumRatio > 1.00001 ? 'subjective-sum--warn' : '';
    },
    manualInitConfiguredCount() {
      return this.assetCodes.reduce((n, c) => {
        const v = Number(this.manualWeights[c]);
        return n + (v > 0 ? 1 : 0);
      }, 0);
    },
    manualInitSumChipClass() {
      const r = this.manualInitSumRatio;
      if (r > 1.00001) return 'is-over';
      if (Math.abs(r - 1) < 0.005) return 'is-perfect';
      if (r > 0) return 'is-partial';
      return 'is-empty';
    },
    miniMeterWidth() {
      const r = this.manualInitSumRatio;
      if (!(r > 0)) return '0%';
      const pct = Math.min(r, 1) * 100;
      return pct.toFixed(2) + '%';
    }
  },
  data() {
    return {
      initCollapsed: true
    };
  },
  methods: {
    formatWeightSliderTooltip,
    toggleInitCollapsed() {
      this.initCollapsed = !this.initCollapsed;
    },
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
    /**
     * 矩阵表格更新调仓权重列表：
     * 1. 原地替换数组内容，保持父组件引用一致（兼容现有非 .sync 绑定）
     * 2. 同步抛出 update:manualWeightAdjustments，兼容 .sync 写法
     */
    onAdjustmentsUpdate(newList) {
      const list = Array.isArray(newList) ? newList : [];
      if (Array.isArray(this.manualWeightAdjustments)) {
        this.manualWeightAdjustments.splice(0, this.manualWeightAdjustments.length, ...list);
      }
      this.$emit('update:manualWeightAdjustments', list);
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
  letter-spacing: 0.2px;
}

/* —— 可折叠表头 —— */
.swfp-section-head--toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 10px;
  border-radius: 8px;
  background: linear-gradient(135deg, #f5f8ff 0%, #f7faf6 100%);
  border: 1px solid #e4ebf5;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
  user-select: none;
  position: relative;
  overflow: hidden;
}

.swfp-section-head--toggle::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, #409eff, #67c23a);
  opacity: 0.7;
}

.swfp-section-head--toggle:hover {
  border-color: #c6d8f4;
  box-shadow: 0 2px 10px rgba(64, 158, 255, 0.08);
}

.swfp-section-head--toggle:focus-visible {
  outline: 2px solid #409eff;
  outline-offset: 2px;
}

.swfp-section-head--toggle.is-open {
  background: linear-gradient(135deg, #eef4ff 0%, #f0f9ec 100%);
  border-color: #c6d8f4;
}

.swfp-head-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  min-width: 0;
  flex: 1 1 auto;
}

/* —— 摘要 chips —— */
.swfp-summary-chips {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
  color: #5c6b80;
}

.swfp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid #e4ebf5;
  font-variant-numeric: tabular-nums;
  line-height: 1.6;
}

.swfp-chip i {
  font-size: 12px;
  color: #909399;
}

.swfp-chip em {
  font-style: normal;
  font-weight: 600;
  color: #303133;
  margin: 0 2px;
}

.swfp-chip-unit {
  color: #909399;
}

.swfp-chip-sep {
  color: #c8d0dc;
}

.swfp-chip--configured em {
  color: #409eff;
}

.swfp-chip.is-empty em { color: #909399; }
.swfp-chip.is-partial em { color: #e6a23c; }
.swfp-chip.is-perfect {
  background: rgba(103, 194, 58, 0.08);
  border-color: rgba(103, 194, 58, 0.4);
}
.swfp-chip.is-perfect em { color: #67c23a; }
.swfp-chip.is-over {
  background: rgba(245, 108, 108, 0.08);
  border-color: rgba(245, 108, 108, 0.4);
}
.swfp-chip.is-over em { color: #f56c6c; }

/* —— 迷你进度条 —— */
.swfp-mini-meter {
  display: inline-block;
  width: 64px;
  height: 4px;
  border-radius: 2px;
  background: #e4e7ed;
  overflow: hidden;
  margin-left: 2px;
}

.swfp-mini-meter__fill {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: linear-gradient(90deg, #95d475, #67c23a);
  transition: width 0.25s ease;
}

.swfp-mini-meter__fill.is-partial {
  background: linear-gradient(90deg, #f3d19e, #e6a23c);
}
.swfp-mini-meter__fill.is-over {
  background: linear-gradient(90deg, #f89898, #f56c6c);
}
.swfp-mini-meter__fill.is-empty {
  background: #dcdfe6;
}

/* —— 切换按钮 —— */
.swfp-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 12px;
  color: #409eff;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
  flex: 0 0 auto;
}

.swfp-toggle-btn:hover {
  background: rgba(64, 158, 255, 0.08);
  border-color: rgba(64, 158, 255, 0.3);
}

.swfp-toggle-arrow {
  transition: transform 0.25s ease;
}

.swfp-section-head--toggle.is-open .swfp-toggle-arrow {
  transform: rotate(180deg);
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
</style>
