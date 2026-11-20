<template>
  <div class="factor-panel-import">
    <!-- ══════════ 导入 ══════════ -->
    <el-card class="upload-card">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-upload2"></i> 因子截面数据导入</span>
        <el-popover placement="bottom" width="520" trigger="click">
          <ul class="fp-help">
            <li><strong>一行 = 一个数据集的一期一股</strong>；一个文件可含任意期数，按「日期」列自动分期</li>
            <li><strong>日期*</strong>：权重生效日，驱动调仓；<strong>代码*</strong>须与资产库代码完全一致</li>
            <li><strong>行业*/券池*</strong>：分组键，行业内限额与组内选取数量按此列分组</li>
            <li>因子列可自由增删，列名映射登记在后端 <code>field_mappings.FACTOR_NAME_MAPPING_BY_DATASET</code></li>
            <li><strong>整行因子全空会被跳过</strong>（计入 factor_empty）：成分快照期请整期都不填因子列</li>
            <li><strong>覆盖</strong>只影响本数据集中文件出现的那几期，其他期与其他数据集不动</li>
          </ul>
          <el-button slot="reference" type="text" icon="el-icon-question" style="float: right; padding: 0;">格式说明</el-button>
        </el-popover>
      </div>

      <el-form :inline="true" size="small" class="fp-form">
        <el-form-item label="数据集">
          <el-select
            v-model="dataset"
            placeholder="请选择目标数据集"
            style="width: 420px;"
            :loading="datasetsLoading"
            @change="handleDatasetChange"
          >
            <el-option
              v-for="item in datasets"
              :key="item.dataset"
              :label="datasetOptionLabel(item)"
              :value="item.dataset"
              :disabled="item.registered === false"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="生效日">
          <el-date-picker
            v-model="asOfDate"
            type="date"
            value-format="yyyy-MM-dd"
            placeholder="文件含日期列则留空"
            style="width: 170px;"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-button
            icon="el-icon-download"
            :disabled="!dataset"
            :loading="templateDownloading"
            @click="handleDownloadTemplate"
          >
            下载本数据集模板
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="currentDataset" class="fp-dataset-hint">
        <i class="el-icon-info"></i> {{ currentDataset.label }}
        <span class="fp-dataset-stat">
          库内 {{ currentDataset.row_count }} 行 / {{ currentDataset.period_count }} 期
          <template v-if="currentDataset.start_date">
            （{{ currentDataset.start_date }} ~ {{ currentDataset.end_date }}）
          </template>
          <template v-else>（尚无数据）</template>
        </span>
      </div>

      <div class="fp-mode">
        <span class="fp-mode-label">导入模式</span>
        <el-radio-group v-model="importMode" size="small">
          <el-radio-button label="upsert">逐行覆盖（重复导入结果一致）</el-radio-button>
          <el-radio-button label="replace">整期替换（先删本数据集文件内的期）</el-radio-button>
          <el-radio-button label="incremental">增量（只写库内没有的行）</el-radio-button>
        </el-radio-group>
      </div>

      <el-row :gutter="20">
        <el-col :span="12">
          <el-upload
            ref="fpUpload"
            action=""
            :auto-upload="false"
            :show-file-list="true"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :file-list="fileList"
            accept=".xlsx,.xls"
            :limit="1"
          >
            <el-button slot="trigger" type="primary" icon="el-icon-folder-opened">选择因子截面 Excel</el-button>
            <div slot="tip" class="el-upload__tip">支持 .xlsx、.xls；整个文件写入同一个数据集</div>
          </el-upload>
        </el-col>
        <el-col :span="12">
          <el-button
            icon="el-icon-view"
            :loading="previewing"
            :disabled="!selectedFile || !dataset"
            @click="handleRun(true)"
          >
            预演（不写库）
          </el-button>
          <el-button
            type="success"
            icon="el-icon-upload"
            :loading="uploading"
            :disabled="!selectedFile || !dataset"
            @click="handleRun(false)"
          >
            开始导入
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- ══════════ 最近一次结果 ══════════ -->
    <el-card v-if="result" class="result-card">
      <div slot="header" class="clearfix">
        <span>
          <i class="el-icon-document-checked"></i>
          {{ resultIsPreview ? '预演结果（未写库）' : '导入结果' }}
          · {{ result.dataset }}
        </span>
        <el-button type="text" icon="el-icon-close" style="float: right; padding: 0;" @click="result = null">
          收起
        </el-button>
      </div>

      <el-alert :type="result.error_count ? 'warning' : 'success'" :closable="false" show-icon>
        <template slot="title">{{ resultMessage }}</template>
      </el-alert>

      <el-descriptions :column="3" border size="small" style="margin-top: 14px;">
        <el-descriptions-item label="文件行数">{{ result.total_rows }}</el-descriptions-item>
        <el-descriptions-item label="新增">{{ result.inserted_count }}</el-descriptions-item>
        <el-descriptions-item label="更新">{{ result.updated_count }}</el-descriptions-item>
        <el-descriptions-item label="跳过">{{ result.skipped_count }}</el-descriptions-item>
        <el-descriptions-item label="错误">{{ result.error_count }}</el-descriptions-item>
        <el-descriptions-item label="期日范围">{{ result.date_range || '-' }}</el-descriptions-item>
      </el-descriptions>

      <div v-if="result.snapshot_periods && result.snapshot_periods.length" class="fp-tags">
        <span class="fp-tags-label">成分快照期</span>
        <el-tag size="small" type="warning">
          {{ result.snapshot_periods.length }} 期整期无因子，策略将全截面入选等权
        </el-tag>
      </div>
      <div v-if="skippedTags.length" class="fp-tags">
        <span class="fp-tags-label">跳过原因</span>
        <el-tag v-for="t in skippedTags" :key="t.key" size="small" type="info">{{ t.key }}：{{ t.count }}</el-tag>
      </div>
      <div v-if="unknownCodeCount" class="fp-tags">
        <span class="fp-tags-label">不在资产库的代码</span>
        <el-tag size="small" type="warning">{{ unknownCodeCount }} 只（回测时取不到行情）</el-tag>
        <span v-if="unknownCodesSample.length" class="fp-muted">{{ unknownCodesSample.join('、') }}</span>
      </div>
      <div v-if="nonNumericCells.length" class="fp-tags">
        <span class="fp-tags-label">数值因子列出现文本（已置空）</span>
        <el-tag v-for="c in nonNumericCells" :key="c.column" size="small" type="danger">
          {{ c.column }}：{{ c.count }} 行
        </el-tag>
      </div>
      <div v-if="unmappedColumns.length" class="fp-tags">
        <span class="fp-tags-label">已忽略的列</span>
        <el-tag v-for="c in unmappedColumns" :key="c" size="small" type="warning">{{ c }}</el-tag>
      </div>
      <div v-if="result.factor_keys && result.factor_keys.length" class="fp-tags">
        <span class="fp-tags-label">识别到的因子键</span>
        <el-tag v-for="k in result.factor_keys" :key="k" size="small">{{ k }}</el-tag>
      </div>

      <el-table
        v-if="periodRows.length"
        :data="periodRows"
        size="mini"
        border
        max-height="240"
        style="margin-top: 14px;"
      >
        <el-table-column prop="as_of_date" label="期日" width="140" />
        <el-table-column prop="row_count" label="行数" width="100" />
        <el-table-column prop="kind" label="类型" width="110" />
      </el-table>

      <el-table
        v-if="result.errors && result.errors.length"
        :data="result.errors"
        size="mini"
        border
        max-height="240"
        style="margin-top: 14px;"
      >
        <el-table-column prop="row" label="行号" width="80" />
        <el-table-column prop="code" label="代码" width="140" />
        <el-table-column prop="reason" label="原因" show-overflow-tooltip />
      </el-table>
    </el-card>

    <!-- ══════════ 库内数据 ══════════ -->
    <el-card class="stats-card">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-data-line"></i> 库内因子截面</span>
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
        <el-descriptions :column="5" border size="small">
          <el-descriptions-item label="统计口径">
            {{ dataset || '全部数据集合计' }}
          </el-descriptions-item>
          <el-descriptions-item label="总行数">{{ stats.count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="期数">{{ stats.period_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="起止期日">
            {{ stats.start_date || '-' }} ~ {{ stats.end_date || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="涉及代码数">{{ stats.stock_count || 0 }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="factorNames.length" class="fp-tags">
          <span class="fp-tags-label">库内因子键（出现行数）</span>
          <el-tag v-for="f in factorNames" :key="f.name" size="small" type="info">
            {{ f.name }}：{{ f.count }}
          </el-tag>
        </div>

        <el-table
          v-loading="periodsLoading"
          :data="pagedPeriods"
          size="small"
          border
          style="margin-top: 14px;"
        >
          <el-table-column prop="as_of_date" label="期日" width="120" sortable />
          <el-table-column prop="dataset" label="数据集" width="180" show-overflow-tooltip />
          <el-table-column prop="row_count" label="行数" width="90" />
          <el-table-column prop="stock_count" label="证券数" width="90" />
          <el-table-column prop="industry_count" label="分组数" width="90" />
          <el-table-column prop="mv_row_count" label="有市值行数" width="110" />
          <el-table-column label="因子键" min-width="200">
            <template slot-scope="scope">
              <span v-if="!scope.row.factor_keys.length" class="fp-muted">无（成分快照期）</span>
              <span v-else>{{ scope.row.factor_keys.join('、') }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template slot-scope="scope">
              <el-button type="text" size="mini" @click="openPeriodDetail(scope.row)">查看明细</el-button>
              <el-button type="text" size="mini" class="fp-danger" @click="handleDeletePeriod(scope.row)">
                删除该期
              </el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <span class="fp-muted">该数据集尚无数据</span>
          </template>
        </el-table>

        <el-pagination
          v-if="periods.length > periodPageSize"
          :current-page.sync="periodPage"
          :page-size="periodPageSize"
          :total="periods.length"
          layout="total, prev, pager, next"
          small
          style="margin-top: 12px; text-align: right;"
        />
      </div>
    </el-card>

    <!-- ══════════ 期明细 ══════════ -->
    <el-dialog
      :title="detailTitle"
      :visible.sync="detailVisible"
      width="80%"
      append-to-body
      top="6vh"
    >
      <div v-loading="detailLoading">
        <div v-if="detailFactorKeys.length" class="fp-tags">
          <span class="fp-tags-label">因子键</span>
          <el-tag v-for="k in detailFactorKeys" :key="k" size="small">{{ k }}</el-tag>
        </div>
        <el-table :data="detailRows" size="mini" border max-height="520">
          <el-table-column prop="code" label="代码" width="130" fixed />
          <el-table-column prop="name" label="简称" width="140" show-overflow-tooltip />
          <el-table-column prop="industry" label="分组" width="160" show-overflow-tooltip />
          <el-table-column
            v-for="k in detailFactorKeys"
            :key="k"
            :label="k"
            width="130"
            show-overflow-tooltip
          >
            <template slot-scope="scope">{{ formatFactor(scope.row.factors, k) }}</template>
          </el-table-column>
          <el-table-column label="总市值" width="120">
            <template slot-scope="scope">{{ formatMv(scope.row.total_mv) }}</template>
          </el-table-column>
          <el-table-column prop="data_date" label="取数日" width="110" />
          <template slot="empty"><span class="fp-muted">无数据</span></template>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import {
  listFactorPanelDatasets,
  getFactorPanelOverview,
  importFactorPanel,
  downloadFactorPanelTemplate,
  getFactorPanelPeriod,
  deleteFactorPanelPeriod
} from '@/api/factorPanel';

// 期清单分页大小：一个数据集几十期，一页放得下就不用翻页
const PERIOD_PAGE_SIZE = 20;

export default {
  name: 'FactorPanelImport',
  data() {
    return {
      dataset: '',
      datasets: [],
      datasetsLoading: false,
      asOfDate: '',
      importMode: 'upsert',
      fileList: [],
      selectedFile: null,
      uploading: false,
      previewing: false,
      templateDownloading: false,
      result: null,
      resultIsPreview: false,
      resultMessage: '',
      stats: {},
      periods: [],
      factorNames: [],
      statsLoading: false,
      periodsLoading: false,
      periodPage: 1,
      periodPageSize: PERIOD_PAGE_SIZE,
      detailVisible: false,
      detailLoading: false,
      detailRows: [],
      detailTitle: ''
    };
  },
  computed: {
    currentDataset() {
      return this.datasets.find(d => d.dataset === this.dataset) || null;
    },
    resultWarnings() {
      return (this.result && this.result.warnings) || {};
    },
    unknownCodeCount() {
      return this.resultWarnings.code_not_in_assets || 0;
    },
    unknownCodesSample() {
      return this.resultWarnings.unknown_codes_sample || [];
    },
    nonNumericCells() {
      const cells = this.resultWarnings.non_numeric_cells || {};
      return Object.keys(cells).sort().map(column => ({ column, count: cells[column] }));
    },
    skippedTags() {
      const reasons = (this.result && this.result.skipped_reasons) || {};
      return Object.keys(reasons).map(key => ({ key, count: reasons[key] }));
    },
    unmappedColumns() {
      return this.resultWarnings.unmapped_columns || [];
    },
    periodRows() {
      const map = (this.result && this.result.period_rows) || {};
      const snapshots = new Set((this.result && this.result.snapshot_periods) || []);
      return Object.keys(map).sort().map(k => ({
        as_of_date: k,
        row_count: map[k],
        kind: snapshots.has(k) ? '成分快照' : '打分'
      }));
    },
    pagedPeriods() {
      const start = (this.periodPage - 1) * this.periodPageSize;
      return this.periods.slice(start, start + this.periodPageSize);
    },
    detailFactorKeys() {
      const keys = new Set();
      this.detailRows.forEach(row => {
        Object.keys(row.factors || {}).forEach(k => keys.add(k));
      });
      return Array.from(keys).sort();
    }
  },
  mounted() {
    this.refreshAll();
  },
  methods: {
    datasetOptionLabel(item) {
      if (item.registered === false) {
        return `${item.dataset}（库内存在但未登记，不可导入）`;
      }
      return `${item.dataset} · ${item.row_count} 行 / ${item.period_count} 期`;
    },
    handleDatasetChange() {
      this.result = null;
      this.periodPage = 1;
      this.fetchOverview();
    },
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
    async handleDownloadTemplate() {
      if (!this.dataset) {
        this.$message.warning('请先选择数据集');
        return;
      }
      this.templateDownloading = true;
      try {
        const blob = await downloadFactorPanelTemplate(this.dataset);
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `factor_panel_import_template_${this.dataset}.xlsx`;
        link.click();
        window.URL.revokeObjectURL(url);
        this.$message.success(`已下载 ${this.dataset} 的导入模板`);
      } catch (err) {
        this.$message.error(await this.resolveError(err, '模板下载失败'));
      } finally {
        this.templateDownloading = false;
      }
    },
    async handleRun(dryRun) {
      if (!this.selectedFile) {
        this.$message.warning('请先选择文件');
        return;
      }
      if (!this.dataset) {
        this.$message.warning('请先选择数据集');
        return;
      }
      const name = (this.selectedFile.name || '').toLowerCase();
      if (!name.endsWith('.xlsx') && !name.endsWith('.xls')) {
        this.$message.warning('请上传 .xlsx 或 .xls 格式文件');
        return;
      }
      const confirmText = dryRun
        ? `预演只解析文件并返回识别到的期数/行数/因子键，不写库。是否继续？`
        : this.buildImportConfirmText();
      try {
        await this.$confirm(confirmText, dryRun ? '确认预演' : '确认导入', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning'
        });
      } catch (e) {
        return;
      }
      const loadingKey = dryRun ? 'previewing' : 'uploading';
      this[loadingKey] = true;
      try {
        const res = await importFactorPanel(this.selectedFile, {
          dataset: this.dataset,
          mode: this.importMode,
          asOfDate: this.asOfDate,
          dryRun
        });
        const data = res.data || res;
        this.result = data;
        this.resultIsPreview = dryRun;
        // 提示文本以后端为单源：后端会把告警（代码不在资产库、数值列出现文本等）拼进去
        this.resultMessage = (res && res.message) || this.buildResultSummary(data, dryRun);
        this.$message({
          type: data.error_count ? 'warning' : 'success',
          message: this.resultMessage,
          duration: 6000,
          showClose: true
        });
        if (!dryRun) {
          this.handleFileRemove();
          await this.refreshAll();
        }
      } catch (err) {
        this.$message.error(await this.resolveError(err, '导入失败'));
      } finally {
        this[loadingKey] = false;
      }
    },
    buildResultSummary(r, dryRun) {
      // 后端未返回 message 时的本地兜底（不重复拼告警，告警已用标签展现）
      if (dryRun) {
        return `识别到 ${r.periods.length} 期、共 ${r.total_rows} 行，因子键 ${r.factor_keys.length} 个，错误 ${r.error_count} 行`;
      }
      return `新增 ${r.inserted_count} 行，更新 ${r.updated_count} 行，跳过 ${r.skipped_count} 行，错误 ${r.error_count} 行`;
    },
    buildImportConfirmText() {
      const base = `将把文件写入数据集「${this.dataset}」。`;
      if (this.importMode === 'replace') {
        return `${base}整期替换会先删除本数据集中文件出现的那几期的全部行，再写入文件内容；其他期与其他数据集不受影响。是否继续？`;
      }
      if (this.importMode === 'incremental') {
        return `${base}增量模式只写库内还没有的（数据集, 日期, 代码），已有行保持原值不被覆盖。是否继续？`;
      }
      return `${base}逐行覆盖会按（数据集, 日期, 代码）覆盖同主键的行，重复导入结果一致。是否继续？`;
    },
    async refreshAll() {
      await Promise.all([this.fetchDatasets(), this.fetchOverview()]);
    },
    async fetchDatasets() {
      this.datasetsLoading = true;
      try {
        const res = await listFactorPanelDatasets();
        this.datasets = (res && res.data) || [];
        // 只有一个已登记数据集时直接选中，省掉一步操作
        const usable = this.datasets.filter(d => d.registered !== false);
        if (!this.dataset && usable.length === 1) {
          this.dataset = usable[0].dataset;
        }
      } catch (err) {
        this.datasets = [];
      } finally {
        this.datasetsLoading = false;
      }
    },
    async fetchOverview() {
      this.statsLoading = true;
      this.periodsLoading = true;
      try {
        const res = await getFactorPanelOverview(this.dataset);
        const data = (res && res.data) || {};
        this.stats = data.stats || {};
        this.periods = (data.periods || []).slice().reverse();
        this.factorNames = data.factor_names || [];
      } catch (err) {
        this.stats = {};
        this.periods = [];
        this.factorNames = [];
      } finally {
        this.statsLoading = false;
        this.periodsLoading = false;
      }
    },
    async openPeriodDetail(row) {
      this.detailTitle = `${row.dataset} · ${row.as_of_date} · ${row.row_count} 行`;
      this.detailVisible = true;
      this.detailLoading = true;
      this.detailRows = [];
      try {
        const res = await getFactorPanelPeriod(row.dataset, row.as_of_date);
        const data = (res && res.data) || {};
        this.detailRows = data.rows || [];
      } catch (err) {
        this.$message.error(await this.resolveError(err, '读取该期明细失败'));
      } finally {
        this.detailLoading = false;
      }
    },
    async handleDeletePeriod(row) {
      try {
        await this.$confirm(
          `将删除数据集「${row.dataset}」期日 ${row.as_of_date} 的全部 ${row.row_count} 行，其他期与其他数据集不受影响。是否继续？`,
          '确认整期删除',
          { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
        );
      } catch (e) {
        return;
      }
      try {
        const res = await deleteFactorPanelPeriod(row.dataset, row.as_of_date);
        this.$message.success((res && res.message) || '已删除');
        await this.refreshAll();
      } catch (err) {
        this.$message.error(await this.resolveError(err, '删除失败'));
      }
    },
    formatFactor(factors, key) {
      const value = (factors || {})[key];
      if (value === null || value === undefined || value === '') return '-';
      if (typeof value === 'number') {
        return Math.abs(value) >= 1000 ? value.toLocaleString('zh-CN') : String(value);
      }
      return String(value);
    },
    formatMv(value) {
      if (value === null || value === undefined || value === '') return '-';
      return `${(Number(value) / 1e8).toFixed(2)} 亿`;
    },
    async resolveError(err, fallback) {
      let detail = err && err.response && err.response.data;
      // responseType=blob 时错误体也是 Blob，需读成文本才能拿到后端 detail
      if (detail instanceof Blob) {
        try {
          detail = JSON.parse(await detail.text());
        } catch (e) {
          detail = null;
        }
      }
      // 后端有两套错误体：FastAPI 校验是 {detail}，业务层统一封装是 {code, message, data}。
      // 只读 detail 会落回 axios 的「Request failed with status code 400」，把真实原因吞掉。
      let msg = (detail && (detail.detail || detail.message))
        || (err && err.message)
        || fallback;
      if (Array.isArray(msg)) msg = msg.join('; ');
      if (typeof msg !== 'string') msg = JSON.stringify(msg);
      // 统一封装的 422 只在 message 里写「请求参数验证失败」，明细在 data[].msg
      if (detail && Array.isArray(detail.data) && detail.data.length) {
        const rows = detail.data
          .map(item => (item && (item.msg || item.message)) || '')
          .filter(Boolean);
        const uniq = [...new Set(rows)];
        if (uniq.length) msg = `${msg}（${uniq.join('; ')}）`;
      }
      return msg || fallback;
    }
  }
};
</script>

<style scoped>
.factor-panel-import {
  padding: 20px;
}
.fp-help {
  margin: 0;
  padding-left: 20px;
  line-height: 1.8;
  font-size: 12px;
}
.fp-form {
  margin-bottom: 4px;
}
.fp-dataset-hint {
  margin-bottom: 14px;
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
}
.fp-dataset-stat {
  color: #909399;
  margin-left: 8px;
}
.fp-mode {
  margin-bottom: 16px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.fp-mode-label {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}
.result-card,
.stats-card {
  margin-top: 20px;
}
.fp-tags {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.fp-tags-label {
  font-size: 12px;
  color: #909399;
  margin-right: 4px;
}
.fp-muted {
  color: #c0c4cc;
  font-size: 12px;
}
.fp-danger {
  color: #f56c6c;
}
.upload-card .el-upload__tip {
  margin-top: 8px;
  color: #909399;
  font-size: 12px;
}
</style>
