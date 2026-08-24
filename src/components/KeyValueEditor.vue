<template>
  <div class="key-value-editor" :class="{ 'kv-compact': compact }">
    <!-- 紧凑模式：无标题栏，直接展示表格 -->
    <template v-if="compact">
      <div v-if="rows.length === 0" class="kv-empty-compact">
        <span>未设置权重上限，所有资产不受限制</span>
        <el-button type="text" size="mini" icon="el-icon-plus" @click="addAllAssets" v-if="assetOptions.length > 0">添加全部已选资产</el-button>
      </div>
      <div v-else class="kv-compact-list">
        <div v-for="(row, idx) in rows" :key="idx" class="kv-compact-row">
          <el-select
            v-model="row.key"
            placeholder="选择资产"
            filterable
            size="mini"
            style="width: 180px;"
            @change="handleRowChange(idx)"
          >
            <el-option
              v-for="asset in availableAssetsFor(idx)"
              :key="asset.code"
              :label="`${asset.name}(${asset.code})`"
              :value="asset.code"
            ></el-option>
          </el-select>
          <span class="kv-compact-sep">≤</span>
          <el-input-number
            v-model="row.value"
            :min="valueMin"
            :max="valueMax"
            :step="valueStep || 0.05"
            :precision="valuePrecision"
            size="mini"
            style="width: 110px;"
            @change="handleRowChange(idx)"
          ></el-input-number>
          <el-button
            type="text"
            size="mini"
            icon="el-icon-delete"
            class="kv-compact-del"
            @click="removeRow(idx)"
          ></el-button>
        </div>
        <el-button type="text" size="mini" icon="el-icon-plus" @click="addRow" class="kv-compact-add">添加资产上限</el-button>
      </div>
    </template>

    <!-- 标准模式 -->
    <template v-else>
      <div class="kv-header">
        <span class="kv-title">{{ title || '键值对配置' }}</span>
        <el-button type="text" size="mini" icon="el-icon-plus" @click="addRow">添加</el-button>
      </div>
      <div v-if="rows.length === 0" class="kv-empty">
        <span style="color: #909399; font-size: 13px;">暂无配置项，点击“添加”开始配置</span>
      </div>
      <div v-for="(row, idx) in rows" :key="idx" class="kv-row">
        <template v-if="keyMode === 'asset'">
          <el-select
            v-model="row.key"
            placeholder="选择资产"
            filterable
            size="small"
            style="width: 220px;"
            @change="handleRowChange(idx)"
          >
            <el-option
              v-for="asset in assetOptions"
              :key="asset.code"
              :label="`${asset.code} - ${asset.name}`"
              :value="asset.code"
            ></el-option>
          </el-select>
        </template>
        <template v-else>
          <el-input
            v-model="row.key"
            placeholder="键"
            size="small"
            style="width: 160px;"
            @input="handleRowChange(idx)"
          ></el-input>
        </template>
        <span class="kv-separator">→</span>
        <el-input-number
          v-if="valueType === 'number'"
          v-model="row.value"
          :min="valueMin"
          :max="valueMax"
          :step="valueStep || 0.01"
          :precision="valuePrecision"
          size="small"
          style="width: 160px;"
          @change="handleRowChange(idx)"
        ></el-input-number>
        <el-input
          v-else
          v-model="row.value"
          :placeholder="valuePlaceholder || '值'"
          size="small"
          style="width: 160px;"
          @input="handleRowChange(idx)"
        ></el-input>
        <el-button
          type="text"
          size="mini"
          icon="el-icon-delete"
          style="color: #F56C6C; margin-left: 8px;"
          @click="removeRow(idx)"
        ></el-button>
      </div>
    </template>
  </div>
</template>

<script>
export default {
  name: 'KeyValueEditor',
  props: {
    value: {
      type: [String, Object],
      default: '',
    },
    title: {
      type: String,
      default: '',
    },
    keyMode: {
      type: String,
      default: 'text', // 'text' or 'asset'
    },
    valueType: {
      type: String,
      default: 'number', // 'number' or 'text'
    },
    valueMin: { type: Number, default: 0 },
    valueMax: { type: Number, default: 1 },
    valueStep: { type: Number, default: 0.01 },
    valuePrecision: { type: Number, default: 4 },
    valuePlaceholder: { type: String, default: '' },
    assetOptions: {
      type: Array,
      default: () => [],
    },
    compact: {
      type: Boolean,
      default: false,
    },
  },
  data() {
    return {
      rows: [],
    };
  },
  watch: {
    value: {
      immediate: true,
      handler(val) {
        this.parseValue(val);
      },
    },
  },
  methods: {
    parseValue(val) {
      if (!val) {
        this.rows = [];
        return;
      }
      let dict = val;
      if (typeof val === 'string') {
        try {
          dict = JSON.parse(val);
        } catch {
          this.rows = [];
          return;
        }
      }
      if (typeof dict === 'object' && dict !== null && !Array.isArray(dict)) {
        this.rows = Object.entries(dict).map(([key, value]) => ({
          key,
          value: typeof value === 'number' ? value : parseFloat(value) || 0,
        }));
      } else {
        this.rows = [];
      }
    },
    emitValue() {
      const dict = {};
      for (const row of this.rows) {
        if (row.key) {
          dict[row.key] = row.value;
        }
      }
      this.$emit('input', JSON.stringify(dict));
      this.$emit('change', dict);
    },
    handleRowChange() {
      this.emitValue();
    },
    addRow() {
      this.rows.push({ key: '', value: this.valueType === 'number' ? 0.1 : '' });
    },
    addAllAssets() {
      // 紧凑模式：一键添加所有已选资产，默认上限 0.1
      this.assetOptions.forEach(asset => {
        if (!this.rows.find(r => r.key === asset.code)) {
          this.rows.push({ key: asset.code, value: 0.1 });
        }
      });
      this.emitValue();
    },
    /** 紧凑模式下，每行可选的资产（排除其他行已选的） */
    availableAssetsFor(currentIdx) {
      const usedKeys = this.rows
        .filter((_, i) => i !== currentIdx)
        .map(r => r.key)
        .filter(Boolean);
      return this.assetOptions.filter(a => !usedKeys.includes(a.code));
    },
    removeRow(idx) {
      this.rows.splice(idx, 1);
      this.emitValue();
    },
  },
};
</script>

<style scoped>
.key-value-editor {
  width: 100%;
  max-width: 520px;
}
.kv-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.kv-title {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}
.kv-empty {
  padding: 12px 0;
  text-align: center;
  border: 1px dashed #DCDFE6;
  border-radius: 4px;
}
.kv-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}
.kv-separator {
  margin: 0 8px;
  color: #909399;
  font-size: 14px;
}

/* 紧凑模式样式 */
.kv-compact {
  max-width: 400px;
}
.kv-empty-compact {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  color: #909399;
  font-size: 12px;
}
.kv-compact-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kv-compact-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.kv-compact-sep {
  color: #909399;
  font-size: 13px;
  flex-shrink: 0;
}
.kv-compact-del {
  color: #F56C6C;
  padding: 0;
  flex-shrink: 0;
}
.kv-compact-add {
  padding: 2px 0;
  font-size: 12px;
}
</style>
