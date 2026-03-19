<template>
  <div class="fx-import">
    <el-card class="upload-card">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-upload2"></i> 汇率数据导入</span>
      </div>
      <el-alert
        title="文件格式说明"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      >
        <p style="margin: 0 0 8px 0;">请上传 fx.xlsx 格式文件，参考 portfilio-end/大类资产模型备份/fx.xlsx：</p>
        <ul style="margin: 0; padding-left: 20px;">
          <li><strong>第一列</strong>：日期（作为行索引）</li>
          <li><strong>后续列</strong>：EUR、USD、HKD、CNH，单元格为该货币对人民币的汇率</li>
          <li><strong>导入策略</strong>：替换全部已有数据（幂等）</li>
        </ul>
      </el-alert>

      <el-row :gutter="20">
        <el-col :span="12">
          <el-upload
            ref="fxUpload"
            action=""
            :auto-upload="false"
            :show-file-list="true"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :file-list="fileList"
            accept=".xlsx,.xls"
            :limit="1"
          >
            <el-button slot="trigger" type="primary" icon="el-icon-upload2">选择 fx.xlsx 文件</el-button>
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
    </el-card>

    <el-card class="stats-card" style="margin-top: 20px;">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-data-line"></i> 当前汇率数据统计</span>
        <el-button
          type="text"
          icon="el-icon-refresh"
          @click="refreshAll"
          style="float: right; padding: 0;"
        >
          刷新
        </el-button>
      </div>
      <div v-loading="statsLoading" class="stats-content">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="数据条数">{{ stats.count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="起始日期">{{ stats.start_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="结束日期">{{ stats.end_date || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </el-card>

    <el-card class="chart-card" style="margin-top: 20px;">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-data-line"></i> 汇率走势</span>
      </div>
      <div v-loading="chartLoading" class="chart-content">
        <div v-if="fxRates.length === 0 && !chartLoading" class="chart-empty">暂无汇率数据</div>
        <div v-else ref="fxChart" class="fx-chart"></div>
      </div>
    </el-card>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import { importFxRates, getFxStats, getFxRates } from '@/api/fx';

const FX_COLUMNS = ['EUR', 'USD', 'HKD', 'CNH'];

export default {
  name: 'FxImport',
  data() {
    return {
      fileList: [],
      selectedFile: null,
      uploading: false,
      statsLoading: false,
      chartLoading: false,
      chartInstance: null,
      fxRates: [],
      stats: {
        count: 0,
        start_date: null,
        end_date: null
      }
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
    handleFileChange(file, fileList) {
      if (fileList.length > 1) {
        this.fileList = [fileList[fileList.length - 1]];
      } else {
        this.fileList = fileList;
      }
      this.selectedFile = file && file.raw ? file.raw : null;
    },
    handleFileRemove() {
      this.fileList = [];
      this.selectedFile = null;
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
      this.$confirm('导入将替换全部已有汇率数据，是否继续？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        this.uploading = true;
        try {
          const res = await importFxRates(this.selectedFile);
          const data = res.data || res;
          this.$message.success(
            data.message || `成功导入 ${(data.imported || 0)} 条汇率记录`
          );
          this.handleFileRemove();
          await this.refreshAll();
        } catch (err) {
          let msg = err.response?.data?.detail || err.message || '导入失败';
          if (Array.isArray(msg)) msg = msg.join('; ');
          if (typeof msg !== 'string') msg = JSON.stringify(msg);
          this.$message.error(msg);
        } finally {
          this.uploading = false;
        }
      }).catch(() => {});
    },
    async fetchStats() {
      this.statsLoading = true;
      try {
        const res = await getFxStats();
        const data = res.data || res;
        this.stats = {
          count: data.count ?? 0,
          start_date: data.start_date || null,
          end_date: data.end_date || null
        };
      } catch (err) {
        this.stats = { count: 0, start_date: null, end_date: null };
      } finally {
        this.statsLoading = false;
      }
    },
    async refreshAll() {
      await this.fetchStats();
      if (this.stats.count > 0) {
        await this.fetchFxRates();
        this.$nextTick(() => this.renderFxChart());
      } else {
        this.fxRates = [];
        this.$nextTick(() => this.renderFxChart());
      }
    },
    async fetchFxRates() {
      this.chartLoading = true;
      try {
        const params = {};
        if (this.stats.start_date) params.startDate = this.stats.start_date;
        if (this.stats.end_date) params.endDate = this.stats.end_date;
        const res = await getFxRates(params);
        const data = res.data || res;
        this.fxRates = data.rows || [];
      } catch (err) {
        this.fxRates = [];
      } finally {
        this.chartLoading = false;
      }
    },
    renderFxChart() {
      const dom = this.$refs.fxChart;
      if (this.chartInstance && !this.chartInstance.isDisposed) {
        this.chartInstance.dispose();
        this.chartInstance = null;
      }
      if (!this.fxRates || this.fxRates.length === 0) return;
      if (!dom) return;
      const myChart = echarts.init(dom);
      this.chartInstance = myChart;
      const dates = this.fxRates.map(r => r.date);
      const series = FX_COLUMNS.map((col, i) => ({
        name: col,
        type: 'line',
        data: this.fxRates.map(r => r[col]),
        smooth: true,
        itemStyle: { color: i === 0 ? '#409EFF' : undefined }
      })).filter(s => s.data.some(v => v != null));
      myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: series.map(s => s.name), bottom: 0 },
        grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
        xAxis: { type: 'category', boundaryGap: false, data: dates },
        yAxis: { type: 'value', name: '汇率（对人民币）' },
        series
      }, true);
      myChart.resize();
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
.fx-import {
  padding: 20px;
}
.upload-card .el-upload__tip {
  margin-top: 8px;
  color: #909399;
  font-size: 12px;
}
.stats-content {
  min-height: 80px;
}
.chart-content {
  min-height: 400px;
}
.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
  color: #909399;
  font-size: 14px;
}
.fx-chart {
  width: 100%;
  height: 400px;
}
</style>
