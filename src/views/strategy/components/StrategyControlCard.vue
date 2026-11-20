<template>
  <el-card shadow="never" class="control-card">
    <div slot="header" class="card-header">
      <span class="card-title">
        <i class="el-icon-warning-outline"></i>
        风险控制策略
      </span>
      <el-switch
        :value="form.enable_control"
        @change="handleToggle"
        active-text="启用"
        inactive-text=""
      ></el-switch>
    </div>

    <template v-if="form.enable_control">
      <!-- 提示条 -->
      <div class="form-hint">
        <i class="el-icon-info"></i>
        <span>启用后，系统每日监控组合波动率，超过阈值时自动按 target_vol / vol 比例缩放权重，控制风险暴露。</span>
      </div>

      <!-- 控制器选择 -->
      <el-form-item label="控制器策略" label-width="100px">
        <div class="field-row">
          <el-select
            :value="form.controller_code"
            class="field-row__control"
            placeholder="请选择风险控制策略"
            @change="handleControllerCodeChange"
          >
            <el-option
              v-for="tpl in controlTemplateList"
              :key="tpl.code"
              :label="tpl.name"
              :value="tpl.code"
            ></el-option>
          </el-select>
        </div>
        <!-- 描述单独成行：塞进 option 会把下拉面板按内容宽度撑到弹窗之外 -->
        <div v-if="selectedControllerTemplate && selectedControllerTemplate.description" class="template-desc">
          {{ selectedControllerTemplate.description }}
        </div>
      </el-form-item>

      <!-- ===== 滚动窗口波动率：自定义布局 ===== -->
      <template v-if="isRollingVol">
        <div class="form-section">
          <div class="form-section-header accent-blue">
            <i class="el-icon-data-line"></i>
            <span>波动率窗口配置</span>
            <el-tooltip content="系统分别计算三个窗口的年化波动率，取最大值作为当前波动率估计" placement="top">
              <i class="el-icon-question q-icon"></i>
            </el-tooltip>
          </div>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="短期窗口" label-width="80px">
                <el-input-number
                  :value="form.controller_parameters.vol_window_short"
                  @input="updateControllerParam('vol_window_short', $event)"
                  :min="5" :max="60" :step="1" :precision="0"
                  style="width: 100%;"
                />
                <div class="param-hint">约 1 个月交易日</div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="中期窗口" label-width="80px">
                <el-input-number
                  :value="form.controller_parameters.vol_window_medium"
                  @input="updateControllerParam('vol_window_medium', $event)"
                  :min="20" :max="130" :step="5" :precision="0"
                  style="width: 100%;"
                />
                <div class="param-hint">约 1 个季度交易日</div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="长期窗口" label-width="80px">
                <el-input-number
                  :value="form.controller_parameters.vol_window_long"
                  @input="updateControllerParam('vol_window_long', $event)"
                  :min="60" :max="260" :step="10" :precision="0"
                  style="width: 100%;"
                />
                <div class="param-hint">约半年交易日</div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <div class="form-section">
          <div class="form-section-header accent-orange">
            <i class="el-icon-aim"></i>
            <span>触发与缩放</span>
            <el-tooltip content="当组合波动率超过触发阈值时，按 目标波动率/实际波动率 等比例缩放权重" placement="top">
              <i class="el-icon-question q-icon"></i>
            </el-tooltip>
          </div>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="目标波动率" label-width="90px">
                <el-input-number
                  :value="form.controller_parameters.target_vol"
                  @input="updateControllerParam('target_vol', $event)"
                  :min="0.01" :max="0.20" :step="0.005" :precision="4"
                  style="width: 100%;"
                />
                <div class="param-hint">年化目标，如 0.05 = 5%</div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="触发阈值" label-width="80px">
                <el-input-number
                  :value="form.controller_parameters.vol_reset_threshold"
                  @input="updateControllerParam('vol_reset_threshold', $event)"
                  :min="0.02" :max="0.30" :step="0.005" :precision="4"
                  style="width: 100%;"
                />
                <div class="param-hint">超过此值触发缩放</div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="启用重置" label-width="80px">
                <el-switch
                  :value="form.controller_parameters.enable_vol_reset"
                  @input="updateControllerParam('enable_vol_reset', $event)"
                ></el-switch>
                <div class="param-hint">关闭后仅监控不缩放</div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>
      </template>

      <!-- ===== 双层窗口波动率：自定义布局 ===== -->
      <template v-else-if="isDualWindowVol">
        <div class="form-section">
          <div class="form-section-header accent-blue">
            <i class="el-icon-data-line"></i>
            <span>波动率窗口配置</span>
            <el-tooltip content="使用短期+长期两个窗口的滚动波动率平均值作为当前波动率估计，更平滑稳定" placement="top">
              <i class="el-icon-question q-icon"></i>
            </el-tooltip>
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="短期窗口" label-width="80px">
                <el-input-number
                  :value="form.controller_parameters.vc_short"
                  @input="updateControllerParam('vc_short', $event)"
                  :min="5" :max="60" :step="1" :precision="0"
                  style="width: 100%;"
                />
                <div class="param-hint">短期滚动波动率窗口（交易日）</div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="长期窗口" label-width="80px">
                <el-input-number
                  :value="form.controller_parameters.vc_long"
                  @input="updateControllerParam('vc_long', $event)"
                  :min="20" :max="260" :step="5" :precision="0"
                  style="width: 100%;"
                />
                <div class="param-hint">长期滚动波动率窗口（交易日）</div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <div class="form-section">
          <div class="form-section-header accent-orange">
            <i class="el-icon-aim"></i>
            <span>触发与缩放</span>
          </div>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="目标波动率" label-width="90px">
                <el-input-number
                  :value="form.controller_parameters.target_vol"
                  @input="updateControllerParam('target_vol', $event)"
                  :min="0.01" :max="0.20" :step="0.005" :precision="4"
                  style="width: 100%;"
                />
                <div class="param-hint">年化目标波动率</div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="重置阈值" label-width="90px">
                <el-input-number
                  :value="form.controller_parameters.vol_reset_threshold"
                  @input="updateControllerParam('vol_reset_threshold', $event)"
                  :min="0.02" :max="0.30" :step="0.005" :precision="4"
                  style="width: 100%;"
                />
                <div class="param-hint">超过此值触发缩放</div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="启用重置" label-width="80px">
                <el-switch
                  :value="form.controller_parameters.enable_vol_reset"
                  @input="updateControllerParam('enable_vol_reset', $event)"
                ></el-switch>
                <div class="param-hint">关闭后仅监控不缩放</div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>
      </template>

      <!-- ===== 未知控制器：通用渲染回退 ===== -->
      <template v-else-if="selectedControllerTemplate && selectedControllerTemplate.parameters && selectedControllerTemplate.parameters.length > 0">
        <el-divider content-position="left">
          {{ selectedControllerTemplate.name }} 参数
        </el-divider>
        <param-field-renderer
          v-for="param in selectedControllerTemplate.parameters"
          :key="'ctrl_' + param.name"
          :param="param"
          :value="form.controller_parameters[param.name]"
          @input="updateControllerParam(param.name, $event)"
        />
      </template>

      <!-- 重置默认 -->
      <div class="reset-bar" v-if="form.controller_code">
        <el-button type="text" size="small" icon="el-icon-refresh-left" @click="$emit('reset-controller-params')">
          重置为默认参数
        </el-button>
      </div>
    </template>
  </el-card>
</template>

<script>
import ParamFieldRenderer from './ParamFieldRenderer.vue';

export default {
  name: 'StrategyControlCard',
  components: { ParamFieldRenderer },
  props: {
    form: { type: Object, required: true },
    controlTemplateList: { type: Array, default: () => [] },
    templateList: { type: Array, default: () => [] }
  },
  computed: {
    selectedControllerTemplate() {
      if (!this.form.controller_code) return null;
      return this.templateList.find(t => t.code === this.form.controller_code);
    },
    isRollingVol() {
      return this.form.controller_code === 'ctrl_rolling_vol';
    },
    isDualWindowVol() {
      return this.form.controller_code === 'ctrl_dual_window_vol';
    }
  },
  methods: {
    handleToggle(value) {
      this.form.enable_control = value;
      if (!value) {
        this.form.controller_code = '';
        this.form.controller_parameters = {};
      }
    },
    handleControllerCodeChange(code) {
      this.$emit('controller-code-change', code);
    },
    updateControllerParam(name, value) {
      this.$set(this.form.controller_parameters, name, value);
    }
  }
};
</script>

<style scoped>
.control-card {
  margin-bottom: 20px;
}

/* 下拉框占满剩余宽度 */
.field-row {
  display: flex;
  align-items: center;
}

.field-row__control {
  flex: 1;
  min-width: 0;
}

/* 描述受表单内容宽度约束自动换行，不再撑宽下拉面板 */
.template-desc {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-title {
  font-weight: 600;
  font-size: 15px;
  color: #1a1a2e;
  display: flex;
  align-items: center;
  gap: 6px;
}
.card-title i {
  color: #409eff;
  font-size: 16px;
}

/* -- form hint bar -- */
.form-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  margin-bottom: 16px;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  border-radius: 6px;
  font-size: 12px;
  color: #409eff;
  line-height: 1.5;
}
.form-hint i {
  font-size: 14px;
  flex-shrink: 0;
}

/* -- section card -- */
.form-section {
  margin-bottom: 16px;
  padding: 16px 18px 12px;
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.form-section:last-of-type {
  margin-bottom: 8px;
}

/* -- section header with left accent -- */
.form-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin: -4px 0 16px;
  padding: 8px 12px;
  background: #fff;
  border-left: 3px solid #409eff;
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.form-section-header i:first-child {
  font-size: 15px;
}
.form-section-header.accent-blue {
  border-left-color: #409eff;
}
.form-section-header.accent-blue i:first-child {
  color: #409eff;
}
.form-section-header.accent-orange {
  border-left-color: #e6a23c;
}
.form-section-header.accent-orange i:first-child {
  color: #e6a23c;
}

/* -- tooltip icon -- */
.q-icon {
  margin-left: 4px;
  color: #c0c4cc;
  cursor: help;
  font-size: 12px;
}

/* -- param hint -- */
.param-hint {
  font-size: 11px;
  color: #909399;
  margin-top: 3px;
  line-height: 1.4;
  padding-left: 2px;
}

/* -- reset bar -- */
.reset-bar {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #ebeef5;
  text-align: right;
}

/* -- form items spacing -- */
::v-deep .form-section .el-form-item {
  margin-bottom: 14px;
}
::v-deep .form-section .el-form-item__label {
  color: #606266;
  font-size: 13px;
}
</style>

