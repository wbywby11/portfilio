<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">策略模型</h2>
      <div>
        <el-button type="primary" icon="el-icon-plus" @click="handleCreate">
          创建策略
        </el-button>
      </div>
    </div>

    <div class="page-content">
      <!-- 搜索栏 -->
      <el-form :inline="true" :model="searchForm" class="search-form">
        <el-form-item label="模型名称">
          <el-input v-model="searchForm.name" placeholder="请输入模型名称" clearable></el-input>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="searchForm.status" placeholder="请选择" clearable>
            <el-option label="草稿" value="草稿"></el-option>
            <el-option label="已发布" value="已发布"></el-option>
            <el-option label="已归档" value="已归档"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="模板">
          <el-select v-model="searchForm.template_code" placeholder="请选择模板" clearable>
            <el-option
              v-for="item in templateOptions"
              :key="item.code"
              :label="item.name"
              :value="item.code"
            ></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="el-icon-search" @click="handleSearch">查询</el-button>
          <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- 策略表格 -->
      <el-table
        :data="tableData"
        v-loading="loading"
        style="width: 100%"
        stripe
      >
        <el-table-column prop="name" label="策略名称" width="200"></el-table-column>
        <el-table-column prop="template_code" label="所用模板" width="150">
          <template slot-scope="scope">
            <el-tag size="small">{{ scope.row.template_code }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template slot-scope="scope">
            <el-tag :type="getStatusType(scope.row.status)" size="small">
              {{ getStatusLabel(scope.row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" show-overflow-tooltip></el-table-column>
        <el-table-column prop="backtest_result" label="回测结果" width="150">
          <template slot-scope="scope">
            <div v-if="scope.row.backtest_result">
              <span style="color: #67c23a;">
                年化收益: {{ (scope.row.backtest_result.annual_return * 100).toFixed(2) }}%
              </span>
              <br />
              <span style="color: #909399; font-size: 12px;">
                夏普: {{ scope.row.backtest_result.sharpe_ratio ? scope.row.backtest_result.sharpe_ratio.toFixed(2) : '-' }}
              </span>
            </div>
            <span v-else style="color: #909399;">未回测</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160">
          <template slot-scope="scope">
            {{ formatDate(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="small" @click="handleView(scope.row)">查看</el-button>
            <el-button
              type="text"
              size="small"
              @click="handleBacktest(scope.row)"
            >
              回测
            </el-button>
            <el-button
              type="text"
              size="small"
              @click="handlePublish(scope.row)"
              :disabled="scope.row.status === '已发布' || scope.row.status === 'published' || !scope.row.backtest_result"
            >
              发布
            </el-button>
            <el-button type="text" size="small" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button type="text" size="small" @click="handleDelete(scope.row)" style="color: #f56c6c;">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <el-pagination
        @size-change="handleSizeChange"
        @current-change="handleCurrentChange"
        :current-page="pagination.current"
        :page-sizes="[10, 20, 50, 100]"
        :page-size="pagination.pageSize"
        layout="total, sizes, prev, pager, next, jumper"
        :total="pagination.total"
        style="margin-top: 20px; text-align: right;"
      </el-pagination>
    </div>

    <!-- 回测配置对话框 -->
    <backtest-dialog
      v-model="backtestDialogVisible"
      :model-id="currentModelId"
      @success="handleBacktestSuccess"
    />
  </div>
</template>

<script>
import dayjs from 'dayjs';
import BacktestDialog from '@/components/BacktestDialog.vue';

export default {
  name: 'StrategyModelList',
  components: {
    BacktestDialog
  },
  data() {
    return {
      searchForm: {
        name: '',
        status: '',
        template_code: ''
      },
      tableData: [],
      templateOptions: [],
      loading: false,
      pagination: {
        current: 1,
        pageSize: 20,
        total: 0
      },
      backtestDialogVisible: false,
      currentModelId: ''
    };
  },
  created() {
    this.fetchTemplates();
    this.fetchData();
  },
  methods: {
    async fetchTemplates() {
      try {
        const res = await this.$store.dispatch('strategy/fetchTemplateList');
        this.templateOptions = res;
      } catch (error) {
        console.error('获取模板列表失败:', error);
      }
    },
    async fetchData() {
      this.loading = true;
      try {
        const res = await this.$store.dispatch('strategy/fetchStrategyModelList', {
          status: this.searchForm.status,
          template_code: this.searchForm.template_code
        });
        this.tableData = res;
        this.pagination.total = res.length;
      } catch (error) {
        this.$message.error('加载策略列表失败');
      } finally {
        this.loading = false;
      }
    },
    handleSearch() {
      this.pagination.current = 1;
      this.fetchData();
    },
    handleReset() {
      this.searchForm = {
        name: '',
        status: '',
        template_code: ''
      };
      this.fetchData();
    },
    handleCreate() {
      this.$router.push('/strategy/model/add');
    },
    handleView(row) {
      this.$router.push(`/strategy/model/detail/${row.id}`);
    },
    async handleBacktest(row) {
      this.currentModelId = row.id;
      this.backtestDialogVisible = true;
    },
    handleBacktestSuccess() {
      this.fetchData();
    },
    async handlePublish(row) {
      this.$confirm('确定要发布该策略模型吗？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('strategy/publishModel', row.id);
          this.$message.success('发布成功');
          this.fetchData();
        } catch (error) {
          this.$message.error('发布失败：' + (error.response?.data?.detail || error.message));
        }
      }).catch(() => {});
    },
    handleEdit(row) {
      this.$router.push(`/strategy/model/edit/${row.id}`);
    },
    handleDelete(row) {
      this.$confirm(`确定要删除策略 "${row.name}" 吗?`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('strategy/deleteStrategyModel', row.id);
          this.$message.success('删除成功');
          this.fetchData();
        } catch (error) {
          this.$message.error('删除失败：' + (error.response?.data?.detail || error.message));
        }
      }).catch(() => {});
    },
    handleSizeChange(val) {
      this.pagination.pageSize = val;
      this.fetchData();
    },
    handleCurrentChange(val) {
      this.pagination.current = val;
      this.fetchData();
    },
    getStatusType(status) {
      const map = {
        '草稿': 'info',
        '已发布': 'success',
        '已归档': '',
        // 兼容英文状态
        'draft': 'info',
        'published': 'success',
        'archived': ''
      };
      return map[status] || 'info';
    },
    getStatusLabel(status) {
      const map = {
        '草稿': '草稿',
        '已发布': '已发布',
        '已归档': '已归档',
        // 兼容英文状态
        'draft': '草稿',
        'published': '已发布',
        'archived': '已归档'
      };
      return map[status] || status;
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-';
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #303133;
  margin: 0;
}

.search-form {
  background: #fff;
  padding: 20px;
  margin-bottom: 20px;
  border-radius: 4px;
}
</style>
