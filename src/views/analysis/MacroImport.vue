<template>
  <div class="macro-import">
    <el-card class="upload-card">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-upload2"></i> 宏观与估值序列导入</span>
        <div class="header-actions">
          <el-button
            type="text"
            icon="el-icon-download"
            :loading="templateDownloading"
            @click="handleDownloadTemplate"
          >
            下载模板
          </el-button>
          <el-popover placement="bottom" width="460" trigger="click">
            <ul class="format-help">
              <li><strong>数据表</strong>：第一列为日期，后续每列列名为序列代码（如 H00922_PE、CBA_10Y），单元格为当日取值</li>
              <li><strong>序列说明表</strong>（可选，名称固定为「序列说明」）：序列代码 / 序列类型 / 单位 / 来源；缺该表时序列按 other 归类</li>
              <li><strong>序列类型</strong>只能取 valuation、bond_yield、credit_spread、erp、macro、other</li>
              <li><strong>覆盖</strong>：只清空文件中出现的序列代码后重写，其他序列不受影响；<strong>增量</strong>：只补库内缺失的 (序列, 日期)，已有取值不覆盖</li>
              <li>序列代码统一去空白转大写存储；取值不限正负（PB、信用利差、ERP 分量可为负）</li>
            </ul>
            <el-button slot="reference" type="text" icon="el-icon-question">格式说明</el-button>
          </el-popover>
        </div>
      </div>

      <div class="import-mode">
        <span class="import-mode-label">Excel 导入模式</span>
        <el-radio-group v-model="importMode" size="small">
          <el-radio-button label="replace">覆盖（按序列重写）</el-radio-button>
          <el-radio-button label="incremental">增量（仅填补缺失）</el-radio-button>
        </el-radio-group>
      </div>

      <el-row :gutter="20">
        <el-col :span="12">
          <el-upload
            action=""
            :auto-upload="false"
            :show-file-list="true"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :file-list="fileList"
            accept=".xlsx,.xls"
            :limit="1"
          >
            <el-button slot="trigger" type="primary" icon="el-icon-upload2">选择 Excel 文件</el-button>
            <div slot="tip" class="el-upload__tip">支持 .xlsx、.xls，每次导入一个文件</div>
          </el-upload>
        </el-col>
        <el-col :span="12">
          <el-button
            type="success"
            icon="el-icon-upload"
            :loading="uploading"
            :disabled="!selectedFile"
            @click="handleImport"
          >
            开始导入
          </el-button>
        </el-col>
      </el-row>

      <div v-if="lastResult" class="import-result">
        <i class="el-icon-circle-check"></i>
        {{ lastResult }}
      </div>
    </el-card>

    <el-card class="stats-card" style="margin-top: 20px;">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-data-line"></i> 数据概览</span>
        <el-button
          type="text"
          icon="el-icon-refresh"
          style="float: right; padding: 0;"
          @click="refreshAll"
        >
          刷新
        </el-button>
      </div>
      <div v-loading="statsLoading">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="总条数">{{ stats.count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="序列数">{{ stats.series_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="起始日期">{{ stats.start_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="结束日期">{{ stats.end_date || '-' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="stats.by_type && stats.by_type.length" class="type-summary">
          <el-tag
            v-for="t in stats.by_type"
            :key="t.series_type"
            size="small"
            type="info"
            class="type-tag"
          >
            {{ t.label }}：{{ t.series_count }} 条序列 / {{ t.count }} 条记录
          </el-tag>
        </div>
      </div>
    </el-card>

    <el-card class="list-card" style="margin-top: 20px;">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-s-grid"></i> 序列清单</span>
        <el-select
          v-model="filterType"
          size="small"
          clearable
          placeholder="全部类型"
          style="float: right; width: 170px;"
          @change="fetchSeries"
        >
          <el-option
            v-for="(label, key) in seriesTypes"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
      </div>
      <el-table
        v-loading="seriesLoading"
        :data="seriesList"
        size="small"
        border
        style="width: 100%"
        empty-text="库内暂无序列，请先导入 Excel"
      >
        <el-table-column prop="code" label="序列代码" min-width="160" />
        <el-table-column prop="series_type" label="类型" width="130">
          <template slot-scope="scope">
            <el-tag size="mini" type="info">{{ typeLabel(scope.row.series_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="80">
          <template slot-scope="scope">{{ scope.row.unit || '-' }}</template>
        </el-table-column>
        <el-table-column prop="count" label="条数" width="90" />
        <el-table-column prop="start_date" label="起始日期" width="110" />
        <el-table-column prop="end_date" label="结束日期" width="110" />
        <el-table-column prop="source" label="来源" min-width="120">
          <template slot-scope="scope">{{ scope.row.source || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="mini" @click="showChart(scope.row.code)">查看走势</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="activeCode" class="chart-card" style="margin-top: 20px;">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-data-line"></i> {{ activeCode }} 走势</span>
        <el-button type="text" icon="el-icon-close" style="float: right; padding: 0;" @click="closeChart">
          收起
        </el-button>
      </div>
      <div v-loading="chartLoading" class="chart-content">
        <div v-if="chartRows.length === 0 && !chartLoading" class="chart-empty">该序列无数据</div>
        <div v-else ref="macroChart" class="macro-chart"></div>
      </div>
    </el-card>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import {
  importMacroSeries,
  getMacroStats,
  listMacroSeries,
  getMacroSeriesData,
  downloadMacroTemplate
} from '@/api/macro';

export default {
  name: 'MacroSeriesImport',
  data() {
    return {
      fileList: [],
      selectedFile: null,
      uploading: false,
      templateDownloading: false,
      importMode: 'replace',
      lastResult: '',
      statsLoading: false,
      seriesLoading: false,
      chartLoading: false,
      chartInstance: null,
      seriesTypes: {},
      filterType: '',
      seriesList: [],
      stats: {
        count: 0,
        series_count: 0,
        start_date: null,
        end_date: null,
        by_type: []
      },
      activeCode: '',
      chartRows: []
    };
  },
  mounted() {
    this.refreshAll();
    window.addEventListener('resize', this.handleResize);
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.handleResize);
    if (this.chartInstance && !this.chartInstance.isDisposed) {
      this.chartInstance.dispose();
      this.chartInstance = null;
    }
  },
  methods: {
    typeLabel(key) {
      return this.seriesTypes[key] || key || '-';
    },
    resolveError(err, fallback) {
      let msg = (err.response && err.response.data && err.response.data.detail) || err.message || fallback;
      if (Array.isArray(msg)) msg = msg.map(m => (m && m.msg) || m).join('; ');
      if (typeof msg !== 'string') msg = JSON.stringify(msg);
      return msg;
    },
    handleFileChange(file, fileList) {
      this.fileList = fileList.length > 1 ? [fileList[fileList.length - 1]] : fileList;
      this.selectedFile = file && file.raw ? file.raw : null;
      this.lastResult = '';
    },
    handleFileRemove() {
      this.fileList = [];
      this.selectedFile = null;
    },
    async handleDownloadTemplate() {
      this.templateDownloading = true;
      try {
        const blob = await downloadMacroTemplate();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'macro_series_template.xlsx';
        link.click();
        window.URL.revokeObjectURL(url);
      } catch (err) {
        this.$message.error(this.resolveError(err, '模板下载失败'));
      } finally {
        this.templateDownloading = false;
      }
    },
    async handleImport() {
      if (!this.selectedFile) {
        this.$message.warning('请先选择文件');
        return;
      }
      const name = (this.selectedFile.name || '').toLowerCase();
      if (!name.endsWith('.xlsx') && !name.endsWith('.xls')) {
        this.$message.warning('请上传 .xlsx 或 .xls 格式文件');
        return;
      }
      const isReplace = this.importMode === 'replace';
      const confirmText = isReplace
        ? '覆盖模式会清空文件中出现的序列代码后重写，其他序列不受影响。是否继续？'
        : '增量模式不会删除已有数据，只补充库内缺失的 (序列, 日期)，已有取值不覆盖。是否继续？';
      this.$confirm(confirmText, isReplace ? '确认按序列覆盖' : '确认增量导入', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        this.uploading = true;
        try {
          const res = await importMacroSeries(this.selectedFile, { mode: this.importMode });
          const data = res.data || res;
          this.lastResult = data.message || `已写入 ${data.inserted || 0} 条`;
          this.$message.success(this.lastResult);
          this.handleFileRemove();
          await this.refreshAll();
        } catch (err) {
          this.$message.error(this.resolveError(err, '导入失败'));
        } finally {
          this.uploading = false;
        }
      }).catch(() => {});
    },
    async fetchStats() {
      this.statsLoading = true;
      try {
        const res = await getMacroStats();
        const data = res.data || res;
        this.stats = {
          count: data.count || 0,
          series_count: data.series_count || 0,
          start_date: data.start_date || null,
          end_date: data.end_date || null,
          by_type: data.by_type || []
        };
      } catch (err) {
        this.stats = { count: 0, series_count: 0, start_date: null, end_date: null, by_type: [] };
      } finally {
        this.statsLoading = false;
      }
    },
    async fetchSeries() {
      this.seriesLoading = true;
      try {
        const res = await listMacroSeries({ seriesType: this.filterType });
        const data = res.data || res;
        this.seriesList = data.items || [];
        if (data.types && Object.keys(data.types).length) {
          this.seriesTypes = data.types;
        }
      } catch (err) {
        this.seriesList = [];
        this.$message.error(this.resolveError(err, '序列清单加载失败'));
      } finally {
        this.seriesLoading = false;
      }
    },
    async refreshAll() {
      await this.fetchStats();
      await this.fetchSeries();
      if (this.activeCode) await this.showChart(this.activeCode);
    },
    async showChart(code) {
      this.activeCode = code;
      this.chartLoading = true;
      try {
        const res = await getMacroSeriesData(code);
        const data = res.data || res;
        this.chartRows = data.rows || [];
      } catch (err) {
        this.chartRows = [];
        this.$message.error(this.resolveError(err, '走势加载失败'));
      } finally {
        this.chartLoading = false;
        this.$nextTick(() => this.renderChart());
      }
    },
    closeChart() {
      this.activeCode = '';
      this.chartRows = [];
      if (this.chartInstance && !this.chartInstance.isDisposed) {
        this.chartInstance.dispose();
        this.chartInstance = null;
      }
    },
    renderChart() {
      const dom = this.$refs.macroChart;
      if (!dom || this.chartRows.length === 0) return;
      if (this.chartInstance && !this.chartInstance.isDisposed) {
        this.chartInstance.dispose();
      }
      const chart = echarts.init(dom);
      this.chartInstance = chart;
      chart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        toolbox: { right: 12, top: 8, feature: { restore: { title: '还原缩放' } } },
        grid: { left: '3%', right: '5%', top: 40, bottom: 60, containLabel: true },
        dataZoom: [
          { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
          { type: 'slider', xAxisIndex: 0, filterMode: 'none', height: 20, bottom: 8 }
        ],
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: this.chartRows.map(r => r.date)
        },
        yAxis: { type: 'value', name: this.activeCode, scale: true },
        series: [
          {
            name: this.activeCode,
            type: 'line',
            showSymbol: false,
            data: this.chartRows.map(r => r.value)
          }
        ]
      }, true);
      chart.resize();
    },
    handleResize() {
      if (this.chartInstance && !this.chartInstance.isDisposed) {
        this.chartInstance.resize();
      }
    }
  }
};
</script>

<style scoped>
.macro-import {
  padding: 20px;
}
.header-actions {
  float: right;
  padding: 0;
}
.header-actions .el-button + .el-button {
  margin-left: 12px;
}
.format-help {
  margin: 0;
  padding-left: 18px;
  line-height: 1.7;
  font-size: 12px;
  color: #606266;
}
.import-mode {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.import-mode-label {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}
.import-result {
  margin-top: 14px;
  font-size: 12px;
  color: #67c23a;
  line-height: 1.6;
}
.type-summary {
  margin-top: 12px;
}
.type-tag {
  margin-right: 8px;
  margin-bottom: 6px;
}
.chart-content {
  min-height: 380px;
}
.macro-chart {
  width: 100%;
  height: 380px;
}
.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 380px;
  color: #909399;
  font-size: 14px;
}
</style>
