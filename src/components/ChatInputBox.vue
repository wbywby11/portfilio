<template>
  <div
    class="input-area"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
    :class="{ 'drag-over': isDragOver }"
  >
    <!-- 拖拽提示 -->
    <div v-if="isDragOver" class="drag-overlay">
      <i class="el-icon-upload2"></i>
      <span>拖放 Excel/CSV 文件到此处</span>
    </div>

    <!-- 已选附件 -->
    <div v-if="attachments.length" class="attachment-list">
      <el-tag
        v-for="(att, idx) in attachments"
        :key="idx"
        :type="att.status === 'success' ? 'success' : att.status === 'error' ? 'danger' : 'info'"
        closable
        @close="removeAttachment(idx)"
        size="small"
      >
        <i :class="att.status === 'uploading' ? 'el-icon-loading' : 'el-icon-document'"></i>
        {{ att.name }} ({{ formatSize(att.size) }})
      </el-tag>
    </div>

    <div class="input-wrapper">
      <!-- 附件按钮 -->
      <el-button
        class="attach-btn"
        icon="el-icon-paperclip"
        circle
        size="mini"
        @click="triggerFileSelect"
        :disabled="isLoading"
      ></el-button>

      <el-input
        ref="inputBox"
        type="textarea"
        v-model="inputText"
        :placeholder="isLoading ? 'AI 正在回复中...' : '输入你的问题，Shift+Enter 换行，Enter 发送'"
        :disabled="isLoading"
        :autosize="{ minRows: 1, maxRows: 6 }"
        @keydown.native="handleKeydown"
      ></el-input>
      <el-button
        class="send-btn"
        type="primary"
        icon="el-icon-s-promotion"
        :loading="isLoading"
        :disabled="!canSend"
        @click="handleSend"
      >发送</el-button>
    </div>

    <!-- 隐藏的文件选择器 -->
    <input
      ref="fileInput"
      type="file"
      accept=".xlsx,.xls,.csv"
      style="display: none"
      @change="handleFileSelect"
    />
  </div>
</template>

<script>
import { uploadAttachment } from '@/api/agent'

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
      inputText: '',
      attachments: [],  // [{id, name, size, status: 'uploading'|'success'|'error'}]
      isDragOver: false
    }
  },
  computed: {
    canSend() {
      if (this.isLoading) return false
      const hasText = this.inputText.trim().length > 0
      const hasAttachments = this.attachments.some(a => a.status === 'success')
      return hasText || hasAttachments
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
      // 检查是否有文件正在上传
      const uploadingAttachments = this.attachments.filter(a => a.status === 'uploading')
      if (uploadingAttachments.length > 0) {
        this.$message.warning('文件正在上传，请稍候...')
        return
      }

      const text = this.inputText.trim()
      const attachmentIds = this.attachments
        .filter(a => a.status === 'success' && a.id)
        .map(a => a.id)

      if ((!text && !attachmentIds.length) || this.isLoading) return

      // 确保 message 始终为有效字符串，附件场景下给默认描述
      const msg = text || (attachmentIds.length ? '请处理上传的文件' : '')

      this.$emit('send', {
        message: msg,
        attachments: attachmentIds
      })

      this.inputText = ''
      this.attachments = []
    },

    /** 外部调用：设置输入框文本 */
    setText(text) {
      this.inputText = text
    },

    triggerFileSelect() {
      this.$refs.fileInput.click()
    },

    handleFileSelect(e) {
      const file = e.target.files[0]
      if (file) this.uploadFile(file)
      e.target.value = ''
    },

    onDragOver() {
      this.isDragOver = true
    },
    onDragLeave() {
      this.isDragOver = false
    },

    onDrop(e) {
      this.isDragOver = false
      const file = e.dataTransfer.files[0]
      if (file) {
        const ext = '.' + file.name.split('.').pop().toLowerCase()
        if (['.xlsx', '.xls', '.csv'].includes(ext)) {
          this.uploadFile(file)
        } else {
          this.$message.warning('仅支持 .xlsx/.xls/.csv 文件')
        }
      }
    },

    async uploadFile(file) {
      const att = { id: null, name: file.name, size: file.size, status: 'uploading' }
      this.attachments.push(att)
      const idx = this.attachments.length - 1

      try {
        const res = await uploadAttachment(file)
        const data = res.data || res
        this.$set(this.attachments, idx, {
          ...att,
          id: data.attachment_id,
          status: 'success'
        })
      } catch (err) {
        this.$set(this.attachments, idx, { ...att, status: 'error' })
        this.$message.error('文件上传失败: ' + (err.message || '未知错误'))
      }
    },

    removeAttachment(idx) {
      this.attachments.splice(idx, 1)
    },

    formatSize(bytes) {
      if (bytes < 1024) return bytes + 'B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB'
      return (bytes / (1024 * 1024)).toFixed(1) + 'MB'
    }
  }
}
</script>

<style scoped>
.input-area {
  border-top: 1px solid #ebeef5;
  padding: 16px 20px;
  background: #fff;
  position: relative;
}

.input-area.drag-over {
  border-color: #409eff !important;
  background-color: #ecf5ff;
}

.drag-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(64, 158, 255, 0.1);
  border: 2px dashed #409eff;
  border-radius: 4px;
  z-index: 10;
  gap: 8px;
  font-size: 14px;
  color: #409eff;
}

.attachment-list {
  padding: 4px 0 8px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.input-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-wrapper >>> .el-textarea__inner {
  resize: none;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.5;
}

.attach-btn {
  flex-shrink: 0;
}

.send-btn {
  flex-shrink: 0;
  height: 40px;
  border-radius: 8px;
}
</style>
