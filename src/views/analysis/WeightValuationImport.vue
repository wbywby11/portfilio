<template>
  <div class="weight-valuation-import">
    <el-card class="upload-card">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-upload2"></i> 权重与持仓估值数据导入</span>
      </div>
      <el-alert
        title="支持格式说明"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      >
        <p style="margin: 0 0 8px 0;">支持导入以下类型的 xlsx 文件（参考 daily_px.xlsx、fx.xlsx、trade_dates.xlsx、权重汇总.xlsx 等）：</p>
        <ul style="margin: 0; padding-left: 20px;">
          <li><strong>价格/净值</strong>：第一列为日期，其余列为资产价格或净值（如 daily_px、每日净值）</li>
          <li><strong>汇率</strong>：第一列为日期，其余列为汇率（如 fx.xlsx）</li>
          <li><strong>权重</strong>：第一列为日期，其余列为资产权重（如 权重汇总、调仓前权重）</li>
          <li><strong>交易日历</strong>：日期列（如 trade_dates.xlsx）</li>
        </ul>
      </el-alert>
      <el-upload
        ref="xlsxUpload"
        action=""
        :auto-upload="false"
        :show-file-list="true"
        :on-change="handleFileChange"
        :on-remove="handleFileRemove"
        accept=".xlsx,.xls"
        :limit="5"
      >
        <el-button slot="trigger" type="primary" icon="el-icon-upload2">选择 xlsx 文件</el-button>
        <div slot="tip" class="el-upload__tip">支持 .xlsx、.xls，可多选（最多5个）</div>
      </el-upload>
    </el-card>

    <template v-if="parsedSheets.length > 0">
      <el-card class="sheet-select-card">
        <div slot="header" class="clearfix">
          <span><i class="el-icon-document"></i> 选择工作表与可视化类型</span>
        </div>
        <el-form :inline="true" size="small">
          <el-form-item label="文件">
            <el-select v-model="selectedFileKey" placeholder="选择文件" @change="onFileChange" style="width: 200px;">
              <el-option
                v-for="item in parsedSheets"
                :key="item.fileKey"
                :label="item.fileName"
                :value="item.fileKey"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="工作表">
            <el-select v-model="selectedSheet" placeholder="选择工作表" @change="onSheetChange" style="width: 180px;">
              <el-option
                v-for="s in currentSheets"
                :key="s.name"
                :label="s.name"
                :value="s.name"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="可视化类型">
            <el-radio-group v-model="chartType" @change="renderChart">
              <el-radio label="line">净值/估值曲线</el-radio>
              <el-radio label="stacked">权重堆积图</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 净值/估值：参考回测「净值与回撤走势」双图布局 -->
      <el-row :gutter="20" v-if="chartType === 'line' && currentSheetData">
        <el-col :span="12">
          <el-card class="chart-card">
            <div slot="header" class="clearfix">
              <span><i class="el-icon-data-line"></i> 净值/估值曲线</span>
            </div>
            <div ref="navChart" style="width: 100%; height: 400px;" v-loading="chartLoading"></div>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card class="chart-card">
            <div slot="header" class="clearfix">
              <span><i class="el-icon-data-line"></i> 回撤走势</span>
            </div>
            <div ref="drawdownChart" style="width: 100%; height: 400px;" v-loading="chartLoading"></div>
          </el-card>
        </el-col>
      </el-row>
      <!-- 权重堆积：参考回测「持仓权重变化」 -->
      <el-row :gutter="20" v-if="chartType === 'stacked' && currentSheetData">
        <el-col :span="24">
          <el-card class="chart-card">
            <div slot="header" class="clearfix">
              <span><i class="el-icon-data-line"></i> 持仓权重变化</span>
              <span v-if="!hasWeightColumns" style="font-size: 12px; color: #E6A23C; margin-left: 12px;">（当前工作表无可视化权重列，请选择「权重汇总」等含资产权重列的工作表）</span>
            </div>
            <div ref="positionChart" style="width: 100%; height: 450px;" v-loading="chartLoading"></div>
          </el-card>
        </el-col>
      </el-row>

      <el-card class="table-card" style="margin-top: 20px;">
        <div slot="header" class="clearfix">
          <span><i class="el-icon-s-grid"></i> 数据明细</span>
          <span style="font-size: 12px; color: #909399; margin-left: 12px;">
            {{ displayData.length }} 行 × {{ displayColumns.length }} 列
          </span>
        </div>
        <vxe-table
          border
          stripe
          height="400"
          :data="displayData"
          :scroll-x="{enabled: true}"
          show-overflow="title"
        >
          <vxe-column
            v-for="col in displayColumns"
            :key="col"
            :field="col"
            :title="col"
            :width="col === dateCol ? 120 : 110"
          >
            <template #default="{ row }">
              {{ formatCell(row[col], col) }}
            </template>
          </vxe-column>
        </vxe-table>
      </el-card>
    </template>
  </div>
</template>

<script>
import * as XLSX from 'xlsx';
import * as echarts from 'echarts';

export default {
  name: 'WeightValuationImport',
  data() {
    return {
      parsedSheets: [],
      selectedFileKey: '',
      selectedSheet: '',
      chartType: 'line',
      chartInstances: {},    // navChart, drawdownChart, positionChart
      chartLoading: false,
      dateCol: '',
      valueCols: []
    };
  },
  computed: {
    currentFile() {
      return this.parsedSheets.find(f => f.fileKey === this.selectedFileKey);
    },
    currentSheets() {
      return this.currentFile ? this.currentFile.sheets : [];
    },
    currentSheetData() {
      if (!this.selectedSheet || !this.currentFile) return null;
      const s = this.currentFile.sheets.find(sh => sh.name === this.selectedSheet);
      return s ? s : null;
    },
    displayData() {
      const s = this.currentSheetData;
      if (!s || !s.data) return [];
      return s.data;
    },
    displayColumns() {
      const s = this.currentSheetData;
      if (!s) return [];
      return [s.dateCol, ...s.valueCols].filter(Boolean);
    },
    dateCol() {
      return this.currentSheetData?.dateCol || '';
    },
    hasWeightColumns() {
      const s = this.currentSheetData;
      if (!s || !s.valueCols) return true;
      const excludePattern = /杠杆|波动率|系数/i;
      const weightCols = s.valueCols.filter(c => !excludePattern.test(String(c)));
      return weightCols.length > 0;
    }
  },
  mounted() {
    window.addEventListener('resize', this.handleResize);
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.handleResize);
    Object.values(this.chartInstances).forEach(chart => {
      if (chart && !chart.isDisposed) chart.dispose();
    });
    this.chartInstances = {};
  },
  methods: {
    parseExcelFile(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
          try {
            const data = new Uint8Array(e.target.result);
            const workbook = XLSX.read(data, { type: 'array', cellDates: true });
            const sheets = [];
            workbook.SheetNames.forEach(sheetName => {
              const ws = workbook.Sheets[sheetName];
              const raw = XLSX.utils.sheet_to_json(ws, { header: 1, defval: null });
              if (!raw || raw.length < 2) return;
              const parsed = this.parseSheet(raw, sheetName);
              if (parsed) sheets.push(parsed);
            });
            resolve({ fileName: file.name, sheets });
          } catch (err) {
            reject(err);
          }
        };
        reader.onerror = () => reject(new Error('文件读取失败'));
        reader.readAsArrayBuffer(file);
      });
    },
    parseSheet(raw) {
      const headers = raw[0];
      if (!headers || headers.length < 2) return null;
      const dateCol = this.guessDateColumn(headers, raw);
      if (!dateCol) return null;
      const valueCols = headers.filter((h, i) => i !== dateCol && this.isNumericColumn(raw, i));
      if (valueCols.length === 0) return null;
      const data = [];
      for (let r = 1; r < raw.length; r++) {
        const row = raw[r];
        const dateVal = row[dateCol];
        const dateStr = this.toDateString(dateVal);
        if (!dateStr) continue;
        const obj = { [headers[dateCol]]: dateStr };
        valueCols.forEach((colName, idx) => {
          const colIdx = headers.indexOf(colName);
          const val = row[colIdx];
          obj[colName] = this.toNumber(val);
        });
        data.push(obj);
      }
      if (data.length === 0) return null;
      const dateColName = headers[dateCol] && !String(headers[dateCol]).startsWith('Unnamed') ? headers[dateCol] : '日期';
      data.forEach(row => {
        row[dateColName] = row[headers[dateCol]];
        if (headers[dateCol] !== dateColName) delete row[headers[dateCol]];
      });
      return {
        name: sheetName || dateColName,
        data,
        dateCol: dateColName,
        valueCols
      };
    },
    guessDateColumn(headers, raw) {
      for (let c = 0; c < headers.length; c++) {
        const sample = raw.slice(1, Math.min(6, raw.length)).map(r => r[c]);
        if (sample.every(v => this.looksLikeDate(v))) return c;
      }
      if (headers[0] && (String(headers[0]).toLowerCase().includes('date') || String(headers[0]).includes('日期') || String(headers[0]).includes('计算日期'))) return 0;
      return 0;
    },
    looksLikeDate(v) {
      if (v == null) return false;
      if (v instanceof Date) return true;
      const n = Number(v);
      if (!isNaN(n) && n > 10000 && n < 100000) return true;
      const s = String(v);
      if (/^\d{4}-\d{2}-\d{2}/.test(s)) return true;
      if (/^\d{8}$/.test(s)) return true;
      if (/^\d{4}\/\d{1,2}\/\d{1,2}/.test(s)) return true;
      return false;
    },
    isNumericColumn(raw, colIdx) {
      const sample = raw.slice(1, Math.min(20, raw.length)).map(r => r[colIdx]).filter(v => v != null && v !== '');
      if (sample.length === 0) return false;
      const numericCount = sample.filter(v => !isNaN(Number(v))).length;
      return numericCount >= sample.length * 0.5;
    },
    toDateString(v) {
      if (v == null || v === '') return null;
      if (v instanceof Date) {
        const y = v.getFullYear();
        const m = String(v.getMonth() + 1).padStart(2, '0');
        const d = String(v.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
      }
      const n = Number(v);
      if (!isNaN(n) && n > 10000 && n < 100000) {
        const d = new Date((n - 25569) * 86400 * 1000);
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
      }
      const s = String(v).trim();
      const m = s.match(/(\d{4})[-\/]?(\d{1,2})[-\/]?(\d{1,2})/);
      if (m) return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`;
      if (/^\d{8}$/.test(s)) return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`;
      return null;
    },
    toNumber(v) {
      if (v == null || v === '') return null;
      const n = Number(v);
      return isNaN(n) ? null : n;
    },
    async handleFileChange(file, fileList) {
      if (!file || !file.raw) return;
      this.chartLoading = true;
      try {
        const { fileName, sheets } = await this.parseExcelFile(file.raw);
        const fileKey = `${fileName}_${Date.now()}`;
        this.parsedSheets.push({ fileKey, fileName, fileUid: file.uid, sheets });
        if (!this.selectedFileKey) {
          this.selectedFileKey = fileKey;
          this.selectedSheet = sheets[0]?.name || '';
          if (sheets[0] && /权重|调仓/.test(sheets[0].name)) this.chartType = 'stacked';
        }
        this.$nextTick(() => this.renderChart());
      } catch (err) {
        this.$message.error('解析失败：' + (err.message || '未知错误'));
      } finally {
        this.chartLoading = false;
      }
    },
    handleFileRemove(file) {
      const idx = this.parsedSheets.findIndex(f => f.fileUid === file.uid || f.fileName === file.name);
      if (idx >= 0) {
        this.parsedSheets.splice(idx, 1);
        if (this.selectedFileKey && !this.parsedSheets.find(f => f.fileKey === this.selectedFileKey)) {
          this.selectedFileKey = this.parsedSheets[0]?.fileKey || '';
          this.selectedSheet = this.currentSheets[0]?.name || '';
        }
        this.$nextTick(() => this.renderChart());
      }
    },
    onFileChange() {
      this.selectedSheet = this.currentSheets[0]?.name || '';
      this.$nextTick(() => this.renderChart());
    },
    onSheetChange() {
      const s = this.currentSheetData;
      if (s && /权重|调仓/.test(s.name)) this.chartType = 'stacked';
      this.$nextTick(() => this.renderChart());
    },
    renderChart() {
      this.$nextTick(() => {
        const s = this.currentSheetData;
        if (!s || !s.data || s.data.length === 0) return;

        if (this.chartType === 'line') {
          this.disposeChart('positionChart');
          this.renderNavChart();
          this.renderDrawdownChart();
        } else {
          this.disposeChart('navChart');
          this.disposeChart('drawdownChart');
          this.renderPositionChart();
        }
      });
    },
    /** 净值曲线：参考回测 initNavChart */
    renderNavChart() {
      const dom = this.$refs.navChart;
      if (!dom || dom.offsetWidth === 0) return;
      this.disposeChart('navChart');
      const myChart = echarts.init(dom);
      this.chartInstances.navChart = myChart;

      const s = this.currentSheetData;
      const dates = s.data.map(r => r[s.dateCol]);
      const series = s.valueCols.map((col, i) => ({
        name: col,
        type: 'line',
        data: s.data.map(r => r[col]),
        smooth: true,
        itemStyle: { color: i === 0 ? '#409EFF' : undefined },
        markLine: i === 0 ? {
          data: [{ yAxis: 1.0, name: '基准线', lineStyle: { color: '#909399', type: 'dashed' } }]
        } : undefined
      }));

      myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: s.valueCols, bottom: 0 },
        grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: { type: 'value', name: '净值' },
        series
      }, true);
      myChart.resize();
    },
    /** 回撤曲线：参考回测 initDrawdownChart，从首列净值计算 */
    renderDrawdownChart() {
      const dom = this.$refs.drawdownChart;
      if (!dom || dom.offsetWidth === 0) return;
      this.disposeChart('drawdownChart');
      const myChart = echarts.init(dom);
      this.chartInstances.drawdownChart = myChart;

      const s = this.currentSheetData;
      const dates = s.data.map(r => r[s.dateCol]);
      const firstCol = s.valueCols[0];
      const navs = s.data.map(r => r[firstCol]);
      const drawdowns = this.computeDrawdown(navs);

      myChart.setOption({
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          formatter: (params) => {
            const p = params[0];
            return `${p.name}<br/>回撤: ${(drawdowns[p.dataIndex] || 0).toFixed(2)}%`;
          }
        },
        title: { text: '回撤走势', left: 'center', textStyle: { fontSize: 14 } },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: {
          type: 'value',
          name: '回撤 (%)',
          axisLabel: { formatter: '{value}%' }
        },
        series: [{
          name: '回撤',
          type: 'line',
          data: drawdowns,
          smooth: true,
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(245, 108, 108, 0.3)' },
                { offset: 1, color: 'rgba(245, 108, 108, 0.1)' }
              ]
            }
          },
          itemStyle: { color: '#F56C6C' }
        }]
      }, true);
      myChart.resize();
    },
    computeDrawdown(navs) {
      let peak = -Infinity;
      return navs.map(v => {
        if (v != null && v > 0) peak = Math.max(peak, v);
        if (peak <= 0) return 0;
        return ((peak - (v || 0)) / peak) * 100;
      });
    },
    /** 权重堆积图：参考回测 initPositionChart */
    renderPositionChart() {
      const dom = this.$refs.positionChart;
      if (!dom || dom.offsetWidth === 0) return;
      this.disposeChart('positionChart');
      const myChart = echarts.init(dom);
      this.chartInstances.positionChart = myChart;

      const s = this.currentSheetData;
      const dates = s.data.map(r => r[s.dateCol]);
      const excludePattern = /杠杆|波动率|系数/i;
      let valueCols = s.valueCols.filter(c => !excludePattern.test(String(c)));
      if (valueCols.length === 0) valueCols = s.valueCols;
      if (valueCols.length === 0) return;

      const series = valueCols.map(col => ({
        name: col,
        type: 'line',
        stack: 'total',
        areaStyle: {},
        emphasis: { focus: 'series' },
        data: s.data.map(r => (r[col] != null ? r[col] * 100 : 0))
      }));

      const maxSum = s.data.reduce((max, row) => {
        const sum = valueCols.reduce((s, c) => s + (row[c] != null ? row[c] * 100 : 0), 0);
        return Math.max(max, sum);
      }, 0);
      const yAxisMax = maxSum <= 100 ? 100 : Math.max(100, Math.ceil(maxSum / 5) * 5);

      myChart.setOption({
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          confine: true,
          formatter: (params) => {
            let html = `${params[0].axisValue}<br/>`;
            params.forEach(p => {
              const v = Array.isArray(p.value) ? p.value[p.value.length - 1] : p.value;
              html += `${p.seriesName}: ${(v != null ? parseFloat(v).toFixed(2) : '-')}%<br/>`;
            });
            return html;
          }
        },
        legend: { data: valueCols, bottom: 0, type: 'scroll' },
        grid: { left: '3%', right: '4%', top: 40, bottom: '22%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: {
          type: 'value',
          name: '权重 (%)',
          axisLabel: { formatter: '{value}%' },
          min: 0,
          max: yAxisMax
        },
        dataZoom: [
          { type: 'inside', start: 50, end: 100 },
          { show: true, type: 'slider', bottom: '2%', start: 50, end: 100 }
        ],
        series
      }, true);
      myChart.resize();
    },
    disposeChart(key) {
      const chart = this.chartInstances[key];
      if (chart && typeof chart.dispose === 'function') {
        chart.dispose();
      }
      delete this.chartInstances[key];
    },
    formatCell(val, col) {
      if (val == null) return '-';
      if (col === this.currentSheetData?.dateCol) return val;
      const n = Number(val);
      if (!isNaN(n)) return n.toFixed(4);
      return val;
    },
    handleResize() {
      Object.values(this.chartInstances).forEach(chart => {
        try {
          if (chart && typeof chart.resize === 'function') chart.resize();
        } catch (e) { /* disposed */ }
      });
    }
  }
};
</script>

<style scoped>
.weight-valuation-import {
  padding: 10px;
}
.upload-card,
.sheet-select-card,
.chart-card,
.table-card {
  margin-bottom: 16px;
}
</style>
