<template>
  <el-dialog
    title="版本参数对比"
    :visible.sync="dialogVisible"
    width="900px"
    top="5vh"
    @close="$emit('close')"
  >
    <div v-if="versionA && versionB" class="compare-container">
      <!-- 版本标题 -->
      <div class="compare-header">
        <div class="version-label version-a">
          <el-tag type="primary" size="small">v{{ versionA.version }}</el-tag>
          <span class="version-time">{{ formatDate(versionA.created_at) }}</span>
          <span v-if="versionA.change_summary" class="version-summary">{{ versionA.change_summary }}</span>
        </div>
        <div class="vs-divider">VS</div>
        <div class="version-label version-b">
          <el-tag type="success" size="small">v{{ versionB.version }}</el-tag>
          <span class="version-time">{{ formatDate(versionB.created_at) }}</span>
          <span v-if="versionB.change_summary" class="version-summary">{{ versionB.change_summary }}</span>
        </div>
      </div>

      <!-- 参数差异表 -->
      <div class="diff-section">
        <h4><i class="el-icon-s-operation"></i> 分配策略参数</h4>
        <table class="diff-table">
          <thead>
            <tr>
              <th class="param-name-col">参数</th>
              <th>v{{ versionA.version }}</th>
              <th>v{{ versionB.version }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in allocatorDiff" :key="'alloc_' + row.key" :class="{ 'diff-changed': row.changed }">
              <td class="param-name-col">{{ row.label }}</td>
              <td :class="{ 'val-old': row.changed }">{{ row.valA }}</td>
              <td :class="{ 'val-new': row.changed }">{{ row.valB }}</td>
            </tr>
            <tr v-if="allocatorDiff.length === 0">
              <td colspan="3" class="no-diff">无差异</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 选择器对比 -->
      <div class="diff-section">
        <h4><i class="el-icon-search"></i> 资产选择器</h4>
        <table class="diff-table">
          <thead>
            <tr>
              <th class="param-name-col">配置项</th>
              <th>v{{ versionA.version }}</th>
              <th>v{{ versionB.version }}</th>
            </tr>
          </thead>
          <tbody>
            <tr :class="{ 'diff-changed': versionA.selector_enabled !== versionB.selector_enabled }">
              <td class="param-name-col">启用状态</td>
              <td>{{ versionA.selector_enabled ? '已启用' : '未启用' }}</td>
              <td>{{ versionB.selector_enabled ? '已启用' : '未启用' }}</td>
            </tr>
            <tr v-if="versionA.selector_enabled || versionB.selector_enabled" :class="{ 'diff-changed': versionA.selector_type !== versionB.selector_type }">
              <td class="param-name-col">选择器类型</td>
              <td>{{ versionA.selector_type || '-' }}</td>
              <td>{{ versionB.selector_type || '-' }}</td>
            </tr>
            <tr v-for="row in selectorDiff" :key="'sel_' + row.key" :class="{ 'diff-changed': row.changed }">
              <td class="param-name-col">{{ row.label }}</td>
              <td :class="{ 'val-old': row.changed }">{{ row.valA }}</td>
              <td :class="{ 'val-new': row.changed }">{{ row.valB }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 控制器对比 -->
      <div class="diff-section">
        <h4><i class="el-icon-warning-outline"></i> 风险控制</h4>
        <table class="diff-table">
          <thead>
            <tr>
              <th class="param-name-col">配置项</th>
              <th>v{{ versionA.version }}</th>
              <th>v{{ versionB.version }}</th>
            </tr>
          </thead>
          <tbody>
            <tr :class="{ 'diff-changed': versionA.controller_code !== versionB.controller_code }">
              <td class="param-name-col">控制器</td>
              <td>{{ versionA.controller_code || '未启用' }}</td>
              <td>{{ versionB.controller_code || '未启用' }}</td>
            </tr>
            <tr v-for="row in controllerDiff" :key="'ctrl_' + row.key" :class="{ 'diff-changed': row.changed }">
              <td class="param-name-col">{{ row.label }}</td>
              <td :class="{ 'val-old': row.changed }">{{ row.valA }}</td>
              <td :class="{ 'val-new': row.changed }">{{ row.valB }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 资产列表对比 -->
      <div class="diff-section" v-if="assetsChanged">
        <h4><i class="el-icon-coin"></i> 资产池变更</h4>
        <div class="assets-compare">
          <div class="assets-col">
            <span class="assets-label">v{{ versionA.version }}（{{ (versionA.asset_codes || []).length }} 个）</span>
            <div>
              <el-tag v-for="code in versionA.asset_codes" :key="'a_' + code" size="mini"
                :type="!versionB.asset_codes.includes(code) ? 'danger' : ''"
                style="margin: 2px 4px 2px 0;">
                {{ code }}
              </el-tag>
            </div>
          </div>
          <div class="assets-col">
            <span class="assets-label">v{{ versionB.version }}（{{ (versionB.asset_codes || []).length }} 个）</span>
            <div>
              <el-tag v-for="code in versionB.asset_codes" :key="'b_' + code" size="mini"
                :type="!versionA.asset_codes.includes(code) ? 'success' : ''"
                style="margin: 2px 4px 2px 0;">
                {{ code }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- 绩效对比（如有关联回测） -->
      <div class="diff-section" v-if="backtestA || backtestB">
        <h4><i class="el-icon-data-line"></i> 绩效对比</h4>
        <table class="diff-table performance-table">
          <thead>
            <tr>
              <th class="param-name-col">指标</th>
              <th>v{{ versionA.version }}</th>
              <th>v{{ versionB.version }}</th>
              <th>变化</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="metric in performanceMetrics" :key="metric.key">
              <td class="param-name-col">{{ metric.label }}</td>
              <td>{{ metric.valA }}</td>
              <td>{{ metric.valB }}</td>
              <td :class="metric.betterClass">{{ metric.delta }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!backtestA || !backtestB" class="perf-hint">
          <i class="el-icon-info"></i> 部分版本无关联回测记录，仅展示已有数据
        </p>
      </div>
    </div>

    <div v-else class="empty-compare">
      <i class="el-icon-files" style="font-size: 40px; color: #dcdfe6;"></i>
      <p>请选择两个版本进行对比</p>
    </div>
  </el-dialog>
</template>

<script>
import dayjs from 'dayjs';

export default {
  name: 'VersionCompareDialog',
  props: {
    visible: { type: Boolean, default: false },
    versionA: { type: Object, default: null },
    versionB: { type: Object, default: null },
    /** 回测记录列表（用于按 param_version_number 匹配） */
    backtestHistory: { type: Array, default: () => [] }
  },
  computed: {
    dialogVisible: {
      get() { return this.visible; },
      set(val) { this.$emit('update:visible', val); }
    },
    /** 版本A关联的最佳回测 */
    backtestA() {
      if (!this.versionA) return null;
      return this.backtestHistory.find(r => r.param_version_number === this.versionA.version) || null;
    },
    backtestB() {
      if (!this.versionB) return null;
      return this.backtestHistory.find(r => r.param_version_number === this.versionB.version) || null;
    },
    /** 分配器参数差异 */
    allocatorDiff() {
      return this.buildDiff(
        this.versionA ? this.versionA.allocator_params : {},
        this.versionB ? this.versionB.allocator_params : {}
      );
    },
    /** 选择器参数差异 */
    selectorDiff() {
      return this.buildDiff(
        this.versionA ? this.versionA.selector_params : {},
        this.versionB ? this.versionB.selector_params : {}
      );
    },
    /** 控制器参数差异 */
    controllerDiff() {
      return this.buildDiff(
        this.versionA ? this.versionA.controller_params : {},
        this.versionB ? this.versionB.controller_params : {}
      );
    },
    /** 资产列表是否变化 */
    assetsChanged() {
      if (!this.versionA || !this.versionB) return false;
      const a = (this.versionA.asset_codes || []).join(',');
      const b = (this.versionB.asset_codes || []).join(',');
      return a !== b;
    },
    /** 绩效指标对比 */
    performanceMetrics() {
      const rA = this.backtestA ? this.backtestA.result : null;
      const rB = this.backtestB ? this.backtestB.result : null;
      const metrics = [
        { key: 'annual_return', label: '年化收益（260日）', fmt: v => v != null ? (v * 100).toFixed(2) + '%' : '-', higherBetter: true },
        { key: 'annual_return_365', label: '年化收益（365日）', fmt: v => v != null ? (v * 100).toFixed(2) + '%' : '-', higherBetter: true },
        { key: 'sharpe_ratio', label: '夏普比率（260日）', fmt: v => v != null ? v.toFixed(3) : '-', higherBetter: true },
        { key: 'sharpe_ratio_365', label: '夏普比率（365日）', fmt: v => v != null ? v.toFixed(3) : '-', higherBetter: true },
        { key: 'max_drawdown', label: '最大回撤', fmt: v => v != null ? (v * 100).toFixed(2) + '%' : '-', higherBetter: false },
        { key: 'total_return', label: '总收益', fmt: v => v != null ? (v * 100).toFixed(2) + '%' : '-', higherBetter: true },
        { key: 'annual_volatility', label: '年化波动（260日）', fmt: v => v != null ? (v * 100).toFixed(2) + '%' : '-', higherBetter: false },
        { key: 'annual_volatility_365', label: '年化波动（365日）', fmt: v => v != null ? (v * 100).toFixed(2) + '%' : '-', higherBetter: false },
      ];
      return metrics.map(m => {
        const rawA = rA ? rA[m.key] : null;
        const rawB = rB ? rB[m.key] : null;
        let delta = '-';
        let betterClass = '';
        if (rawA != null && rawB != null) {
          const diff = rawB - rawA;
          const isBetter = m.higherBetter ? diff > 0 : diff < 0;
          const isWorse = m.higherBetter ? diff < 0 : diff > 0;
          betterClass = isBetter ? 'perf-better' : (isWorse ? 'perf-worse' : '');
          if (m.key === 'annual_return' || m.key === 'annual_return_365' || m.key === 'total_return' || m.key === 'annual_volatility' || m.key === 'annual_volatility_365' || m.key === 'max_drawdown') {
            delta = (diff >= 0 ? '+' : '') + (diff * 100).toFixed(2) + '%';
          } else {
            delta = (diff >= 0 ? '+' : '') + diff.toFixed(3);
          }
        }
        return {
          key: m.key,
          label: m.label,
          valA: m.fmt(rawA),
          valB: m.fmt(rawB),
          delta,
          betterClass
        };
      });
    }
  },
  methods: {
    formatDate(val) {
      if (!val) return '-';
      return dayjs(val).format('YYYY-MM-DD HH:mm');
    },
    /** 构建两个参数对象的差异行 */
    buildDiff(paramsA, paramsB) {
      const a = paramsA || {};
      const b = paramsB || {};
      const allKeys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
      // 排除内部字段
      const exclude = ['selector_parameters', 'manual_weight_adjustments'];
      return allKeys
        .filter(k => !exclude.includes(k))
        .map(key => {
          const rawA = a[key];
          const rawB = b[key];
          const valA = this.formatVal(rawA);
          const valB = this.formatVal(rawB);
          return {
            key,
            label: key,
            valA,
            valB,
            changed: valA !== valB
          };
        })
        .sort((x, y) => (y.changed ? 1 : 0) - (x.changed ? 1 : 0));
    },
    formatVal(val) {
      if (val === undefined || val === null) return '-';
      if (typeof val === 'object') return JSON.stringify(val);
      if (typeof val === 'number') {
        return Number.isInteger(val) ? String(val) : val.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
      }
      return String(val);
    }
  }
};
</script>

<style scoped>
.compare-container {
  max-height: 70vh;
  overflow-y: auto;
}
.compare-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 6px;
}
.version-label {
  display: flex;
  align-items: center;
  gap: 8px;
}
.version-time {
  font-size: 12px;
  color: #909399;
}
.version-summary {
  font-size: 12px;
  color: #606266;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vs-divider {
  font-weight: 700;
  color: #c0c4cc;
  font-size: 16px;
}
.diff-section {
  margin-bottom: 20px;
}
.diff-section h4 {
  margin: 0 0 10px 0;
  font-size: 14px;
  color: #303133;
}
.diff-section h4 i {
  margin-right: 6px;
  color: #909399;
}
.diff-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.diff-table th,
.diff-table td {
  border: 1px solid #ebeef5;
  padding: 8px 12px;
  text-align: left;
}
.diff-table th {
  background: #fafafa;
  font-weight: 500;
  color: #606266;
}
.param-name-col {
  width: 30%;
  color: #606266;
}
.diff-changed {
  background: #fdf6ec;
}
.val-old {
  color: #f56c6c;
  text-decoration: line-through;
}
.val-new {
  color: #67c23a;
  font-weight: 500;
}
.no-diff {
  text-align: center;
  color: #c0c4cc;
}
.assets-compare {
  display: flex;
  gap: 20px;
}
.assets-col {
  flex: 1;
}
.assets-label {
  font-size: 12px;
  color: #909399;
  display: block;
  margin-bottom: 6px;
}
.perf-better {
  color: #67c23a;
  font-weight: 500;
}
.perf-worse {
  color: #f56c6c;
  font-weight: 500;
}
.perf-hint {
  font-size: 12px;
  color: #909399;
  margin-top: 8px;
}
.empty-compare {
  text-align: center;
  padding: 40px;
  color: #909399;
}
</style>
