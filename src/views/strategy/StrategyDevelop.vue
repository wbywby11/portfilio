<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">策略开发</h2>
    </div>

    <div class="page-content">
      <el-row :gutter="20">
        <!-- 左侧：资产选择 -->
        <el-col :span="6">
          <div class="panel">
            <div class="panel-title">选择资产</div>
            <el-input
              placeholder="搜索资产代码/名称"
              v-model="assetSearch"
              size="small"
              clearable
              prefix-icon="el-icon-search"
              style="margin-bottom: 10px;"
            ></el-input>
            
            <el-tree
              :data="assetTree"
              :props="{ label: 'label', children: 'children' }"
              show-checkbox
              node-key="code"
              @check="handleAssetCheck"
            ></el-tree>

            <div style="margin-top: 15px;">
              <el-tag
                v-for="asset in selectedAssets"
                :key="asset.asset_code"
                closable
                @close="removeAsset(asset)"
                style="margin: 5px;"
              >
                {{ asset.asset_name }}
              </el-tag>
            </div>
          </div>
        </el-col>

        <!-- 中间：参数配置 -->
        <el-col :span="12">
          <div class="panel">
            <div class="panel-title">参数配置</div>
            
            <el-form :model="strategyForm" label-width="120px">
              <el-form-item label="策略名称">
                <el-input v-model="strategyForm.name" placeholder="请输入策略名称"></el-input>
              </el-form-item>

              <el-form-item label="算法模型">
                <el-select v-model="strategyForm.templateId" placeholder="请选择算法模型" @change="handleTemplateChange">
                  <el-option
                    v-for="tpl in templateList"
                    :key="tpl.id"
                    :label="tpl.name"
                    :value="tpl.id"
                  ></el-option>
                </el-select>
              </el-form-item>

              <el-divider>模型参数</el-divider>

              <div v-if="currentTemplate">
                <el-form-item
                  v-for="param in currentTemplate.parameters"
                  :key="param.name"
                  :label="param.label"
                >
                  <el-input-number
                    v-model="strategyForm.parameters[param.name]"
                    :min="param.min"
                    :max="param.max"
                    :step="param.step || 0.01"
                    :precision="4"
                  ></el-input-number>
                </el-form-item>
              </div>

              <el-form-item>
                <el-button type="primary" @click="calculateStrategy" :loading="calculating">
                  {{ calculating ? '计算中...' : '运行计算' }}
                </el-button>
                <el-button @click="resetForm">重置</el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-col>

        <!-- 右侧：结果预览 -->
        <el-col :span="6">
          <div class="panel">
            <div class="panel-title">计算结果</div>
            
            <div v-if="calculationResult">
              <div class="result-item">
                <span class="result-label">预期收益率：</span>
                <span class="result-value">{{ formatPercent(calculationResult.expectedReturn) }}</span>
              </div>
              <div class="result-item">
                <span class="result-label">预期风险：</span>
                <span class="result-value">{{ formatPercent(calculationResult.expectedRisk) }}</span>
              </div>
              <div class="result-item">
                <span class="result-label">夏普比率：</span>
                <span class="result-value">{{ calculationResult.sharpeRatio.toFixed(4) }}</span>
              </div>

              <el-divider>权重分配</el-divider>
              
              <div class="weight-list">
                <div v-for="(weight, code) in calculationResult.weights" :key="code" class="weight-item">
                  <span>{{ code }}</span>
                  <el-progress
                    :percentage="parseFloat(weight) * 100"
                    :format="() => formatPercent(weight)"
                  ></el-progress>
                </div>
              </div>

              <el-button type="success" size="small" @click="saveStrategy" style="width: 100%; margin-top: 20px;">
                保存策略
              </el-button>
            </div>
            
            <el-empty v-else description="请先运行计算" :image-size="100"></el-empty>
          </div>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';

export default {
  name: 'StrategyDevelop',
  data() {
    return {
      assetSearch: '',
      selectedAssets: [],
      strategyForm: {
        name: '',
        templateId: '',
        parameters: {}
      },
      calculating: false,
      calculationResult: null
    };
  },
  computed: {
    ...mapState('strategy', ['templateList']),
    ...mapState('asset', ['assetList', 'assetCategories']),
    assetTree() {
      return this.assetCategories.map(cat => ({
        label: cat.label,
        code: cat.value,
        children: this.assetList
          .filter(a => a.asset_type === cat.value)
          .map(a => ({
            label: `${a.asset_code} ${a.asset_name}`,
            code: a.asset_code,
            name: a.asset_name,
            category: a.asset_type,
            ...a
          }))
      }));
    },
    currentTemplate() {
      return this.templateList.find(t => t.id === this.strategyForm.templateId);
    }
  },
  created() {
    // 初始化加载资产列表和模板列表
    this.loadInitialData();
    
    if (this.$route.query.templateId) {
      this.strategyForm.templateId = this.$route.query.templateId;
      this.handleTemplateChange(this.strategyForm.templateId);
    }
  },
  methods: {
    async loadInitialData() {
      try {
        // 加载资产列表（不分页，获取所有资产）
        await this.$store.dispatch('asset/fetchAssetList', {
          pageSize: 1000
        });
        
        // 加载模板列表
        await this.$store.dispatch('strategy/fetchTemplateList');
      } catch (error) {
        console.error('加载数据失败:', error);
        this.$message.error('加载数据失败');
      }
    },
    handleAssetCheck(data, checked) {
      // 过滤出只包含资产节点（有 asset_code 字段且无 children 的节点）
      this.selectedAssets = checked.checkedNodes.filter(n => n.asset_code && !n.children);
      console.log('已选择资产:', this.selectedAssets);
    },
    removeAsset(asset) {
      this.selectedAssets = this.selectedAssets.filter(a => a.asset_code !== asset.asset_code);
    },
    handleTemplateChange(templateId) {
      const template = this.templateList.find(t => t.id === templateId);
      if (template) {
        this.strategyForm.parameters = {};
        template.parameters.forEach(p => {
          this.strategyForm.parameters[p.name] = p.default;
        });
      }
    },
    async calculateStrategy() {
      if (this.selectedAssets.length === 0) {
        this.$message.warning('请先选择资产');
        return;
      }
      if (!this.strategyForm.templateId) {
        this.$message.warning('请选择算法模型');
        return;
      }

      this.calculating = true;
      try {
        this.calculationResult = await this.$store.dispatch('strategy/calculateStrategy', {
          assets: this.selectedAssets,
          template: this.strategyForm.templateId,
          parameters: this.strategyForm.parameters
        });
        this.$message.success('计算完成');
      } catch (error) {
        this.$message.error('计算失败：' + error.message);
      } finally {
        this.calculating = false;
      }
    },
    async saveStrategy() {
      if (!this.strategyForm.name) {
        this.$message.warning('请输入策略名称');
        return;
      }

      const strategy = {
        ...this.strategyForm,
        assets: this.selectedAssets,
        result: this.calculationResult,
        creator: this.$store.state.user.userInfo.name
      };

      await this.$store.dispatch('strategy/saveStrategy', strategy);
      this.$message.success('策略已保存');
      this.$router.push('/strategy/list');
    },
    resetForm() {
      this.strategyForm = {
        name: '',
        templateId: '',
        parameters: {}
      };
      this.calculationResult = null;
    },
    formatPercent(num) {
      return (parseFloat(num) * 100).toFixed(2) + '%';
    }
  }
};
</script>

<style scoped>
.panel {
  background: #fff;
  border-radius: 4px;
  padding: 20px;
  min-height: 600px;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 15px;
  padding-bottom: 10px;
  border-bottom: 1px solid #eee;
}

.result-item {
  display: flex;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
}

.result-label {
  color: #606266;
  font-size: 14px;
}

.result-value {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.weight-list {
  max-height: 300px;
  overflow-y: auto;
}

.weight-item {
  margin-bottom: 15px;
}

.weight-item span {
  display: block;
  font-size: 13px;
  color: #606266;
  margin-bottom: 5px;
}
</style>
