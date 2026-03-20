<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">组合详情</h2>
      <div>
        <el-button @click="$router.back()">返回</el-button>
        <el-button type="primary" icon="el-icon-refresh" @click="loadData">刷新</el-button>
        <el-button type="warning" icon="el-icon-edit" @click="handleRebalance">调仓操作</el-button>
      </div>
    </div>

    <div :class="{'page-content': !isDialog}" v-loading="loading">
      <el-row :gutter="20">
        <el-col :span="16">
          <!-- 基本信息 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>基本信息</span>
            </div>

            <el-descriptions :column="2" border>
              <el-descriptions-item label="组合名称">{{ portfolio.name }}</el-descriptions-item>
              <el-descriptions-item label="组合类型">
                <el-tag :type="portfolio.portfolio_type === '模型驱动' ? 'success' : 'primary'" size="small">
                  {{ portfolio.portfolio_type }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="初始资金">
                ¥{{ formatNumber(portfolio.initial_capital) }}
              </el-descriptions-item>
              <el-descriptions-item label="当前资金">
                ¥{{ formatNumber(portfolio.current_capital) }}
              </el-descriptions-item>
              <el-descriptions-item label="建仓日期">
                {{ formatDate(portfolio.inception_date) }}
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">
                {{ formatDate(portfolio.created_at) }}
              </el-descriptions-item>
              <el-descriptions-item label="创建人" v-if="portfolio.created_by">
                {{ portfolio.created_by }}
              </el-descriptions-item>
              <el-descriptions-item label="关联模型" v-if="portfolio.model_id">
                <el-link type="primary" @click="viewModel(portfolio.model_id)">
                  查看策略模型
                </el-link>
              </el-descriptions-item>
              <el-descriptions-item label="组合描述" :span="2">
                {{ portfolio.description || '暂无描述' }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <!-- 当前持仓 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>当前持仓</span>
              <span style="color: #909399; font-size: 13px; font-weight: normal;">
                更新时间: {{ formatDate(portfolio.updated_at) }}
              </span>
            </div>

            <el-table :data="portfolio.positions" border>
              <el-table-column prop="asset_code" label="资产代码" width="120"></el-table-column>
              <el-table-column prop="asset_name" label="资产名称" width="150"></el-table-column>
              <el-table-column prop="shares" label="持仓数量" align="right" width="120">
                <template slot-scope="scope">
                  {{ scope.row.shares ? scope.row.shares.toFixed(2) : '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="weight" label="权重" align="right" width="100">
                <template slot-scope="scope">
                  {{ scope.row.weight ? (scope.row.weight * 100).toFixed(2) + '%' : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template slot-scope="scope">
                  <el-button type="text" size="small" @click="viewAssetDetail(scope.row.asset_code)">
                    查看资产
                  </el-button>
                </template>
              </el-table-column>
            </el-table>

            <el-empty v-if="!portfolio.positions || portfolio.positions.length === 0" 
              description="暂无持仓数据">
            </el-empty>
          </el-card>

          <!-- 业绩曲线 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>业绩曲线</span>
              <el-radio-group v-model="chartType" size="small" @change="renderCharts">
                <el-radio-button label="unit_value">单位净值</el-radio-button>
                <el-radio-button label="cumulative_return">累计收益率</el-radio-button>
              </el-radio-group>
            </div>

            <div v-if="analysis && analysis.equity_curve">
              <div ref="performanceChart" style="width: 100%; height: 450px;"></div>
            </div>

            <el-empty v-else description="暂无业绩数据" :image-size="100"></el-empty>
          </el-card>

          <!-- 调仓记录 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>最近调仓记录</span>
              <el-button type="text" size="small" @click="viewAllHistory">查看全部</el-button>
            </div>

            <el-timeline v-if="rebalanceRecords.length > 0">
              <el-timeline-item
                v-for="record in rebalanceRecords.slice(0, 5)"
                :key="record.id"
                :timestamp="formatDate(record.rebalance_date)"
                placement="top"
              >
                <el-card shadow="hover" class="timeline-card">
                  <div>
                    <el-tag :type="getActionType(record.action)" size="small">
                      {{ record.action }}
                    </el-tag>
                    <span style="margin-left: 10px; color: #606266;">
                      {{ record.reason || '无说明' }}
                    </span>
                  </div>
                </el-card>
              </el-timeline-item>
            </el-timeline>

            <el-empty v-else description="暂无调仓记录"></el-empty>
          </el-card>
        </el-col>

        <el-col :span="8">
          <!-- 业绩概览 -->
          <el-card shadow="never" class="info-card">
            <div slot="header">业绩概览</div>

            <div v-if="analysis" class="metrics-container">
              <div class="metric-item">
                <div class="metric-label">当前市值</div>
                <div class="metric-value">
                  ¥{{ formatNumber(analysis.current_value) }}
                </div>
              </div>

              <div class="metric-item">
                <div class="metric-label">累计收益率</div>
                <div class="metric-value" :style="{ color: getReturnColor(analysis.total_return) }">
                  {{ formatPercent(analysis.total_return) }}
                </div>
              </div>

              <div class="metric-item">
                <div class="metric-label">年化收益率</div>
                <div class="metric-value" :style="{ color: getReturnColor(analysis.annual_return) }">
                  {{ formatPercent(analysis.annual_return) }}
                </div>
              </div>

              <div class="metric-item">
                <div class="metric-label">年化波动率</div>
                <div class="metric-value">
                  {{ formatPercent(analysis.annual_volatility) }}
                </div>
              </div>

              <div class="metric-item">
                <div class="metric-label">夏普比率</div>
                <div class="metric-value">
                  {{ analysis.sharpe_ratio ? analysis.sharpe_ratio.toFixed(3) : '-' }}
                </div>
              </div>

              <div class="metric-item">
                <div class="metric-label">最大回撤</div>
                <div class="metric-value" style="color: #f56c6c;">
                  {{ formatPercent(analysis.max_drawdown) }}
                </div>
              </div>

              <el-button type="primary" size="small" style="width: 100%; margin-top: 15px;" 
                @click="viewFullPerformance">
                查看完整业绩分析
              </el-button>
            </div>

            <el-empty v-else description="暂无业绩数据" :image-size="80"></el-empty>
          </el-card>

          <!-- 快捷操作 -->
          <el-card shadow="never" class="info-card">
            <div slot="header">快捷操作</div>

            <div class="action-buttons">
              <el-button type="primary" icon="el-icon-edit" size="small" @click="handleRebalance" plain>
                调仓操作
              </el-button>
              <el-button type="success" icon="el-icon-data-line" size="small" @click="viewFullPerformance" plain>
                业绩分析
              </el-button>
              <el-button type="warning" icon="el-icon-s-data" size="small" @click="viewBenchmark" plain>
                基准对比
              </el-button>
              <el-button type="info" icon="el-icon-tickets" size="small" @click="viewAllHistory" plain>
                调仓历史
              </el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 弹窗部分 -->
    <el-dialog title="再平衡设置" :visible.sync="rebalanceVisible" width="1000px" append-to-body>
      <rebalance v-if="rebalanceVisible" is-dialog :id="portfolioId" @close="rebalanceVisible = false" @success="loadData" />
    </el-dialog>

    <el-dialog title="调仓历史" :visible.sync="historyVisible" width="1000px" append-to-body>
      <trade-history v-if="historyVisible" is-dialog :id="portfolioId" />
    </el-dialog>

    <el-dialog title="业绩分析" :visible.sync="performanceVisible" width="1200px" append-to-body>
      <performance v-if="performanceVisible" is-dialog :id="portfolioId" />
    </el-dialog>

    <el-dialog title="基准对比" :visible.sync="benchmarkVisible" width="1000px" append-to-body>
      <benchmark v-if="benchmarkVisible" is-dialog :id="portfolioId" />
    </el-dialog>

    <el-dialog :title="`资产行情 - ${currentAssetCode}`" :visible.sync="assetQuoteVisible" width="1200px" append-to-body top="5vh">
      <asset-quote v-if="assetQuoteVisible" is-dialog :asset-code="currentAssetCode" />
    </el-dialog>
    
    <el-dialog title="策略详情" :visible.sync="modelDetailVisible" width="1200px" append-to-body>
      <strategy-model-detail v-if="modelDetailVisible" is-dialog :id="currentModelId" />
    </el-dialog>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import * as echarts from 'echarts';
import * as portfolioApi from '@/api/portfolio';

export default {
  name: 'PortfolioDetail',
  components: {
    Rebalance: () => import('./Rebalance.vue'),
    TradeHistory: () => import('./TradeHistory.vue'),
    Performance: () => import('./Performance.vue'),
    Benchmark: () => import('./Benchmark.vue'),
    AssetQuote: () => import('../asset/AssetQuote.vue'),
    StrategyModelDetail: () => import('../strategy/StrategyModelDetail.vue')
  },
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    id: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      portfolioId: null,
      portfolio: {
        name: '',
        portfolio_type: '',
        description: '',
        model_id: null,
        initial_capital: 0,
        current_capital: 0,
        inception_date: null,
        created_by: '',
        created_at: null,
        updated_at: null,
        positions: []
      },
      rebalanceRecords: [],
      analysis: null,
      loading: false,
      chartType: 'unit_value', // unit_value 或 cumulative_return
      performanceChart: null,
      rebalanceVisible: false,
      historyVisible: false,
      performanceVisible: false,
      benchmarkVisible: false,
      assetQuoteVisible: false,
      modelDetailVisible: false,
      currentModelId: '',
      currentAssetCode: ''
    };
  },
  created() {
    this.portfolioId = this.isDialog ? this.id : this.$route.params.id;
    this.loadData();
  },
  watch: {
    id(newVal) {
      if (this.isDialog && newVal) {
        this.portfolioId = newVal;
        this.loadData();
      }
    }
  },
  mounted() {
    this.initChart();
  },
  beforeDestroy() {
    if (this.performanceChart) {
      this.performanceChart.dispose();
    }
  },
  methods: {
    async loadData() {
      this.loading = true;
      try {
        // 加载组合基本信息
        const portfolioRes = await portfolioApi.getPortfolio(this.portfolioId);
        this.portfolio = portfolioRes.data || {};

        // 加载调仓记录
        const recordsRes = await portfolioApi.getRebalanceRecords(this.portfolioId);
        this.rebalanceRecords = recordsRes.data || [];

        // 加载业绩分析数据
        try {
          const analysisRes = await portfolioApi.getPortfolioAnalysis(this.portfolioId);
          this.analysis = analysisRes.data || null;
          
          // 渲染图表
          this.$nextTick(() => {
            this.renderCharts();
          });
        } catch (error) {
          console.warn('业绩数据加载失败:', error);
          this.analysis = null;
        }
      } catch (error) {
        this.$message.error('加载数据失败：' + (error.response?.data?.message || error.message));
      } finally {
        this.loading = false;
      }
    },
    handleRebalance() {
      this.rebalanceVisible = true;
    },
    viewAllHistory() {
      this.historyVisible = true;
    },
    viewFullPerformance() {
      this.performanceVisible = true;
    },
    viewBenchmark() {
      this.benchmarkVisible = true;
    },
    viewModel(modelId) {
      this.currentModelId = modelId;
      this.modelDetailVisible = true;
    },
    viewAssetDetail(assetCode) {
      this.currentAssetCode = assetCode;
      this.assetQuoteVisible = true;
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
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-';
    },
    getReturnColor(value) {
      if (value > 0) return '#67c23a';
      if (value < 0) return '#f56c6c';
      return '#909399';
    },
    getActionType(action) {
      const map = {
        '买入': 'success',
        '卖出': 'danger',
        '调整': 'warning'
      };
      return map[action] || 'info';
    },
    initChart() {
      if (this.$refs.performanceChart) {
        this.performanceChart = echarts.init(this.$refs.performanceChart);
      }
    },
    renderCharts() {
      if (!this.analysis || !this.analysis.equity_curve || !this.analysis.equity_curve.length) {
        return;
      }

      // 初始化或获取图表实例
      if (!this.performanceChart && this.$refs.performanceChart) {
        this.performanceChart = echarts.init(this.$refs.performanceChart);
      }

      if (!this.performanceChart) {
        return;
      }

      const equityCurve = this.analysis.equity_curve;
      const dates = equityCurve.map(item => item.date);
      
      let title = '';
      let yAxisLabel = '';
      let seriesData = [];
      let tooltipFormatter = null;

      if (this.chartType === 'unit_value') {
        // 单位净值曲线
        title = '单位净值走势';
        yAxisLabel = '净值';
        seriesData = equityCurve.map(item => item.unit_value || 1);
        tooltipFormatter = function(params) {
          const date = params[0].axisValue;
          const value = params[0].data;
          return `${date}<br/>单位净值: ${value.toFixed(4)}`;
        };
      } else {
        // 累计收益率曲线
        title = '累计收益率走势';
        yAxisLabel = '收益率';
        seriesData = equityCurve.map(item => (item.cumulative_return || 0) * 100);
        tooltipFormatter = function(params) {
          const date = params[0].axisValue;
          const value = params[0].data;
          const color = value >= 0 ? '#67c23a' : '#f56c6c';
          return `${date}<br/>累计收益率: <span style="color: ${color}">${value.toFixed(2)}%</span>`;
        };
      }

      const option = {
        title: {
          text: title,
          left: 'center',
          textStyle: {
            fontSize: 16,
            fontWeight: 'normal'
          }
        },
        tooltip: {
          trigger: 'axis',
          formatter: tooltipFormatter
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
          boundaryGap: false,
          axisLabel: {
            formatter: function(value) {
              return dayjs(value).format('MM-DD');
            }
          }
        },
        yAxis: {
          type: 'value',
          name: yAxisLabel,
          axisLabel: {
            formatter: this.chartType === 'unit_value' 
              ? '{value}'
              : '{value}%'
          }
        },
        series: [
          {
            name: yAxisLabel,
            type: 'line',
            data: seriesData,
            smooth: true,
            symbol: 'none',
            lineStyle: {
              width: 2,
              color: this.chartType === 'unit_value' ? '#409EFF' : '#67c23a'
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: this.chartType === 'unit_value' 
                  ? [
                      { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
                      { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
                    ]
                  : [
                      { offset: 0, color: 'rgba(103, 194, 58, 0.3)' },
                      { offset: 1, color: 'rgba(103, 194, 58, 0.05)' }
                    ]
              }
            },
            markLine: this.chartType === 'cumulative_return' ? {
              silent: true,
              symbol: 'none',
              data: [
                {
                  yAxis: 0,
                  lineStyle: {
                    color: '#909399',
                    type: 'dashed'
                  },
                  label: {
                    show: false
                  }
                }
              ]
            } : undefined
          }
        ]
      };

      this.performanceChart.setOption(option, true);
    }
  }
};
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.info-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

.timeline-card {
  margin-bottom: 10px;
}

.metrics-container {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.metric-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 4px;
}

.metric-label {
  font-size: 14px;
  color: #606266;
}

.metric-value {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.action-buttons {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.action-buttons .el-button {
  width: 100%;
}
</style>
