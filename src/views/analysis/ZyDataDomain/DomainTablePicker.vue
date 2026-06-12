<template>
  <div class="domain-table-picker">
    <div class="picker-header">
      <el-input
        v-model="filterText"
        size="small"
        placeholder="搜索表名/中文名"
        prefix-icon="el-icon-search"
        clearable />
    </div>
    <el-tree
      ref="tree"
      class="picker-tree"
      :data="treeData"
      node-key="id"
      :default-expand-all="false"
      :expand-on-click-node="false"
      :highlight-current="true"
      :filter-node-method="filterNode"
      :default-expanded-keys="defaultExpanded"
      :current-node-key="currentKey"
      @node-click="onClick">
      <span slot-scope="{ node, data }" class="tree-node">
        <i v-if="data.icon" :class="data.icon" :style="{ color: data.color }"></i>
        <span class="label">{{ data.label }}</span>
        <span v-if="data.tableCount != null" class="count-badge">{{ data.tableCount }}</span>
        <el-tag v-if="data.code" size="mini" effect="plain" class="code-tag">{{ data.code }}</el-tag>
      </span>
    </el-tree>
  </div>
</template>

<script>
import { DOMAINS } from '@/config/zyDataDomain';

export default {
  name: 'DomainTablePicker',
  props: {
    value: { type: String, default: '' } // 当前选中表名
  },
  data() {
    return {
      filterText: '',
      currentKey: this.value
    };
  },
  computed: {
    treeData() {
      return DOMAINS.map(d => ({
        id: 'D::' + d.domain,
        label: `${d.domainName} (${d.domainCode})`,
        icon: d.icon,
        color: d.color,
        tableCount: d.tables.length,
        children: d.tables.map(t => ({
          id: t.name,
          label: `${t.label}`,
          code: t.name,
          domain: d.domain,
          isLeaf: true
        }))
      }));
    },
    defaultExpanded() {
      // 默认展开第一个域
      return this.treeData.length ? [this.treeData[0].id] : [];
    }
  },
  watch: {
    filterText(v) {
      this.$refs.tree && this.$refs.tree.filter(v);
    },
    value(v) {
      this.currentKey = v;
      this.$nextTick(() => {
        this.$refs.tree && this.$refs.tree.setCurrentKey(v);
      });
    }
  },
  mounted() {
    if (this.currentKey) {
      this.$refs.tree.setCurrentKey(this.currentKey);
    }
  },
  methods: {
    filterNode(value, data) {
      if (!value) return true;
      const v = value.toLowerCase();
      return (data.label || '').toLowerCase().indexOf(v) !== -1 ||
             (data.code || '').toLowerCase().indexOf(v) !== -1;
    },
    onClick(data) {
      if (data.isLeaf) {
        this.currentKey = data.id;
        this.$emit('input', data.id);
        this.$emit('change', data);
      }
    }
  }
};
</script>

<style scoped>
.domain-table-picker {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-right: 1px solid #e4e7ed;
  background: #fff;
}
.picker-header {
  padding: 10px;
  border-bottom: 1px solid #ebeef5;
}
.picker-tree {
  flex: 1;
  overflow-y: auto;
  padding: 6px 4px;
}
.tree-node {
  display: inline-flex;
  align-items: center;
  flex: 1;
  font-size: 13px;
}
.tree-node .label {
  margin-left: 4px;
  flex: 1;
}
.tree-node i {
  font-size: 14px;
  margin-right: 4px;
}
.count-badge {
  background: #ecf5ff;
  color: #409EFF;
  border-radius: 8px;
  padding: 0 6px;
  font-size: 11px;
  margin-left: 4px;
}
.code-tag {
  margin-left: 6px;
  transform: scale(0.85);
  transform-origin: left center;
}
</style>
