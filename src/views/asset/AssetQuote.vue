<template>
  <div :class="{'asset-quote-container': !isDialog}">
    <el-card class="filter-card">
      <el-form :inline="true" :model="filterForm" size="small">
        <el-form-item label="选择资产">
          <el-select 
            v-model="selectedAsset" 
            filterable 
            placeholder="请选择资产" 
            @change="handleAssetChange"
            style="width: 250px"
          >
            <el-option
              v-for="item in assetOptions"
              :key="item.code"
              :label="`${item.name} (${item.code})`"
              :value="item.code"
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
            value-format="yyyy-MM-dd"
            @change="handleDateChange"
          >
          </el-date-picker>
        </el-form-item>
        <el-form-item label="价格精度">
          <el-select v-model="pricePrecision" placeholder="请选择" style="width: 120px">
            <el-option label="2位" :value="2"></el-option>
            <el-option label="4位" :value="4"></el-option>
            <el-option label="6位" :value="6"></el-option>
            <el-option label="8位" :value="8"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="el-icon-search" @click="fetchData">查询</el-button>
          <el-button type="success" icon="el-icon-refresh" @click="handleSyncToday">同步行情</el-button>
          <el-button icon="el-icon-download" @click="handleDownloadPriceTemplate">下载行情模板</el-button>
          <el-upload
            ref="priceUpload"
            action=""
            :auto-upload="false"
            :show-file-list="false"
            :on-change="handlePriceFileChange"
            accept=".xlsx,.xls"
            style="display: inline-block; margin-left: 10px;"
          >
            <el-button icon="el-icon-upload2">批量导入行情</el-button>
          </el-upload>
        </el-form-item>
      </el-form>
    </el-card>

    <el-tabs v-model="activeTab" style="margin-top: 20px;" type="border-card">
      <el-tab-pane label="K线图" name="chart">
        <div ref="klineChart" style="width: 100%; height: 500px;" v-loading="loading"></div>
      </el-tab-pane>
      <el-tab-pane label="行情明细" name="table">
        <vxe-table
          border
          stripe
          height="500"
          :loading="loading"
          :data="quoteData"
          :scroll-y="{enabled: true, gt: 0}"
          show-overflow
        >
          <vxe-column field="date" title="日期" sortable width="150"></vxe-column>
          <vxe-column field="open" title="开盘价" width="120">
            <template #default="{ row }">
              {{ row.open != null ? formatPrice(row.open) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="high" title="最高价" width="120">
            <template #default="{ row }">
              {{ row.high != null ? formatPrice(row.high) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="low" title="最低价" width="120">
            <template #default="{ row }">
              {{ row.low != null ? formatPrice(row.low) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="close" title="收盘价" width="120">
            <template #default="{ row }">
              <span :class="getPriceClass(row)">
                {{ row.close != null ? formatPrice(row.close) : '-' }}
              </span>
            </template>
          </vxe-column>
          <vxe-column field="volume" title="成交量" width="150">
            <template #default="{ row }">
              {{ row.volume != null ? formatVolume(row.volume) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="amount" title="成交额" width="150">
            <template #default="{ row }">
              {{ row.amount != null ? formatAmount(row.amount) : '-' }}
            </template>
          </vxe-column>
        </vxe-table>
      </el-tab-pane>
    </el-tabs>

    <sync-progress-dialog ref="syncProgressDialog" @sync-success="handleSyncSuccess" />
  </div>
</template>

<script>
import { getAssetOptions, getAssetKline } from '@/api/asset';
import { downloadPriceTemplate, importPricesFromExcel } from '@/api/asset';
import SyncProgressDialog from '@/components/SyncProgressDialog.vue';
import * as echarts from 'echarts';

export default {
  name: 'AssetQuote',
  components: { SyncProgressDialog },
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    assetCode: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      selectedAsset: '',
      assetOptions: [],
      dateRange: [],
      filterForm: {},
      activeTab: 'chart',
      loading: false,
      quoteData: [],
      chartInstance: null,
      pricePrecision: 2  // 价格精度，默认2位小数
    };
  },
  mounted() {
    this.initDateRange();
    this.fetchAssetOptions();
  },
  watch: {
    assetCode(newVal) {
      if (this.isDialog && newVal) {
        this.selectedAsset = newVal;
        this.fetchData();
      }
    },
    activeTab(val) {
      if (val === 'chart') {
        this.$nextTick(() => {
          if (this.chartInstance) {
            this.chartInstance.resize();
          }
        });
      }
    }
  },
  methods: {
    initDateRange() {
      const end = new Date();
      const start = new Date();
      start.setMonth(start.getMonth() - 6); // 默认看半年
      this.dateRange = [this.formatDate(start), this.formatDate(end)];
    },
    formatDate(date) {
      const y = date.getFullYear();
      let m = date.getMonth() + 1;
      m = m < 10 ? '0' + m : m;
      let d = date.getDate();
      d = d < 10 ? '0' + d : d;
      return `${y}-${m}-${d}`;
    },
    async fetchAssetOptions() {
      try {
        const res = await getAssetOptions();
        this.assetOptions = res.data || res;
        
        // 优先使用 props 的 assetCode
        if (this.isDialog && this.assetCode) {
          this.selectedAsset = this.assetCode;
        } else {
          // 优先从路由参数获取 code，否则默认选第一个
          const queryCode = this.$route.query.code;
          if (queryCode && this.assetOptions.some(item => item.code === queryCode)) {
            this.selectedAsset = queryCode;
          } else if (this.assetOptions.length > 0) {
            this.selectedAsset = this.assetOptions[0].code;
          }
        }
        
        if (this.selectedAsset) {
          this.fetchData();
        }
      } catch (error) {
        this.$message.error('获取资产列表失败');
      }
    },
    handleAssetChange() {
      this.fetchData();
    },
    handleDateChange() {
      this.fetchData();
    },
    handleSyncToday() {
      this.$refs.syncProgressDialog.openSyncToday();
    },
    handleSyncSuccess() {
      this.fetchData();
    },
    async fetchData() {
      if (!this.selectedAsset) return;
      this.loading = true;
      try {
        const params = {
          start_date: this.dateRange ? this.dateRange[0] : '',
          end_date: this.dateRange ? this.dateRange[1] : ''
        };
        const res = await getAssetKline(this.selectedAsset, params);
        const rawData = res.data || res;
        
        // 数据标准化：如果缺少 open/high/low，用 close 填充
        this.quoteData = rawData.map(item => ({
          date: item.date,
          open: item.open ?? item.close ?? 0,
          high: item.high ?? item.close ?? 0,
          low: item.low ?? item.close ?? 0,
          close: item.close ?? 0,
          volume: item.volume ?? 0,
          amount: item.amount ?? 0
        }));
        
        this.renderChart();
      } catch (error) {
        this.$message.error('获取行情数据失败');
      } finally {
        this.loading = false;
      }
    },
    renderChart() {
      this.$nextTick(() => {
        if (!this.$refs.klineChart) return;
        
        if (!this.chartInstance) {
          this.chartInstance = echarts.init(this.$refs.klineChart);
        }

        if (this.quoteData.length === 0) {
          this.chartInstance.clear();
          this.chartInstance.setOption({
            title: {
              text: this.getAssetName(this.selectedAsset) + ' K线图',
              left: 0,
              subtext: '暂无数据',
              subtextStyle: { color: '#999' }
            },
            xAxis: { type: 'category', data: [] },
            yAxis: { type: 'value' },
            series: []
          });
          return;
        }

        const dates = this.quoteData.map(item => item.date);
        const closeData = this.quoteData.map(item => item.close);
        const klineData = this.quoteData.map(item => [item.open, item.close, item.low, item.high]);
        
        // 检测是否所有数据都只有收盘价（open=high=low=close）
        const hasOnlyClose = this.quoteData.every(item => 
          item.open === item.close && item.high === item.close && item.low === item.close
        );

        const quoteData = this.quoteData;
        const option = {
          title: {
            text: this.getAssetName(this.selectedAsset) + (hasOnlyClose ? ' 收盘价走势' : ' K线图'),
            left: 0
          },
          tooltip: {
            trigger: 'axis',
            axisPointer: {
              type: 'cross'
            },
            formatter: (params) => {
              if (!params || !params.length) return '';
              const idx = params[0].dataIndex;
              const row = quoteData[idx];
              if (!row) return params[0].name || '';
              const lines = [row.date || params[0].name];
              if (hasOnlyClose) {
                lines.push(`收盘: ${this.formatPrice(row.close)}`);
              } else {
                const o = row.open, c = row.close, h = row.high, l = row.low;
                lines.push(`开盘: ${this.formatPrice(o)}  收盘: ${this.formatPrice(c)}`);
                lines.push(`最高: ${this.formatPrice(h)}  最低: ${this.formatPrice(l)}`);
                if (o != null && o !== 0 && c != null) {
                  const pct = (((c - o) / o) * 100).toFixed(2);
                  lines.push(`涨跌幅: ${pct}%`);
                }
              }
              if (row.volume != null && row.volume !== 0) lines.push(`成交量: ${this.formatVolume(row.volume)}`);
              if (row.amount != null && row.amount !== 0) lines.push(`成交额: ${this.formatAmount(row.amount)}`);
              return lines.join('<br/>');
            }
          },
          grid: {
            left: '3%',
            right: '3%',
            bottom: '10%'
          },
          xAxis: {
            type: 'category',
            data: dates,
            scale: true,
            boundaryGap: hasOnlyClose ? false : true,
            axisLine: { onZero: false },
            splitLine: { show: false }
          },
          yAxis: {
            scale: true,
            splitArea: {
              show: true
            }
          },
          dataZoom: [
            {
              type: 'inside',
              start: 50,
              end: 100
            },
            {
              show: true,
              type: 'slider',
              top: '90%',
              start: 50,
              end: 100
            }
          ],
          series: hasOnlyClose ? [
            {
              name: '收盘',
              type: 'line',
              data: closeData,
              smooth: false,
              symbol: 'circle',
              symbolSize: 6,
              itemStyle: {
                color: '#5470c6'
              },
              lineStyle: {
                width: 2
              }
            }
          ] : [
            {
              name: '日K',
              type: 'candlestick',
              data: klineData,
              itemStyle: {
                color: '#ec0000',
                color0: '#00da3c',
                borderColor: '#8A0000',
                borderColor0: '#008F28'
              }
            }
          ],
          legend: {
            data: hasOnlyClose ? ['收盘'] : ['日K'],
            bottom: '2%'
          }
        };

        this.chartInstance.setOption(option, true);
      });
    },
    getAssetName(code) {
      const asset = this.assetOptions.find(item => item.code === code);
      return asset ? asset.name : code;
    },
    formatPrice(price) {
      if (price == null) return '-';
      return price.toFixed(this.pricePrecision);
    },
    getPriceClass(row) {
      if (row.close == null || row.open == null) return '';
      return row.close >= row.open ? 'price-up' : 'price-down';
    },
    formatVolume(v) {
      if (v == null || v === 0) return '-';
      if (v >= 100000000) return (v / 100000000).toFixed(2) + '亿';
      if (v >= 10000) return (v / 10000).toFixed(2) + '万';
      return v.toString();
    },
    formatAmount(v) {
      if (v == null || v === 0) return '-';
      const n = Number(v);
      if (n >= 100000000) return (n / 100000000).toFixed(2) + '亿';
      if (n >= 10000) return (n / 10000).toFixed(2) + '万';
      return n.toLocaleString();
    },
    // 下载行情导入模板
    async handleDownloadPriceTemplate() {
      try {
        const blob = await downloadPriceTemplate();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = '资产行情导入模板.xlsx';
        link.click();
        window.URL.revokeObjectURL(url);
        this.$message.success('模板下载成功');
      } catch (error) {
        this.$message.error('模板下载失败');
      }
    },
    // 处理行情文件选择
    async handlePriceFileChange(file) {
      if (!this.selectedAsset) {
        this.$message.warning('请先选择资产');
        return;
      }
      
      this.$confirm('是否覆盖已存在的行情数据？', '提示', {
        confirmButtonText: '覆盖',
        cancelButtonText: '仅新增',
        distinguishCancelAndClose: true,
        type: 'warning'
      }).then(async () => {
        await this.importPriceData(file.raw, true);
      }).catch((action) => {
        if (action === 'cancel') {
          this.importPriceData(file.raw, false);
        }
      });
    },
    // 导入行情数据
    async importPriceData(file, replaceExisting) {
      const loading = this.$loading({
        lock: true,
        text: '正在导入行情数据...',
        spinner: 'el-icon-loading'
      });
      
      try {
        const result = await importPricesFromExcel(this.selectedAsset, file, replaceExisting);
        const data = result.data || result;
        
        this.$message.success(
          `导入完成！成功: ${data.success_count || 0}条，失败: ${data.error_count || 0}条`
        );
        
        if (data.errors && data.errors.length > 0) {
          this.$alert(
            data.errors.slice(0, 10).join('\n') + (data.errors.length > 10 ? '\n...' : ''),
            '导入错误详情（最多显示10条）',
            {
              confirmButtonText: '确定',
              type: 'warning'
            }
          );
        }
        
        // 刷新行情数据
        this.fetchData();
      } catch (error) {
        const errorMsg = error.response?.data?.detail || error.message || '导入失败';
        this.$message.error('导入失败：' + errorMsg);
      } finally {
        loading.close();
        // 清空文件选择
        if (this.$refs.priceUpload) {
          this.$refs.priceUpload.clearFiles();
        }
      }
    }
  }
};
</script>

<style scoped>
.asset-quote-container {
  padding: 10px;
}
.price-up {
  color: #f56c6c;
}
.price-down {
  color: #67c23a;
}
</style>
