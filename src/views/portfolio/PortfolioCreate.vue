<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">创建组合</h2>
    </div>

    <div class="page-content">
      <el-steps :active="currentStep" finish-status="success" align-center style="margin-bottom: 30px;">
        <el-step title="基本信息"></el-step>
        <el-step title="建仓方式"></el-step>
        <el-step title="确认创建"></el-step>
      </el-steps>

      <!-- 步骤1：基本信息 -->
      <div v-show="currentStep === 0">
        <el-form :model="portfolioForm" :rules="rules" ref="portfolioForm" label-width="120px" style="max-width: 600px;">
          <el-form-item label="组合名称" prop="name">
            <el-input v-model="portfolioForm.name" placeholder="请输入组合名称"></el-input>
          </el-form-item>

          <el-form-item label="初始资金" prop="initialCapital">
            <el-input-number
              v-model="portfolioForm.initialCapital"
              :min="10000"
              :step="10000"
              :precision="2"
            ></el-input-number>
            <span style="margin-left: 10px; color: #909399;">元（最小1万元）</span>
          </el-form-item>

          <el-form-item label="业绩基准">
            <el-select v-model="portfolioForm.benchmarks" multiple placeholder="请选择业绩基准（可多选）">
              <el-option
                v-for="item in benchmarks"
                :key="item.code"
                :label="item.name"
                :value="item.code"
              ></el-option>
            </el-select>
          </el-form-item>

          <el-form-item label="组合描述">
            <el-input
              v-model="portfolioForm.description"
              type="textarea"
              :rows="3"
              placeholder="请输入组合描述（可选）"
            ></el-input>
          </el-form-item>

          <el-form-item>
            <el-button type="primary" @click="nextStep">下一步</el-button>
            <el-button @click="$router.back()">取消</el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- 步骤2：建仓方式 -->
      <div v-show="currentStep === 1" style="max-width: 800px;">
        <el-radio-group v-model="buildType" style="margin-bottom: 20px;">
          <el-radio-button label="manual">手工建仓</el-radio-button>
          <el-radio-button label="strategy">模型关联建仓</el-radio-button>
        </el-radio-group>

        <!-- 手工建仓 -->
        <div v-if="buildType === 'manual'">
          <el-button type="primary" icon="el-icon-plus" @click="addHolding" size="small" style="margin-bottom: 15px;">
            添加持仓
          </el-button>
          
          <el-table :data="portfolioForm.holdings" style="width: 100%;">
            <el-table-column label="资产" width="250">
              <template slot-scope="scope">
                <el-select v-model="scope.row.assetCode" placeholder="选择资产" filterable>
                  <el-option
                    v-for="asset in assetList"
                    :key="asset.code"
                    :label="`${asset.code} ${asset.name}`"
                    :value="asset.code"
                  ></el-option>
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="持仓数量" width="150">
              <template slot-scope="scope">
                <el-input-number v-model="scope.row.quantity" :min="0" :precision="2" controls-position="right">
                </el-input-number>
              </template>
            </el-table-column>
            <el-table-column label="成本价格" width="150">
              <template slot-scope="scope">
                <el-input-number v-model="scope.row.price" :min="0" :precision="4" controls-position="right">
                </el-input-number>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template slot-scope="scope">
                <el-button type="text" @click="removeHolding(scope.$index)" style="color: #f56c6c;">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 模型关联建仓 -->
        <div v-if="buildType === 'strategy'">
          <el-form label-width="120px">
            <el-form-item label="选择策略">
              <el-select v-model="selectedStrategy" placeholder="请选择资产配置策略" @change="handleStrategyChange">
                <el-option
                  v-for="strategy in strategyList"
                  :key="strategy.id"
                  :label="strategy.name"
                  :value="strategy.id"
                ></el-option>
              </el-select>
            </el-form-item>

            <el-form-item label="交易成本率">
              <el-input-number v-model="transactionCost" :min="0" :max="0.1" :step="0.0001" :precision="4">
              </el-input-number>
              <span style="margin-left: 10px; color: #909399;">%</span>
            </el-form-item>

            <div v-if="selectedStrategyData">
              <el-divider>预期持仓明细</el-divider>
              <el-table :data="expectedHoldings" style="width: 100%;">
                <el-table-column prop="code" label="资产代码" width="120"></el-table-column>
                <el-table-column prop="name" label="资产名称" width="150"></el-table-column>
                <el-table-column prop="weight" label="目标权重" width="120" align="right">
                  <template slot-scope="scope">
                    {{ formatPercent(scope.row.weight) }}
                  </template>
                </el-table-column>
                <el-table-column prop="amount" label="投资金额" width="150" align="right">
                  <template slot-scope="scope">
                    {{ formatNumber(scope.row.amount) }}
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-form>
        </div>

        <div style="margin-top: 30px;">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" @click="nextStep">下一步</el-button>
        </div>
      </div>

      <!-- 步骤3：确认创建 -->
      <div v-show="currentStep === 2" style="max-width: 800px;">
        <el-result icon="success" title="组合配置完成" subTitle="请确认以下信息后创建组合">
          <template slot="extra">
            <el-descriptions title="组合信息" :column="2" border>
              <el-descriptions-item label="组合名称">{{ portfolioForm.name }}</el-descriptions-item>
              <el-descriptions-item label="初始资金">{{ formatNumber(portfolioForm.initialCapital) }} 元</el-descriptions-item>
              <el-descriptions-item label="建仓方式">{{ buildType === 'manual' ? '手工建仓' : '模型关联建仓' }}</el-descriptions-item>
              <el-descriptions-item label="持仓数量">{{ getHoldingsCount() }} 个</el-descriptions-item>
            </el-descriptions>

            <div style="margin-top: 30px; text-align: center;">
              <el-button @click="prevStep">上一步</el-button>
              <el-button type="primary" @click="createPortfolio" :loading="submitting">
                {{ submitting ? '创建中...' : '确认创建' }}
              </el-button>
            </div>
          </template>
        </el-result>
      </div>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';

export default {
  name: 'PortfolioCreate',
  data() {
    return {
      currentStep: 0,
      portfolioForm: {
        name: '',
        initialCapital: 100000,
        benchmarks: [],
        description: '',
        holdings: []
      },
      rules: {
        name: [{ required: true, message: '请输入组合名称', trigger: 'blur' }],
        initialCapital: [{ required: true, message: '请输入初始资金', trigger: 'blur' }]
      },
      buildType: 'manual',
      selectedStrategy: '',
      transactionCost: 0.001,
      submitting: false
    };
  },
  computed: {
    ...mapState('portfolio', ['benchmarks']),
    ...mapState('asset', ['assetList']),
    ...mapState('strategy', ['strategyList']),
    selectedStrategyData() {
      return this.strategyList.find(s => s.id === this.selectedStrategy);
    },
    expectedHoldings() {
      if (!this.selectedStrategyData || !this.selectedStrategyData.result) return [];
      
      const weights = this.selectedStrategyData.result.weights;
      const capital = this.portfolioForm.initialCapital;
      
      return this.selectedStrategyData.assets.map(asset => ({
        code: asset.code,
        name: asset.name,
        weight: weights[asset.code],
        amount: capital * parseFloat(weights[asset.code])
      }));
    }
  },
  created() {
    if (this.$route.query.strategyId) {
      this.buildType = 'strategy';
      this.selectedStrategy = this.$route.query.strategyId;
      this.handleStrategyChange(this.selectedStrategy);
    }
  },
  methods: {
    nextStep() {
      if (this.currentStep === 0) {
        this.$refs.portfolioForm.validate((valid) => {
          if (valid) {
            this.currentStep++;
          }
        });
      } else if (this.currentStep === 1) {
        if (this.buildType === 'manual' && this.portfolioForm.holdings.length === 0) {
          this.$message.warning('请至少添加一个持仓');
          return;
        }
        if (this.buildType === 'strategy' && !this.selectedStrategy) {
          this.$message.warning('请选择策略');
          return;
        }
        this.currentStep++;
      }
    },
    prevStep() {
      this.currentStep--;
    },
    addHolding() {
      this.portfolioForm.holdings.push({
        assetCode: '',
        quantity: 0,
        price: 1.0
      });
    },
    removeHolding(index) {
      this.portfolioForm.holdings.splice(index, 1);
    },
    handleStrategyChange(strategyId) {
      const strategy = this.strategyList.find(s => s.id === strategyId);
      if (strategy && strategy.result) {
        // 根据策略生成持仓
        this.portfolioForm.holdings = this.expectedHoldings.map(h => ({
          assetCode: h.code,
          quantity: h.amount,
          price: 1.0
        }));
      }
    },
    async createPortfolio() {
      this.submitting = true;
      try {
        await this.$store.dispatch('portfolio/createPortfolio', {
          ...this.portfolioForm,
          buildType: this.buildType,
          strategyId: this.buildType === 'strategy' ? this.selectedStrategy : null
        });
        this.$message.success('组合创建成功');
        this.$router.push('/portfolio/list');
      } catch (error) {
        this.$message.error('创建失败：' + error.message);
      } finally {
        this.submitting = false;
      }
    },
    getHoldingsCount() {
      if (this.buildType === 'strategy' && this.expectedHoldings.length > 0) {
        return this.expectedHoldings.length;
      }
      return this.portfolioForm.holdings.length;
    },
    formatNumber(num) {
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num || 0);
    },
    formatPercent(num) {
      return (parseFloat(num) * 100).toFixed(2) + '%';
    }
  }
};
</script>
