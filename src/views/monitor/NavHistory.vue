<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">净值走势</h2>
      <div>
        <el-button @click="$router.back()">返回</el-button>
        <el-button type="primary" icon="el-icon-refresh" @click="loadData" :loading="loading">刷新</el-button>
        <el-button type="success" icon="el-icon-download" @click="handleExport">导出数据</el-button>
      </div>
    </div>

    <div class="page-content" v-loading="loading">
      <!-- 时间范围选择器 -->
      <el-card shadow="never" class="filter-card">
        <el-form :inline="true" size="small">
          <el-form-item label="选择周期">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              @change="handleDateChange"
            ></el-date-picker>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 统计信息 -->
      <el-row :gutter="20" style="margin-top: 20px;">
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">区间收益率</div>
            <div class="stat-value" :style="{ color: getReturnColor(statistics.periodReturn) }">
              {{ formatPercent(statistics.periodReturn) }}
            </div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">年化收益率</div>
            <div class="stat-value" :style="{ color: getReturnColor(statistics.annualReturn) }">
              {{ formatPercent(statistics.annualReturn) }}
            </div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">年化波动率</div>
            <div class="stat-value">{{ formatPercent(statistics.annualVolatility) }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">最大回撤</div>
            <div class="stat-value" style="color: #67C23A;">
              {{ formatPercent(statistics.maxDrawdown) }}
            </div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">夏普比率</div>
            <div class="stat-value">{{ formatNumber(statistics.sharpeRatio, 3) }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">数据天数</div>
            <div class="stat-value">{{ navHistory.length }}</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 净值曲线图（主图） -->
      <el-card shadow="never" class="info-card" style="margin-top: 20px;">
        <div slot="header" class="card-header">
          <span>净值与日收益率走势</span>
        </div>
        <div ref="mainChart" style="width: 100%; height: 500px;"></div>
        <el-empty v-if="navHistory.length === 0" description="暂无净值数据"></el-empty>
      </el-card>

      <!-- 当日损益归因图 -->
      <el-card shadow="never" class="info-card" style="margin-top: 20px;">
        <div slot="header" class="card-header">
          <span>当日损益归因</span>
          <span v-if="latestDate" style="color: #909399; font-size: 13px; font-weight: normal;">
            {{ latestDate }}
          </span>
        </div>
        <div v-if="attributionData.length > 0" ref="attributionChart" style="width: 100%; height: 350px;"></div>
        <div v-else class="attribution-placeholder">
          <el-empty description="损益归因需要市场数据接口支持">
            <template slot="description">
              <p style="color: #909399; margin-bottom: 5px;">待完整数据接口支持</p>
              <p style="color: #c0c4cc; font-size: 12px;">需要各资产日价格数据计算收益贡献</p>
            </template>
          </el-empty>
        </div>
        <div v-if="attributionData.length > 0" class="attribution-summary">
          <span>合计贡献: {{ formatNumber(totalContribution, 4) }}</span>
          <span style="margin-left: 20px;">实际净值变动: {{ formatNumber(actualNavChange, 4) }}</span>
          <span style="margin-left: 20px;">差异: {{ formatNumber(attributionDiff, 4) }}</span>
        </div>
      </el-card>

      <!-- 每日收益统计表 -->
      <el-card shadow="never" class="info-card" style="margin-top: 20px;">
        <div slot="header" class="card-header">
          <span>每日收益统计</span>
          <el-select v-model="returnsDisplayDays" size="small" style="width: 100px;" @change="updateReturnsTable">
            <el-option label="近10日" :value="10"></el-option>
            <el-option label="近20日" :value="20"></el-option>
            <el-option label="近30日" :value="30"></el-option>
            <el-option label="近60日" :value="60"></el-option>
          </el-select>
        </div>
        <el-table
          v-if="returnsTableData.length > 0"
          :data="returnsTableData"
          border
          stripe
          style="width: 100%;"
          size="small"
        >
          <el-table-column prop="date" label="日期" width="110" align="center"></el-table-column>
          <el-table-column prop="nav" label="净值" width="100" align="right">
            <template slot-scope="scope">
              {{ formatNumber(scope.row.nav, 4) }}
            </template>
          </el-table-column>
          <el-table-column prop="dailyPnL" label="日收益额" width="100" align="right">
            <template slot-scope="scope">
              <span :style="{ color: getReturnColor(scope.row.dailyPnL) }">
                {{ formatSignedNumber(scope.row.dailyPnL, 4) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="dailyReturnPct" label="日收益率(%)" width="120" align="right">
            <template slot-scope="scope">
              <span :style="{ color: getReturnColor(scope.row.dailyReturnPct) }">
                {{ formatSignedPercent(scope.row.dailyReturnPct) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="cumulativeReturnPct" label="累计收益率(%)" width="130" align="right">
            <template slot-scope="scope">
              <span :style="{ color: getReturnColor(scope.row.cumulativeReturnPct) }">
                {{ formatSignedPercent(scope.row.cumulativeReturnPct) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无收益数据"></el-empty>
      </el-card>

      <!-- 净值数据表格 -->
      <el-card shadow="never" class="info-card" style="margin-top: 20px;">
        <div slot="header" class="card-header">
          <span>净值数据明细</span>
          <span style="color: #909399; font-size: 13px; font-weight: normal;">
            共 {{ navHistory.length }} 条记录
          </span>
        </div>
        <el-table
          :data="paginatedData"
          border
          stripe
          style="width: 100%;"
          :default-sort="{ prop: 'date', order: 'descending' }"
        >
          <el-table-column prop="date" label="日期" width="120" sortable></el-table-column>
          <el-table-column prop="nav" label="净值" width="120" align="right">
            <template slot-scope="scope">
              {{ scope.row.nav ? scope.row.nav.toFixed(4) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="daily_return" label="日收益率" width="120" align="right">
            <template slot-scope="scope">
              <span :style="{ color: getReturnColor(scope.row.daily_return) }">
                {{ scope.row.daily_return !== null && scope.row.daily_return !== undefined 
                   ? (scope.row.daily_return * 100).toFixed(4) + '%' 
                   : '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="cumulative_return" label="累计收益率" width="130" align="right">
            <template slot-scope="scope">
              <span :style="{ color: getReturnColor(scope.row.cumulative_return) }">
                {{ scope.row.cumulative_return !== null && scope.row.cumulative_return !== undefined 
                   ? (scope.row.cumulative_return * 100).toFixed(2) + '%' 
                   : '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="drawdown" label="回撤" width="120" align="right">
            <template slot-scope="scope">
              <span style="color: #67C23A;">
                {{ scope.row.drawdown !== null && scope.row.drawdown !== undefined 
                   ? (scope.row.drawdown * 100).toFixed(2) + '%' 
                   : '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="is_rebalance" label="调仓日" width="100" align="center">
            <template slot-scope="scope">
              <el-tag v-if="scope.row.is_rebalance" type="warning" size="mini">调仓</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          style="margin-top: 20px; text-align: right;"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
          :current-page="currentPage"
          :page-sizes="[20, 50, 100, 200]"
          :page-size="pageSize"
          layout="total, sizes, prev, pager, next, jumper"
          :total="navHistory.length"
        ></el-pagination>
      </el-card>
    </div>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import * as echarts from 'echarts';
import { mapState, mapActions, mapGetters } from 'vuex';

export default {
  name: 'MonitorNavHistory',
  data() {
    return {
      loading: false,
      dateRange: [],
      currentPage: 1,
      pageSize: 50,
      mainChart: null,
      attributionChart: null,
      returnsDisplayDays: 20,
      // 损益归因数据（简化版，从持仓数据计算）
      attributionData: [],
      totalContribution: 0,
      actualNavChange: 0
    };
  },
  computed: {
    ...mapState('monitor', ['navHistory', 'positions', 'monitorState']),
    // 最新日期
    latestDate() {
      if (this.navHistory && this.navHistory.length > 0) {
        return this.navHistory[this.navHistory.length - 1].date;
      }
      return null;
    },
    // 归因差异
    attributionDiff() {
      return this.actualNavChange - this.totalContribution;
    },
    // 每日收益表格数据
    returnsTableData() {
      if (!this.navHistory || this.navHistory.length < 2) return [];
      const n = Math.min(this.returnsDisplayDays + 1, this.navHistory.length);
      const recentData = this.navHistory.slice(-n);
      const baseNav = recentData[0].nav;
      const result = [];
      for (let i = 1; i < recentData.length; i++) {
        const prev = recentData[i - 1];
        const curr = recentData[i];
        const dailyPnL = curr.nav - prev.nav;
        const dailyReturnPct = (curr.nav / prev.nav - 1) * 100;
        const cumulativeReturnPct = (curr.nav / baseNav - 1) * 100;
        result.push({
          date: curr.date,
          nav: curr.nav,
          dailyPnL: dailyPnL,
          dailyReturnPct: dailyReturnPct,
          cumulativeReturnPct: cumulativeReturnPct
        });
      }
      // 最新在前
      return result.reverse();
    },
    paginatedData() {
      const start = (this.currentPage - 1) * this.pageSize;
      const end = start + this.pageSize;
      // 按日期倒序排序
      const sorted = [...this.navHistory].sort((a, b) => {
        return new Date(b.date) - new Date(a.date);
      });
      return sorted.slice(start, end);
    },
    statistics() {
      if (this.navHistory.length < 2) {
        return {
          periodReturn: null,
          annualReturn: null,
          annualVolatility: null,
          maxDrawdown: null,
          sharpeRatio: null
        };
      }

      const data = this.navHistory;
      const firstNav = (data[0] && data[0].nav) ? data[0].nav : 1;
      const lastNav = (data[data.length - 1] && data[data.length - 1].nav) ? data[data.length - 1].nav : 1;
      
      // 区间收益率
      const periodReturn = (lastNav / firstNav) - 1;
      
      // 计算日收益率
      const dailyReturns = data
        .filter(d => d.daily_return !== null && d.daily_return !== undefined)
        .map(d => d.daily_return);
      
      // 空数组防护
      if (dailyReturns.length === 0) {
        return {
          periodReturn,
          annualReturn: null,
          annualVolatility: null,
          maxDrawdown: null,
          sharpeRatio: null
        };
      }
      
      // 年化收益率（简单计算）
      const days = data.length;
      const annualReturn = Math.pow(lastNav / firstNav, 252 / days) - 1;
      
      // 年化波动率
      const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
      const variance = dailyReturns.reduce((sum, r) => sum + Math.pow(r - mean, 2), 0) / dailyReturns.length;
      const annualVolatility = Math.sqrt(variance * 252);
      
      // 最大回撤
      let maxDrawdown = 0;
      let peak = firstNav;
      for (const item of data) {
        if (item.nav > peak) peak = item.nav;
        const drawdown = (item.nav - peak) / peak;
        if (drawdown < maxDrawdown) maxDrawdown = drawdown;
      }
      
      // 夏普比率
      const sharpeRatio = annualVolatility > 0 ? annualReturn / annualVolatility : 0;

      return {
        periodReturn,
        annualReturn,
        annualVolatility,
        maxDrawdown,
        sharpeRatio
      };
    }
  },
  mounted() {
    this.loadData();
    window.addEventListener('resize', this.handleResize);
  },
  beforeDestroy() {
    if (this.mainChart) {
      this.mainChart.dispose();
    }
    if (this.attributionChart) {
      this.attributionChart.dispose();
    }
    window.removeEventListener('resize', this.handleResize);
  },
  methods: {
    ...mapActions('monitor', ['fetchNavHistory', 'fetchPositions']),
    async loadData() {
      this.loading = true;
      try {
        const params = this.getDateRangeParams();
        await Promise.all([
          this.fetchNavHistory(params),
          this.fetchPositions()
        ]);
        this.computeAttribution();
        this.$nextTick(() => {
          this.initChart();
          this.renderMainChart();
          this.renderAttributionChart();
        });
      } catch (error) {
        this.$message.error('加载数据失败：' + ((error.response && error.response.data && error.response.data.message) ? error.response.data.message : error.message));
      } finally {
        this.loading = false;
      }
    },
    getDateRangeParams() {
      // 如果用户选择了日期范围，使用用户选择的范围
      if (this.dateRange && this.dateRange.length === 2) {
        return { start: this.dateRange[0], end: this.dateRange[1] };
      }
      // 默认返回全部数据（不限制时间范围）
      return { start: '', end: '' };
    },
    handleDateChange() {
      if (this.dateRange && this.dateRange.length === 2) {
        this.loadData();
      }
    },
    initChart() {
      if (!this.mainChart && this.$refs.mainChart) {
        this.mainChart = echarts.init(this.$refs.mainChart);
      }
    },
    renderMainChart() {
      if (!this.mainChart || this.navHistory.length === 0) {
        return;
      }

      const dates = this.navHistory.map(item => item.date);
      const navValues = this.navHistory.map(item => item.nav);
      const dailyReturns = this.navHistory.map(item => 
        item.daily_return !== null && item.daily_return !== undefined 
          ? (item.daily_return * 100) 
          : 0
      );
      
      // 找出调仓日标记点
      const markPoints = this.navHistory
        .filter(item => item.is_rebalance)
        .map(item => ({
          coord: [item.date, item.nav],
          name: '调仓',
          value: '调仓日'
        }));

      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: (params) => {
            let result = `${params[0].axisValue}<br/>`;
            params.forEach(param => {
              if (param.seriesName === '净值') {
                result += `${param.marker}净值: ${param.data.toFixed(4)}<br/>`;
              } else if (param.seriesName === '日收益率') {
                const color = param.data >= 0 ? '#F56C6C' : '#67C23A';
                result += `${param.marker}日收益率: <span style="color:${color}">${param.data.toFixed(4)}%</span><br/>`;
              }
            });
            return result;
          }
        },
        legend: {
          data: ['净值', '日收益率'],
          top: 10
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '80px',
          containLabel: true
        },
        dataZoom: [
          {
            type: 'inside',
            start: 0,
            end: 100
          },
          {
            type: 'slider',
            start: 0,
            end: 100,
            bottom: 20
          }
        ],
        xAxis: {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLabel: {
            formatter: (value) => dayjs(value).format('MM-DD')
          }
        },
        yAxis: [
          {
            type: 'value',
            name: '净值',
            position: 'left',
            scale: true,
            axisLabel: {
              formatter: '{value}'
            }
          },
          {
            type: 'value',
            name: '日收益率(%)',
            position: 'right',
            axisLabel: {
              formatter: '{value}%'
            }
          }
        ],
        series: [
          {
            name: '净值',
            type: 'line',
            data: navValues,
            smooth: true,
            symbol: 'none',
            yAxisIndex: 0,
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
                  { offset: 0, color: 'rgba(64, 158, 255, 0.2)' },
                  { offset: 1, color: 'rgba(64, 158, 255, 0.02)' }
                ]
              }
            },
            markPoint: {
              symbol: 'pin',
              symbolSize: 30,
              data: markPoints,
              itemStyle: {
                color: '#E6A23C'
              }
            }
          },
          {
            name: '日收益率',
            type: 'bar',
            data: dailyReturns,
            yAxisIndex: 1,
            itemStyle: {
              color: (params) => {
                return params.data >= 0 ? '#F56C6C' : '#67C23A';
              }
            }
          }
        ]
      };

      this.mainChart.setOption(option, true);
    },
    handleResize() {
      if (this.mainChart) {
        this.mainChart.resize();
      }
      if (this.attributionChart) {
        this.attributionChart.resize();
      }
    },
    // 计算损益归因（简化版，基于持仓权重估算）
    computeAttribution() {
      // 简化版损益归因：如果有持仓数据且有日收益率，估算各资产贡献
      // 注：这是简化实现，真实归因需要各资产日价格数据
      if (!this.positions || this.positions.length === 0) {
        this.attributionData = [];
        return;
      }
      if (!this.navHistory || this.navHistory.length < 2) {
        this.attributionData = [];
        return;
      }
      
      const latestNav = this.navHistory[this.navHistory.length - 1].nav;
      const prevNav = this.navHistory[this.navHistory.length - 2].nav;
      this.actualNavChange = latestNav - prevNav;
      const dailyReturn = latestNav / prevNav - 1;
      
      // 简化归因：假设各资产收益与整体收益率相同（这是一个粗略估计）
      // 真实归因需要各资产的实际日收益率
      const attribution = [];
      let total = 0;
      for (const pos of this.positions) {
        if (Math.abs(pos.weight) < 0.0001) continue;
        // 估算贡献 = 权重 × 日收益率 × 净值
        const contribution = pos.weight * dailyReturn * prevNav;
        attribution.push({
          asset: pos.asset,
          weight: pos.weight,
          contribution: contribution
        });
        total += contribution;
      }
      // 按贡献绝对值排序
      attribution.sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
      this.attributionData = attribution;
      this.totalContribution = total;
    },
    // 渲染损益归因图
    renderAttributionChart() {
      if (!this.$refs.attributionChart || this.attributionData.length === 0) {
        return;
      }
      if (!this.attributionChart) {
        this.attributionChart = echarts.init(this.$refs.attributionChart);
      }
      
      const assets = this.attributionData.map(d => d.asset);
      const contributions = this.attributionData.map(d => d.contribution);
      const colors = contributions.map(c => c >= 0 ? '#00a651' : '#d62728');
      
      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params) => {
            const data = params[0];
            const idx = data.dataIndex;
            const item = this.attributionData[idx];
            return `${item.asset}<br/>权重: ${(item.weight * 100).toFixed(2)}%<br/>收益贡献: ${item.contribution >= 0 ? '+' : ''}${item.contribution.toFixed(4)}`;
          }
        },
        grid: {
          left: '100px',
          right: '80px',
          top: '20px',
          bottom: '20px'
        },
        xAxis: {
          type: 'value',
          name: '收益贡献',
          axisLabel: {
            formatter: '{value}'
          }
        },
        yAxis: {
          type: 'category',
          data: assets,
          inverse: true,
          axisLabel: {
            fontSize: 11
          }
        },
        series: [{
          name: '收益贡献',
          type: 'bar',
          data: contributions.map((c, i) => ({
            value: c,
            itemStyle: { color: colors[i] }
          })),
          label: {
            show: true,
            position: 'right',
            formatter: (params) => {
              const v = params.value;
              return v >= 0 ? '+' + v.toFixed(4) : v.toFixed(4);
            },
            fontSize: 10
          }
        }]
      };
      this.attributionChart.setOption(option, true);
    },
    // 更新收益表格
    updateReturnsTable() {
      // 计算属性会自动响应
    },
    handleSizeChange(size) {
      this.pageSize = size;
      this.currentPage = 1;
    },
    handleCurrentChange(page) {
      this.currentPage = page;
    },
    handleExport() {
      if (this.navHistory.length === 0) {
        this.$message.warning('暂无数据可导出');
        return;
      }
      
      // 简单导出为CSV
      const headers = ['日期', '净值', '日收益率', '累计收益率', '回撤', '调仓日'];
      const rows = this.navHistory.map(item => [
        item.date,
        (item.nav !== null && item.nav !== undefined) ? item.nav.toFixed(4) : '',
        item.daily_return !== null ? (item.daily_return * 100).toFixed(4) + '%' : '',
        item.cumulative_return !== null ? (item.cumulative_return * 100).toFixed(2) + '%' : '',
        item.drawdown !== null ? (item.drawdown * 100).toFixed(2) + '%' : '',
        item.is_rebalance ? '是' : ''
      ]);
      
      const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
      const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `净值数据_${dayjs().format('YYYYMMDD')}.csv`;
      link.click();
      
      this.$message.success('导出成功');
    },
    formatNumber(num, decimals = 2) {
      if (num === null || num === undefined || Number.isNaN(num)) return '-';
      return num.toFixed(decimals);
    },
    formatSignedNumber(num, decimals = 2) {
      if (num === null || num === undefined || Number.isNaN(num)) return '-';
      const sign = num >= 0 ? '+' : '';
      return sign + num.toFixed(decimals);
    },
    formatPercent(num) {
      if (num === null || num === undefined || Number.isNaN(num)) return '-';
      return (num * 100).toFixed(2) + '%';
    },
    formatSignedPercent(num) {
      if (num === null || num === undefined || Number.isNaN(num)) return '-';
      const sign = num >= 0 ? '+' : '';
      return sign + num.toFixed(3) + '%';
    },
    getReturnColor(value) {
      if (value === null || value === undefined) return '#909399';
      if (value > 0) return '#F56C6C';
      if (value < 0) return '#67C23A';
      return '#909399';
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

.filter-card {
  margin-bottom: 0;
}

.stat-card {
  text-align: center;
  padding: 15px 10px;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.stat-value {
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

.attribution-placeholder {
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.attribution-summary {
  margin-top: 15px;
  padding: 10px 15px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
  color: #606266;
}
</style>
