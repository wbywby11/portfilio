<template>
  <div class="empty-state">
    <div class="empty-hero">
      <span class="empty-ai-icon"><i class="el-icon-s-opportunity"></i></span>
      <h3>{{ welcomeTitle }}</h3>
      <p class="empty-desc">{{ welcomeDescription }}</p>
    </div>
    <p class="empty-hint">在下方输入你的问题开始对话</p>
  </div>
</template>

<script>
export default {
  name: 'ChatEmptyState',
  props: {
    welcomeTitle: {
      type: String,
      default: ''
    },
    welcomeDescription: {
      type: String,
      default: ''
    }
  }
}
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 24px;
  color: #606266;
}

.empty-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 680px;
  margin-bottom: 28px;
}

.empty-ai-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: linear-gradient(135deg, #409eff 0%, #7c6cf0 100%);
  color: #fff;
  font-size: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  box-shadow: 0 4px 14px rgba(124, 108, 240, 0.3);
}

.empty-state h3 {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 600;
  color: #1f2937;
}

.empty-desc {
  color: #8a93a3;
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  text-align: center;
}

/* 底部输入引导 */
.empty-hint {
  margin-top: 24px;
  font-size: 13px;
  color: #b0b8c5;
}
</style>
