<template>
  <div class="knowledge-base">
    <!-- 顶部操作栏 -->
    <div class="toolbar">
      <el-input
        v-model="searchQuery"
        placeholder="搜索文档（关键词）..."
        prefix-icon="el-icon-search"
        clearable
        class="search-input"
        @keyup.enter.native="handleSearch"
        @clear="handleReset"
      />
      <el-select
        v-model="filterCategory"
        placeholder="全部分类"
        clearable
        class="category-select"
        @change="handleSearch"
      >
        <el-option
          v-for="(label, key) in categories"
          :key="key"
          :label="label"
          :value="key"
        />
      </el-select>
      <el-button type="primary" icon="el-icon-search" @click="handleSearch">搜索</el-button>
      <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
      <el-button type="success" icon="el-icon-plus" @click="openCreateDialog">录入文档</el-button>
      <el-button type="warning" icon="el-icon-upload2" @click="uploadVisible = true">上传文件</el-button>
    </div>

    <!-- 统计概览 -->
    <div class="stats-bar" v-if="stats">
      <span class="stat-item">
        <i class="el-icon-folder"></i> 共 <b>{{ stats.total }}</b> 篇文档
      </span>
      <span
        v-for="(item, key) in stats.categories"
        :key="key"
        class="stat-item"
        v-show="item.count > 0"
      >
        <el-tag size="mini" :type="categoryTagType(key)" effect="plain">{{ item.label }}</el-tag>
        {{ item.count }}
      </span>
    </div>

    <!-- 文档列表 -->
    <div v-loading="loading" class="document-list">
      <template v-if="documents.length > 0">
        <el-card
          v-for="doc in documents"
          :key="doc.id"
          class="doc-card"
          shadow="hover"
        >
          <div class="card-header">
            <span class="doc-title">{{ doc.title }}</span>
            <el-tag :type="categoryTagType(doc.category)" size="small" effect="plain">
              {{ categoryLabel(doc.category) }}
            </el-tag>
          </div>

          <div class="doc-summary">{{ doc.summary || '暂无摘要' }}</div>

          <div class="doc-tags" v-if="doc.tags && doc.tags.length">
            <el-tag
              v-for="(tag, idx) in doc.tags"
              :key="idx"
              size="mini"
              type="info"
              class="tag-item"
            >{{ tag }}</el-tag>
          </div>

          <div class="card-footer">
            <span class="update-time">
              <i class="el-icon-time"></i> {{ formatTime(doc.updated_at) }}
            </span>
            <span class="card-actions">
              <el-button type="text" size="small" @click="handleView(doc)">
                <i class="el-icon-view"></i> 查看
              </el-button>
              <el-button type="text" size="small" @click="handleEdit(doc)">
                <i class="el-icon-edit"></i> 编辑
              </el-button>
              <el-button type="text" size="small" class="delete-btn" @click="handleDelete(doc)">
                <i class="el-icon-delete"></i> 删除
              </el-button>
            </span>
          </div>
        </el-card>
      </template>

      <el-empty v-else-if="!loading" description="暂无知识文档">
        <el-button type="primary" size="small" @click="openCreateDialog">录入第一篇文档</el-button>
      </el-empty>
    </div>

    <!-- 分页 -->
    <div class="pagination-wrap" v-if="total > pageSize">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page.sync="currentPage"
        @current-change="fetchDocuments"
      />
    </div>

    <!-- 新增/编辑对话框 -->
    <el-dialog
      :title="isEdit ? '编辑文档' : '录入文档'"
      :visible.sync="formVisible"
      width="720px"
      append-to-body
      :close-on-click-modal="false"
    >
      <el-form :model="form" :rules="formRules" ref="docForm" label-width="90px">
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="文档标题" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="分类" prop="category">
          <el-select v-model="form.category" placeholder="选择分类" style="width: 100%">
            <el-option
              v-for="(label, key) in categories"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-select
            v-model="form.tags"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入标签后回车"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="关联资产">
          <el-select
            v-model="form.related_assets"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入资产代码后回车（如 000300.SH）"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input
            v-model="form.summary"
            type="textarea"
            :rows="2"
            placeholder="留空则自动从正文截取"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="正文" prop="content">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="12"
            placeholder="支持 Markdown 格式"
          />
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ isEdit ? '保存修改' : '确认录入' }}
        </el-button>
      </span>
    </el-dialog>

    <!-- 查看详情对话框 -->
    <el-dialog
      :title="currentDoc ? currentDoc.title : '文档详情'"
      :visible.sync="detailVisible"
      width="720px"
      append-to-body
    >
      <div v-if="currentDoc" class="detail-dialog">
        <div class="detail-meta">
          <el-tag :type="categoryTagType(currentDoc.category)" size="small" effect="plain">
            {{ categoryLabel(currentDoc.category) }}
          </el-tag>
          <span class="meta-time">更新于 {{ formatTime(currentDoc.updated_at) }}</span>
        </div>
        <div class="detail-tags" v-if="currentDoc.tags && currentDoc.tags.length">
          <el-tag
            v-for="(tag, idx) in currentDoc.tags"
            :key="idx"
            size="mini"
            type="info"
          >{{ tag }}</el-tag>
        </div>
        <el-divider />
        <div class="detail-content">{{ currentDoc.content }}</div>
      </div>
      <span slot="footer">
        <el-button @click="detailVisible = false">关闭</el-button>
      </span>
    </el-dialog>

    <!-- 文件上传对话框 -->
    <el-dialog
      title="上传文件录入"
      :visible.sync="uploadVisible"
      width="560px"
      append-to-body
      :close-on-click-modal="false"
    >
      <el-form label-width="90px">
        <el-form-item label="分类">
          <el-select v-model="uploadCategory" placeholder="选择分类" style="width: 100%">
            <el-option
              v-for="(label, key) in categories"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="uploadTags" placeholder="多个标签用逗号分隔（可选）" />
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            ref="fileUpload"
            drag
            action="#"
            :auto-upload="false"
            :limit="1"
            :on-change="handleFileChange"
            :on-exceed="handleFileExceed"
            accept=".pdf,.docx,.txt"
          >
            <i class="el-icon-upload"></i>
            <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em></div>
            <div class="el-upload__tip" slot="tip">支持 PDF / Word(.docx) / TXT，单个文件≤50MB</div>
          </el-upload>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!uploadFile" @click="handleUpload">
          确认上传
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import {
  getCategories,
  getDocuments,
  getDocument,
  createDocument,
  updateDocument,
  deleteDocument,
  uploadDocument,
  getKnowledgeStats
} from '@/api/knowledge'
import dayjs from 'dayjs'

const CATEGORY_TAG_MAP = {
  research_report: '',
  product_doc: 'success',
  strategy_note: 'warning',
  regulation: 'danger',
  meeting_note: 'info',
  market_commentary: ''
}

export default {
  name: 'KnowledgeBase',
  data() {
    return {
      // 搜索与筛选
      searchQuery: '',
      filterCategory: '',
      // 分类体系
      categories: {},
      // 列表数据
      documents: [],
      total: 0,
      currentPage: 1,
      pageSize: 10,
      loading: false,
      // 统计
      stats: null,
      // 表单对话框
      formVisible: false,
      isEdit: false,
      editId: '',
      submitting: false,
      form: {
        title: '',
        content: '',
        category: 'research_report',
        tags: [],
        summary: '',
        related_assets: []
      },
      formRules: {
        title: [{ required: true, message: '请输入文档标题', trigger: 'blur' }],
        category: [{ required: true, message: '请选择分类', trigger: 'change' }],
        content: [{ required: true, message: '请输入正文内容', trigger: 'blur' }]
      },
      // 详情对话框
      detailVisible: false,
      currentDoc: null,
      // 上传对话框
      uploadVisible: false,
      uploadCategory: 'research_report',
      uploadTags: '',
      uploadFile: null,
      uploading: false
    }
  },
  created() {
    this.fetchCategories()
    this.fetchDocuments()
    this.fetchStats()
  },
  methods: {
    async fetchCategories() {
      try {
        const res = await getCategories()
        if (res.code === 200) {
          this.categories = res.data
        }
      } catch (e) {
        console.error('获取分类失败', e)
      }
    },

    async fetchDocuments() {
      this.loading = true
      try {
        const res = await getDocuments({
          query: this.searchQuery,
          category: this.filterCategory,
          page: this.currentPage,
          page_size: this.pageSize
        })
        if (res.code === 200) {
          const data = res.data
          this.documents = data.items || []
          this.total = data.total || 0
        }
      } catch (e) {
        this.$message.error('获取文档列表失败')
      } finally {
        this.loading = false
      }
    },

    async fetchStats() {
      try {
        const res = await getKnowledgeStats()
        if (res.code === 200) {
          this.stats = res.data
        }
      } catch (e) {
        console.error('获取统计失败', e)
      }
    },

    handleSearch() {
      this.currentPage = 1
      this.fetchDocuments()
    },

    handleReset() {
      this.searchQuery = ''
      this.filterCategory = ''
      this.currentPage = 1
      this.fetchDocuments()
    },

    // ─── 新增/编辑 ───

    openCreateDialog() {
      this.isEdit = false
      this.editId = ''
      this.form = {
        title: '',
        content: '',
        category: 'research_report',
        tags: [],
        summary: '',
        related_assets: []
      }
      this.formVisible = true
      this.$nextTick(() => {
        this.$refs.docForm && this.$refs.docForm.clearValidate()
      })
    },

    async handleEdit(doc) {
      this.isEdit = true
      this.editId = doc.id
      // 加载完整文档
      try {
        const res = await getDocument(doc.id)
        if (res.code === 200) {
          const d = res.data
          this.form = {
            title: d.title || '',
            content: d.content || '',
            category: d.category || 'research_report',
            tags: d.tags || [],
            summary: d.summary || '',
            related_assets: d.related_assets || []
          }
        }
      } catch (e) {
        this.$message.error('加载文档详情失败')
        return
      }
      this.formVisible = true
      this.$nextTick(() => {
        this.$refs.docForm && this.$refs.docForm.clearValidate()
      })
    },

    handleSubmit() {
      this.$refs.docForm.validate(async (valid) => {
        if (!valid) return
        this.submitting = true
        try {
          let res
          if (this.isEdit) {
            res = await updateDocument(this.editId, this.form)
          } else {
            res = await createDocument(this.form)
          }
          if (res.code === 200) {
            this.$message.success(this.isEdit ? '文档已更新' : '文档录入成功')
            this.formVisible = false
            this.fetchDocuments()
            this.fetchStats()
          } else {
            this.$message.error(res.message || '操作失败')
          }
        } catch (e) {
          this.$message.error('操作失败: ' + (e.message || '网络错误'))
        } finally {
          this.submitting = false
        }
      })
    },

    // ─── 查看/删除 ───

    async handleView(doc) {
      try {
        const res = await getDocument(doc.id)
        if (res.code === 200) {
          this.currentDoc = res.data
          this.detailVisible = true
        }
      } catch (e) {
        this.$message.error('获取文档详情失败')
      }
    },

    handleDelete(doc) {
      this.$confirm(`确定删除文档「${doc.title}」？此操作不可恢复。`, '删除确认', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消'
      }).then(async () => {
        try {
          const res = await deleteDocument(doc.id)
          if (res.code === 200) {
            this.$message.success('文档已删除')
            this.fetchDocuments()
            this.fetchStats()
          } else {
            this.$message.error(res.message || '删除失败')
          }
        } catch (e) {
          this.$message.error('删除失败')
        }
      }).catch(() => {})
    },

    // ─── 文件上传 ───

    handleFileChange(file) {
      this.uploadFile = file.raw
    },

    handleFileExceed() {
      this.$message.warning('一次只能上传一个文件，请先移除已选文件')
    },

    async handleUpload() {
      if (!this.uploadFile) return
      this.uploading = true
      try {
        const res = await uploadDocument(this.uploadFile, {
          category: this.uploadCategory,
          tags: this.uploadTags
        })
        if (res.code === 200) {
          this.$message.success(res.message || '文件录入成功')
          this.uploadVisible = false
          this.uploadFile = null
          this.uploadTags = ''
          this.$refs.fileUpload && this.$refs.fileUpload.clearFiles()
          this.fetchDocuments()
          this.fetchStats()
        } else {
          this.$message.error(res.message || '上传失败')
        }
      } catch (e) {
        this.$message.error('上传失败: ' + (e.message || '网络错误'))
      } finally {
        this.uploading = false
      }
    },

    // ─── 工具方法 ───

    categoryLabel(key) {
      return this.categories[key] || key
    },

    categoryTagType(key) {
      return CATEGORY_TAG_MAP[key] || 'info'
    },

    formatTime(t) {
      if (!t) return '-'
      return dayjs(t).format('YYYY-MM-DD HH:mm')
    }
  }
}
</script>

<style scoped>
.knowledge-base {
  padding: 20px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.search-input {
  width: 260px;
}

.category-select {
  width: 150px;
}

.stats-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  padding: 10px 16px;
  background: #f8f9fa;
  border-radius: 6px;
  font-size: 13px;
  color: #606266;
  flex-wrap: wrap;
}

.stat-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.document-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
  min-height: 200px;
}

.doc-card {
  border-radius: 8px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.doc-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 70%;
}

.doc-summary {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 10px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.doc-tags {
  margin-bottom: 10px;
}

.tag-item {
  margin-right: 4px;
  margin-bottom: 4px;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid #f0f0f0;
  padding-top: 10px;
}

.update-time {
  font-size: 12px;
  color: #909399;
}

.delete-btn {
  color: #f56c6c;
}

.pagination-wrap {
  margin-top: 20px;
  text-align: center;
}

/* 详情对话框 */
.detail-dialog .detail-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.meta-time {
  font-size: 12px;
  color: #909399;
}

.detail-tags {
  margin-bottom: 8px;
}

.detail-tags .el-tag {
  margin-right: 4px;
}

.detail-content {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}
</style>
