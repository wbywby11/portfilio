<template>
  <div class="subjective-weights-matrix">
    <vxe-table
      ref="matrixTable"
      border
      resizable
      show-overflow="title"
      size="mini"
      :data="tableData"
      :max-height="500"
      :row-class-name="rowClassName"
      :footer-method="footerMethod"
      show-footer
      :sort-config="{ defaultSort: { field: 'date', order: 'asc' } }"
      class="matrix-table"
    >
      <!-- 序号列 -->
      <vxe-column type="seq" width="40" fixed="left" align="center" title="#"></vxe-column>

      <!-- 日期列 -->
      <vxe-column field="date" title="调仓日期" width="150" fixed="left" sortable>
        <template #default="{ row }">
          <span v-if="readonly" class="matrix-readonly-text">{{ row.date || '—' }}</span>
          <el-date-picker
            v-else
            v-model="row.date"
            type="date"
            value-format="yyyy-MM-dd"
            placeholder="选择日期"
            size="mini"
            style="width: 100%;"
            class="matrix-date-picker"
            @change="onDateChange(row)"
          ></el-date-picker>
        </template>
      </vxe-column>

      <!-- 动态资产列 -->
      <vxe-column
        v-for="code in assetCodes"
        :key="code"
        :field="'w_' + code"
        width="115"
        align="right"
      >
        <template #header>
          <el-tooltip :content="parseAssetHeader(code).full" placement="top" :open-delay="400">
            <span class="matrix-header-label">{{ parseAssetHeader(code).name }}</span>
          </el-tooltip>
        </template>
        <template #default="{ row }">
          <span v-if="readonly" :class="['matrix-readonly-num', weightClass(row['w_' + code])]">
            {{ formatWeight(row['w_' + code]) }}<span class="matrix-readonly-unit">%</span>
          </span>
          <div v-else class="matrix-weight-cell" @mousedown.stop @click.stop>
            <el-input-number
              :value="row['w_' + code] != null ? row['w_' + code] : 0"
              :controls="true"
              controls-position="right"
              size="mini"
              :min="0"
              :max="100"
              :precision="2"
              :step="5"
              :class="['matrix-weight-input', weightClass(row['w_' + code])]"
              @change="val => onWeightChange(row, code, val)"
              @keydown.native.tab="onTabKey($event, row, code)"
              @mousedown.native.stop
              @click.native.stop
            ></el-input-number>
            <span class="weight-unit">%</span>
          </div>
        </template>
      </vxe-column>

      <!-- 合计列 -->
      <vxe-column field="_sum" title="合计%" width="80" fixed="right" align="center">
        <template #default="{ row }">
          <span :class="['matrix-sum-badge', sumClass(row)]">
            {{ rowSum(row).toFixed(1) }}%
          </span>
        </template>
      </vxe-column>

      <!-- 操作列（只读模式不展示） -->
      <vxe-column v-if="!readonly" title="操作" width="120" fixed="right" align="center">
        <template #default="{ row, $rowIndex }">
          <el-tooltip content="归一化" placement="top" :open-delay="500">
            <el-button
              type="text"
              size="mini"
              icon="el-icon-aim"
              @click.stop="normalizeRow($rowIndex)"
            ></el-button>
          </el-tooltip>
          <el-tooltip content="复制行" placement="top" :open-delay="500">
            <el-button
              type="text"
              size="mini"
              icon="el-icon-copy-document"
              @click.stop="copyRow($rowIndex)"
            ></el-button>
          </el-tooltip>
          <el-tooltip content="等权填充" placement="top" :open-delay="500">
            <el-button
              type="text"
              size="mini"
              icon="el-icon-s-grid"
              @click.stop="fillEqual($rowIndex)"
            ></el-button>
          </el-tooltip>
          <el-tooltip content="删除" placement="top" :open-delay="500">
            <el-button
              type="text"
              size="mini"
              icon="el-icon-delete"
              class="btn-danger"
              @click.stop="deleteRow($rowIndex)"
            ></el-button>
          </el-tooltip>
        </template>
      </vxe-column>
    </vxe-table>

    <!-- 底部工具栏（只读模式不展示） -->
    <div v-if="!readonly" class="matrix-toolbar">
      <el-button size="mini" type="primary" plain icon="el-icon-plus" @click="addDate">
        添加调仓日
      </el-button>
      <el-button size="mini" plain icon="el-icon-aim" @click="normalizeAll">
        批量归一化
      </el-button>
    </div>
  </div>
</template>

<script>
import { normalizeWeightsToTwoDecimalSumOne } from '@/utils/subjectiveWeights'

export default {
  name: 'SubjectiveWeightsMatrixTable',
  props: {
    assetCodes: { type: Array, default: () => [] },
    resolveLabel: { type: Function, default: c => c },
    adjustments: { type: Array, default: () => [] },
    maxLeverage: { type: Number, default: 1 },
    /** 只读展示：日期与权重以文本呈现，隐藏操作列与工具栏 */
    readonly: { type: Boolean, default: false }
  },
  data() {
    return {
      tableData: []
    }
  },
  watch: {
    adjustments: {
      handler(val) {
        this.syncFromAdjustments(val)
      },
      immediate: true,
      deep: true
    },
    assetCodes() {
      this.syncFromAdjustments(this.adjustments)
    }
  },
  methods: {
    /**
     * 解析 resolveLabel 返回值，提取「中文名」作为表头主显示，并构造完整 tooltip 文本。
     * 兼容多种父组件返回格式：
     *   - "名称（代码）" / "名称(代码)"  → 名称在前
     *   - "代码 - 名称" / "代码-名称" / "代码 名称" → 代码在前
     *   - 纯代码（如 "000300.SH"）或纯名称
     */
    parseAssetHeader(code) {
      const raw = this.resolveLabel(code);
      const label = (raw == null ? '' : String(raw)).trim();
      const codeStr = String(code || '').trim();
      if (!label) return { name: codeStr, full: codeStr };

      // 1) "名称（代码）" 或 "名称(代码)"
      const m1 = label.match(/^(.+?)\s*[（(]\s*([^（()）]+?)\s*[）)]\s*$/);
      if (m1) {
        const name = m1[1].trim();
        const c = m1[2].trim();
        return { name: name || codeStr, full: name ? `${name} (${c || codeStr})` : (c || codeStr) };
      }

      // 2) label 以传入的 code 开头："code - name" / "code-name" / "code name"
      if (codeStr && label.startsWith(codeStr)) {
        const rest = label.slice(codeStr.length).replace(/^[\s\-—–:：|｜]+/, '').trim();
        if (rest) return { name: rest, full: `${rest} (${codeStr})` };
        return { name: codeStr, full: codeStr };
      }

      // 3) label 与 code 相同（resolveLabel 默认实现）
      if (label === codeStr) return { name: codeStr, full: codeStr };

      // 4) 其他情况：label 视为名称
      return { name: label, full: codeStr ? `${label} (${codeStr})` : label };
    },

    /**
     * 将外部 adjustments 格式转为表格行数据
     */
    syncFromAdjustments(adjs) {
      if (!adjs) {
        this.tableData = []
        return
      }
      this.tableData = adjs.map((adj, idx) => {
        const row = { _idx: idx, date: adj.date || '', auto_normalize: adj.auto_normalize }
        this.assetCodes.forEach(code => {
          const val = (adj.weights && adj.weights[code] != null) ? adj.weights[code] * 100 : 0
          this.$set(row, 'w_' + code, parseFloat(val.toFixed(2)))
        })
        return row
      })
      this.tableData.sort((a, b) => (a.date || '').localeCompare(b.date || ''))
    },

    /**
     * 将表格行数据转回 adjustments 格式并 emit
     */
    emitUpdate() {
      const result = this.tableData.map(row => {
        const weights = {}
        this.assetCodes.forEach(code => {
          weights[code] = parseFloat(((row['w_' + code] || 0) / 100).toFixed(4))
        })
        return {
          date: row.date || '',
          weights,
          auto_normalize: row.auto_normalize != null ? row.auto_normalize : true
        }
      })
      this.$emit('update:adjustments', result)
    },

    /** el-input-number 值变更（含 +/- 按钮、键盘输入、上下箭头） */
    onWeightChange(row, code, val) {
      let v = parseFloat(val)
      if (isNaN(v) || v == null) v = 0
      const maxV = this.maxLeverage * 100
      v = Math.max(0, Math.min(maxV, v))
      this.$set(row, 'w_' + code, parseFloat(v.toFixed(2)))
      this.emitUpdate()
    },

    /** 只读权重文本：两位小数 */
    formatWeight(val) {
      const n = parseFloat(val)
      return Number.isFinite(n) ? n.toFixed(2) : '0.00'
    },

    /** 根据权重值返回视觉 class（0 值浅灰、>50% 加粗） */
    weightClass(val) {
      const v = parseFloat(val) || 0
      return {
        'is-zero': v === 0,
        'is-bold': v > 50
      }
    },

    /** Tab 键流转到下一个单元格 */
    onTabKey(e, row, code) {
      const idx = this.assetCodes.indexOf(code)
      const rowIdx = this.tableData.indexOf(row)
      let nextRowIdx = rowIdx
      let nextColIdx = idx + 1

      if (e.shiftKey) {
        // Shift+Tab 向前
        nextColIdx = idx - 1
        if (nextColIdx < 0) {
          nextRowIdx = rowIdx - 1
          nextColIdx = this.assetCodes.length - 1
        }
      } else {
        // Tab 向后
        if (nextColIdx >= this.assetCodes.length) {
          nextRowIdx = rowIdx + 1
          nextColIdx = 0
        }
      }

      if (nextRowIdx >= 0 && nextRowIdx < this.tableData.length) {
        e.preventDefault()
        this.$nextTick(() => {
          const table = this.$refs.matrixTable
          if (table && table.$el) {
            const inputs = table.$el.querySelectorAll('.matrix-weight-input input')
            const targetIdx = nextRowIdx * this.assetCodes.length + nextColIdx
            if (inputs[targetIdx]) {
              inputs[targetIdx].focus()
            }
          }
        })
      }
    },

    /** 行求和（百分比） */
    rowSum(row) {
      let s = 0
      this.assetCodes.forEach(code => {
        s += (row['w_' + code] || 0)
      })
      return s
    },

    /** 合计列颜色 class（以模型杠杆上限为基准） */
    sumClass(row) {
      const s = this.rowSum(row)
      const cap = (this.maxLeverage || 1) * 100
      if (Math.abs(s - cap) < 0.01) return 'sum-ok'
      if (s < cap) return 'sum-under'
      return 'sum-over'
    },

    /** 日期改变 */
    onDateChange() {
      this.tableData.sort((a, b) => (a.date || '').localeCompare(b.date || ''))
      this.emitUpdate()
    },

    /** 归一化单行 */
    normalizeRow(idx) {
      const row = this.tableData[idx]
      if (!row) return
      const weights = {}
      this.assetCodes.forEach(code => {
        weights[code] = (row['w_' + code] || 0) / 100
      })
      const normalized = normalizeWeightsToTwoDecimalSumOne(weights, this.assetCodes)
      this.assetCodes.forEach(code => {
        this.$set(row, 'w_' + code, parseFloat(((normalized[code] || 0) * 100).toFixed(2)))
      })
      this.emitUpdate()
    },

    /** 复制行 */
    copyRow(idx) {
      const src = this.tableData[idx]
      if (!src) return
      const newRow = { date: '', auto_normalize: true }
      this.assetCodes.forEach(code => {
        this.$set(newRow, 'w_' + code, src['w_' + code] || 0)
      })
      this.tableData.splice(idx + 1, 0, newRow)
      this.emitUpdate()
    },

    /** 等权填充 */
    fillEqual(idx) {
      const row = this.tableData[idx]
      if (!row) return
      const n = this.assetCodes.length
      if (n === 0) return
      const equalWeight = parseFloat((100 / n).toFixed(2))
      this.assetCodes.forEach(code => {
        this.$set(row, 'w_' + code, equalWeight)
      })
      this.normalizeRow(idx)
    },

    /** 删除行 */
    deleteRow(idx) {
      this.tableData.splice(idx, 1)
      this.emitUpdate()
    },

    /** 添加调仓日 — 仅内部操作，通过 emitUpdate 统一通知父组件 */
    addDate() {
      const newRow = { date: '', auto_normalize: true }
      if (this.tableData.length > 0) {
        const lastRow = this.tableData[this.tableData.length - 1]
        this.assetCodes.forEach(code => {
          this.$set(newRow, 'w_' + code, lastRow['w_' + code] || 0)
        })
      } else {
        this.assetCodes.forEach(code => {
          this.$set(newRow, 'w_' + code, 0)
        })
      }
      this.tableData.push(newRow)
      this.emitUpdate()
    },

    /** 批量归一化 */
    normalizeAll() {
      this.tableData.forEach((_, idx) => {
        this.normalizeRow(idx)
      })
    },

    /** 行 class */
    rowClassName({ rowIndex }) {
      return rowIndex % 2 === 0 ? '' : 'stripe-row'
    },

    /** 表尾方法: 显示每列平均权重 */
    footerMethod({ columns }) {
      const footerRow = []
      columns.forEach((col, colIdx) => {
        if (colIdx === 0) {
          footerRow.push('')
          return
        }
        if (col.field === 'date') {
          footerRow.push('平均')
          return
        }
        if (col.field && col.field.startsWith('w_')) {
          const code = col.field.slice(2)
          let sum = 0
          const len = this.tableData.length
          this.tableData.forEach(row => {
            sum += (row['w_' + code] || 0)
          })
          footerRow.push(len > 0 ? (sum / len).toFixed(2) : '0.00')
          return
        }
        if (col.field === '_sum') {
          let total = 0
          const len = this.tableData.length
          this.tableData.forEach(row => {
            total += this.rowSum(row)
          })
          footerRow.push(len > 0 ? (total / len).toFixed(1) + '%' : '0.0%')
          return
        }
        footerRow.push('')
      })
      return [footerRow]
    }
  }
}
</script>

<style scoped>
.subjective-weights-matrix {
  width: 100%;
}

.matrix-table {
  font-size: 12px;
}

/* 紧凑行高 */
.matrix-table >>> .vxe-body--row .vxe-body--column {
  height: 38px;
  line-height: 38px;
}

.matrix-table >>> .vxe-cell {
  padding: 2px 4px;
}

/* 表头标签截断 */
.matrix-header-label {
  display: inline-block;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  font-size: 12px;
  font-weight: 600;
  color: #303133;
}

/* 权重输入单元格 */
.matrix-weight-cell {
  width: 100%;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
}

/* el-input-number 样式 — 无边框，hover/focus 显示边框 */
.matrix-weight-input {
  width: calc(100% - 14px);
  line-height: 1;
}
.matrix-weight-input.el-input-number--mini {
  height: 28px;
  line-height: 28px;
}
.matrix-weight-input >>> .el-input__inner {
  border: 1px solid transparent;
  background: rgba(64, 158, 255, 0.03);
  text-align: right;
  padding-left: 4px;
  padding-right: 28px;
  height: 28px;
  line-height: 28px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  border-radius: 3px;
  transition: border-color 0.2s, background 0.2s;
}
.matrix-weight-input >>> .el-input__inner:hover {
  border-color: #dcdfe6;
  background: #fff;
}
.matrix-weight-input >>> .el-input__inner:focus {
  border-color: #409eff;
  background: #fff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.1);
}

/* 控制按钮 — 默认淡化，hover 恢复正常 */
.matrix-weight-input >>> .el-input-number__increase,
.matrix-weight-input >>> .el-input-number__decrease {
  width: 18px;
  background: transparent;
  border-left-color: transparent;
  color: #c0c4cc;
  font-size: 11px;
  transition: color 0.2s, background 0.2s, border-color 0.2s;
}
.matrix-weight-input >>> .el-input-number__increase {
  height: 14px;
  line-height: 14px;
}
.matrix-weight-input >>> .el-input-number__decrease {
  height: 14px;
  line-height: 14px;
  top: 14px;
}
.matrix-weight-input:hover >>> .el-input-number__increase,
.matrix-weight-input:hover >>> .el-input-number__decrease {
  color: #606266;
  background: #f5f7fa;
  border-left-color: #dcdfe6;
}
.matrix-weight-input >>> .el-input-number__increase:hover,
.matrix-weight-input >>> .el-input-number__decrease:hover {
  color: #409eff;
}

/* 只读文本 */
.matrix-readonly-text {
  font-size: 12px;
  color: #303133;
  font-variant-numeric: tabular-nums;
}
.matrix-readonly-num {
  display: inline-block;
  width: 100%;
  text-align: right;
  font-size: 12px;
  color: #303133;
  font-variant-numeric: tabular-nums;
}
.matrix-readonly-num.is-zero {
  color: #c0c4cc;
}
.matrix-readonly-num.is-bold {
  font-weight: 600;
}
.matrix-readonly-unit {
  margin-left: 1px;
  font-size: 11px;
  color: #909399;
}

/* 0 值浅灰文字 */
.matrix-weight-input.is-zero >>> .el-input__inner {
  color: #c0c4cc;
}
/* >50% 加粗文字 */
.matrix-weight-input.is-bold >>> .el-input__inner {
  font-weight: 600;
  color: #303133;
}

/* % 后缀 */
.weight-unit {
  font-size: 11px;
  color: #909399;
  line-height: 28px;
  flex-shrink: 0;
}

/* 日期选择器紧凑 */
.matrix-date-picker {
  width: 100% !important;
}
.matrix-date-picker >>> .el-input__inner {
  height: 28px;
  line-height: 28px;
  font-size: 12px;
  padding-left: 26px;
}
.matrix-date-picker >>> .el-input__prefix {
  left: 4px;
}

/* 合计列 badge 样式 */
.matrix-sum-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.4;
}
.sum-ok {
  color: #67c23a;
  background: rgba(103, 194, 58, 0.1);
}
.sum-under {
  color: #e6a23c;
  background: rgba(230, 162, 60, 0.1);
}
.sum-over {
  color: #f56c6c;
  background: rgba(245, 108, 108, 0.1);
}

/* 操作按钮危险色 */
.btn-danger {
  color: #f56c6c !important;
}

/* 底部工具栏 */
.matrix-toolbar {
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* 行 hover 高亮 */
.matrix-table >>> .vxe-body--row:hover {
  background-color: #ecf5ff !important;
}
.matrix-table >>> .vxe-body--row:hover .matrix-weight-input >>> .el-input__inner {
  background: #fff;
  border-color: #e4e7ed;
}

/* 斑马纹 */
.matrix-table >>> .stripe-row {
  background-color: #fafafa;
}

/* footer 样式 */
.matrix-table >>> .vxe-footer--column .vxe-cell {
  font-weight: bold;
  color: #606266;
  font-size: 11px;
}
</style>
