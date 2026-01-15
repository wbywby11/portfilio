<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">资产行情</h2>
    </div>

    <div class="page-content">
      <!-- 资产选择区 -->
      <el-card class="select-card" shadow="never">
        <div class="select-section">
          <el-form :inline="true">
            <el-form-item label="选择资产">
              <el-select
                v-model="selectedAssets"
                multiple
                filterable
                placeholder="请选择要查看的资产"
                style="width: 500px;"
                @change="handleAssetChange"
              >
                <el-option
                  v-for="asset in assetOptions"
                  :key="asset.code"
                  :label="`${asset.code} - ${asset.name}`"
                  :value="asset.code"
                ></el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="时间范围">
              <el-date-picker
                v-model="dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                value-format="yyyy-MM-dd"
                @change="handleDateChange"
              ></el-date-picker>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" icon="el-icon-search" @click="loadQuoteData">查询</el-button>
              <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
            </el-form-item>
          </el-form>
        </div>

        <!-- 已选资产标签 -->
        <div v-if="selectedAssets.length > 0" class="selected-tags">
          <span style="margin-right: 10px; color: #909399;">已选择：</span>
          <el-tag
            v-for="code in selectedAssets"
            :key="code"
            closable
            @close="handleRemoveAsset(code)"
            style="margin-right: 8px;"
          >
            {{ getAssetName(code) }}
          </el-tag>
        </div>
      </el-card>

      <!-- 图表区域 -->
      <el-card class="chart-card" v-loading="loading">
        <div class="chart-header">
          <h3>行情走势图</h3>
          <div class="chart-tools">
            <el-radio-group v-model="chartType" size="small" @change="updateChart">
              <el-radio-button label="line">折线图</el-radio-button>
              <el-radio-button label="candlestick">K线图</el-radio-button>
            </el-radio-group>
          </div>
        </div>
        <div ref="chartContainer" class="chart-container"></div>
        
        <!-- 空状态 -->
        <el-empty
          v-if="!loading && selectedAssets.length === 0"
          description="请选择资产查看行情"
          :image-size="120"
        ></el-empty>
      </el-card>
    </div>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import dayjs from 'dayjs';
import request from '@/utils/request';

export default {
  name: 'AssetQuote',
  data() {
    return {
      selectedAssets: [],
      assetOptions: [],
      dateRange: null,
      chartType: 'line',
      loading: false,
      chartInstance: null,
      quoteData: {}  // { assetCode: [{date, open, close, high, low, volume}] }
    };
  },
  created() {
    this.initDateRange();
    this.fetchAssetOptions();
  },
  mounted() {
    this.initChart();
    window.addEventListener('resize', this.handleResize);
  },
  beforeDestroy() {
    if (this.chartInstance) {
      this.chartInstance.dispose();
    }
    window.removeEventListener('resize', this.handleResize);
  },
  methods: {
    // 初始化默认时间范围（最近30天）
    initDateRange() {
      const endDate = dayjs().format('YYYY-MM-DD');
      const startDate = dayjs().subtract(30, 'day').format('YYYY-MM-DD');
      this.dateRange = [startDate, endDate];
    },
    
    // 获取资产选项
    async fetchAssetOptions() {
      try {
        const res = await this.$store.dispatch('asset/fetchAssetOptions');
        this.assetOptions = res;
      } catch (error) {
        console.error('获取资产列表失败:', error);
      }
    },
    
    // 资产选择变化
    handleAssetChange() {
      if (this.selectedAssets.length > 0) {
        this.loadQuoteData();
      } else {
        this.quoteData = {};
        this.updateChart();
      }
    },
    
    // 日期范围变化
    handleDateChange() {
      if (this.selectedAssets.length > 0) {
        this.loadQuoteData();
      }
    },
    
    // 移除资产
    handleRemoveAsset(code) {
      const index = this.selectedAssets.indexOf(code);
      if (index > -1) {
        this.selectedAssets.splice(index, 1);
        delete this.quoteData[code];
        this.updateChart();
      }
    },
    
    // 重置
    handleReset() {
      this.selectedAssets = [];
      this.initDateRange();
      this.quoteData = {};
      this.updateChart();
    },
    
    // 加载行情数据
    async loadQuoteData() {
      if (this.selectedAssets.length === 0 || !this.dateRange) {
        return;
      }
      
      this.loading = true;
      try {
        const promises = this.selectedAssets.map(code => 
          this.fetchAssetKline(code, this.dateRange[0], this.dateRange[1])
        );
        
        await Promise.all(promises);
        this.updateChart();
      } catch (error) {
        this.$message.error('加载行情数据失败');
        console.error('加载行情失败:', error);
      } finally {
        this.loading = false;
      }
    },
    
    // 获取单个资产的K线数据
    async fetchAssetKline(assetCode, startDate, endDate) {
      try {
        // 将日期转换为 datetime 格式（后端要求）
        const formatDateTime = (date) => {
          return dayjs(date).format('YYYY-MM-DD') + 'T00:00:00';
        };
        
        const response = await request({
          url: `/api/v1/assets/${assetCode}/kline`,
          method: 'get',
          params: {
            start_date: formatDateTime(startDate),
            end_date: formatDateTime(endDate)
          }
        });
        
        const data = Array.isArray(response) ? response : (response.data || []);
        this.quoteData[assetCode] = data;
      } catch (error) {
        console.error(`获取${assetCode}行情失败:`, error);
        throw error;
      }
    },
    
    // 初始化图表
    initChart() {
      this.chartInstance = echarts.init(this.$refs.chartContainer);
      this.updateChart();
    },
    
    // 更新图表
    updateChart() {
      if (!this.chartInstance) return;
      
      if (this.selectedAssets.length === 0) {
        this.chartInstance.clear();
        return;
      }
      
      const option = this.chartType === 'candlestick' 
        ? this.getCandlestickOption() 
        : this.getLineOption();
      
      this.chartInstance.setOption(option, true);
    },
    
    // 折线图配置
    getLineOption() {
      const series = this.selectedAssets.map((code, index) => {
        const data = this.quoteData[code] || [];
        return {
          name: this.getAssetName(code),
          type: 'line',
          data: data.map(item => {
            // 只保留日期部分，去掉时间
            const dateStr = item.date.split('T')[0];
            return [dateStr, item.close];
          }),
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: {
            width: 2
          }
        };
      });
      
      return {
        title: {
          text: '资产行情走势',
          left: 'center'
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: function(params) {
            if (!params || params.length === 0) return '';
            let result = `日期: ${params[0].name}<br/>`;
            params.forEach(param => {
              result += `${param.seriesName}: ${param.data[1]}<br/>`;
            });
            return result;
          }
        },
        legend: {
          data: this.selectedAssets.map(code => this.getAssetName(code)),
          top: 30
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          axisLabel: {
            formatter: function(value) {
              return value; // 直接显示日期字符串
            }
          }
        },
        yAxis: {
          type: 'value',
          scale: true
        },
        dataZoom: [
          {
            type: 'inside',
            start: 0,
            end: 100
          },
          {
            show: true,
            type: 'slider',
            top: '90%',
            start: 0,
            end: 100
          }
        ],
        series: series
      };
    },
    
    // K线图配置
    getCandlestickOption() {
      const assetCount = this.selectedAssets.length;
      
      // 计算每个子图的高度分配
      const gridHeight = 70 / assetCount; // 总高度70%，平均分配
      const gridGap = 5; // 子图间隙
      
      // 构建 grids、xAxis、yAxis 和 series
      const grids = [];
      const xAxes = [];
      const yAxes = [];
      const series = [];
      const legends = [];
      
      // 获取所有日期的并集（用于统一X轴）
      const allDates = new Set();
      this.selectedAssets.forEach(code => {
        const data = this.quoteData[code] || [];
        data.forEach(item => allDates.add(item.date.split('T')[0])); // 只取日期部分
      });
      const dateArray = Array.from(allDates).sort();
      
      this.selectedAssets.forEach((code, index) => {
        const data = this.quoteData[code] || [];
        const topPos = index * (gridHeight + gridGap);
        
        // 构建该资产的K线数据，对齐到统一的日期轴
        const dataMap = {};
        data.forEach(item => {
          const dateStr = item.date.split('T')[0]; // 只保留日期
          dataMap[dateStr] = [item.open, item.close, item.low, item.high];
        });
        
        const values = dateArray.map(date => dataMap[date] || ['-', '-', '-', '-']);
        
        // 添加 grid
        grids.push({
          left: '10%',
          right: '10%',
          top: `${topPos + 8}%`,
          height: `${gridHeight - 3}%`
        });
        
        // 添加 xAxis
        xAxes.push({
          type: 'category',
          gridIndex: index,
          data: dateArray,
          boundaryGap: true,
          axisLine: { onZero: false },
          splitLine: { show: false },
          axisLabel: {
            show: index === assetCount - 1, // 只在最后一个子图显示X轴标签
            formatter: function(value) {
              return value; // 直接显示日期字符串
            }
          },
          axisTick: {
            show: index === assetCount - 1
          }
        });
        
        // 添加 yAxis
        yAxes.push({
          scale: true,
          gridIndex: index,
          splitArea: {
            show: true
          },
          axisLabel: {
            formatter: '{value}'
          }
        });
        
        // 添加 series
        series.push({
          name: this.getAssetName(code),
          type: 'candlestick',
          xAxisIndex: index,
          yAxisIndex: index,
          data: values,
          itemStyle: {
            color: '#ef232a',
            color0: '#14b143',
            borderColor: '#ef232a',
            borderColor0: '#14b143'
          }
        });
        
        // 添加图例
        legends.push(this.getAssetName(code));
      });
      
      return {
        title: {
          text: 'K线图对比',
          left: 'center'
        },
        legend: {
          data: legends,
          top: 30,
          selected: legends.reduce((acc, name) => {
            acc[name] = true;
            return acc;
          }, {})
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross',
            link: [{xAxisIndex: 'all'}]
          },
          formatter: function(params) {
            if (!params || params.length === 0) return '';
            let result = `日期: ${params[0].name}<br/>`;
            params.forEach(param => {
              if (param.data && param.data[0] !== '-') {
                result += `${param.seriesName}<br/>`;
                result += `  开盘: ${param.data[1]}<br/>`;
                result += `  收盘: ${param.data[2]}<br/>`;
                result += `  最低: ${param.data[3]}<br/>`;
                result += `  最高: ${param.data[4]}<br/>`;
              }
            });
            return result;
          }
        },
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        dataZoom: [
          {
            type: 'inside',
            xAxisIndex: Array.from({length: assetCount}, (_, i) => i),
            start: 0,
            end: 100
          },
          {
            show: true,
            type: 'slider',
            xAxisIndex: Array.from({length: assetCount}, (_, i) => i),
            top: '92%',
            start: 0,
            end: 100
          }
        ],
        series: series
      };
    },
    
    // 获取资产名称
    getAssetName(code) {
      const asset = this.assetOptions.find(a => a.code === code);
      return asset ? `${asset.code} ${asset.name}` : code;
    },
    
    // 窗口大小变化
    handleResize() {
      if (this.chartInstance) {
        this.chartInstance.resize();
      }
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}

.page-header {
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #303133;
  margin: 0;
}

.page-content {
  background: #f5f7fa;
}

.select-card {
  margin-bottom: 20px;
}

.select-section {
  margin-bottom: 15px;
}

.selected-tags {
  padding-top: 15px;
  border-top: 1px solid #ebeef5;
}

.chart-card {
  margin-bottom: 20px;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.chart-header h3 {
  margin: 0;
  font-size: 16px;
  color: #303133;
}

.chart-container {
  width: 100%;
  height: 500px;
}
</style>
