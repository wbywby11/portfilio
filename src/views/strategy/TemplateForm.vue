<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">编辑模板</h2>
    </div>

    <div :class="{'page-content': !isDialog}">
      <el-form :model="form" :rules="rules" ref="form" label-width="140px" style="max-width: 800px;">
        <el-divider content-position="left">基本信息</el-divider>
        
        <el-form-item label="模板名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入模板名称"></el-input>
        </el-form-item>

        <el-form-item label="模板代码" prop="code">
          <el-input 
            v-model="form.code" 
            placeholder="请输入模板代码，如：M001"
            :disabled="isEdit"
          ></el-input>
          <span v-if="isEdit" style="color: #909399; font-size: 12px;">编辑模式下不可修改模板代码</span>
        </el-form-item>

        <el-form-item label="模板描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="请输入模板描述"
          ></el-input>
        </el-form-item>

        <el-form-item label="策略PDF说明文档">
          <div>
            <el-upload
              :action="uploadAction"
              :headers="uploadHeaders"
              :show-file-list="false"
              :on-success="handlePdfSuccess"
              :before-upload="handlePdfBefore"
              accept=".pdf"
            >
              <el-button size="small" type="primary" icon="el-icon-upload" :loading="uploadingPdf">上传PDF</el-button>
            </el-upload>
            <span v-if="form.pdf_filename" style="margin-left: 12px; color: #67c23a; font-size: 13px;">
              已上传: {{ form.pdf_filename }}
              <el-button type="text" icon="el-icon-delete" @click="removePdf">移除</el-button>
            </span>
            <div style="color: #909399; font-size: 12px; margin-top: 4px;">
              支持PDF格式，文件大小不超过50MB。上传后点击「查看详情」可在弹窗中展示
            </div>
          </div>
        </el-form-item>

        <el-form-item label="策略源代码">
          <div class="codemirror-wrapper">
            <textarea ref="codeEditor"></textarea>
          </div>
        </el-form-item>

        <el-divider content-position="left">参数配置</el-divider>

        <el-form-item label="模型参数">
          <div style="color: #909399; font-size: 12px; margin-bottom: 12px;">
            参数由策略代码定义，此处仅可修改显示名称
          </div>
          <div v-for="(param, index) in form.parameters" :key="index" style="margin-top: 10px;">
            <el-card shadow="never">
              <el-row :gutter="15">
                <el-col :span="8">
                  <el-form-item label="参数名" label-width="80px">
                    <el-input v-model="param.name" disabled></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="显示名" label-width="80px">
                    <el-input v-model="param.label" placeholder="如：风险容忍度"></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="类型" label-width="80px">
                    <el-input :value="getParamTypeLabel(param.param_type)" disabled></el-input>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="15">
                <el-col :span="8">
                  <el-form-item label="默认值" label-width="80px">
                    <el-input :value="formatParamDefault(param)" disabled></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="16">
                  <el-form-item label="参数说明" label-width="80px">
                    <el-input v-model="param.description" placeholder="请输入参数说明"></el-input>
                  </el-form-item>
                </el-col>
              </el-row>
            </el-card>
          </div>
          <div v-if="!form.parameters || form.parameters.length === 0" style="color: #909399; font-size: 13px;">
            该策略无可调参数
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="handleSubmit" :loading="submitting">
            保存
          </el-button>
          <el-button @click="handleCancel">取消</el-button>
        </el-form-item>
      </el-form>
    </div>

  </div>
</template>

<script>
import { updateTemplate } from '@/api/strategy';
import request from '@/utils/request';
import CodeMirror from 'codemirror';
import 'codemirror/lib/codemirror.css';
import 'codemirror/theme/monokai.css';
import 'codemirror/mode/python/python';

// 与其他接口统一：从共享 axios 实例的 baseURL 派生后端地址，不再回退 127.0.0.1
const API_BASE = String(request.defaults.baseURL || process.env.VUE_APP_BASE_URL || '').replace(/\/$/, '');

export default {
  name: 'TemplateForm',
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    code: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      form: {
        code: '',
        name: '',
        description: '',
        source_code: '',
        pdf_filename: null,
        parameters: []
      },
      rules: {
        name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
        code: [{ required: true, message: '请输入模板代码', trigger: 'blur' }],
        description: [{ required: true, message: '请输入模板描述', trigger: 'blur' }]
      },
      submitting: false,
      isEdit: false,
      currentTemplateId: null,
      codeEditor: null,  // CodeMirror 实例
      uploadingPdf: false  // PDF 上传中
    };
  },
  computed: {
    uploadAction() {
      // 编辑模式且有 currentTemplateId 时才能上传
      return this.currentTemplateId
        ? `${API_BASE}/api/v1/model-templates/${this.currentTemplateId}/upload-pdf`
        : '';
    },
    uploadHeaders() {
      const store = this.$store;
      const token = store.state.user && store.state.user.token;
      return token ? { Authorization: `Bearer ${token}` } : {};
    }
  },
  created() {
    const code = this.isDialog ? this.code : this.$route.params.id;
    if (code) {
      this.isEdit = true;
      this.loadTemplate(code);
    }
  },
  watch: {
    code(newVal) {
      if (this.isDialog && newVal) {
        this.isEdit = true;
        this.loadTemplate(newVal);
      } else if (this.isDialog && !newVal) {
        this.isEdit = false;
        this.resetForm();
      }
    }
  },
  methods: {
    resetForm() {
      this.form = {
        code: '',
        name: '',
        description: '',
        source_code: '',
        pdf_filename: null,
        parameters: []
      };
      if (this.codeEditor) {
        this.codeEditor.setValue('');
      }
    },
    async loadTemplate(templateCode) {
      try {
        // 使用 code 获取模板
        const template = await this.$store.dispatch('strategy/fetchTemplate', templateCode);
        this.currentTemplateId = template.id;  // 保存 id 用于更新
        this.form = {
          code: template.code,
          name: template.name,
          description: template.description || '',
          source_code: template.source_code || '',
          pdf_filename: template.pdf_filename || null,
          parameters: (template.parameters || []).map(param => ({
            ...param,
            // 如果options是数组，转换为逗号分隔的字符串
            options: Array.isArray(param.options) ? param.options.join(',') : param.options,
            // 如果是dict类型且是对象，转换为JSON字符串显示
            default_value: param.param_type === 'dict' && typeof param.default_value === 'object'
              ? JSON.stringify(param.default_value, null, 2)
              : param.default_value
          }))
        };
        // 设置代码编辑器的内容
        if (this.codeEditor) {
          this.codeEditor.setValue(template.source_code || '');
        }
      } catch (error) {
        this.$message.error('加载模板数据失败');
        this.$router.back();
      }
    },
    handlePdfBefore(file) {
      if (file.type !== 'application/pdf') {
        this.$message.error('仅支持PDF文件格式');
        return false;
      }
      if (file.size / 1024 / 1024 > 50) {
        this.$message.error('文件大小不能超过50MB');
        return false;
      }
      this.uploadingPdf = true;
      return true;
    },
    handlePdfSuccess(response) {
      this.uploadingPdf = false;
      const data = response.data || response;
      if (data.pdf_filename) {
        this.form.pdf_filename = data.pdf_filename;
        this.$message.success('PDF上传成功');
      } else {
        this.$message.error('上传失败：未获取到文件信息');
      }
    },
    removePdf() {
      this.form.pdf_filename = null;
      this.$message.success('PDF已移除（重新保存模板后生效）');
    },
    getParamTypeLabel(type) {
      const map = { number: '数字', string: '文本', boolean: '复选框', select: '下拉选择', slider: '滑块', dict: '字典(JSON)' };
      return map[type] || type;
    },
    formatParamDefault(param) {
      if (param.param_type === 'boolean') return param.default_value ? '是' : '否';
      if (param.default_value == null || param.default_value === '') return '-';
      return String(param.default_value);
    },
    // options 必须是数组；库内存在历史脏数据（如被 String() 强转的 "[object Object],..."），
    // 提交前统一清洗：合法数组保留，JSON 字符串解析，其余损坏值置 null，避免 PUT 422
    normalizeOptions(v) {
      if (Array.isArray(v)) return v;
      if (typeof v === 'string') {
        const s = v.trim();
        if (s.startsWith('[')) {
          try { return JSON.parse(s); } catch (e) { return null; }
        }
      }
      return null;
    },
    handleSubmit() {
      this.$refs.form.validate(async (valid) => {
        if (valid) {
          this.submitting = true;
          try {
            const submitData = {
              code: this.form.code,
              name: this.form.name,
              description: this.form.description,
              source_code: this.form.source_code || null,
              parameters: this.form.parameters.map(param => ({
                name: param.name,
                label: param.label,
                param_type: param.param_type,
                default_value: param.default_value,
                required: param.required,
                description: param.description || null,
                min_value: param.min_value,
                max_value: param.max_value,
                step: param.step,
                options: this.normalizeOptions(param.options)
              }))
            };

            await updateTemplate(this.currentTemplateId, submitData);
            this.$message.success('模板更新成功');
            
            if (this.isDialog) {
              this.$emit('success');
            } else {
              // 返回列表页
              this.$router.push({ name: 'StrategyTemplate' });
            }
          } catch (error) {
            console.error('提交失败:', error);
            const errorMsg = error.response && error.response.data && error.response.data.detail 
              ? error.response.data.detail 
              : error.message || '操作失败';
            this.$message.error(errorMsg);
          } finally {
            this.submitting = false;
          }
        }
      });
    },
    handleCancel() {
      if (this.isDialog) {
        this.$emit('close');
      } else {
        this.$router.back();
      }
    },
    // 初始化 CodeMirror 编辑器
    initCodeEditor() {
      this.codeEditor = CodeMirror.fromTextArea(this.$refs.codeEditor, {
        mode: 'python',           // Python 语法高亮
        theme: 'monokai',         // Monokai 主题
        lineNumbers: true,        // 显示行号
        lineWrapping: true,       // 自动换行
        indentUnit: 4,            // 缩进 4 个空格
        tabSize: 4,               // Tab 键 4 个空格
        indentWithTabs: false,    // 使用空格缩进
        matchBrackets: true,      // 括号匹配
        autoCloseBrackets: true,  // 自动闭合括号
        extraKeys: {
          'Tab': (cm) => cm.execCommand('indentMore'),
          'Shift-Tab': (cm) => cm.execCommand('indentLess')
        }
      });
      
      // 代码编辑器只读，仅用于查看源码
      this.codeEditor.on('change', () => {
        this.form.source_code = this.codeEditor.getValue();
      });
      
      // 设置高度
      this.codeEditor.setOption('readOnly', true);
      this.codeEditor.setSize(null, '400px');
    }
  },
  mounted() {
    this.initCodeEditor();
  },
  beforeDestroy() {
    // 清理 CodeMirror 实例
    if (this.codeEditor) {
      this.codeEditor.toTextArea();
    }
  },
  watch: {
    // 如果 form.source_code 从外部变化，同步到编辑器
    'form.source_code'(newVal) {
      if (this.codeEditor && this.codeEditor.getValue() !== newVal) {
        this.codeEditor.setValue(newVal || '');
      }
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}

.page-header {
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #303133;
  margin: 0;
}

.page-content {
  background: #fff;
  padding: 20px;
  border-radius: 4px;
}

/* CodeMirror 编辑器样式 */
.codemirror-wrapper {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}

/* 覆盖 CodeMirror 默认样式 */
.codemirror-wrapper >>> .CodeMirror {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;  /* 字体大小调小 */
  line-height: 1.4; /* 行高调小 */
  height: 400px;
}

.codemirror-wrapper >>> .CodeMirror-gutters {
  background-color: #272822;
  border-right: 1px solid #3e3d32;
}

.codemirror-wrapper >>> .CodeMirror-linenumber {
  color: #75715e;
  font-size: 12px;  /* 行号字体更小 */
  padding: 0 5px;
}

/* 代码行样式 */
.codemirror-wrapper >>> .CodeMirror-line {
  padding: 0 4px;  /* 减少行内边距 */
}
</style>
