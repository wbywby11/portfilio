<template>
  <div v-if="resolvedSlots.length" class="dynamic-slots">
    <div
      v-for="slot in resolvedSlots"
      :key="slot.key"
      class="dynamic-slots__item"
      :class="'dynamic-slots__item--' + (slot.span || 'full')">
      <div v-if="slot.title" class="dynamic-slots__title">{{ slot.title }}</div>
      <component :is="slot.resolved" v-bind="slot.props || {}"></component>
    </div>
  </div>
</template>

<script>
import { resolveDynamicComponent } from './dynamicRegistry';

/**
 * DynamicSlots —— 策略自定义插槽容器。
 *
 * 使用方式：
 *   <DynamicSlots :slots="overviewSlots" />
 *   slots 来自策略元数据 custom_components，两种写法均支持：
 *   ['GreeksTable']
 *   [{ component: 'GreeksTable', title: '希腊字母', span: 'half', props: { ... } }]
 *
 * component 既可以是注册表里的名字，也可以直接传组件对象。
 * 未注册的组件会被跳过并打印一次告警，不影响主页签渲染。
 */
export default {
  name: 'DynamicSlots',
  props: {
    slots: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      warned: {}
    };
  },
  computed: {
    /** 归一化：字符串简写 ['GreeksTable'] → { component: 'GreeksTable' } */
    normalizedSlots() {
      return (this.slots || []).map(slot => {
        if (typeof slot === 'string') return { component: slot };
        return slot;
      });
    },
    resolvedSlots() {
      return this.normalizedSlots
        .filter(slot => slot && slot.visible !== false && slot.component)
        .map(slot => {
          const resolved = typeof slot.component === 'object'
            ? slot.component
            : resolveDynamicComponent(slot.component);
          if (!resolved) {
            if (!this.warned[slot.component]) {
              this.warned[slot.component] = true;
              console.warn('[DynamicSlots] 组件未注册，已跳过：' + slot.component);
            }
            return null;
          }
          return {
            key: slot.key || (typeof slot.component === 'string' ? slot.component : slot.title),
            title: slot.title,
            span: slot.span,
            props: slot.props,
            resolved
          };
        })
        .filter(Boolean);
    }
  }
};
</script>

<style scoped>
.dynamic-slots {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
}

.dynamic-slots__item {
  min-width: 0;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}

.dynamic-slots__item--full {
  grid-column: 1 / -1;
}

.dynamic-slots__title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

@media (max-width: 1200px) {
  .dynamic-slots {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
