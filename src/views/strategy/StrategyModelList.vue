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
      <vxe-table
        :data="tableData"
        :loading="loading"
        border
        stripe
        height="600"
        :scroll-y="{enabled: true, gt: 0}"
        show-overflow="title"
      >
        <vxe-column field="name" title="策略名称" min-width="200" show-overflow="title"></vxe-column>
        <vxe-column field="template_code" title="所用模板" width="150">
          <template #default="{ row }">
            <el-tag size="small">
              {{ row.template_name || row.template_code }}
            </el-tag>
          </template>
        </vxe-column>
        <vxe-column field="status" title="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusLabel(row.status) }}
            </el-tag>
          </template>
        </vxe-column>
        <vxe-column field="live_publish_enabled" title="实盘" width="108">
          <template #default="{ row }">
            <el-tag :type="row.live_publish_enabled ? 'success' : 'info'" size="small">
              {{ row.live_publish_enabled ? '已发布' : '未发布' }}
            </el-tag>
          </template>
        </vxe-column>
        <vxe-column field="asset_codes" title="关联资产" width="200">
          <template #default="{ row }">
            <el-popover
              placement="top-start"
              trigger="hover"
              :title="'资产列表'"
              :width="300"
            >
              <div v-for="assetCode in row.asset_codes" :key="assetCode" style="padding: 5px 0;">
                {{ assetCode }} - {{ row.asset_names && row.asset_names[assetCode] || '未知资产' }}
              </div>
              <template slot="reference">
                <el-tag size="small" type="info" style="margin-right: 5px;">
                  {{ row.asset_codes.length }}个资产
                </el-tag>
              </template>
            </el-popover>
          </template>
        </vxe-column>
        <vxe-column field="description" title="描述" min-width="150" show-overflow="title"></vxe-column>
        <vxe-column field="created_at" title="创建时间" width="160">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </vxe-column>
        <vxe-column title="操作" width="400" fixed="right">
          <template #default="{ row }">
            <el-button type="text" size="small" @click="handleView(row)">查看</el-button>
            <el-button
              type="text"
              size="small"
              @click="handleBacktest(row)"
            >
              回测
            </el-button>
            <el-button
              type="text"
              size="small"
              @click="handlePublish(row)"
              :disabled="row.status === '已发布' || row.status === 'published' || row.status === '已归档' || row.status === 'archived'"
            >
              发布
            </el-button>
            <el-button
              type="text"
              size="small"
              :disabled="!canRowLivePublish(row)"
              :loading="liveOpRowId === row.id && liveOpKind === 'publish'"
              @click="handleLivePublishRow(row)"
            >
              实盘发布
            </el-button>
            <el-button
              type="text"
              size="small"
              style="color: #e6a23c;"
              :disabled="!row.live_publish_enabled || isRowArchived(row)"
              :loading="liveOpRowId === row.id && liveOpKind === 'unpublish'"
              @click="handleLiveUnpublishRow(row)"
            >
              取消实盘
            </el-button>
            <el-button type="text" size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button type="text" size="small" @click="handleDelete(row)" style="color: #f56c6c;">
              删除
            </el-button>
          </template>
        </vxe-column>
      </vxe-table>

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
      />
    </div>

    <!-- 回测配置对话框 -->
    <backtest-dialog
      v-model="backtestDialogVisible"
      :model-id="currentModelId"
      @success="handleBacktestSuccess"
    />

    <!-- 策略详情弹窗 -->
    <el-dialog
      title="策略详情"
      :visible.sync="detailDialogVisible"
      width="1200px"
      append-to-body
    >
      <strategy-model-detail
        v-if="detailDialogVisible"
        is-dialog
        :id="currentModelId"
      />
    </el-dialog>

    <!-- 策略表窗弹窗 (新增/编辑) -->
    <el-dialog
      :title="isEdit ? '编辑策略' : '新建策略'"
      :visible.sync="formDialogVisible"
      width="1000px"
      append-to-body
    >
      <strategy-model-form
        v-if="formDialogVisible"
        is-dialog
        :id="currentModelId"
        @success="handleFormSuccess"
        @close="formDialogVisible = false"
      />
    </el-dialog>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import BacktestDialog from '@/components/BacktestDialog.vue';

export default {
  name: 'StrategyModelList',
  components: {
    BacktestDialog,
    StrategyModelDetail: () => import('./StrategyModelDetail.vue'),
    StrategyModelForm: () => import('./StrategyModelForm.vue')
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
      currentModelId: '',
      detailDialogVisible: false,
      formDialogVisible: false,
      isEdit: false,
      liveOpRowId: null,
      liveOpKind: ''
    };
  },
  created() {
    this.fetchTemplates();
    this.fetchData();
  },
  methods: {
    async fetchTemplates() {
      try {
        this.templateOptions = await this.$store.dispatch('strategy/fetchTemplateList');
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
      this.isEdit = false;
      this.currentModelId = '';
      this.formDialogVisible = true;
    },
    handleView(row) {
      this.currentModelId = row.id;
      this.detailDialogVisible = true;
    },
    handleEdit(row) {
      this.isEdit = true;
      this.currentModelId = row.id;
      this.formDialogVisible = true;
    },
    handleFormSuccess() {
      this.formDialogVisible = false;
      this.fetchData();
    },
    async handleBacktest(row) {
      this.currentModelId = row.id;
      this.backtestDialogVisible = true;
    },
    handleBacktestSuccess() {
      this.fetchData();
    },
    async handlePublish(row) {
      this.$confirm('确定要发布该策略模型吗？发布后策略将可以被其他模块使用。', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          this.loading = true;
          await this.$store.dispatch('strategy/publishModel', row.id);
          this.$message.success('发布成功');
          // 刷新列表以更新状态
          await this.fetchData();
        } catch (error) {
          console.error('发布失败:', error);
          const errorMsg = error.response?.data?.detail || error.response?.data?.message || error.message || '未知错误';
          this.$message.error('发布失败：' + errorMsg);
        } finally {
          this.loading = false;
        }
      }).catch(() => {
        // 用户取消操作
      });
    },
    isRowArchived(row) {
      return row.status === '已归档' || row.status === 'archived';
    },
    isRowPublished(row) {
      return row.status === '已发布' || row.status === 'published';
    },
    canRowLivePublish(row) {
      return this.isRowPublished(row) && !this.isRowArchived(row) && !row.live_publish_enabled;
    },
    liveListOperator() {
      return this.$store.getters['user/userName']
        || this.$store.state.user?.userInfo?.name
        || this.$store.state.user?.userInfo?.username
        || 'unknown';
    },
    async handleLivePublishRow(row) {
      if (!this.canRowLivePublish(row)) return;
      try {
        await this.$confirm(
          '确认实盘发布「' + (row.name || row.id) + '」？次交易日生效；risk_budget_target_vol + 混合动量策略可进入「日常监控」准入列表。',
          '实盘发布',
          { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
        );
      } catch {
        return;
      }
      this.liveOpRowId = row.id;
      this.liveOpKind = 'publish';
      try {
        await this.$store.dispatch('strategy/livePublishModel', {
          modelId: row.id,
          data: { source: 'strategy_model_list', operator: this.liveListOperator() }
        });
        this.$message.success('实盘发布成功');
        await this.fetchData();
      } catch (error) {
        this.$message.error(error.response?.data?.detail || error.message || '实盘发布失败');
      } finally {
        this.liveOpRowId = null;
        this.liveOpKind = '';
      }
    },
    async handleLiveUnpublishRow(row) {
      if (!row.live_publish_enabled || this.isRowArchived(row)) return;
      try {
        await this.$confirm(
          '确认取消「' + (row.name || row.id) + '」的实盘发布？',
          '取消实盘发布',
          { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
        );
      } catch {
        return;
      }
      this.liveOpRowId = row.id;
      this.liveOpKind = 'unpublish';
      try {
        await this.$store.dispatch('strategy/liveUnpublishModel', {
          modelId: row.id,
          params: { source: 'strategy_model_list', operator: this.liveListOperator() }
        });
        this.$message.success('已取消实盘发布');
        await this.fetchData();
      } catch (error) {
        this.$message.error(error.response?.data?.detail || error.message || '操作失败');
      } finally {
        this.liveOpRowId = null;
        this.liveOpKind = '';
      }
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
