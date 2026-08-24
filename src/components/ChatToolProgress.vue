<template>
  <div class="tool-progress">
    <div class="completed-steps" v-if="completedSteps.length > 0">
      <span v-for="(step, idx) in completedSteps" :key="idx" class="step-chip">
        <i class="el-icon-check"></i>{{ step }}
      </span>
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
/* 整体包在浅灰圆角容器内，减少视觉噪音 */
.tool-progress {
  display: inline-flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px;
  background: #f4f6f9;
  border-radius: 10px;
  max-width: 100%;
}
.completed-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
/* 已完成步骤：弱化灰底 chip */
.step-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  background: #e9edf2;
  color: #5f6b7d;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.4;
}
.step-chip i {
  color: #52b788;
  font-size: 11px;
  font-weight: 700;
}
/* 当前步骤：蓝色 loading + 文字 */
.current-step {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #409eff;
  font-size: 13px;
}
.current-step i {
  font-size: 14px;
}
</style>
