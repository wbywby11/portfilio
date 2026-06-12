<template>
  <el-dialog
    :title="`资产行情 - ${assetName}`"
    :visible.sync="dialogVisible"
    width="1200px"
    append-to-body
    top="5vh"
    custom-class="asset-chart-dialog"
    @close="handleClose"
  >
    <asset-quote
      v-if="dialogVisible && assetCode"
      is-dialog
      :asset-code="assetCode"
      :start-date="startDate"
      :end-date="endDate"
    />
  </el-dialog>
</template>

<script>
import AssetQuote from '@/views/asset/AssetQuote.vue'

export default {
  name: 'AssetChartDialog',
  components: {
    AssetQuote
  },
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    assetCode: {
      type: String,
      default: ''
    },
    assetName: {
      type: String,
      default: ''
    },
    /** 表格推断出的起始日期，传给 AssetQuote 使默认展示区间与表格同源 */
    startDate: {
      type: String,
      default: ''
    },
    /** 表格推断出的结束日期 */
    endDate: {
      type: String,
      default: ''
    }
  },
  computed: {
    dialogVisible: {
      get() {
        return this.visible
      },
      set(val) {
        this.$emit('update:visible', val)
      }
    }
  },
  methods: {
    handleClose() {
      this.$emit('update:visible', false)
    }
  }
}
</script>

<style scoped>
.asset-chart-dialog >>> .el-dialog__body {
  padding: 10px 20px 20px;
  max-height: 80vh;
  overflow-y: auto;
}
</style>
