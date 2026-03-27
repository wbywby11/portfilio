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
        <el-form-item label="Excel仅导入日">
          <el-date-picker
            v-model="excelOnlyDate"
            type="date"
            value-format="yyyy-MM-dd"
            placeholder="不选则导入全部行"
            clearable
            style="width: 160px;"
          />
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

    <el-alert
      v-if="priceCoverage && priceCoverage.missing_dates && priceCoverage.missing_dates.length"
      type="warning"
      :closable="false"
      show-icon
      class="coverage-alert"
      style="margin-bottom: 16px;">
      <template slot="title">
        <span>区间内缺失 <strong>{{ priceCoverage.missing_dates.length }}</strong> 个交易日行情</span>
        <span class="coverage-meta">（日历：{{ priceCoverage.calendar_mode === 'trade_calendar' ? 'trade_dates.xlsx' : '工作日近似' }}）</span>
      </template>
      <div class="coverage-body">
        <span>应有交易日 {{ priceCoverage.expected_trade_days }} 天，库中已有 {{ priceCoverage.existing_days }} 天。</span>
        <span v-if="recentMissingDate" class="coverage-first">
          最近缺失：<el-button type="text" @click="applyMissingToManual(recentMissingDate)">{{ recentMissingDate }}</el-button>
        </span>
        <span v-if="priceCoverage.first_missing && priceCoverage.first_missing !== recentMissingDate" class="coverage-first">
          最早缺失：<el-button type="text" @click="applyMissingToManual(priceCoverage.first_missing)">{{ priceCoverage.first_missing }}</el-button>
        </span>
        <div class="coverage-dates">{{ missingDatesPreview }}</div>
      </div>
    </el-alert>

    <el-card v-if="selectedAsset" class="manual-import-card" shadow="never">
      <div slot="header" class="manual-import-header">
        <span>手动录入行情</span>
        <span class="manual-import-hint">收盘价必填；填写后开盘、最高、最低默认与收盘价一致，可单独修改。</span>
      </div>
      <el-form :inline="true" size="small" @submit.native.prevent="submitManualImport">
        <el-form-item label="日期">
          <el-date-picker
            v-model="manualForm.date"
            type="date"
            value-format="yyyy-MM-dd"
            placeholder="交易日"
            style="width: 150px;"
          />
        </el-form-item>
        <el-form-item label="收盘">
          <el-input-number
            v-model="manualForm.close"
            :precision="pricePrecision"
            :step="priceStep"
            :min="0"
            controls-position="right"
            class="manual-price-input"
            @change="onManualCloseChange"
          />
        </el-form-item>
        <el-form-item label="开盘">
          <el-input-number
            v-model="manualForm.open"
            :precision="pricePrecision"
            :step="priceStep"
            :min="0"
            controls-position="right"
            class="manual-price-input narrow"
            @change="markManualOpenEdited"
          />
        </el-form-item>
        <el-form-item label="最高">
          <el-input-number
            v-model="manualForm.high"
            :precision="pricePrecision"
            :step="priceStep"
            :min="0"
            controls-position="right"
            class="manual-price-input narrow"
            @change="markManualHighEdited"
          />
        </el-form-item>
        <el-form-item label="最低">
          <el-input-number
            v-model="manualForm.low"
            :precision="pricePrecision"
            :step="priceStep"
            :min="0"
            controls-position="right"
            class="manual-price-input narrow"
            @change="markManualLowEdited"
          />
        </el-form-item>
        <el-form-item label="成交量">
          <el-input-number
            v-model="manualForm.volume"
            :precision="0"
            :step="1"
            :min="0"
            controls-position="right"
            class="manual-vol-input"
          />
        </el-form-item>
        <el-form-item label="成交额">
          <el-input-number
            v-model="manualForm.amount"
            :precision="2"
            :step="0.01"
            :min="0"
            controls-position="right"
            class="manual-vol-input"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="manualSubmitting" @click="submitManualImport">保存该日行情</el-button>
          <el-button type="text" @click="setManualDateToday">设为今日</el-button>
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
import {
  downloadPriceTemplate,
  importPricesFromExcel,
  importPricesJson,
  getPriceCoverageGaps
} from '@/api/asset';
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
      pricePrecision: 2, // 价格精度，默认2位小数
      priceCoverage: null,
      excelOnlyDate: null,
      manualForm: {
        date: '',
        open: null,
        high: null,
        low: null,
        close: null,
        volume: null,
        amount: null
      },
      manualSubmitting: false,
      /** 用户是否曾单独改过开/高/低；改过则不再随收盘价联动 */
      manualOhlcEdited: {
        open: false,
        high: false,
        low: false
      }
    };
  },
  computed: {
    missingDatesPreview() {
      const m = this.priceCoverage && this.priceCoverage.missing_dates;
      if (!m || !m.length) return '';
      const head = m.slice(0, 12);
      const tail = m.length > 12 ? ` … 共 ${m.length} 天` : '';
      return head.join('、') + tail;
    },
    /** 与「价格精度」联动，便于输入小数 */
    priceStep() {
      const p = Number(this.pricePrecision);
      const prec = Number.isFinite(p) ? Math.min(Math.max(p, 0), 8) : 2;
      return Math.pow(10, -prec);
    },
    /** 区间内时间顺序最后一个缺失日（与后端 last_missing 一致；兼容旧接口无该字段时从 missing_dates 推算） */
    recentMissingDate() {
      const p = this.priceCoverage;
      if (!p || !p.missing_dates || !p.missing_dates.length) return null;
      return p.last_missing || p.missing_dates[p.missing_dates.length - 1];
    }
  },
  mounted() {
    this.initDateRange();
    this.fetchAssetOptions();
  },
  watch: {
    assetCode(newVal) {
      if (this.isDialog && newVal) {
        this.selectedAsset = newVal;
        this.manualForm.date = '';
        this.resetManualOhlcEdited();
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
    },
    'manualForm.date'(newVal, oldVal) {
      if (newVal === oldVal) return;
      this.resetManualOhlcEdited();
      this.$nextTick(() => this.syncOhlcFromClose());
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
      this.manualForm.date = '';
      this.resetManualOhlcEdited();
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
        await this.fetchCoverageGaps();
      } catch (error) {
        this.$message.error('获取行情数据失败');
      } finally {
        this.loading = false;
      }
    },
    async fetchCoverageGaps() {
      if (!this.selectedAsset || !this.dateRange || this.dateRange.length !== 2) {
        this.priceCoverage = null;
        return;
      }
      try {
        const res = await getPriceCoverageGaps({
          asset_code: this.selectedAsset,
          start_date: this.dateRange[0],
          end_date: this.dateRange[1]
        });
        const body = res.data !== undefined ? res.data : res;
        this.priceCoverage = body || null;
        // 默认日期：区间内按 trade_dates（或工作日近似）得到的缺失日中，时间最晚的一天
        if (body && body.missing_dates && body.missing_dates.length && !this.manualForm.date) {
          const last =
            body.last_missing ||
            body.missing_dates[body.missing_dates.length - 1];
          if (last) this.manualForm.date = last;
        }
      } catch (e) {
        this.priceCoverage = null;
      }
    },
    applyMissingToManual(d) {
      this.manualForm.date = d;
      this.$message.success('已填入手动录入日期：' + d);
    },
    setManualDateToday() {
      const t = new Date();
      const y = t.getFullYear();
      const m = String(t.getMonth() + 1).padStart(2, '0');
      const da = String(t.getDate()).padStart(2, '0');
      this.manualForm.date = `${y}-${m}-${da}`;
    },
    resetManualOhlcEdited() {
      this.manualOhlcEdited = { open: false, high: false, low: false };
    },
    markManualOpenEdited() {
      if (this._syncingOhlcFromClose) return;
      this.manualOhlcEdited.open = true;
    },
    markManualHighEdited() {
      if (this._syncingOhlcFromClose) return;
      this.manualOhlcEdited.high = true;
    },
    markManualLowEdited() {
      if (this._syncingOhlcFromClose) return;
      this.manualOhlcEdited.low = true;
    },
    /** 收盘价变化时：未单独编辑过的开/高/低与收盘价保持一致 */
    onManualCloseChange(val) {
      if (val === null || val === undefined || val === '' || Number.isNaN(Number(val))) {
        return;
      }
      const c = Number(val);
      if (!Number.isFinite(c)) return;
      this._syncingOhlcFromClose = true;
      try {
        if (!this.manualOhlcEdited.open) this.$set(this.manualForm, 'open', c);
        if (!this.manualOhlcEdited.high) this.$set(this.manualForm, 'high', c);
        if (!this.manualOhlcEdited.low) this.$set(this.manualForm, 'low', c);
      } finally {
        this.$nextTick(() => {
          this._syncingOhlcFromClose = false;
        });
      }
    },
    syncOhlcFromClose() {
      const c = this.manualForm.close;
      if (c === null || c === undefined || c === '' || Number.isNaN(Number(c))) return;
      const n = Number(c);
      if (!Number.isFinite(n)) return;
      this._syncingOhlcFromClose = true;
      try {
        if (!this.manualOhlcEdited.open) this.$set(this.manualForm, 'open', n);
        if (!this.manualOhlcEdited.high) this.$set(this.manualForm, 'high', n);
        if (!this.manualOhlcEdited.low) this.$set(this.manualForm, 'low', n);
      } finally {
        this.$nextTick(() => {
          this._syncingOhlcFromClose = false;
        });
      }
    },
    async submitManualImport() {
      if (!this.selectedAsset) {
        this.$message.warning('请先选择资产');
        return;
      }
      if (!this.manualForm.date) {
        this.$message.warning('请选择日期');
        return;
      }
      const c = this.manualForm.close;
      if (c === null || c === undefined || c === '' || Number.isNaN(Number(c))) {
        this.$message.warning('请填写收盘价');
        return;
      }
      const close = Number(c);
      if (!Number.isFinite(close)) {
        this.$message.warning('收盘价格式不正确');
        return;
      }
      let open = this.manualForm.open;
      let high = this.manualForm.high;
      let low = this.manualForm.low;
      if (open === null || open === undefined || open === '') open = close;
      if (high === null || high === undefined || high === '') high = Math.max(close, Number(open));
      if (low === null || low === undefined || low === '') low = Math.min(close, Number(open));
      open = Number(open);
      high = Number(high);
      low = Number(low);
      const row = {
        date: this.manualForm.date,
        open,
        high,
        low,
        close,
        volume: this.manualForm.volume !== null && this.manualForm.volume !== '' ? Number(this.manualForm.volume) : undefined,
        amount: this.manualForm.amount !== null && this.manualForm.amount !== '' ? Number(this.manualForm.amount) : undefined
      };
      this.manualSubmitting = true;
      try {
        await importPricesJson({
          asset_code: this.selectedAsset,
          replace_existing: false,
          prices: [row]
        });
        this.$message.success('已保存该日行情');
        this.resetManualOhlcEdited();
        this.manualForm.date = '';
        await this.fetchData();
      } catch (err) {
        const msg = (err.response && err.response.data && err.response.data.detail) || err.message || '保存失败';
        this.$message.error(String(msg));
      } finally {
        this.manualSubmitting = false;
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
        const result = await importPricesFromExcel(
          this.selectedAsset,
          file,
          replaceExisting,
          this.excelOnlyDate || null
        );
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
.coverage-alert .coverage-meta {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}
.coverage-body {
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}
.coverage-first {
  margin-left: 12px;
}
.coverage-dates {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  word-break: break-all;
}
.manual-import-card {
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}
.manual-import-header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
}
.manual-import-hint {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}
.manual-import-card .manual-price-input {
  width: 140px;
}
.manual-import-card .manual-price-input.narrow {
  width: 128px;
}
.manual-import-card .manual-vol-input {
  width: 140px;
}
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
