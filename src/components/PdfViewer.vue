<template>
  <div class="pdf-viewer">
    <!-- 加载状态 -->
    <div class="pdf-loading" v-if="loading">
      <i class="el-icon-loading"></i>
      <span>加载中…</span>
    </div>

    <!-- 空状态 -->
    <div class="pdf-empty" v-if="!url">
      <i class="el-icon-document"></i>
      <p>暂无PDF文档</p>
    </div>

    <!-- 浏览器原生 PDF 渲染（自带翻页/缩放/打印/下载工具栏） -->
    <iframe
      v-if="url"
      v-show="!loading"
      :src="url"
      class="pdf-frame"
      title="策略说明文档"
      @load="loading = false"
    ></iframe>
  </div>
</template>

<script>
export default {
  name: 'PdfViewer',
  props: {
    /** PDF 文件的完整 URL */
    url: { type: String, default: '' }
  },
  data() {
    return {
      loading: false
    };
  },
  watch: {
    url: {
      immediate: true,
      handler(val) {
        this.loading = !!val;
      }
    }
  }
};
</script>

<style scoped>
.pdf-viewer {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  background: #525659;
  border-radius: 6px;
  overflow: hidden;
}

.pdf-frame {
  flex: 1;
  width: 100%;
  border: none;
  display: block;
}

/* ── 加载 & 空状态 ── */
.pdf-loading,
.pdf-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: #999;
  gap: 8px;
}
.pdf-loading i,
.pdf-empty i {
  font-size: 36px;
  color: #666;
}
.pdf-loading i {
  animation: pdf-spin 1s linear infinite;
}
@keyframes pdf-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
</style>
