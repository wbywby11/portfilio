<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">模型模板库</h2>
      <div>
        <el-button type="primary" icon="el-icon-plus" @click="handleCreate">
          新增模板
        </el-button>
      </div>
    </div>

    <div class="page-content">
      <!-- 搜索栏 -->
      <el-form :inline="true" class="search-form">
        <el-form-item>
          <el-input
            v-model="searchKeyword"
            placeholder="请输入模板名称或编码"
            clearable
            @clear="handleSearch"
            @keyup.enter.native="handleSearch"
            style="width: 300px;"
          >
            <el-button slot="append" icon="el-icon-search" @click="handleSearch"></el-button>
          </el-input>
        </el-form-item>
      </el-form>

      <!-- 模板列表 -->
      <div class="template-grid">
        <div class="template-grid-item" v-for="template in filteredTemplateList" :key="template.id">
          <el-card class="template-card" shadow="hover">
            <div slot="header" class="card-header">
              <span class="template-name">{{ template.name }}</span>
            </div>
            
            <div class="card-content">
              <p class="template-desc">{{ template.description || '暂无描述' }}</p>
              
              <el-divider></el-divider>
              
              <div class="template-info">
                <div class="info-item">
                  <span class="label">状态：</span>
                  <el-tag :type="template.is_active ? 'success' : 'info'" size="mini">
                    {{ template.is_active ? '已启用' : '已禁用' }}
                  </el-tag>
                </div>
              </div>

              <div class="params-preview" v-if="template.parameters && template.parameters.length > 0">
                <p class="section-title">参数定义（{{ template.parameters.length }}个）：</p>
                <el-tag
                  v-for="param in template.parameters.slice(0, 3)"
                  :key="param.name"
                  size="mini"
                  style="margin-right: 8px; margin-bottom: 8px;"
                >
                  {{ param.label || param.name }}
                </el-tag>
                <span v-if="template.parameters.length > 3" style="color: #909399; font-size: 12px;">
                  ...
                </span>
              </div>
            </div>

            <div class="card-actions">
              <el-button size="small" type="text" @click="handleView(template)">
                查看详情
              </el-button>
              <el-button size="small" type="text" @click="handleEdit(template)">
                编辑
              </el-button>
              <el-button size="small" type="text" @click="handleUse(template)" style="color: #67c23a;">
                使用模板
              </el-button>
              <el-button size="small" type="text" @click="handleDelete(template)" style="color: #f56c6c;">
                删除
              </el-button>
            </div>
          </el-card>
        </div>
      </div>

      <!-- 空状态 -->
      <el-empty v-if="filteredTemplateList.length === 0" :description="searchKeyword ? '没有找到匹配的模板' : '暂无模板数据'"></el-empty>
    </div>

    <!-- 详情对话框 -->
    <el-dialog
      title="模板详情"
      :visible.sync="detailDialogVisible"
      width="600px"
    >
      <div v-if="currentTemplate">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="模板名称">
            {{ currentTemplate.name }}
          </el-descriptions-item>
          <el-descriptions-item label="模板代码">
            {{ currentTemplate.code }}
          </el-descriptions-item>
          <el-descriptions-item label="描述">
            {{ currentTemplate.description || '暂无' }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="currentTemplate.is_active ? 'success' : 'info'" size="small">
              {{ currentTemplate.is_active ? '已启用' : '已禁用' }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="currentTemplate.parameters && currentTemplate.parameters.length > 0" style="margin-top: 20px;">
          <h4>参数定义</h4>
          <el-table :data="currentTemplate.parameters" border size="small">
            <el-table-column prop="name" label="参数名" width="120"></el-table-column>
            <el-table-column prop="label" label="显示名" width="120"></el-table-column>
            <el-table-column prop="param_type" label="类型" width="80">
              <template slot-scope="scope">
                <el-tag size="mini" :type="getParamTypeTag(scope.row.param_type)">
                  {{ getParamTypeLabel(scope.row.param_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="default_value" label="默认值" width="100">
              <template slot-scope="scope">
                <span v-if="scope.row.param_type === 'boolean'">
                  <el-tag :type="scope.row.default_value ? 'success' : 'info'" size="mini">
                    {{ scope.row.default_value ? '是' : '否' }}
                  </el-tag>
                </span>
                <span v-else-if="scope.row.param_type === 'dict'">
                  <el-popover placement="top" trigger="hover" :content="JSON.stringify(scope.row.default_value)">
                    <el-tag slot="reference" size="mini" type="danger">JSON</el-tag>
                  </el-popover>
                </span>
                <span v-else>
                  {{ scope.row.default_value !== null && scope.row.default_value !== undefined ? scope.row.default_value : '-' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="参数范围" width="150">
              <template slot-scope="scope">
                <span v-if="scope.row.param_type === 'number' || scope.row.param_type === 'slider'">
                  [{{ scope.row.min_value }}, {{ scope.row.max_value }}]
                  <span v-if="scope.row.param_type === 'slider' && scope.row.step">
                    <br>步长: {{ scope.row.step }}
                  </span>
                </span>
                <span v-else-if="scope.row.param_type === 'select' && scope.row.options">
                  {{ Array.isArray(scope.row.options) ? scope.row.options.join(', ') : scope.row.options }}
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="required" label="必填" width="60">
              <template slot-scope="scope">
                <el-tag :type="scope.row.required ? 'danger' : 'info'" size="mini">
                  {{ scope.row.required ? '是' : '否' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="说明" show-overflow-tooltip></el-table-column>
          </el-table>
        </div>

        <div v-if="currentTemplate.source_code" style="margin-top: 20px;">
          <h4>算法源代码</h4>
          <div class="codemirror-wrapper">
            <textarea ref="detailCodeEditor"></textarea>
          </div>
        </div>
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="detailDialogVisible = false">关闭</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';
import CodeMirror from 'codemirror';
import 'codemirror/lib/codemirror.css';
import 'codemirror/theme/monokai.css';
import 'codemirror/mode/python/python';

export default {
  name: 'TemplateList',
  data() {
    return {
      templateList: [],
      searchKeyword: '',  // 搜索关键词
      loading: false,
      detailDialogVisible: false,
      currentTemplate: null,
      detailCodeEditor: null  // CodeMirror 实例
    };
  },
  computed: {
    // 过滤后的模板列表
    filteredTemplateList() {
      if (!this.searchKeyword) {
        return this.templateList;
      }
      const keyword = this.searchKeyword.toLowerCase().trim();
      return this.templateList.filter(template => {
        const name = (template.name || '').toLowerCase();
        const code = (template.code || '').toLowerCase();
        return name.includes(keyword) || code.includes(keyword);
      });
    }
  },
  created() {
    this.fetchData();
  },
  methods: {
    async fetchData() {
      this.loading = true;
      try {
        // 列表加载时不包含源代码，提高性能
        const res = await this.$store.dispatch('strategy/fetchTemplateList');
        this.templateList = res;
      } catch (error) {
        this.$message.error('加载模板列表失败');
      } finally {
        this.loading = false;
      }
    },
    handleSearch() {
      this.fetchData();
    },
    handleCreate() {
      this.$router.push('/strategy/template/add');
    },
    async handleView(template) {
      // 单独获取带有源代码的模板详情
      try {
        const fullTemplate = await this.$store.dispatch('strategy/fetchTemplate', template.code);
        this.currentTemplate = fullTemplate;
        this.detailDialogVisible = true;
        // 初始化代码编辑器
        this.$nextTick(() => {
          if (fullTemplate.source_code && this.$refs.detailCodeEditor) {
            // 清理旧的编辑器
            if (this.detailCodeEditor) {
              this.detailCodeEditor.toTextArea();
            }
            // 创建新的只读编辑器
            this.detailCodeEditor = CodeMirror.fromTextArea(this.$refs.detailCodeEditor, {
              mode: 'python',
              theme: 'monokai',
              lineNumbers: true,
              lineWrapping: true,
              readOnly: true,  // 只读模式
              cursorBlinkRate: -1  // 隐藏光标
            });
            this.detailCodeEditor.setValue(fullTemplate.source_code);
            this.detailCodeEditor.setSize(null, '400px');
          }
        });
      } catch (error) {
        this.$message.error('加载模板详情失败');
      }
    },
    handleEdit(template) {
      // 使用 code 作为路由参数，因为后端接口需要 code 来获取模板
      this.$router.push(`/strategy/template/edit/${template.code}`);
    },
    handleUse(template) {
      // 跳转到策略创建页面，并带上模板ID
      this.$router.push({
        path: '/strategy/model/add',
        query: { templateId: template.id }
      });
    },
    handleDelete(template) {
      this.$confirm(`确定要删除模板 "${template.name}" 吗?`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('strategy/deleteTemplate', template.id);
          this.$message.success('删除成功');
          this.fetchData();
        } catch (error) {
          this.$message.error('删除失败：' + (error.response?.data?.detail || error.message));
        }
      }).catch(() => {});
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-';
    },
    getParamTypeLabel(type) {
      const typeMap = {
        'number': '数字',
        'string': '文本',
        'boolean': '复选框',
        'select': '选择',
        'slider': '滑块',
        'dict': '字典(JSON)'
      };
      return typeMap[type] || type;
    },
    getParamTypeTag(type) {
      const tagMap = {
        'number': '',
        'string': 'info',
        'boolean': 'warning',
        'select': 'success',
        'slider': 'primary',
        'dict': 'danger'
      };
      return tagMap[type] || '';
    }
  },
  beforeDestroy() {
    // 清理 CodeMirror 实例
    if (this.detailCodeEditor) {
      this.detailCodeEditor.toTextArea();
    }
  }
};
</script>

<style scoped>
/* 搜索表单样式 */
.search-form {
  margin-bottom: 20px;
}

/* 使用 CSS Grid 布局实现等高卡片 */
.template-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);  /* 每行 3 个 */
  gap: 20px;  /* 间距 */
  margin-bottom: 20px;
}

.template-grid-item {
  display: flex;  /* 关键：让卡片填满高度 */
}

.template-card {
  width: 100%;  /* 占满宽度 */
  transition: all 0.3s;
  display: flex;
  flex-direction: column;  /* 垂直布局 */
}

/* 让 el-card 内部使用 flex 布局 */
.template-card >>> .el-card__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0;  /* 移除默认 padding */
}

.template-card:hover {
  transform: translateY(-5px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 56px;  /* 固定最小高度 */
}

.template-name {
  font-size: 16px;
  font-weight: bold;
  color: #303133;
  /* 限制名称最多两行 */
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
  max-height: 2.8em;
  word-break: break-word;  /* 允许换行 */
}

.card-content {
  flex: 1;  /* 关键：自动填充剩余空间 */
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.template-desc {
  color: #606266;
  line-height: 1.6;
  margin-bottom: 15px;
  /* 限制描述固定三行 */
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  text-overflow: ellipsis;
  height: 4.8em;  /* 固定高度：3行 */
  word-break: break-word;  /* 允许换行 */
}

.template-info {
  margin: 15px 0;
  flex-shrink: 0;  /* 不被压缩 */
}

.info-item {
  margin-bottom: 8px;
  font-size: 13px;
  height: 22px;  /* 固定行高 */
  line-height: 22px;
  /* 限制单行显示 */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.info-item .label {
  color: #909399;
}

.info-item .value {
  color: #606266;
}

.params-preview {
  margin-top: auto;  /* 关键：推到底部 */
  padding-top: 10px;
  min-height: 60px;  /* 固定最小高度 */
  flex-shrink: 0;  /* 不被压缩 */
}

.section-title {
  font-size: 13px;
  font-weight: bold;
  color: #606266;
  margin-bottom: 8px;
}

.card-actions {
  display: flex;
  justify-content: space-around;
  border-top: 1px solid #ebeef5;
  padding: 12px;
  height: 48px;  /* 固定高度 */
  flex-shrink: 0;  /* 不被压缩 */
}

/* 响应式布局 */
@media (max-width: 1400px) {
  .template-grid {
    grid-template-columns: repeat(2, 1fr);  /* 中屏每行 2 个 */
  }
}

@media (max-width: 768px) {
  .template-grid {
    grid-template-columns: 1fr;  /* 小屏每行 1 个 */
  }
}

/* CodeMirror 编辑器样式 */
.codemirror-wrapper {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
  margin-top: 10px;
}

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

/* 只读模式样式 */
.codemirror-wrapper >>> .CodeMirror-cursor {
  display: none !important;
}
</style>
