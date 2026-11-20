<template>
  <el-dialog
    :title="`回测详情 - ${formatDateShort(record.start_date)} 至 ${formatDateShort(record.end_date)}`"
    :visible.sync="visible"
    width="1200px"
    :close-on-click-modal="false"
    @close="handleClose"
    top="5vh"
    append-to-body
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
              <div class="metric-label">年化收益率（260日）</div>
              <div class="metric-value" :style="{ color: getReturnColor(record.result.annual_return) }">
                {{ record.result.annual_return != null ? (record.result.annual_return * 100).toFixed(2) + '%' : '-' }}
              </div>
              <div class="metric-sub">365日：{{ record.result.annual_return_365 != null ? (record.result.annual_return_365 * 100).toFixed(2) + '%' : '-' }}</div>
            </div>
          </el-col>
          <el-col :span="4">
            <div class="metric-box">
              <div class="metric-label">年化波动率（260日）</div>
              <div class="metric-value">
                {{ record.result.annual_volatility != null ? (record.result.annual_volatility * 100).toFixed(2) + '%' : '-' }}
              </div>
              <div class="metric-sub">365日：{{ record.result.annual_volatility_365 != null ? (record.result.annual_volatility_365 * 100).toFixed(2) + '%' : '-' }}</div>
            </div>
          </el-col>
          <el-col :span="4">
            <div class="metric-box">
              <div class="metric-label">夏普比率（260日）</div>
              <div class="metric-value" :style="{ color: record.result.sharpe_ratio > 1 ? '#f56c6c' : '#909399' }">
                {{ record.result.sharpe_ratio != null ? record.result.sharpe_ratio.toFixed(3) : '-' }}
              </div>
              <div class="metric-sub">365日：{{ record.result.sharpe_ratio_365 != null ? record.result.sharpe_ratio_365.toFixed(3) : '-' }}</div>
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
              <div class="metric-label">卡玛比率（260日）</div>
              <div class="metric-value">
                {{ record.result.calmar_ratio.toFixed(3) }}
              </div>
              <div class="metric-sub">365日：{{ record.result.calmar_ratio_365 != null ? record.result.calmar_ratio_365.toFixed(3) : '-' }}</div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <!-- 旧记录无明细提示（升级前保存的回测记录只含指标） -->
      <el-alert
        v-if="!record.result.equity_curve || record.result.equity_curve.length === 0"
        title="该记录未保存明细数据"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px;"
      >
        <div slot="default">
          历史回测记录只保存了绩效指标。重新运行回测后，这里将展示净值曲线、回撤、权重变化、持仓记录与相关性矩阵。
        </div>
      </el-alert>

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

      <!-- 回撤曲线图表 -->
      <el-card shadow="never" class="info-section" v-if="drawdownData.length > 0">
        <div slot="header">
          <span>回撤曲线</span>
          <span style="float: right; color: #909399; font-size: 13px;">
            最大回撤: <span style="color: #f56c6c; font-weight: bold;">{{ (record.result.max_drawdown * 100).toFixed(2) }}%</span>
          </span>
        </div>
        <div ref="drawdownChart" style="width: 100%; height: 350px;"></div>
      </el-card>

      <!-- 波动率曲线图表 -->
      <el-card shadow="never" class="info-section" v-if="volatilityData.length > 0">
        <div slot="header">
          <span>波动率曲线</span>
          <span style="float: right; color: #909399; font-size: 13px;">
            年化波动率: <span style="color: #e6a23c; font-weight: bold;">{{ record.result.annual_volatility != null ? (record.result.annual_volatility * 100).toFixed(2) + '%' : '-' }}</span>
          </span>
        </div>
        <div ref="volatilityChart" style="width: 100%; height: 350px;"></div>
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
        <div slot="header">相关性矩阵</div>
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
import { downsampleParallel } from '@/utils/downsample';
import { createDateAxisLabelFormatter } from '@/utils/dateAxis';

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
      drawdownChart: null,
      volatilityChart: null,
      weightChart: null,
      positionCurrentPage: 1,
      positionPageSize: 10,
      chartType: 'both', // total: 总净值, unit: 单位净值, both: 双轴对比
      weightChartType: 'stacked', // stacked: 堆叠面积图, line: 折线图
      drawdownData: [], // 回撤数据
      volatilityData: [], // 波动率数据
      cachedAllPositions: [] // 缓存展开后的持仓数组，避免分页时重复遍历
    };
  },
  computed: {
    paginatedPositions() {
      const start = (this.positionCurrentPage - 1) * this.positionPageSize;
      const end = start + this.positionPageSize;
      return this.cachedAllPositions.slice(start, end);
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
      return this.cachedAllPositions.length;
    },
    hasWeightChanges() {
      return (
        this.record.result.weight_changes &&
        this.record.result.weight_changes.length > 0
      );
    }
  },
  watch: {
    'record.result.positions': {
      handler(positions) {
        if (!positions) {
          this.cachedAllPositions = [];
          return;
        }
        let all = [];
        positions.forEach(positionRecord => {
          const date = positionRecord.date;
          if (positionRecord.positions && Array.isArray(positionRecord.positions)) {
            positionRecord.positions.forEach(pos => {
              all.push({
                date: date,
                asset_code: pos.asset_code,
                asset_name: pos.asset_name,
                weight: pos.weight,
                shares: pos.shares,
                price: pos.price,
                market_value: pos.market_value,
                portfolio_value: positionRecord.portfolio_value,
                rebalance_reason: positionRecord.rebalance_reason
              });
            });
          }
        });
        this.cachedAllPositions = all;
      },
      immediate: true
    },
    value(val) {
      this.visible = val;
      if (val) {
        // 先计算回撤和波动率数据，然后等待DOM更新后再初始化图表
        this.calculateDrawdown();
        this.calculateVolatility();
        this.$nextTick(() => {
          this.initChart();
          this.renderEquityChart();
          this.renderDrawdownChart();
          this.renderVolatilityChart();
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
    },
    'record.result.equity_curve'() {
      // 当净值曲线数据更新时重新计算回撤和波动率
      this.calculateDrawdown();
      this.calculateVolatility();
      this.$nextTick(() => {
        this.initChart();
        this.renderDrawdownChart();
        this.renderVolatilityChart();
      });
    }
  },
  mounted() {
    if (this.visible) {
      // 先计算回撤和波动率数据
      this.calculateDrawdown();
      this.calculateVolatility();
      this.$nextTick(() => {
        // 等待DOM更新后再初始化图表
        this.initChart();
        this.renderEquityChart();
        this.renderDrawdownChart();
        this.renderVolatilityChart();
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
    if (this.drawdownChart) {
      this.drawdownChart.dispose();
      this.drawdownChart = null;
    }
    if (this.volatilityChart) {
      this.volatilityChart.dispose();
      this.volatilityChart = null;
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
      if (this.$refs.drawdownChart && !this.drawdownChart) {
        this.drawdownChart = echarts.init(this.$refs.drawdownChart);
      }
      if (this.$refs.volatilityChart && !this.volatilityChart) {
        this.volatilityChart = echarts.init(this.$refs.volatilityChart);
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
      let dates = equityCurve.map(item => dayjs(item.date).format('YYYY-MM-DD'));
      let unitValues = equityCurve.map(item => item.unit_value);
      // 轴标签格式：跨年显示 YYYY-MM，单年显示 MM-DD（基于完整序列判断）
      const dateLabelFormatter = createDateAxisLabelFormatter(dates);
      
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

      // 降采样：限制最多 500 个数据点，避免大数据量时 ECharts 卡顿
      const maxPoints = 500;
      if (dates.length > maxPoints) {
        const sampledUnit = downsampleParallel(dates, unitValues, maxPoints);
        const sampledReturn = downsampleParallel(dates, returnValues, maxPoints);
        dates = sampledUnit.dates;
        unitValues = sampledUnit.values;
        returnValues = sampledReturn.values;
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
          data: dates,
          axisLabel: {
            formatter: dateLabelFormatter
          }
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
                  color: '#f56c6c'
                },
                areaStyle: {
                  color: {
                    type: 'linear',
                    x: 0,
                    y: 0,
                    x2: 0,
                    y2: 1,
                    colorStops: [
                      { offset: 0, color: 'rgba(245, 108, 108, 0.3)' },
                      { offset: 1, color: 'rgba(245, 108, 108, 0.05)' }
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
                  color: this.chartType === 'return' ? '#f56c6c' : '#409eff'
                },
                areaStyle: this.chartType === 'return' ? {
                  color: {
                    type: 'linear',
                    x: 0,
                    y: 0,
                    x2: 0,
                    y2: 1,
                    colorStops: [
                      { offset: 0, color: 'rgba(245, 108, 108, 0.3)' },
                      { offset: 1, color: 'rgba(245, 108, 108, 0.05)' }
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
      
      // 提取资产代码：展示全部候选资产（含权重为 0 的），图注与权重数据一致
      const allAssets = new Set();
      weightChanges.forEach(change => {
        if (change.weights) {
          Object.keys(change.weights).forEach(asset => allAssets.add(asset));
        }
      });
      const assetList = Array.from(allAssets);

      // 轴标签格式：跨年显示 YYYY-MM，单年显示 MM-DD
      const dateLabelFormatter = createDateAxisLabelFormatter(weightChanges.map(change => change.date).filter(Boolean));
      
      // 为每个资产创建时间序列数据
      const seriesData = {};
      const assetDisplayNames = {}; // 存储资产显示名称
      
      assetList.forEach(asset => {
        // 生成显示名称：资产代码 - 资产名称（如果有名称且与代码不同）
        const assetName = assetNames[asset];
        assetDisplayNames[asset] = (assetName && assetName.trim() && assetName !== asset)
          ? `${asset} - ${assetName}`
          : asset;
        
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
      
      // 纵轴边界：做空策略存在负权重，下界取「各日权重和」最小值（堆叠模式下即负向堆叠底边）；
      // 上限同时覆盖「单资产最大权重」，避免做空对冲场景单权重超出日权重和被裁剪；
      // 纯多头策略（无负权重）上下界行为与历史一致
      let maxWeightSum = 0;
      let minWeightSum = 0;
      let maxSingleWeight = 0;
      weightChanges.forEach(change => {
        const ws = Object.values(change.weights || {});
        const sum = ws.reduce((s, w) => s + (Number(w) || 0), 0);
        maxWeightSum = Math.max(maxWeightSum, sum);
        minWeightSum = Math.min(minWeightSum, sum);
        ws.forEach(w => {
          const v = Number(w) || 0;
          if (v > maxSingleWeight) maxSingleWeight = v;
        });
      });
      const upperBound = Math.max(maxWeightSum, maxSingleWeight);
      const yAxisMax = upperBound <= 1 ? 1 : Math.ceil(upperBound * 10) / 10;
      const yAxisMin = minWeightSum >= 0 ? 0 : Math.floor(minWeightSum * 10) / 10;

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
          left: 80,
          right: '4%',
          bottom: '3%',
          top: '20%',
          containLabel: true
        },
        xAxis: {
          type: 'time',
          boundaryGap: false,
          axisLabel: {
            formatter: dateLabelFormatter
          }
        },
        yAxis: {
          type: 'value',
          name: '权重 (%)',
          nameGap: 25,
          min: yAxisMin,
          max: yAxisMax,
          axisLabel: {
            formatter: (value) => {
              return (value * 100).toFixed(0) + '%';
            },
            margin: 10
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
      return value >= 0 ? '#f56c6c' : '#67c23a';
    },
    getCorrelationColor(value) {
      if (value == null) return '#909399';
      if (value > 0.5) return '#f56c6c';  // 高度正相关，红色
      if (value > 0.2) return '#e6a23c';  // 中度正相关，橙色
      if (value < -0.5) return '#409eff'; // 高度负相关，蓝色
      if (value < -0.2) return '#7a6df0'; // 中度负相关，紫色
      return '#909399';  // 低相关性，灰色
    },
    calculateDrawdown() {
      // 从后端返回的 equity_curve 中提取回撤数据
      if (!this.record.result.equity_curve || this.record.result.equity_curve.length === 0) {
        console.log('回测详情: equity_curve 为空，无法生成回撤数据');
        this.drawdownData = [];
        return;
      }
      
      console.log('回测详情: equity_curve 有', this.record.result.equity_curve.length, '个数据点');
      console.log('回测详情: 第一个点的数据:', this.record.result.equity_curve[0]);
      
      this.drawdownData = this.record.result.equity_curve
        .filter(item => item.drawdown != null) // 只保留有回撤数据的点
        .map(item => ({
          date: item.date,
          value: item.drawdown * 100 // 转换为百分比
        }));
      
      console.log('回测详情: 回撤数据点数:', this.drawdownData.length);
      if (this.drawdownData.length > 0) {
        console.log('回测详情: 第一个回撤点:', this.drawdownData[0]);
      }
    },
    calculateVolatility() {
      // 从后端返回的 equity_curve 中提取波动率数据
      if (!this.record.result.equity_curve || this.record.result.equity_curve.length === 0) {
        console.log('回测详情: equity_curve 为空，无法生成波动率数据');
        this.volatilityData = [];
        return;
      }
      
      this.volatilityData = this.record.result.equity_curve
        .filter(item => item.portfolio_volatility != null) // 只保留有波动率数据的点
        .map(item => ({
          date: item.date,
          value: item.portfolio_volatility * 100, // 转换为百分比
          isVolReset: item.rebalance_type === 'vol_reset'
        }));
      
      console.log('回测详情: 波动率数据点数:', this.volatilityData.length);
      if (this.volatilityData.length > 0) {
        console.log('回测详情: 第一个波动率点:', this.volatilityData[0]);
      }
    },
    renderDrawdownChart() {
      if (!this.drawdownChart || this.drawdownData.length === 0) {
        return;
      }
      
      let dates = this.drawdownData.map(item => dayjs(item.date).format('YYYY-MM-DD'));
      let values = this.drawdownData.map(item => item.value);
      // 轴标签格式：跨年显示 YYYY-MM，单年显示 MM-DD（基于完整序列判断）
      const dateLabelFormatter = createDateAxisLabelFormatter(dates);

      // 降采样：限制最多 500 个数据点
      const sampledDD = downsampleParallel(dates, values, 500);
      dates = sampledDD.dates;
      values = sampledDD.values;
      
      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: (params) => {
            const date = params[0].axisValue;
            const value = params[0].value;
            return `${date}<br />回撤: ${value.toFixed(2)}%`;
          }
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          top: '10%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: dates,
          axisLabel: {
            formatter: dateLabelFormatter
          }
        },
        yAxis: {
          type: 'value',
          max: 0,
          axisLabel: {
            formatter: '{value}%'
          }
        },
        series: [
          {
            name: '回撤',
            type: 'line',
            data: values,
            smooth: true,
            symbol: 'none',
            lineStyle: {
              width: 2,
              color: '#f56c6c'
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(245, 108, 108, 0.1)' },
                  { offset: 1, color: 'rgba(245, 108, 108, 0.3)' }
                ]
              }
            }
          }
        ]
      };
      
      this.drawdownChart.setOption(option, true);
    },
    renderVolatilityChart() {
      if (!this.volatilityChart || this.volatilityData.length === 0) {
        return;
      }

      // 降采样波动率数据：保留完整元数据用于 tooltip 和 markPoint
      const MAX_VOL_POINTS = 500;
      let sampledVolData = this.volatilityData;
      if (this.volatilityData.length > MAX_VOL_POINTS) {
        const step = (this.volatilityData.length - 1) / (MAX_VOL_POINTS - 1);
        const indices = [];
        for (let k = 0; k < MAX_VOL_POINTS; k++) {
          indices.push(Math.round(k * step));
        }
        sampledVolData = indices.map(idx => this.volatilityData[idx]);
      }

      const dates = sampledVolData.map(item => dayjs(item.date).format('YYYY-MM-DD'));
      const values = sampledVolData.map(item => item.value);
      // 轴标签格式：跨年显示 YYYY-MM，单年显示 MM-DD（基于完整序列判断）
      const dateLabelFormatter = createDateAxisLabelFormatter(this.volatilityData.map(item => item.date));
      const volResetPoints = sampledVolData
        .map((item, i) => (item.isVolReset ? { name: '波动率重置', coord: [i, item.value] } : null))
        .filter(Boolean);
      
      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: (params) => {
            const date = params[0].axisValue;
            const value = params[0].value;
            const idx = params[0].dataIndex;
            const isReset = sampledVolData[idx] && sampledVolData[idx].isVolReset;
            return `${date}<br />组合波动率: ${(value != null ? value : 0).toFixed(2)}%${isReset ? '<br /><span style="color:#E6A23C">◆ 波动率重置调仓日</span>' : ''}`;
          }
        },
        grid: {
          left: '8%',
          right: '14%',
          bottom: '3%',
          top: '10%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: dates,
          axisLabel: {
            formatter: dateLabelFormatter
          }
        },
        yAxis: {
          type: 'value',
          name: '年化波动率 (%)',
          min: 0,
          axisLabel: {
            formatter: '{value}%'
          }
        },
        series: [
          {
            name: '组合波动率',
            type: 'line',
            data: values,
            smooth: true,
            symbol: 'none',
            lineStyle: {
              width: 2,
              color: '#e6a23c'
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(230, 162, 60, 0.3)' },
                  { offset: 1, color: 'rgba(230, 162, 60, 0.1)' }
                ]
              }
            },
            markPoint: volResetPoints.length > 0 ? {
              symbol: 'pin',
              symbolSize: 40,
              data: volResetPoints,
              label: { formatter: '波动率重置', fontSize: 10 },
              itemStyle: { color: '#E6A23C' },
              emphasis: { label: { show: true } }
            } : undefined
          }
        ]
      };
      
      this.volatilityChart.setOption(option, true);
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
  background: linear-gradient(135deg, #f8f9fb 0%, #ffffff 100%);
  border: 1px solid #e8ecf1;
  border-radius: 8px;
  padding: 16px 12px;
  text-align: center;
  transition: box-shadow 0.2s;
}
.metric-box:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.metric-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}

.metric-value {
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.metric-sub {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  font-variant-numeric: tabular-nums;
}

.backtest-detail .el-card {
  margin-bottom: 16px;
  border-radius: 8px;
}
.backtest-detail .el-card >>> .el-card__header {
  font-size: 14px;
  font-weight: 600;
  padding: 12px 16px;
  background: #fafbfc;
}
</style>