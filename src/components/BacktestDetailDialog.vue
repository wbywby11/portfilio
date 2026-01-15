<template>
  <el-dialog
    :title="`回测详情 - ${formatDateShort(record.start_date)} 至 ${formatDateShort(record.end_date)}`"
    :visible.sync="visible"
    width="1200px"
    :close-on-click-modal="false"
    @close="handleClose"
    top="5vh"
  >
    <div v-loading="loading" class="backtest-detail">
      <!-- 回测基本信息 -->
      <el-card shadow="never" class="info-section">
        <div slot="header">回测信息</div>
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="回测区间">
            {{ formatDateShort(record.start_date) }} ~ {{ formatDateShort(record.end_date) }}
          </el-descriptions-item>
          <el-descriptions-item label="初始资金">
            ¥{{ record.initial_capital.toLocaleString() }}
          </el-descriptions-item>
          <el-descriptions-item label="回测时间">
            {{ formatDate(record.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="记录ID">
            {{ record.id.substring(0, 8) }}...
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 核心指标 -->
      <el-card shadow="never" class="info-section">
        <div slot="header">核心指标</div>
        <el-row :gutter="20">
          <el-col :span="4">
            <div class="metric-box">
              <div class="metric-label">总收益率</div>
              <div class="metric-value" :style="{ color: getReturnColor(record.result.total_return) }">
                {{ record.result.total_return != null ? (record.result.total_return * 100).toFixed(2) + '%' : '-' }}
              </div>
            </div>
          </el-col>
          <el-col :span="4">
            <div class="metric-box">
              <div class="metric-label">年化收益率</div>
              <div class="metric-value" :style="{ color: getReturnColor(record.result.annual_return) }">
                {{ record.result.annual_return != null ? (record.result.annual_return * 100).toFixed(2) + '%' : '-' }}
              </div>
            </div>
          </el-col>
          <el-col :span="4">
            <div class="metric-box">
              <div class="metric-label">年化波动率</div>
              <div class="metric-value">
                {{ record.result.annual_volatility != null ? (record.result.annual_volatility * 100).toFixed(2) + '%' : '-' }}
              </div>
            </div>
          </el-col>
          <el-col :span="4">
            <div class="metric-box">
              <div class="metric-label">夏普比率</div>
              <div class="metric-value" :style="{ color: record.result.sharpe_ratio > 1 ? '#67c23a' : '#909399' }">
                {{ record.result.sharpe_ratio != null ? record.result.sharpe_ratio.toFixed(3) : '-' }}
              </div>
            </div>
          </el-col>
          <el-col :span="4">
            <div class="metric-box">
              <div class="metric-label">最大回撤</div>
              <div class="metric-value" style="color: #f56c6c;">
                {{ record.result.max_drawdown != null ? (record.result.max_drawdown * 100).toFixed(2) + '%' : '-' }}
              </div>
            </div>
          </el-col>
          <el-col :span="4" v-if="record.result.calmar_ratio != null">
            <div class="metric-box">
              <div class="metric-label">卡玛比率</div>
              <div class="metric-value">
                {{ record.result.calmar_ratio.toFixed(3) }}
              </div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <!-- 权益曲线图表 -->
      <el-card shadow="never" class="info-section" v-if="record.result.equity_curve && record.result.equity_curve.length > 0">
        <div slot="header">
          <span>权益曲线</span>
          <el-radio-group v-model="chartType" size="small" style="float: right;">
            <el-radio-button label="total">总净值</el-radio-button>
            <el-radio-button label="unit">单位净值</el-radio-button>
            <el-radio-button label="both">双轴对比</el-radio-button>
          </el-radio-group>
        </div>
        <div ref="equityChart" style="width: 100%; height: 400px;"></div>
      </el-card>

      <!-- 持仓记录 -->
      <el-card shadow="never" class="info-section" v-if="record.result.positions && record.result.positions.length > 0">
        <div slot="header">
          <span>持仓记录</span>
          <span style="float: right; color: #909399; font-size: 13px;">
            共 {{ totalPositionRecords }} 条记录
          </span>
        </div>
        <el-table
          :data="paginatedPositions"
          border
          size="small"
          max-height="300"
        >
          <el-table-column prop="date" label="日期" width="120">
            <template slot-scope="scope">
              {{ formatDateShort(scope.row.date) }}
            </template>
          </el-table-column>
          <el-table-column prop="asset_code" label="资产代码" width="120"></el-table-column>
          <el-table-column prop="shares" label="持仓数量" width="120" align="right">
            <template slot-scope="scope">
              {{ scope.row.shares ? scope.row.shares.toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="weight" label="权重" width="100" align="right">
            <template slot-scope="scope">
              {{ scope.row.weight ? (scope.row.weight * 100).toFixed(2) + '%' : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="price" label="价格" width="100" align="right">
            <template slot-scope="scope">
              {{ scope.row.price ? scope.row.price.toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="market_value" label="市值" align="right">
            <template slot-scope="scope">
              {{ scope.row.market_value ? '¥' + scope.row.market_value.toLocaleString() : '-' }}
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          @current-change="handlePositionPageChange"
          :current-page="positionCurrentPage"
          :page-size="positionPageSize"
          layout="total, prev, pager, next"
          :total="totalPositionRecords"
          style="margin-top: 15px; text-align: right;"
        ></el-pagination>
      </el-card>

      <!-- 相关性矩阵 -->
      <el-card shadow="never" class="info-section" v-if="record.result.correlation_matrix && Object.keys(record.result.correlation_matrix).length > 0">
        <div slot="header">资产相关性矩阵</div>
        <el-table
          :data="correlationTableData"
          border
          size="small"
        >
          <el-table-column prop="asset" label="资产" width="120" fixed></el-table-column>
          <el-table-column
            v-for="asset in correlationAssets"
            :key="asset"
            :label="asset"
            width="100"
            align="center"
          >
            <template slot-scope="scope">
              <span :style="{ color: getCorrelationColor(scope.row[asset]) }">
                {{ scope.row[asset] ? scope.row[asset].toFixed(3) : '-' }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <div slot="footer">
      <el-button @click="handleClose">关闭</el-button>
      <el-button type="primary" @click="handleExport">导出报告</el-button>
    </div>
  </el-dialog>
</template>

<script>
import dayjs from 'dayjs';
import * as echarts from 'echarts';

export default {
  name: 'BacktestDetailDialog',
  props: {
    value: {
      type: Boolean,
      default: false
    },
    record: {
      type: Object,
      required: true,
      default: () => ({
        id: '',
        start_date: '',
        end_date: '',
        initial_capital: 0,
        result: {},
        created_at: ''
      })
    }
  },
  data() {
    return {
      visible: this.value,
      loading: false,
      equityChart: null,
      positionCurrentPage: 1,
      positionPageSize: 10,
      chartType: 'both' // total: 总净值, unit: 单位净值, both: 双轴对比
    };
  },
  computed: {
    paginatedPositions() {
      if (!this.record.result.positions) return [];
      
      // 将每个日期的持仓展开为单独的行
      let allPositions = [];
      this.record.result.positions.forEach(positionRecord => {
        const date = positionRecord.date;
        if (positionRecord.positions && Array.isArray(positionRecord.positions)) {
          positionRecord.positions.forEach(pos => {
            allPositions.push({
              date: date,
              asset_code: pos.asset_code,
              asset_name: pos.asset_name,
              weight: pos.weight,
              shares: pos.shares,
              price: pos.price,
              market_value: pos.market_value, // 使用 market_value 替代 value
              portfolio_value: positionRecord.portfolio_value
            });
          });
        }
      });
      
      const start = (this.positionCurrentPage - 1) * this.positionPageSize;
      const end = start + this.positionPageSize;
      return allPositions.slice(start, end);
    },
    correlationAssets() {
      if (!this.record.result.correlation_matrix) return [];
      return Object.keys(this.record.result.correlation_matrix);
    },
    correlationTableData() {
      if (!this.record.result.correlation_matrix) return [];
      const matrix = this.record.result.correlation_matrix;
      const assets = Object.keys(matrix);
      return assets.map(asset => {
        const row = { asset };
        assets.forEach(otherAsset => {
          row[otherAsset] = matrix[asset] && matrix[asset][otherAsset] !== undefined 
            ? matrix[asset][otherAsset] 
            : null;
        });
        return row;
      });
    },
    totalPositionRecords() {
      if (!this.record.result.positions) return 0;
      let count = 0;
      this.record.result.positions.forEach(positionRecord => {
        if (positionRecord.positions && Array.isArray(positionRecord.positions)) {
          count += positionRecord.positions.length;
        }
      });
      return count;
    }
  },
  watch: {
    value(val) {
      this.visible = val;
      if (val) {
        this.$nextTick(() => {
          this.initChart();
          this.renderEquityChart();
        });
      }
    },
    visible(val) {
      this.$emit('input', val);
    },
    chartType() {
      // 切换图表类型时重新渲染
      this.$nextTick(() => {
        this.renderEquityChart();
      });
    }
  },
  mounted() {
    if (this.visible) {
      this.initChart();
      this.renderEquityChart();
    }
  },
  beforeDestroy() {
    if (this.equityChart) {
      this.equityChart.dispose();
    }
  },
  methods: {
    initChart() {
      if (this.$refs.equityChart && !this.equityChart) {
        this.equityChart = echarts.init(this.$refs.equityChart);
      }
    },
    renderEquityChart() {
      if (!this.equityChart || !this.record.result.equity_curve) {
        return;
      }

      const equityCurve = this.record.result.equity_curve;
      const dates = equityCurve.map(item => item.date ? dayjs(item.date).format('YYYY-MM-DD') : '');
      const totalValues = equityCurve.map(item => item.value || 0);
      const unitValues = equityCurve.map(item => item.unit_value || 1);

      let option = {};

      if (this.chartType === 'both') {
        // 双轴对比模式
        option = {
          tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            formatter: (params) => {
              let result = params[0].name + '<br/>';
              params.forEach(param => {
                const unit = param.seriesName === '总净值' ? '￥' : '';
                result += `${param.marker}${param.seriesName}: ${unit}${param.value.toLocaleString()}<br/>`;
              });
              return result;
            }
          },
          legend: { data: ['总净值', '单位净值'] },
          grid: { left: '3%', right: '5%', bottom: '3%', containLabel: true },
          xAxis: { type: 'category', data: dates, boundaryGap: false },
          yAxis: [
            {
              type: 'value',
              name: '总净值（元）',
              position: 'left',
              axisLabel: { formatter: (value) => '￥' + (value / 1000).toFixed(0) + 'K' }
            },
            {
              type: 'value',
              name: '单位净值',
              position: 'right',
              axisLabel: { formatter: (value) => value.toFixed(4) }
            }
          ],
          series: [
            {
              name: '总净值',
              type: 'line',
              data: totalValues,
              smooth: true,
              symbol: 'none',
              yAxisIndex: 0,
              lineStyle: { width: 2, color: '#409EFF' },
              areaStyle: {
                color: {
                  type: 'linear',
                  x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: 'rgba(64, 158, 255, 0.25)' },
                    { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
                  ]
                }
              }
            },
            {
              name: '单位净值',
              type: 'line',
              data: unitValues,
              smooth: true,
              symbol: 'none',
              yAxisIndex: 1,
              lineStyle: { width: 2, color: '#67C23A' }
            }
          ]
        };
      } else if (this.chartType === 'total') {
        // 总净值模式
        option = {
          tooltip: {
            trigger: 'axis',
            formatter: (params) => `${params[0].name}<br/>总净值: ￥${params[0].value.toLocaleString()}`
          },
          grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
          xAxis: { type: 'category', data: dates, boundaryGap: false },
          yAxis: {
            type: 'value',
            name: '总净值（元）',
            axisLabel: { formatter: (value) => '￥' + (value / 1000).toFixed(0) + 'K' }
          },
          series: [
            {
              name: '总净值',
              type: 'line',
              data: totalValues,
              smooth: true,
              symbol: 'none',
              lineStyle: { width: 2, color: '#409EFF' },
              areaStyle: {
                color: {
                  type: 'linear',
                  x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: 'rgba(64, 158, 255, 0.25)' },
                    { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
                  ]
                }
              }
            }
          ]
        };
      } else {
        // 单位净值模式
        option = {
          tooltip: {
            trigger: 'axis',
            formatter: (params) => `${params[0].name}<br/>单位净值: ${params[0].value.toFixed(4)}`
          },
          grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
          xAxis: { type: 'category', data: dates, boundaryGap: false },
          yAxis: {
            type: 'value',
            name: '单位净值',
            axisLabel: { formatter: (value) => value.toFixed(4) }
          },
          series: [
            {
              name: '单位净值',
              type: 'line',
              data: unitValues,
              smooth: true,
              symbol: 'none',
              lineStyle: { width: 2, color: '#67C23A' },
              areaStyle: {
                color: {
                  type: 'linear',
                  x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: 'rgba(103, 194, 58, 0.25)' },
                    { offset: 1, color: 'rgba(103, 194, 58, 0.05)' }
                  ]
                }
              }
            }
          ]
        };
      }

      this.equityChart.setOption(option, true);
    },
    handlePositionPageChange(page) {
      this.positionCurrentPage = page;
    },
    getReturnColor(value) {
      if (value == null || value === undefined) return '#909399';
      return value >= 0 ? '#67c23a' : '#f56c6c';
    },
    getCorrelationColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (value > 0.7) return '#f56c6c';
      if (value > 0.3) return '#e6a23c';
      if (value > -0.3) return '#909399';
      if (value > -0.7) return '#409eff';
      return '#67c23a';
    },
    handleExport() {
      this.$message.info('导出功能开发中');
    },
    handleClose() {
      this.visible = false;
      if (this.equityChart) {
        this.equityChart.dispose();
        this.equityChart = null;
      }
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-';
    },
    formatDateShort(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '-';
    }
  }
};
</script>

<style scoped>
.backtest-detail {
  max-height: 70vh;
  overflow-y: auto;
}

.info-section {
  margin-bottom: 20px;
}

.metric-box {
  text-align: center;
  padding: 15px;
  background: #f5f7fa;
  border-radius: 4px;
}

.metric-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.metric-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}
</style>
