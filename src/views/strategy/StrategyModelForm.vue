<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑策略' : '新建策略' }}</h2>
    </div>

    <div class="page-content">
      <el-form
        ref="form"
        :model="form"
        :rules="rules"
        label-width="120px"
        class="strategy-form"
      >
        <el-card shadow="never" class="form-card">
          <div slot="header" class="card-header">
            <span>基本信息</span>
          </div>

          <el-form-item label="策略名称" prop="name">
            <el-input
              v-model="form.name"
              placeholder="请输入策略名称"
              maxlength="50"
              show-word-limit
            ></el-input>
          </el-form-item>

          <el-form-item label="策略描述" prop="description">
            <el-input
              type="textarea"
              v-model="form.description"
              :rows="3"
              placeholder="请输入策略描述（可选）"
              maxlength="200"
              show-word-limit
            ></el-input>
          </el-form-item>
        </el-card>

        <el-card shadow="never" class="form-card">
          <div slot="header" class="card-header">
            <span>策略配置</span>
          </div>

          <el-form-item label="算法模板" prop="template_code">
            <el-select
              v-model="form.template_code"
              placeholder="请选择算法模板"
              @change="handleTemplateChange"
              style="width: 100%;"
            >
              <el-option
                v-for="tpl in templateList"
                :key="tpl.code"
                :label="`${tpl.code} - ${tpl.name}`"
                :value="tpl.code"
              >
                <span style="float: left">{{ tpl.code }} - {{ tpl.name }}</span>
                <span style="float: right; color: #8492a6; font-size: 13px">{{ tpl.description }}</span>
              </el-option>
            </el-select>
          </el-form-item>

          <el-form-item label="选择资产" prop="asset_codes">
            <el-select
              v-model="form.asset_codes"
              multiple
              filterable
              placeholder="请选择资产（可多选）"
              style="width: 100%;"
            >
              <el-option
                v-for="asset in assetOptions"
                :key="asset.code"
                :label="`${asset.code} - ${asset.name}`"
                :value="asset.code"
              ></el-option>
            </el-select>
            <div v-if="form.asset_codes.length > 0" style="margin-top: 10px;">
              <el-tag
                v-for="code in form.asset_codes"
                :key="code"
                closable
                @close="removeAsset(code)"
                style="margin-right: 8px; margin-bottom: 8px;"
              >
                {{ getAssetLabel(code) }}
              </el-tag>
            </div>
          </el-form-item>

          <el-form-item label="调仓频率" prop="rebalance_frequency">
            <el-select v-model="form.rebalance_frequency" placeholder="请选择调仓频率">
              <el-option label="日度" value="日"></el-option>
              <el-option label="周度" value="周"></el-option>
              <el-option label="月度" value="月"></el-option>
              <el-option label="季度" value="季"></el-option>
              <el-option label="年度" value="年"></el-option>
            </el-select>
          </el-form-item>
        </el-card>

        <el-card shadow="never" class="form-card" v-if="currentTemplate">
          <div slot="header" class="card-header">
            <span>模型参数</span>
            <el-button type="text" size="small" @click="resetParameters">重置为默认值</el-button>
          </div>

          <el-form-item
            v-for="param in currentTemplate.parameters"
            :key="param.name"
            :label="param.label || param.name"
          >
            <!-- 数字类型 -->
            <el-input-number
              v-if="param.param_type === 'number'"
              v-model="form.parameters[param.name]"
              :min="param.min_value !== null && param.min_value !== undefined ? param.min_value : undefined"
              :max="param.max_value !== null && param.max_value !== undefined ? param.max_value : undefined"
              :step="param.step || 0.01"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
            
            <!-- 滑块类型 -->
            <div v-else-if="param.param_type === 'slider'" style="display: flex; align-items: center;">
              <el-slider
                v-model="form.parameters[param.name]"
                :min="param.min_value !== null && param.min_value !== undefined ? param.min_value : 0"
                :max="param.max_value !== null && param.max_value !== undefined ? param.max_value : 100"
                :step="param.step || 1"
                style="width: 200px; margin-right: 15px;"
                show-input
              ></el-slider>
            </div>
            
            <!-- 下拉选择类型 -->
            <el-select
              v-else-if="param.param_type === 'select'"
              v-model="form.parameters[param.name]"
              placeholder="请选择"
              style="width: 200px;"
            >
              <el-option
                v-for="option in getParamOptions(param)"
                :key="option"
                :label="option"
                :value="option"
              ></el-option>
            </el-select>
            
            <!-- 复选框类型 -->
            <el-switch
              v-else-if="param.param_type === 'boolean'"
              v-model="form.parameters[param.name]"
            ></el-switch>
            
            <!-- 文本类型 -->
            <el-input
              v-else-if="param.param_type === 'string'"
              v-model="form.parameters[param.name]"
              placeholder="请输入"
              style="width: 200px;"
            ></el-input>
            
            <!-- 字典类型 -->
            <el-input
              v-else-if="param.param_type === 'dict'"
              type="textarea"
              v-model="form.parameters[param.name]"
              :rows="3"
              placeholder='请输入JSON字符串，如：{"key": "value"}'
              style="width: 100%; max-width: 500px;"
            ></el-input>
            
            <!-- 默认使用数字输入框（向下兼容） -->
            <el-input-number
              v-else
              v-model="form.parameters[param.name]"
              :min="param.min_value !== null && param.min_value !== undefined ? param.min_value : undefined"
              :max="param.max_value !== null && param.max_value !== undefined ? param.max_value : undefined"
              :step="param.step || 0.01"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
            
            <span style="margin-left: 10px; color: #909399; font-size: 13px;">
              {{ param.description || '' }}
            </span>
          </el-form-item>
        </el-card>

        <el-form-item>
          <el-button type="primary" @click="handleSubmit" :loading="submitting">
            {{ submitting ? '保存中...' : '保存策略' }}
          </el-button>
          <el-button @click="handleCancel">取消</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';

export default {
  name: 'StrategyModelForm',
  data() {
    return {
      isEdit: false,
      currentModelId: null,
      form: {
        name: '',
        description: '',
        template_code: '',
        asset_codes: [],
        parameters: {},
        rebalance_frequency: '月'
      },
      assetOptions: [],
      submitting: false,
      rules: {
        name: [
          { required: true, message: '请输入策略名称', trigger: 'blur' }
        ],
        template_code: [
          { required: true, message: '请选择算法模板', trigger: 'change' }
        ],
        asset_codes: [
          { required: true, message: '请选择资产', trigger: 'change' }
        ],
        rebalance_frequency: [
          { required: true, message: '请选择调仓频率', trigger: 'change' }
        ]
      }
    };
  },
  computed: {
    ...mapState('strategy', ['templateList']),
    currentTemplate() {
      if (!this.form.template_code) return null;
      return this.templateList.find(t => t.code === this.form.template_code);
    }
  },
  created() {
    this.isEdit = !!this.$route.params.id;
    if (this.isEdit) {
      this.currentModelId = this.$route.params.id;
      this.loadModel();
    }
    this.loadInitialData();
  },
  methods: {
    async loadInitialData() {
      try {
        // 加载模板列表
        await this.$store.dispatch('strategy/fetchTemplateList');
        
        // 加载资产选项
        const res = await this.$store.dispatch('asset/fetchAssetOptions');
        this.assetOptions = res;
      } catch (error) {
        console.error('加载数据失败:', error);
        this.$message.error('加载数据失败');
      }
    },
    async loadModel() {
      try {
        const model = await this.$store.dispatch('strategy/fetchStrategyModel', this.currentModelId);
        
        // 处理参数：如果是 dict 类型且是对象，转换为 JSON 字符串显示
        const parameters = { ...(model.parameters || {}) };
        if (model.template_code) {
          const template = this.templateList.find(t => t.code === model.template_code);
          if (template && template.parameters) {
            template.parameters.forEach(param => {
              if (param.param_type === 'dict' && typeof parameters[param.name] === 'object') {
                parameters[param.name] = JSON.stringify(parameters[param.name], null, 2);
              }
            });
          }
        }

        this.form = {
          name: model.name,
          description: model.description || '',
          template_code: model.template_code,
          asset_codes: model.asset_codes || [],
          parameters: parameters,
          rebalance_frequency: model.rebalance_frequency || '月'
        };
      } catch (error) {
        this.$message.error('加载策略数据失败');
        this.$router.back();
      }
    },
    handleTemplateChange(templateCode) {
      const template = this.templateList.find(t => t.code === templateCode);
      if (template && template.parameters) {
        // 初始化参数默认值
        const parameters = {};
        template.parameters.forEach(param => {
          if (param.param_type === 'dict') {
            parameters[param.name] = param.default !== undefined 
              ? (typeof param.default === 'object' ? JSON.stringify(param.default, null, 2) : param.default)
              : '{}';
          } else {
            parameters[param.name] = param.default;
          }
        });
        this.form.parameters = parameters;
      }
    },
    removeAsset(code) {
      const index = this.form.asset_codes.indexOf(code);
      if (index > -1) {
        this.form.asset_codes.splice(index, 1);
      }
    },
    getAssetLabel(code) {
      const asset = this.assetOptions.find(a => a.code === code);
      return asset ? `${asset.code} ${asset.name}` : code;
    },
    // 获取参数的选项列表
    getParamOptions(param) {
      if (!param.options) {
        return [];
      }
      // 如果options是数组，直接返回
      if (Array.isArray(param.options)) {
        return param.options;
      }
      // 如果options是字符串，按逗号分割
      if (typeof param.options === 'string') {
        return param.options.split(',').map(o => o.trim()).filter(o => o);
      }
      return [];
    },

    resetParameters() {
      if (this.currentTemplate && this.currentTemplate.parameters) {
        const parameters = {};
        this.currentTemplate.parameters.forEach(param => {
          parameters[param.name] = param.default;
        });
        this.form.parameters = parameters;
        this.$message.success('参数已重置为默认值');
      }
    },
    handleSubmit() {
      this.$refs.form.validate(async (valid) => {
        if (!valid) {
          this.$message.warning('请完善必填项');
          return;
        }

        this.submitting = true;
        try {
          // 处理参数：如果是 dict 类型，尝试从 JSON 字符串解析为对象
          const submitParameters = { ...this.form.parameters };
          if (this.currentTemplate && this.currentTemplate.parameters) {
            this.currentTemplate.parameters.forEach(param => {
              if (param.param_type === 'dict' && typeof submitParameters[param.name] === 'string') {
                try {
                  submitParameters[param.name] = JSON.parse(submitParameters[param.name]);
                } catch (e) {
                  console.error(`解析参数 ${param.name} 失败:`, e);
                  // 如果解析失败，保留原字符串或抛出错误
                  throw new Error(`参数 "${param.label || param.name}" 不是有效的 JSON 格式`);
                }
              }
            });
          }

          const modelData = {
            name: this.form.name,
            description: this.form.description,
            template_code: this.form.template_code,
            asset_codes: this.form.asset_codes,
            parameters: submitParameters,
            rebalance_frequency: this.form.rebalance_frequency
          };

          if (this.isEdit) {
            await this.$store.dispatch('strategy/updateStrategyModel', {
              modelId: this.currentModelId,
              data: modelData
            });
            this.$message.success('更新成功');
          } else {
            await this.$store.dispatch('strategy/createStrategyModel', modelData);
            this.$message.success('创建成功，策略已保存为草稿');
          }

          this.$router.push('/strategy/model');
        } catch (error) {
          this.$message.error('保存失败：' + (error.response?.data?.detail || error.message));
        } finally {
          this.submitting = false;
        }
      });
    },
    handleCancel() {
      this.$router.back();
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
  max-width: 900px;
}

.strategy-form {
  background: #fff;
}

.form-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}
</style>