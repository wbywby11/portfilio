<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">组合详情</h2>
      <el-button @click="$router.back()">返回</el-button>
    </div>
    <div class="page-content">
      <el-alert title="功能开发中" type="info" :closable="false"></el-alert>
    </div>
  </div>
</template>

<script>
export default {
  name: 'PortfolioDetail'
};
</script>
