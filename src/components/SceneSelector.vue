<template>
  <div class="scene-selector">
    <div
      v-for="scene in scenes"
      :key="scene.key"
      :class="['scene-tag', { active: scene.key === currentScene }, { 'scene-disabled': scene.disabled }]"
      :style="tagStyle(scene)"
      @click="!scene.disabled && handleSelect(scene.key)"
    >
      <i :class="scene.icon" class="scene-icon"></i>
      <span class="scene-label">{{ scene.label }}</span>
      <span v-if="scene.disabled" class="scene-badge">即将上线</span>
    </div>
  </div>
</template>

<script>
/**
 * 场景选择器 — 横向标签式
 * Props: scenes(Array), currentScene(String)
 * Events: change(sceneKey)
 */
export default {
  name: 'SceneSelector',
  props: {
    scenes: {
      type: Array,
      required: true
    },
    currentScene: {
      type: String,
      default: 'auto'
    }
  },
  methods: {
    handleSelect(key) {
      if (key !== this.currentScene) {
        this.$emit('change', key)
      }
    },
    tagStyle(scene) {
      const isActive = scene.key === this.currentScene
      return {
        '--scene-color': scene.color,
        color: isActive ? scene.color : '#606266',
        backgroundColor: isActive ? scene.color + '12' : '#fff',
        borderColor: isActive ? scene.color : '#dcdfe6'
      }
    }
  }
}
</script>

<style scoped>
.scene-selector {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
  overflow-x: auto;
  flex-shrink: 0;
}

.scene-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  border: 1px solid #dcdfe6;
  border-radius: 16px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
  transition: all 0.25s ease;
  position: relative;
  user-select: none;
}

.scene-tag::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 50%;
  transform: translateX(-50%) scaleX(0);
  width: 60%;
  height: 2px;
  background: var(--scene-color);
  border-radius: 1px;
  transition: transform 0.25s ease;
}

.scene-tag:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.scene-tag.active::after {
  transform: translateX(-50%) scaleX(1);
}

.scene-icon {
  font-size: 14px;
}

.scene-label {
  line-height: 1;
}

.scene-disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

.scene-badge {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 4px;
  background: #909399;
  color: #fff;
  line-height: 1.2;
  margin-left: 2px;
}
</style>
