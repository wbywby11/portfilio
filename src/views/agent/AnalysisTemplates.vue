<template>
  <div class="analysis-templates">
    <div class="page-header">
      <h2>分析模板</h2>
      <el-button type="primary" size="small" icon="el-icon-plus" @click="showCreateDialog">创建模板</el-button>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="filters.category" placeholder="分类" clearable size="small" style="width: 160px;" @change="loadTemplates">
        <el-option label="数据分析" value="data_analysis" />
        <el-option label="信用评级" value="credit_rating" />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" clearable size="small" style="width: 140px; margin-left: 12px;" @change="loadTemplates">
        <el-option label="启用" value="active" />
        <el-option label="已归档" value="archived" />
      </el-select>
      <el-button size="small" type="primary" icon="el-icon-search" style="margin-left: 12px;" @click="loadTemplates">查询</el-button>
      <el-button size="small" icon="el-icon-refresh" @click="resetFilters">重置</el-button>
    </div>

    <!-- 模板列表表格 -->
    <el-table :data="templates" v-loading="loading" stripe style="margin-top: 16px;">
      <el-table-column prop="display_name" label="模板名称" min-width="180" show-overflow-tooltip />
      <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
      <el-table-column label="参数" width="80" align="center">
        <template slot-scope="{ row }">{{ (row.parameters || []).length }}</template>
      </el-table-column>
      <el-table-column label="步骤" width="80" align="center">
        <template slot-scope="{ row }">{{ (row.steps || []).length }}</template>
      </el-table-column>
      <el-table-column label="标签" width="200">
        <template slot-scope="{ row }">
          <el-tag v-for="tag in (row.tags || []).slice(0, 3)" :key="tag" size="mini" style="margin-right:4px;">{{ tag }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="80">
        <template slot-scope="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="mini">
            {{ row.status === 'active' ? '启用' : '归档' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template slot-scope="{ row }">
          <el-button size="mini" type="primary" plain @click="showExecuteDialog(row)">执行</el-button>
          <el-button size="mini" plain @click="showEditDialog(row)">编辑</el-button>
          <el-button size="mini" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="pageSize" :current-page.sync="currentPage" @current-change="loadTemplates" />
    </div>

    <!-- 执行弹窗 -->
    <el-dialog title="执行分析模板" :visible.sync="executeDialogVisible" width="700px">
      <div v-if="!executeResult">
        <h4>{{ currentTemplate.display_name }}</h4>
        <p style="color:#909399;">{{ currentTemplate.description }}</p>
        <el-form :model="executeParams" label-width="120px" style="margin-top: 20px;">
          <el-form-item v-for="param in (currentTemplate.parameters || [])" :key="param.name" :label="param.label" :required="param.required">
            <el-select v-if="param.type === 'enum'" v-model="executeParams[param.name]" placeholder="请选择" style="width: 100%;">
              <el-option v-for="val in (param.values || [])" :key="val" :label="val" :value="val" />
            </el-select>
            <el-input v-else-if="param.type === 'string'" v-model="executeParams[param.name]" />
            <el-input-number v-else-if="param.type === 'number'" v-model="executeParams[param.name]" style="width: 100%;" />
            <el-input v-else v-model="executeParams[param.name]" />
          </el-form-item>
        </el-form>
      </div>
      <div v-else class="execute-result">
        <h4>执行完成</h4>
        <!-- 步骤执行进度 -->
        <div v-for="step in executeResult.step_results" :key="step.step" class="step-item">
          <i :class="step.success ? 'el-icon-success' : 'el-icon-error'" :style="{color: step.success ? '#67C23A' : '#F56C6C'}"></i>
          <span>{{ step.name }}</span>
          <span style="color:#909399; margin-left: 8px;">{{ step.summary }}</span>
        </div>
        <!-- 数据表格区域 -->
        <div v-for="step in executeResult.step_results" :key="'data_' + step.step">
          <div v-if="step.data && step.data.records && step.data.records.length > 0" class="step-data-section">
            <h4>{{ step.name }}</h4>
            <p class="step-summary">{{ step.summary }}</p>
            <chat-data-table
              :records="step.data.records"
              :summary="step.summary"
              :record-count="step.data.record_count"
              :data-shape="step.data.data_shape"
              :step-key="'step_' + step.step"
            />
          </div>
          <div v-else-if="step.summary" class="step-summary-only">
            <h4>{{ step.name }}</h4>
            <p>{{ step.summary }}</p>
          </div>
        </div>
        <!-- 总结报告（可折叠） -->
        <el-collapse v-if="renderedMarkdown" style="margin-top: 16px;">
          <el-collapse-item title="总结报告" name="report">
            <div class="report-content" v-html="renderedMarkdown" style="padding: 16px; background: #fafbfc; border-radius: 4px; border: 1px solid #e4e7ed;"></div>
          </el-collapse-item>
        </el-collapse>
      </div>
      <div slot="footer">
        <el-button v-if="!executeResult" @click="executeDialogVisible = false">取消</el-button>
        <el-button v-if="!executeResult" type="primary" :loading="executing" @click="handleExecute">执行</el-button>
        <el-button v-if="executeResult" @click="downloadMd">下载 Markdown</el-button>
        <el-button v-if="executeResult" @click="executeDialogVisible = false; executeResult = null;">关闭</el-button>
      </div>
    </el-dialog>

    <!-- 创建/编辑弹窗 -->
    <el-dialog :title="isEdit ? '编辑模板' : '创建模板'" :visible.sync="editDialogVisible" width="800px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="标识名" required><el-input v-model="editForm.name" placeholder="英文标识，如 asset_correlation" /></el-form-item>
        <el-form-item label="显示名" required><el-input v-model="editForm.display_name" placeholder="模板显示名称" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="editForm.description" type="textarea" :rows="2" placeholder="模板用途描述" /></el-form-item>
        <el-form-item label="标签"><el-input v-model="editForm.tags" placeholder="逗号分隔，如 数据分析, 相关性" /></el-form-item>

        <!-- 参数定义 -->
        <el-form-item label="参数定义">
          <div v-for="(param, idx) in editForm.parameters" :key="idx" class="dynamic-row">
            <el-input v-model="param.name" placeholder="参数名" size="small" style="width: 110px;" />
            <el-input v-model="param.label" placeholder="显示标签" size="small" style="width: 120px; margin-left: 8px;" />
            <el-select v-model="param.type" placeholder="类型" size="small" style="width: 100px; margin-left: 8px;">
              <el-option label="字符串" value="string" /><el-option label="数字" value="number" /><el-option label="枚举" value="enum" />
            </el-select>
            <el-input v-model="param.values" placeholder="枚举值(逗号分隔)" size="small" style="width: 140px; margin-left: 8px;" />
            <el-switch v-model="param.required" active-text="必填" size="small" style="margin-left: 8px;" />
            <el-input v-model="param.default" placeholder="默认值" size="small" style="width: 100px; margin-left: 8px;" />
            <el-button size="mini" type="danger" icon="el-icon-delete" circle style="margin-left: 8px;" @click="removeParam(idx)" />
          </div>
          <el-button size="small" icon="el-icon-plus" @click="addParam">增加参数</el-button>
        </el-form-item>

        <!-- 步骤定义 -->
        <el-form-item label="步骤定义">
          <div v-for="(step, idx) in editForm.steps" :key="'s'+idx" class="dynamic-row" style="flex-wrap: wrap;">
            <div style="display:flex; width:100%; margin-bottom:6px;">
              <el-input v-model="step.name" placeholder="步骤名称" size="small" style="width: 140px;" />
              <el-input v-model="step.tool" placeholder="工具名" size="small" style="width: 140px; margin-left: 8px;" />
              <el-input v-model="step.condition" placeholder="执行条件(可选)" size="small" style="width: 160px; margin-left: 8px;" />
              <el-button size="mini" type="danger" icon="el-icon-delete" circle style="margin-left: 8px;" @click="removeStep(idx)" />
            </div>
            <el-input v-model="step.tool_params" type="textarea" :rows="2" placeholder="工具参数 JSON" size="small" style="width: 100%;" />
          </div>
          <el-button size="small" icon="el-icon-plus" @click="addStep">增加步骤</el-button>
        </el-form-item>

        <el-form-item label="输出模板">
          <el-input v-model="editForm.output_template" type="textarea" :rows="6" :placeholder="'支持 {{ step_results[0].summary }} 等 Jinja2 插值和 Markdown 格式'" />
        </el-form-item>
      </el-form>
      <div slot="footer">
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import ChatDataTable from '@/components/ChatDataTable.vue'
import {
  getAnalysisTemplates, createAnalysisTemplate, getAnalysisTemplate,
  updateAnalysisTemplate, deleteAnalysisTemplate, executeAnalysisTemplate
} from '@/api/agent'

marked.setOptions({ breaks: true, gfm: true })

function sanitizeHtml(html) {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','br','hr','ul','ol','li','blockquote','pre','code','table','thead','tbody','tr','th','td','strong','em','del','a','img','span','div','sub','sup'],
    ALLOWED_ATTR: ['href','src','alt','title','class','target','rel'],
    ALLOW_DATA_ATTR: false
  })
}

export default {
  name: 'AnalysisTemplates',
  components: { ChatDataTable },
  data() {
    return {
      templates: [],
      loading: false,
      total: 0,
      currentPage: 1,
      pageSize: 20,
      filters: { category: '', status: '' },
      executeDialogVisible: false,
      currentTemplate: {},
      executeParams: {},
      executing: false,
      executeResult: null,
      renderedMarkdown: '',
      editDialogVisible: false,
      isEdit: false,
      editForm: {
        name: '', display_name: '', description: '', tags: '',
        parameters: [], steps: [], output_template: ''
      },
      saving: false
    }
  },
  created() {
    this.loadTemplates()
  },
  methods: {
    async loadTemplates() {
      this.loading = true
      try {
        const params = { page: this.currentPage, page_size: this.pageSize }
        if (this.filters.category) params.category = this.filters.category
        if (this.filters.status) params.status = this.filters.status
        const res = await getAnalysisTemplates(params)
        const data = res.data || res
        this.templates = data.items || data.templates || []
        this.total = data.total || this.templates.length
      } catch (e) {
        console.error('加载模板列表失败:', e)
        this.$message.error('加载模板列表失败')
      } finally {
        this.loading = false
      }
    },

    resetFilters() {
      this.filters = { category: '', status: '' }
      this.currentPage = 1
      this.loadTemplates()
    },

    showExecuteDialog(template) {
      this.currentTemplate = template
      this.executeParams = {}
      for (const p of (template.parameters || [])) {
        this.$set(this.executeParams, p.name, p.default !== undefined ? p.default : '')
      }
      this.executeResult = null
      this.renderedMarkdown = ''
      this.executeDialogVisible = true
    },

    async handleExecute() {
      this.executing = true
      try {
        const res = await executeAnalysisTemplate(this.currentTemplate.template_id || this.currentTemplate._id || this.currentTemplate.id, this.executeParams)
        const data = res.data || res
        this.executeResult = data
        const md = data.rendered_content || data.output || data.content || ''
        this.renderedMarkdown = this.renderMd(md)
        this.$message.success('执行完成')
      } catch (e) {
        console.error('执行模板失败:', e)
        this.$message.error('执行失败')
      } finally {
        this.executing = false
      }
    },

    downloadMd() {
      const content = this.executeResult.rendered_content || this.executeResult.output || this.executeResult.content || ''
      const name = this.currentTemplate.display_name || '分析结果'
      const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name + '.md'
      a.click()
      URL.revokeObjectURL(url)
    },

    showCreateDialog() {
      this.isEdit = false
      this.editForm = { name: '', display_name: '', description: '', tags: '', parameters: [], steps: [], output_template: '' }
      this.editDialogVisible = true
    },

    async showEditDialog(template) {
      this.isEdit = true
      try {
        const res = await getAnalysisTemplate(template.template_id || template._id || template.id)
        const data = res.data || res
        this.editForm = {
          template_id: data.template_id || data.id,
          name: data.name || '',
          display_name: data.display_name || '',
          description: data.description || '',
          tags: Array.isArray(data.tags) ? data.tags.join(',') : (data.tags || ''),
          parameters: (data.parameters || []).map(p => ({
            name: p.name, label: p.label, type: p.type, values: Array.isArray(p.values) ? p.values.join(',') : (p.values || ''),
            required: !!p.required, default: p.default !== undefined ? String(p.default) : ''
          })),
          steps: (data.steps || []).map(s => ({
            name: s.name, tool: s.tool, tool_params: typeof s.tool_params === 'object' ? JSON.stringify(s.tool_params, null, 2) : (s.tool_params || ''),
            condition: s.condition || ''
          })),
          output_template: data.output_template || ''
        }
        this.editDialogVisible = true
      } catch (e) {
        console.error('获取模板详情失败:', e)
        this.$message.error('获取模板详情失败')
      }
    },

    addParam() {
      this.editForm.parameters.push({ name: '', label: '', type: 'string', values: '', required: false, default: '' })
    },

    removeParam(idx) {
      this.editForm.parameters.splice(idx, 1)
    },

    addStep() {
      this.editForm.steps.push({ name: '', tool: '', tool_params: '{}', condition: '' })
    },

    removeStep(idx) {
      this.editForm.steps.splice(idx, 1)
    },

    async handleSave() {
      if (!this.editForm.name || !this.editForm.display_name) {
        this.$message.warning('请填写标识名和显示名')
        return
      }
      const payload = {
        name: this.editForm.name,
        display_name: this.editForm.display_name,
        description: this.editForm.description,
        tags: this.editForm.tags ? this.editForm.tags.split(',').map(s => s.trim()).filter(Boolean) : [],
        parameters: this.editForm.parameters.map(p => ({
          name: p.name, label: p.label, type: p.type,
          values: p.type === 'enum' && p.values ? p.values.split(',').map(s => s.trim()).filter(Boolean) : undefined,
          required: !!p.required, default: p.default || undefined
        })),
        steps: this.editForm.steps.map(s => ({
          name: s.name, tool: s.tool,
          tool_params: s.tool_params ? (() => { try { return JSON.parse(s.tool_params) } catch { return s.tool_params } })() : {},
          condition: s.condition || undefined
        })),
        output_template: this.editForm.output_template
      }
      this.saving = true
      try {
        if (this.isEdit) {
          await updateAnalysisTemplate(this.editForm.template_id, payload)
          this.$message.success('更新成功')
        } else {
          await createAnalysisTemplate(payload)
          this.$message.success('创建成功')
        }
        this.editDialogVisible = false
        this.loadTemplates()
      } catch (e) {
        console.error('保存模板失败:', e)
        this.$message.error('保存失败')
      } finally {
        this.saving = false
      }
    },

    handleDelete(row) {
      this.$confirm(`确定要删除模板「${row.display_name || row.name}」吗？`, '提示', {
        confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
      }).then(async () => {
        try {
          await deleteAnalysisTemplate(row.template_id || row._id || row.id)
          this.$message.success('删除成功')
          this.loadTemplates()
        } catch (e) {
          console.error('删除模板失败:', e)
          this.$message.error('删除失败')
        }
      }).catch(() => {})
    },

    renderMd(text) {
      if (!text) return ''
      try { return sanitizeHtml(marked.parse(text)) } catch { return text }
    }
  }
}
</script>

<style scoped>
.analysis-templates {
  padding: 0 4px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
  color: #303133;
}
.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
.dynamic-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
}
.step-item {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
}
.step-item i {
  font-size: 16px;
  margin-right: 6px;
}
.report-content >>> h1,
.report-content >>> h2,
.report-content >>> h3 {
  margin: 12px 0 8px;
  font-weight: 600;
}
.report-content >>> p {
  margin: 4px 0;
}
.report-content >>> ul,
.report-content >>> ol {
  padding-left: 20px;
  margin: 4px 0;
}
.report-content >>> code {
  background: #e8eaed;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 13px;
}
.report-content >>> pre {
  background: #282c34;
  color: #abb2bf;
  padding: 14px 16px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
}
.report-content >>> table {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
}
.report-content >>> th,
.report-content >>> td {
  border: 1px solid #dcdfe6;
  padding: 6px 10px;
  text-align: left;
  font-size: 13px;
}
.report-content >>> th {
  background: #f5f7fa;
  font-weight: 600;
}
.step-data-section {
  margin-bottom: 20px;
}
.step-data-section h4 {
  margin: 10px 0;
  color: #303133;
  font-size: 14px;
}
.step-summary {
  color: #909399;
  font-size: 12px;
  margin-bottom: 8px;
}
.step-summary-only {
  margin-bottom: 16px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 4px;
}
.step-summary-only h4 {
  margin: 0 0 6px;
  font-size: 14px;
  color: #303133;
}
.step-summary-only p {
  margin: 0;
  color: #606266;
  font-size: 13px;
}
</style>
