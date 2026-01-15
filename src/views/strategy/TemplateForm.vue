<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑模板' : '新增模板' }}</h2>
    </div>

    <div class="page-content">
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

        <el-form-item label="适用场景" prop="application_scenario">
          <el-input
            v-model="form.application_scenario"
            type="textarea"
            :rows="2"
            placeholder="请输入适用场景，如：适用于低风险稳健型投资者"
          ></el-input>
        </el-form-item>

        <el-form-item label="算法实现类" prop="algorithm_class">
          <el-input
            v-model="form.algorithm_class"
            placeholder="请输入算法实现类名，如：MeanVarianceOptimizer"
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
                    <el-select v-model="param.param_type" placeholder="请选择" style="width: 100%;">
                      <el-option label="数字" value="number"></el-option>
                      <el-option label="文本" value="string"></el-option>
                      <el-option label="布尔" value="boolean"></el-option>
                      <el-option label="下拉选择" value="select"></el-option>
                      <el-option label="日期" value="date"></el-option>
                      <el-option label="数组" value="array"></el-option>
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="默认值" label-width="80px">
                    <el-input v-model="param.default_value" placeholder="请输入"></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="是否必填" label-width="80px">
                    <el-switch v-model="param.required"></el-switch>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="15" v-if="param.param_type === 'number'">
                <el-col :span="12">
                  <el-form-item label="最小值" label-width="80px">
                    <el-input-number v-model="param.min_value" style="width: 100%;" :controls="false"></el-input-number>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="最大值" label-width="80px">
                    <el-input-number v-model="param.max_value" style="width: 100%;" :controls="false"></el-input-number>
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
          <el-button @click="handleCancel">取消</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script>
import { createTemplate, updateTemplate } from '@/api/strategy';
import CodeMirror from 'codemirror';
import 'codemirror/lib/codemirror.css';
import 'codemirror/theme/monokai.css';
import 'codemirror/mode/python/python';

export default {
  name: 'TemplateForm',
  data() {
    return {
      form: {
        code: '',
        name: '',
        description: '',
        application_scenario: '',
        algorithm_class: '',
        source_code: '',
        parameters: []
      },
      rules: {
        name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
        code: [{ required: true, message: '请输入模板代码', trigger: 'blur' }],
        description: [{ required: true, message: '请输入模板描述', trigger: 'blur' }],
        application_scenario: [{ required: true, message: '请输入适用场景', trigger: 'blur' }],
        algorithm_class: [{ required: true, message: '请输入算法实现类', trigger: 'blur' }]
      },
      submitting: false,
      isEdit: false,
      currentTemplateId: null,
      codeEditor: null  // CodeMirror 实例
    };
  },
  created() {
    // 路由参数是 code（模板代码），不是 id
    if (this.$route.params.id) {
      this.isEdit = true;
      this.loadTemplate();
    }
  },
  methods: {
    async loadTemplate() {
      const templateCode = this.$route.params.id;  // 路由参数名是 id，但实际值是 code
      try {
        // 使用 code 获取模板
        const template = await this.$store.dispatch('strategy/fetchTemplate', templateCode);
        this.currentTemplateId = template.id;  // 保存 id 用于更新
        this.form = {
          code: template.code,
          name: template.name,
          description: template.description || '',
          application_scenario: template.application_scenario || '',
          algorithm_class: template.algorithm_class || '',
          source_code: template.source_code || '',
          parameters: template.parameters || []
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
        default_value: null,
        required: true,
        description: '',
        min_value: null,
        max_value: null,
        options: null
      });
    },
    removeParam(index) {
      this.form.parameters.splice(index, 1);
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
              application_scenario: this.form.application_scenario,
              algorithm_class: this.form.algorithm_class,
              source_code: this.form.source_code || null,
              parameters: this.form.parameters.map(param => ({
                name: param.name,
                label: param.label,
                param_type: param.param_type,
                default_value: param.default_value,
                required: param.required,
                description: param.description || null,
                min_value: param.param_type === 'number' ? param.min_value : null,
                max_value: param.param_type === 'number' ? param.max_value : null,
                options: param.param_type === 'select' ? param.options : null
              }))
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
            
            // 返回列表页
            this.$router.push('/strategy/template');
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
      this.$router.back();
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
