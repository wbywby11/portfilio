<template>
  <div class="tool-progress">
    <div class="completed-steps" v-if="completedSteps.length > 0">
      <el-tag v-for="(step, idx) in completedSteps" :key="idx"
        size="mini" type="success" class="step-tag">
        <i class="el-icon-check"></i> {{ step }}
      </el-tag>
    </div>
    <div class="current-step" v-if="currentLabel">
      <i class="el-icon-loading"></i>
      <span>{{ currentLabel }}</span>
    </div>
    <div class="current-step" v-else>
      <i class="el-icon-loading"></i>
      <span>正在分析中...</span>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ChatToolProgress',
  props: {
    completedSteps: {
      type: Array,
      default: () => []
    },
    currentLabel: {
      type: String,
      default: ''
    }
  }
}
</script>

<style scoped>
.tool-progress {
  padding: 8px 12px;
  margin-top: 8px;
}
.completed-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.step-tag {
  font-size: 12px;
}
.current-step {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #409EFF;
  font-size: 13px;
}
.current-step i {
  font-size: 14px;
}
</style>
