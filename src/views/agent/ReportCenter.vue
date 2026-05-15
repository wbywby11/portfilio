<template>
  <div class="report-center">
    <div class="page-header">
      <h2>报告中心</h2>
      <p class="page-desc">管理 AI 生成的所有研究报告</p>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select
        v-model="filters.template_type"
        placeholder="报告类型"
        clearable
        size="small"
        style="width: 160px;"
      >
        <el-option label="定期报告" value="periodic" />
        <el-option label="尽职调查" value="due_diligence" />
        <el-option label="投资决策" value="investment_decision" />
        <el-option label="产品运作" value="product_review" />
        <el-option label="合规检查" value="compliance" />
        <el-option label="策略研究" value="strategy_research" />
      </el-select>
      <el-select
        v-model="filters.status"
        placeholder="状态"
        clearable
        size="small"
        style="width: 140px; margin-left: 12px;"
      >
        <el-option label="草稿" value="draft" />
        <el-option label="已填充" value="filled" />
        <el-option label="审查中" value="under_review" />
        <el-option label="已批准" value="approved" />
      </el-select>
      <el-button size="small" type="primary" icon="el-icon-search" style="margin-left: 12px;" @click="loadReports">
        查询
      </el-button>
      <el-button size="small" icon="el-icon-refresh" @click="resetFilters">重置</el-button>
    </div>

    <!-- 报告列表 -->
    <el-table :data="reports" v-loading="loading" stripe style="margin-top: 16px;">
      <el-table-column prop="title" label="报告标题" min-width="200" show-overflow-tooltip />
      <el-table-column prop="template_type" label="类型" width="120">
        <template slot-scope="{ row }">
          <el-tag size="mini">{{ typeLabels[row.template_type] || row.template_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template slot-scope="{ row }">
          <el-tag size="mini" :type="statusTagType(row.status)">{{ statusLabels[row.status] || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="content_length" label="内容长度" width="110">
        <template slot-scope="{ row }">
          <span v-if="row.content_length">{{ row.content_length }} 字符</span>
          <span v-else style="color: #c0c4cc;">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180">
        <template slot-scope="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template slot-scope="{ row }">
          <el-button size="mini" type="text" icon="el-icon-download" @click="handleDownload(row)">下载</el-button>
          <el-button size="mini" type="text" icon="el-icon-delete" style="color: #F56C6C;" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page.sync="currentPage"
        @current-change="loadReports"
      />
    </div>
  </div>
</template>

<script>
import { getReports, getReport, deleteReport, exportReport } from '@/api/agent'

export default {
  name: 'ReportCenter',
  data() {
    return {
      reports: [],
      loading: false,
      total: 0,
      currentPage: 1,
      pageSize: 20,
      filters: {
        template_type: '',
        status: ''
      },
      typeLabels: {
        periodic: '定期报告',
        due_diligence: '尽职调查',
        investment_decision: '投资决策',
        product_review: '产品运作',
        compliance: '合规检查',
        strategy_research: '策略研究'
      },
      statusLabels: {
        draft: '草稿',
        filled: '已填充',
        under_review: '审查中',
        approved: '已批准'
      }
    }
  },
  created() {
    this.loadReports()
  },
  methods: {
    async loadReports() {
      this.loading = true
      try {
        const params = {
          page: this.currentPage,
          page_size: this.pageSize
        }
        if (this.filters.template_type) params.template_type = this.filters.template_type
        if (this.filters.status) params.status = this.filters.status

        const res = await getReports(params)
        const data = res.data || res
        this.reports = data.items || data.reports || []
        this.total = data.total || this.reports.length
      } catch (e) {
        console.error('加载报告列表失败:', e)
        this.$message.error('加载报告列表失败')
      } finally {
        this.loading = false
      }
    },

    resetFilters() {
      this.filters.template_type = ''
      this.filters.status = ''
      this.currentPage = 1
      this.loadReports()
    },

    async handleDownload(row) {
      try {
        // 优先尝试调用导出接口
        const res = await exportReport(row.report_id)
        const data = res.data || res
        const content = data.content || data.rendered_content || data.markdown || ''
        if (!content) {
          this.$message.warning('报告内容为空，无法下载')
          return
        }
        this.downloadMd(content, row.title || '报告')
      } catch (e) {
        // 导出接口不可用时，尝试用详情接口
        try {
          const detail = await getReport(row.report_id)
          const d = detail.data || detail
          const content = d.content || d.rendered_content || ''
          if (!content) {
            this.$message.warning('报告内容为空，无法下载')
            return
          }
          this.downloadMd(content, row.title || '报告')
        } catch (err) {
          console.error('下载报告失败:', err)
          this.$message.error('下载报告失败')
        }
      }
    },

    downloadMd(content, title) {
      const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = (title || '报告') + '.md'
      a.click()
      URL.revokeObjectURL(url)
    },

    handleDelete(row) {
      this.$confirm(`确定要删除报告「${row.title || row.report_id}」吗？`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await deleteReport(row.report_id)
          this.$message.success('删除成功')
          this.loadReports()
        } catch (e) {
          console.error('删除报告失败:', e)
          this.$message.error('删除失败')
        }
      }).catch(() => {})
    },

    statusTagType(status) {
      const map = { draft: 'info', filled: '', under_review: 'warning', approved: 'success' }
      return map[status] || 'info'
    },

    formatDate(dateStr) {
      if (!dateStr) return '—'
      try {
        const d = new Date(dateStr)
        const pad = (n) => String(n).padStart(2, '0')
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
      } catch (e) {
        return dateStr
      }
    }
  }
}
</script>

<style scoped>
.report-center {
  padding: 0 4px;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
  color: #303133;
}

.page-desc {
  margin: 0;
  font-size: 13px;
  color: #909399;
}

.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
