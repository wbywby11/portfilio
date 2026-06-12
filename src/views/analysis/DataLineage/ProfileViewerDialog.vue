<template>
  <el-dialog
    title="L5.3 跨域联动画像"
    :visible.sync="dialogVisible"
    width="700px"
    @close="$emit('close')"
  >
    <div class="toolbar">
      <el-button type="primary" size="small" @click="handleGenerate" :loading="generating">
        生成/刷新全部
      </el-button>
    </div>
    <div v-if="loading" class="loading">
      <i class="el-icon-loading"></i> 加载中...
    </div>
    <div v-else-if="!list.length" class="empty">暂无数据，请点击生成</div>
    <div v-else class="resonance-list">
      <div v-for="item in list" :key="item.scenario_id" class="resonance-card">
        <div class="card-header">
          <span class="scenario-name">{{ item.scenario_name }}</span>
          <span class="domains-tag" v-for="d in item.domains_involved" :key="d">{{ d }}</span>
        </div>
        <div class="card-body">
          <div class="field"><span class="label">场景定义：</span>{{ item.scenario_definition }}</div>
          <div class="field"><span class="label">跨域结构：</span>{{ item.cross_structure }}</div>
          <div class="field"><span class="label">共振趋势：</span>{{ item.resonance_trend }}</div>
          <div class="field"><span class="label">极端脱钩：</span>{{ item.extreme_decoupling }}</div>
        </div>
        <div class="card-footer">生成时间: {{ item.computed_at }}</div>
      </div>
    </div>
  </el-dialog>
</template>

<script>
import { getCrossResonance, generateCrossResonance } from '@/api/semantic'

export default {
  name: 'ProfileViewerDialog',
  props: {
    visible: { type: Boolean, default: false }
  },
  data() {
    return {
      list: [],
      loading: false,
      generating: false
    }
  },
  computed: {
    dialogVisible: {
      get() { return this.visible },
      set(val) { this.$emit('update:visible', val) }
    }
  },
  watch: {
    visible(val) {
      if (val) {
        this.loadList()
      }
    }
  },
  methods: {
    async loadList() {
      this.loading = true
      try {
        const res = await getCrossResonance()
        this.list = res.data || res || []
      } catch (e) {
        this.list = []
      } finally {
        this.loading = false
      }
    },
    async handleGenerate() {
      this.generating = true
      try {
        await generateCrossResonance()
        await this.loadList()
      } catch (e) {
        console.warn('生成跨域联动画像失败', e)
      } finally {
        this.generating = false
      }
    }
  }
}
</script>

<style scoped>
.toolbar {
  margin-bottom: 16px;
}
.loading, .empty {
  padding: 40px 0;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
.resonance-list {
  max-height: 500px;
  overflow-y: auto;
}
.resonance-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 12px;
  transition: box-shadow 0.2s;
}
.resonance-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.card-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.scenario-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.domains-tag {
  font-size: 11px;
  background: #ecf5ff;
  color: #409EFF;
  padding: 2px 6px;
  border-radius: 3px;
}
.card-body {
  margin-bottom: 8px;
}
.field {
  font-size: 12px;
  color: #606266;
  line-height: 1.8;
}
.field .label {
  color: #909399;
}
.card-footer {
  font-size: 11px;
  color: #c0c4cc;
  border-top: 1px dashed #ebeef5;
  padding-top: 6px;
}
</style>
