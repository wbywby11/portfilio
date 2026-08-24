<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">策略库</h2>
      <div></div>
    </div>

    <div class="page-content">
      <!-- 搜索栏 -->
      <el-form :inline="true" class="search-form">
        <el-form-item>
          <el-input
            v-model="searchKeyword"
            placeholder="请输入策略名称或编码"
            clearable
            @clear="handleSearch"
            @keyup.enter.native="handleSearch"
            style="width: 300px;"
          >
            <el-button slot="append" icon="el-icon-search" @click="handleSearch"></el-button>
          </el-input>
        </el-form-item>
      </el-form>

      <!-- 策略列表（按分类分组） -->
      <template v-for="group in groupedTemplateList">
        <div :key="group.category" class="category-section" v-if="group.items.length > 0">
          <h3 class="category-title">
            <i :class="group.icon"></i>
            {{ group.label }}
            <span class="category-count">（{{ group.items.length }}）</span>
          </h3>
          <div class="template-grid">
            <div class="template-grid-item" v-for="template in group.items" :key="template.id">
              <el-card class="template-card" shadow="hover">
                <div slot="header" class="card-header">
                  <span class="template-name">{{ template.name }}</span>
                  <el-tag v-if="template.category" :type="getCategoryTagType(template.category)" size="mini">{{ getCategoryLabel(template.category) }}</el-tag>
                </div>
                
                <div class="card-content">
                  <el-tooltip
                    :content="template.description"
                    placement="top"
                    :disabled="!template.description"
                    :open-delay="300"
                  >
                    <p class="template-desc">{{ template.description || '暂无描述' }}</p>
                  </el-tooltip>

                  <div class="template-info">
                    <div class="info-item">
                      <span class="label">状态：</span>
                      <el-tag :type="template.is_active ? 'success' : 'info'" size="mini">
                        {{ template.is_active ? '已启用' : '已禁用' }}
                      </el-tag>
                    </div>
                  </div>

                  <div class="params-preview" v-if="template.parameters && template.parameters.length > 0">
                    <p class="section-title">参数定义（{{ template.parameters.length }}个）：</p>
                    <el-tag
                      v-for="param in template.parameters.slice(0, 3)"
                      :key="param.name"
                      size="mini"
                      style="margin-right: 8px; margin-bottom: 8px;"
                    >
                      {{ param.label || param.name }}
                    </el-tag>
                    <span v-if="template.parameters.length > 3" style="color: #909399; font-size: 12px;">
                      ...
                    </span>
                  </div>
                </div>

                <div class="card-actions">
                  <el-button size="small" type="text" @click="handleView(template)">
                    查看详情
                  </el-button>
                  <el-button size="small" type="text" @click="handleEdit(template)">
                    编辑
                  </el-button>
                  <el-button size="small" type="text" @click="handleUse(template)" style="color: #67c23a;">
                    使用模板
                  </el-button>

                </div>
              </el-card>
            </div>
          </div>
        </div>
      </template>

      <!-- 空状态 -->
      <el-empty v-if="filteredTemplateList.length === 0" :description="searchKeyword ? '没有找到匹配的策略' : '暂无策略数据'"></el-empty>
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

    <!-- 使用模板对话框 (创建策略) -->
    <el-dialog
      title="基于模板创建策略"
      :visible.sync="useTemplateDialogVisible"
      width="1000px"
      append-to-body
    >
      <strategy-model-form
        v-if="useTemplateDialogVisible"
        is-dialog
        :initial-template-code="currentTemplateCategory === 'allocation' ? currentTemplateCode : ''"
        :initial-selector-code="currentTemplateCategory === 'selection' ? currentTemplateCode : ''"
        :initial-controller-code="currentTemplateCategory === 'control' ? currentTemplateCode : ''"
        @success="handleUseSuccess"
        @close="useTemplateDialogVisible = false"
      />
    </el-dialog>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';
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
    TemplateForm: () => import('./TemplateForm.vue'),
    StrategyModelForm: () => import('./StrategyModelForm.vue')
  },
  data() {
    return {
      templateList: [],
      searchKeyword: '',  // 搜索关键词
      loading: false,
      detailDialogVisible: false,
      currentTemplate: null,
      pdfUrl: null,       // PDF 文档访问 URL
      pdfFullscreen: false, // PDF 全屏状态
      uploadingPdf: false,  // PDF 上传中
      deletingPdf: false,   // PDF 删除中
      formDialogVisible: false,
      currentTemplateCode: '',
      currentTemplateCategory: '',
      useTemplateDialogVisible: false
    };
  },
  computed: {
    // 过滤后的模板列表
    filteredTemplateList() {
      if (!this.searchKeyword) {
        return this.templateList;
      }
      const keyword = this.searchKeyword.toLowerCase().trim();
      return this.templateList.filter(template => {
        const name = (template.name || '').toLowerCase();
        const code = (template.code || '').toLowerCase();
        return name.includes(keyword) || code.includes(keyword);
      });
    },
    // 按分类分组的模板列表
    groupedTemplateList() {
      const list = this.filteredTemplateList;
      const allocation = list.filter(t => !t.category || t.category === 'allocation');
      const selection = list.filter(t => t.category === 'selection');
      const control = list.filter(t => t.category === 'control');
      return [
        { category: 'allocation', label: '配置策略', icon: 'el-icon-s-data', items: allocation },
        { category: 'selection', label: '资产选择策略', icon: 'el-icon-s-grid', items: selection },
        { category: 'control', label: '风险控制策略', icon: 'el-icon-s-check', items: control },
      ];
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
    handleSearch() {
      this.fetchData();
    },

    handleFormSuccess() {
      this.formDialogVisible = false;
      this.fetchData();
    },
    handleUseSuccess() {
      this.useTemplateDialogVisible = false;
      this.$message.success('策略创建成功');
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
    handleUse(template) {
      this.currentTemplateCode = template.code;
      this.currentTemplateCategory = template.category || 'allocation';
      this.useTemplateDialogVisible = true;
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-';
    },
    getParamTypeLabel(type) {
      const typeMap = {
        'number': '数字',
        'string': '文本',
        'boolean': '复选框',
        'select': '选择',
        'slider': '滑块',
        'dict': '字典(JSON)'
      };
      return typeMap[type] || type;
    },
    getCategoryLabel(category) {
      const map = { allocation: '配置', selection: '选择', control: '控制' };
      return map[category] || category;
    },
    getCategoryTagType(category) {
      const map = { allocation: '', selection: 'success', control: 'warning' };
      return map[category] || 'info';
    },
    getParamTypeTag(type) {
      const tagMap = {
        'number': '',
        'string': 'info',
        'boolean': 'warning',
        'select': 'success',
        'slider': 'primary',
        'dict': 'danger'
      };
      return tagMap[type] || '';
    }
  },
  beforeDestroy() {
    // 无需额外清理
  }
};
</script>

<style scoped>
/* 搜索表单样式 */
.search-form {
  margin-bottom: 20px;
}

/* 分类区域标题 */
.category-section {
  margin-bottom: 30px;
}

.category-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 16px 0;
  padding-bottom: 10px;
  border-bottom: 2px solid #e4e7ed;
  display: flex;
  align-items: center;
}

.category-title i {
  margin-right: 8px;
  color: #409eff;
}

.category-count {
  font-size: 14px;
  font-weight: normal;
  color: #909399;
}

/* 使用 CSS Grid 布局实现等高卡片；minmax(0,1fr) 防止长描述撑破列宽，auto-fill 按可用宽度自适应列数 */
.template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr));
  gap: 20px;
  margin-bottom: 20px;
}

.template-grid-item {
  display: flex;  /* 关键：让卡片填满高度 */
  min-width: 0;   /* 允许收缩，避免长内容撑破网格列 */
}

.template-card {
  width: 100%;  /* 占满宽度 */
  min-width: 0;
  transition: all 0.3s;
  display: flex;
  flex-direction: column;  /* 垂直布局 */
}

/* 让 el-card 内部使用 flex 布局 */
.template-card >>> .el-card__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0;  /* 移除默认 padding */
}

.template-card:hover {
  transform: translateY(-5px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 56px;
  gap: 8px;
}

.template-name {
  font-size: 16px;
  font-weight: bold;
  color: #303133;
  /* 限制名称最多两行 */
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
  max-height: 2.8em;
  word-break: break-word;  /* 允许换行 */
}

.card-content {
  flex: 1;  /* 关键：自动填充剩余空间 */
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.template-desc {
  color: #606266;
  line-height: 1.6;
  margin-bottom: 10px;
  /* 单行截断，全文悬浮展示 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: break-word;
}

.template-info {
  margin: 8px 0;
  flex-shrink: 0;  /* 不被压缩 */
}

.info-item {
  margin-bottom: 8px;
  font-size: 13px;
  height: 22px;  /* 固定行高 */
  line-height: 22px;
  /* 限制单行显示 */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.info-item .label {
  color: #909399;
}

.info-item .value {
  color: #606266;
}

.params-preview {
  margin-top: auto;  /* 关键：推到底部 */
  padding-top: 10px;
  min-height: 60px;  /* 固定最小高度 */
  flex-shrink: 0;  /* 不被压缩 */
}

.section-title {
  font-size: 13px;
  font-weight: bold;
  color: #606266;
  margin-bottom: 8px;
}

.card-actions {
  display: flex;
  justify-content: space-around;
  border-top: 1px solid #ebeef5;
  padding: 12px;
  height: 48px;  /* 固定高度 */
  flex-shrink: 0;  /* 不被压缩 */
}

/* 列数由 auto-fill 按宽度自适应，无需媒体查询断点 */

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
