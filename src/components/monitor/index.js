import MetricCard from './MetricCard.vue';
import StandardTable from './StandardTable.vue';
import TimeSeriesChart from './TimeSeriesChart.vue';
import DynamicSlots from './DynamicSlots.vue';

export { MetricCard, StandardTable, TimeSeriesChart, DynamicSlots };
export * from './dynamicRegistry';

/** 可选：Vue.use(MonitorUI) 全局注册（当前页面按需局部引入） */
export default {
  install(Vue) {
    Vue.component('MetricCard', MetricCard);
    Vue.component('StandardTable', StandardTable);
    Vue.component('TimeSeriesChart', TimeSeriesChart);
    Vue.component('DynamicSlots', DynamicSlots);
  }
};
