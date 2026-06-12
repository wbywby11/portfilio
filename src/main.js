import Vue from 'vue';
import App from './App.vue';
import router from './router';
import store from './store';
import ElementUI from 'element-ui';
import 'element-ui/lib/theme-chalk/index.css';
import 'vxe-table/lib/style.css';
import * as echarts from 'echarts';
import VXETable from 'vxe-table';
import VxeTooltip from 'vxe-table/lib/tooltip';
import VXETablePluginElement from 'vxe-table-plugin-element'
import 'vxe-table-plugin-element/dist/style.css'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import VueVirtualScroller from 'vue-virtual-scroller'

Vue.use(ElementUI);
Vue.use(VueVirtualScroller);
VXETable.use(VXETablePluginElement)
Vue.use(VXETable);
Vue.use(VxeTooltip);

Vue.prototype.$echarts = echarts;

Vue.config.productionTip = false;

new Vue({
  router,
  store,
  render: h => h(App)
}).$mount('#app');
