<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">策略库</h2>
    </div>

    <div class="page-content">
      <!-- 工具栏：分类筛选 + 搜索 -->
      <div class="toolbar">
        <el-radio-group v-model="categoryFilter" size="small">
          <el-radio-button label="all">全部（{{ templateList.length }}）</el-radio-button>
          <el-radio-button label="allocation">配置策略（{{ categoryCounts.allocation }}）</el-radio-button>
          <el-radio-button label="selection">资产选择（{{ categoryCounts.selection }}）</el-radio-button>
          <el-radio-button label="control">风险控制（{{ categoryCounts.control }}）</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="searchKeyword"
          placeholder="输入策略名称或编码实时筛选"
          clearable
          prefix-icon="el-icon-search"
          style="width: 280px;"
        />
      </div>

      <!-- 策略列表 -->
      <vxe-table
        :data="tableData"
        :loading="loading"
        border
        stripe
        height="620"
        :scroll-y="{enabled: true, gt: 0}"
        show-overflow="tooltip"
        @row-click="handleRowClick"
      >
        <vxe-column field="code" title="编码" width="110"></vxe-column>
        <vxe-column field="name" title="策略名称" min-width="180">
          <template #default="{ row }">
            <span class="template-name-link">{{ row.name }}</span>
          </template>
        </vxe-column>
        <vxe-column title="分类" width="150" align="center">
          <template #default="{ row }">
            <el-tag :type="getCategoryTagType(row.category)" size="mini">{{ getCategoryLabel(row.category) }}</el-tag>
            <el-tag
              v-if="row.strategy_form === 'standalone'"
              type="danger"
              size="mini"
              effect="plain"
              class="form-tag"
            >独立策略</el-tag>
          </template>
        </vxe-column>
        <vxe-column field="description" title="策略描述" min-width="340"></vxe-column>
        <vxe-column title="参数" width="70" align="center">
          <template #default="{ row }">
            {{ row.parameters && row.parameters.length ? row.parameters.length + '个' : '—' }}
          </template>
        </vxe-column>
        <vxe-column title="文档" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.pdf_filename" size="mini" type="success">有</el-tag>
            <span v-else class="text-muted">—</span>
          </template>
        </vxe-column>
        <vxe-column title="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="mini">{{ row.is_active ? '已启用' : '已禁用' }}</el-tag>
          </template>
        </vxe-column>
        <vxe-column title="操作" width="140" fixed="right" align="center">
          <template #default="{ row }">
            <el-button size="mini" type="text" @click.stop="handleView(row)">查看详情</el-button>
            <el-button size="mini" type="text" @click.stop="handleEdit(row)">编辑</el-button>
          </template>
        </vxe-column>
      </vxe-table>

      <!-- 空状态 -->
      <el-empty
        v-if="!loading && tableData.length === 0"
        :description="(searchKeyword || categoryFilter !== 'all') ? '未找到匹配的策略，请调整筛选条件' : '暂无策略数据'"
      ></el-empty>
    </div>

    <!-- 详情对话框 -->
    <el-dialog
      :visible.sync="detailDialogVisible"
      :fullscreen="pdfFullscreen"
      :width="pdfFullscreen ? '' : '900px'"
      append-to-body
      :top="pdfFullscreen ? '0' : '5vh'"
      custom-class="pdf-detail-dialog"
      :show-close="false"
      @closed="onDetailClosed"
    >
      <!-- 自定义顶部标题栏 -->
      <div slot="title" class="pdf-dialog-header">
        <span class="pdf-dialog-title">{{ currentTemplate ? `${currentTemplate.name} - 策略说明` : '模板详情' }}</span>
        <div class="pdf-dialog-actions">
          <el-upload
            class="pdf-upload-inline"
            action="#"
            :http-request="handlePdfUpload"
            :before-upload="handlePdfBefore"
            :show-file-list="false"
            accept=".pdf"
          >
            <el-button
              :type="pdfUrl ? 'default' : 'primary'"
              :icon="pdfUrl ? 'el-icon-refresh' : 'el-icon-upload2'"
              size="mini"
              :loading="uploadingPdf"
            >{{ pdfUrl ? '替换PDF' : '上传PDF' }}</el-button>
          </el-upload>
          <el-button v-if="pdfUrl" type="primary" icon="el-icon-download" size="mini" @click="handleDownloadPdf">下载PDF</el-button>
          <el-button
            v-if="pdfUrl"
            type="danger"
            plain
            icon="el-icon-delete"
            size="mini"
            :loading="deletingPdf"
            @click="handleDeletePdf"
          >删除PDF</el-button>
          <el-button
            :type="pdfFullscreen ? 'info' : 'default'"
            :icon="pdfFullscreen ? 'el-icon-copy-document' : 'el-icon-full-screen'"
            size="mini"
            @click="pdfFullscreen = !pdfFullscreen"
          >{{ pdfFullscreen ? '退出全屏' : '全屏' }}</el-button>
          <el-button icon="el-icon-close" size="mini" @click="detailDialogVisible = false">关闭</el-button>
        </div>
      </div>
      <div v-if="currentTemplate" class="pdf-viewer-wrapper" :class="{'pdf-fullscreen': pdfFullscreen}">
        <pdf-viewer
          v-if="pdfUrl && detailDialogVisible"
          :url="pdfUrl"
        />
        <div v-else-if="!pdfUrl" class="pdf-empty-state" v-loading="uploadingPdf" element-loading-text="正在上传PDF…">
          <i class="el-icon-document" style="font-size: 48px; color: #c0c4cc;"></i>
          <p style="color: #909399; margin: 12px 0 20px;">该策略尚未上传说明文档（PDF）</p>
          <el-upload
            class="pdf-empty-upload"
            action="#"
            drag
            :http-request="handlePdfUpload"
            :before-upload="handlePdfBefore"
            :show-file-list="false"
            accept=".pdf"
          >
            <i class="el-icon-upload"></i>
            <div class="el-upload__text">将PDF文件拖到此处，或<em>点击上传</em></div>
          </el-upload>
          <p style="color: #c0c4cc; font-size: 12px; margin-top: 12px;">仅支持PDF格式，大小不超过50MB</p>
        </div>
      </div>
    </el-dialog>

    <!-- 模板表单对话框 -->
    <el-dialog
      title="编辑模板"
      :visible.sync="formDialogVisible"
      width="1000px"
      append-to-body
    >
      <template-form
        v-if="formDialogVisible"
        is-dialog
        :code="currentTemplateCode"
        @success="handleFormSuccess"
        @close="formDialogVisible = false"
      />
    </el-dialog>

  </div>
</template>

<script>
import PdfViewer from '@/components/PdfViewer.vue';
import { uploadTemplatePdf, deleteTemplatePdf } from '@/api/strategy';
import request from '@/utils/request';

// 与其他接口统一：从共享 axios 实例的 baseURL 派生后端地址（门户/服务配置注入的即此实例），
// 不再独立读 VUE_APP_BASE_URL 后回退 127.0.0.1，避免 PDF 预览绕开服务配置导致连接拒绝
const API_BASE = String(request.defaults.baseURL || process.env.VUE_APP_BASE_URL || '').replace(/\/$/, '');

export default {
  name: 'TemplateList',
  components: {
    PdfViewer,
    TemplateForm: () => import('./TemplateForm.vue')
  },
  data() {
    return {
      templateList: [],
      searchKeyword: '',     // 搜索关键词（客户端实时筛选）
      categoryFilter: 'all', // 分类筛选：all/allocation/selection/control
      loading: false,
      detailDialogVisible: false,
      currentTemplate: null,
      pdfUrl: null,       // PDF 文档访问 URL
      pdfFullscreen: false, // PDF 全屏状态
      uploadingPdf: false,  // PDF 上传中
      deletingPdf: false,   // PDF 删除中
      formDialogVisible: false,
      currentTemplateCode: ''
    };
  },
  computed: {
    // 各分类数量（基于全量列表，不受搜索影响）
    categoryCounts() {
      const count = c => this.templateList.filter(t => (t.category || 'allocation') === c).length;
      return {
        allocation: count('allocation'),
        selection: count('selection'),
        control: count('control')
      };
    },
    // 表格数据：分类筛选 + 关键词筛选（名称/编码）
    tableData() {
      let list = this.templateList;
      if (this.categoryFilter !== 'all') {
        list = list.filter(t => (t.category || 'allocation') === this.categoryFilter);
      }
      const keyword = this.searchKeyword.toLowerCase().trim();
      if (keyword) {
        list = list.filter(t => {
          const name = (t.name || '').toLowerCase();
          const code = (t.code || '').toLowerCase();
          return name.includes(keyword) || code.includes(keyword);
        });
      }
      return list;
    }
  },
  created() {
    this.fetchData();
  },
  methods: {
    async fetchData() {
      this.loading = true;
      try {
        // 列表加载时不包含源代码，提高性能
        const res = await this.$store.dispatch('strategy/fetchTemplateList');
        this.templateList = res;
      } catch (error) {
        this.$message.error('加载模板列表失败');
      } finally {
        this.loading = false;
      }
    },
    handleFormSuccess() {
      this.formDialogVisible = false;
      this.fetchData();
    },
    handleRowClick({ row }) {
      this.handleView(row);
    },
    async handleView(template) {
      // 加载模板详情并尝试获取PDF文档URL
      try {
        const fullTemplate = await this.$store.dispatch('strategy/fetchTemplate', template.code);
        this.currentTemplate = fullTemplate;
        this.pdfUrl = null;
        this.pdfFullscreen = false;
        this.detailDialogVisible = true;

        // 如果有 pdf_filename，直接构建URL
        if (fullTemplate.pdf_filename) {
          this.pdfUrl = `${API_BASE}/api/v1/model-templates/pdf/${fullTemplate.pdf_filename}`;
        }
      } catch (error) {
        this.$message.error('加载模板详情失败');
      }
    },
    onDetailClosed() {
      // 弹窗关闭后清理状态
      this.pdfUrl = null;
      this.currentTemplate = null;
    },
    /** 上传前校验：格式与大小与后端限制保持一致 */
    handlePdfBefore(file) {
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      if (!isPdf) {
        this.$message.error('仅支持PDF文件格式');
        return false;
      }
      if (file.size / 1024 / 1024 > 50) {
        this.$message.error(`文件大小不能超过50MB（当前 ${(file.size / 1024 / 1024).toFixed(1)}MB）`);
        return false;
      }
      return true;
    },
    /** 自定义上传：走 @/utils/request 统一拦截器，避开组件内硬编码接口地址 */
    async handlePdfUpload(options) {
      const templateId = this.currentTemplate && this.currentTemplate.id;
      if (!templateId) {
        this.$message.error('上传失败：未获取到模板ID，请关闭弹窗后重新打开详情');
        return;
      }
      const formData = new FormData();
      formData.append('file', options.file);
      this.uploadingPdf = true;
      try {
        const res = await uploadTemplatePdf(templateId, formData);
        const data = res.data || res;
        if (!data.pdf_filename) {
          throw new Error('接口未返回 pdf_filename');
        }
        this.$set(this.currentTemplate, 'pdf_filename', data.pdf_filename);
        // 后端固定以 {code}.pdf 命名，替换后 URL 不变；带时间戳强制 iframe 重新拉取，否则命中缓存仍显示旧文档
        this.pdfUrl = `${API_BASE}/api/v1/model-templates/pdf/${data.pdf_filename}?t=${Date.now()}`;
        this.$message.success(`上传成功：已为策略「${this.currentTemplate.name}」保存说明文档 ${data.pdf_filename}`);
        this.fetchData();
      } catch (error) {
        const detail = (error.response && error.response.data && error.response.data.detail) || error.message;
        this.$message.error(`上传失败：${detail || '请稍后重试'}`);
      } finally {
        this.uploadingPdf = false;
      }
    },
    /** 删除当前策略的 PDF 说明文档（同时清理磁盘文件与模板字段） */
    async handleDeletePdf() {
      const templateId = this.currentTemplate && this.currentTemplate.id;
      if (!templateId) {
        this.$message.error('删除失败：未获取到模板ID，请关闭弹窗后重新打开详情');
        return;
      }
      const templateName = this.currentTemplate.name || this.currentTemplate.code;
      try {
        await this.$confirm(`确定删除策略「${templateName}」的说明文档？此操作不可撤销`, '确认删除', {
          type: 'warning',
          confirmButtonText: '删除',
          cancelButtonText: '取消'
        });
      } catch (e) {
        return;  // 用户取消
      }
      this.deletingPdf = true;
      try {
        await deleteTemplatePdf(templateId);
        this.pdfUrl = null;
        this.$set(this.currentTemplate, 'pdf_filename', null);
        this.$message.success(`已删除策略「${templateName}」的说明文档`);
        this.fetchData();
      } catch (error) {
        const detail = (error.response && error.response.data && error.response.data.detail) || error.message;
        this.$message.error(`删除失败：${detail || '请稍后重试'}`);
      } finally {
        this.deletingPdf = false;
      }
    },
    handleDownloadPdf() {
      if (this.pdfUrl) {
        // 使用 fetch 获取 PDF blob，再触发下载（避免跨域下 link.download 失效）
        fetch(this.pdfUrl)
          .then(resp => resp.blob())
          .then(blob => {
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = (this.currentTemplate && this.currentTemplate.pdf_filename) || '策略说明.pdf';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
          })
          .catch(() => {
            // fallback：新标签页打开
            window.open(this.pdfUrl, '_blank');
          });
      }
    },
    handleEdit(template) {
      this.currentTemplateCode = template.code;
      this.formDialogVisible = true;
    },
    getCategoryLabel(category) {
      const map = { allocation: '配置', selection: '选择', control: '控制' };
      return map[category || 'allocation'] || category || '—';
    },
    getCategoryTagType(category) {
      const map = { allocation: '', selection: 'success', control: 'warning' };
      return map[category || 'allocation'] || 'info';
    }
  }
};
</script>

<style scoped>
/* 分类列的形态标签（独立策略）与分类标签拉开间距 */
.form-tag {
  margin-left: 4px;
}

/* 工具栏：分类筛选 + 搜索 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

/* 策略名称可点击感：整行可点进详情 */
.template-name-link {
  color: #303133;
  font-weight: 500;
  cursor: pointer;
}

.vxe-table ::v-deep .vxe-body--row {
  cursor: pointer;
}

.text-muted {
  color: #c0c4cc;
}

/* PDF 查看器样式 */
.pdf-viewer-wrapper {
  position: relative;
  height: 70vh;
  max-height: 800px;
}

.pdf-viewer-wrapper.pdf-fullscreen {
  flex: 1;
  min-height: 0;
  height: auto;
}

.pdf-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #909399;
  gap: 8px;
}

.pdf-loading i {
  font-size: 32px;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pdf-empty-state {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  background: #f5f7fa;
  border-radius: 6px;
}

/* 空态拖拽上传区 */
.pdf-empty-upload ::v-deep .el-upload-dragger {
  width: 420px;
  height: 160px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #fff;
}
.pdf-empty-upload ::v-deep .el-icon-upload {
  margin: 0 0 12px;
  font-size: 44px;
  line-height: 1;
}
</style>

<style>
/* PDF详情弹窗标题栏 */
.pdf-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.pdf-dialog-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 16px;
}
.pdf-dialog-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
/* 标题栏内联上传按钮：去除 el-upload 默认块级布局，与同行按钮对齐 */
.pdf-upload-inline {
  display: inline-flex;
  line-height: 1;
}

/* PDF详情弹窗全屏模式下的 body 高度自适应 */
.pdf-detail-dialog.is-fullscreen .el-dialog__body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.pdf-detail-dialog.is-fullscreen {
  display: flex;
  flex-direction: column;
  margin: 0 !important;
}
.pdf-detail-dialog.is-fullscreen .el-dialog__header {
  padding: 8px 16px;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
}

/* 非全屏模式也紧凑 header */
.pdf-detail-dialog .el-dialog__header {
  padding: 12px 20px;
}
.pdf-detail-dialog .el-dialog__body {
  padding: 12px 20px;
}

/* 隐藏不需要的 footer */
.pdf-detail-dialog .el-dialog__footer {
  display: none;
}
</style>
