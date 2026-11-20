<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">组合管理</h2>
      <div>
        <el-button type="primary" icon="el-icon-plus" @click="handleCreate">
          创建组合
        </el-button>
      </div>
    </div>

    <div class="page-content">
      <!-- 搜索栏 -->
      <el-form :inline="true" :model="searchForm" class="search-form">
        <el-form-item label="来源类型">
          <el-select v-model="searchForm.source" placeholder="全部" clearable size="small" style="width: 150px;">
            <el-option label="手工创建" value="manual"></el-option>
            <el-option label="单策略驱动" value="single_strategy"></el-option>
            <el-option label="组合模型" value="portfolio_model"></el-option>
          </el-select>
        </el-form-item>
      </el-form>

      <!-- 组合表格 -->
      <vxe-table
        :data="filteredData"
        :loading="loading"
        border
        stripe
        height="600"
        :scroll-x="{enabled: true, gt: 0}"
        :scroll-y="{enabled: true, gt: 0}"
        show-overflow="title"
      >
        <vxe-column field="name" title="组合名称" min-width="200" show-overflow="title"></vxe-column>
        <vxe-column field="source" title="来源类型" width="120">
          <template #default="{ row }">
            <el-tag :type="getSourceTagType(resolveSource(row))" size="small">
              {{ getSourceLabel(resolveSource(row)) }}
            </el-tag>
          </template>
        </vxe-column>
        <vxe-column title="子策略" width="80" align="center">
          <template #default="{ row }">
            <span v-if="row.sub_strategies && row.sub_strategies.length">
              {{ row.sub_strategies.length }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="实盘状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.live_publish_enabled ? 'success' : 'info'" size="small">
              {{ row.live_publish_enabled ? '实盘中' : '未实盘' }}
            </el-tag>
          </template>
        </vxe-column>
        <vxe-column title="年化收益率（260日）" width="140" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary" :style="{color: (row.latest_backtest_summary.annual_return||0) >= 0 ? '#f56c6c' : '#67c23a'}">
              {{ formatPct(row.latest_backtest_summary.annual_return) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="年化收益率（365日）" width="140" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatPct(row.latest_backtest_summary.annual_return_365) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="年化波动率（260日）" width="140" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatPct(row.latest_backtest_summary.annual_vol) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="年化波动率（365日）" width="140" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatPct(row.latest_backtest_summary.annual_vol_365) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="夏普率（260日）" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary" :style="{color: (row.latest_backtest_summary.sharpe||0) >= 1 ? '#f56c6c' : (row.latest_backtest_summary.sharpe||0) >= 0 ? '#e6a23c' : '#67c23a', fontWeight: 600}">
              {{ formatNum(row.latest_backtest_summary.sharpe) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="夏普率（365日）" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatNum(row.latest_backtest_summary.sharpe_365) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="最大回撤" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary" style="color:#f56c6c">
              {{ formatPct(row.latest_backtest_summary.max_drawdown) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="回测区间" width="180" align="center">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary && row.latest_backtest_summary.start_date">
              {{ formatDateShort(row.latest_backtest_summary.start_date) }} ~ {{ formatDateShort(row.latest_backtest_summary.end_date) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="操作" width="200" fixed="right" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="mini" type="text" @click.stop="handleView(row)">详情</el-button>
              <el-tooltip
                :content="row.live_publish_enabled ? '组合已实盘，配置已冻结；请先取消实盘再编辑' : '编辑组合配置'"
                placement="top"
              >
                <span>
                  <el-button size="mini" type="text" :disabled="!!row.live_publish_enabled" @click.stop="handleEdit(row)">编辑</el-button>
                </span>
              </el-tooltip>
              <el-button
                v-if="row.live_publish_enabled"
                size="mini"
                type="text"
                class="warn-btn"
                :disabled="!canLiveUnpublish(row)"
                @click.stop="handleLiveUnpublish(row)"
              >取消实盘</el-button>
              <el-button
                v-else
                size="mini"
                type="text"
                :disabled="!canLivePublish(row)"
                @click.stop="handleLivePublish(row)"
              >实盘发布</el-button>
              <el-button size="mini" type="text" class="danger-btn" @click.stop="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </vxe-column>
      </vxe-table>

      <el-empty v-if="filteredData.length === 0 && !loading" description="暂无组合，点击上方按钮创建"></el-empty>
    </div>

    <!-- 详情弹窗 -->
    <el-dialog title="组合详情" :visible.sync="detailDialogVisible" width="1200px" append-to-body>
      <portfolio-detail v-if="detailDialogVisible" is-dialog :id="currentId" />
    </el-dialog>

    <!-- 创建弹窗 -->
    <el-dialog
      title="创建组合"
      :visible.sync="createDialogVisible"
      width="1000px"
      append-to-body
    >
      <portfolio-create
        v-if="createDialogVisible"
        is-dialog
        @success="handleCreateSuccess"
        @close="createDialogVisible = false"
      />
    </el-dialog>

    <!-- 编辑弹窗 -->
    <el-dialog
      title="编辑组合"
      :visible.sync="editDialogVisible"
      width="1000px"
      append-to-body
    >
      <portfolio-create
        v-if="editDialogVisible"
        is-dialog
        :id="editId"
        @success="handleEditSuccess"
        @close="editDialogVisible = false"
      />
    </el-dialog>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import { livePublishModel, liveUnpublishModel } from '@/api/strategy';

export default {
  name: 'PortfolioList',
  components: {
    PortfolioDetail: () => import('./PortfolioDetail.vue'),
    PortfolioCreate: () => import('./PortfolioCreate.vue')
  },
  data() {
    return {
      searchForm: {
        source: ''
      },
      tableData: [],
      loading: false,
      detailDialogVisible: false,
      currentId: '',
      createDialogVisible: false,
      editDialogVisible: false,
      editId: null
    };
  },
  computed: {
    filteredData() {
      let data = this.tableData;
      if (this.searchForm.source) {
        data = data.filter(d => this.resolveSource(d) === this.searchForm.source);
      }
      return data;
    }
  },
  created() {
    this.fetchData();
  },
  methods: {
    async fetchData() {
      this.loading = true;
      try {
        const list = await this.$store.dispatch('portfolio/fetchPortfolioList');
        this.tableData = list;
      } catch (error) {
        this.$message.error('加载组合列表失败');
      } finally {
        this.loading = false;
      }
    },
    handleSearch() {
      // filteredData 是计算属性，会自动响应
    },
    handleCreate() {
      // 组件弹窗方式打开，避免硬编码路由路径在远端部署下失效
      this.createDialogVisible = true;
    },
    handleCreateSuccess() {
      this.createDialogVisible = false;
      this.fetchData();
    },
    handleView(row) {
      this.currentId = row.id;
      this.detailDialogVisible = true;
    },
    handleEdit(row) {
      if (row.live_publish_enabled) {
        this.$message.warning('组合已实盘，配置已冻结；请先取消实盘再编辑');
        return;
      }
      this.editId = row.id;
      this.editDialogVisible = true;
    },
    handleEditSuccess() {
      this.editDialogVisible = false;
      this.fetchData();
    },
    canLivePublish(row) {
      return !!this.getLinkedModelId(row) && !row.live_publish_enabled;
    },
    canLiveUnpublish(row) {
      return !!row.live_publish_enabled;
    },

    getLinkedModelId(row) {
      return row.portfolio_model_id || row.model_id || null;
    },
    async handleLivePublish(row) {
      const modelId = this.getLinkedModelId(row);
      if (!modelId) {
        this.$message.warning('该组合尚未关联组合模型，无法实盘发布');
        return;
      }
      try {
        await this.$confirm(
          `确认实盘发布组合「${row.name}」？实盘后将进入日常监控，于次交易日生效；实盘期间配置冻结，取消实盘后可编辑。`,
          '实盘发布',
          { confirmButtonText: '确定发布', cancelButtonText: '取消', type: 'warning' }
        );
      } catch { return; }
      try {
        await livePublishModel(modelId, { source: 'portfolio_list' });
        this.$message.success('实盘发布成功，已进入日常监控');
        await this.fetchData();
      } catch (e) {
        this.$message.error('实盘发布失败：' + (e.response?.data?.detail || e.message || '未知错误'));
        await this.fetchData();
      }
    },
    async handleLiveUnpublish(row) {
      if (!row.live_publish_enabled) return;
      const modelId = this.getLinkedModelId(row);
      if (!modelId) return;
      try {
        await this.$confirm(
          `确认取消组合「${row.name}」的实盘？取消后将从日常监控下架，历史数据与操作记录保留。`,
          '取消实盘',
          { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
        );
      } catch { return; }
      try {
        await liveUnpublishModel(modelId, { source: 'portfolio_list' });
        this.$message.success('已取消实盘发布，监控已下架');
        await this.fetchData();
      } catch (e) {
        this.$message.error('取消实盘失败：' + (e.response?.data?.detail || e.message || '未知错误'));
        await this.fetchData();
      }
    },
    async handleDelete(row) {
      try {
        await this.$confirm(`确定要删除组合 "${row.name}" 吗？`, '提示', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning'
        });
        await this.$store.dispatch('portfolio/deletePortfolio', row.id);
        this.$message.success('删除成功');
        this.fetchData();
      } catch (e) {
        if (e !== 'cancel') {
          this.$message.error('删除失败：' + (e.response?.data?.detail || e.message));
        }
      }
    },
    getSourceTagType(source) {
      const map = { manual: 'info', single_strategy: '', portfolio_model: 'success' };
      return map[source] || 'info';
    },
    resolveSource(row) {
      // 与编辑回显同源规则：存量组合 source 可能误标为 manual，
      // 按实际数据结构判定，保证列表显示与编辑页口径一致
      if ((row.sub_strategies || []).length > 0) {
        return 'portfolio_model';
      }
      if (row.source === 'single_strategy' || row.model_id) {
        return 'single_strategy';
      }
      return row.source || 'manual';
    },
    getSourceLabel(source) {
      const map = { manual: '手工', single_strategy: '单策略', portfolio_model: '组合模型' };
      return map[source] || source || '—';
    },
    getWeightMethodLabel(method) {
      const map = { equal_weight: '等权', risk_parity: '风险平价', min_variance: '最小方差', custom: '自定义' };
      return map[method] || method || '—';
    },
    formatPct(v) {
      if (v === null || v === undefined) return '—';
      return (Number(v) * 100).toFixed(2) + '%';
    },
    formatNum(v) {
      if (v === null || v === undefined) return '—';
      return Number(v).toFixed(2);
    },
    formatDateShort(d) {
      return d ? dayjs(d).format('YYYY-MM-DD') : '—';
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
