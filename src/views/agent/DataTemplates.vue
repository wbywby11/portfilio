<template>
  <div class="data-templates">
    <div class="page-header">
      <h2>数据模板</h2>
      <el-button size="small" icon="el-icon-refresh" @click="loadTemplates">刷新</el-button>
    </div>

    <!-- 模板列表 -->
    <el-table :data="templates" v-loading="loading" stripe style="margin-top: 16px;">
      <el-table-column prop="display_name" label="模板名称" min-width="180" show-overflow-tooltip />
      <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
      <el-table-column label="步骤数" width="80" align="center">
        <template slot-scope="{ row }">{{ (row.steps || []).length }}</template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template slot-scope="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template slot-scope="{ row }">
          <el-button size="mini" type="primary" plain @click="showRunDialog(row)">运行</el-button>
          <el-button size="mini" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 空状态 -->
    <div v-if="!loading && templates.length === 0" class="empty-state">
      <i class="el-icon-data-analysis empty-icon"></i>
      <p>暂无数据模板，可在对话中使用数据加工功能后保存为模板</p>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="pagination-wrap">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page.sync="currentPage"
        @current-change="loadTemplates"
      />
    </div>

    <!-- 运行弹窗 -->
    <el-dialog
      :title="currentTemplate.display_name || '运行模板'"
      :visible.sync="runDialogVisible"
      width="80%"
      custom-class="run-dialog"
      :close-on-click-modal="false"
      @closed="onRunDialogClosed"
    >
      <!-- 参数表单 -->
      <div v-if="!runResult">
        <p style="color:#909399; margin-bottom: 16px;">{{ currentTemplate.description }}</p>
        <el-form
          v-if="(currentTemplate.parameters || []).length > 0"
          :model="runParams"
          label-width="120px"
        >
          <el-form-item
            v-for="param in currentTemplate.parameters"
            :key="param.name"
            :label="param.label || param.name"
            :required="param.required"
          >
            <el-select
              v-if="param.type === 'enum'"
              v-model="runParams[param.name]"
              placeholder="请选择"
              style="width: 100%;"
            >
              <el-option v-for="val in (param.values || [])" :key="val" :label="val" :value="val" />
            </el-select>
            <el-input-number
              v-else-if="param.type === 'number'"
              v-model="runParams[param.name]"
              style="width: 100%;"
            />
            <el-input v-else v-model="runParams[param.name]" />
          </el-form-item>
        </el-form>
        <div v-else style="color:#909399;">该模板无需额外参数，点击运行即可执行。</div>
      </div>

      <!-- 运行结果 -->
      <div v-else class="run-result">
        <!-- 步骤状态 -->
        <div v-for="step in runResult.step_results" :key="step.step" class="step-status">
          <i
            :class="step.success ? 'el-icon-success' : 'el-icon-error'"
            :style="{ color: step.success ? '#67C23A' : '#F56C6C' }"
          ></i>
          <span class="step-name">{{ step.name }}</span>
          <span class="step-summary">{{ step.summary }}</span>
        </div>

        <!-- 数据表格 -->
        <div v-for="step in runResult.step_results" :key="'data_' + step.step">
          <div v-if="step.data && step.data.records && step.data.records.length > 0" class="step-data-section">
            <h4>{{ step.name }}</h4>
            <chat-data-table
              :records="step.data.records"
              :summary="step.summary"
              :record-count="step.data.record_count"
              :data-shape="step.data.data_shape"
              :step-key="'step_' + step.step"
            />
          </div>
        </div>

        <!-- Markdown 报告 -->
        <el-collapse v-if="renderedMarkdown" style="margin-top: 16px;">
          <el-collapse-item title="总结报告" name="report">
            <div class="report-content" v-html="renderedMarkdown"></div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <div slot="footer">
        <el-button v-if="!runResult" @click="runDialogVisible = false">取消</el-button>
        <el-button v-if="!runResult" type="primary" :loading="executing" @click="handleRun">运行</el-button>
        <el-button v-if="runResult" @click="runDialogVisible = false">关闭</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import {
  getAnalysisTemplates,
  executeAnalysisTemplate,
  deleteAnalysisTemplate
} from '@/api/agent'
import ChatDataTable from '@/components/ChatDataTable.vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

export default {
  name: 'DataTemplates',
  components: { ChatDataTable },
  data() {
    return {
      loading: false,
      templates: [],
      total: 0,
      pageSize: 10,
      currentPage: 1,
      // 运行弹窗
      runDialogVisible: false,
      currentTemplate: {},
      runParams: {},
      executing: false,
      runResult: null
    }
  },
  computed: {
    renderedMarkdown() {
      if (!this.runResult || !this.runResult.rendered_content) return ''
      const html = marked(this.runResult.rendered_content)
      return DOMPurify.sanitize(html)
    }
  },
  created() {
    this.loadTemplates()
  },
  methods: {
    async loadTemplates() {
      this.loading = true
      try {
        const res = await getAnalysisTemplates({
          category: 'data_analysis',
          page: this.currentPage,
          page_size: this.pageSize
        })
        this.templates = res.data.items || res.data || []
        this.total = res.data.total || this.templates.length
      } catch (e) {
        this.$message.error('加载模板列表失败')
      } finally {
        this.loading = false
      }
    },

    formatTime(val) {
      if (!val) return '-'
      const d = new Date(val)
      return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    },

    showRunDialog(row) {
      this.currentTemplate = row
      this.runParams = {}
      // 填充默认值
      ;(row.parameters || []).forEach(p => {
        if (p.default !== undefined) {
          this.$set(this.runParams, p.name, p.default)
        } else {
          this.$set(this.runParams, p.name, '')
        }
      })
      this.runResult = null
      this.runDialogVisible = true
    },

    async handleRun() {
      this.executing = true
      try {
        const res = await executeAnalysisTemplate(this.currentTemplate.template_id || this.currentTemplate._id || this.currentTemplate.id, this.runParams)
        this.runResult = res.data
      } catch (e) {
        this.$message.error(e.response?.data?.detail || '执行失败')
      } finally {
        this.executing = false
      }
    },

    handleDelete(row) {
      this.$confirm('确定删除该数据模板？删除后不可恢复', '提示', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await deleteAnalysisTemplate(row.template_id || row._id || row.id)
          this.$message.success('已删除')
          this.loadTemplates()
        } catch (e) {
          this.$message.error('删除失败')
        }
      }).catch(() => {})
    },

    onRunDialogClosed() {
      this.runResult = null
      this.currentTemplate = {}
    }
  }
}
</script>

<style scoped>
.data-templates {
  padding: 24px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
}
.pagination-wrap {
  margin-top: 16px;
  text-align: right;
}
.empty-state {
  text-align: center;
  padding: 60px 0;
  color: #909399;
}
.empty-icon {
  font-size: 48px;
  color: #c0c4cc;
  margin-bottom: 12px;
}
.run-dialog {
  max-width: 900px;
}
.step-status {
  padding: 8px 0;
  display: flex;
  align-items: center;
  border-bottom: 1px solid #f0f0f0;
}
.step-status i {
  font-size: 18px;
  margin-right: 8px;
}
.step-name {
  font-weight: 500;
  margin-right: 12px;
}
.step-summary {
  color: #909399;
  font-size: 13px;
}
.step-data-section {
  margin-top: 16px;
  padding: 12px;
  background: #fafbfc;
  border-radius: 4px;
  border: 1px solid #ebeef5;
}
.step-data-section h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
}
.report-content {
  padding: 16px;
  background: #fafbfc;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  line-height: 1.6;
}
</style>
