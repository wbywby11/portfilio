<template>
  <div class="scene-selector">
    <el-dropdown trigger="click" @command="handleSelect" :hide-on-click="true">
      <span class="scene-trigger">
        <i :class="currentIcon" class="scene-trigger-icon"></i>
        <span class="scene-trigger-label">{{ currentLabel }}</span>
        <i class="el-icon-arrow-down scene-trigger-arrow"></i>
      </span>
      <el-dropdown-menu slot="dropdown" class="scene-dropdown">
        <el-dropdown-item
          v-for="scene in activeScenes"
          :key="scene.key"
          :command="scene.key"
          :class="{ 'is-active': scene.key === currentScene }"
        >
          <i :class="scene.icon" class="scene-menu-icon"></i>
          <span>{{ scene.label }}</span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </el-dropdown>
  </div>
</template>

<script>
/**
 * 场景选择器 — 横向标签式（仅显示可用场景）
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
  computed: {
    /** 仅显示未禁用的场景 */
    activeScenes() {
      return this.scenes.filter(s => !s.disabled)
    },
    currentLabel() {
      const cur = this.scenes.find(s => s.key === this.currentScene)
      return cur ? cur.label : '智能匹配'
    },
    currentIcon() {
      const cur = this.scenes.find(s => s.key === this.currentScene)
      return cur ? cur.icon : 'el-icon-magic-stick'
    }
  },
  methods: {
    handleSelect(key) {
      if (key !== this.currentScene) {
        this.$emit('change', key)
      }
    }
  }
}
</script>

<style scoped>
.scene-selector {
  padding: 8px 20px;
  background: transparent;
  flex-shrink: 0;
  border-bottom: 1px solid #ebeef5;
}

.scene-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #606266;
  transition: all 0.18s ease;
  user-select: none;
}

.scene-trigger:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #303133;
}

.scene-trigger-icon {
  font-size: 13px;
  color: #409eff;
}

.scene-trigger-label {
  font-weight: 500;
}

.scene-trigger-arrow {
  font-size: 10px;
  color: #909399;
  margin-left: 2px;
}

/* 下拉菜单项 */
.scene-menu-icon {
  font-size: 13px;
  margin-right: 6px;
  color: #909399;
}
</style>

<style>
/* 下拉菜单激活态（全局，不受 scoped 限制） */
.scene-dropdown .el-dropdown-menu__item.is-active {
  color: #409eff;
  font-weight: 500;
}
</style>
