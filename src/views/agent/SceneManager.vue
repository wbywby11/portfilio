<template>
  <div class="scene-manager">
    <!-- 顶部说明 -->
    <div class="page-header">
      <h3>场景管理</h3>
      <p class="page-desc">管理数智平台AI助手的业务场景配置，包括启用/禁用场景和编辑快捷问题。</p>
    </div>

    <!-- 场景卡片列表 -->
    <div v-loading="loading" class="scene-grid">
      <el-card
        v-for="scene in localScenes"
        :key="scene.key"
        class="scene-card"
        shadow="hover"
      >
        <div class="card-header">
          <div class="card-title-row">
            <i :class="scene.icon" :style="{ color: scene.color, fontSize: '20px' }"></i>
            <span class="scene-name">{{ scene.label }}</span>
            <el-tag v-if="scene.key === 'auto'" size="mini" effect="plain">默认</el-tag>
          </div>
          <el-switch
            :value="scene.enabled !== false"
            active-color="#67C23A"
            @change="handleToggleScene(scene, $event)"
          />
        </div>

        <div class="scene-key">
          <span class="key-label">Key:</span>
          <code>{{ scene.key }}</code>
          <span v-if="scene.toolset" class="toolset-tag">
            <span class="key-label">Toolset:</span>
            <code>{{ scene.toolset }}</code>
          </span>
        </div>

        <p class="scene-desc">{{ scene.description }}</p>

        <!-- 快捷问题编辑 -->
        <div class="quick-questions-section">
          <div class="section-title">
            <span>快捷问题</span>
            <el-button
              type="text"
              size="mini"
              icon="el-icon-plus"
              @click="handleAddQuestion(scene)"
            >添加</el-button>
          </div>
          <div
            v-for="(q, idx) in scene.quickQuestions"
            :key="idx"
            class="question-item"
          >
            <span class="question-index">{{ idx + 1 }}.</span>
            <span class="question-text">{{ quickQuestionLabel(q) }}</span>
            <span class="question-actions">
              <el-button
                type="text"
                size="mini"
                icon="el-icon-edit"
                @click="handleEditQuestion(scene, idx)"
              />
              <el-button
                type="text"
                size="mini"
                icon="el-icon-delete"
                class="delete-btn"
                @click="handleRemoveQuestion(scene, idx)"
              />
            </span>
          </div>
          <div v-if="!scene.quickQuestions || !scene.quickQuestions.length" class="no-questions">
            暂无快捷问题
          </div>
        </div>
      </el-card>
    </div>

    <!-- 编辑快捷问题对话框 -->
    <el-dialog
      :title="editDialog.isAdd ? '添加快捷问题' : '编辑快捷问题'"
      :visible.sync="editDialog.visible"
      width="480px"
      append-to-body
    >
      <el-form :model="editDialog" label-width="80px">
        <el-form-item label="问题内容">
          <el-input
            v-model="editDialog.question"
            type="textarea"
            :rows="3"
            placeholder="请输入快捷问题内容"
          />
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="editDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveQuestion">确定</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
/**
 * 场景管理页面 — 管理员专用
 * 查看/启用/禁用场景、编辑快捷问题
 */
import { AGENT_SCENES } from '@/config/agentScenes'
import { quickQuestionLabel } from '@/config/creditRatingQuickAddons'

export default {
  name: 'SceneManager',
  data() {
    return {
      loading: false,
      /** 本地场景列表（可编辑状态，初始化自全局配置） */
      localScenes: AGENT_SCENES.map(s => ({
        ...s,
        enabled: s.enabled !== false,
        quickQuestions: [...(s.quickQuestions || [])]
      })),
      /** 编辑对话框状态 */
      editDialog: {
        visible: false,
        isAdd: false,
        sceneKey: '',
        questionIdx: -1,
        question: ''
      }
    }
  },
  methods: {
    quickQuestionLabel,

    /** 切换场景启用/禁用 */
    handleToggleScene(scene, enabled) {
      if (scene.key === 'auto') {
        this.$message.warning('智能匹配场景不可禁用')
        return
      }
      scene.enabled = enabled
      this.$message.success(enabled ? `已启用「${scene.label}」` : `已禁用「${scene.label}」`)
      // TODO: 持久化到后端
    },

    /** 添加快捷问题 */
    handleAddQuestion(scene) {
      this.editDialog = {
        visible: true,
        isAdd: true,
        sceneKey: scene.key,
        questionIdx: -1,
        question: ''
      }
    },

    /** 编辑快捷问题 */
    handleEditQuestion(scene, idx) {
      const raw = scene.quickQuestions[idx]
      this.editDialog = {
        visible: true,
        isAdd: false,
        sceneKey: scene.key,
        questionIdx: idx,
        question: quickQuestionLabel(raw)
      }
    },

    /** 保存快捷问题（新增或编辑） */
    handleSaveQuestion() {
      const q = this.editDialog.question.trim()
      if (!q) {
        this.$message.warning('问题内容不能为空')
        return
      }
      const scene = this.localScenes.find(s => s.key === this.editDialog.sceneKey)
      if (!scene) return

      if (this.editDialog.isAdd) {
        scene.quickQuestions.push(q)
      } else {
        const idx = this.editDialog.questionIdx
        const prev = scene.quickQuestions[idx]
        const preserved =
          prev &&
          typeof prev === 'object' &&
          prev.system_turn_addon &&
          scene.key === 'credit_rating'
            ? { message: q, system_turn_addon: prev.system_turn_addon }
            : q
        this.$set(scene.quickQuestions, idx, preserved)
      }
      this.editDialog.visible = false
      this.$message.success(this.editDialog.isAdd ? '已添加快捷问题' : '已更新快捷问题')
      // TODO: 持久化到后端
    },

    /** 删除快捷问题 */
    handleRemoveQuestion(scene, idx) {
      this.$confirm('确定删除该快捷问题？', '提示', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(() => {
        scene.quickQuestions.splice(idx, 1)
        this.$message.success('已删除')
        // TODO: 持久化到后端
      }).catch(() => {})
    }
  }
}
</script>

<style scoped>
.scene-manager {
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
  padding: 20px;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h3 {
  margin: 0 0 4px;
  font-size: 18px;
  color: #303133;
}

.page-desc {
  margin: 0;
  font-size: 13px;
  color: #909399;
}

.scene-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}

.scene-card {
  transition: transform 0.2s;
}

.scene-card:hover {
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scene-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.scene-key {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.scene-key code {
  background: #f5f7fa;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  color: #606266;
}

.toolset-tag {
  margin-left: 12px;
}

.key-label {
  font-weight: 600;
  color: #606266;
}

.scene-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin: 0 0 16px;
}

.quick-questions-section {
  border-top: 1px solid #ebeef5;
  padding-top: 12px;
}

.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.question-item {
  display: flex;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px solid #f5f7fa;
}

.question-item:last-child {
  border-bottom: none;
}

.question-index {
  color: #909399;
  margin-right: 6px;
  flex-shrink: 0;
}

.question-text {
  flex: 1;
  color: #303133;
  line-height: 1.4;
}

.question-actions {
  flex-shrink: 0;
  display: flex;
  gap: 2px;
}

.delete-btn {
  color: #F56C6C !important;
}

.no-questions {
  font-size: 13px;
  color: #c0c4cc;
  padding: 8px 0;
}
</style>
