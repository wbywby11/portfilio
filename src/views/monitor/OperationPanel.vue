<template>
  <div class="operation-panel" v-loading="loading">
    <!-- 空态 -->
    <el-empty v-if="!loading && groups.length === 0" description="暂无操作指令，运行监控后系统信号将在此生成指令记录"></el-empty>

    <!-- 单分组（单策略监控）：直接展示，含自身历史 -->
    <template v-else-if="groups.length === 1">
      <OperationGroupTable
        :group="groups[0]"
        :group-label="groupLabel(groups[0])"
        :current-weights="currentWeights"
        :asset-label-resolver="assetLabel"
        :asset-meta="assetMeta"
        :strategy-context="strategyContext"
        @optimize="openOptimize"
        @remark-updated="loadData"
      />
    </template>

    <!-- 组合监控：组合最新指令卡片 + 统一历史表（组合与子策略合并） -->
    <template v-else>
      <OperationGroupTable
        v-if="primaryGroup"
        :group="primaryGroup"
        :group-label="groupLabel(primaryGroup)"
        :current-weights="currentWeights"
        :asset-label-resolver="assetLabel"
        :asset-meta="assetMeta"
        :strategy-context="strategyContext"
        :show-history="false"
        @optimize="openOptimize"
        @remark-updated="loadData"
      />

      <OperationGroupTable
        v-if="mergedOperations.length"
        :group="unifiedGroup"
        unified
        :current-weights="currentWeights"
        :asset-label-resolver="assetLabel"
        :asset-meta="assetMeta"
        :strategy-context="strategyContext"
        :show-latest="false"
        history-title="历史指令 · 组合与子策略"
        @optimize="openOptimize"
        @remark-updated="loadData"
      />
    </template>

    <!-- 策略自定义插槽：操作页专属组件（如对冲比例表），未声明时不渲染 -->
    <DynamicSlots v-if="customSlots.length" :slots="customSlots" />

    <!-- 比例优化弹窗：基于待执行指令的模型建议权重微调后提交为主观指令 -->
    <el-dialog
      title="优化比例（调仓日主观调整）"
      :visible.sync="optimizeVisible"
      width="640px"
      :close-on-click-modal="false"
      @closed="resetOptimize">
      <div v-if="optimizeOp" class="optimize-body">
        <p class="optimize-hint">
          模型建议如下，可微调各资产权重；提交后原指令标记为「已替代」，实际绩效按新权重续算。
          执行日固定为 {{ optimizeOp.execute_date || optimizeOp.signal_date }}。
        </p>
        <div v-for="row in optimizeRows" :key="'opt-' + row.code" class="optimize-row">
          <span class="optimize-label" :title="row.code">{{ assetLabel(row.code) }}</span>
          <el-slider
            v-model="row.weight"
            :min="0"
            :max="100"
            :step="0.5"
            :format-tooltip="v => v.toFixed(2) + '%'"
            class="optimize-slider" />
          <el-input-number
            v-model="row.weight"
            :min="0"
            :max="500"
            :step="0.5"
            :precision="2"
            size="small"
            controls-position="right"
            class="optimize-num" />
        </div>
        <div class="optimize-sum-bar">
          <span :class="optimizeSumClass">权重合计：{{ optimizeSumPct }}%（等效杠杆 {{ optimizeLeverage }}x）</span>
        </div>
        <el-input
          type="textarea"
          v-model="optimizeDescription"
          :rows="2"
          placeholder="请输入调整原因或备注（可选）"
          maxlength="500"
          show-word-limit
          style="margin-top: 10px;" />
      </div>
      <span slot="footer">
        <el-button @click="optimizeVisible = false">取消</el-button>
        <el-button type="primary" :loading="optimizeSubmitting" @click="submitOptimize">提交主观指令</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { mapGetters, mapState } from 'vuex';
import { getMonitorOperations, addSubjectiveOverride } from '@/api/monitor';
import OperationGroupTable from './components/OperationGroupTable.vue';
import DynamicSlots from '@/components/monitor/DynamicSlots.vue';
import { resolveCustomComponents } from '@/config/monitor';

export default {
  name: 'OperationPanel',
  components: { OperationGroupTable, DynamicSlots },
  props: {
    /** 当前监控选中的策略上下文，用于资产展示名解析 */
    strategyContext: {
      type: Object,
      default: null
    }
  },
  data() {
    return {
      loading: false,
      groups: [],
      /** 资产键 → { name, price, price_date }，由 /operations 随指令一并下发 */
      assetMeta: {},
      optimizeVisible: false,
      optimizeSubmitting: false,
      optimizeOp: null,
      optimizeRows: [],
      optimizeDescription: ''
    };
  },
  computed: {
    ...mapGetters('monitor', ['activeMonitorId', 'currentBatchId']),
    ...mapState('monitor', ['monitorState']),
    /** 策略自定义插槽（操作页）：由策略元数据声明 */
    customSlots() {
      return resolveCustomComponents('operation', this.strategyContext);
    },
    /** 当前实际持仓目标权重（小数形式），仅组合层指令作为差值基准 */
    currentWeights() {
      return (this.monitorState && this.monitorState.target_weights) || {};
    },
    /** 组合监控的主展示分组：组合层优先，缺失时退化为第一组 */
    primaryGroup() {
      return this.groups.find(g => g.strategy_key === 'portfolio') || this.groups[0] || null;
    },
    /** 统一历史：组合层历史（最新一条除外）+ 全部子策略指令，按时间降序 */
    mergedOperations() {
      const rows = [];
      this.groups.forEach(g => {
        const isPortfolio = g.strategy_key === 'portfolio';
        const ops = (g.operations || []).slice().sort((a, b) =>
          String(b.execute_date || b.signal_date || '').localeCompare(String(a.execute_date || a.signal_date || ''))
        );
        const list = isPortfolio ? ops.slice(1) : ops;
        list.forEach(op => rows.push({
          ...op,
          __portfolio: isPortfolio,
          __groupLabel: this.groupLabel(g)
        }));
      });
      return rows.sort((a, b) =>
        String(b.execute_date || b.signal_date || '').localeCompare(String(a.execute_date || a.signal_date || ''))
      );
    },
    /** 喂给统一历史表的虚拟分组 */
    unifiedGroup() {
      return { strategy_key: '__unified__', operations: this.mergedOperations };
    },
    optimizeSumRatio() {
      return this.optimizeRows.reduce((s, r) => s + (Number(r.weight) || 0), 0) / 100;
    },
    optimizeSumPct() {
      return this.optimizeRows.reduce((s, r) => s + (Number(r.weight) || 0), 0).toFixed(2);
    },
    optimizeLeverage() {
      return this.optimizeSumRatio.toFixed(2);
    },
    optimizeSumClass() {
      return this.optimizeSumRatio > 1.00001 ? 'optimize-sum--warn' : '';
    }
  },
  created() {
    this.loadData();
  },
  methods: {
    async loadData() {
      if (!this.activeMonitorId) return;
      this.loading = true;
      try {
        // 指令按批次归档（pending 指令会被下一批次继承），读当前展示批次
        const res = await getMonitorOperations({
          monitor_id: this.activeMonitorId,
          batch_id: this.currentBatchId || undefined
        });
        const body = res && res.data !== undefined ? res.data : res;
        this.groups = (body && body.groups) || [];
        this.assetMeta = (body && body.asset_meta) || {};
      } catch (e) {
        console.warn('OperationPanel 加载指令失败:', e.message);
        this.groups = [];
      } finally {
        this.loading = false;
      }
    },
    groupLabel(g) {
      if (g.strategy_name) return g.strategy_name;
      if (g.strategy_key === this.activeMonitorId) {
        const s = this.strategyContext;
        if (s && (s.display_name || s.name)) return s.display_name || s.name;
        return '当前策略';
      }
      return g.strategy_key;
    },
    /** 资产键 → 展示名（接口 asset_meta 优先，回退策略上下文映射） */
    assetLabel(code) {
      const c = String(code || '').trim();
      if (!c) return '';
      const meta = this.assetMeta[c];
      if (meta && meta.name) return meta.name;
      const s = this.strategyContext;
      const map = s && s.asset_names;
      if (map && map[c]) return map[c];
      return c;
    },
    openOptimize(op) {
      this.optimizeOp = op;
      const tw = op.target_weights || {};
      this.optimizeRows = Object.keys(tw)
        .sort()
        .map(code => ({
          code,
          weight: Math.round((Number(tw[code]) || 0) * 100 * 100) / 100
        }));
      this.optimizeDescription = '';
      this.optimizeVisible = true;
    },
    resetOptimize() {
      this.optimizeOp = null;
      this.optimizeRows = [];
      this.optimizeDescription = '';
    },
    async submitOptimize() {
      const op = this.optimizeOp;
      if (!op) return;
      const sum = this.optimizeRows.reduce((s, r) => s + (Number(r.weight) || 0), 0);
      if (sum <= 0) {
        this.$message.warning('权重合计为 0，请至少配置一个资产权重');
        return;
      }
      const weights = {};
      this.optimizeRows.forEach(r => {
        weights[r.code] = (Number(r.weight) || 0) / 100;
      });
      this.optimizeSubmitting = true;
      try {
        await addSubjectiveOverride({
          monitor_id: this.activeMonitorId,
          weights,
          execute_date: op.execute_date || op.signal_date,
          description: this.optimizeDescription || `比例优化（替代指令 ${op._id}）`,
          linked_operation_id: op._id
        });
        this.$message.success(`已提交比例优化指令：原指令标记为「已替代」，执行日 ${op.execute_date || op.signal_date}`);
        this.optimizeVisible = false;
        this.$emit('override-added');
        this.loadData();
        // 同步刷新主观指令列表卡片
        this.$store.dispatch('monitor/fetchSubjectiveOverrides', {});
      } catch (e) {
        const msg = (e.response && e.response.data && (e.response.data.detail || e.response.data.message)) || e.message;
        this.$message.error('提交失败：' + msg);
      } finally {
        this.optimizeSubmitting = false;
      }
    }
  }
};
</script>

<style scoped>
.operation-panel {
  min-height: 80px;
}

.optimize-body {
  max-height: 60vh;
  overflow-y: auto;
}

.optimize-hint {
  margin: 0 0 12px 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
}

.optimize-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.optimize-label {
  flex: 0 0 132px;
  font-size: 13px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.optimize-slider {
  flex: 1 1 auto;
  min-width: 0;
  padding: 0 6px;
}

.optimize-num {
  flex: 0 0 110px;
  width: 110px !important;
}

.optimize-sum-bar {
  padding-top: 8px;
  border-top: 1px solid #ebeef5;
  font-size: 13px;
  color: #606266;
}

.optimize-sum--warn {
  color: #e6a23c;
  font-weight: 600;
}
</style>
