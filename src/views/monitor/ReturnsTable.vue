<template>
  <div class="returns-panel" v-loading="loading">
    <template v-if="rows.length > 0">
      <el-table
        :data="pagedRows"
        border
        stripe
        size="small"
        height="100%"
        style="width: 100%;">
        <el-table-column prop="date" label="日期" min-width="96" align="center"></el-table-column>
        <el-table-column label="净值" min-width="80" align="right">
          <template slot-scope="scope">{{ formatNumber(scope.row.nav, 4) }}</template>
        </el-table-column>
        <el-table-column label="日收益率" min-width="90" align="right">
          <template slot-scope="scope">
            <span :class="returnClass(scope.row.daily_return)">
              {{ formatSignedPercent(scope.row.daily_return) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="区间累计" min-width="90" align="right">
          <template slot-scope="scope">
            <span :class="returnClass(scope.row.cumulative_return)">
              {{ formatSignedPercent(scope.row.cumulative_return) }}
            </span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        :current-page.sync="page"
        :page-size="pageSize"
        :total="rows.length"
        layout="total, prev, pager, next"
        small
        class="panel-pagination" />
    </template>
    <el-empty
      v-else
      description="该周期内暂无收益数据"
      :image-size="80" />
  </div>
</template>

<script>
import { mapGetters, mapState } from 'vuex';

/** 每页条数：与页面统一周期无关，仅影响表格翻页密度 */
const PAGE_SIZE = 20;

export default {
  name: 'MonitorReturnsTable',
  data() {
    return {
      page: 1,
      pageSize: PAGE_SIZE
    };
  },
  computed: {
    ...mapState('monitor', ['performancePanel']),
    ...mapGetters('monitor', ['isLoading']),
    loading() {
      return this.isLoading && !this.performancePanel;
    },
    navRows() {
      return (this.performancePanel && this.performancePanel.nav_history) || [];
    },
    /** 区间内全部交易日，最新在前（区间首日无前收，不参与日收益统计） */
    rows() {
      return this.navRows.length < 2 ? [] : this.navRows.slice(1).reverse();
    },
    pagedRows() {
      const start = (this.page - 1) * this.pageSize;
      return this.rows.slice(start, start + this.pageSize);
    }
  },
  watch: {
    rows() {
      this.page = 1;
    }
  },
  methods: {
    formatNumber(num, decimals = 2) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      return Number(num).toFixed(decimals);
    },
    formatSignedPercent(num) {
      if (num === null || num === undefined || Number.isNaN(Number(num))) return '—';
      return `${Number(num) >= 0 ? '+' : ''}${(Number(num) * 100).toFixed(2)}%`;
    },
    returnClass(value) {
      if (value === null || value === undefined || value === 0) return 'number-neutral';
      return value > 0 ? 'number-positive' : 'number-negative';
    }
  }
};
</script>

<style scoped>
.returns-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.returns-panel >>> .el-table {
  flex: 1;
  min-height: 0;
}

.panel-pagination {
  margin-top: 10px;
  text-align: right;
}
</style>
