<template>
  <div class="backtest-result">
    <el-card shadow="never" style="margin-top: 20px;">
      <div slot="header" class="card-header">
        <span>回测结果</span>
      </div>

      <!-- 单策略回测结果（modelId 优先用传入的，否则用结果中策略 id，保证备注可保存） -->
      <div v-if="mode === 'single'">
        <single-strategy-result
          v-for="(resultData, resultKey) in singleResultsList"
          :key="resultKey"
          :strategy-name="(resultData.strategy && resultData.strategy.name) || resultKey"
          :result="resultData.result"
          :strategy="resultData.strategy"
          :remark="resultData.remark"
          :record-id="normalizedRecordId(resultData)"
          :model-id="singleStrategyModelId(resultData)"
        ></single-strategy-result>
      </div>

      <!-- 多策略对比结果 -->
      <div v-else>
        <multi-strategy-comparison
          :results="results"
        ></multi-strategy-comparison>
      </div>
    </el-card>
  </div>
</template>

<script>
import SingleStrategyResult from './backtest/SingleStrategyResult.vue';
import MultiStrategyComparison from './backtest/MultiStrategyComparison.vue';

export default {
  name: 'BacktestResult',
  components: {
    SingleStrategyResult,
    MultiStrategyComparison
  },
  props: {
    results: {
      type: Object,
      required: true
    },
    mode: {
      type: String,
      required: true,
      validator: value => ['single', 'multi'].includes(value)
    },
    config: {
      type: Object,
      default: () => ({})
    },
    modelId: {
      type: String,
      default: null
    }
  },
  computed: {
    // 单策略时过滤掉可能的 _modelId 等非策略项，只传策略名 -> 结果数据
    singleResultsList() {
      if (!this.results || this.mode !== 'single') return {};
      const out = {};
      for (const [key, val] of Object.entries(this.results)) {
        if (key !== '_modelId' && val && (val.result || val.strategy)) out[key] = val;
      }
      return out;
    }
  },
  watch: {
    singleResultsList: {
      handler(list) {
        if (this.mode !== 'single' || !list || Object.keys(list).length === 0) return;
        for (const [resultKey, resultData] of Object.entries(list)) {
          const displayName = (resultData.strategy && resultData.strategy.name) || resultKey;
          const mid = this.singleStrategyModelId(resultData);
          const rid = this.normalizedRecordId(resultData);
          console.log('[BacktestRecord] BacktestResult 传递 singleStrategyResult', 'strategyName=', displayName, 'modelId=', mid, 'recordId=', rid, 'canSave=', !!(mid && rid));
        }
      },
      immediate: true,
      deep: true
    }
  },
  methods: {
    singleStrategyModelId(resultData) {
      if (this.modelId) return this.modelId;
      const s = resultData && resultData.strategy;
      if (s && (s.id != null)) return String(s.id);
      return null;
    },
    normalizedRecordId(resultData) {
      if (!resultData) return null;
      const rid = resultData.record_id;
      if (rid != null && rid !== '') return String(rid);
      const r = resultData.result;
      if (r && r.record_id != null && r.record_id !== '') return String(r.record_id);
      return null;
    }
  }
};
</script>

<style scoped>
.backtest-result {
  margin-top: 20px;
}

.card-header {
  font-weight: 500;
  font-size: 16px;
}
</style>
