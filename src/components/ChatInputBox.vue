<template>
  <div class="input-area">
    <!-- 浮层卡片 -->
    <div class="input-card">
      <el-input
        ref="inputBox"
        type="textarea"
        v-model="inputText"
        :placeholder="isLoading ? 'AI 正在回复中...' : '输入你的问题，Shift+Enter 换行，Enter 发送'"
        :disabled="isLoading"
        :autosize="{ minRows: 1, maxRows: 6 }"
        @keydown.native="handleKeydown"
      ></el-input>

      <!-- 底部工具栏：发送右下 -->
      <div class="input-toolbar">
        <span></span>
        <el-button
          class="send-btn"
          :class="{ active: canSend }"
          icon="el-icon-s-promotion"
          circle
          size="mini"
          :loading="isLoading"
          :disabled="!canSend"
          @click="handleSend"
        ></el-button>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ChatInputBox',
  props: {
    isLoading: {
      type: Boolean,
      default: false
    }
  },
  data() {
    return {
      inputText: ''
    }
  },
  computed: {
    canSend() {
      if (this.isLoading) return false
      return this.inputText.trim().length > 0
    }
  },
  methods: {
    handleKeydown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        this.handleSend()
      }
    },
    handleSend() {
      const text = this.inputText.trim()
      if (!text || this.isLoading) return

      this.$emit('send', text)
      this.inputText = ''
    },

    /** 外部调用：设置输入框文本 */
    setText(text) {
      this.inputText = text
    }
  }
}
</script>

<style scoped>
.input-area {
  padding: 12px 24px 20px;
  background: #f7f8fa;
  position: relative;
  border-top: 1px solid #ebeef5;
}

/* 浮层卡片：白底 + 16px 圆角 + 轻阴影，聚焦时蓝色描边 */
.input-card {
  background: #fff;
  border: 1px solid #e3e7ee;
  border-radius: 16px;
  padding: 12px 14px 10px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.input-card:focus-within {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.14);
}

/* 输入框去边框，由卡片承载视觉 */
.input-card ::v-deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  background: transparent;
  resize: none;
  padding: 4px 4px 8px;
  font-size: 14px;
  line-height: 1.6;
}

.input-card ::v-deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.input-card ::v-deep(.el-textarea.is-disabled .el-textarea__inner) {
  background: transparent;
  color: #909399;
}

.input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 2px 2px;
}

/* 发送按钮：圆形图标按钮，有内容蓝色高亮、无内容/加载中置灰 */
.send-btn,
.send-btn:hover,
.send-btn:focus {
  width: 36px;
  height: 36px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: #e8ebf0;
  color: #a8b0bd;
  transition: all 0.2s ease;
}

.send-btn i {
  font-size: 15px;
}

.send-btn.active,
.send-btn.active:hover,
.send-btn.active:focus {
  background: linear-gradient(135deg, #409eff 0%, #5b7cfa 100%);
  color: #fff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.4);
}

.send-btn.active:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.5);
}

.send-btn.is-disabled,
.send-btn.is-disabled:hover {
  background: #e8ebf0;
  color: #a8b0bd;
  box-shadow: none;
  transform: none;
}
</style>
