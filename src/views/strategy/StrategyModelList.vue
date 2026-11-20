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
          <el-input v-model="searchForm.name" placeholder="请输入模型名称" clearable style="width: 160px;"></el-input>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="searchForm.status" placeholder="请选择" clearable style="width: 120px;">
            <el-option label="草稿" value="草稿"></el-option>
            <el-option label="发布" value="发布"></el-option>
            <el-option label="实盘" value="实盘"></el-option>
            <el-option label="已归档" value="已归档"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="策略">
          <el-select v-model="searchForm.template_code" placeholder="请选择策略" clearable style="width: 150px;">
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
        :scroll-x="{enabled: true, gt: 0}"
        :scroll-y="{enabled: true, gt: 0}"
        show-overflow="title"
      >
        <vxe-column field="name" title="策略名称" min-width="150" show-overflow="title"></vxe-column>
        <vxe-column field="template_code" title="所用模板" width="120">
          <template #default="{ row }">
            <el-tag size="small">
              {{ row.template_name || row.template_code }}
            </el-tag>
          </template>
        </vxe-column>
        <vxe-column field="status" title="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tooltip :content="getStatusHint(row)" placement="top" append-to-body>
              <el-tag :type="getStatusType(row)" size="small">
                {{ getStatusLabel(row) }}
              </el-tag>
            </el-tooltip>
          </template>
        </vxe-column>
        <vxe-column title="发布版本" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.published_version" style="font-weight: 600;">v{{ row.published_version }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="年化收益率（260日）" width="130" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary" :style="{color: (row.latest_backtest_summary.annual_return||0) >= 0 ? '#f56c6c' : '#67c23a'}">
              {{ formatPct(row.latest_backtest_summary.annual_return) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="年化收益率（365日）" width="130" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatPct(row.latest_backtest_summary.annual_return_365) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="年化波动率（260日）" width="130" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatPct(row.latest_backtest_summary.annual_vol) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="年化波动率（365日）" width="130" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatPct(row.latest_backtest_summary.annual_vol_365) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="夏普率（260日）" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary" :style="{color: (row.latest_backtest_summary.sharpe||0) >= 1 ? '#f56c6c' : (row.latest_backtest_summary.sharpe||0) >= 0 ? '#e6a23c' : '#67c23a', fontWeight: 600}">
              {{ formatNum(row.latest_backtest_summary.sharpe) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="夏普率（365日）" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatNum(row.latest_backtest_summary.sharpe_365) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="最大回撤" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary" style="color:#f56c6c">
              {{ formatPct(row.latest_backtest_summary.max_drawdown) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="回测区间" width="170" align="center">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary && row.latest_backtest_summary.start_date">
              {{ formatDateShort(row.latest_backtest_summary.start_date) }} ~ {{ formatDateShort(row.latest_backtest_summary.end_date) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column field="asset_codes" title="关联资产" width="90">
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
                <el-tag size="small" type="info">
                  {{ row.asset_codes.length }}个资产
                </el-tag>
              </template>
            </el-popover>
          </template>
        </vxe-column>
        <vxe-column title="操作" width="270" fixed="right" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="mini" type="text" @click.stop="handleView(row)">查看</el-button>
              <el-tooltip
                :content="isRowArchived(row) ? '已归档，不可编辑' : '已发布，配置已冻结；请先取消发布再编辑'"
                :disabled="!isRowPublished(row) && !isRowArchived(row)"
                placement="top"
              >
                <span>
                  <el-button
                    size="mini"
                    type="text"
                    :disabled="isRowPublished(row) || isRowArchived(row)"
                    @click.stop="handleEdit(row)"
                  >编辑</el-button>
                </span>
              </el-tooltip>
              <el-button
                v-if="isRowPublished(row)"
                size="mini"
                type="text"
                class="warn-btn"
                :disabled="!canRowUnpublish(row)"
                @click.stop="handleUnpublishRow(row)"
              >取消发布</el-button>
              <el-button
                v-else
                size="mini"
                type="text"
                :disabled="!canRowPublish(row)"
                @click.stop="handlePublish(row)"
              >发布</el-button>
              <el-button
                v-if="row.live_publish_enabled"
                size="mini"
                type="text"
                class="warn-btn"
                :disabled="!canRowLiveUnpublish(row)"
                @click.stop="handleLiveUnpublishRow(row)"
              >取消实盘</el-button>
              <el-button
                v-else
                size="mini"
                type="text"
                :disabled="!canRowLivePublish(row)"
                @click.stop="handleLivePublishRow(row)"
              >实盘发布</el-button>
              <el-button size="mini" type="text" class="danger-btn" @click.stop="handleDelete(row)">删除</el-button>
            </div>
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

export default {
  name: 'StrategyModelList',
  components: {
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
      currentModelId: '',
      detailDialogVisible: false,
      formDialogVisible: false,
      isEdit: false
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
        // 合并后的「发布 / 实盘」在后端同属已发布状态，实盘与否由 live_publish_enabled 区分
        const backendStatus = ['发布', '实盘'].includes(this.searchForm.status)
          ? '已发布'
          : this.searchForm.status;
        const res = await this.$store.dispatch('strategy/fetchStrategyModelList', {
          status: backendStatus,
          template_code: this.searchForm.template_code
        });
        let list = Array.isArray(res) ? res : [];
        // 列表接口无名称参数，名称关键字在前端过滤
        const keyword = (this.searchForm.name || '').trim();
        if (keyword) {
          list = list.filter(item => (item.name || '').includes(keyword));
        }
        if (this.searchForm.status === '发布') {
          list = list.filter(item => !item.live_publish_enabled);
        } else if (this.searchForm.status === '实盘') {
          list = list.filter(item => item.live_publish_enabled);
        }
        this.tableData = list;
        this.pagination.total = list.length;
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
      if (this.isRowPublished(row)) {
        this.$message.warning('策略已发布，配置已冻结；请先取消发布再编辑');
        return;
      }
      this.isEdit = true;
      this.currentModelId = row.id;
      this.formDialogVisible = true;
    },
    handleFormSuccess() {
      this.formDialogVisible = false;
      this.fetchData();
    },
    async handlePublish(row) {
      this.$confirm('确定要发布该策略模型吗？发布后模板、资产、参数、窗口、调仓频率将全部冻结，下游组合与回测均按此版本运行；如需修改必须先取消发布。', '发布', {
        confirmButtonText: '确定发布',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          this.loading = true;
          await this.$store.dispatch('strategy/publishModel', row.id);
          this.$message.success('发布成功，配置已冻结');
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
    canRowLiveUnpublish(row) {
      return !!row.live_publish_enabled && !this.isRowArchived(row);
    },
    canRowUnpublish(row) {
      return this.isRowPublished(row) && !this.isRowArchived(row);
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
          '确认实盘发布「' + (row.name || row.id) + '」？实盘后可在日常监控展示，次交易日生效；vol_scaled_budget + 混合动量策略可进入「日常监控」准入列表。',
          '实盘发布',
          { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
        );
      } catch {
        return;
      }
      try {
        await this.$store.dispatch('strategy/livePublishModel', {
          modelId: row.id,
          data: { source: 'strategy_model_list', operator: this.liveListOperator() }
        });
        this.$message.success('实盘发布成功');
        await this.fetchData();
      } catch (error) {
        this.$message.error(error.response?.data?.detail || error.message || '实盘发布失败');
      }
    },
    async handleLiveUnpublishRow(row) {
      if (!this.canRowLiveUnpublish(row)) return;
      try {
        await this.$confirm(
          '确认取消「' + (row.name || row.id) + '」的实盘？取消后将从日常监控下架，历史数据与操作记录保留。',
          '取消实盘',
          { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
        );
      } catch {
        return;
      }
      try {
        await this.$store.dispatch('strategy/liveUnpublishModel', {
          modelId: row.id,
          params: { source: 'strategy_model_list', operator: this.liveListOperator() }
        });
        this.$message.success('已取消实盘发布，监控已下架');
        await this.fetchData();
      } catch (error) {
        this.$message.error(error.response?.data?.detail || error.message || '操作失败');
      }
    },
    async handleUnpublishRow(row) {
      if (!this.canRowUnpublish(row)) return;
      const liveHint = row.live_publish_enabled
        ? '将先取消实盘并从日常监控下架；'
        : '';
      try {
        await this.$confirm(
          '确认取消发布「' + (row.name || row.id) + '」？' + liveHint +
          '若正被实盘组合使用，需先取消组合实盘并调整成员；模型回到草稿可编辑，版本号与历史记录保留。',
          '取消发布',
          { type: 'warning', confirmButtonText: '确定取消发布', cancelButtonText: '保留发布' }
        );
      } catch {
        return;
      }
      try {
        await this.$store.dispatch('strategy/unpublishModel', {
          modelId: row.id,
          params: { source: 'strategy_model_list', operator: this.liveListOperator() }
        });
        this.$message.success('已取消发布，模型回到草稿');
        await this.fetchData();
      } catch (error) {
        this.$message.error(error.response?.data?.detail || error.message || '取消发布失败');
      }
    },
    canRowPublish(row) {
      return !this.isRowPublished(row) && !this.isRowArchived(row);
    },
    handleDelete(row) {
      this.$confirm(`确定要删除策略 "${row.name}" 吗？若正被实盘组合使用将无法删除，此操作不可撤销。`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('strategy/deleteStrategyModel', row.id);
          this.$message.success('删除成功');
          this.fetchData();
        } catch (error) {
          // 409 = 被实盘组合引用等业务拦截，直接展示后端提示，避免重复前缀
          this.$message.error(error.response?.data?.detail || ('删除失败：' + (error.message || '未知错误')));
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
    // 状态合并：实盘 > 发布 > 已归档 > 草稿
    getStatusValue(row) {
      if (row.live_publish_enabled) return '实盘';
      if (this.isRowPublished(row)) return '发布';
      if (this.isRowArchived(row)) return '已归档';
      return '草稿';
    },
    getStatusType(row) {
      const map = {
        '草稿': 'info',
        '发布': '',
        '实盘': 'success',
        '已归档': 'warning'
      };
      const value = this.getStatusValue(row);
      return Object.prototype.hasOwnProperty.call(map, value) ? map[value] : 'info';
    },
    getStatusLabel(row) {
      return this.getStatusValue(row);
    },
    getStatusHint(row) {
      const map = {
        '草稿': '草稿：可自由编辑，尚不能用于组合',
        '发布': '发布：配置已冻结，可被组合引用；修改需先取消发布，被实盘组合引用时需先解除引用',
        '实盘': '实盘：已在日常监控展示；修改需先取消实盘再取消发布，被实盘组合引用时需先解除引用',
        '已归档': '已归档：不再参与组合与监控'
      };
      return map[this.getStatusValue(row)] || '';
    },
    formatDateShort(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '—';
    },
    formatPct(v) {
      if (v === null || v === undefined) return '—';
      const n = Number(v);
      if (isNaN(n)) return '—';
      return (n * 100).toFixed(2) + '%';
    },
    formatNum(v) {
      if (v === null || v === undefined) return '—';
      const n = Number(v);
      if (isNaN(n)) return '—';
      return n.toFixed(2);
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

.danger-btn {
  color: #f56c6c;
}

.warn-btn {
  color: #e6a23c;
}

.warn-btn.is-disabled,
.warn-btn.is-disabled:hover {
  color: #c0c4cc;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.row-actions ::v-deep .el-button + .el-button {
  margin-left: 0;
}

</style>
