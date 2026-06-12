<template>
  <el-dialog
    :visible.sync="dialogVisible"
    :title="dialogTitle"
    width="780px"
    append-to-body
    :close-on-click-modal="false"
    @close="onClose">
    <el-form
      ref="form"
      :model="formData"
      :rules="formRules"
      label-width="140px"
      label-position="right"
      size="small"
      class="record-form">
      <el-row :gutter="16">
        <el-col v-for="field in formFields" :key="field.key" :span="fieldSpan(field)">
          <el-form-item :label="field.label" :prop="field.key">
            <!-- 枚举/外键下拉 -->
            <el-select
              v-if="field.type === 'enum' || (field.options && field.options.length)"
              v-model="formData[field.key]"
              :placeholder="`请选择 ${field.label}`"
              :allow-create="!!field.allowCreate"
              :filterable="true"
              :disabled="field.primary && isEdit"
              clearable
              style="width:100%">
              <el-option v-for="opt in field.options" :key="opt" :label="opt" :value="opt" />
            </el-select>
            <!-- 日期 -->
            <el-date-picker
              v-else-if="field.type === 'date'"
              v-model="formData[field.key]"
              type="date"
              format="yyyyMMdd"
              value-format="yyyyMMdd"
              :placeholder="`请选择 ${field.label}`"
              :disabled="field.primary && isEdit"
              style="width:100%" />
            <!-- 数值 -->
            <el-input-number
              v-else-if="field.type === 'number'"
              v-model="formData[field.key]"
              :step="field.step || 0.01"
              :precision="field.precision != null ? field.precision : undefined"
              :controls-position="'right'"
              :disabled="field.primary && isEdit"
              style="width:100%" />
            <!-- 字符串 -->
            <el-input
              v-else
              v-model="formData[field.key]"
              :placeholder="`请输入 ${field.label}`"
              :disabled="field.primary && isEdit"
              clearable />
            <div v-if="field.primary" class="field-tip">
              <i class="el-icon-key"></i> 主键字段{{ isEdit ? '（编辑模式不可修改）' : '' }}
            </div>
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>
    <span slot="footer">
      <el-button size="small" @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" size="small" :loading="submitting" @click="submit">
        {{ isEdit ? '更新' : '保存' }}
      </el-button>
    </span>
  </el-dialog>
</template>

<script>
export default {
  name: 'RecordFormDialog',
  props: {
    visible: { type: Boolean, default: false },
    table: { type: Object, default: null },
    record: { type: Object, default: null }, // 编辑时传入；新增为 null
    submitting: { type: Boolean, default: false }
  },
  data() {
    return {
      dialogVisible: this.visible,
      formData: {}
    };
  },
  computed: {
    isEdit() {
      return !!(this.record && this.record._id);
    },
    dialogTitle() {
      if (!this.table) return '';
      return (this.isEdit ? '编辑 - ' : '新增 - ') + this.table.label + ' (' + this.table.name + ')';
    },
    formFields() {
      if (!this.table) return [];
      return this.table.fields;
    },
    formRules() {
      const rules = {};
      this.formFields.forEach(f => {
        if (f.required) {
          rules[f.key] = [{
            required: true,
            message: `请填写 ${f.label}`,
            trigger: ['blur', 'change']
          }];
        }
      });
      return rules;
    }
  },
  watch: {
    visible(v) {
      this.dialogVisible = v;
      if (v) this.initFormData();
    },
    dialogVisible(v) {
      if (!v) this.$emit('update:visible', false);
    }
  },
  methods: {
    initFormData() {
      const data = {};
      this.formFields.forEach(f => {
        if (this.record && this.record[f.key] !== undefined) {
          data[f.key] = this.record[f.key];
        } else if (f.defaultValue !== undefined) {
          data[f.key] = f.defaultValue;
        } else {
          data[f.key] = f.type === 'number' ? null : '';
        }
      });
      this.formData = data;
      this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate());
    },
    fieldSpan(field) {
      // 长字段单列、其他双列
      if (field.width && field.width >= 220) return 24;
      if (field.type === 'string' && (field.key.includes('CONTENT') || field.key.includes('SUMMARY') || field.key.includes('REMARK') || field.key.includes('NOTE'))) {
        return 24;
      }
      return 12;
    },
    submit() {
      this.$refs.form.validate(valid => {
        if (!valid) return;
        const payload = {};
        Object.keys(this.formData).forEach(k => {
          const v = this.formData[k];
          if (v !== '' && v !== null && v !== undefined) payload[k] = v;
        });
        this.$emit('submit', { isEdit: this.isEdit, payload, record: this.record });
      });
    },
    onClose() {
      this.dialogVisible = false;
    }
  }
};
</script>

<style scoped>
.record-form {
  max-height: 60vh;
  overflow-y: auto;
  padding-right: 8px;
}
.field-tip {
  font-size: 11px;
  color: #909399;
  line-height: 16px;
}
.field-tip i {
  color: #E6A23C;
}
</style>
