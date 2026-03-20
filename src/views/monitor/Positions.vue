<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">持仓明细</h2>
      <div>
        <el-button @click="$router.back()">返回</el-button>
        <el-button type="primary" icon="el-icon-refresh" @click="loadData" :loading="loading">刷新</el-button>
      </div>
    </div>

    <div class="page-content" v-loading="loading">
      <!-- 持仓汇总 -->
      <el-row :gutter="20" class="summary-row">
        <el-col :span="4">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">总资产(CNH)</div>
            <div class="summary-value">{{ formatCurrency(summary.totalValue) }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">总杠杆</div>
            <div class="summary-value">{{ formatNumber(summary.totalLeverage, 2) }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">持仓资产数</div>
            <div class="summary-value">{{ positions.length }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">最大持仓</div>
            <div class="summary-value">{{ formatPercent(summary.maxWeight) }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">最小持仓</div>
            <div class="summary-value">{{ formatPercent(summary.minWeight) }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">偏离资产数</div>
            <div class="summary-value" :style="{ color: summary.deviationCount > 0 ? '#E6A23C' : '#67C23A' }">
              {{ summary.deviationCount }}
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20" style="margin-top: 20px;">
        <!-- 持仓表格 -->
        <el-col :span="14">
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>持仓明细表</span>
              <span style="color: #909399; font-size: 13px; font-weight: normal;">
                更新时间: {{ updateTime }}
              </span>
            </div>
            <el-table
              :data="positions"
              border
              stripe
              style="width: 100%;"
              :row-class-name="getRowClassName"
            >
              <el-table-column prop="asset_name" label="资产名称" min-width="150">
                <template slot-scope="scope">
                  <span>{{ scope.row.asset_name || scope.row.asset_code }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="target_weight" label="目标权重(%)" width="110" align="right">
                <template slot-scope="scope">
                  {{ formatPercent(scope.row.target_weight) }}
                </template>
              </el-table-column>
              <el-table-column prop="actual_weight" label="实际权重(%)" width="110" align="right">
                <template slot-scope="scope">
                  {{ formatPercent(scope.row.actual_weight) }}
                </template>
              </el-table-column>
              <el-table-column prop="deviation" label="偏离度(%)" width="110" align="right">
                <template slot-scope="scope">
                  <span :style="{ color: getDeviationColor(scope.row.deviation) }">
                    {{ formatDeviation(scope.row.deviation) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="value_cnh" label="持仓(CNH)" width="130" align="right">
                <template slot-scope="scope">
                  {{ formatCurrency(scope.row.value_cnh) }}
                </template>
              </el-table-column>
              <el-table-column prop="value_local" label="本币持仓" width="130" align="right">
                <template slot-scope="scope">
                  {{ formatCurrency(scope.row.value_local) }}
                </template>
              </el-table-column>
              <el-table-column prop="daily_return" label="当日收益(%)" width="110" align="right">
                <template slot-scope="scope">
                  <span :style="{ color: getReturnColor(scope.row.daily_return) }">
                    {{ scope.row.daily_return !== null && scope.row.daily_return !== undefined 
                       ? (scope.row.daily_return * 100).toFixed(2) + '%' 
                       : '-' }}
                  </span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="positions.length === 0" description="暂无持仓数据"></el-empty>
          </el-card>
        </el-col>

        <!-- 图表区 -->
        <el-col :span="10">
          <!-- 权重分布饼图 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>权重分布</span>
            </div>
            <div ref="pieChart" style="width: 100%; height: 300px;"></div>
            <el-empty v-if="positions.length === 0" description="暂无数据"></el-empty>
          </el-card>

          <!-- 权重偏离度柱状图 -->
          <el-card shadow="never" class="info-card" style="margin-top: 20px;">
            <div slot="header" class="card-header">
              <span>权重偏离度</span>
              <el-tooltip content="超过±2%的偏离度用红色标注" placement="top">
                <i class="el-icon-question" style="color: #909399;"></i>
              </el-tooltip>
            </div>
            <div ref="deviationChart" style="width: 100%; height: 300px;"></div>
            <el-empty v-if="positions.length === 0" description="暂无数据"></el-empty>
          </el-card>
        </el-col>
      </el-row>

      <!-- 资产相关性分析 -->
      <el-row :gutter="20" style="margin-top: 20px;">
        <el-col :span="24">
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>底层资产分析</span>
              <el-tooltip content="展示资产间的相关性矩阵和波动率分析" placement="top">
                <i class="el-icon-info" style="color: #909399;"></i>
              </el-tooltip>
            </div>
            <el-row :gutter="20">
              <!-- 资产相关性热力图占位 -->
              <el-col :span="14">
                <div class="analysis-section">
                  <div class="section-title">资产相关性矩阵</div>
                  <el-empty description="资产相关性分析（待数据接口支持）">
                    <template slot="image">
                      <i class="el-icon-data-analysis" style="font-size: 60px; color: #c0c4cc;"></i>
                    </template>
                    <div class="empty-tips">
                      <p>相关性热力图将展示各资产间的收益率相关系数</p>
                      <p>颜色说明：深红（高正相关）→ 白（无相关）→ 深蓝（高负相关）</p>
                    </div>
                  </el-empty>
                </div>
              </el-col>
              <!-- 波动率分析占位 -->
              <el-col :span="10">
                <div class="analysis-section">
                  <div class="section-title">年化波动率</div>
                  <el-empty description="波动率分析（待数据接口支持）">
                    <template slot="image">
                      <i class="el-icon-s-data" style="font-size: 60px; color: #c0c4cc;"></i>
                    </template>
                    <div class="empty-tips">
                      <p>将展示各资产的年化波动率柱状图</p>
                      <p>超过阈值的高波动资产将用红色标注</p>
                    </div>
                  </el-empty>
                </div>
              </el-col>
            </el-row>
          </el-card>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import * as echarts from 'echarts';
import { mapState, mapActions } from 'vuex';

export default {
  name: 'MonitorPositions',
  data() {
    return {
      loading: false,
      pieChart: null,
      deviationChart: null,
      deviationThreshold: 0.02  // 2% 偏离阈值
    };
  },
  computed: {
    ...mapState('monitor', ['positions', 'monitorState']),
    updateTime() {
      return this.monitorState?.date 
        ? dayjs(this.monitorState.date).format('YYYY-MM-DD')
        : '-';
    },
    summary() {
      if (this.positions.length === 0) {
        return {
          totalValue: 0,
          totalLeverage: 0,
          maxWeight: 0,
          minWeight: 0,
          deviationCount: 0
        };
      }

      const totalValue = this.positions.reduce((sum, p) => sum + (p.value_cnh || 0), 0);
      const weights = this.positions.map(p => p.actual_weight || 0);
      const totalLeverage = weights.reduce((sum, w) => sum + Math.abs(w), 0);
      const maxWeight = Math.max(...weights);
      const minWeight = Math.min(...weights.filter(w => w > 0));
      const deviationCount = this.positions.filter(p => 
        Math.abs(p.deviation || 0) > this.deviationThreshold
      ).length;

      return {
        totalValue,
        totalLeverage,
        maxWeight,
        minWeight: minWeight === Infinity ? 0 : minWeight,
        deviationCount
      };
    }
  },
  mounted() {
    this.loadData();
    window.addEventListener('resize', this.handleResize);
  },
  beforeDestroy() {
    if (this.pieChart) {
      this.pieChart.dispose();
    }
    if (this.deviationChart) {
      this.deviationChart.dispose();
    }
    window.removeEventListener('resize', this.handleResize);
  },
  methods: {
    ...mapActions('monitor', ['fetchPositions', 'fetchMonitorState']),
    async loadData() {
      this.loading = true;
      try {
        await Promise.all([
          this.fetchPositions(),
          this.fetchMonitorState()
        ]);
        this.$nextTick(() => {
          this.initCharts();
          this.renderPieChart();
          this.renderDeviationChart();
        });
      } catch (error) {
        this.$message.error('加载数据失败：' + (error.response?.data?.message || error.message));
      } finally {
        this.loading = false;
      }
    },
    initCharts() {
      if (!this.pieChart && this.$refs.pieChart) {
        this.pieChart = echarts.init(this.$refs.pieChart);
      }
      if (!this.deviationChart && this.$refs.deviationChart) {
        this.deviationChart = echarts.init(this.$refs.deviationChart);
      }
    },
    renderPieChart() {
      if (!this.pieChart || this.positions.length === 0) {
        return;
      }

      const data = this.positions.map(p => ({
        name: p.asset_name || p.asset_code,
        value: Math.abs(p.actual_weight || 0)
      }));

      const option = {
        tooltip: {
          trigger: 'item',
          formatter: (params) => {
            return `${params.name}<br/>权重: ${(params.value * 100).toFixed(2)}%`;
          }
        },
        legend: {
          type: 'scroll',
          orient: 'vertical',
          right: 10,
          top: 20,
          bottom: 20,
          formatter: (name) => {
            if (name.length > 8) {
              return name.substring(0, 8) + '...';
            }
            return name;
          }
        },
        series: [{
          name: '权重分布',
          type: 'pie',
          radius: ['40%', '70%'],
          center: ['35%', '50%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 4,
            borderColor: '#fff',
            borderWidth: 2
          },
          label: {
            show: false
          },
          emphasis: {
            label: {
              show: true,
              fontSize: 14,
              fontWeight: 'bold',
              formatter: (params) => {
                return `${params.name}\n${(params.value * 100).toFixed(2)}%`;
              }
            }
          },
          labelLine: {
            show: false
          },
          data: data
        }]
      };

      this.pieChart.setOption(option, true);
    },
    renderDeviationChart() {
      if (!this.deviationChart || this.positions.length === 0) {
        return;
      }

      const sortedPositions = [...this.positions].sort((a, b) => 
        Math.abs(b.deviation || 0) - Math.abs(a.deviation || 0)
      );

      const names = sortedPositions.map(p => p.asset_name || p.asset_code);
      const deviations = sortedPositions.map(p => ((p.deviation || 0) * 100).toFixed(2));

      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'shadow'
          },
          formatter: (params) => {
            const data = params[0];
            const color = Math.abs(data.value) > 2 ? '#F56C6C' : '#409EFF';
            return `${data.name}<br/>偏离度: <span style="color:${color}">${data.value}%</span>`;
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
          data: names,
          axisLabel: {
            rotate: 45,
            interval: 0,
            formatter: (value) => {
              if (value.length > 6) {
                return value.substring(0, 6) + '...';
              }
              return value;
            }
          }
        },
        yAxis: {
          type: 'value',
          name: '偏离度(%)',
          axisLabel: {
            formatter: '{value}%'
          }
        },
        series: [{
          name: '偏离度',
          type: 'bar',
          data: deviations,
          itemStyle: {
            color: (params) => {
              return Math.abs(params.value) > 2 ? '#F56C6C' : '#409EFF';
            }
          },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [
              {
                yAxis: 2,
                lineStyle: { color: '#E6A23C', type: 'dashed' },
                label: { show: true, formatter: '阈值 2%' }
              },
              {
                yAxis: -2,
                lineStyle: { color: '#E6A23C', type: 'dashed' },
                label: { show: true, formatter: '阈值 -2%' }
              }
            ]
          }
        }]
      };

      this.deviationChart.setOption(option, true);
    },
    handleResize() {
      if (this.pieChart) {
        this.pieChart.resize();
      }
      if (this.deviationChart) {
        this.deviationChart.resize();
      }
    },
    getRowClassName({ row }) {
      if (Math.abs(row.deviation || 0) > this.deviationThreshold) {
        return 'deviation-warning-row';
      }
      return '';
    },
    formatNumber(num, decimals = 2) {
      if (num === null || num === undefined) return '-';
      return num.toFixed(decimals);
    },
    formatPercent(num) {
      if (num === null || num === undefined) return '-';
      return (num * 100).toFixed(2) + '%';
    },
    formatDeviation(num) {
      if (num === null || num === undefined) return '-';
      const value = (num * 100).toFixed(2);
      return (num >= 0 ? '+' : '') + value + '%';
    },
    formatCurrency(num) {
      if (num === null || num === undefined) return '-';
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num);
    },
    getReturnColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (value > 0) return '#F56C6C';
      if (value < 0) return '#67C23A';
      return '#909399';
    },
    getDeviationColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (Math.abs(value) > this.deviationThreshold) return '#F56C6C';
      return '#606266';
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
  margin: 0;
  font-size: 20px;
  font-weight: 500;
}

.page-content {
  min-height: 400px;
}

.summary-row {
  margin-bottom: 0;
}

.summary-card {
  text-align: center;
  padding: 15px 10px;
}

.summary-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.summary-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.info-card {
  margin-bottom: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

/* 偏离预警行高亮 */
::v-deep .deviation-warning-row {
  background-color: #fef0f0 !important;
}

::v-deep .deviation-warning-row:hover > td {
  background-color: #fde2e2 !important;
}

/* 资产分析区域样式 */
.analysis-section {
  min-height: 280px;
  padding: 10px;
}

.section-title {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 15px;
  padding-bottom: 10px;
  border-bottom: 1px solid #ebeef5;
}

.empty-tips {
  margin-top: 15px;
  text-align: center;
}

.empty-tips p {
  margin: 5px 0;
  font-size: 12px;
  color: #909399;
}
</style>
