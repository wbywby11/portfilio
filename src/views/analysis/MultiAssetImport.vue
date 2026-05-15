<template>
  <div class="multi-asset-import">
    <el-card class="upload-card">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-upload2"></i> 多资产行情导入</span>
      </div>
      <el-alert
        title="支持格式说明"
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      >
        <p style="margin: 0 0 8px 0;">支持导入「大类资产底层数据」格式的 xlsx 文件（如 大类资产底层数据-含插件.xlsx）：</p>
        <ul style="margin: 0; padding-left: 20px;">
          <li>每个工作表：第 3 行为资产名称、第 4 行为资产代码、第 5 行起为日期与价格</li>
          <li>按资产代码逐个导入；若代码一致名称不一致会提示是否覆盖名称</li>
          <li>若已有行情会提示选择「仅新增」或「全覆盖」</li>
        </ul>
      </el-alert>
      <el-upload
        ref="xlsxUpload"
        action=""
        :auto-upload="false"
        :show-file-list="true"
        :on-change="handleFileChange"
        :on-remove="handleFileRemove"
        :file-list="fileList"
        accept=".xlsx,.xls"
        :limit="1"
      >
        <el-button slot="trigger" type="primary" icon="el-icon-upload2">选择 xlsx 文件</el-button>
        <div slot="tip" class="el-upload__tip">支持 .xlsx、.xls，每次导入一个文件</div>
      </el-upload>
    </el-card>

    <template v-if="previewAssets.length > 0">
      <el-card class="preview-card">
        <div slot="header" class="clearfix">
          <span><i class="el-icon-document"></i> 导入预览（共 {{ previewAssets.length }} 个资产）</span>
          <el-button
            v-if="!importing"
            type="primary"
            size="small"
            style="float: right;"
            :loading="parsing"
            @click="startImport"
          >
            开始导入
          </el-button>
        </div>
        <el-form :inline="true" size="small" style="margin-bottom: 12px;">
          <el-form-item label="名称冲突时">
            <el-select v-model="globalOverwriteName" placeholder="默认" style="width: 120px;">
              <el-option label="不覆盖" :value="false" />
              <el-option label="覆盖名称" :value="true" />
            </el-select>
          </el-form-item>
          <el-form-item label="已有行情时">
            <el-select v-model="globalReplaceExisting" placeholder="默认" style="width: 120px;">
              <el-option label="仅新增" :value="false" />
              <el-option label="全覆盖" :value="true" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button size="small" @click="applyGlobalToAll">应用到全部</el-button>
          </el-form-item>
        </el-form>
        <vxe-table
          border
          stripe
          max-height="400"
          :data="previewAssets"
          :scroll-y="{enabled: true}"
          show-overflow="title"
        >
          <vxe-column field="code" title="资产代码" width="140" />
          <vxe-column field="name" title="资产名称" min-width="160" show-overflow="title" />
          <vxe-column field="price_count" title="行情条数" width="100" />
          <vxe-column field="conflict_text" title="冲突" width="140">
            <template #default="{ row }">
              <el-tag v-if="!row.name_conflict && !row.has_prices" type="success" size="mini">无</el-tag>
              <el-tag v-else-if="row.name_conflict && row.has_prices" type="warning" size="mini">名称+行情</el-tag>
              <el-tag v-else-if="row.name_conflict" type="warning" size="mini">名称不一致</el-tag>
              <el-tag v-else type="info" size="mini">已有行情</el-tag>
            </template>
          </vxe-column>
          <vxe-column title="覆盖名称" width="120">
            <template #default="{ row }">
              <el-select
                v-model="row.overwrite_name"
                size="mini"
                style="width: 100%;"
                :disabled="!row.name_conflict || importing"
              >
                <el-option :label="row.name_conflict ? '不覆盖' : '-'" :value="false" />
                <el-option label="覆盖" :value="true" />
              </el-select>
            </template>
          </vxe-column>
          <vxe-column title="行情策略" width="120">
            <template #default="{ row }">
              <el-select
                v-model="row.replace_existing"
                size="mini"
                style="width: 100%;"
                :disabled="!row.has_prices || importing"
              >
                <el-option :label="row.has_prices ? '仅新增' : '-'" :value="false" />
                <el-option label="全覆盖" :value="true" />
              </el-select>
            </template>
          </vxe-column>
        </vxe-table>
      </el-card>

      <!-- 导入进度 -->
      <el-card v-if="importing" class="progress-card">
        <div slot="header" class="clearfix">
          <span><i class="el-icon-loading"></i> 导入进度</span>
        </div>
        <el-progress
          :percentage="importProgress"
          :status="importProgress === 100 ? 'success' : undefined"
        />
        <div style="margin-top: 12px; color: #606266;">
          当前：{{ currentImportAsset || '-' }} （{{ importDoneCount }}/{{ previewAssets.length }}）
        </div>
        <div
          v-if="rowImportDetailLine"
          style="margin-top: 8px; padding: 8px 10px; background: #f4f4f5; border-radius: 4px; font-size: 13px; font-family: Consolas, 'Courier New', monospace; color: #303133;"
        >
          {{ rowImportDetailLine }}
        </div>
        <div v-if="importErrors.length > 0" style="margin-top: 8px;">
          <el-alert
            :title="`${importErrors.length} 个错误`"
            type="warning"
            :closable="false"
            show-icon
          >
            <div v-for="(e, i) in importErrors.slice(0, 5)" :key="i">{{ e }}</div>
            <div v-if="importErrors.length > 5">... 共 {{ importErrors.length }} 条</div>
          </el-alert>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script>
import {
  previewMultiAssetImport,
  parseMultiAssetExcel,
  importSingleAssetFromMulti,
  getPriceImportProgress
} from '@/api/asset';
import {
  unwrapPriceImportProgressPayload,
  formatPriceImportProgressLine,
  PRICE_IMPORT_PROGRESS_POLL_MS
} from '@/utils/priceImportProgress';

export default {
  name: 'MultiAssetImport',
  data() {
    return {
      fileList: [],
      selectedFile: null,
      previewAssets: [],
      globalOverwriteName: false,
      globalReplaceExisting: false,
      parsing: false,
      importing: false,
      importDoneCount: 0,
      currentImportAsset: '',
      importErrors: [],
      rowImportDetailLine: '',
      _rowImportProgressTimer: null
    };
  },
  computed: {
    importProgress() {
      if (this.previewAssets.length === 0) return 0;
      return Math.round((this.importDoneCount / this.previewAssets.length) * 100);
    }
  },
  beforeDestroy() {
    this.stopRowImportProgressPoll();
  },
  methods: {
    newPriceImportProgressId() {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
      }
      return `p-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
    },
    stopRowImportProgressPoll() {
      if (this._rowImportProgressTimer) {
        clearInterval(this._rowImportProgressTimer);
        this._rowImportProgressTimer = null;
      }
    },
    startRowImportProgressPoll(progressId) {
      this.stopRowImportProgressPoll();
      if (!progressId) return;
      let hadSnap = false;
      let inFlight = false;
      const tick = () => {
        if (inFlight) return;
        inFlight = true;
        getPriceImportProgress(progressId)
          .then((res) => {
            const snap = unwrapPriceImportProgressPayload(res);
            if (snap) {
              hadSnap = true;
              this.rowImportDetailLine = formatPriceImportProgressLine(snap);
            } else if (!hadSnap) {
              this.rowImportDetailLine = '正在连接导入任务，等待服务端进度…';
            }
          })
          .catch(() => {
            if (!hadSnap) {
              this.rowImportDetailLine = '无法拉取进度（请检查网络或登录态）';
            }
          })
          .finally(() => {
            inFlight = false;
          });
      };
      tick();
      this._rowImportProgressTimer = setInterval(tick, PRICE_IMPORT_PROGRESS_POLL_MS);
    },
    async handleFileChange(file, list) {
      if (!file || !file.raw) return;
      this.selectedFile = file.raw;
      this.fileList = list;
      this.previewAssets = [];
      this.parsing = true;
      try {
        const res = await previewMultiAssetImport(file.raw);
        const data = res.data || res;
        const assets = (data.assets || []).map(a => ({
          ...a,
          overwrite_name: false,
          replace_existing: false
        }));
        this.previewAssets = assets;
      } catch (err) {
        this.$message.error('解析失败：' + (err.response?.data?.detail || err.message || '未知错误'));
      } finally {
        this.parsing = false;
      }
    },
    handleFileRemove() {
      this.selectedFile = null;
      this.fileList = [];
      this.previewAssets = [];
    },
    applyGlobalToAll() {
      this.previewAssets.forEach(a => {
        if (a.name_conflict) a.overwrite_name = this.globalOverwriteName;
        if (a.has_prices) a.replace_existing = this.globalReplaceExisting;
      });
      this.$message.success('已应用到全部');
    },
    async startImport() {
      if (!this.selectedFile || this.previewAssets.length === 0) {
        this.$message.warning('请先选择文件');
        return;
      }
      this.importing = true;
      this.importDoneCount = 0;
      this.importErrors = [];
      this.rowImportDetailLine = '';
      try {
        const parseRes = await parseMultiAssetExcel(this.selectedFile);
        const parsed = parseRes.data || parseRes;
        const assetsWithPrices = parsed.assets || [];
        const codeToData = {};
        assetsWithPrices.forEach(a => {
          codeToData[a.code] = a;
        });

        for (let i = 0; i < this.previewAssets.length; i++) {
          const p = this.previewAssets[i];
          this.currentImportAsset = `${p.name} (${p.code})`;
          const full = codeToData[p.code];
          if (!full || !full.prices || full.prices.length === 0) {
            this.importErrors.push(`${p.code}: 无有效行情数据`);
            this.importDoneCount++;
            continue;
          }
          const progressId = this.newPriceImportProgressId();
          this.startRowImportProgressPoll(progressId);
          try {
            await importSingleAssetFromMulti({
              code: p.code,
              name: p.name,
              prices: full.prices,
              overwrite_name: p.overwrite_name,
              replace_existing: p.replace_existing,
              progress_id: progressId,
              import_metric: 'close'
            });
          } catch (err) {
            this.importErrors.push(`${p.code}: ${err.response?.data?.detail || err.message || '导入失败'}`);
          } finally {
            this.stopRowImportProgressPoll();
          }
          this.importDoneCount++;
        }

        this.$message.success(`导入完成：${this.importDoneCount}/${this.previewAssets.length} 个资产`);
      } catch (err) {
        this.$message.error('导入失败：' + (err.response?.data?.detail || err.message || '未知错误'));
      } finally {
        this.importing = false;
        this.currentImportAsset = '';
        this.stopRowImportProgressPoll();
        this.rowImportDetailLine = '';
      }
    }
  }
};
</script>

<style scoped>
.multi-asset-import {
  padding: 10px;
}
.upload-card,
.preview-card,
.progress-card {
  margin-bottom: 16px;
}
</style>
