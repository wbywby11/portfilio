/**
 * 策略自定义组件注册表。
 *
 * 策略配置里只声明组件名字符串（custom_components: ["GreeksTable"]），
 * 具体实现通过此注册表映射为异步组件，四个主页签无需知道任何策略细节。
 *
 * 新增策略专属组件：
 *   1. 新建 src/views/monitor/custom/GreeksTable.vue
 *   2. 在本文件 registerDynamicComponent('GreeksTable', () => import(...))
 *   3. 策略元数据声明 custom_components: [{ component: 'GreeksTable', title: '希腊字母' }]
 */
const registry = {};

/** 注册（或覆盖）一个动态组件，loader 可为组件对象或返回 Promise 的工厂 */
export function registerDynamicComponent(name, loader) {
  if (!name || !loader) return;
  registry[name] = loader;
}

/** 批量注册：{ GreeksTable: () => import(...) } */
export function registerDynamicComponents(map) {
  Object.keys(map || {}).forEach(name => registerDynamicComponent(name, map[name]));
}

/** 解析组件；未注册返回 null，由 DynamicSlots 跳过并告警 */
export function resolveDynamicComponent(name) {
  return registry[name] || null;
}

/** 已注册组件名列表（调试/自检用） */
export function listDynamicComponents() {
  return Object.keys(registry);
}

export default {
  registerDynamicComponent,
  registerDynamicComponents,
  resolveDynamicComponent,
  listDynamicComponents
};
