<template>
  <div class="standard-table" :class="{ 'standard-table--full': fullWidth }">
    <vxe-table
      ref="table"
      :data="visibleData"
      :border="border"
      :stripe="stripe"
      :size="size"
      :height="height"
      :max-height="maxHeight"
      :row-config="rowConfig"
      :tree-config="treeConfig"
      :empty-text="emptyText"
      :show-overflow="false"
      :show-header-overflow="false"
      :auto-resize="true"
      class="standard-table__inner">
      <!-- 展开行：内容由使用方插槽提供 -->
      <vxe-column
        v-for="col in expandColumns"
        :key="col.key || 'expand'"
        type="expand"
        :width="col.width || 48"
        :align="col.align || 'center'">
        <template #content="scope">
          <slot :name="col.slot || 'expand'" :row="scope.row" :column="col"></slot>
        </template>
      </vxe-column>

      <!-- 数据列：按 columns 配置渲染，数字列自动右对齐 -->
      <vxe-column
        v-for="col in dataColumns"
        :key="col.key || col.field || col.title"
        :field="col.field"
        :title="col.title"
        :width="col.width"
        :min-width="col.minWidth"
        :align="resolveAlign(col)"
        :header-align="col.headerAlign || resolveAlign(col)"
        :fixed="col.fixed">
        <template #default="scope">
          <!-- 数据条 -->
          <div v-if="col.cell === 'dataBar'" class="st-data-bar">
            <span
              class="st-data-bar__fill"
              :class="'st-data-bar__fill--' + (col.dataBar && col.dataBar.color ? col.dataBar.color : 'primary')"
              :style="{ width: barWidth(scope.row, col) }"></span>
            <span class="st-data-bar__text">{{ cellText(scope.row, col) }}</span>
          </div>

          <!-- 变动：红绿底色块 -->
          <span
            v-else-if="col.cell === 'change'"
            class="st-change"
            :class="changeClass(scope.row, col)">{{ changeText(scope.row, col) }}</span>

          <!-- 标签 -->
          <el-tag
            v-else-if="col.cell === 'tag'"
            :type="col.tagType ? col.tagType(scope.row) : 'info'"
            size="mini"
            effect="plain">{{ cellText(scope.row, col) }}</el-tag>

          <!-- 自定义插槽列：用于资产名、计算逻辑等复杂单元格 -->
          <slot
            v-else-if="col.cell === 'slot'"
            :name="col.slot || col.field"
            :row="scope.row"
            :column="col"
            :value="cellValue(scope.row, col)"></slot>

          <!-- 默认文本 -->
          <span v-else class="st-text">{{ cellText(scope.row, col) }}</span>
        </template>
      </vxe-column>
    </vxe-table>
  </div>
</template>

<script>
/**
 * StandardTable —— 配置驱动的表格组件（基于 vxe-table）。
 *
 * columns 配置项：
 *   {
 *     field, title, width, minWidth,
 *     align: 'left' | 'center' | 'right',   // 不传时数字类列自动右对齐
 *     cell: 'text' | 'dataBar' | 'change' | 'tag' | 'slot',
 *     format: 'pct' | 'pointPct' | 'signedPct' | 'signedPointPct' | 'number' | 'text',
 *     precision: 2,
 *     formatter: (value, row) => string,    // 自定义格式化，优先于 format
 *     value: (row) => any,                  // 非 field 取值
 *     dataBar: { color: 'primary' | 'success' | 'danger', minWidth: 2 },
 *     zeroText: '不变',                      // cell='change' 时为 0 的文案
 *     tagType: (row) => 'success',
 *     slot: 'asset',                        // cell='slot' / type='expand' 时的插槽名
 *     type: 'expand',
 *     visible: false                        // 动态列开关
 *   }
 */
export default {
  name: 'StandardTable',
  props: {
    data: {
      type: Array,
      default: () => []
    },
    columns: {
      type: Array,
      default: () => []
    },
    rowKey: {
      type: String,
      default: ''
    },
    /**
     * 树形展开配置：传入即开启树形表，不传为平铺表。
     * 形如 { childrenField: 'children', expandAll: true }；数据里把子行放在
     * childrenField 指定的字段下即可，无需拍平。
     */
    treeConfig: {
      type: Object,
      default: null
    },
    height: {
      type: [Number, String],
      default: null
    },
    maxHeight: {
      type: [Number, String],
      default: null
    },
    border: {
      type: Boolean,
      default: true
    },
    stripe: {
      type: Boolean,
      default: false
    },
    size: {
      type: String,
      default: 'small'
    },
    emptyText: {
      type: String,
      default: '暂无数据'
    },
    /** 表格是否撑满容器宽度 */
    fullWidth: {
      type: Boolean,
      default: true
    }
  },
  computed: {
    visibleColumns() {
      return (this.columns || []).filter(col => col && col.visible !== false);
    },
    expandColumns() {
      return this.visibleColumns.filter(col => col.type === 'expand');
    },
    dataColumns() {
      return this.visibleColumns.filter(col => col.type !== 'expand');
    },
    visibleData() {
      return this.data || [];
    },
    rowConfig() {
      return this.rowKey ? { keyField: this.rowKey, isHover: true } : { isHover: true };
    },
    /** 数据条列的归一化基准：列内最大绝对值 */
    barMaxMap() {
      const map = {};
      this.dataColumns.forEach(col => {
        if (col.cell !== 'dataBar') return;
        const values = this.visibleData
          .map(row => Math.abs(Number(this.cellValue(row, col))))
          .filter(v => !Number.isNaN(v));
        map[this.columnKey(col)] = values.length ? Math.max.apply(null, values) : 0;
      });
      return map;
    }
  },
  methods: {
    columnKey(col) {
      return col.key || col.field || col.title;
    },
    resolveAlign(col) {
      if (col.align) return col.align;
      if (['dataBar', 'change', 'number'].indexOf(col.cell) >= 0 || col.numeric) {
        return 'right';
      }
      return 'left';
    },
    cellValue(row, col) {
      if (typeof col.value === 'function') return col.value(row);
      return col.field ? row[col.field] : undefined;
    },
    cellText(row, col) {
      const value = this.cellValue(row, col);
      if (typeof col.formatter === 'function') return col.formatter(value, row);
      return this.formatValue(value, col);
    },
    formatValue(value, col) {
      if (value === null || value === undefined || value === '') {
        return col.placeholder === undefined ? '—' : col.placeholder;
      }
      const numeric = col.format && ['pct', 'pointPct', 'signedPct', 'signedPointPct', 'number', 'integer'].indexOf(col.format) >= 0;
      // 文本列（日期、名称等）直接输出，不参与数值校验
      if (!numeric) return String(value);
      if (Number.isNaN(Number(value))) {
        return col.placeholder === undefined ? '—' : col.placeholder;
      }
      const n = Number(value);
      const p = col.precision === undefined || col.precision === null ? 2 : col.precision;
      switch (col.format) {
        case 'pct':
          return (n * 100).toFixed(p) + '%';
        case 'pointPct':
          return n.toFixed(p) + '%';
        case 'signedPct':
          return (n > 0 ? '+' : '') + (n * 100).toFixed(p) + '%';
        case 'signedPointPct':
          return (n > 0 ? '+' : '') + n.toFixed(p) + '%';
        case 'number':
          return n.toFixed(p);
        case 'integer':
          return String(Math.round(n));
        default:
          return String(value);
      }
    },
    barWidth(row, col) {
      const key = this.columnKey(col);
      const max = this.barMaxMap[key] || 0;
      const value = Number(this.cellValue(row, col)) || 0;
      if (value === 0 || max <= 0) return '0%';
      const minWidth = (col.dataBar && col.dataBar.minWidth) || 2;
      const pct = (Math.abs(value) / max) * 100;
      return Math.max(minWidth, Math.min(100, pct)).toFixed(2) + '%';
    },
    changeClass(row, col) {
      const raw = this.cellValue(row, col);
      // 空值不是 0：树形汇总行不希望出现「不变」的灰色块
      if (raw === null || raw === undefined || raw === '') return '';
      const value = Number(raw) || 0;
      const eps = col.epsilon === undefined ? 1e-5 : col.epsilon;
      if (value > eps) return 'st-change--up';
      if (value < -eps) return 'st-change--down';
      return 'st-change--flat';
    },
    changeText(row, col) {
      const raw = this.cellValue(row, col);
      if (raw === null || raw === undefined || raw === '') {
        return col.placeholder === undefined ? '—' : col.placeholder;
      }
      const value = Number(raw) || 0;
      const eps = col.epsilon === undefined ? 1e-5 : col.epsilon;
      if (value > eps || value < -eps) return this.cellText(row, col);
      return col.zeroText === undefined ? '不变' : col.zeroText;
    },
    /** 供父组件调用：手动重算布局（页签切换后调用） */
    resize() {
      const table = this.$refs.table;
      if (table && typeof table.recalculate === 'function') table.recalculate();
    },
    /** 树形表全展开/全收起；平铺表或无数据时静默返回 */
    setAllExpand(expanded) {
      const table = this.$refs.table;
      if (!table || !this.treeConfig) return;
      if (typeof table.setAllTreeExpand === 'function') {
        table.setAllTreeExpand(!!expanded);
      }
    }
  }
};
</script>

<style scoped>
.standard-table {
  width: 100%;
  min-width: 0;
}

.standard-table--full,
.standard-table__inner {
  width: 100% !important;
}

.standard-table >>> .vxe-table--body-wrapper,
.standard-table >>> .vxe-table--header-wrapper {
  width: 100%;
}

.st-text {
  font-variant-numeric: tabular-nums;
}

/* 数据条：从右向左延伸，与右对齐数值同侧 */
.st-data-bar {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  height: 20px;
  overflow: hidden;
}

.st-data-bar__fill {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  border-radius: 3px;
  pointer-events: none;
}

.st-data-bar__fill--primary {
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.05), rgba(64, 158, 255, 0.2));
}

.st-data-bar__fill--success {
  background: linear-gradient(90deg, rgba(103, 194, 58, 0.05), rgba(103, 194, 58, 0.2));
}

.st-data-bar__fill--danger {
  background: linear-gradient(90deg, rgba(245, 108, 108, 0.05), rgba(245, 108, 108, 0.2));
}

.st-data-bar__text {
  position: relative;
  z-index: 1;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
}

/* 变动块：涨红跌绿，0 灰 */
.st-change {
  display: inline-block;
  min-width: 76px;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.st-change--up {
  background: #fef0f0;
  color: #f56c6c;
}

.st-change--down {
  background: #f0f9eb;
  color: #67c23a;
}

.st-change--flat {
  background: #f4f4f5;
  color: #909399;
}
</style>
