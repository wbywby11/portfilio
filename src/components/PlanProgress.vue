<template>
  <div class="plan-progress" v-if="plan && plan.steps && plan.steps.length > 0">
    <div class="plan-header">
      <span class="plan-icon">📋</span>
      <span class="plan-goal">{{ plan.goal }}</span>
      <span class="plan-badge">{{ completedCount }} / {{ plan.steps.length }}</span>
    </div>
    <div class="plan-steps">
      <div
        v-for="(step, index) in plan.steps"
        :key="index"
        class="plan-step"
        :class="'step-' + step.status"
      >
        <span class="step-indicator">
          <span v-if="step.status === 'completed'" class="indicator-completed">✓</span>
          <span v-else-if="step.status === 'in_progress'" class="indicator-progress"></span>
          <span v-else-if="step.status === 'failed'" class="indicator-failed">✗</span>
          <span v-else class="indicator-pending">○</span>
        </span>
        <span class="step-text">{{ step.step }}</span>
        <span class="step-summary" v-if="step.result_summary">{{ step.result_summary }}</span>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'PlanProgress',
  props: {
    plan: {
      type: Object,
      default: null
    }
  },
  computed: {
    completedCount() {
      if (!this.plan || !this.plan.steps) return 0
      return this.plan.steps.filter(s => s.status === 'completed').length
    }
  }
}
</script>

<style scoped>
.plan-progress {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
  border: 1px solid #e9ecef;
}

.plan-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.plan-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.plan-goal {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan-badge {
  flex-shrink: 0;
  font-size: 12px;
  color: #fff;
  background: #409EFF;
  border-radius: 10px;
  padding: 2px 8px;
  font-weight: 500;
}

.plan-steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.plan-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.4;
}

.step-indicator {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}

.indicator-completed {
  color: #67C23A;
  font-weight: 700;
  font-size: 14px;
}

.indicator-progress {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #409EFF;
  animation: pulse 1.5s ease-in-out infinite;
}

.indicator-pending {
  color: #c0c4cc;
  font-size: 12px;
}

.indicator-failed {
  color: #F56C6C;
  font-weight: 700;
  font-size: 14px;
}

.step-text {
  color: #606266;
  flex-shrink: 0;
}

.step-completed .step-text {
  color: #909399;
}

.step-in_progress .step-text {
  color: #303133;
  font-weight: 500;
}

.step-summary {
  font-size: 12px;
  color: #909399;
  margin-left: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}

/* 响应式 */
@media (max-width: 768px) {
  .plan-progress {
    padding: 10px 12px;
  }

  .plan-goal {
    font-size: 13px;
  }

  .plan-step {
    font-size: 12px;
  }

  .step-summary {
    display: none;
  }
}
</style>
