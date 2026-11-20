<template>
  <div class="op-detail">
    <div v-if="suggestionText" class="op-detail-suggestion">
      <i class="el-icon-info"></i> {{ suggestionText }}
    </div>

    <!-- 组合层指令：策略比重 → 穿透资产 两级拆解 -->
    <template v-if="op.strategy_breakdown && op.strategy_breakdown.length">
      <div class="detail-block-title">① 策略比重</div>
      <el-table :data="strategyRows" size="mini" border>
        <el-table-column label="策略" min-width="160" prop="name" />
        <el-table-column label="组合权重" width="110" align="right">
          <template slot-scope="scope">{{ formatPct(scope.row.weight) }}</template>
        </el-table-column>
        <el-table-column label="调整前权重" width="110" align="right">
          <template slot-scope="scope">{{ formatPct(scope.row.baseline) }}</template>
        </el-table-column>
        <el-table-column label="变动" width="130" align="right">
          <template slot-scope="scope">
            <span :class="changeClass(scope.row.change)">{{ formatChange(scope.row.change) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="detail-block-title">② 穿透资产目标权重</div>
      <el-table :data="weightRows" size="mini" border>
        <el-table-column label="资产" min-width="160">
          <template slot-scope="scope">
            <div class="asset-cell">
              <span class="asset-cell__name">{{ assetLabelResolver(scope.row.code) }}</span>
              <span v-if="assetLabelResolver(scope.row.code) !== scope.row.code" class="asset-cell__code">{{ scope.row.code }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="目标权重" width="100" align="right">
          <template slot-scope="scope">{{ formatPct(scope.row.target) }}</template>
        </el-table-column>
        <el-table-column label="拆解来源" min-width="300">
          <template slot-scope="scope">
            <div v-if="assetDerivations(scope.row.code).length" class="derivation-formulas">
              <div
                v-for="d in assetDerivations(scope.row.code)"
                :key="d.name"
                class="derivation-formula">
                {{ d.name }}：{{ formatPct(d.subW) }} × {{ formatPct(d.stratW) }} = {{ formatPct(d.contrib) }}
              </div>
            </div>
            <span v-else class="logic-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="变动" width="110" align="right">
          <template slot-scope="scope">
            <span :class="changeClass(scope.row.change)">{{ formatChange(scope.row.change) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- 单策略 / 子策略指令：资产权重明细 -->
    <template v-else>
      <el-table v-if="weightRows.length" :data="weightRows" size="mini" border>
        <el-table-column label="资产" min-width="160">
          <template slot-scope="scope">
            <div class="asset-cell">
              <span class="asset-cell__name">{{ assetLabelResolver(scope.row.code) }}</span>
              <span v-if="assetLabelResolver(scope.row.code) !== scope.row.code" class="asset-cell__code">{{ scope.row.code }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="调整前权重" width="110" align="right">
          <template slot-scope="scope">{{ formatPct(scope.row.baseline) }}</template>
        </el-table-column>
        <el-table-column label="目标权重" width="110" align="right">
          <template slot-scope="scope">{{ formatPct(scope.row.target) }}</template>
        </el-table-column>
        <el-table-column label="变动" width="130" align="right">
          <template slot-scope="scope">
            <span :class="changeClass(scope.row.change)">{{ formatChange(scope.row.change) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="op-detail-empty">无权重明细</div>
    </template>
  </div>
</template>

<script>
export default {
  name: 'OperationOpDetail',
  props: {
    /** 指令文档 */
    op: { type: Object, required: true },
    /** 「调整前」基准权重（小数形式），由父组件按指令状态解析（已执行取 prev_weights） */
    baselineWeights: { type: Object, default: () => ({}) },
    /** 资产键 → 展示名函数 */
    assetLabelResolver: { type: Function, default: c => c }
  },
  computed: {
    weightRows() {
      const tw = this.op.target_weights || {};
      const base = this.baselineWeights || {};
      const codes = new Set([...Object.keys(tw), ...Object.keys(base)]);
      return [...codes].sort().map(code => {
        const target = tw[code] != null ? Number(tw[code]) : 0;
        const baseline = base[code] != null ? Number(base[code]) : 0;
        return { code, target, baseline, change: target - baseline };
      });
    },
    /** 组合层指令：策略比重明细行（按权重降序） */
    strategyRows() {
      const prev = this.op.prev_strategy_weights || {};
      return (this.op.strategy_breakdown || [])
        .slice()
        .sort((a, b) => Number(b.weight) - Number(a.weight))
        .map(b => {
          const weight = Number(b.weight) || 0;
          const baseline = prev[b.strategy_key] != null ? Number(prev[b.strategy_key]) : 0;
          return {
            key: b.strategy_key,
            name: b.strategy_name || b.strategy_key,
            weight,
            baseline,
            change: weight - baseline
          };
        });
    },
    suggestionText() {
      const s = this.op.suggestion || {};
      if (s.description) return s.description;
      const parts = [];
      if (s.vol_trigger != null) parts.push(`实时波动 ${(Number(s.vol_trigger) * 100).toFixed(2)}%`);
      if (s.scale_factor != null) parts.push(`缩放系数 ${Number(s.scale_factor).toFixed(4)}`);
      return parts.join('；');
    }
  },
  methods: {
    /** 资产的拆解来源：该资产仓位 = Σ（策略内仓位 × 策略占组合比重） */
    assetDerivations(code) {
      const parts = [];
      (this.op.strategy_breakdown || []).forEach(b => {
        const subW = Number((b.asset_weights || {})[code]);
        if (!subW) return;
        const stratW = Number(b.weight) || 0;
        parts.push({
          name: b.strategy_name || b.strategy_key,
          subW,
          stratW,
          contrib: stratW * subW
        });
      });
      return parts;
    },
    formatPct(v) {
      if (v == null) return '—';
      return (Number(v) * 100).toFixed(2) + '%';
    },
    formatChange(change) {
      const pct = (change * 100).toFixed(2);
      if (change > 0.00001) return '+' + pct + '%';
      if (change < -0.00001) return pct + '%';
      return '不变';
    },
    changeClass(change) {
      if (change > 0.00001) return 'change-increase';
      if (change < -0.00001) return 'change-decrease';
      return 'change-none';
    }
  }
};
</script>

<style scoped>
.op-detail {
  padding: 8px 12px 8px 48px;
}

.op-detail-suggestion {
  font-size: 12px;
  color: #e6a23c;
  margin-bottom: 8px;
}

.op-detail-empty {
  font-size: 12px;
  color: #909399;
}

.detail-block-title {
  font-size: 12px;
  font-weight: 600;
  color: #303133;
  margin: 8px 0 6px 0;
}

.asset-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.asset-cell__name {
  color: #303133;
}

.asset-cell__code {
  font-size: 11px;
  color: #909399;
}

.derivation-formulas {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
}

.logic-muted {
  font-size: 12px;
  color: #909399;
}

.change-increase {
  color: #f56c6c;
  font-weight: 500;
}

.change-decrease {
  color: #67c23a;
  font-weight: 500;
}

.change-none {
  color: #909399;
}
</style>
