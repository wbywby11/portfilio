<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">业绩基准对比</h2>
    </div>
    <div :class="{'page-content': !isDialog}">
      <el-alert title="业绩基准对比功能开发中" type="info" :closable="false"></el-alert>
    </div>
  </div>
</template>

<script>
export default { 
  name: 'Benchmark',
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    id: {
      type: String,
      default: ''
    }
  }
};
</script>
