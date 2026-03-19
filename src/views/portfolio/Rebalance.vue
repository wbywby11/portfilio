<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">再平衡设置</h2>
      <div>
        <el-button @click="$router.back()">返回</el-button>
        <el-button type="primary" @click="saveSettings" :loading="saving">
          {{ saving ? '保存中...' : '保存设置' }}
        </el-button>
      </div>
    </div>
    <div v-else style="margin-bottom: 20px; text-align: right;">
        <el-button type="primary" size="small" @click="saveSettings" :loading="saving">
          {{ saving ? '保存中...' : '保存设置' }}
        </el-button>
    </div>

    <div :class="{'page-content': !isDialog}">
      <!-- 基本信息 -->
      <el-alert
        title="提示"
        type="info"
        description="再平衡策略用于自动或半自动地将组合调整回目标权重，可设置多种触发条件"
        :closable="false"
        style="margin-bottom: 20px;"
      ></el-alert>

      <div class="info-card">
        <div class="info-card-title">组合信息</div>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="组合名称">{{ portfolio.name }}</el-descriptions-item>
          <el-descriptions-item label="当前状态">
            <el-tag :type="portfolio.status === 'active' ? 'success' : 'info'" size="small">
              {{ portfolio.status === 'active' ? '运行中' : '已暂停' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="当前市值">{{ formatNumber(portfolio.totalValue) }} 元</el-descriptions-item>
          <el-descriptions-item label="累计收益率">
            <span :class="getReturnClass(portfolio.totalReturn)">
              {{ formatPercent(portfolio.totalReturn) }}
            </span>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <!-- 触发条件配置 -->
      <div class="info-card">
        <div class="info-card-title">触发条件（可多选）</div>
        
        <el-checkbox-group v-model="settings.triggers">
          <!-- 定期再平衡 -->
          <div class="trigger-item">
            <el-checkbox label="periodic" border>
              <i class="el-icon-time"></i> 定期再平衡
            </el-checkbox>
            
            <el-collapse-transition>
              <div v-if="settings.triggers.includes('periodic')" class="trigger-config">
                <el-form label-width="120px" size="small">
                  <el-form-item label="再平衡频率">
                    <el-select v-model="settings.periodicConfig.frequency" placeholder="请选择">
                      <el-option label="每日" value="daily"></el-option>
                      <el-option label="每周" value="weekly"></el-option>
                      <el-option label="每月" value="monthly"></el-option>
                      <el-option label="每季" value="quarterly"></el-option>
                      <el-option label="每年" value="yearly"></el-option>
                    </el-select>
                    <el-tooltip content="定期再平衡的执行频率，每日表示每个交易日都检查，每月表示每月第一个交易日执行，每季表示每季度第一个交易日执行" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                  </el-form-item>
                  
                  <el-form-item label="执行时间" v-if="settings.periodicConfig.frequency === 'monthly'">
                    <el-input-number
                      v-model="settings.periodicConfig.dayOfMonth"
                      :min="1"
                      :max="28"
                      controls-position="right"
                    ></el-input-number>
                    <el-tooltip content="每月第N个交易日执行再平衡，例如设置为1表示每月第一个交易日执行" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                    <span style="margin-left: 10px; color: #909399;">每月第 N 个交易日</span>
                  </el-form-item>
                  
                  <el-form-item label="执行方式">
                    <el-radio-group v-model="settings.periodicConfig.executionType">
                      <el-radio label="auto">收盘后自动执行</el-radio>
                      <el-radio label="manual">生成建议，手动确认</el-radio>
                    </el-radio-group>
                    <el-tooltip content="自动执行会在满足条件时直接调仓，手动确认会生成调仓建议供您审核后执行，建议首次使用时选择手动确认" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                  </el-form-item>
                  
                  <el-form-item label="生效日期">
                    <el-date-picker
                      v-model="settings.periodicConfig.startDate"
                      type="date"
                      placeholder="选择日期"
                      value-format="yyyy-MM-dd"
                    ></el-date-picker>
                  </el-form-item>
                </el-form>
              </div>
            </el-collapse-transition>
          </div>

          <!-- 阈值触发再平衡 -->
          <div class="trigger-item">
            <el-checkbox label="threshold" border>
              <i class="el-icon-warning"></i> 阈值触发再平衡
            </el-checkbox>
            
            <el-collapse-transition>
              <div v-if="settings.triggers.includes('threshold')" class="trigger-config">
                <el-form label-width="120px" size="small">
                  <el-form-item label="偏离阈值">
                    <el-input-number
                      v-model="settings.thresholdConfig.deviationThreshold"
                      :min="1"
                      :max="50"
                      :step="0.5"
                      :precision="1"
                      controls-position="right"
                    ></el-input-number>
                    <el-tooltip content="权重偏离目标超过此百分比时触发再平衡，例如设置为5%表示当资产权重偏离目标超过5%时自动调仓" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                    <span style="margin-left: 10px; color: #909399;">%（默认：5，范围：1-50，步长：0.5）</span>
                  </el-form-item>
                  
                  <el-form-item label="检查频率">
                    <el-radio-group v-model="settings.thresholdConfig.checkFrequency">
                      <el-radio label="daily">每日收盘后</el-radio>
                      <el-radio label="realtime">实时监控</el-radio>
                    </el-radio-group>
                    <el-tooltip content="每日收盘后检查在收盘后计算权重偏离，实时监控会在交易时间内持续监控，实时监控会增加系统负载" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                  </el-form-item>
                  
                  <el-form-item label="触发方式">
                    <el-radio-group v-model="settings.thresholdConfig.triggerMode">
                      <el-radio label="any">任一资产触发</el-radio>
                      <el-radio label="overall">组合整体触发</el-radio>
                    </el-radio-group>
                    <el-tooltip content="任一资产触发表示只要有一个资产偏离超过阈值就执行再平衡，组合整体触发表示需要组合整体偏离超过阈值才执行" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                  </el-form-item>
                  
                  <el-form-item label="资产范围">
                    <el-radio-group v-model="settings.thresholdConfig.assetScope">
                      <el-radio label="all">全部资产</el-radio>
                      <el-radio label="custom">指定资产</el-radio>
                    </el-radio-group>
                  </el-form-item>
                </el-form>
              </div>
            </el-collapse-transition>
          </div>

          <!-- 模型信号触发 -->
          <div class="trigger-item">
            <el-checkbox label="model" border>
              <i class="el-icon-data-analysis"></i> 模型信号触发
            </el-checkbox>
            
            <el-collapse-transition>
              <div v-if="settings.triggers.includes('model')" class="trigger-config">
                <el-form label-width="120px" size="small">
                  <el-form-item label="关联策略">
                    <el-select v-model="settings.modelConfig.strategyId" placeholder="请选择策略">
                      <el-option
                        v-for="strategy in strategyList"
                        :key="strategy.id"
                        :label="strategy.name"
                        :value="strategy.id"
                      ></el-option>
                    </el-select>
                  </el-form-item>
                  
                  <el-form-item label="跟随方式">
                    <el-radio-group v-model="settings.modelConfig.followMode">
                      <el-radio label="full">完全跟随</el-radio>
                      <el-radio label="partial">部分调整</el-radio>
                    </el-radio-group>
                  </el-form-item>
                  
                  <el-form-item label="更新频率">
                    <el-select v-model="settings.modelConfig.updateFrequency" placeholder="请选择">
                      <el-option label="实时跟随" value="realtime"></el-option>
                      <el-option label="每日更新" value="daily"></el-option>
                      <el-option label="每周更新" value="weekly"></el-option>
                    </el-select>
                  </el-form-item>
                  
                  <el-form-item label="执行延迟">
                    <el-input-number
                      v-model="settings.modelConfig.executionDelay"
                      :min="0"
                      :max="10"
                      :step="1"
                      controls-position="right"
                    ></el-input-number>
                    <span style="margin-left: 10px; color: #909399;">个交易日（默认：0，范围：0-10）</span>
                  </el-form-item>
                </el-form>
              </div>
            </el-collapse-transition>
          </div>

          <!-- 手动触发 -->
          <div class="trigger-item">
            <el-checkbox label="manual" border disabled checked>
              <i class="el-icon-edit"></i> 手动触发（默认可用）
            </el-checkbox>
            <div class="trigger-desc">随时可以手动触发再平衡，无需额外配置</div>
          </div>
        </el-checkbox-group>
      </div>

      <!-- 执行方式配置 -->
      <div class="info-card">
        <div class="info-card-title">执行方式</div>
        
        <el-radio-group v-model="settings.executionMethod">
          <div class="execution-item">
            <el-radio label="full" border>
              <div class="execution-label">
                <strong>完全再平衡</strong>
                <span class="execution-desc">调整至目标权重</span>
              </div>
            </el-radio>
            
            <el-collapse-transition>
              <div v-if="settings.executionMethod === 'full'" class="execution-config">
                <el-form label-width="140px" size="small">
                  <el-form-item label="考虑交易成本">
                    <el-switch v-model="settings.fullConfig.considerCost"></el-switch>
                  </el-form-item>
                  
                  <el-form-item label="最小交易金额">
                    <el-input-number
                      v-model="settings.fullConfig.minTradeAmount"
                      :min="0"
                      :max="100000"
                      :step="100"
                      controls-position="right"
                    ></el-input-number>
                    <el-tooltip content="避免小额交易，当计算出的交易金额小于此值时，将跳过该交易，减少交易成本" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                    <span style="margin-left: 10px; color: #909399;">元（默认：1000，范围：0-100000，步长：100）</span>
                  </el-form-item>
                  
                  <el-form-item label="价格类型">
                    <el-radio-group v-model="settings.fullConfig.priceType">
                      <el-radio label="market">市价</el-radio>
                      <el-radio label="limit">限价</el-radio>
                    </el-radio-group>
                  </el-form-item>
                </el-form>
              </div>
            </el-collapse-transition>
          </div>

          <div class="execution-item">
            <el-radio label="partial" border>
              <div class="execution-label">
                <strong>部分再平衡</strong>
                <span class="execution-desc">平滑调整</span>
              </div>
            </el-radio>
            
            <el-collapse-transition>
              <div v-if="settings.executionMethod === 'partial'" class="execution-config">
                <el-form label-width="140px" size="small">
                  <el-form-item label="调整比例">
                    <el-slider
                      v-model="settings.partialConfig.adjustmentRatio"
                      :min="10"
                      :max="100"
                      :step="10"
                      show-input
                    ></el-slider>
                    <el-tooltip content="每次调整偏离度的百分比，例如设置为50%表示每次只调整一半的偏离度，平滑调整避免大幅波动" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                    <span style="color: #909399;">每次调整偏离度的 {{ settings.partialConfig.adjustmentRatio }}%</span>
                  </el-form-item>
                  
                  <el-form-item label="调整上限">
                    <el-input-number
                      v-model="settings.partialConfig.maxAdjustment"
                      :min="1"
                      :max="50"
                      :step="0.5"
                      :precision="1"
                      controls-position="right"
                    ></el-input-number>
                    <span style="margin-left: 10px; color: #909399;">%（默认：10，范围：1-50，步长：0.5）</span>
                  </el-form-item>
                  
                  <el-form-item label="分批执行">
                    <el-input-number
                      v-model="settings.partialConfig.batchCount"
                      :min="1"
                      :max="10"
                      :step="1"
                      controls-position="right"
                    ></el-input-number>
                    <span style="margin-left: 10px; color: #909399;">次（默认：3，范围：1-10）</span>
                  </el-form-item>
                </el-form>
              </div>
            </el-collapse-transition>
          </div>

          <div class="execution-item">
            <el-radio label="cashflow" border>
              <div class="execution-label">
                <strong>现金流驱动再平衡</strong>
                <span class="execution-desc">利用现金流调整</span>
              </div>
            </el-radio>
            
            <el-collapse-transition>
              <div v-if="settings.executionMethod === 'cashflow'" class="execution-config">
                <el-form label-width="140px" size="small">
                  <el-form-item label="调整方式">
                    <el-checkbox-group v-model="settings.cashflowConfig.modes">
                      <el-checkbox label="inflow">使用现金流入调整</el-checkbox>
                      <el-checkbox label="outflow">使用现金流出调整</el-checkbox>
                    </el-checkbox-group>
                  </el-form-item>
                  
                  <el-form-item label="现金不足时">
                    <el-radio-group v-model="settings.cashflowConfig.insufficientAction">
                      <el-radio label="pause">暂停调整</el-radio>
                      <el-radio label="partial">部分调整</el-radio>
                    </el-radio-group>
                  </el-form-item>
                </el-form>
              </div>
            </el-collapse-transition>
          </div>
        </el-radio-group>
      </div>

      <!-- 高级设置 -->
      <div class="info-card">
        <div class="info-card-title">高级设置</div>
        
        <el-form label-width="140px" size="small">
          <el-divider content-position="left">交易约束</el-divider>
          
          <el-form-item label="最小交易单位">
            <el-radio-group v-model="settings.advanced.minTradeUnit">
              <el-radio label="lot">按手</el-radio>
              <el-radio label="share">按股</el-radio>
            </el-radio-group>
          </el-form-item>
          
          <el-form-item label="交易时间限制">
            <el-checkbox-group v-model="settings.advanced.tradeTimeRestrictions">
                <el-checkbox label="avoidOpen">避开开盘时段</el-checkbox>
              <el-checkbox label="avoidClose">避开收盘时段</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          
          <el-form-item label="价格冲击考虑">
            <el-switch v-model="settings.advanced.considerPriceImpact"></el-switch>
            <span style="margin-left: 10px; color: #909399;">大额交易的价格影响</span>
          </el-form-item>
          
          <el-divider content-position="left">审批流程</el-divider>
          
          <el-form-item label="需要审批">
            <el-switch v-model="settings.advanced.requireApproval"></el-switch>
          </el-form-item>
          
          <el-form-item label="审批人" v-if="settings.advanced.requireApproval">
            <el-select v-model="settings.advanced.approver" placeholder="请选择审批人">
              <el-option label="投资经理 - 张三" value="manager1"></el-option>
              <el-option label="投资经理 - 李四" value="manager2"></el-option>
            </el-select>
          </el-form-item>
          
          <el-form-item label="审批时限" v-if="settings.advanced.requireApproval">
            <el-input-number
              v-model="settings.advanced.approvalTimeLimit"
              :min="1"
              :max="72"
              :step="1"
              controls-position="right"
            ></el-input-number>
            <span style="margin-left: 10px; color: #909399;">小时（默认：24，范围：1-72）</span>
          </el-form-item>
          
          <el-divider content-position="left">通知设置</el-divider>
          
          <el-form-item label="再平衡前通知">
            <el-checkbox-group v-model="settings.advanced.beforeNotifications">
              <el-checkbox label="email">邮件</el-checkbox>
              <el-checkbox label="message">站内信</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          
          <el-form-item label="执行结果通知">
            <el-checkbox-group v-model="settings.advanced.afterNotifications">
              <el-checkbox label="email">邮件</el-checkbox>
              <el-checkbox label="message">站内信</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          
          <el-form-item label="异常报警">
            <el-switch v-model="settings.advanced.errorAlert"></el-switch>
            <span style="margin-left: 10px; color: #909399;">执行失败时提醒</span>
          </el-form-item>
        </el-form>
      </div>

      <!-- 再平衡计划预览 -->
      <div class="info-card" v-if="settings.triggers.length > 0">
        <div class="info-card-title">再平衡计划预览</div>
        <el-timeline>
          <el-timeline-item
            v-for="(plan, index) in rebalancePlan"
            :key="index"
            :icon="plan.icon"
            :type="plan.type"
            :timestamp="plan.time"
            placement="top"
          >
            <h4>{{ plan.title }}</h4>
            <p>{{ plan.description }}</p>
          </el-timeline-item>
        </el-timeline>
      </div>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';

export default {
  name: 'Rebalance',
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    id: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      portfolioId: null,
      portfolio: {},
      settings: {
        triggers: ['manual'],
        periodicConfig: {
          frequency: 'monthly',
          dayOfMonth: 1,
          executionType: 'manual',
          startDate: new Date().toISOString().split('T')[0]
        },
        thresholdConfig: {
          deviationThreshold: 5,
          checkFrequency: 'daily',
          triggerMode: 'any',
          assetScope: 'all'
        },
        modelConfig: {
          strategyId: '',
          followMode: 'full',
          updateFrequency: 'daily',
          executionDelay: 0
        },
        executionMethod: 'full',
        fullConfig: {
          considerCost: true,
          minTradeAmount: 1000,
          priceType: 'market'
        },
        partialConfig: {
          adjustmentRatio: 50,
          maxAdjustment: 10,
          batchCount: 3
        },
        cashflowConfig: {
          modes: ['inflow'],
          insufficientAction: 'pause'
        },
        advanced: {
          minTradeUnit: 'lot',
          tradeTimeRestrictions: [],
          considerPriceImpact: false,
          requireApproval: false,
          approver: '',
          approvalTimeLimit: 24,
          beforeNotifications: ['message'],
          afterNotifications: ['message'],
          errorAlert: true
        }
      },
      saving: false
    };
  },
  computed: {
    ...mapState('strategy', ['strategyList']),
    rebalancePlan() {
      const plan = [];
      
      if (this.settings.triggers.includes('periodic')) {
        const freq = this.getFrequencyLabel(this.settings.periodicConfig.frequency);
        plan.push({
          icon: 'el-icon-time',
          type: 'primary',
          time: `生效日期: ${this.settings.periodicConfig.startDate}`,
          title: '定期再平衡',
          description: `${freq}执行再平衡，${this.settings.periodicConfig.executionType === 'auto' ? '自动执行' : '需手动确认'}`
        });
      }
      
      if (this.settings.triggers.includes('threshold')) {
        plan.push({
          icon: 'el-icon-warning',
          type: 'warning',
          time: `监控频率: ${this.settings.thresholdConfig.checkFrequency === 'daily' ? '每日' : '实时'}`,
          title: '阈值触发再平衡',
          description: `权重偏离超过 ${this.settings.thresholdConfig.deviationThreshold}% 时触发`
        });
      }
      
      if (this.settings.triggers.includes('model')) {
        const strategy = this.strategyList.find(s => s.id === this.settings.modelConfig.strategyId);
        plan.push({
          icon: 'el-icon-data-analysis',
          type: 'success',
          time: `更新频率: ${this.getFrequencyLabel(this.settings.modelConfig.updateFrequency)}`,
          title: '模型信号触发',
          description: `跟随策略: ${strategy ? strategy.name : '未选择'}，${this.settings.modelConfig.followMode === 'full' ? '完全跟随' : '部分调整'}`
        });
      }
      
      return plan;
    }
  },
  created() {
    this.portfolioId = this.isDialog ? this.id : this.$route.params.id;
    this.loadPortfolio();
  },
  watch: {
    id(newVal) {
      if (this.isDialog && newVal) {
        this.portfolioId = newVal;
        this.loadPortfolio();
      }
    }
  },
  methods: {
    loadPortfolio() {
      this.portfolio = this.$store.getters['portfolio/getPortfolioById'](this.portfolioId) || {};
      
      // 加载已保存的再平衡设置
      if (this.portfolio.rebalanceSettings) {
        this.settings = { ...this.settings, ...this.portfolio.rebalanceSettings };
      }
    },
    async saveSettings() {
      if (this.settings.triggers.length === 0 || !this.settings.triggers.some(t => t !== 'manual')) {
        this.$message.warning('请至少选择一种自动触发条件');
        return;
      }
      
      this.saving = true;
      try {
        // 保存设置到组合
        await this.$store.dispatch('portfolio/updatePortfolio', {
          ...this.portfolio,
          rebalanceSettings: this.settings
        });
        
        this.$message.success('再平衡设置已保存');
        if (this.isDialog) {
          this.$emit('success');
        } else {
          setTimeout(() => {
            this.$router.back();
          }, 1000);
        }
      } catch (error) {
        this.$message.error('保存失败：' + error.message);
      } finally {
        this.saving = false;
      }
    },
    formatNumber(num) {
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num || 0);
    },
    formatPercent(num) {
      return ((num || 0) * 100).toFixed(2) + '%';
    },
    getReturnClass(ret) {
      if (ret > 0) return 'number-positive';
      if (ret < 0) return 'number-negative';
      return 'number-neutral';
    },
    getFrequencyLabel(freq) {
      const map = {
        daily: '每日',
        weekly: '每周',
        monthly: '每月',
        quarterly: '每季',
        yearly: '每年',
        realtime: '实时'
      };
      return map[freq] || freq;
    }
  }
};
</script>

<style scoped>
.trigger-item,
.execution-item {
  margin-bottom: 20px;
}

.trigger-item >>> .el-checkbox.is-bordered,
.execution-item >>> .el-radio.is-bordered {
  width: 100%;
  padding: 15px 20px;
  height: auto;
}

.trigger-config,
.execution-config {
  margin-top: 15px;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 4px;
}

.trigger-desc {
  margin-top: 10px;
  padding-left: 30px;
  color: #909399;
  font-size: 13px;
}

.execution-label {
  display: flex;
  flex-direction: column;
}

.execution-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
