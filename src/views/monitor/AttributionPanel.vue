<template>
  <div class="attribution-panel" v-loading="loading">
    <el-alert
      v-if="showWarningAlert"
      :title="warning"
      type="warning"
      :closable="false"
      show-icon
      class="attribution-alert" />
    <el-table
      v-if="items.length > 0"
      :data="items"
      size="mini"
      border
      stripe
      style="width: 100%;">
      <el-table-column type="index" label="#" width="46" align="center"></el-table-column>
      <el-table-column prop="name" label="资产名称" min-width="150" show-overflow-tooltip>
        <template slot-scope="scope">
          <span
            :class="{ 'other-row': scope.row.code === '__other__' }"
            :title="scope.row.code === '__other__' ? otherNote : scope.row.name">
            {{ scope.row.name }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="asset_class" label="类别" width="96" align="center">
        <template slot-scope="scope">
          <el-tag :type="getAssetClassType(scope.row.asset_class)" size="mini">
            {{ scope.row.asset_class || '未分类' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="区间涨跌" width="104" align="right">
        <template slot-scope="scope">
          <span :class="returnClass(scope.row.period_return)">
            {{ formatSignedPct(scope.row.period_return) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="平均权重" width="104" align="right">
        <template slot-scope="scope">
          <span>{{ formatPct(scope.row.weight) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="收益贡献" min-width="200" align="right">
        <template slot-scope="scope">
          <div class="contribution-cell">
            <div class="contribution-bar-bg">
              <div
                class="contribution-bar-fill"
                :style="{
                  width: barWidth(scope.row.contribution),
                  backgroundColor: scope.row.contribution >= 0 ? '#F56C6C' : '#67C23A'
                }"></div>
            </div>
            <span :class="returnClass(scope.row.contribution)" class="contribution-num">
              {{ formatSignedPoints(scope.row.contribution) }}
            </span>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <el-empty
      v-else
      :description="emptyDescription"
      :image-size="80" />
    <div v-if="items.length > 0" class="attribution-footnote">
      贡献为 NAV 链接多期归因（调仓次日生效、人民币口径），与「其他」合计等于区间收益；区间涨跌与平均权重为资产区间口径，与贡献不构成简单乘积（权重逐日变化）。
    </div>
  </div>
</template>

<script>
import { mapGetters, mapState } from 'vuex';

export default {
  name: 'MonitorAttributionPanel',
  computed: {
    ...mapState('monitor', ['performancePanel']),
    ...mapGetters('monitor', ['isLoading']),
    loading() {
      return this.isLoading && !this.performancePanel;
    },
    attribution() {
      return (this.performancePanel && this.performancePanel.attribution) || {};
    },
    /** 后端归因口径提示（持仓覆盖不足等） */
    warning() {
      return this.attribution.warning || '';
    },
    showWarningAlert() {
      return !!this.warning && this.items.length > 0;
    },
    /** 「其他」项口径说明：= 区间收益 − 各资产贡献 */
    otherNote() {
      return this.attribution.other_note || '区间收益 − 各资产贡献';
    },
    emptyDescription() {
      return this.warning || '该周期内暂无可归因的资产收益';
    },
    /** 后端已按收益贡献降序返回，直接展示 */
    items() {
      return this.attribution.items || [];
    },
    /** 贡献条形归一化基数：绝对值最大的贡献 */
    maxAbsContribution() {
      return this.items.reduce(
        (max, item) => Math.max(max, Math.abs(Number(item.contribution) || 0)),
        0
      );
    }
  },
  methods: {
    barWidth(contribution) {
      if (!this.maxAbsContribution) return '0%';
      return `${Math.min(Math.abs(Number(contribution) || 0) / this.maxAbsContribution * 100, 100)}%`;
    },
    getAssetClassType(assetClass) {
      const typeMap = {
        '权益': 'primary',
        '固定收益': 'success',
        '大宗商品': 'warning'
      };
      return typeMap[assetClass] || 'info';
    },
    /** 百分数 → +12.34% */
    formatSignedPoints(num) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      const value = Number(num);
      return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
    },
    /** 小数 → 12.34% */
    formatPct(num) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      return `${Number(num).toFixed(2)}%`;
    },
    /** 小数收益 → +12.34% */
    formatSignedPct(num) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      const value = Number(num) * 100;
      return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
    },
    returnClass(value) {
      if (value === null || value === undefined || value === 0) return 'number-neutral';
      return value > 0 ? 'number-positive' : 'number-negative';
    }
  }
};
</script>

<style scoped>
.attribution-panel {
  flex: 1;
  min-height: 0;
}

.attribution-alert {
  margin-bottom: 8px;
}

.attribution-footnote {
  margin-top: 8px;
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
}

.contribution-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.other-row {
  color: #909399;
  font-style: italic;
}

.contribution-bar-bg {
  flex: 1;
  min-width: 40px;
  height: 8px;
  background: #f0f2f5;
  border-radius: 4px;
  overflow: hidden;
}

.contribution-bar-fill {
  height: 100%;
  border-radius: 4px;
}

.contribution-num {
  min-width: 62px;
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>
