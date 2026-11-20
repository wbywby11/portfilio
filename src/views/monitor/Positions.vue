<template>
  <div class="positions-panel" v-loading="loading">
    <!-- 持仓汇总指标 -->
    <div class="summary-grid">
      <div class="summary-card">
        <div class="summary-label">总杠杆</div>
        <div class="summary-value">{{ formatNumber(positions.total_leverage, 2) }}</div>
      </div>
      <div class="summary-card">
        <div class="summary-label">持仓资产数</div>
        <div class="summary-value">{{ positions.count || 0 }}</div>
      </div>
      <div class="summary-card">
        <div class="summary-label">最大持仓</div>
        <div class="summary-value">{{ formatPercent(summary.maxWeight) }}</div>
      </div>
      <div class="summary-card">
        <div class="summary-label">Top3 集中度</div>
        <div class="summary-value" :style="{ color: summary.top3Concentration > 60 ? '#F56C6C' : '#303133' }">
          {{ formatPercent(summary.top3Concentration) }}
        </div>
      </div>
    </div>

    <!-- 类别权重小计 -->
    <div class="category-bar" v-if="byClass.length > 0">
      <span class="category-label">类别权重</span>
      <span v-for="item in byClass" :key="item.category" class="category-item">
        <el-tag :type="getAssetClassType(item.category)" size="mini">{{ item.category }}</el-tag>
        <span class="category-weight">{{ formatPercent(item.weight) }}</span>
      </span>
    </div>

    <!-- 持仓表格 -->
    <el-table
      v-if="items.length > 0"
      :data="sortedItems"
      border
      stripe
      style="width: 100%;"
      size="small"
      height="100%">
      <el-table-column type="index" label="#" width="45" align="center"></el-table-column>
      <el-table-column prop="name" label="资产名称" min-width="140" show-overflow-tooltip>
        <template slot-scope="scope">
          <span class="asset-name-cell" :title="scope.row.code">{{ scope.row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="asset_class" label="类别" width="96" align="center">
        <template slot-scope="scope">
          <el-tag :type="getAssetClassType(scope.row.asset_class)" size="mini">
            {{ scope.row.asset_class || '未分类' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="权重" width="170">
        <template slot-scope="scope">
          <div class="weight-bar-cell">
            <span class="weight-num">{{ formatPercent(scope.row.current_weight) }}</span>
            <div class="weight-bar-bg">
              <div
                class="weight-bar-fill"
                :style="{
                  width: barWidth(scope.row.current_weight),
                  backgroundColor: scope.row.current_weight >= 0 ? '#409EFF' : '#E6A23C'
                }"></div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="当日涨跌" width="104" align="right">
        <template slot-scope="scope">
          <span :class="returnClass(scope.row.daily_change)">
            {{ formatSignedPercent(scope.row.daily_change) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="currency" label="货币" width="70" align="center">
        <template slot-scope="scope">
          <span class="currency-cell">{{ scope.row.currency || '—' }}</span>
        </template>
      </el-table-column>
    </el-table>
    <el-empty
      v-else
      description="该周期内暂无持仓快照，请先运行监控初始化或日常运行"
      :image-size="80" />
  </div>
</template>

<script>
import { mapGetters, mapState } from 'vuex';

export default {
  name: 'MonitorPositions',
  computed: {
    ...mapState('monitor', ['performancePanel']),
    ...mapGetters('monitor', ['isLoading']),
    loading() {
      return this.isLoading && !this.performancePanel;
    },
    positions() {
      return (this.performancePanel && this.performancePanel.positions) || {};
    },
    items() {
      return this.positions.items || [];
    },
    byClass() {
      return this.positions.by_class || [];
    },
    sortedItems() {
      return this.items.slice().sort((a, b) => (
        Math.abs(Number(b.current_weight) || 0) - Math.abs(Number(a.current_weight) || 0)
      ));
    },
    summary() {
      const weights = this.items.map(p => Math.abs(Number(p.current_weight) || 0));
      const maxWeight = weights.length ? Math.max(...weights) : 0;
      const top3 = weights.slice().sort((a, b) => b - a).slice(0, 3);
      return {
        maxWeight,
        top3Concentration: top3.reduce((sum, w) => sum + w, 0)
      };
    }
  },
  methods: {
    barWidth(weight) {
      const maxWeight = this.summary.maxWeight;
      if (!maxWeight) return '0%';
      return `${Math.min(Math.abs(Number(weight) || 0) / maxWeight * 100, 100)}%`;
    },
    getAssetClassType(assetClass) {
      const typeMap = {
        '权益': 'primary',
        '固定收益': 'success',
        '大宗商品': 'warning'
      };
      return typeMap[assetClass] || 'info';
    },
    formatNumber(num, decimals = 2) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      return Number(num).toFixed(decimals);
    },
    formatPercent(num) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      return `${Number(num).toFixed(2)}%`;
    },
    formatSignedPercent(num) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      return `${Number(num) >= 0 ? '+' : ''}${Number(num).toFixed(2)}%`;
    },
    returnClass(value) {
      if (value === null || value === undefined || value === 0) return 'number-neutral';
      return value > 0 ? 'number-positive' : 'number-negative';
    }
  }
};
</script>

<style scoped>
.positions-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.positions-panel >>> .el-table {
  flex: 1;
  min-height: 0;
}

.positions-panel >>> .el-empty {
  margin: auto;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}

.summary-card {
  text-align: center;
  padding: 10px 8px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.summary-value {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.category-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 12px;
  background: #f8fafc;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.category-label {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}

.category-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.category-weight {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.weight-bar-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.weight-num {
  font-size: 13px;
  font-weight: 600;
  min-width: 52px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.weight-bar-bg {
  flex: 1;
  height: 8px;
  background: #f0f2f5;
  border-radius: 4px;
  overflow: hidden;
}

.weight-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.asset-name-cell {
  font-weight: 500;
}

.currency-cell {
  color: #909399;
  font-size: 12px;
}

@media (max-width: 1400px) {
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
