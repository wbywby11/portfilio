<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">组合列表</h2>
      <el-button type="primary" icon="el-icon-plus" @click="handleCreate">
        创建组合
      </el-button>
    </div>

    <div class="page-content">
      <el-table :data="portfolioList" style="width: 100%" v-loading="loading">
        <el-table-column prop="name" label="组合名称" min-width="150" fixed="left"></el-table-column>
        <el-table-column prop="portfolio_type" label="组合类型" width="100">
          <template slot-scope="scope">
            <el-tag :type="scope.row.portfolio_type === '模型驱动' ? 'success' : 'info'" size="small">
              {{ scope.row.portfolio_type || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="current_capital" label="当前市值" width="130" align="right">
          <template slot-scope="scope">
            ¥{{ formatNumber(scope.row.current_capital) }}
          </template>
        </el-table-column>
        <el-table-column prop="latest_unit_value" label="最新净值" width="110" align="right">
          <template slot-scope="scope">
            {{ scope.row.latest_unit_value ? scope.row.latest_unit_value.toFixed(4) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="total_return" label="累计收益率" width="120" align="right">
          <template slot-scope="scope">
            <span :class="getReturnClass(scope.row.total_return)">
              {{ formatPercent(scope.row.total_return) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="annual_return" label="年化收益率" width="120" align="right">
          <template slot-scope="scope">
            <span :class="getReturnClass(scope.row.annual_return)">
              {{ formatPercent(scope.row.annual_return) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="max_drawdown" label="最大回撤" width="110" align="right">
          <template slot-scope="scope">
            <span style="color: #f56c6c;">
              {{ formatPercent(scope.row.max_drawdown) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="sharpe_ratio" label="夏普比率" width="110" align="right">
          <template slot-scope="scope">
            {{ scope.row.sharpe_ratio ? scope.row.sharpe_ratio.toFixed(3) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="inception_date" label="建仓日期" width="120">
          <template slot-scope="scope">
            {{ formatDateShort(scope.row.inception_date) }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template slot-scope="scope">
            {{ formatDate(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="small" @click="viewDetail(scope.row.id)">详情</el-button>
            <el-button type="text" size="small" @click="viewPerformance(scope.row.id)">业绩</el-button>
            <el-button type="text" size="small" @click="viewBenchmark(scope.row.id)">基准</el-button>
            <el-button type="text" size="small" @click="deletePortfolio(scope.row)" style="color: #f56c6c;">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="portfolioList.length === 0" description="暂无组合数据，点击上方按钮创建第一个组合"></el-empty>
    </div>

    <!-- 业绩详情对话框 -->
    <el-dialog
      title="业绩详情"
      :visible.sync="performanceDialogVisible"
      width="900px"
      :close-on-click-modal="false"
    >
      <div v-loading="performanceLoading">
        <el-descriptions :column="2" border v-if="currentPerformance">
          <el-descriptions-item label="组合名称" :span="2">
            {{ currentPerformance.portfolio_name }}
          </el-descriptions-item>
          <el-descriptions-item label="当前市值">
            ¥{{ formatNumber(currentPerformance.current_value) }}
          </el-descriptions-item>
          <el-descriptions-item label="初始资金">
            ¥{{ formatNumber(currentPerformance.initial_capital) }}
          </el-descriptions-item>
          <el-descriptions-item label="累计收益率">
            <span :class="getReturnClass(currentPerformance.total_return)">
              {{ formatPercent(currentPerformance.total_return) }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="年化收益率">
            <span :class="getReturnClass(currentPerformance.annual_return)">
              {{ formatPercent(currentPerformance.annual_return) }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="年化波动率">
            {{ formatPercent(currentPerformance.annual_volatility) }}
          </el-descriptions-item>
          <el-descriptions-item label="夏普比率">
            {{ currentPerformance.sharpe_ratio ? currentPerformance.sharpe_ratio.toFixed(3) : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="最大回撤">
            <span style="color: #f56c6c;">
              {{ formatPercent(currentPerformance.max_drawdown) }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="卡玛比率" v-if="currentPerformance.calmar_ratio">
            {{ currentPerformance.calmar_ratio.toFixed(3) }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- 权益曲线图表 -->
        <div v-if="currentPerformance && currentPerformance.equity_curve" style="margin-top: 20px;">
          <div ref="equityChart" style="width: 100%; height: 400px;"></div>
        </div>

        <el-empty v-if="!currentPerformance" description="暂无业绩数据"></el-empty>
      </div>
      <div slot="footer" class="dialog-footer">
        <el-button @click="performanceDialogVisible = false">关闭</el-button>
      </div>
    </el-dialog>

    <!-- 创建组合弹窗 -->
    <el-dialog title="创建组合" :visible.sync="portfolioCreateVisible" width="1000px" append-to-body>
      <portfolio-create v-if="portfolioCreateVisible" is-dialog @success="portfolioCreateVisible = false; fetchData()" @close="portfolioCreateVisible = false" />
    </el-dialog>

    <!-- 组合详情弹窗 -->
    <el-dialog title="组合详情" :visible.sync="portfolioDetailVisible" width="1200px" append-to-body top="5vh">
      <portfolio-detail v-if="portfolioDetailVisible" is-dialog :id="currentPortfolioId" />
    </el-dialog>

    <!-- 基准对比弹窗 -->
    <el-dialog title="基准对比" :visible.sync="benchmarkVisible" width="1000px" append-to-body>
      <benchmark v-if="benchmarkVisible" is-dialog :id="currentPortfolioId" />
    </el-dialog>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';
import * as echarts from 'echarts';
import * as portfolioApi from '@/api/portfolio';
import PortfolioCreate from './PortfolioCreate.vue';
import PortfolioDetail from './PortfolioDetail.vue';
import Benchmark from './Benchmark.vue';

export default {
  name: 'PortfolioList',
  components: {
    PortfolioCreate,
    PortfolioDetail,
    Benchmark
  },
  data() {
    return {
      loading: false,
      performanceDialogVisible: false,
      performanceLoading: false,
      currentPerformance: null,
      equityChart: null,
      portfolioCreateVisible: false,
      portfolioDetailVisible: false,
      benchmarkVisible: false,
      currentPortfolioId: ''
    };
  },
  computed: {
    ...mapState('portfolio', ['portfolioList'])
  },
  created() {
    this.fetchData();
  },
  methods: {
    async fetchData() {
      this.loading = true;
      try {
        await this.$store.dispatch('portfolio/fetchPortfolioList');
      } finally {
        this.loading = false;
      }
    },
    formatNumber(num) {
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num || 0);
    },
    formatPercent(num) {
      return ((num || 0) * 100).toFixed(2) + '%';
    },
    formatDate(date) {
      return dayjs(date).format('YYYY-MM-DD HH:mm:ss');
    },
    formatDateShort(date) {
      return dayjs(date).format('YYYY-MM-DD');
    },
    getReturnClass(ret) {
      if (ret > 0) return 'number-positive';
      if (ret < 0) return 'number-negative';
      return 'number-neutral';
    },
    getStatusType(status) {
      const map = { active: 'success', paused: 'warning', archived: 'info' };
      return map[status] || 'info';
    },
    getStatusLabel(status) {
      const map = { active: '运行中', paused: '已暂停', archived: '已归档' };
      return map[status] || status;
    },
    handleCreate() {
      this.portfolioCreateVisible = true;
    },
    viewDetail(id) {
      this.currentPortfolioId = id;
      this.portfolioDetailVisible = true;
    },
    async viewPerformance(id) {
      this.performanceDialogVisible = true;
      this.performanceLoading = true;
      this.currentPerformance = null;
      
      try {
        const res = await portfolioApi.getPortfolioAnalysis(id);
        this.currentPerformance = res.data;
        
        // 渲染图表
        this.$nextTick(() => {
          this.renderEquityChart();
        });
      } catch (error) {
        this.$message.error('获取业绩数据失败：' + (error.response?.data?.message || error.message));
      } finally {
        this.performanceLoading = false;
      }
    },
    viewBenchmark(id) {
      this.currentPortfolioId = id;
      this.benchmarkVisible = true;
    },
    deletePortfolio(row) {
      this.$confirm(`确定要删除组合 "${row.name}" 吗？`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('portfolio/deletePortfolio', row.id);
          this.$message.success('删除成功');
          this.fetchData();
        } catch (error) {
          this.$message.error('删除失败：' + (error.response?.data?.message || error.message));
        }
      }).catch(() => {});
    },
    renderEquityChart() {
      if (!this.currentPerformance || !this.currentPerformance.equity_curve) {
        return;
      }

      // 初始化或获取图表实例
      if (!this.equityChart && this.$refs.equityChart) {
        this.equityChart = echarts.init(this.$refs.equityChart);
      }

      if (!this.equityChart) {
        return;
      }

      const equityCurve = this.currentPerformance.equity_curve;
      const dates = equityCurve.map(item => item.date);
      const values = equityCurve.map(item => item.value);

      const option = {
        title: {
          text: '权益曲线',
          left: 'center'
        },
        tooltip: {
          trigger: 'axis',
          formatter: function(params) {
            const date = params[0].axisValue;
            const value = params[0].data;
            return `${date}<br/>权益: ¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
          }
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          data: dates,
          boundaryGap: false
        },
        yAxis: {
          type: 'value',
          axisLabel: {
            formatter: function(value) {
              return '¥' + (value / 10000).toFixed(0) + '万';
            }
          }
        },
        series: [
          {
            name: '权益',
            type: 'line',
            data: values,
            smooth: true,
            lineStyle: {
              width: 2,
              color: '#409EFF'
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
                  { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
                ]
              }
            }
          }
        ]
      };

      this.equityChart.setOption(option);
    }
  },
  beforeDestroy() {
    if (this.equityChart) {
      this.equityChart.dispose();
    }
  }
};
</script>

<style scoped>
.number-positive {
  color: #67c23a;
}

.number-negative {
  color: #f56c6c;
}

.number-neutral {
  color: #909399;
}
</style>
