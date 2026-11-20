<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">业绩分析</h2>
      <el-button @click="$router.back()">返回</el-button>
    </div>
    <div :class="{'page-content': !isDialog}" v-loading="loading">
      <template v-if="analysis">
        <!-- 核心指标卡片 -->
        <el-card shadow="never" class="info-card">
          <div slot="header" class="card-header">
            <span>核心指标</span>
          </div>
          <el-row :gutter="16" class="metrics-row">
            <el-col :span="4">
              <div class="metric-card">
                <div class="metric-label">年化收益（260日）</div>
                <div class="metric-value" :style="{color: (analysis.annual_return||0) >= 0 ? '#f56c6c' : '#67c23a', fontSize: '16px'}">
                  {{ ((analysis.annual_return||0)*100).toFixed(2) }}%
                </div>
                <div class="metric-sub">365日：{{ ((analysis.annual_return_365||0)*100).toFixed(2) }}%</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="metric-card">
                <div class="metric-label">年化波动（260日）</div>
                <div class="metric-value" style="fontSize: 16px;">{{ ((analysis.annual_volatility||0)*100).toFixed(2) }}%</div>
                <div class="metric-sub">365日：{{ ((analysis.annual_volatility_365||0)*100).toFixed(2) }}%</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="metric-card">
                <div class="metric-label">夏普比率（260日）</div>
                <div class="metric-value" :style="{color: (analysis.sharpe_ratio||0) >= 1 ? '#f56c6c' : '#e6a23c', fontSize: '16px', fontWeight: 600}">
                  {{ (analysis.sharpe_ratio||0).toFixed(2) }}
                </div>
                <div class="metric-sub">365日：{{ (analysis.sharpe_ratio_365||0).toFixed(2) }}</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="metric-card">
                <div class="metric-label">最大回撤</div>
                <div class="metric-value" style="color: #f56c6c; fontSize: 16px;">{{ ((analysis.max_drawdown||0)*100).toFixed(2) }}%</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="metric-card">
                <div class="metric-label">卡玛比率（260日）</div>
                <div class="metric-value" style="fontSize: 16px;">{{ (analysis.calmar_ratio||0).toFixed(2) }}</div>
                <div class="metric-sub">365日：{{ (analysis.calmar_ratio_365||0).toFixed(2) }}</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="metric-card">
                <div class="metric-label">累计收益</div>
                <div class="metric-value" :style="{color: (analysis.total_return||0) >= 0 ? '#f56c6c' : '#67c23a', fontSize: '16px'}">
                  {{ ((analysis.total_return||0)*100).toFixed(2) }}%
                </div>
              </div>
            </el-col>
          </el-row>
        </el-card>

        <!-- 业绩曲线 -->
        <el-card shadow="never" class="info-card">
          <div slot="header" class="card-header">
            <span>业绩曲线</span>
            <el-radio-group v-model="chartType" size="small" @change="renderCharts">
              <el-radio-button label="unit_value">单位净值</el-radio-button>
              <el-radio-button label="cumulative_return">累计收益率</el-radio-button>
              <el-radio-button label="drawdown">回撤走势</el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="analysis.equity_curve || analysis.drawdown_series">
            <div ref="performanceChart" style="width: 100%; height: 450px;"></div>
          </div>
          <el-empty v-else description="暂无业绩数据" :image-size="100"></el-empty>
        </el-card>

        <!-- 子策略绩效对比（仅 PORTFOLIO_MODEL） -->
        <el-card v-if="portfolioDetails && portfolioDetails.sub_strategy_performance && portfolioDetails.sub_strategy_performance.length" shadow="never" class="info-card">
          <div slot="header" class="card-header">
            <span>子策略绩效对比</span>
          </div>
          <el-table :data="portfolioDetails.sub_strategy_performance" size="small" border>
            <el-table-column prop="name" label="子策略" width="120" />
            <el-table-column prop="weight" label="权重" width="80" align="right">
              <template slot-scope="{ row }">{{ (row.weight * 100).toFixed(0) }}%</template>
            </el-table-column>
            <el-table-column label="年化收益（260日）" width="130" align="right">
              <template slot-scope="{ row }">
                <span :style="{color: (row.annual_return||0) >= 0 ? '#f56c6c' : '#67c23a'}">{{ ((row.annual_return||0) * 100).toFixed(2) }}%</span>
              </template>
            </el-table-column>
            <el-table-column label="年化收益（365日）" width="130" align="right">
              <template slot-scope="{ row }">{{ ((row.annual_return_365||0) * 100).toFixed(2) }}%</template>
            </el-table-column>
            <el-table-column label="波动（260日）" width="115" align="right">
              <template slot-scope="{ row }">{{ ((row.annual_vol||0) * 100).toFixed(2) }}%</template>
            </el-table-column>
            <el-table-column label="波动（365日）" width="115" align="right">
              <template slot-scope="{ row }">{{ ((row.annual_vol_365||0) * 100).toFixed(2) }}%</template>
            </el-table-column>
            <el-table-column label="夏普（260日）" width="105" align="right">
              <template slot-scope="{ row }">{{ (row.sharpe||0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="夏普（365日）" width="105" align="right">
              <template slot-scope="{ row }">{{ (row.sharpe_365||0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="回撤" width="90" align="right">
              <template slot-scope="{ row }"><span style="color:#f56c6c">{{ ((row.max_drawdown||0) * 100).toFixed(2) }}%</span></template>
            </el-table-column>
            <el-table-column label="贡献占比" width="100" align="right">
              <template slot-scope="{ row }">{{ ((row.contribution_pct||0) * 100).toFixed(1) }}%</template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 分析与记录笔记 -->
        <el-card shadow="never" class="info-card">
          <div slot="header" class="card-header">
            <span>分析与记录笔记</span>
            <el-button type="primary" size="mini" @click="saveNote" :loading="savingNote">保存</el-button>
          </div>
          <el-input
            type="textarea"
            v-model="note"
            placeholder="记录您的分析、观察和决策依据..."
            :rows="8"
            maxlength="2000"
            show-word-limit
          ></el-input>
        </el-card>
      </template>

      <el-empty v-else-if="!loading" description="暂无业绩数据" :image-size="100"></el-empty>
    </div>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import * as portfolioApi from '@/api/portfolio';
import { createDateAxisLabelFormatter } from '@/utils/dateAxis';

export default {
  name: 'Performance',
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
      loading: false,
      analysis: null,
      portfolioDetails: null,
      chartType: 'unit_value',
      performanceChart: null,
      note: '',
      savingNote: false,
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
        // 加载分析数据
        const analysisRes = await portfolioApi.getPortfolioAnalysis(this.portfolioId);
        this.analysis = analysisRes.data || null;

        // 加载组合详情（含子策略绩效）
        const detailsRes = await portfolioApi.getPortfolioDetails(this.portfolioId);
        this.portfolioDetails = detailsRes.data || null;

        // 加载笔记
        if (this.portfolioDetails && this.portfolioDetails.note) {
          this.note = this.portfolioDetails.note;
        }

        // 渲染图表
        this.$nextTick(() => {
          this.renderCharts();
        });
      } catch (error) {
        console.warn('业绩数据加载失败:', error);
        this.analysis = null;
      } finally {
        this.loading = false;
      }
    },
    async saveNote() {
      this.savingNote = true;
      try {
        await portfolioApi.updatePortfolioNote(this.portfolioId, { note: this.note });
        this.$message.success('笔记已保存');
      } catch (e) {
        this.$message.error('保存失败：' + (e.response?.data?.detail || e.message || '未知错误'));
      } finally {
        this.savingNote = false;
      }
    },
    initChart() {
      if (this.$refs.performanceChart) {
        this.performanceChart = echarts.init(this.$refs.performanceChart);
      }
    },
    renderCharts() {
      // 初始化或获取图表实例
      if (!this.performanceChart && this.$refs.performanceChart) {
        this.performanceChart = echarts.init(this.$refs.performanceChart);
      }

      if (!this.performanceChart) {
        return;
      }

      let title = '';
      let yAxisLabel = '';
      let seriesData = [];
      let dates = [];
      let tooltipFormatter = null;
      let lineColor = '#409EFF';
      let areaColorStops = [
        { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
        { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
      ];
      let yAxisFormatter = '{value}';
      let markLineData = null;

      if (this.chartType === 'drawdown') {
        const drawdownSeries = this.analysis.drawdown_series || [];
        if (!drawdownSeries.length) return;
        title = '回撤走势';
        yAxisLabel = '回撤';
        dates = drawdownSeries.map(item => item.date);
        seriesData = drawdownSeries.map(item => (item.drawdown || 0) * 100);
        lineColor = '#f56c6c';
        areaColorStops = [
          { offset: 0, color: 'rgba(245, 108, 108, 0.3)' },
          { offset: 1, color: 'rgba(245, 108, 108, 0.05)' }
        ];
        yAxisFormatter = '{value}%';
        tooltipFormatter = function(params) {
          const date = params[0].axisValue;
          const value = params[0].data;
          return `${date}<br/>回撤: <span style="color: #f56c6c">${value.toFixed(2)}%</span>`;
        };
      } else {
        const equityCurve = this.analysis.equity_curve;
        if (!equityCurve || !equityCurve.length) return;
        dates = equityCurve.map(item => item.date);

        if (this.chartType === 'unit_value') {
          title = '单位净值走势';
          yAxisLabel = '净值';
          seriesData = equityCurve.map(item => item.unit_value || 1);
          lineColor = '#409EFF';
          areaColorStops = [
            { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
            { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
          ];
          yAxisFormatter = '{value}';
          tooltipFormatter = function(params) {
            const date = params[0].axisValue;
            const value = params[0].data;
            return `${date}<br/>单位净值: ${value.toFixed(4)}`;
          };
        } else {
          title = '累计收益率走势';
          yAxisLabel = '收益率';
          seriesData = equityCurve.map(item => (item.cumulative_return || 0) * 100);
          lineColor = '#67c23a';
          areaColorStops = [
            { offset: 0, color: 'rgba(103, 194, 58, 0.3)' },
            { offset: 1, color: 'rgba(103, 194, 58, 0.05)' }
          ];
          yAxisFormatter = '{value}%';
          markLineData = [{ yAxis: 0, lineStyle: { color: '#909399', type: 'dashed' }, label: { show: false } }];
          tooltipFormatter = function(params) {
            const date = params[0].axisValue;
            const value = params[0].data;
            const color = value >= 0 ? '#67c23a' : '#f56c6c';
            return `${date}<br/>累计收益率: <span style="color: ${color}">${value.toFixed(2)}%</span>`;
          };
        }
      }

      const option = {
        title: {
          text: title,
          left: 'center',
          textStyle: { fontSize: 16, fontWeight: 'normal' }
        },
        tooltip: { trigger: 'axis', formatter: tooltipFormatter },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLabel: {
            // 跨年显示 YYYY-MM，单年显示 MM-DD，便于定位年份
            formatter: createDateAxisLabelFormatter(dates)
          }
        },
        yAxis: {
          type: 'value',
          name: yAxisLabel,
          axisLabel: { formatter: yAxisFormatter }
        },
        series: [{
          name: yAxisLabel,
          type: 'line',
          data: seriesData,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 2, color: lineColor },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: areaColorStops
            }
          },
          markLine: markLineData ? { silent: true, symbol: 'none', data: markLineData } : undefined
        }]
      };

      this.performanceChart.setOption(option, true);
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #303133;
  margin: 0;
}
.page-content {
  padding: 20px;
  background: #fff;
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
.metrics-row {
  margin-top: 10px;
}
.metric-card {
  text-align: center;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 4px;
}
.metric-label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 10px;
}
.metric-value {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}
.metric-sub {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}
</style>
