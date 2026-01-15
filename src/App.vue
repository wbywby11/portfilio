<template>
  <div id="app">
    <router-view />
  </div>
</template>

<script>
export default {
  name: 'App'
};
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  width: 100%;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Microsoft YaHei', sans-serif;
  color: #333;
}

/* 全局滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #888;
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: #555;
}

/* Element UI 全局样式调整 */
.el-table {
  font-size: 13px;
}

.el-table th {
  background-color: #f5f7fa;
  font-weight: 600;
}

.el-button {
  font-size: 13px;
}

/* 数字格式化 */
.number-positive {
  color: #f56c6c;
}

.number-negative {
  color: #67c23a;
}

.number-neutral {
  color: #909399;
}

/* 卡片样式 */
.info-card {
  padding: 20px;
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  margin-bottom: 20px;
}

.info-card-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 15px;
  color: #303133;
}

/* 页面容器 */
.page-container {
  padding: 20px;
  background: #f0f2f5;
  min-height: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.page-content {
  background: #fff;
  padding: 20px;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}
</style>
