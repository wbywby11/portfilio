<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑模板' : '新增模板' }}</h2>
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

        <el-form-item label="算法源代码">
          <div class="codemirror-wrapper">
            <textarea ref="codeEditor"></textarea>
          </div>
        </el-form-item>

        <el-divider content-position="left">参数配置</el-divider>

        <el-form-item label="模型参数">
          <el-button size="small" icon="el-icon-plus" @click="addParam">添加参数</el-button>
          <div v-for="(param, index) in form.parameters" :key="index" style="margin-top: 15px;">
            <el-card shadow="never">
              <div slot="header" style="display: flex; justify-content: space-between; align-items: center;">
                <span>参数 {{ index + 1 }}</span>
                <el-button type="danger" icon="el-icon-delete" size="mini" @click="removeParam(index)">删除</el-button>
              </div>
              <el-row :gutter="15">
                <el-col :span="12">
                  <el-form-item label="参数名" label-width="80px">
                    <el-input v-model="param.name" placeholder="如：risk_tolerance"></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="显示名" label-width="80px">
                    <el-input v-model="param.label" placeholder="如：风险容忍度"></el-input>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="15">
                <el-col :span="8">
                  <el-form-item label="参数类型" label-width="80px">
                    <el-select v-model="param.param_type" placeholder="请选择" style="width: 100%;" @change="handleParamTypeChange(param)">
                      <el-option label="数字" value="number"></el-option>
                      <el-option label="文本" value="string"></el-option>
                      <el-option label="复选框" value="boolean"></el-option>
                      <el-option label="下拉选择" value="select"></el-option>
                      <el-option label="滑块" value="slider"></el-option>
                      <el-option label="字典(JSON)" value="dict"></el-option>
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="默认值" label-width="80px">
                    <!-- 数字/滑块类型用数字输入框 -->
                    <el-input-number 
                      v-if="param.param_type === 'number' || param.param_type === 'slider'"
                      v-model="param.default_value" 
                      style="width: 100%;" 
                      :controls="false"
                      placeholder="请输入"
                    ></el-input-number>
                    <!-- 布尔类型用开关 -->
                    <el-switch 
                      v-else-if="param.param_type === 'boolean'"
                      v-model="param.default_value"
                      active-text="是"
                      inactive-text="否"
                    ></el-switch>
                    <!-- 字典类型用文本域 -->
                    <el-input
                      v-else-if="param.param_type === 'dict'"
                      type="textarea"
                      v-model="param.default_value"
                      :rows="3"
                      placeholder='请输入JSON字符串，如：{"key": "value"}'
                    ></el-input>
                    <!-- 其他类型用普通输入框 -->
                    <el-input 
                      v-else
                      v-model="param.default_value" 
                      placeholder="请输入"
                    ></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="是否必填" label-width="80px">
                    <el-switch v-model="param.required"></el-switch>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="15" v-if="param.param_type === 'number' || param.param_type === 'slider'">
                <el-col :span="8">
                  <el-form-item label="最小值" label-width="80px">
                    <el-input-number v-model="param.min_value" style="width: 100%;" :controls="false"></el-input-number>
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="最大值" label-width="80px">
                    <el-input-number v-model="param.max_value" style="width: 100%;" :controls="false"></el-input-number>
                  </el-form-item>
                </el-col>
                <el-col :span="8" v-if="param.param_type === 'slider'">
                  <el-form-item label="步长" label-width="80px">
                    <el-input-number v-model="param.step" style="width: 100%;" :controls="false" :min="1"></el-input-number>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="15" v-if="param.param_type === 'select'">
                <el-col :span="24">
                  <el-form-item label="选项列表" label-width="80px">
                    <el-input v-model="param.options" placeholder="请输入选项，用逗号分隔，如：option1,option2,option3"></el-input>
                    <span style="color: #909399; font-size: 12px;">多个选项用逗号分隔</span>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-form-item label="参数说明" label-width="80px">
                <el-input v-model="param.description" type="textarea" :rows="2" placeholder="请输入参数说明"></el-input>
              </el-form-item>
            </el-card>
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="handleSubmit" :loading="submitting">
            {{ isEdit ? '保存' : '创建' }}
          </el-button>
          <el-button @click="handleValidate" :loading="validating" icon="el-icon-check">
            验证模板
          </el-button>
          <el-button @click="handleCancel">取消</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 验证结果对话框 -->
    <el-dialog
      title="模板验证结果"
      :visible.sync="validateDialogVisible"
      width="600px"
    >
      <div v-if="validateResult">
        <el-alert
          :title="validateResult.valid ? '验证通过' : '验证失败'"
          :type="validateResult.valid ? 'success' : 'error'"
          :closable="false"
          show-icon
        >
        </el-alert>

        <div v-if="validateResult.strategy_class" style="margin-top: 15px;">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="策略类名">
              <el-tag type="success">{{ validateResult.strategy_class }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <div v-if="validateResult.errors && validateResult.errors.length > 0" style="margin-top: 15px;">
          <h4 style="color: #f56c6c;">错误信息：</h4>
          <ul style="color: #f56c6c;">
            <li v-for="(error, index) in validateResult.errors" :key="'error-' + index">
              {{ error }}
            </li>
          </ul>
        </div>

        <div v-if="validateResult.warnings && validateResult.warnings.length > 0" style="margin-top: 15px;">
          <h4 style="color: #e6a23c;">警告信息：</h4>
          <ul style="color: #e6a23c;">
            <li v-for="(warning, index) in validateResult.warnings" :key="'warning-' + index">
              {{ warning }}
            </li>
          </ul>
        </div>
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="validateDialogVisible = false">关闭</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { createTemplate, updateTemplate, validateTemplate } from '@/api/strategy';
import CodeMirror from 'codemirror';
import 'codemirror/lib/codemirror.css';
import 'codemirror/theme/monokai.css';
import 'codemirror/mode/python/python';

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
        parameters: []
      },
      rules: {
        name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
        code: [{ required: true, message: '请输入模板代码', trigger: 'blur' }],
        description: [{ required: true, message: '请输入模板描述', trigger: 'blur' }]
      },
      submitting: false,
      validating: false,
      validateDialogVisible: false,
      validateResult: null,
      isEdit: false,
      currentTemplateId: null,
      codeEditor: null  // CodeMirror 实例
    };
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
    addParam() {
      this.form.parameters.push({
        name: '',
        label: '',
        param_type: 'number',
        default_value: 0,  // 数字类型默认为0
        required: true,
        description: '',
        min_value: null,
        max_value: null,
        step: null,
        options: null
      });
    },
    removeParam(index) {
      this.form.parameters.splice(index, 1);
    },
    handleParamTypeChange(param) {
      // 切换参数类型时，重置默认值为适合的类型
      if (param.param_type === 'boolean') {
        param.default_value = false;
      } else if (param.param_type === 'number' || param.param_type === 'slider') {
        param.default_value = 0;
      } else if (param.param_type === 'dict') {
        param.default_value = '{}';
      } else {
        param.default_value = '';
      }
    },
    handleSubmit() {
      this.$refs.form.validate(async (valid) => {
        if (valid) {
          this.submitting = true;
          try {
            // 准备提交数据
            const submitData = {
              code: this.form.code,
              name: this.form.name,
              description: this.form.description,
              source_code: this.form.source_code || null,
              parameters: this.form.parameters.map(param => {
                const paramData = {
                  name: param.name,
                  label: param.label,
                  param_type: param.param_type,
                  required: param.required,
                  description: param.description || null
                };
                
                // 处理默认值，确保类型正确
                if (param.param_type === 'boolean') {
                  paramData.default_value = Boolean(param.default_value);
                } else if (param.param_type === 'number' || param.param_type === 'slider') {
                  paramData.default_value = Number(param.default_value) || 0;
                } else if (param.param_type === 'dict') {
                  try {
                    paramData.default_value = typeof param.default_value === 'string' 
                      ? JSON.parse(param.default_value) 
                      : param.default_value;
                  } catch (e) {
                    paramData.default_value = {};
                  }
                } else {
                  paramData.default_value = param.default_value;
                }
                
                // 数字和滑块类型需要最小值和最大值
                if (param.param_type === 'number' || param.param_type === 'slider') {
                  paramData.min_value = param.min_value;
                  paramData.max_value = param.max_value;
                }
                
                // 滑块类型需要步长
                if (param.param_type === 'slider') {
                  paramData.step = param.step;
                }
                
                // 下拉选择类型需要选项列表
                if (param.param_type === 'select') {
                  // 将逗号分隔的字符串转换为数组
                  paramData.options = param.options ? param.options.split(',').map(o => o.trim()).filter(o => o) : [];
                }
                
                return paramData;
              })
            };

            if (this.isEdit) {
              // 更新模板
              await updateTemplate(this.currentTemplateId, submitData);
              this.$message.success('模板更新成功');
            } else {
              // 创建模板
              await createTemplate(submitData);
              this.$message.success('模板创建成功');
            }
            
            if (this.isDialog) {
              this.$emit('success');
            } else {
              // 返回列表页
              this.$router.push('/strategy/template');
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
    async handleValidate() {
      // 验证模板有效性
      this.$refs.form.validate(async (valid) => {
        if (valid) {
          this.validating = true;
          try {
            // 准备验证数据
            const validateData = {
              code: this.form.code,
              name: this.form.name,
              description: this.form.description,
              source_code: this.form.source_code || null,
              parameters: this.form.parameters.map(param => {
                const paramData = {
                  name: param.name,
                  label: param.label,
                  param_type: param.param_type,
                  required: param.required,
                  description: param.description || null
                };
                
                // 处理默认值，确保类型正确
                if (param.param_type === 'boolean') {
                  paramData.default_value = Boolean(param.default_value);
                } else if (param.param_type === 'number' || param.param_type === 'slider') {
                  paramData.default_value = Number(param.default_value) || 0;
                } else if (param.param_type === 'dict') {
                  try {
                    paramData.default_value = typeof param.default_value === 'string' 
                      ? JSON.parse(param.default_value) 
                      : param.default_value;
                  } catch (e) {
                    paramData.default_value = {};
                  }
                } else {
                  paramData.default_value = param.default_value;
                }
                
                // 数字和滑块类型需要最小值和最大值
                if (param.param_type === 'number' || param.param_type === 'slider') {
                  paramData.min_value = param.min_value;
                  paramData.max_value = param.max_value;
                }
                
                // 滑块类型需要步长
                if (param.param_type === 'slider') {
                  paramData.step = param.step;
                }
                
                // 下拉选择类型需要选项列表
                if (param.param_type === 'select') {
                  // 将逗号分隔的字符串转换为数组
                  paramData.options = param.options ? param.options.split(',').map(o => o.trim()).filter(o => o) : [];
                }
                
                return paramData;
              })
            };

            const result = await validateTemplate(validateData);
            const data = result.data || result;
            
            // 保存验证结果并显示对话框
            this.validateResult = data;
            this.validateDialogVisible = true;
            
            // 同时显示简要消息
            if (data.valid) {
              this.$message.success('模板验证通过！');
            } else {
              this.$message.error('模板验证失败，请查看详细信息');
            }
          } catch (error) {
            console.error('验证失败:', error);
            const errorMsg = error.response && error.response.data && error.response.data.detail 
              ? error.response.data.detail 
              : error.message || '验证失败';
            this.$message.error(errorMsg);
          } finally {
            this.validating = false;
          }
        } else {
          this.$message.warning('请先填写必填项');
        }
      });
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
      
      // 监听内容变化，同步到 form.source_code
      this.codeEditor.on('change', () => {
        this.form.source_code = this.codeEditor.getValue();
      });
      
      // 设置高度
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
