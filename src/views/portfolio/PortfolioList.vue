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
        <vxe-column title="年化收益率" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary" :style="{color: (row.latest_backtest_summary.annual_return||0) >= 0 ? '#f56c6c' : '#67c23a'}">
              {{ formatPct(row.latest_backtest_summary.annual_return) }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="年化波动率" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary">{{ formatPct(row.latest_backtest_summary.annual_vol) }}</span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </vxe-column>
        <vxe-column title="夏普率" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.latest_backtest_summary" :style="{color: (row.latest_backtest_summary.sharpe||0) >= 1 ? '#f56c6c' : (row.latest_backtest_summary.sharpe||0) >= 0 ? '#e6a23c' : '#67c23a', fontWeight: 600}">
              {{ formatNum(row.latest_backtest_summary.sharpe) }}
            </span>
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
        <vxe-column title="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button type="text" size="small" @click="handleView(row)">详情</el-button>
            <el-button type="text" size="small" @click="handleEdit(row)">编辑</el-button>
            <el-dropdown trigger="click" @command="cmd => handleRowCommand(cmd, row)">
              <el-button type="text" size="small">
                更多<i class="el-icon-arrow-down el-icon--right"></i>
              </el-button>
              <el-dropdown-menu slot="dropdown">
                <el-dropdown-item command="livePublish" :disabled="row.live_publish_enabled">实盘发布</el-dropdown-item>
                <el-dropdown-item command="liveUnpublish" :disabled="!row.live_publish_enabled">取消实盘</el-dropdown-item>
                <el-dropdown-item command="delete" divided style="color: #f56c6c;">删除</el-dropdown-item>
              </el-dropdown-menu>
            </el-dropdown>
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
      editId: null,
      liveOpRowId: null,
      liveOpKind: ''
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
    handleRowCommand(cmd, row) {
      if (cmd === 'livePublish') this.handleLivePublish(row);
      else if (cmd === 'liveUnpublish') this.handleLiveUnpublish(row);
      else if (cmd === 'delete') this.handleDelete(row);
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
      this.editId = row.id;
      this.editDialogVisible = true;
    },
    handleEditSuccess() {
      this.editDialogVisible = false;
      this.fetchData();
    },

    getLinkedModelId(row) {
      return row.portfolio_model_id || row.model_id || null;
    },
    getPublishTargetIds(row) {
      // 优先直接关联模型，否则回退到子策略模型
      const direct = this.getLinkedModelId(row);
      if (direct) return [direct];
      const subIds = (row.sub_strategies || [])
        .map(s => s.model_id)
        .filter(Boolean);
      return [...new Set(subIds)];
    },
    async handleLivePublish(row) {
      const ids = this.getPublishTargetIds(row);
      if (!ids.length) {
        this.$message.warning('该组合无关联策略模型且无子策略，无法实盘发布');
        return;
      }
      const desc = ids.length > 1 ? `关联的 ${ids.length} 个子策略模型` : '关联的模型';
      try {
        await this.$confirm(
          `确定将组合「${row.name}」${desc}进行实盘发布？发布后可在日常监控中运行。`,
          '实盘发布确认',
          { confirmButtonText: '确定发布', cancelButtonText: '取消', type: 'info' }
        );
      } catch { return; }
      this.liveOpRowId = row.id;
      this.liveOpKind = 'publish';
      try {
        for (const mid of ids) {
          await livePublishModel(mid, { source: 'portfolio_list' });
        }
        this.$message.success('实盘发布成功，可在日常监控中添加该策略');
        await this.fetchData();
      } catch (e) {
        this.$message.error('实盘发布失败：' + (e.response?.data?.detail || e.message || '未知错误'));
        await this.fetchData();
      } finally {
        this.liveOpRowId = null;
        this.liveOpKind = '';
      }
    },
    async handleLiveUnpublish(row) {
      if (!row.live_publish_enabled) return;
      const ids = this.getPublishTargetIds(row);
      if (!ids.length) return;
      try {
        await this.$confirm(
          `确认取消组合「${row.name}」的实盘发布？取消后将不再出现在日常监控准入列表中。`,
          '取消实盘发布',
          { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
        );
      } catch { return; }
      this.liveOpRowId = row.id;
      this.liveOpKind = 'unpublish';
      try {
        for (const mid of ids) {
          await liveUnpublishModel(mid, { source: 'portfolio_list' });
        }
        this.$message.success('已取消实盘发布');
        await this.fetchData();
      } catch (e) {
        this.$message.error('取消实盘失败：' + (e.response?.data?.detail || e.message || '未知错误'));
        await this.fetchData();
      } finally {
        this.liveOpRowId = null;
        this.liveOpKind = '';
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
</style>
