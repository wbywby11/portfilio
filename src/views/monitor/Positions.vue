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
        <el-col :span="5">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">总资产(CNH)</div>
            <div class="summary-value">{{ formatCurrency(summary.totalValue) }}</div>
          </el-card>
        </el-col>
        <el-col :span="5">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">总杠杆</div>
            <div class="summary-value">{{ formatNumber(summary.totalLeverage, 2) }}</div>
          </el-card>
        </el-col>
        <el-col :span="5">
          <el-card shadow="hover" class="summary-card">
            <div class="summary-label">持仓资产数</div>
            <div class="summary-value">{{ positions.length }}</div>
          </el-card>
        </el-col>
        <el-col :span="5">
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
      </el-row>

      <!-- 类别权重小计 -->
      <el-row :gutter="20" style="margin-top: 15px;" v-if="categoryWeights.length > 0">
        <el-col :span="24">
          <el-card shadow="hover" class="category-summary-card">
            <div class="category-summary-content">
              <span class="category-summary-label">类别权重：</span>
              <span 
                v-for="item in categoryWeights" 
                :key="item.category" 
                class="category-item"
              >
                <el-tag :type="getAssetClassType(item.category)" size="small">{{ item.category }}</el-tag>
                <span class="category-weight">{{ formatPercent(item.weight) }}</span>
              </span>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20" style="margin-top: 20px;">
        <!-- 持仓表格 -->
        <el-col :span="16">
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
              show-summary
              :summary-method="getSummaries"
            >
              <el-table-column prop="name" label="资产名称" min-width="150">
                <template slot-scope="scope">
                  <span>{{ getAssetName(scope.row) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="asset_class" label="资产类别" width="110" align="center">
                <template slot-scope="scope">
                  <el-tag 
                    :type="getAssetClassType(getAssetClass(scope.row))" 
                    size="small"
                  >
                    {{ getAssetClass(scope.row) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="current_weight" label="当前权重" width="110" align="right">
                <template slot-scope="scope">
                  {{ formatPercent(getCurrentWeight(scope.row)) }}
                </template>
              </el-table-column>
              <el-table-column prop="daily_change" label="当日涨跌" width="110" align="right">
                <template slot-scope="scope">
                  <span :style="{ color: getDailyChangeColor(getDailyChange(scope.row)) }">
                    {{ formatDailyChange(getDailyChange(scope.row)) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="currency" label="计价货币" width="100" align="center">
                <template slot-scope="scope">
                  {{ getCurrency(scope.row) }}
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="positions.length === 0" description="暂无持仓数据"></el-empty>
          </el-card>
        </el-col>

        <!-- 图表区 -->
        <el-col :span="8">
          <!-- 权重分布饼图 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>权重分布</span>
            </div>
            <div ref="pieChart" style="width: 100%; height: 400px;"></div>
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
            <!-- 分析窗口选择器 -->
            <el-row :gutter="15" style="margin-bottom: 15px;">
              <el-col :span="24">
                <div class="analysis-toolbar">
                  <span class="toolbar-label">分析窗口：</span>
                  <el-radio-group v-model="analysisWindow" size="small" @change="handleWindowChange">
                    <el-radio-button :label="60">近60天</el-radio-button>
                    <el-radio-button :label="120">近120天</el-radio-button>
                    <el-radio-button :label="250">近1年</el-radio-button>
                  </el-radio-group>
                </div>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <!-- 资产相关性热力图 -->
              <el-col :span="14">
                <div class="analysis-section">
                  <div class="section-title">资产相关性矩阵</div>
                  <div v-show="correlationMatrix" ref="correlationChart" style="width: 100%; height: 380px;"></div>
                  <el-empty v-if="!correlationMatrix" description="暂无相关性数据"></el-empty>
                </div>
              </el-col>
              <!-- 波动率分析 -->
              <el-col :span="10">
                <div class="analysis-section">
                  <div class="section-title">年化波动率</div>
                  <div v-show="assetMetrics && assetMetrics.length > 0" ref="volatilityChart" style="width: 100%; height: 380px;"></div>
                  <el-empty v-if="!assetMetrics || assetMetrics.length === 0" description="暂无波动率数据"></el-empty>
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
      correlationChart: null,
      volatilityChart: null,
      analysisWindow: 120,
      analysisLoading: false
    };
  },
  computed: {
    ...mapState('monitor', ['positions', 'monitorState', 'assetMetrics', 'correlationMatrix']),
    assetCodes() {
      return ['SH000300', 'SZ399006', 'ZZ000001', 'HSTECH', 'SPX', 'GDAXI', 'ZQGZ10', 'ZQGZ2', 'B00Y', 'GLD', 'IRON', 'YSJS'];
    },
    updateTime() {
      return (this.monitorState && this.monitorState.date) 
        ? dayjs(this.monitorState.date).format('YYYY-MM-DD')
        : '-';
    },
    summary() {
      if (this.positions.length === 0) {
        return {
          totalValue: 0,
          totalLeverage: 0,
          maxWeight: 0,
          minWeight: 0
        };
      }

      const totalValue = this.positions.reduce((sum, p) => sum + (p.value_cnh || 0), 0);
      const weights = this.positions.map(p => this.getCurrentWeight(p));
      const totalLeverage = weights.reduce((sum, w) => sum + Math.abs(w), 0) / 100;
      const maxWeight = Math.max(...weights);
      const positiveWeights = weights.filter(w => w > 0);
      const minWeight = positiveWeights.length > 0 ? Math.min(...positiveWeights) : 0;

      return {
        totalValue,
        totalLeverage,
        maxWeight,
        minWeight
      };
    },
    categoryWeights() {
      if (this.positions.length === 0) {
        return [];
      }
      
      const categoryMap = {};
      this.positions.forEach(p => {
        const category = this.getAssetClass(p);
        const weight = this.getCurrentWeight(p);
        if (!categoryMap[category]) {
          categoryMap[category] = 0;
        }
        categoryMap[category] += weight;
      });
      
      return Object.keys(categoryMap).map(category => ({
        category: category,
        weight: categoryMap[category]
      })).sort((a, b) => b.weight - a.weight);
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
    if (this.correlationChart) {
      this.correlationChart.dispose();
    }
    if (this.volatilityChart) {
      this.volatilityChart.dispose();
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
        
        // 在获取持仓数据后，获取资产分析数据
        if (this.monitorState && this.monitorState.date) {
          await this.loadAssetAnalysis();
        }
        
        this.$nextTick(() => {
          this.initCharts();
          this.renderPieChart();
          this.initCorrelationChart();
          this.initVolatilityChart();
          this.renderCorrelationHeatmap();
          this.renderVolatilityChart();
        });
      } catch (error) {
        this.$message.error('加载数据失败：' + ((error.response && error.response.data && error.response.data.message) ? error.response.data.message : error.message));
      } finally {
        this.loading = false;
      }
    },
    initCharts() {
      if (!this.pieChart && this.$refs.pieChart) {
        this.pieChart = echarts.init(this.$refs.pieChart);
      }
    },
    renderPieChart() {
      if (!this.pieChart || this.positions.length === 0) {
        return;
      }

      const data = this.positions.map(p => ({
        name: this.getAssetName(p),
        value: Math.abs(this.getCurrentWeight(p))
      }));

      const option = {
        tooltip: {
          trigger: 'item',
          formatter: (params) => {
            return `${params.name}<br/>权重: ${params.value.toFixed(2)}%`;
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
                return `${params.name}\n${params.value.toFixed(2)}%`;
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
    handleResize() {
      if (this.pieChart) {
        this.pieChart.resize();
      }
      if (this.correlationChart) {
        this.correlationChart.resize();
      }
      if (this.volatilityChart) {
        this.volatilityChart.resize();
      }
    },
    // 兼容新旧数据格式的辅助方法
    getAssetName(item) {
      return item.name || item.asset_name || item.asset_code || '-';
    },
    getAssetClass(item) {
      return item.asset_class || '未分类';
    },
    getCurrentWeight(item) {
      // 兼容旧格式：优先使用 current_weight，否则使用 actual_weight
      if (item.current_weight !== undefined) {
        return item.current_weight;
      }
      return item.actual_weight || 0;
    },
    getDailyChange(item) {
      // 兼容旧格式：优先使用 daily_change，否则使用 daily_return
      if (item.daily_change !== undefined) {
        return item.daily_change;
      }
      // 旧格式 daily_return 是小数，需要转换为百分比
      if (item.daily_return !== undefined && item.daily_return !== null) {
        return item.daily_return * 100;
      }
      return null;
    },
    getCurrency(item) {
      return item.currency || '-';
    },
    getAssetClassType(assetClass) {
      const typeMap = {
        '权益': 'primary',
        '固定收益': 'success',
        '大宗商品': 'warning'
      };
      return typeMap[assetClass] || 'info';
    },
    getDailyChangeColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (value > 0) return '#F56C6C';  // 红涨
      if (value < 0) return '#67C23A';  // 绿跌
      return '#909399';
    },
    formatDailyChange(value) {
      if (value === null || value === undefined) return '-';
      const formatted = Math.abs(value).toFixed(2);
      if (value > 0) return '+' + formatted + '%';
      if (value < 0) return '-' + formatted + '%';
      return formatted + '%';
    },
    formatNumber(num, decimals = 2) {
      if (num === null || num === undefined) return '-';
      return num.toFixed(decimals);
    },
    formatPercent(num) {
      if (num === null || num === undefined) return '-';
      return num.toFixed(2) + '%';
    },
    formatCurrency(num) {
      if (num === null || num === undefined) return '-';
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num);
    },
    getSummaries(param) {
      const { columns, data } = param;
      const sums = [];
      columns.forEach((column, index) => {
        if (index === 0) {
          sums[index] = '合计';
          return;
        }
        if (column.property === 'current_weight') {
          const total = data.reduce((sum, item) => {
            return sum + Math.abs(this.getCurrentWeight(item));
          }, 0);
          sums[index] = this.formatPercent(total);
        } else {
          sums[index] = '';
        }
      });
      return sums;
    },
    async loadAssetAnalysis() {
      try {
        this.analysisLoading = true;
        var endDate = this.monitorState.date; // 格式 YYYY-MM-DD
        // 计算起始日期
        var end = new Date(endDate);
        var start = new Date(end);
        start.setDate(start.getDate() - this.analysisWindow);
        var startDate = start.toISOString().slice(0, 10); // YYYY-MM-DD
        
        await this.$store.dispatch('monitor/fetchAssetAnalysis', {
          thscodes: this.assetCodes,
          startDate: startDate,
          endDate: endDate
        });
      } catch (error) {
        console.warn('获取资产分析数据失败:', error);
      } finally {
        this.analysisLoading = false;
      }
    },
    async handleWindowChange() {
      if (this.monitorState && this.monitorState.date) {
        await this.loadAssetAnalysis();
        this.$nextTick(function() {
          this.renderCorrelationHeatmap();
          this.renderVolatilityChart();
        }.bind(this));
      }
    },
    initCorrelationChart() {
      if (!this.correlationChart && this.$refs.correlationChart) {
        this.correlationChart = echarts.init(this.$refs.correlationChart);
      }
    },
    initVolatilityChart() {
      if (!this.volatilityChart && this.$refs.volatilityChart) {
        this.volatilityChart = echarts.init(this.$refs.volatilityChart);
      }
    },
    renderCorrelationHeatmap() {
      this.initCorrelationChart();
      if (!this.correlationChart || !this.correlationMatrix) return;
      
      var corrData = this.correlationMatrix;
      if (!corrData.matrix) return;
      
      var assets = corrData.asset_info || [];
      var assetNames = assets.map(function(a) { return a.name; });
      var matrix = corrData.matrix;
      
      var heatmapData = [];
      for (var i = 0; i < assets.length; i++) {
        var code1 = assets[i].thscode;
        for (var j = 0; j < assets.length; j++) {
          var code2 = assets[j].thscode;
          var value = (matrix[code1] && matrix[code1][code2] !== undefined) ? parseFloat(matrix[code1][code2]) : 0;
          heatmapData.push([j, i, value]);
        }
      }
      
      var option = {
        tooltip: {
          trigger: 'item',
          formatter: function(params) {
            var val = params.value[2];
            return assetNames[params.value[0]] + ' - ' + assetNames[params.value[1]] + '<br/>相关系数: ' + val.toFixed(4);
          }
        },
        grid: {
          left: '20%',
          right: '12%',
          top: '5%',
          bottom: '20%'
        },
        xAxis: {
          type: 'category',
          data: assetNames,
          axisLabel: { rotate: 45, interval: 0, fontSize: 10 }
        },
        yAxis: {
          type: 'category',
          data: assetNames,
          axisLabel: { fontSize: 10 }
        },
        visualMap: {
          min: -1,
          max: 1,
          calculable: true,
          orient: 'vertical',
          right: 0,
          top: 'center',
          itemHeight: 200,
          text: ['1.0', '-1.0'],
          inRange: {
            color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026']
          }
        },
        series: [{
          name: '相关系数',
          type: 'heatmap',
          data: heatmapData,
          label: {
            show: assets.length <= 8,
            formatter: function(params) { return params.value[2].toFixed(2); },
            fontSize: 9
          },
          emphasis: {
            itemStyle: { borderColor: '#333', borderWidth: 1 }
          }
        }]
      };
      
      this.correlationChart.setOption(option, true);
    },
    renderVolatilityChart() {
      this.initVolatilityChart();
      if (!this.volatilityChart || !this.assetMetrics || this.assetMetrics.length === 0) return;
      
      var metrics = this.assetMetrics;
      var sortedMetrics = metrics.slice().sort(function(a, b) {
        return (b.annual_volatility || 0) - (a.annual_volatility || 0);
      });
      
      var names = sortedMetrics.map(function(m) { return m.name; });
      var volatilities = sortedMetrics.map(function(m) { return ((m.annual_volatility || 0) * 100); });
      
      // 计算75分位阈值
      var sorted = volatilities.slice().sort(function(a, b) { return a - b; });
      var threshold = sorted[Math.floor(sorted.length * 0.75)] || 20;
      
      var option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: function(params) {
            var data = params[0];
            return data.name + '<br/>年化波动率: ' + data.value.toFixed(2) + '%';
          }
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '20%',
          top: '10%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          data: names,
          axisLabel: {
            rotate: 45,
            interval: 0,
            fontSize: 10
          }
        },
        yAxis: {
          type: 'value',
          name: '年化波动率(%)',
          axisLabel: { formatter: '{value}%' }
        },
        series: [{
          name: '年化波动率',
          type: 'bar',
          data: volatilities,
          itemStyle: {
            color: function(params) {
              return (params.value || 0) > threshold ? '#F56C6C' : '#409EFF';
            }
          },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{
              yAxis: threshold,
              lineStyle: { color: '#E6A23C', type: 'dashed' },
              label: { show: true, formatter: '75分位: ' + threshold.toFixed(1) + '%' }
            }]
          }
        }]
      };
      
      this.volatilityChart.setOption(option, true);
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

.category-summary-card {
  padding: 10px 15px;
}

.category-summary-content {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 15px;
}

.category-summary-label {
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
  font-size: 14px;
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

.analysis-toolbar {
  display: flex;
  align-items: center;
  padding: 10px 15px;
  background: #f5f7fa;
  border-radius: 4px;
}

.toolbar-label {
  font-size: 13px;
  color: #606266;
  margin-right: 10px;
}
</style>
