<template>
  <div class="monitored-strategy-list" v-loading="loading">
    <!-- 操作栏 -->
    <div class="list-toolbar">
      <span class="toolbar-title">监控策略</span>
      <div class="toolbar-actions">
        <el-button size="small" icon="el-icon-plus" @click="showAddDialog">添加策略</el-button>
        <el-button size="small" icon="el-icon-refresh" @click="fetchList">刷新</el-button>
      </div>
    </div>

    <!-- 策略列表 -->
    <el-table
      :data="strategies"
      size="small"
      row-key="_id"
      class="strategy-table"
      highlight-current-row
    >
      <el-table-column label="策略名称" min-width="200">
        <template slot-scope="scope">
          <div class="strategy-name-cell">
            <template v-if="editingId === scope.row._id">
              <el-input
                v-model="editName"
                size="mini"
                @keyup.enter.native="confirmRename(scope.row)"
                @blur="confirmRename(scope.row)"
                @click.native.stop
                ref="renameInput"
              />
            </template>
            <template v-else>
              <span class="strategy-name">{{ scope.row.display_name }}</span>
              <i class="el-icon-edit rename-icon" @click.stop="startRename(scope.row)" />
            </template>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="描述" min-width="260">
        <template slot-scope="scope">
          <span class="strategy-desc">{{ scope.row.description || '—' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="200" align="center">
        <template slot-scope="scope">
          <el-button
            size="mini"
            type="text"
            @click.stop="$emit('view', scope.row)"
          >查看</el-button>
          <el-button
            size="mini"
            type="text"
            class="text-warning"
            @click.stop="$emit('init', scope.row)"
          >初始化</el-button>
          <el-button
            size="mini"
            type="text"
            class="text-primary"
            @click.stop="$emit('run', scope.row)"
          >运行</el-button>
          <el-button
            size="mini"
            type="text"
            class="text-danger"
            @click.stop="handleArchive(scope.row)"
          >归档</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 空态 -->
    <el-empty
      v-if="!loading && strategies.length === 0"
      description="暂无监控策略，请点击「添加策略」"
    >
      <el-button type="primary" size="small" @click="showAddDialog">添加策略</el-button>
    </el-empty>

    <!-- 添加策略对话框 -->
    <el-dialog title="添加监控策略" :visible.sync="addDialogVisible" width="560px">
      <div v-loading="addableLoading">
        <p class="dialog-hint">选择要纳入日常监控的策略：</p>

        <!-- 研究员策略 -->
        <div v-if="addableResearcher.length" class="addable-section">
          <div class="addable-section-title">研究员策略</div>
          <div class="researcher-list">
            <div
              v-for="item in addableResearcher"
              :key="item.code"
              class="researcher-item"
              :class="{ disabled: isRegistered('researcher', item.code) }"
            >
              <div class="researcher-info">
                <span class="researcher-name">{{ item.display_name }}</span>
                <span class="researcher-desc">{{ item.description }}</span>
              </div>
              <el-button
                size="mini"
                type="primary"
                :disabled="isRegistered('researcher', item.code)"
                @click="addResearcher(item.code)"
              >
                {{ isRegistered('researcher', item.code) ? '已添加' : '添加' }}
              </el-button>
            </div>
          </div>
        </div>

        <!-- 实盘发布策略/组合 -->
        <div v-if="addableLive.length" class="addable-section">
          <div class="addable-section-title">实盘发布策略/组合</div>
          <div class="researcher-list">
            <div
              v-for="item in addableLive"
              :key="item.model_id"
              class="researcher-item"
              :class="{ disabled: isRegistered(item.source_type, item.model_id) }"
            >
              <div class="researcher-info">
                <span class="researcher-name">
                  {{ item.name }}
                  <el-tag size="mini" :type="item.source_type === 'portfolio' ? 'warning' : 'success'" style="margin-left:6px;">
                    {{ item.source_type === 'portfolio' ? '组合' : '策略' }}
                  </el-tag>
                </span>
                <span class="researcher-desc">{{ item.template_code }} · {{ item.asset_count }}个资产</span>
              </div>
              <el-button
                size="mini"
                type="primary"
                :disabled="isRegistered(item.source_type, item.model_id)"
                @click="addLivePublished(item)"
              >
                {{ isRegistered(item.source_type, item.model_id) ? '已添加' : '添加' }}
              </el-button>
            </div>
          </div>
        </div>

        <el-empty v-if="!addableLoading && !addableResearcher.length && !addableLive.length" description="暂无可添加的策略" :image-size="40" />
      </div>
    </el-dialog>
  </div>
</template>

<script>
import {
  getMonitoredStrategies,
  createFromResearcher,
  createFromLive,
  updateMonitoredStrategy,
  archiveMonitoredStrategy,
  getAddableStrategies
} from '@/api/monitor';

export default {
  name: 'MonitoredStrategyList',
  props: {
    selectedId: { type: String, default: '' }
  },
  data() {
    return {
      loading: false,
      strategies: [],
      // 改名
      editingId: null,
      editName: '',
      // 添加对话框
      addDialogVisible: false,
      addableLoading: false,
      addableResearcher: [],
      addableLive: []
    };
  },
  created() {
    this.fetchList();
  },
  methods: {
    async fetchList() {
      this.loading = true;
      try {
        const res = await getMonitoredStrategies();
        this.strategies = res.data || [];
      } catch (e) {
        this.$message.error('获取监控策略列表失败');
      } finally {
        this.loading = false;
      }
    },

    // ── 改名 ──
    startRename(row) {
      this.editingId = row._id;
      this.editName = row.display_name;
      this.$nextTick(() => {
        const input = this.$refs.renameInput;
        if (input) {
          (Array.isArray(input) ? input[0] : input).focus();
        }
      });
    },
    async confirmRename(row) {
      if (!this.editName || this.editName === row.display_name) {
        this.editingId = null;
        return;
      }
      try {
        await updateMonitoredStrategy(row._id, { display_name: this.editName });
        row.display_name = this.editName;
        this.$message.success('改名成功');
      } catch (e) {
        this.$message.error('改名失败');
      }
      this.editingId = null;
    },

    // ── 归档 ──
    handleArchive(row) {
      this.$confirm(
        `确定归档策略「${row.display_name}」？归档后将从监控列表中移除，可通过「添加策略」重新纳入监控。`,
        '归档确认',
        { type: 'warning' }
      ).then(async () => {
        try {
          await archiveMonitoredStrategy(row._id);
          this.$message.success(`策略「${row.display_name}」已归档`);
          this.$emit('archive', row._id);
          await this.fetchList();
        } catch (e) {
          const msg = (e.response && e.response.data && e.response.data.detail) || e.message || '未知错误';
          this.$message.error('归档失败：' + msg);
        }
      }).catch(() => {});
    },

    // ── 添加策略 ──
    async showAddDialog() {
      this.addDialogVisible = true;
      this.addableLoading = true;
      try {
        const res = await getAddableStrategies();
        const data = res.data || {};
        this.addableResearcher = data.researcher || [];
        this.addableLive = data.live_published || [];
      } catch (e) {
        this.$message.error('获取可添加策略列表失败');
      } finally {
        this.addableLoading = false;
      }
    },
    isRegistered(sourceType, sourceRef) {
      return this.strategies.some(
        s => s.source_type === sourceType && s.source_ref === sourceRef
      );
    },
    async addResearcher(code) {
      try {
        await createFromResearcher(code);
        this.$message.success('添加成功');
        this.addDialogVisible = false;
        await this.fetchList();
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.detail) || e.message || '未知错误';
        this.$message.error('添加失败：' + msg);
      }
    },
    async addLivePublished(item) {
      try {
        await createFromLive({ model_id: item.model_id, source_type: item.source_type });
        this.$message.success('添加成功');
        this.addDialogVisible = false;
        await this.fetchList();
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.detail) || e.message || '未知错误';
        this.$message.error('添加失败：' + msg);
      }
    }
  }
};
</script>

<style scoped>
.monitored-strategy-list {
  padding: 0;
}
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.toolbar-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.strategy-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.strategy-name {
  font-weight: 500;
}
.strategy-desc {
  font-size: 12px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rename-icon {
  cursor: pointer;
  color: #909399;
  font-size: 13px;
}
.rename-icon:hover {
  color: #409eff;
}
.text-warning {
  color: #e6a23c;
}
.text-primary {
  color: #409eff;
}
.text-danger {
  color: #f56c6c;
}
.dialog-hint {
  margin-bottom: 12px;
  color: #606266;
  font-size: 13px;
}
.addable-section {
  margin-bottom: 16px;
}
.addable-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
  padding-left: 2px;
}
.researcher-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.researcher-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
.researcher-item.disabled {
  opacity: 0.6;
  background: #f5f7fa;
}
.researcher-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.researcher-name {
  font-weight: 500;
  font-size: 14px;
}
.researcher-desc {
  font-size: 12px;
  color: #909399;
}
</style>
