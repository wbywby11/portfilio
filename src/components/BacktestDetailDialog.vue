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
          <span>净值与收益曲线</span>
          <el-radio-group v-model="chartType" size="small" style="float: right;">
            <el-radio-button label="return">累计收益率</el-radio-button>
            <el-radio-button label="unit">单位净值</el-radio-button>
            <el-radio-button label="both">双轴对比</el-radio-button>
          </el-radio-group>
        </div>
        <div ref="equityChart" style="width: 100%; height: 400px;"></div>
      </el-card>

      <!-- 权重变化图表 -->
      <el-card shadow="never" class="info-section" v-if="hasWeightChanges">
        <div slot="header">
          <span>权重变化轨迹</span>
          <el-radio-group v-model="weightChartType" size="small" style="float: right;">
            <el-radio-button label="stacked">堆叠面积图</el-radio-button>
            <el-radio-button label="line">折线图</el-radio-button>
          </el-radio-group>
        </div>
        <div ref="weightChart" style="width: 100%; height: 500px;"></div>
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
          <el-table-column prop="asset_code" label="资产代码" width="200">
            <template slot-scope="scope">
              {{ scope.row.asset_code }} - {{ scope.row.asset_name || (record.result.asset_names && record.result.asset_names[scope.row.asset_code]) || '未知资产' }}
            </template>
          </el-table-column>
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
          <el-table-column prop="market_value" label="市值" width="120" align="right">
            <template slot-scope="scope">
              {{ scope.row.market_value ? '¥' + scope.row.market_value.toLocaleString() : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="rebalance_reason" label="调整原因" min-width="150" show-overflow-tooltip>
            <template slot-scope="scope">
              {{ scope.row.rebalance_reason || '-' }}
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
      weightChart: null,
      positionCurrentPage: 1,
      positionPageSize: 10,
      chartType: 'both', // total: 总净值, unit: 单位净值, both: 双轴对比
      weightChartType: 'stacked' // stacked: 堆叠面积图, line: 折线图
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
              portfolio_value: positionRecord.portfolio_value,
              rebalance_reason: positionRecord.rebalance_reason
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
    },
    hasWeightChanges() {
      return (
        this.record.result.weight_changes &&
        this.record.result.weight_changes.length > 0
      );
    }
  },
  watch: {
    value(val) {
      this.visible = val;
      if (val) {
        this.$nextTick(() => {
          this.initChart();
          this.renderEquityChart();
          this.initWeightChart();
          this.renderWeightChart();
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
    },
    'record.result.weight_changes'() {
      // 当权重变化数据更新时重新渲染权重图表
      this.$nextTick(() => {
        this.initWeightChart();
        this.renderWeightChart();
      });
    },
    weightChartType() {
      // 当权重图表类型改变时重新渲染
      this.$nextTick(() => {
        this.renderWeightChart();
      });
    }
  },
  mounted() {
    if (this.visible) {
      this.initChart();
      this.renderEquityChart();
      this.$nextTick(() => {
        this.initWeightChart();
        this.renderWeightChart();
      });
    }
  },
  beforeDestroy() {
    if (this.equityChart) {
      this.equityChart.dispose();
      this.equityChart = null;
    }
    if (this.weightChart) {
      this.weightChart.dispose();
      this.weightChart = null;
    }
  },
  methods: {
    initChart() {
      if (this.$refs.equityChart && !this.equityChart) {
        this.equityChart = echarts.init(this.$refs.equityChart);
      }
    },
    initWeightChart() {
      if (this.$refs.weightChart && !this.weightChart) {
        this.weightChart = echarts.init(this.$refs.weightChart);
      }
    },
    renderEquityChart() {
      if (!this.equityChart || !this.record.result.equity_curve) {
        return;
      }
      
      const equityCurve = this.record.result.equity_curve;
      const returnCurve = this.record.result.return_curve || [];
      
      // 准备数据
      const dates = equityCurve.map(item => dayjs(item.date).format('MM-DD'));
      const unitValues = equityCurve.map(item => item.unit_value);
      
      // 累计收益率数据（从 return_curve 获取）
      let returnValues = [];
      if (returnCurve.length > 0) {
        // 如果后端返回了 return_curve，使用后端计算好的累计收益率
        returnValues = returnCurve.map(item => item.cumulative_return * 100); // 转为百分比
      } else {
        // 如果没有 return_curve，从 unit_value 计算
        const initialValue = unitValues[0] || 1;
        returnValues = unitValues.map(val => ((val - initialValue) / initialValue) * 100);
      }
      
      // 准备图表配置
      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: (params) => {
            const date = params[0].axisValue;
            let result = `${date}<br />`;
            params.forEach(param => {
              const value = param.value;
              if (value !== undefined && value !== null && !isNaN(value)) {
                // 根据系列名称决定格式
                if (param.seriesName.includes('收益率')) {
                  result += `${param.seriesName}: ${value.toFixed(2)}%<br />`;
                } else {
                  result += `${param.seriesName}: ${value.toFixed(4)}<br />`;
                }
              } else {
                result += `${param.seriesName}: -<br />`;
              }
            });
            return result;
          }
        },
        legend: {
          data: this.chartType === 'both' ? ['累计收益率', '单位净值'] : [this.chartType === 'return' ? '累计收益率' : '单位净值'],
          top: '10%'
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          top: '20%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: dates
        },
        yAxis: this.chartType === 'both'
          ? [
              {
                type: 'value',
                name: '收益率(%)',
                position: 'left',
                axisLabel: {
                  formatter: '{value}%'
                }
              },
              {
                type: 'value',
                name: '单位净值',
                position: 'right',
                scale: true
              }
            ]
          : {
              type: 'value',
              scale: true,
              axisLabel: {
                formatter: this.chartType === 'return' ? '{value}%' : '{value}'
              }
            },
        series: this.chartType === 'both' 
          ? [
              {
                name: '累计收益率',
                type: 'line',
                yAxisIndex: 0,
                data: returnValues,
                smooth: true,
                symbol: 'none',
                lineStyle: {
                  width: 2,
                  color: '#67c23a'
                },
                areaStyle: {
                  color: {
                    type: 'linear',
                    x: 0,
                    y: 0,
                    x2: 0,
                    y2: 1,
                    colorStops: [
                      { offset: 0, color: 'rgba(103, 194, 58, 0.3)' },
                      { offset: 1, color: 'rgba(103, 194, 58, 0.05)' }
                    ]
                  }
                }
              },
              {
                name: '单位净值',
                type: 'line',
                yAxisIndex: 1,
                data: unitValues,
                smooth: true,
                symbol: 'none',
                lineStyle: {
                  width: 2,
                  type: 'dashed',
                  color: '#409eff'
                }
              }
            ]
          : [
              {
                name: this.chartType === 'return' ? '累计收益率' : '单位净值',
                type: 'line',
                data: this.chartType === 'return' ? returnValues : unitValues,
                smooth: true,
                symbol: 'none',
                lineStyle: {
                  width: 2,
                  color: this.chartType === 'return' ? '#67c23a' : '#409eff'
                },
                areaStyle: this.chartType === 'return' ? {
                  color: {
                    type: 'linear',
                    x: 0,
                    y: 0,
                    x2: 0,
                    y2: 1,
                    colorStops: [
                      { offset: 0, color: 'rgba(103, 194, 58, 0.3)' },
                      { offset: 1, color: 'rgba(103, 194, 58, 0.05)' }
                    ]
                  }
                } : undefined
              }
            ]
      };
      
      this.equityChart.setOption(option, true);
    },
    renderWeightChart() {
      if (!this.weightChart || !this.record.result.weight_changes) {
        return;
      }
      
      const weightChanges = this.record.result.weight_changes;
      const assetNames = this.record.result.asset_names || {};
      
      // 提取所有唯一的资产代码
      const allAssets = new Set();
      weightChanges.forEach(change => {
        if (change.weights) {
          Object.keys(change.weights).forEach(asset => allAssets.add(asset));
        }
      });
      
      const assetList = Array.from(allAssets);
      
      // 为每个资产创建时间序列数据
      const seriesData = {};
      const assetDisplayNames = {}; // 存储资产显示名称
      
      assetList.forEach(asset => {
        // 生成显示名称：资产代码 - 资产名称
        const assetName = assetNames[asset] || '未知资产';
        assetDisplayNames[asset] = `${asset} - ${assetName}`;
        
        seriesData[asset] = weightChanges.map(change => {
          const date = change.date ? dayjs(change.date).format('YYYY-MM-DD') : '';
          const weight = change.weights && change.weights[asset] ? change.weights[asset] : 0;
          return [date, weight];
        });
      });
      
      // 准备图表配置
      let seriesConfig;
      if (this.weightChartType === 'stacked') {
        // 堆叠面积图
        seriesConfig = assetList.map((asset, index) => ({
          name: assetDisplayNames[asset],
          type: 'line',
          stack: 'Total',  // 堆叠
          data: seriesData[asset],
          smooth: true,
          symbol: 'none',
          lineStyle: {
            width: 1
          },
          areaStyle: {
            opacity: 0.6
          },
          itemStyle: {
            color: this.getColorByIndex(index)
          }
        }));
      } else {
        // 普通折线图
        seriesConfig = assetList.map((asset, index) => ({
          name: assetDisplayNames[asset],
          type: 'line',
          data: seriesData[asset],
          smooth: true,
          symbol: 'none',
          lineStyle: {
            width: 2
          },
          itemStyle: {
            color: this.getColorByIndex(index)
          }
        }));
      }
      
      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: (params) => {
            const date = dayjs(params[0].axisValue).format('YYYY-MM-DD');
            let result = `${date}<br />`;
            params.forEach(param => {
              const value = param.value[1];
              if (value !== undefined && value !== null) {
                const formattedValue = parseFloat(value).toFixed(4);
                result += `${param.seriesName}: ${(formattedValue * 100).toFixed(2)}%<br />`;
              } else {
                result += `${param.seriesName}: -<br />`;
              }
            });
            return result;
          }
        },
        legend: {
          data: assetList.map(asset => assetDisplayNames[asset]),
          type: 'scroll',
          orient: 'horizontal',
          top: '10%'
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          top: '20%',
          containLabel: true
        },
        xAxis: {
          type: 'time',
          boundaryGap: false,
          axisLabel: {
            formatter: (value) => {
              return dayjs(value).format('MM-DD');
            }
          }
        },
        yAxis: {
          type: 'value',
          axisLabel: {
            formatter: (value) => {
              return (value * 100).toFixed(0) + '%';
            }
          }
        },
        series: seriesConfig
      };
      
      this.weightChart.setOption(option, true);
    },
    getColorByIndex(index) {
      // 定义一组易于区分的颜色
      const colors = [
        '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
        '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#546570',
        '#bda29a', '#6e7074', '#5fa466', '#bd1111', '#4abcd9'
      ];
      return colors[index % colors.length];
    },
    handlePositionPageChange(page) {
      this.positionCurrentPage = page;
    },
    handleClose() {
      this.visible = false;
    },
    handleExport() {
      // 导出报告功能
      this.$message.info('正在导出回测报告...');
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-';
    },
    formatDateShort(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '-';
    },
    getReturnColor(value) {
      if (value == null) return '#909399';
      return value >= 0 ? '#67c23a' : '#f56c6c';
    },
    getCorrelationColor(value) {
      if (value == null) return '#909399';
      if (value > 0.5) return '#f56c6c';  // 高度正相关，红色
      if (value > 0.2) return '#e6a23c';  // 中度正相关，橙色
      if (value < -0.5) return '#409eff'; // 高度负相关，蓝色
      if (value < -0.2) return '#7a6df0'; // 中度负相关，紫色
      return '#909399';  // 低相关性，灰色
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
  padding: 15px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  text-align: center;
  background: #fafafa;
}

.metric-label {
  font-size: 12px;
  color: #606266;
  margin-bottom: 5px;
}

.metric-value {
  font-size: 16px;
  font-weight: bold;
  color: #303133;
}
</style>