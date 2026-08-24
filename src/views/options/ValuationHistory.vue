<template>
  <div class="history-page">
    <!-- 顶部标题 -->
    <div class="page-header">
      <h2 class="page-title">估值历史</h2>
      <p class="page-desc">查看估值工作台的历次运行结果，回溯产品估值变化</p>
    </div>

    <!-- 查询条件 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="yyyy-MM-dd"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          size="small"
          style="width: 300px;"
        />
        <el-button type="primary" icon="el-icon-search" size="small" @click="loadHistory" :loading="loading" style="margin-left: 8px;">
          查询
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-button icon="el-icon-download" size="small" @click="handleExport" :disabled="!history.length">
          导出 Excel
        </el-button>
      </div>
    </div>

    <!-- 历史表格 -->
    <div class="table-area">
      <vxe-table
        :data="history"
        :loading="loading"
        border
        stripe
        :height="selectedProduct ? 360 : 520"
        :scroll-y="{enabled: true, gt: 0}"
        show-overflow="title"
        @row-click="handleRowClick"
        :row-class-name="rowClassName"
      >
        <vxe-column field="date" title="日期" width="110" sortable />
        <vxe-column field="product_id" title="产品编号" width="120" />
        <vxe-column field="type" title="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ typeLabel(row.type) }}</el-tag>
          </template>
        </vxe-column>
        <vxe-column field="principal" title="本金" min-width="130" align="right">
          <template #default="{ row }">{{ formatNum(row.principal) }}</template>
        </vxe-column>
        <vxe-column field="price_total" title="估值" min-width="140" align="right">
          <template #default="{ row }">
            <span style="font-weight: 600;">{{ formatNum(row.price_total) }}</span>
          </template>
        </vxe-column>
        <vxe-column title="变动%" min-width="100" align="right">
          <template #default="{ row }">
            <span v-if="row._pctChange != null" :class="row._pctChange >= 0 ? 'val-positive' : 'val-negative'">
              {{ row._pctChange >= 0 ? '+' : '' }}{{ row._pctChange.toFixed(2) }}%
            </span>
            <span v-else style="color: #c0c4cc;">-</span>
          </template>
        </vxe-column>
        <vxe-column field="method" title="方法" min-width="120">
          <template #default="{ row }">
            <el-tag size="mini" type="info">{{ methodLabel(row.method) }}</el-tag>
          </template>
        </vxe-column>
      </vxe-table>
    </div>

    <!-- 趋势图 -->
    <div v-if="selectedProduct" class="chart-area">
      <div class="chart-header">
        <span class="chart-title">{{ selectedProduct }} 估值趋势</span>
        <el-button type="text" size="small" @click="selectedProduct = null">收起</el-button>
      </div>
      <div ref="trendChart" style="height: 220px;"></div>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && history.length === 0" class="empty-state">
      <i class="el-icon-document empty-icon"></i>
      <div class="empty-title">暂无估值历史</div>
      <div class="empty-hint">在估值工作台运行估值后，结果将出现在此处</div>
    </div>
  </div>
</template>

<script>
import { getValuationHistory, getValuationTrend } from '@/api/optionPricing';
import * as echarts from 'echarts';

const TYPE_MAP = {
  fixed: '固定收益', binary: '二元结构', spread: '价差结构',
  sharkfin: '鲨鱼鳍', snowball: '雪球', phoenix: '凤凰', double_barrier: '双鲨',
  asian: '亚式期权', rainbow: '彩虹期权', range_accrual: '区间累积',
  callable_fixed: '可赎回固收', digital_range: '数字区间',
};
const METHOD_MAP = {
  analytic: '解析解', monte_carlo: '蒙特卡洛', fixed_income: '固收折现',
  discount: '折现', binary_analytic: '二元解析', spread_analytic: '价差解析',
  sharkfin_analytic: '鲨鱼鳍解析', snowball_mc: '雪球MC', phoenix_mc: '凤凰MC',
  double_barrier_mc: '双鲨MC', asian_arithmetic_mc: '亚式算术MC',
  asian_geometric_analytic: '亚式几何', range_accrual_mc: '区间累积MC',
  callable_fixed_binomial: '可赎回二叉树', digital_range_analytic: '数字区间解析',
};

export default {
  name: 'ValuationHistory',
  data() {
    return {
      loading: false,
      dateRange: null,
      history: [],
      selectedProduct: null,
      chart: null,
      // 用于计算变动%: product_id -> [{date, price}]
      priceByProduct: {},
    };
  },
  created() {
    this.loadHistory();
  },
  beforeDestroy() {
    if (this.chart) { this.chart.dispose(); this.chart = null; }
  },
  methods: {
    async loadHistory() {
      this.loading = true;
      try {
        const params = {
          start_date: this.dateRange ? this.dateRange[0] : undefined,
          end_date: this.dateRange ? this.dateRange[1] : undefined,
          limit: 500,
        };
        const res = await getValuationHistory(params);
        const raw = (res.data && res.data.data) || res.data || [];
        // 按产品分组计算变动%
        this.priceByProduct = {};
        raw.forEach(r => {
          if (!this.priceByProduct[r.product_id]) {
            this.priceByProduct[r.product_id] = [];
          }
          this.priceByProduct[r.product_id].push({ date: r.date, price: r.price_total, principal: r.principal });
        });
        // 按日期正序排列每个产品的历史
        Object.keys(this.priceByProduct).forEach(pid => {
          this.priceByProduct[pid].sort((a, b) => a.date.localeCompare(b.date));
        });
        // 计算变动%
        this.history = raw.map(r => {
          const series = this.priceByProduct[r.product_id] || [];
          const idx = series.findIndex(s => s.date === r.date);
          let pctChange = null;
          if (idx > 0) {
            const prev = series[idx - 1];
            if (prev.price > 0) {
              pctChange = ((r.price_total - prev.price) / prev.price) * 100;
            }
          }
          return { ...r, _pctChange: pctChange };
        });
        // 按日期倒序
        this.history.sort((a, b) => b.date.localeCompare(a.date));
      } catch (e) {
        this.$message.error('加载估值历史失败');
      } finally {
        this.loading = false;
      }
    },
    async handleRowClick({ row }) {
      if (!row) return;
      const pid = row.product_id;
      if (this.selectedProduct === pid) {
        this.selectedProduct = null;
        return;
      }
      this.selectedProduct = pid;
      await this.loadTrend(pid);
    },
    async loadTrend(productId) {
      try {
        const res = await getValuationTrend(productId);
        const trend = (res.data && res.data.data) || res.data || [];
        this.$nextTick(() => this.renderChart(trend));
      } catch (e) {
        // fallback: use local data
        const series = this.priceByProduct[productId] || [];
        this.$nextTick(() => this.renderChart(series.map(s => ({ date: s.date, price_total: s.price }))));
      }
    },
    renderChart(data) {
      if (!this.$refs.trendChart || !data.length) return;
      if (this.chart) this.chart.dispose();
      this.chart = echarts.init(this.$refs.trendChart);
      const dates = data.map(d => d.date);
      const prices = data.map(d => d.price_total != null ? d.price_total : d.price);
      this.chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 80, right: 30, top: 20, bottom: 40 },
        xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30, fontSize: 11 } },
        yAxis: { type: 'value', axisLabel: { formatter: v => (v / 10000).toFixed(0) + '万' } },
        series: [{
          type: 'line', data: prices, smooth: true,
          areaStyle: { opacity: 0.1 },
          lineStyle: { width: 2, color: '#409eff' },
          itemStyle: { color: '#409eff' },
        }]
      });
    },
    async handleExport() {
      try {
        const XLSX = await import('xlsx');
        const rows = this.history.map(h => ({
          '日期': h.date,
          '产品编号': h.product_id,
          '类型': TYPE_MAP[h.type] || h.type,
          '本金': h.principal,
          '估值': h.price_total,
          '变动%': h._pctChange != null ? h._pctChange.toFixed(2) + '%' : '',
          '方法': METHOD_MAP[h.method] || h.method,
        }));
        const ws = XLSX.utils.json_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, '估值历史');
        XLSX.writeFile(wb, `valuation_history_${this.dateRange ? this.dateRange[0] : 'all'}.xlsx`);
        this.$message.success('导出成功');
      } catch (e) {
        this.$message.error('导出失败');
      }
    },
    rowClassName({ row }) {
      return this.selectedProduct === row.product_id ? 'row-selected' : '';
    },
    typeLabel(t) { return TYPE_MAP[t] || t; },
    methodLabel(m) { return METHOD_MAP[m] || m || '-'; },
    formatNum(n) { return n != null ? n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'; },
  }
};
</script>

<style scoped>
.history-page { padding: 0; }
.page-header { margin-bottom: 16px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; color: #303133; }
.page-desc { margin: 4px 0 0; color: #909399; font-size: 13px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.toolbar-left { display: flex; align-items: center; }
.toolbar-right { display: flex; gap: 8px; }
.table-area { background: #fff; border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; }
.chart-area {
  margin-top: 16px; background: #fff; border: 1px solid #ebeef5;
  border-radius: 4px; padding: 16px;
}
.chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.chart-title { font-size: 14px; font-weight: 600; color: #303133; }
.empty-state {
  display: flex; flex-direction: column; align-items: center;
  padding: 60px 0; color: #909399;
}
.empty-icon { font-size: 48px; color: #dcdfe6; margin-bottom: 12px; }
.empty-title { font-size: 15px; color: #606266; margin-bottom: 4px; }
.empty-hint { font-size: 13px; }
.val-positive { color: #67c23a; font-weight: 500; }
.val-negative { color: #f56c6c; font-weight: 500; }
</style>

<style>
.row-selected { background-color: #ecf5ff !important; }
</style>
