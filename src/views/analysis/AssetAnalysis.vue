<template>
  <div class="asset-analysis">
    <el-card class="filter-card">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-data-analysis"></i> 资产分析</span>
      </div>
      
      <!-- 筛选条件 -->
      <el-form :inline="true" :model="filterForm" size="small">
        <el-form-item label="选择资产">
          <el-select
            v-model="filterForm.thscodes"
            multiple
            filterable
            placeholder="请选择资产"
            style="width: 400px;"
            @change="handleAssetChange"
          >
            <el-option
              v-for="asset in assetOptions"
              :key="asset.code"
              :label="`${asset.name} (${asset.code})`"
              :value="asset.code"
            >
            </el-option>
          </el-select>
        </el-form-item>
        
        <el-form-item label="日期范围">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            format="yyyy-MM-dd"
            value-format="yyyyMMdd"
            @change="handleDateChange"
          >
          </el-date-picker>
        </el-form-item>
        
        <el-form-item>
          <el-button type="primary" icon="el-icon-search" @click="handleAnalyze" :loading="loading">
            开始分析
          </el-button>
          <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 资产指标表格 -->
    <el-card v-if="metricsData.length > 0" class="metrics-card" style="margin-top: 20px;">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-document"></i> 资产指标</span>
      </div>
      <el-table :data="metricsData" border stripe>
        <el-table-column prop="thscode" label="资产代码" width="120" fixed></el-table-column>
        <el-table-column prop="name" label="资产名称" width="150" fixed></el-table-column>
        <el-table-column prop="annual_return" label="年化收益率" width="120">
          <template slot-scope="scope">
            <span :style="{color: scope.row.annual_return >= 0 ? '#67c23a' : '#f56c6c'}">
              {{ (scope.row.annual_return * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="annual_volatility" label="年化波动率" width="120">
          <template slot-scope="scope">
            {{ (scope.row.annual_volatility * 100).toFixed(2) }}%
          </template>
        </el-table-column>
        <el-table-column prop="sharpe_ratio" label="夏普比率" width="110">
          <template slot-scope="scope">
            {{ scope.row.sharpe_ratio ? scope.row.sharpe_ratio.toFixed(3) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="max_drawdown" label="最大回撤" width="110">
          <template slot-scope="scope">
            <span style="color: #f56c6c;">
              {{ (scope.row.max_drawdown * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="calmar_ratio" label="卡玛比率" width="110">
          <template slot-scope="scope">
            {{ scope.row.calmar_ratio ? scope.row.calmar_ratio.toFixed(3) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="cumulative_return" label="累计收益率" width="120">
          <template slot-scope="scope">
            <span :style="{color: scope.row.cumulative_return >= 0 ? '#67c23a' : '#f56c6c'}">
              {{ (scope.row.cumulative_return * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 图表展示区域 -->
    <el-row :gutter="20" v-if="timeSeriesData.length > 0" style="margin-top: 20px;">
      <!-- 累计净值曲线 -->
      <el-col :span="24">
        <el-card>
          <div slot="header" class="clearfix">
            <span><i class="el-icon-data-line"></i> 累计净值曲线</span>
          </div>
          <div id="navChart" style="width: 100%; height: 400px;"></div>
        </el-card>
      </el-col>

      <!-- 回撤曲线 -->
      <el-col :span="24" style="margin-top: 20px;">
        <el-card>
          <div slot="header" class="clearfix">
            <span><i class="el-icon-data-line"></i> 回撤曲线</span>
          </div>
          <div id="drawdownChart" style="width: 100%; height: 400px;"></div>
        </el-card>
      </el-col>

      <!-- 收益率分布 -->
      <el-col :span="24" style="margin-top: 20px;">
        <el-card>
          <div slot="header" class="clearfix">
            <span><i class="el-icon-data-line"></i> 收益率序列</span>
          </div>
          <div id="returnsChart" style="width: 100%; height: 400px;"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 相关性矩阵 -->
    <el-card v-if="correlationMatrix" class="correlation-card" style="margin-top: 20px;">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-s-grid"></i> 相关性矩阵</span>
        <el-radio-group v-model="correlationMethod" size="mini" style="float: right;" @change="handleCorrelationMethodChange">
          <el-radio-button label="pearson">皮尔逊</el-radio-button>
          <el-radio-button label="spearman">斯皮尔曼</el-radio-button>
          <el-radio-button label="kendall">肯德尔</el-radio-button>
        </el-radio-group>
      </div>
      <div id="correlationChart" style="width: 100%; height: 500px;"></div>
    </el-card>
  </div>
</template>

<script>
import { getAssetOptions } from '@/api/asset';
import { getAssetMetrics, getCorrelationMatrix, getTimeSeriesData } from '@/api/analysis';
import * as echarts from 'echarts';

export default {
  name: 'AssetAnalysis',
  data() {
    return {
      loading: false,
      assetOptions: [],
      filterForm: {
        thscodes: [],
        start_date: '',
        end_date: ''
      },
      dateRange: [],
      metricsData: [],
      timeSeriesData: [],
      correlationMatrix: null,
      correlationMethod: 'pearson',
      navChart: null,
      drawdownChart: null,
      returnsChart: null,
      correlationChart: null
    };
  },
  mounted() {
    this.loadAssetOptions();
    // 设置默认日期范围（最近一年）
    const endDate = new Date();
    const startDate = new Date();
    startDate.setFullYear(startDate.getFullYear() - 1);
    this.dateRange = [
      this.formatDate(startDate),
      this.formatDate(endDate)
    ];
    this.handleDateChange();
  },
  beforeDestroy() {
    // 销毁图表实例
    if (this.navChart) this.navChart.dispose();
    if (this.drawdownChart) this.drawdownChart.dispose();
    if (this.returnsChart) this.returnsChart.dispose();
    if (this.correlationChart) this.correlationChart.dispose();
  },
  methods: {
    // 加载资产选项
    async loadAssetOptions() {
      try {
        const res = await getAssetOptions();
        this.assetOptions = res.data || res || [];
      } catch (error) {
        console.error('加载资产列表失败:', error);
        this.$message.error('加载资产列表失败');
      }
    },
    // 格式化日期
    formatDate(date) {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      return `${year}${month}${day}`;
    },
    // 资产选择变化
    handleAssetChange() {
      // 可以在这里添加联动逻辑
    },
    // 日期范围变化
    handleDateChange() {
      if (this.dateRange && this.dateRange.length === 2) {
        this.filterForm.start_date = this.dateRange[0];
        this.filterForm.end_date = this.dateRange[1];
      }
    },
    // 开始分析
    async handleAnalyze() {
      if (this.filterForm.thscodes.length === 0) {
        this.$message.warning('请至少选择一个资产');
        return;
      }
      if (!this.filterForm.start_date || !this.filterForm.end_date) {
        this.$message.warning('请选择日期范围');
        return;
      }

      this.loading = true;
      try {
        // 并行请求多个接口
        const [metricsRes, timeSeriesRes, correlationRes] = await Promise.all([
          getAssetMetrics(this.filterForm),
          getTimeSeriesData(this.filterForm),
          getCorrelationMatrix(this.filterForm, this.correlationMethod)
        ]);

        // 处理资产指标数据
        const metricsData = metricsRes.data || metricsRes;
        this.metricsData = Array.isArray(metricsData) ? metricsData : [];

        // 处理时间序列数据
        const timeSeriesData = timeSeriesRes.data || timeSeriesRes;
        this.timeSeriesData = Array.isArray(timeSeriesData) ? timeSeriesData : [];

        // 处理相关性矩阵数据
        this.correlationMatrix = correlationRes.data || correlationRes;

        // 渲染图表
        this.$nextTick(() => {
          this.renderNavChart();
          this.renderDrawdownChart();
          this.renderReturnsChart();
          this.renderCorrelationChart();
        });

        this.$message.success('分析完成');
      } catch (error) {
        console.error('分析失败:', error);
        this.$message.error('分析失败: ' + (error.message || '未知错误'));
      } finally {
        this.loading = false;
      }
    },
    // 重置
    handleReset() {
      this.filterForm.thscodes = [];
      const endDate = new Date();
      const startDate = new Date();
      startDate.setFullYear(startDate.getFullYear() - 1);
      this.dateRange = [
        this.formatDate(startDate),
        this.formatDate(endDate)
      ];
      this.handleDateChange();
      this.metricsData = [];
      this.timeSeriesData = [];
      this.correlationMatrix = null;
    },
    // 相关性方法变化
    async handleCorrelationMethodChange() {
      if (this.filterForm.thscodes.length === 0) return;
      
      try {
        const correlationRes = await getCorrelationMatrix(this.filterForm, this.correlationMethod);
        this.correlationMatrix = correlationRes.data || correlationRes;
        this.$nextTick(() => {
          this.renderCorrelationChart();
        });
      } catch (error) {
        console.error('获取相关性矩阵失败:', error);
        this.$message.error('获取相关性矩阵失败');
      }
    },
    // 渲染累计净值图表
    renderNavChart() {
      if (this.timeSeriesData.length === 0) return;

      const chartDom = document.getElementById('navChart');
      if (!chartDom) return;

      if (this.navChart) {
        this.navChart.dispose();
      }
      this.navChart = echarts.init(chartDom);

      const series = this.timeSeriesData.map(asset => ({
        name: asset.name,
        type: 'line',
        data: asset.nav.map(point => [point.date, point.value]),
        smooth: true,
        showSymbol: false
      }));

      const option = {
        title: {
          text: '累计净值走势',
          left: 'center'
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          }
        },
        legend: {
          data: this.timeSeriesData.map(asset => asset.name),
          bottom: 0
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '60px',
          containLabel: true
        },
        xAxis: {
          type: 'time',
          boundaryGap: false
        },
        yAxis: {
          type: 'value',
          name: '净值'
        },
        series: series
      };

      this.navChart.setOption(option);
    },
    // 渲染回撤图表
    renderDrawdownChart() {
      if (this.timeSeriesData.length === 0) return;

      const chartDom = document.getElementById('drawdownChart');
      if (!chartDom) return;

      if (this.drawdownChart) {
        this.drawdownChart.dispose();
      }
      this.drawdownChart = echarts.init(chartDom);

      const series = this.timeSeriesData.map(asset => ({
        name: asset.name,
        type: 'line',
        data: asset.drawdown.map(point => [point.date, point.value * 100]),
        smooth: true,
        showSymbol: false,
        areaStyle: {
          color: 'rgba(245, 108, 108, 0.2)'
        }
      }));

      const option = {
        title: {
          text: '回撤走势',
          left: 'center'
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: function(params) {
            let result = params[0].axisValueLabel + '<br/>';
            params.forEach(param => {
              result += param.marker + param.seriesName + ': ' + param.value[1].toFixed(2) + '%<br/>';
            });
            return result;
          }
        },
        legend: {
          data: this.timeSeriesData.map(asset => asset.name),
          bottom: 0
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '60px',
          containLabel: true
        },
        xAxis: {
          type: 'time',
          boundaryGap: false
        },
        yAxis: {
          type: 'value',
          name: '回撤(%)',
          max: 0
        },
        series: series
      };

      this.drawdownChart.setOption(option);
    },
    // 渲染收益率图表
    renderReturnsChart() {
      if (this.timeSeriesData.length === 0) return;

      const chartDom = document.getElementById('returnsChart');
      if (!chartDom) return;

      if (this.returnsChart) {
        this.returnsChart.dispose();
      }
      this.returnsChart = echarts.init(chartDom);

      const series = this.timeSeriesData.map(asset => ({
        name: asset.name,
        type: 'line',
        data: asset.returns.map(point => [point.date, point.value * 100]),
        smooth: false,
        showSymbol: false
      }));

      const option = {
        title: {
          text: '收益率序列',
          left: 'center'
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: function(params) {
            let result = params[0].axisValueLabel + '<br/>';
            params.forEach(param => {
              result += param.marker + param.seriesName + ': ' + param.value[1].toFixed(4) + '%<br/>';
            });
            return result;
          }
        },
        legend: {
          data: this.timeSeriesData.map(asset => asset.name),
          bottom: 0
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '60px',
          containLabel: true
        },
        xAxis: {
          type: 'time',
          boundaryGap: false
        },
        yAxis: {
          type: 'value',
          name: '收益率(%)'
        },
        series: series
      };

      this.returnsChart.setOption(option);
    },
    // 渲染相关性矩阵热力图
    renderCorrelationChart() {
      if (!this.correlationMatrix) return;

      const chartDom = document.getElementById('correlationChart');
      if (!chartDom) return;

      if (this.correlationChart) {
        this.correlationChart.dispose();
      }
      this.correlationChart = echarts.init(chartDom);

      const assetInfo = this.correlationMatrix.asset_info || [];
      const matrix = this.correlationMatrix.matrix || {};
      
      const assetNames = assetInfo.map(info => info.name || info.thscode);
      const assetCodes = assetInfo.map(info => info.thscode);

      // 构建热力图数据
      const data = [];
      assetCodes.forEach((code1, i) => {
        assetCodes.forEach((code2, j) => {
          const value = matrix[code1] && matrix[code1][code2] !== undefined ? matrix[code1][code2] : 0;
          data.push([i, j, value]);
        });
      });

      const option = {
        title: {
          text: `相关性矩阵 (${this.correlationMatrix.method})`,
          left: 'center'
        },
        tooltip: {
          position: 'top',
          formatter: function(params) {
            return assetNames[params.value[0]] + ' vs ' + assetNames[params.value[1]] + '<br/>相关系数: ' + params.value[2].toFixed(3);
          }
        },
        grid: {
          height: '70%',
          top: '80px'
        },
        xAxis: {
          type: 'category',
          data: assetNames,
          splitArea: {
            show: true
          },
          axisLabel: {
            rotate: 45,
            interval: 0
          }
        },
        yAxis: {
          type: 'category',
          data: assetNames,
          splitArea: {
            show: true
          }
        },
        visualMap: {
          min: -1,
          max: 1,
          calculable: true,
          orient: 'horizontal',
          left: 'center',
          bottom: '10px',
          inRange: {
            color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026']
          }
        },
        series: [{
          name: '相关性',
          type: 'heatmap',
          data: data,
          label: {
            show: true,
            formatter: function(params) {
              return params.value[2].toFixed(2);
            }
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowColor: 'rgba(0, 0, 0, 0.5)'
            }
          }
        }]
      };

      this.correlationChart.setOption(option);
    }
  }
};
</script>

<style scoped>
.asset-analysis {
  padding: 20px;
}

.filter-card {
  margin-bottom: 20px;
}

.clearfix:before,
.clearfix:after {
  display: table;
  content: "";
}

.clearfix:after {
  clear: both;
}
</style>
