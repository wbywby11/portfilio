import Vue from 'vue';
import App from './App.vue';
import router from './router';
import store from './store';
import ElementUI from 'element-ui';
import 'element-ui/lib/theme-chalk/index.css';
import 'vxe-table/lib/style.css';
import * as echarts from 'echarts';
import VXETable from 'vxe-table';
import VXETablePluginElement from 'vxe-table-plugin-element'
import 'vxe-table-plugin-element/dist/style.css'

Vue.use(ElementUI);
VXETable.use(VXETablePluginElement)
Vue.use(VXETable);

Vue.prototype.$echarts = echarts;

Vue.config.productionTip = false;

new Vue({
  router,
  store,
  render: h => h(App)
}).$mount('#app');
