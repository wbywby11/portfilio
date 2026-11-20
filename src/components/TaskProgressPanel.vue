<template>
  <div v-if="task" class="task-progress">
    <el-alert
      :title="task.message || phaseLabel"
      :type="alertType"
      :closable="false"
      show-icon
      class="task-progress__alert" />
    <!-- 本项目 element-ui 为定制版，el-progress 不支持 indeterminate，
         必须给真实 percentage，否则进度条恒停在 0%。 -->
    <el-progress
      v-if="active"
      :percentage="percent"
      :stroke-width="12"
      :status="progressStatus" />
    <div class="task-progress__meta">
      <span>阶段：{{ phaseLabel }}</span>
      <!-- 引擎类路径（含回测）的 total 是「阶段 × 刻度」放大值，X/Y 不好读，
           由 showTaskSteps 统一隐去，明细看上方 message。 -->
      <span v-if="showSteps">已处理：{{ task.current || 0 }} / {{ task.total }} 个交易日</span>
      <span v-if="task.total && task.current_date">当前日期：{{ task.current_date }}</span>
      <span>已用时：{{ elapsedText }}</span>
    </div>
    <!-- 完成后的业务结果因任务类型而异（监控给净值/日期，回测给绩效），由调用方插入 -->
    <slot name="result" :task="task" />
    <div v-if="task.error && task.error.message" class="task-progress__error">
      {{ task.error.message }}
    </div>
  </div>
</template>

<script>
import {
  isTaskActive,
  taskPercent,
  taskPhaseLabel,
  taskAlertType,
  taskProgressStatus,
  taskElapsedText,
  showTaskSteps
} from '@/utils/taskProgress';

/**
 * 后台任务进度面板：日常监控跑批与回测共用。
 *
 * 只负责展示 monitor_tasks 文档，不管数据从哪来（监控走 store 轮询，
 * 回测走页面内轮询），也不含底部按钮——「后台运行 / 关闭」的语义各页不同，
 * 由调用方的 el-dialog footer 决定。
 */
export default {
  name: 'TaskProgressPanel',
  props: {
    /** 任务文档（GET /monitor/tasks/{task_id} 的 data）；为空时整个面板不渲染 */
    task: {
      type: Object,
      default: null
    }
  },
  computed: {
    active() {
      return isTaskActive(this.task);
    },
    percent() {
      return taskPercent(this.task);
    },
    phaseLabel() {
      return taskPhaseLabel(this.task);
    },
    alertType() {
      return taskAlertType(this.task);
    },
    progressStatus() {
      return taskProgressStatus(this.task);
    },
    elapsedText() {
      return taskElapsedText(this.task);
    },
    showSteps() {
      return showTaskSteps(this.task);
    }
  }
};
</script>

<style scoped>
.task-progress__alert {
  margin-bottom: 16px;
}

.task-progress__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 12px;
  color: #606266;
  font-size: 13px;
}

.task-progress__error {
  margin-top: 8px;
  color: #f56c6c;
  font-size: 13px;
  word-break: break-all;
}
</style>
