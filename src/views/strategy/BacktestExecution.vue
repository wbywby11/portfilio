<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">回测执行</h2>
    </div>

    <div class="page-content">
      <el-card shadow="never">
        <div slot="header" class="card-header">
          <span>回测配置</span>
        </div>

        <el-form :model="form" :rules="rules" ref="form" label-width="170px" class="backtest-form" style="max-width: 900px;">
          <!-- 回测模式 -->
          <el-divider content-position="left">回测模式</el-divider>
          <el-form-item label="回测模式">
            <el-radio-group v-model="form.backtest_mode">
              <el-radio-button label="single">单策略回测</el-radio-button>
              <el-radio-button label="multi">多策略对比</el-radio-button>
            </el-radio-group>
            <el-tooltip content="单策略回测：查看单个策略的完整回测结果，包含净值曲线、持仓变化、交易明细等；多策略对比：同时运行2-5个策略，横向对比绩效指标和净值曲线" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>

          <!-- 策略选择 -->
          <el-divider content-position="left">策略选择</el-divider>
          <el-form-item label="选择策略" prop="strategy_ids">
            <!-- 单策略模式 -->
            <el-select
              v-if="form.backtest_mode === 'single'"
              v-model="form.strategy_ids"
              placeholder="请选择策略"
              style="width: 100%;"
              @change="handleStrategyChange"
            >
              <el-option
                v-for="strategy in strategyList"
                :key="strategy.id"
                :label="`${strategy.name} (${strategy.template_code})`"
                :value="strategy.id"
              >
                <span style="float: left">{{ strategy.name }}</span>
                <span style="float: right; color: #8492a6; font-size: 13px">
                  {{ strategy.template_code }}
                  <el-tag
                    :type="getStatusTagType(strategy.status)"
                    size="mini"
                    style="margin-left: 4px;"
                  >
                    {{ strategy.status || '草稿' }}
                  </el-tag>
                </span>
              </el-option>
            </el-select>
            <!-- 多策略模式 - 使用多选框 -->
            <div v-else style="width: 100%;">
              <el-checkbox-group v-model="form.strategy_ids" @change="handleStrategyChange" style="width: 100%;">
                <div style="max-height: 300px; overflow-y: auto; border: 1px solid #DCDFE6; border-radius: 4px; padding: 10px;">
                  <el-checkbox
                    v-for="(strategy, index) in strategyList"
                    :key="strategy.id"
                    :label="strategy.id"
                    style="display: block; margin-bottom: 10px; padding: 8px;"
                    :style="{'border-bottom': index < strategyList.length - 1 ? '1px solid #F0F0F0' : 'none'}"
                  >
                    <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                      <span style="flex: 1; font-weight: 500;">{{ strategy.name }}</span>
                      <span style="color: #8492a6; font-size: 12px; margin-right: 8px;">
                        {{ strategy.template_code }}
                      </span>
                      <el-tag
                        :type="getStatusTagType(strategy.status)"
                        size="mini"
                      >
                        {{ strategy.status || '草稿' }}
                      </el-tag>
                    </div>
                  </el-checkbox>
                </div>
              </el-checkbox-group>
            </div>
            <el-tooltip content="选择要回测的策略模型，多策略对比模式下需要选择2-5个策略" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
            <div v-if="strategyList.length === 0" style="margin-top: 10px;">
              <el-alert
                title="提示"
                type="warning"
                :closable="false"
                show-icon
              >
                暂无可用策略，请先创建策略模型
              </el-alert>
            </div>
            <!-- 多策略模式下显示已选择数量 -->
            <div v-else-if="form.backtest_mode === 'multi'" style="margin-top: 10px;">
              <span v-if="selectedStrategyCount > 0" style="color: #409EFF; font-size: 13px; font-weight: 500;">
                已选择 {{ selectedStrategyCount }} 个策略
                <span v-if="selectedStrategyCount < 2" style="color: #F56C6C; margin-left: 10px;">
                  （至少需要选择2个策略）
                </span>
                <span v-else-if="selectedStrategyCount > 5" style="color: #F56C6C; margin-left: 10px;">
                  （最多只能选择5个策略）
                </span>
              </span>
              <span v-else style="color: #909399; font-size: 13px;">
                共 {{ strategyList.length }} 个策略可选，请选择2-5个策略进行对比
              </span>
            </div>
            <!-- 单策略模式下不显示选择数量 -->
            <div v-else-if="form.backtest_mode === 'single'" style="margin-top: 10px;">
              <span style="color: #909399; font-size: 13px;">
                共 {{ strategyList.length }} 个策略可选（包括草稿和已发布）
              </span>
            </div>
          </el-form-item>

          <!-- 回测参数 -->
          <el-divider content-position="left">回测参数</el-divider>
          
          <!-- 初始资金 -->
          <el-form-item label="初始资金" prop="initial_cash">
            <el-input-number
              v-model="form.initial_cash"
              :min="100000"
              :max="100000000"
              :step="100000"
              style="width: 200px;"
            ></el-input-number>
            <el-tooltip content="回测的初始投资金额，最小10万元，用于计算组合净值和收益" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
            <span style="margin-left: 10px; color: #909399;">元（默认：1000000，范围：100000-100000000，步长：100000）</span>
          </el-form-item>

          <!-- 调仓频率 -->
          <el-form-item v-if="!isManualAllocationStrategy" label="调仓频率" prop="rebalance_freq">
            <el-select v-model="form.rebalance_freq" placeholder="请选择调仓频率" style="width: 200px;">
              <el-option label="每日" value="daily"></el-option>
              <el-option label="每周" value="weekly"></el-option>
              <el-option label="每月" value="monthly"></el-option>
              <el-option label="每季度" value="quarterly"></el-option>
              <el-option label="每年" value="yearly"></el-option>
            </el-select>
            <el-tooltip content="组合权重调整的频率，每日表示每个交易日都调仓，每月表示每月第一个交易日调仓，每季度表示每季度第一个交易日调仓" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>

          <!-- 波动率阈值重置：非主观策略可选；主观策略不设周期性调仓与波动率重置 -->
          <template v-if="!isManualAllocationStrategy">
            <el-divider content-position="left">波动率阈值重置</el-divider>
            <div style="margin-bottom: 12px; color: #909399; font-size: 13px;">
              当组合波动率超过阈值时将按比例缩放权重以控制风险。
            </div>
            <el-form-item label="启用波动率阈值重置">
              <el-switch v-model="form.enable_vol_reset"></el-switch>
              <el-tooltip content="启用后，当组合波动率超过设定阈值时将触发权重重置" placement="top">
                <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
              </el-tooltip>
            </el-form-item>
            <el-form-item v-if="form.enable_vol_reset" label="波动率重置阈值">
              <el-input-number
                v-model="form.vol_reset_threshold"
                :min="0.01"
                :max="0.5"
                :step="0.01"
                :precision="2"
                controls-position="right"
                style="width: 200px;"
              ></el-input-number>
              <span style="margin-left: 10px; color: #909399; font-size: 13px;">（默认 0.06，即 6%）</span>
            </el-form-item>
          </template>
          
          <!-- 显示策略参数信息（risk_budget_target_vol 策略参数不可前台调整，隐藏显示） -->
          <el-form-item v-if="selectedStrategyInfo && selectedStrategyInfo.parameters && !isRiskBudgetTargetVolStrategy" label="策略参数">
            <el-card shadow="never" style="background-color: #f5f7fa;">
              <div slot="header" style="font-size: 14px; font-weight: 500;">
                <span>{{ selectedStrategyInfo.name || '策略参数' }}</span>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">
                  ({{ selectedStrategyInfo.template_name || selectedStrategyInfo.template_code }})
                </span>
              </div>
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item
                  v-for="(value, key) in selectedStrategyInfo.parameters"
                  :key="key"
                  :label="getParameterLabel(key)"
                  :span="1"
                >
                  <template v-if="typeof value === 'object' && value !== null && !Array.isArray(value)">
                    <!-- 字典类型参数，显示为键值对 -->
                    <div v-if="Object.keys(value).length > 0" style="font-size: 12px;">
                      <div v-for="(dictValue, dictKey) in value" :key="dictKey" style="margin-bottom: 4px;">
                        <el-tag size="mini" style="margin-right: 4px;">{{ dictKey }}</el-tag>
                        <span>{{ formatParameterValue(dictValue) }}</span>
                      </div>
                    </div>
                    <span v-else style="color: #909399;">空配置</span>
                  </template>
                  <template v-else>
                    {{ formatParameterValue(value) }}
                  </template>
                </el-descriptions-item>
              </el-descriptions>
            </el-card>
            <el-tooltip content="策略模型配置的参数，这些参数将用于回测计算" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>

          <!-- 单策略下显示动量选择器参数（多策略时使用下方「各策略选择器参数」避免重复） -->
          <el-form-item 
            v-if="form.backtest_mode === 'single' && hasMomentumSelection" 
            label="动量资产选择器参数"
          >
            <el-card shadow="never" style="background-color: #f0f9ff; border: 1px solid #b3d8ff;">
              <div slot="header" style="font-size: 14px; font-weight: 500; color: #409EFF;">
                <i class="el-icon-s-data"></i> 动量资产选择器配置
              </div>
              <el-form :model="form" label-width="170px" style="margin-bottom: 0;">
              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="选择器类型" label-width="170px">
                    <el-select v-model="form.selector_type" placeholder="请选择" style="width: 100%;">
                      <el-option label="动量选择器" value="momentum"></el-option>
                      <el-option label="混合动量选择器" value="hybrid"></el-option>
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="MOM窗口" label-width="170px">
                    <el-input
                      v-model="form.momentum_windows"
                      placeholder="例如：20,60,120,250"
                      style="width: 100%;"
                    ></el-input>
                    <el-tooltip content="MOM 因子计算窗口（交易日），逗号分隔" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="SMOM窗口" label-width="170px">
                    <el-input
                      v-model="form.smom_windows"
                      placeholder="例如：20,60,120,250"
                      style="width: 100%;"
                    ></el-input>
                    <el-tooltip content="SMOM 因子计算窗口（交易日），逗号分隔" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="20" v-if="form.selector_type === 'hybrid'">
                <el-col :span="24">
                  <el-form-item label="MACD短期窗口" label-width="170px">
                    <el-input
                      v-model="form.macd_windows"
                      placeholder="例如：40,80,120,160"
                      style="width: 100%;"
                    ></el-input>
                    <el-tooltip content="双均线动量 MACD 因子计算窗口（交易日），逗号分隔，默认 40/80/120/160" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="20" v-if="form.selector_type === 'hybrid'">
                <el-col :span="24">
                  <el-form-item label="反转因子偏度窗口" label-width="170px">
                    <el-input
                      v-model="form.reversal_windows"
                      placeholder="例如：10,22"
                      style="width: 100%;"
                    ></el-input>
                    <el-tooltip content="反转因子 SKEW 计算窗口（交易日），逗号分隔，默认 10/22" placement="top">
                      <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                    </el-tooltip>
                  </el-form-item>
                </el-col>
              </el-row>
              </el-form>
            </el-card>
            <el-tooltip content="这些参数用于动态选择资产，可以在回测时修改以测试不同配置的效果" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>

          <!-- 多策略模式：显示所有策略的选择器参数 -->
          <el-form-item 
            v-if="form.backtest_mode === 'multi' && selectedStrategiesWithSelection.length > 0" 
            label="各策略选择器参数"
          >
            <el-collapse>
              <el-collapse-item
                v-for="strategy in selectedStrategiesWithSelection"
                :key="strategy.id"
                :title="`${strategy.name} - 动量选择器参数`"
                :name="strategy.id"
              >
                <el-form :model="form" label-width="170px" style="margin-bottom: 0;">
                <el-row :gutter="20">
                  <el-col :span="12">
                    <el-form-item :label="`${strategy.name} - 选择器类型`" label-width="170px">
                      <el-select 
                        v-model="form.multiStrategySelectionParams[strategy.id].selector_type" 
                        placeholder="请选择" 
                        style="width: 100%;"
                      >
                        <el-option label="动量选择器" value="momentum"></el-option>
                        <el-option label="混合动量选择器" value="hybrid"></el-option>
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-row :gutter="20">
                  <el-col :span="12">
                    <el-form-item :label="`${strategy.name} - MOM窗口`" label-width="170px">
                      <el-input
                        v-model="form.multiStrategySelectionParams[strategy.id].momentum_windows"
                        placeholder="例如：20,60,120,250"
                        style="width: 100%;"
                      ></el-input>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item :label="`${strategy.name} - SMOM窗口`" label-width="170px">
                      <el-input
                        v-model="form.multiStrategySelectionParams[strategy.id].smom_windows"
                        placeholder="例如：20,60,120,250"
                        style="width: 100%;"
                      ></el-input>
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-row :gutter="20" v-if="form.multiStrategySelectionParams[strategy.id].selector_type === 'hybrid'">
                  <el-col :span="24">
                    <el-form-item :label="`${strategy.name} - MACD短期窗口`" label-width="170px">
                      <el-input
                        v-model="form.multiStrategySelectionParams[strategy.id].macd_windows"
                        placeholder="例如：40,80,120,160"
                        style="width: 100%;"
                      ></el-input>
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-row :gutter="20" v-if="form.multiStrategySelectionParams[strategy.id].selector_type === 'hybrid'">
                  <el-col :span="24">
                    <el-form-item :label="`${strategy.name} - 反转因子偏度窗口`" label-width="170px">
                      <el-input
                        v-model="form.multiStrategySelectionParams[strategy.id].reversal_windows"
                        placeholder="例如：10,22"
                        style="width: 100%;"
                      ></el-input>
                    </el-form-item>
                  </el-col>
                </el-row>
                </el-form>
              </el-collapse-item>
            </el-collapse>
          </el-form-item>

          <!-- 显示资产池信息 -->
          <el-form-item v-if="selectedStrategyInfo && selectedStrategyInfo.asset_codes && selectedStrategyInfo.asset_codes.length > 0" label="资产池">
            <div style="margin-bottom: 8px;">
              <el-tooltip
                v-for="code in selectedStrategyInfo.asset_codes"
                :key="code"
                :content="selectedStrategyInfo.asset_names && selectedStrategyInfo.asset_names[code] ? `${code} - ${selectedStrategyInfo.asset_names[code]}` : code"
                placement="top"
              >
                <el-tag
                  size="small"
                  style="margin-right: 8px; margin-bottom: 8px; cursor: help;"
                >
                  {{ code }}
                </el-tag>
              </el-tooltip>
            </div>
            <el-alert
              v-if="selectedStrategyInfo.asset_codes.length === 0"
              title="提示"
              type="warning"
              :closable="false"
              show-icon
            >
              该策略未配置资产池，请先编辑策略模型添加资产
            </el-alert>
            <el-tooltip content="资产池来自策略模型配置，如需修改请编辑策略模型。请确保资产库中已配置这些资产并已导入行情数据。" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>

          <!-- 主观配置策略：杠杆倍数限制 + 权重初始化与交互式权重调整 -->
          <template v-if="form.backtest_mode === 'single' && isManualAllocationStrategy">
            <el-form-item label="杠杆倍数限制">
              <el-input-number
                v-model="form.run_max_leverage"
                :min="1"
                :max="10"
                :step="0.5"
                :precision="1"
                placeholder="不填则使用策略模型配置"
                controls-position="right"
                style="width: 160px;"
              ></el-input-number>
              <span style="margin-left: 8px; color: #909399; font-size: 12px;">（如 4 表示 400%，初始化/预设调仓日/步进调仓权重和均不得超过此倍数×100%）</span>
            </el-form-item>
            <el-form-item label="权重初始化（本次回测）">
              <el-card shadow="never" style="background-color: #fafafa; border: 1px solid #e4e7ed;">
                <div slot="header" style="font-size: 14px; font-weight: 500; color: #303133;">
                  <i class="el-icon-s-operation"></i> 权重初始化
                </div>
                <div style="margin-bottom: 12px; color: #606266; font-size: 13px;">
                  主观配置策略必须至少有一个资产的权重大于 0。若模型已配置权重初始化，将自动带出；也可在此修改后仅对本次回测生效。
                  <span v-if="Object.keys(maxWeightDict).length > 0" style="color: #909399;">各资产权重按指数编制规则设上限，悬停输入框可查看上限。</span>
                </div>
                <el-form :model="{}" label-width="80px" style="margin-bottom: 0;">
                  <el-form-item label="资产权重" label-width="80px">
                  <div style="display: flex; flex-wrap: wrap; gap: 12px;">
                    <div
                      v-for="code in (selectedStrategyInfo && selectedStrategyInfo.asset_codes) || []"
                      :key="code"
                      style="display: flex; align-items: center; gap: 4px; min-width: 140px;"
                    >
                      <span style="font-size: 12px; min-width: 120px; overflow: hidden; text-overflow: ellipsis;" :title="(selectedStrategyInfo.asset_names && selectedStrategyInfo.asset_names[code]) ? code + ' - ' + selectedStrategyInfo.asset_names[code] : code">{{ (selectedStrategyInfo.asset_names && selectedStrategyInfo.asset_names[code]) ? code + ' - ' + selectedStrategyInfo.asset_names[code] : code }}</span>
                      <el-tooltip v-if="maxWeightDict[code] != null" :content="'指数编制规则上限 ' + ((maxWeightDict[code] || 0) * 100).toFixed(0) + '%'" placement="top">
                        <span>
                          <el-input-number
                            v-model="form.run_manual_weights[code]"
                            :min="0"
                            :max="maxWeightDict[code] != null ? maxWeightDict[code] : 1"
                            :step="0.05"
                            :precision="4"
                            size="small"
                            controls-position="right"
                            style="width: 90px;"
                          ></el-input-number>
                        </span>
                      </el-tooltip>
                      <el-input-number
                        v-else
                        v-model="form.run_manual_weights[code]"
                        :min="0"
                        :max="1"
                        :step="0.05"
                        :precision="4"
                        size="small"
                        controls-position="right"
                        style="width: 90px;"
                      ></el-input-number>
                    </div>
                  </div>
                  <div v-if="runManualWeightsSum !== null" style="margin-top: 8px; font-size: 12px;" :style="{ color: runManualWeightsSum > runMaxLeverage ? '#F56C6C' : (Math.abs(runManualWeightsSum - 1) < 0.001 ? '#67C23A' : '#E6A23C') }">
                    权重和：{{ (runManualWeightsSum * 100).toFixed(2) }}%
                    <span v-if="runMaxLeverage != null" style="color: #909399;">（不得超过杠杆 {{ (runMaxLeverage * 100).toFixed(0) }}%）</span>
                  </div>
                </el-form-item>
                </el-form>
              </el-card>
            </el-form-item>
            <!-- 主观策略：预设调仓日期与权重（仅在这些日期调仓） -->
            <el-form-item label="预设调仓日期与权重">
              <el-card shadow="never" style="background-color: #f0f9ff; border: 1px solid #b3d8ff;">
                <div slot="header" style="font-size: 14px; font-weight: 500; color: #409EFF;">
                  <i class="el-icon-date"></i> 仅在这些日期调仓
                </div>
                <div style="margin-bottom: 12px; color: #606266; font-size: 13px;">
                  主观策略<strong>不设</strong>周期性调仓与波动率阈值重置，仅在下方预设的日期调仓。若策略模型中已配置调仓日与权重，将自动带出；否则请在此添加。每个调仓日可填预设权重——<strong>回测运行到该日会暂停</strong>，可查看绩效后按预设权重调仓并继续。请至少添加一个调仓日。
                  <span v-if="Object.keys(maxWeightDict).length > 0" style="color: #909399;">各资产权重按指数编制规则设上限，悬停输入框可查看上限。</span>
                </div>
                <el-form :model="form" label-width="80px" style="margin-bottom: 0;">
                <div
                  v-for="(adj, idx) in form.manual_weight_adjustments"
                  :key="idx"
                  style="border: 1px solid #DCDFE6; border-radius: 4px; padding: 12px; margin-bottom: 12px; background: #fff;"
                >
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <span style="font-weight: 500;">调仓日 {{ idx + 1 }}</span>
                    <el-button type="text" size="small" @click="removeManualAdjustment(idx)" style="color: #F56C6C;">删除</el-button>
                  </div>
                  <el-row :gutter="16">
                    <el-col :span="8">
                      <el-form-item label="日期" label-width="80px">
                        <el-date-picker
                          v-model="adj.date"
                          type="date"
                          placeholder="选择调仓日期（仅工作日）"
                          value-format="yyyy-MM-dd"
                          :picker-options="rebalanceDatePickerOptions"
                          style="width: 100%;"
                          @change="$refs.form && $refs.form.clearValidate()"
                        ></el-date-picker>
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="是否归一化" label-width="90px">
                        <el-switch v-model="adj.auto_normalize"></el-switch>
                        <el-tooltip content="可选。开启则将该日权重归一化至 100%；关闭则按填写值使用。" placement="top">
                          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
                        </el-tooltip>
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-form-item label="资产权重" label-width="80px">
                    <div style="display: flex; flex-wrap: wrap; gap: 12px;">
                      <div
                        v-for="code in (selectedStrategyInfo && selectedStrategyInfo.asset_codes) || []"
                        :key="code"
                        style="display: flex; align-items: center; gap: 4px; min-width: 140px;"
                      >
                        <span style="font-size: 12px; min-width: 120px; overflow: hidden; text-overflow: ellipsis;" :title="(selectedStrategyInfo.asset_names && selectedStrategyInfo.asset_names[code]) ? code + ' - ' + selectedStrategyInfo.asset_names[code] : code">{{ (selectedStrategyInfo.asset_names && selectedStrategyInfo.asset_names[code]) ? code + ' - ' + selectedStrategyInfo.asset_names[code] : code }}</span>
                        <el-tooltip v-if="maxWeightDict[code] != null" :content="'指数编制规则上限 ' + ((maxWeightDict[code] || 0) * 100).toFixed(0) + '%'" placement="top">
                          <span>
                            <el-input-number
                              v-model="adj.weights[code]"
                              :min="0"
                              :max="maxWeightDict[code] != null ? maxWeightDict[code] : 1"
                              :step="0.05"
                              :precision="4"
                              size="small"
                              controls-position="right"
                              style="width: 90px;"
                              @change="onAdjustmentWeightChange(idx)"
                            ></el-input-number>
                          </span>
                        </el-tooltip>
                        <el-input-number
                          v-else
                          v-model="adj.weights[code]"
                          :min="0"
                          :max="1"
                          :step="0.05"
                          :precision="4"
                          size="small"
                          controls-position="right"
                          style="width: 90px;"
                          @change="onAdjustmentWeightChange(idx)"
                        ></el-input-number>
                      </div>
                    </div>
                    <div v-if="getAdjustmentWeightSum(idx) !== null" style="margin-top: 8px; font-size: 12px;" :style="{ color: Math.abs(getAdjustmentWeightSum(idx) - 1) < 0.001 ? '#67C23A' : '#E6A23C' }">
                      权重和：{{ (getAdjustmentWeightSum(idx) * 100).toFixed(2) }}%
                      <span v-if="Math.abs(getAdjustmentWeightSum(idx) - 1) > 0.001 && adj.auto_normalize">（将自动归一化）</span>
                      <span v-else-if="Math.abs(getAdjustmentWeightSum(idx) - 1) > 0.001 && !adj.auto_normalize">（不归一化，按填写值使用）</span>
                    </div>
                  </el-form-item>
                </div>
                <el-button type="primary" size="small" plain @click="addManualAdjustment">
                  <i class="el-icon-plus"></i> 添加调仓日
                </el-button>
                </el-form>
              </el-card>
            </el-form-item>
          </template>

          <!-- 多策略对比：杠杆倍数限制 + 主观策略预设调仓日期与权重 -->
          <template v-if="form.backtest_mode === 'multi' && (selectedStrategiesWithManual.length > 0 || selectedStrategiesWithSelection.length > 0)">
            <el-form-item label="杠杆倍数限制">
              <el-input-number
                v-model="form.run_max_leverage"
                :min="1"
                :max="10"
                :step="0.5"
                :precision="1"
                placeholder="不填则使用各策略模型配置"
                controls-position="right"
                style="width: 160px;"
              ></el-input-number>
              <span style="margin-left: 8px; color: #909399; font-size: 12px;">（主观策略：权重和不得超过此倍数；动量选择策略：资产权重按此倍数缩放，不归一化）</span>
            </el-form-item>
            <el-form-item label="主观策略：预设调仓日期与权重">
              <el-card shadow="never" style="background-color: #f0f9ff; border: 1px solid #b3d8ff;">
                <div slot="header" style="font-size: 14px; font-weight: 500; color: #409EFF;">
                  <i class="el-icon-date"></i> 多策略中的主观策略需至少一个调仓日（权重可留空，步进时再选）
                </div>
                <div style="margin-bottom: 12px; color: #606266; font-size: 13px;">
                  每个主观策略与单策略一致：可设置<strong>权重初始化</strong>（默认取策略模型默认权重），并在下方预设调仓日与权重。若策略模型中已配置，将自动带出；否则请在此添加。资产权重按指数编制规则设上限。
                </div>
                <el-collapse>
                  <el-collapse-item
                    v-for="s in selectedStrategiesWithManual"
                    :key="s.id"
                    :name="s.id"
                  >
                    <template slot="title">
                      <span style="font-weight: 500;">{{ s.name || s.id }}</span>
                    </template>
                    <el-form :model="form" label-width="80px" style="margin-bottom: 0;">
                    <!-- 多策略主观：权重初始化（本次回测），默认值为策略模型默认权重 -->
                    <div v-if="form.multiStrategyRunManualWeights[s.id]" style="margin-bottom: 16px; padding: 12px; background: #fafafa; border: 1px solid #e4e7ed; border-radius: 4px;">
                      <div style="font-size: 13px; font-weight: 500; margin-bottom: 8px; color: #303133;">权重初始化（本次回测）</div>
                      <div style="font-size: 12px; color: #909399; margin-bottom: 8px;">默认取自策略模型默认权重，可修改后仅对本次回测生效。</div>
                      <div style="display: flex; flex-wrap: wrap; gap: 12px;">
                        <div
                          v-for="code in (s.asset_codes || [])"
                          :key="'init-' + code"
                          style="display: flex; align-items: center; gap: 4px; min-width: 140px;"
                        >
                          <span style="font-size: 12px; min-width: 120px; overflow: hidden; text-overflow: ellipsis;" :title="(s.asset_names && s.asset_names[code]) ? code + ' - ' + s.asset_names[code] : code">{{ (s.asset_names && s.asset_names[code]) ? code + ' - ' + s.asset_names[code] : code }}</span>
                          <el-tooltip v-if="multiStrategyMaxWeightDict[code] != null" :content="'指数编制规则上限 ' + ((multiStrategyMaxWeightDict[code] || 0) * 100).toFixed(0) + '%'" placement="top">
                            <el-input-number
                              v-model="form.multiStrategyRunManualWeights[s.id][code]"
                              :min="0"
                              :max="multiStrategyMaxWeightDict[code] != null ? multiStrategyMaxWeightDict[code] : 1"
                              :step="0.05"
                              :precision="4"
                              size="small"
                              controls-position="right"
                              style="width: 90px;"
                            ></el-input-number>
                          </el-tooltip>
                          <el-input-number
                            v-else
                            v-model="form.multiStrategyRunManualWeights[s.id][code]"
                            :min="0"
                            :max="1"
                            :step="0.05"
                            :precision="4"
                            size="small"
                            controls-position="right"
                            style="width: 90px;"
                          ></el-input-number>
                        </div>
                      </div>
                      <div v-if="getMultiStrategyRunManualWeightsSum(s.id) !== null" style="margin-top: 8px; font-size: 12px;" :style="{ color: getMultiStrategyRunManualWeightsSum(s.id) > getEffectiveMaxLeverage(s) ? '#F56C6C' : (Math.abs(getMultiStrategyRunManualWeightsSum(s.id) - 1) < 0.001 ? '#67C23A' : '#E6A23C') }">
                        权重和：{{ (getMultiStrategyRunManualWeightsSum(s.id) * 100).toFixed(2) }}%
                        <span v-if="getEffectiveMaxLeverage(s) != null" style="color: #909399;">（不得超过杠杆 {{ (getEffectiveMaxLeverage(s) * 100).toFixed(0) }}%）</span>
                      </div>
                    </div>
                    <div style="font-size: 13px; font-weight: 500; margin-bottom: 8px; color: #303133;">预设调仓日期与权重</div>
                    <div
                      v-for="(adj, idx) in getMultiStrategyManualAdjustmentsList(s.id)"
                      :key="idx"
                      style="border: 1px solid #DCDFE6; border-radius: 4px; padding: 12px; margin-bottom: 12px; background: #fff;"
                    >
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <span style="font-weight: 500;">调仓日 {{ idx + 1 }}</span>
                        <el-button type="text" size="small" @click="removeMultiStrategyManualAdjustment(s.id, idx)" style="color: #F56C6C;">删除</el-button>
                      </div>
                      <el-row :gutter="16">
                        <el-col :span="8">
                          <el-form-item label="日期" label-width="80px">
                            <el-date-picker
                              v-model="adj.date"
                              type="date"
                              placeholder="选择调仓日期"
                              value-format="yyyy-MM-dd"
                              :picker-options="rebalanceDatePickerOptions"
                              style="width: 100%;"
                            ></el-date-picker>
                          </el-form-item>
                        </el-col>
                        <el-col :span="8">
                          <el-form-item label="是否归一化" label-width="90px">
                            <el-switch v-model="adj.auto_normalize"></el-switch>
                          </el-form-item>
                        </el-col>
                      </el-row>
                      <el-form-item label="资产权重" label-width="80px">
                        <div style="display: flex; flex-wrap: wrap; gap: 12px;">
                          <div
                            v-for="code in (s.asset_codes || [])"
                            :key="code"
                            style="display: flex; align-items: center; gap: 4px; min-width: 140px;"
                          >
                            <span style="font-size: 12px; min-width: 120px; overflow: hidden; text-overflow: ellipsis;" :title="(s.asset_names && s.asset_names[code]) ? code + ' - ' + s.asset_names[code] : code">{{ (s.asset_names && s.asset_names[code]) ? code + ' - ' + s.asset_names[code] : code }}</span>
                            <el-tooltip v-if="multiStrategyMaxWeightDict[code] != null" :content="'指数编制规则上限 ' + ((multiStrategyMaxWeightDict[code] || 0) * 100).toFixed(0) + '%'" placement="top">
                              <el-input-number
                                v-model="adj.weights[code]"
                                :min="0"
                                :max="multiStrategyMaxWeightDict[code] != null ? multiStrategyMaxWeightDict[code] : 1"
                                :step="0.05"
                                :precision="4"
                                size="small"
                                controls-position="right"
                                style="width: 90px;"
                              ></el-input-number>
                            </el-tooltip>
                            <el-input-number
                              v-else
                              v-model="adj.weights[code]"
                              :min="0"
                              :max="1"
                              :step="0.05"
                              :precision="4"
                              size="small"
                              controls-position="right"
                              style="width: 90px;"
                            ></el-input-number>
                          </div>
                        </div>
                        <div v-if="getMultiStrategyAdjustmentWeightSum(s.id, idx) !== null" style="margin-top: 8px; font-size: 12px;" :style="{ color: Math.abs(getMultiStrategyAdjustmentWeightSum(s.id, idx) - 1) < 0.001 ? '#67C23A' : '#E6A23C' }">
                          权重和：{{ (getMultiStrategyAdjustmentWeightSum(s.id, idx) * 100).toFixed(2) }}%
                        </div>
                      </el-form-item>
                    </div>
                    <el-button type="primary" size="small" plain @click="addMultiStrategyManualAdjustment(s.id)">
                      <i class="el-icon-plus"></i> 添加调仓日
                    </el-button>
                    </el-form>
                  </el-collapse-item>
                </el-collapse>
              </el-card>
            </el-form-item>
          </template>

          <!-- 波动率重置日人工干预说明（单策略且启用波动率重置且非主观策略时显示） -->
          <el-form-item v-if="form.backtest_mode === 'single' && !isManualAllocationStrategy && form.enable_vol_reset" label="波动率重置日">
            <el-card shadow="never" style="background-color: #f0f9ff; border: 1px solid #b3d8ff;">
              <div slot="header" style="font-size: 14px; font-weight: 500; color: #409EFF;">
                <i class="el-icon-edit"></i> 执行过程中步进选择
              </div>
              <div style="color: #606266; font-size: 13px;">
                回测将先运行一次；若存在<strong>波动率阈值重置</strong>触发的日期，完成后会列出这些日期，由您逐日选择「使用自动重置权重」或「人工设定重置权重」，然后重新回测得到最终结果。
              </div>
            </el-card>
          </el-form-item>

          <!-- 回测时间 -->
          <el-form-item label="回测时间" prop="date_range">
            <el-date-picker
              v-model="form.date_range"
              type="daterange"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              style="width: 100%;"
            ></el-date-picker>
            <el-tooltip content="回测的时间区间，系统将从开始日期到结束日期进行模拟交易" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </el-form-item>

          <!-- 交易成本 -->
          <el-divider content-position="left">交易成本</el-divider>
          
          <el-form-item label="手续费率" prop="commission_rate">
            <el-input-number
              v-model="form.commission_rate"
              :min="0"
              :max="0.01"
              :step="0.0001"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
            <el-tooltip content="交易手续费率，默认0.03%（万三），包含买卖双向成本" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
            <span style="margin-left: 10px; color: #909399;">（默认：0.0003，范围：0-0.01，步长：0.0001）</span>
          </el-form-item>

          <el-form-item label="滑点" prop="slippage">
            <el-input-number
              v-model="form.slippage"
              :min="0"
              :max="0.01"
              :step="0.0001"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
            <el-tooltip content="市场冲击成本（滑点），默认0.05%（万五），用于模拟大额交易对价格的影响" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
            <span style="margin-left: 10px; color: #909399;">（默认：0.0005，范围：0-0.01，步长：0.0001）</span>
          </el-form-item>

          <!-- 操作按钮 -->
          <el-form-item>
            <el-button type="primary" @click="handleExecute" :loading="executing" size="medium">
              <i class="el-icon-video-play"></i> {{ executing ? '回测中...' : '执行回测' }}
            </el-button>
            <el-button @click="handleReset" size="medium">重置</el-button>
            <el-button @click="handleViewHistory" size="medium">历史记录</el-button>
          </el-form-item>
        </el-form>

        <!-- 提示信息 -->
        <el-alert
          v-if="!executing && !backtestResults"
          title="提示"
          type="info"
          :closable="false"
          style="margin-top: 20px;"
        >
          <template slot="default">
            <p>请配置回测参数后点击执行按钮</p>
            <p style="margin-top: 10px; font-size: 12px; color: #909399;">
              • 单策略回测：查看单个策略的完整回测结果，包含净值曲线、持仓变化、交易明细等<br/>
              • 多策略对比：同时运行2-5个策略，横向对比绩效指标和净值曲线
            </p>
          </template>
        </el-alert>
      </el-card>

      <!-- 回测结果展示 -->
      <backtest-result
        v-if="backtestResults"
        :results="backtestResults"
        :mode="form.backtest_mode"
        :config="form"
        :model-id="backtestModelId"
      ></backtest-result>

      <!-- 波动率重置日 - 选择是否人工干预（步进式） -->
      <el-dialog
        title="波动率重置日 — 选择是否人工干预"
        :visible.sync="volResetDecisionDialog.visible"
        width="720px"
        :close-on-click-modal="false"
        :append-to-body="false"
        @close="onVolResetDialogClose"
      >
        <p style="color: #606266; margin-bottom: 16px;">
          以下日期触发了<strong>波动率阈值重置</strong>。您可为每个日期选择「使用自动重置权重」或「人工设定重置权重」，然后重新回测得到最终结果。
        </p>
        <div
          v-for="(pt, idx) in volResetDecisionDialog.points"
          :key="pt.dateStr"
          style="border: 1px solid #EBEEF5; border-radius: 4px; padding: 12px; margin-bottom: 12px; background: #FAFAFA;"
        >
          <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 500; margin-right: 12px;">{{ pt.dateStr }}</span>
            <el-radio-group v-model="pt.useAuto" size="small">
              <el-radio :label="true">使用自动重置权重</el-radio>
              <el-radio :label="false">人工设定重置权重</el-radio>
            </el-radio-group>
          </div>
          <div v-if="!pt.useAuto" style="margin-top: 10px;">
            <div style="display: flex; flex-wrap: wrap; gap: 10px;">
              <div
                v-for="code in (volResetDecisionDialog.strategy && volResetDecisionDialog.strategy.asset_codes) || []"
                :key="code"
                style="display: flex; align-items: center; gap: 4px;"
              >
                <span style="font-size: 12px; width: 72px; overflow: hidden; text-overflow: ellipsis;" :title="code">{{ code }}</span>
                <el-input-number
                  v-model="pt.manualWeights[code]"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :precision="4"
                  size="small"
                  controls-position="right"
                  style="width: 88px;"
                ></el-input-number>
              </div>
            </div>
            <div v-if="getVolResetPointWeightSum(pt) !== null" style="margin-top: 6px; font-size: 12px;" :style="{ color: Math.abs(getVolResetPointWeightSum(pt) - 1) < 0.001 ? '#67C23A' : '#E6A23C' }">
              权重和：{{ (getVolResetPointWeightSum(pt) * 100).toFixed(2) }}%
            </div>
          </div>
        </div>
        <span slot="footer" class="dialog-footer">
          <el-button @click="onVolResetDialogClose">使用首次回测结果</el-button>
          <el-button type="primary" :loading="volResetDecisionDialog.loading" @click="confirmVolResetAndRerun">
            确认并重新回测
          </el-button>
        </span>
      </el-dialog>

      <!-- 主观策略预设调仓日步进：到该日暂停，按预设权重调仓，可查看绩效后继续 -->
      <el-dialog
        :title="presetStepDialogTitle"
        :visible.sync="presetStepDialog.visible"
        width="700px"
        :close-on-click-modal="false"
        :append-to-body="false"
        @close="onPresetStepDialogClose"
      >
        <template v-if="presetStepDialog.stepResponse">
          <p v-if="form.backtest_mode === 'multi' && presetStepDialog.strategy" style="margin-bottom: 10px; padding: 8px 12px; background: #ecf5ff; border-left: 4px solid #409EFF; color: #303133; font-weight: 500;">
            当前步进策略：<strong>{{ presetStepDialog.strategy.name }}</strong>
          </p>
          <p style="color: #606266; margin-bottom: 12px;">
            回测已运行至 <strong>{{ formatPresetDate(presetStepDialog.stepResponse.next_preset_date) }}</strong>，该日将按预设权重调仓，可查看下方绩效后继续。
          </p>
          <!-- 当前持仓绩效（至本调仓日）：始终显示该卡片，有数据则展示收益/波动/回撤/风险调整收益 -->
          <el-card shadow="never" style="margin-bottom: 14px; background: #fafafa; border: 1px solid #EBEEF5;">
            <div slot="header" style="font-size: 13px; font-weight: 600; color: #303133;">当前持仓绩效（至本调仓日）</div>
            <template v-if="presetStepDialog.stepResponse.current_metrics && Object.keys(presetStepDialog.stepResponse.current_metrics).length">
              <el-row :gutter="16">
                <el-col :span="8">
                  <div class="metric-item">
                    <span class="metric-label">累计收益率</span>
                    <span class="metric-value" :style="{ color: ((presetStepDialog.stepResponse.current_metrics.total_return || 0) >= 0) ? '#67C23A' : '#F56C6C' }">
                      {{ formatPercent(presetStepDialog.stepResponse.current_metrics.total_return) }}
                    </span>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="metric-item">
                    <span class="metric-label">年化收益率</span>
                    <span class="metric-value" :style="{ color: ((presetStepDialog.stepResponse.current_metrics.annual_return || 0) >= 0) ? '#67C23A' : '#F56C6C' }">
                      {{ formatPercent(presetStepDialog.stepResponse.current_metrics.annual_return) }}
                    </span>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="metric-item">
                    <span class="metric-label">年化波动率</span>
                    <span class="metric-value">{{ formatPercent(presetStepDialog.stepResponse.current_metrics.volatility) }}</span>
                  </div>
                </el-col>
              </el-row>
              <el-row :gutter="16" style="margin-top: 10px;">
                <el-col :span="8">
                  <div class="metric-item">
                    <span class="metric-label">最大回撤</span>
                    <span class="metric-value" style="color: #F56C6C;">{{ formatPercent(presetStepDialog.stepResponse.current_metrics.max_drawdown) }}</span>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="metric-item">
                    <span class="metric-label">夏普比率</span>
                    <span class="metric-value">{{ formatMetric(presetStepDialog.stepResponse.current_metrics.sharpe_ratio) }}</span>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="metric-item">
                    <span class="metric-label">卡玛比率</span>
                    <span class="metric-value">{{ formatMetric(presetStepDialog.stepResponse.current_metrics.calmar_ratio) }}</span>
                  </div>
                </el-col>
              </el-row>
              <el-row :gutter="16" style="margin-top: 10px;">
                <el-col :span="12">
                  <div class="metric-item">
                    <span class="metric-label">当前净值</span>
                    <span class="metric-value">{{ formatNav(presetStepDialog.stepResponse.current_metrics.current_nav) }}</span>
                  </div>
                </el-col>
                <el-col :span="12">
                  <div class="metric-item">
                    <span class="metric-label">初始净值</span>
                    <span class="metric-value">{{ formatNav(presetStepDialog.stepResponse.current_metrics.initial_nav) }}</span>
                  </div>
                </el-col>
              </el-row>
            </template>
            <p v-else style="color: #909399; font-size: 13px; margin: 0;">暂无至本日绩效数据</p>
          </el-card>
          <!-- 多策略：其他策略截至当前调仓日指标（对比参考） -->
          <el-card v-if="form.backtest_mode === 'multi'" shadow="never" style="margin-bottom: 14px; background: #f5f7fa; border: 1px solid #E4E7ED;">
            <div slot="header" style="font-size: 13px; font-weight: 600; color: #303133;">其他策略截至本调仓日绩效（同一时间线对比，非最终回测结果）</div>
            <div v-if="presetStepDialog.loading" style="color: #909399; font-size: 13px;">加载中…</div>
            <el-table v-else-if="presetStepDialog.otherStrategiesMetrics && presetStepDialog.otherStrategiesMetrics.length" :data="presetStepDialog.otherStrategiesMetrics" size="small" border style="width: 100%;">
              <el-table-column prop="strategyName" label="策略" min-width="100"></el-table-column>
              <el-table-column label="累计收益" min-width="90">
                <template slot-scope="scope">{{ formatPercent(scope.row.total_return) }}</template>
              </el-table-column>
              <el-table-column label="年化收益" min-width="90">
                <template slot-scope="scope">{{ formatPercent(scope.row.annual_return) }}</template>
              </el-table-column>
              <el-table-column label="波动率" min-width="80">
                <template slot-scope="scope">{{ formatPercent(scope.row.volatility) }}</template>
              </el-table-column>
              <el-table-column label="最大回撤" min-width="90">
                <template slot-scope="scope">{{ formatPercent(scope.row.max_drawdown) }}</template>
              </el-table-column>
              <el-table-column label="夏普" min-width="70">
                <template slot-scope="scope">{{ formatMetric(scope.row.sharpe_ratio) }}</template>
              </el-table-column>
            </el-table>
            <p v-else style="color: #909399; font-size: 13px; margin: 0;">暂无其他策略数据</p>
          </el-card>
          <div style="margin-bottom: 12px; font-size: 13px; color: #909399;">
            当前持仓权重：
            <span v-for="(w, code) in (presetStepDialog.stepResponse.current_weights || {})" :key="code" style="margin-right: 12px;">
              {{ (presetStepDialog.stepResponse.asset_names && presetStepDialog.stepResponse.asset_names[code]) || code }} {{ ((w || 0) * 100).toFixed(1) }}%
            </span>
          </div>
        </template>
        <span slot="footer" class="dialog-footer">
          <el-button @click="onPresetStepDialogClose">取消</el-button>
          <el-button type="primary" :loading="presetStepDialog.loading" @click="confirmPresetStepAndContinue">
            确认并继续回测
          </el-button>
        </span>
      </el-dialog>

      <!-- 同步调仓日与权重到策略模型确认 -->
      <el-dialog
        title="同步调仓配置到策略模型"
        :visible.sync="syncConfirmDialog.visible"
        width="480px"
        :close-on-click-modal="false"
        :append-to-body="false"
        @close="onSyncConfirmDialogClose"
      >
        <p style="color: #606266; margin-bottom: 12px;">
          您已修改了调仓日期或权重，是否将修改同步回对应的主观策略模型？同步后，下次回测将默认使用新配置。
        </p>
        <span slot="footer" class="dialog-footer">
          <el-button @click="syncConfirmChoose('cancel')">取消</el-button>
          <el-button @click="syncConfirmChoose('runOnly')">仅回测</el-button>
          <el-button type="primary" :loading="syncConfirmDialog.loading" @click="syncConfirmChoose('syncAndRun')">
            同步并回测
          </el-button>
        </span>
      </el-dialog>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';
import BacktestResult from './BacktestResult.vue';
import { getMaxWeightsByCodes, computeMetricsFromSnapshots } from '@/api/strategy';

export default {
  name: 'BacktestExecution',
  components: {
    BacktestResult
  },
  data() {
    return {
      form: {
        backtest_mode: 'single',
        strategy_ids: null, // 单策略模式为单个值，多策略模式为数组
        initial_cash: 1000000,
        rebalance_freq: 'monthly',
        date_range: [
          dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
          dayjs().format('YYYY-MM-DD')
        ],
        commission_rate: 0.0003,
        slippage: 0.0005,
        // 波动率阈值重置（所有策略可选）
        enable_vol_reset: true,
        vol_reset_threshold: 0.06,
        // 动量选择器参数（单策略模式使用）
        selector_type: 'momentum',
        asset_selection_count: 2,
        momentum_windows: '20,60,120,250',
        smom_windows: '20,60,120,250',
        macd_windows: '40,80,120,160',
        reversal_windows: '10,22',
        // 手动选择的资产代码列表
        selected_asset_codes: [],
        // 多策略模式的选择器参数（每个策略单独配置）
        multiStrategySelectionParams: {},
        // 交互式权重调整（仅主观配置策略）
        enable_interactive_adjustment: false,
        manual_weight_adjustments: [],
        // 权重初始化（本次回测覆盖，仅主观配置策略；为空时使用模型配置）
        run_manual_weights: {},
        // 多策略对比：每个主观策略的预设调仓日与权重 { [strategyId]: [ { date, weights, auto_normalize }, ... ] }
        multiStrategyManualAdjustments: {},
        // 多策略对比：每个主观策略的权重初始化（本次回测）{ [strategyId]: { [code]: number } }，默认值为策略模型默认权重
        multiStrategyRunManualWeights: {},
        // 杠杆倍数限制（本次回测，不填则使用策略模型配置；用于动态限制初始化权重、预设调仓日权重、步进调仓权重）
        run_max_leverage: null
      },
      executing: false,
      backtestResults: null,
      backtestModelId: null,
      selectedStrategyInfo: null,
      // 波动率重置日人工干预：首次回测后若存在重置日则弹出，用户逐日选择后重新回测
      volResetDecisionDialog: {
        visible: false,
        loading: false,
        strategyId: null,
        strategy: null,
        backtestData: null,
        firstRunResult: null,
        points: []  // { dateStr, autoWeights, useAuto, manualWeights }
      },
      // 主观策略预设调仓日步进：到每个预设日暂停，用户选择 预设权重/实时输入/不调仓
      presetStepDialog: {
        visible: false,
        loading: false,
        strategyId: null,
        strategy: null,
        backtestData: null,
        stepResponse: null,  // { phase, state, next_preset_date, remaining_preset_dates, current_weights, snapshots, asset_names }
        decision: 'skip',    // use_preset | custom | skip
        customWeights: {},   // 当 decision === 'custom' 时使用
        autoNormalize: false, // 是否归一化（默认不归一化）
        otherStrategiesMetrics: []  // 多策略步进时，其他策略截至当前调仓日的指标 [{ strategyId, strategyName, total_return, ... }]
      },
      // 多主观策略同步步进：多个主观策略均 start 后，按时间线顺序依次弹窗；key=strategyId, value={ strategy, strategyId, backtestData, stepResponse }
      multiManualPending: {},
      maxWeightDict: {},  // 指数编制规则下每类资产权重上限，供权重初始化与预设调仓输入限制
      multiStrategyMaxWeightDict: {},  // 多策略主观：所有主观策略资产池的指数编制规则权重上限 { [assetCode]: max }
      // 调仓日期禁用：节假日列表（YYYY-MM-DD），可从接口扩展；空则仅禁用周末
      rebalanceHolidayDates: [],
      // 用于检测回测表单中的调仓日/权重是否被修改（以便提示同步回策略模型）
      originalManualAdjustments: null,      // 单策略：从策略加载的预设调仓日与权重
      originalRunManualWeights: null,       // 单策略：从策略加载的权重初始化
      originalMultiStrategyManualAdjustments: {},   // 多策略：{ [strategyId]: [...] }
      originalMultiStrategyRunManualWeights: {},   // 多策略：{ [strategyId]: {...} }
      // 同步确认对话框
      syncConfirmDialog: {
        visible: false,
        loading: false,
        resolve: null  // Promise resolve，用于返回用户选择
      }
    };
  },
  computed: {
    ...mapState('strategy', ['strategyModelList']),
    // 为了兼容性，提供 strategyList 作为 strategyModelList 的别名
    strategyList() {
      return this.strategyModelList || [];
    },
    presetStepDialogTitle() {
      const d = this.presetStepDialog;
      if (this.form.backtest_mode === 'multi' && d.strategy && d.strategy.name) {
        return `预设调仓日 — 选择调仓方式（当前策略：${d.strategy.name}）`;
      }
      return '预设调仓日 — 选择调仓方式';
    },
    selectedStrategies() {
      if (!this.form.strategy_ids) return [];
      const ids = Array.isArray(this.form.strategy_ids) ? this.form.strategy_ids : [this.form.strategy_ids];
      return ids.map(id => this.strategyList.find(s => s.id === id)).filter(Boolean);
    },
    // 检查是否有策略启用了动量选择器
    hasMomentumSelection() {
      if (!this.selectedStrategyInfo) return false;
      return this.selectedStrategyInfo.enable_momentum_selection === true;
    },
    // 获取所有启用了选择器的策略（多策略模式）
    selectedStrategiesWithSelection() {
      if (this.form.backtest_mode !== 'multi') return [];
      return this.selectedStrategies.filter(s => s.enable_momentum_selection === true);
    },
    // 多策略模式下选中的主观配置策略（需配置预设调仓日与权重）
    selectedStrategiesWithManual() {
      if (this.form.backtest_mode !== 'multi') return [];
      return this.selectedStrategies.filter(s => this.isStrategyManual(s));
    },
    // 表单校验规则（主观策略下不校验调仓频率，因其被隐藏；数值类用 validator 避免类型误判）
    rules() {
      return {
        strategy_ids: [
          {
            validator: (rule, value, callback) => {
              const ids = value === null || value === undefined ? ([]).concat(value) : (Array.isArray(value) ? value : [value]);
              if (!ids.length || ids.every(id => id === null || id === undefined || id === '')) return callback(new Error('请选择策略'));
              callback();
            },
            trigger: 'change'
          }
        ],
        initial_cash: [
          {
            validator: (rule, value, callback) => {
              const n = Number(value);
              if (value === undefined || value === null || value === '') return callback(new Error('请输入初始资金'));
              if (!Number.isFinite(n) || n < 100000) return callback(new Error('初始资金至少为10万元'));
              callback();
            },
            trigger: 'blur'
          }
        ],
        rebalance_freq: [
          {
            validator: (rule, value, callback) => {
              if (this.isManualAllocationStrategy) return callback();
              if (value === undefined || value === null || value === '') return callback(new Error('请选择调仓频率'));
              callback();
            },
            trigger: 'change'
          }
        ],
        date_range: [
          {
            validator: (rule, value, callback) => {
              if (!value || !Array.isArray(value) || value.length !== 2) return callback(new Error('请选择回测时间'));
              if (!value[0] || !value[1]) return callback(new Error('请选择完整的回测时间范围'));
              callback();
            },
            trigger: 'change'
          }
        ],
        commission_rate: [
          {
            validator: (rule, value, callback) => {
              if (value === undefined || value === null || value === '') return callback(new Error('请输入手续费率'));
              const n = Number(value);
              if (!Number.isFinite(n) || n < 0) return callback(new Error('手续费率不能为负'));
              callback();
            },
            trigger: 'blur'
          }
        ],
        slippage: [
          {
            validator: (rule, value, callback) => {
              if (value === undefined || value === null || value === '') return callback(new Error('请输入滑点'));
              const n = Number(value);
              if (!Number.isFinite(n) || n < 0) return callback(new Error('滑点不能为负'));
              callback();
            },
            trigger: 'blur'
          }
        ]
      };
    },
    // 计算已选择的策略数量（正确处理单策略和多策略模式）
    selectedStrategyCount() {
      if (!this.form.strategy_ids) return 0;
      if (this.form.backtest_mode === 'single') {
        // 单策略模式：strategy_ids 是单个值或 null
        return this.form.strategy_ids ? 1 : 0;
      } else {
        // 多策略模式：strategy_ids 是数组
        return Array.isArray(this.form.strategy_ids) ? this.form.strategy_ids.length : 0;
      }
    },
    hasPresetWeightsForCurrentDate() {
      const resp = this.presetStepDialog.stepResponse;
      if (!resp || !resp.next_preset_date) return false;
      const list = this.form.backtest_mode === 'multi' && this.presetStepDialog.strategyId
        ? (this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[this.presetStepDialog.strategyId]) || []
        : (this.form.manual_weight_adjustments || []);
      const preset = list.find(adj => (adj.date || '').replace(/-/g, '').slice(0, 8) === resp.next_preset_date);
      return preset && preset.weights && Object.keys(preset.weights).length > 0 && Object.values(preset.weights).some(v => (Number(v) || 0) > 0);
    },
    presetStepCustomSum() {
      const w = this.presetStepDialog.customWeights || {};
      const vals = Object.values(w);
      if (!vals.length) return null;
      return vals.reduce((s, v) => s + (Number(v) || 0), 0);
    },
    presetStepMaxLeverage() {
      return this.getEffectiveMaxLeverage(this.presetStepDialog.strategy);
    },
    // 资产池列表（用于手动选择资产）
    assetPoolForSelection() {
      if (!this.selectedStrategyInfo || !this.selectedStrategyInfo.asset_codes) {
        return [];
      }
      // 返回资产池中的资产，带名称（若有）
      return this.selectedStrategyInfo.asset_codes.map(code => ({
        code,
        name: this.selectedStrategyInfo.asset_names?.[code] || code
      }));
    },
    // 资产池大小
    assetPoolSize() {
      return this.assetPoolForSelection.length || 100;
    },
    // 是否为主观配置策略（支持权重初始化与交互式权重调整）
    isManualAllocationStrategy() {
      if (!this.selectedStrategyInfo) return false;
      const code = (this.selectedStrategyInfo.template_code || '').toString();
      return code === 'manual_allocation' || code === 'manual_allocation_strategy'
        || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
    },
    // 是否为 risk_budget_target_vol 策略（回测时策略参数不可前台调整，隐藏策略参数展示）
    isRiskBudgetTargetVolStrategy() {
      if (!this.selectedStrategyInfo) return false;
      const code = (this.selectedStrategyInfo.template_code || '').toString();
      return code === 'risk_budget_target_vol';
    },
    // 策略模型中的权重初始化（用于回测页展示/覆盖）
    modelManualWeights() {
      if (!this.selectedStrategyInfo) return {};
      const p = this.selectedStrategyInfo.parameters || this.selectedStrategyInfo.strategy_params || {};
      const mw = p.manual_weights;
      if (typeof mw === 'object' && mw !== null) return mw;
      return {};
    },
    runManualWeightsSum() {
      const mw = this.form.run_manual_weights;
      if (typeof mw !== 'object' || !mw) return null;
      return Object.values(mw).reduce((s, v) => s + (Number(v) || 0), 0);
    },
    /** 本次回测有效杠杆倍数（用于显示与校验）；单策略且主观配置时有效，否则为 null */
    runMaxLeverage() {
      if (this.form.backtest_mode !== 'single' || !this.isManualAllocationStrategy) return null;
      return this.getEffectiveMaxLeverage(this.selectedStrategyInfo);
    },
    /** 是否修改了调仓日或权重（单策略或多策略主观） */
    hasManualAdjustmentsModified() {
      if (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) {
        if (this.originalManualAdjustments == null && this.originalRunManualWeights == null) return false;
        const adjEq = this.deepEqual(this.form.manual_weight_adjustments || [], this.originalManualAdjustments || []);
        const runEq = this.deepEqual(this.form.run_manual_weights || {}, this.originalRunManualWeights || {});
        return !adjEq || !runEq;
      }
      if (this.form.backtest_mode === 'multi' && (this.selectedStrategiesWithManual || []).length > 0) {
        const m = this.form.multiStrategyManualAdjustments || {};
        const r = this.form.multiStrategyRunManualWeights || {};
        const origM = this.originalMultiStrategyManualAdjustments || {};
        const origR = this.originalMultiStrategyRunManualWeights || {};
        for (const s of this.selectedStrategiesWithManual || []) {
          const id = s.id;
          const adjEq = this.deepEqual(m[id] || [], origM[id] || []);
          const runEq = this.deepEqual(r[id] || {}, origR[id] || {});
          if (!adjEq || !runEq) return true;
        }
        return false;
      }
      return false;
    },
    // 调仓日期选择器：禁用周末、节假日，且限制在回测时间区间内
    rebalanceDatePickerOptions() {
      const holidaySet = new Set(this.rebalanceHolidayDates || []);
      const start = this.form.date_range && this.form.date_range[0];
      const end = this.form.date_range && this.form.date_range[1];
      return {
        disabledDate(time) {
          const day = time.getDay();
          if (day === 0 || day === 6) return true; // 周六、周日
          const y = time.getFullYear();
          const m = String(time.getMonth() + 1).padStart(2, '0');
          const d = String(time.getDate()).padStart(2, '0');
          const dateStr = `${y}-${m}-${d}`;
          if (holidaySet.has(dateStr)) return true;
          if (start && dateStr < start) return true;
          if (end && dateStr > end) return true;
          return false;
        }
      };
    }
  },
    watch: {
    'form.strategy_ids': {
      handler() {
        this.updateSelectedStrategyInfo();
        // 策略切换时清空已选资产
        this.form.selected_asset_codes = [];
        // 切换策略时清空交互式权重调整
        this.form.enable_interactive_adjustment = false;
        this.form.manual_weight_adjustments = [];
        // 主观配置策略：预设调仓日由 updateSelectedStrategyInfo 中 initManualWeightAdjustmentsFromStrategy 加载
        this.$nextTick(() => {
          this.syncRunManualWeights();
          if (this.isManualAllocationStrategy && this.$refs.form) this.$refs.form.clearValidate();
        });
        // 如果是多策略模式，初始化选择器参数并清空各策略的已选资产
        if (this.form.backtest_mode === 'multi') {
          // 清空所有策略的已选资产
          Object.keys(this.form.multiStrategySelectionParams || {}).forEach(strategyId => {
            if (this.form.multiStrategySelectionParams[strategyId]) {
              this.$set(this.form.multiStrategySelectionParams[strategyId], 'selected_asset_codes', []);
            }
          });
          this.$nextTick(() => {
            this.initMultiStrategySelectionParams();
            this.initMultiStrategyManualAdjustments();
          });
        }
      },
      deep: true
    },
    'form.backtest_mode'(newMode) {
      // 切换模式时重置策略选择
      if (newMode === 'single') {
        // 切换到单策略模式：如果当前是数组，取第一个；如果是单个值，保持不变
        if (Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids.length > 0 ? this.form.strategy_ids[0] : null;
        }
      } else {
        // 切换到多策略模式：如果当前是单个值，转为数组
        if (!Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids ? [this.form.strategy_ids] : [];
        }
      }
      this.updateSelectedStrategyInfo();
      if (newMode === 'multi') {
        this.$nextTick(() => this.initMultiStrategyManualAdjustments());
      }
    },
    selectedStrategyInfo: {
      handler(info) {
        if (!info || this.form.backtest_mode !== 'single') return;
        const code = (info.template_code || '').toString();
        const isManual = code === 'manual_allocation' || code === 'manual_allocation_strategy'
          || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
        // 仅动量/量化策略应用指数编制规则权重上限；主观策略不限制
        if (!isManual && info.asset_codes && info.asset_codes.length > 0) {
          getMaxWeightsByCodes(info.asset_codes).then(res => {
            const data = (res && res.data && typeof res.data === 'object' && !Array.isArray(res.data)) ? res.data : {};
            this.maxWeightDict = data;
          }).catch(() => {
            this.maxWeightDict = {};
          });
        } else {
          this.maxWeightDict = {};
        }
      },
      immediate: true
    }
  },
  created() {
    this.loadStrategyList();
    // 初始化时更新策略信息
    this.$nextTick(() => {
      this.updateSelectedStrategyInfo();
    });
  },
  methods: {
    async loadStrategyList() {
      try {
        // 加载所有策略（包括草稿和已发布的），不筛选状态
        // 这样新创建的策略也可以用于回测
        const list = await this.$store.dispatch('strategy/fetchStrategyModelList', {
          // 不传 status 参数，加载所有状态的策略
        });
        console.log('策略列表加载成功，共', list?.length || 0, '个策略');
        console.log('策略列表详情:', list);
        // 检查是否有已发布的策略
        const published = list?.filter(s => s.status === '已发布' || s.status === 'published') || [];
        console.log('已发布的策略数量:', published.length);
        if (published.length > 0) {
          console.log('已发布的策略:', published.map(s => ({ id: s.id, name: s.name, status: s.status })));
        }
      } catch (error) {
        console.error('加载策略列表失败:', error);
        this.$message.error('加载策略列表失败：' + (error.response?.data?.detail || error.message || '未知错误'));
      }
    },
    /** 从策略模型加载预设调仓日与权重；若无预设则添加一个默认项 */
    initManualWeightAdjustmentsFromStrategy() {
      if (!this.isManualAllocationStrategy) return;
      const strategy = this.selectedStrategyInfo;
      if (!strategy) {
        this.addManualAdjustment();
        this.saveOriginalManualValues();
        return;
      }
      let preset = strategy.parameters && strategy.parameters.manual_weight_adjustments;
      if (typeof preset === 'string') {
        try { preset = preset.trim() ? JSON.parse(preset) : []; } catch (_) { preset = []; }
      }
      if (Array.isArray(preset) && preset.length > 0) {
        const codes = strategy.asset_codes || [];
        this.form.manual_weight_adjustments = preset.map(adj => {
          const weights = {};
          codes.forEach(c => {
            weights[c] = (adj.weights && adj.weights[c] != null) ? Number(adj.weights[c]) : 0;
          });
          if (codes.length > 0 && Object.values(weights).every(v => !v || v === 0)) {
            weights[codes[0]] = 1;
          }
          return {
            date: this.normalizeDateForPicker(adj.date || '') || '',
            weights,
            auto_normalize: !!adj.auto_normalize
          };
        });
      } else {
        this.addManualAdjustment();
      }
      this.saveOriginalManualValues();
      if (this.$refs.form) this.$refs.form.clearValidate();
    },
    /** 将后端返回的日期（YYYYMMDD 或 YYYY-MM-DD）转为 el-date-picker 需要的 YYYY-MM-DD */
    normalizeDateForPicker(val) {
      if (!val || typeof val !== 'string') return val;
      const s = String(val).replace(/-/g, '').trim().slice(0, 8);
      if (s.length === 8 && /^\d{8}$/.test(s)) {
        return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
      }
      return val;
    },
    /** 深度比较两个值是否相等 */
    deepEqual(a, b) {
      if (a === b) return true;
      if (a == null || b == null) return a === b;
      if (typeof a !== typeof b) return false;
      if (typeof a !== 'object') return a === b;
      if (Array.isArray(a) !== Array.isArray(b)) return false;
      if (Array.isArray(a)) {
        if (a.length !== b.length) return false;
        return a.every((v, i) => this.deepEqual(v, b[i]));
      }
      const keysA = Object.keys(a);
      const keysB = Object.keys(b);
      if (keysA.length !== keysB.length) return false;
      return keysA.every(k => keysB.includes(k) && this.deepEqual(a[k], b[k]));
    },
    /** 保存当前表单值为原始值（用于检测用户是否修改） */
    saveOriginalManualValues() {
      if (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) {
        this.originalManualAdjustments = JSON.parse(JSON.stringify(this.form.manual_weight_adjustments || []));
        this.originalRunManualWeights = JSON.parse(JSON.stringify(this.form.run_manual_weights || {}));
      } else if (this.form.backtest_mode === 'multi') {
        const m = this.form.multiStrategyManualAdjustments || {};
        const r = this.form.multiStrategyRunManualWeights || {};
        this.originalMultiStrategyManualAdjustments = JSON.parse(JSON.stringify(m));
        this.originalMultiStrategyRunManualWeights = JSON.parse(JSON.stringify(r));
      }
    },
    addManualAdjustment() {
      const codes = (this.selectedStrategyInfo && this.selectedStrategyInfo.asset_codes) || [];
      const weights = {};
      codes.forEach(c => { weights[c] = 0; });
      if (codes.length > 0) {
        weights[codes[0]] = 1; // 默认第一个资产 100%
      }
      this.form.manual_weight_adjustments.push({
        date: this.form.date_range && this.form.date_range[0] ? this.form.date_range[0] : '',
        weights,
        auto_normalize: false
      });
      if (this.$refs.form) this.$refs.form.clearValidate();
    },
    removeManualAdjustment(idx) {
      this.form.manual_weight_adjustments.splice(idx, 1);
      if (this.$refs.form) this.$refs.form.clearValidate();
    },
    isStrategyManual(strategy) {
      if (!strategy) return false;
      const code = (strategy.template_code || '').toString();
      return code === 'manual_allocation' || code === 'manual_allocation_strategy'
        || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
    },
    /** 从策略模型取默认权重（新增策略时填写的默认权重）；支持后端返回的 JSON 字符串 */
    getModelManualWeightsForStrategy(s) {
      if (!s) return {};
      const p = s.parameters || s.strategy_params || {};
      let mw = p.manual_weights;
      if (typeof mw === 'string') {
        try {
          mw = JSON.parse(mw);
        } catch (e) {
          return {};
        }
      }
      if (typeof mw === 'object' && mw !== null) return mw;
      return {};
    },
    async initMultiStrategyManualAdjustments() {
      if (this.form.backtest_mode !== 'multi') return;
      const manual = this.selectedStrategiesWithManual || [];
      const m = this.form.multiStrategyManualAdjustments || {};
      const runWeights = this.form.multiStrategyRunManualWeights || {};
      const allCodes = new Set();
      for (let i = 0; i < manual.length; i++) {
        const s = manual[i];
        const id = s.id;
        (s.asset_codes || []).forEach(c => allCodes.add(c));
        let fromModel = this.getModelManualWeightsForStrategy(s);
        let presetAdjustments = s.parameters && s.parameters.manual_weight_adjustments;
        if (Object.keys(fromModel).length === 0 || !Array.isArray(presetAdjustments)) {
          try {
            const full = await this.$store.dispatch('strategy/fetchStrategyModel', id);
            const fullModel = (full && full.data !== undefined) ? full.data : full;
            fromModel = this.getModelManualWeightsForStrategy(fullModel && (fullModel.parameters !== undefined ? { parameters: fullModel.parameters } : fullModel) || fullModel);
            if (fullModel && fullModel.parameters && fullModel.parameters.manual_weight_adjustments) {
              presetAdjustments = fullModel.parameters.manual_weight_adjustments;
            }
          } catch (e) {
            fromModel = {};
          }
        }
        if (typeof presetAdjustments === 'string') {
          try { presetAdjustments = presetAdjustments.trim() ? JSON.parse(presetAdjustments) : []; } catch (_) { presetAdjustments = []; }
        }
        const buildWeightsFromModel = (codes) => {
          const weights = {};
          (codes || []).forEach(c => {
            weights[c] = (fromModel[c] !== undefined && fromModel[c] !== null) ? Number(fromModel[c]) : 0;
          });
          if ((codes || []).length > 0 && Object.values(weights).every(v => !v || v === 0)) {
            weights[(codes || [])[0]] = 1;
          }
          return weights;
        };
        let list = m[id];
        if (!list || list.length === 0) {
          const codes = s.asset_codes || [];
          if (Array.isArray(presetAdjustments) && presetAdjustments.length > 0) {
            list = presetAdjustments.map(adj => {
              const weights = {};
              codes.forEach(c => {
                weights[c] = (adj.weights && adj.weights[c] != null) ? Number(adj.weights[c]) : 0;
              });
              if (codes.length > 0 && Object.values(weights).every(v => !v || v === 0)) {
                weights[codes[0]] = 1;
              }
              return {
                date: this.normalizeDateForPicker(adj.date || '') || '',
                weights,
                auto_normalize: !!adj.auto_normalize
              };
            });
          } else {
            list = [];
            const weights = buildWeightsFromModel(codes);
            const startDate = (this.form.date_range && this.form.date_range[0]) ? this.form.date_range[0] : '';
            list.push({ date: startDate, weights, auto_normalize: false });
          }
          this.$set(this.form.multiStrategyManualAdjustments, id, list);
        }
        if (!runWeights[id]) {
          const weights = buildWeightsFromModel(s.asset_codes || []);
          this.$set(this.form.multiStrategyRunManualWeights, id, weights);
        }
      }
      this.saveOriginalManualValues();
      // 主观策略不应用指数编制规则权重上限，多策略对比中的 manual 均为主观策略
      this.multiStrategyMaxWeightDict = {};
    },
    getMultiStrategyManualAdjustmentsList(strategyId) {
      const m = this.form.multiStrategyManualAdjustments;
      if (!m || !m[strategyId]) return [];
      return m[strategyId];
    },
    addMultiStrategyManualAdjustment(strategyId) {
      const strategy = this.strategyList.find(s => s.id === strategyId);
      if (!strategy) return;
      const m = this.form.multiStrategyManualAdjustments || {};
      if (!m[strategyId]) {
        this.$set(this.form, 'multiStrategyManualAdjustments', { ...m, [strategyId]: [] });
      }
      const list = this.form.multiStrategyManualAdjustments[strategyId];
      const codes = strategy.asset_codes || [];
      const weights = {};
      codes.forEach(c => { weights[c] = 0; });
      if (codes.length > 0) weights[codes[0]] = 1;
      const startDate = this.form.date_range && this.form.date_range[0] ? this.form.date_range[0] : '';
      list.push({ date: startDate, weights, auto_normalize: false });
    },
    removeMultiStrategyManualAdjustment(strategyId, idx) {
      const list = this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[strategyId];
      if (!list) return;
      list.splice(idx, 1);
    },
    getMultiStrategyAdjustmentWeightSum(strategyId, idx) {
      const list = this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[strategyId];
      if (!list || !list[idx] || !list[idx].weights) return null;
      return Object.values(list[idx].weights).reduce((s, v) => s + (Number(v) || 0), 0);
    },
    getMultiStrategyRunManualWeightsSum(strategyId) {
      const w = this.form.multiStrategyRunManualWeights && this.form.multiStrategyRunManualWeights[strategyId];
      if (!w || typeof w !== 'object') return null;
      return Object.values(w).reduce((s, v) => s + (Number(v) || 0), 0);
    },
    getMultiStrategyMaxWeight(strategyOrCodes, code) {
      return this.multiStrategyMaxWeightDict && this.multiStrategyMaxWeightDict[code];
    },
    getAdjustmentWeightSum(idx) {
      const adj = this.form.manual_weight_adjustments[idx];
      if (!adj || !adj.weights) return null;
      return Object.values(adj.weights).reduce((s, v) => s + (Number(v) || 0), 0);
    },
    /** 从策略模型取最大杠杆（默认 4 = 400%） */
    getMaxLeverageForStrategy(strategy) {
      if (!strategy) return 4;
      const p = strategy.parameters || strategy.strategy_params || {};
      const v = p.max_leverage;
      return (v !== undefined && v !== null && !Number.isNaN(Number(v))) ? Number(v) : 4;
    },
    /** 本次回测有效杠杆倍数：优先使用表单「杠杆倍数限制」，否则用策略模型配置 */
    getEffectiveMaxLeverage(strategy) {
      const fromForm = this.form.run_max_leverage;
      if (fromForm != null && fromForm !== '' && !Number.isNaN(Number(fromForm))) {
        const n = Number(fromForm);
        if (n >= 1) return n;
      }
      return this.getMaxLeverageForStrategy(strategy);
    },
    onAdjustmentWeightChange(idx) {
      this.$forceUpdate();
      if (this.$refs.form) this.$refs.form.clearValidate();
    },
    /** 同步调仓日与权重到策略模型（单策略或多策略中的主观策略） */
    async syncManualAdjustmentsToStrategy(strategyId, strategy) {
      const isSingle = this.form.backtest_mode === 'single';
      let adjustments = [];
      let manualWeights = {};
      if (isSingle) {
        adjustments = (this.form.manual_weight_adjustments || []).map(adj => ({
          date: (adj.date || '').replace(/-/g, '').slice(0, 8),
          weights: adj.weights && Object.keys(adj.weights).length > 0 ? { ...adj.weights } : undefined,
          auto_normalize: !!adj.auto_normalize
        }));
        manualWeights = this.form.run_manual_weights || {};
      } else {
        const list = (this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[strategyId]) || [];
        adjustments = list.map(adj => ({
          date: (adj.date || '').replace(/-/g, '').slice(0, 8),
          weights: adj.weights && Object.keys(adj.weights).length > 0 ? { ...adj.weights } : undefined,
          auto_normalize: !!adj.auto_normalize
        }));
        manualWeights = (this.form.multiStrategyRunManualWeights && this.form.multiStrategyRunManualWeights[strategyId]) || {};
      }
      try {
        const full = await this.$store.dispatch('strategy/fetchStrategyModel', strategyId);
        const model = full && full.data !== undefined ? full.data : full;
        const params = { ...(model.parameters || {}) };
        params.manual_weight_adjustments = adjustments;
        if (Object.keys(manualWeights).length > 0) {
          params.manual_weights = manualWeights;
        }
        const updateData = {
          name: model.name,
          description: model.description,
          template_code: model.template_code,
          asset_codes: model.asset_codes,
          parameters: params,
          rebalance_frequency: model.rebalance_frequency,
          enable_momentum_selection: model.enable_momentum_selection,
          selector_type: model.selector_type || '',
          asset_selection_count: model.asset_selection_count ?? 1,
          min_history_days: model.min_history_days ?? 260,
          momentum_windows: model.momentum_windows || '20,60,120,250',
          smom_windows: model.smom_windows || model.momentum_windows || '20,60,120,250',
          tie_break_window: model.tie_break_window ?? 22
        };
        if (model.enable_momentum_selection && model.selector_type === 'hybrid') {
          updateData.macd_windows = model.macd_windows || '40,80,120,160';
        }
        await this.$store.dispatch('strategy/updateStrategyModel', { modelId: strategyId, data: updateData });
        this.$message.success(`策略「${strategy && strategy.name ? strategy.name : strategyId}」调仓配置已同步`);
        this.saveOriginalManualValues();
      } catch (e) {
        console.error('同步策略调仓配置失败:', e);
        this.$message.error('同步失败：' + (e.response?.data?.detail || e.message || '未知错误'));
        throw e;
      }
    },
    /** 同步所有已修改的主观策略 */
    async syncAllModifiedStrategies() {
      if (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) {
        const id = Array.isArray(this.form.strategy_ids) ? this.form.strategy_ids[0] : this.form.strategy_ids;
        if (id) {
          const s = this.strategyList.find(r => r.id === id);
          await this.syncManualAdjustmentsToStrategy(id, s);
        }
      } else if (this.form.backtest_mode === 'multi') {
        for (const s of this.selectedStrategiesWithManual || []) {
          await this.syncManualAdjustmentsToStrategy(s.id, s);
        }
      }
    },
    syncConfirmChoose(choice) {
      if (this.syncConfirmDialog.resolve) {
        this.syncConfirmDialog.resolve(choice);
        this.syncConfirmDialog.resolve = null;
      }
      if (choice === 'syncAndRun') {
        this.syncConfirmDialog.loading = true;
      } else {
        this.syncConfirmDialog.visible = false;
        this.syncConfirmDialog.loading = false;
      }
    },
    onSyncConfirmDialogClose() {
      if (this.syncConfirmDialog.resolve) {
        this.syncConfirmDialog.resolve('cancel');
        this.syncConfirmDialog.resolve = null;
      }
      this.syncConfirmDialog.loading = false;
    },
    handleStrategyChange() {
      // 策略选择变化时的处理
      if (this.form.backtest_mode === 'multi') {
        // 确保 strategy_ids 是数组
        if (!Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids ? [this.form.strategy_ids] : [];
        }
        
        // 限制最多选择5个策略
        if (this.form.strategy_ids && this.form.strategy_ids.length > 5) {
          this.$message.warning('多策略对比最多选择5个策略，已自动保留前5个');
          this.form.strategy_ids = this.form.strategy_ids.slice(0, 5);
        }
      } else {
        // 单策略模式：确保 strategy_ids 是单个值
        if (Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids.length > 0 ? this.form.strategy_ids[0] : null;
        }
      }
      this.updateSelectedStrategyInfo();
    },
    async updateSelectedStrategyInfo() {
      // 更新选中的策略信息（用于显示资产池和参数等）
      let strategyId = null;
      
      if (this.form.backtest_mode === 'single') {
        // 单策略模式
        strategyId = Array.isArray(this.form.strategy_ids) 
          ? (this.form.strategy_ids.length > 0 ? this.form.strategy_ids[0] : null)
          : this.form.strategy_ids;
      } else {
        // 多策略模式显示第一个策略的信息
        if (this.form.strategy_ids && Array.isArray(this.form.strategy_ids) && this.form.strategy_ids.length > 0) {
          strategyId = this.form.strategy_ids[0];
        }
      }
      
      if (strategyId) {
        // 先从列表中查找
        const strategy = this.strategyList.find(s => s.id === strategyId);
        const code = strategy && (strategy.template_code || '').toString();
        const isManual = code === 'manual_allocation' || code === 'manual_allocation_strategy'
          || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
        const hasManualWeights = strategy && strategy.parameters && typeof strategy.parameters.manual_weights === 'object' && strategy.parameters.manual_weights !== null;
        // 列表信息不完整，或为主观配置策略时拉取完整策略（保证权重初始化与预设调仓日能带出）
        const needFull = strategy && (
          !strategy.parameters ||
          !strategy.parameter_labels ||
          isManual
        );
        if (needFull) {
          try {
            const fullStrategy = await this.$store.dispatch('strategy/fetchStrategyModel', strategyId);
            this.selectedStrategyInfo = fullStrategy;
            this.initSelectionParams(fullStrategy);
          } catch (error) {
            console.error('获取策略详情失败:', error);
            this.selectedStrategyInfo = strategy;
            this.initSelectionParams(strategy);
          }
        } else {
          this.selectedStrategyInfo = strategy;
          this.initSelectionParams(strategy);
        }
      } else {
        this.selectedStrategyInfo = null;
      }

      // 波动率阈值重置：若已选策略模型配置过，则表单默认使用模型配置值（单策略用该策略，多策略用第一个策略）
      this.applyVolResetDefaultsFromStrategy(this.selectedStrategyInfo);

      // 主观配置策略：同步权重初始化到本次回测表单
      this.syncRunManualWeights();

      // 单策略主观：从策略预设加载调仓日与权重（若有）
      if (this.form.backtest_mode === 'single' && strategyId && this.isManualAllocationStrategy) {
        this.initManualWeightAdjustmentsFromStrategy();
      }

      // 多策略模式：初始化所有策略的选择器参数
      if (this.form.backtest_mode === 'multi') {
        this.initMultiStrategySelectionParams();
      }
    },
    /** 从模型带出权重初始化到 form.run_manual_weights，供本次回测使用或覆盖 */
    syncRunManualWeights() {
      const codes = (this.selectedStrategyInfo && this.selectedStrategyInfo.asset_codes) || [];
      const fromModel = this.modelManualWeights;
      const run = {};
      codes.forEach(c => {
        run[c] = (fromModel[c] !== undefined && fromModel[c] !== null) ? Number(fromModel[c]) : 0;
      });
      if (codes.length > 0 && Object.values(run).every(v => !v || v === 0)) {
        run[codes[0]] = 1;
      }
      this.form.run_manual_weights = run;
    },
    /** 格式化回测 snapshot 的 time 为 YYYY-MM-DD */
    formatSnapshotDate(t) {
      if (!t) return '';
      return dayjs(t).format('YYYY-MM-DD');
    },
    /** 波动率重置决策：首次回测后发现重置日，打开对话框 */
    openVolResetDecisionDialog(strategyId, strategy, backtestData, firstRunResult, volResetSnapshots) {
      const assetCodes = strategy.asset_codes || [];
      this.volResetDecisionDialog.strategyId = strategyId;
      this.volResetDecisionDialog.strategy = strategy;
      this.volResetDecisionDialog.backtestData = backtestData;
      this.volResetDecisionDialog.firstRunResult = firstRunResult;
      this.volResetDecisionDialog.points = volResetSnapshots.map(s => {
        const dateStr = this.formatSnapshotDate(s.time);
        const autoWeights = s.weights || {};
        const manualWeights = {};
        assetCodes.forEach(c => { manualWeights[c] = autoWeights[c] !== undefined ? Number(autoWeights[c]) : 0; });
        return { dateStr, autoWeights, useAuto: true, manualWeights };
      });
      this.volResetDecisionDialog.visible = true;
      this.volResetDecisionDialog.loading = false;
    },
    /** 对话框关闭：使用首次回测结果作为最终结果 */
    onVolResetDialogClose() {
      if (this.volResetDecisionDialog.firstRunResult && this.volResetDecisionDialog.strategy) {
        const first = this.volResetDecisionDialog.firstRunResult;
        this.backtestModelId = this.volResetDecisionDialog.strategyId;
        this.backtestResults = {
          [this.volResetDecisionDialog.strategy.name]: {
            result: first,
            strategy: this.volResetDecisionDialog.strategy,
            record_id: first.record_id != null ? String(first.record_id) : null,
            remark: first.remark != null ? first.remark : ''
          }
        };
        this.$nextTick(() => {
          const el = document.querySelector('.backtest-result');
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      }
      this.volResetDecisionDialog.visible = false;
      this.volResetDecisionDialog.points = [];
      this.volResetDecisionDialog.strategyId = null;
      this.volResetDecisionDialog.strategy = null;
      this.volResetDecisionDialog.backtestData = null;
      this.volResetDecisionDialog.firstRunResult = null;
    },
    /** 波动率重置决策：某条目的权重和（用于展示） */
    getVolResetPointWeightSum(pt) {
      if (!pt || !pt.manualWeights) return null;
      return Object.values(pt.manualWeights).reduce((s, v) => s + (Number(v) || 0), 0);
    },
    /** 确认人工干预选择并重新回测 */
    async confirmVolResetAndRerun() {
      const dialog = this.volResetDecisionDialog;
      const manualPoints = dialog.points.filter(p => !p.useAuto);
      const hasInvalid = manualPoints.some(p => {
        const sum = this.getVolResetPointWeightSum(p);
        return sum === null || sum <= 0;
      });
      if (hasInvalid) {
        this.$message.warning('选择「人工设定重置权重」的日期，权重和必须大于 0');
        return;
      }

      const manual_weight_adjustments = dialog.points
        .filter(p => !p.useAuto)
        .map(p => ({
          date: p.dateStr.replace(/-/g, '').slice(0, 8),
          weights: { ...(p.manualWeights || {}) },
          auto_normalize: false
        }));

      dialog.loading = true;
      try {
        const backtestData = { ...dialog.backtestData };
        if (manual_weight_adjustments.length > 0) {
          backtestData.manual_weight_adjustments = manual_weight_adjustments;
        }
        const result = await this.$store.dispatch('strategy/runBacktest', {
          modelId: dialog.strategyId,
          data: backtestData
        });
        const resultData = (result && result.data !== undefined) ? result.data : result;
        this.backtestModelId = dialog.strategyId;
        this.backtestResults = {
          [dialog.strategy.name]: {
            result: resultData,
            strategy: dialog.strategy,
            remark: resultData.remark != null ? resultData.remark : '',
            record_id: resultData.record_id != null ? String(resultData.record_id) : resultData.record_id
          }
        };
        this.$message.success('已按您的选择重新回测完成');
        this.volResetDecisionDialog.visible = false;
        this.volResetDecisionDialog.points = [];
        this.volResetDecisionDialog.strategyId = null;
        this.volResetDecisionDialog.strategy = null;
        this.volResetDecisionDialog.backtestData = null;
        this.volResetDecisionDialog.firstRunResult = null;
        this.$nextTick(() => {
          const el = document.querySelector('.backtest-result');
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      } catch (error) {
        this.$message.error('重新回测失败：' + (error.response?.data?.detail || error.message));
      } finally {
        dialog.loading = false;
      }
    },
    formatPresetDate(ymd) {
      if (!ymd || ymd.length < 8) return ymd;
      return `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}`;
    },
    formatPercent(v) {
      if (v == null || v === undefined) return '-';
      const p = Number(v);
      if (Number.isNaN(p)) return '-';
      return (p * 100).toFixed(2) + '%';
    },
    formatMetric(v) {
      if (v == null || v === undefined) return '-';
      const n = Number(v);
      if (Number.isNaN(n)) return '-';
      return n.toFixed(2);
    },
    formatNav(v) {
      if (v == null || v === undefined) return '-';
      const n = Number(v);
      if (Number.isNaN(n)) return '-';
      return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    onPresetStepDialogClose() {
      this.presetStepDialog.visible = false;
      this.presetStepDialog.stepResponse = null;
      this.presetStepDialog.strategyId = null;
      this.presetStepDialog.otherStrategiesMetrics = [];
      this.presetStepDialog.strategy = null;
      this.presetStepDialog.backtestData = null;
      if (Object.keys(this.multiManualPending || {}).length > 0) {
        this.multiManualPending = {};
        this.executing = false;
      }
    },
    /** 多策略步进时：拉取其他策略截至当前调仓日（endDateYyyymmdd）的指标，用于对比参考；包含正在执行的主观策略（multiManualPending）与已完成策略（backtestResults） */
    async fetchOtherStrategiesMetricsForStep(currentStrategyId, endDateYyyymmdd) {
      const ids = Array.isArray(this.form.strategy_ids) ? this.form.strategy_ids : (this.form.strategy_ids ? [this.form.strategy_ids] : []);
      const currentKey = String(currentStrategyId);
      const others = ids.filter(id => String(id) !== currentKey);
      if (others.length === 0) {
        this.presetStepDialog.otherStrategiesMetrics = [];
        this.presetStepDialog.loading = false;
        return;
      }
      const metricsList = [];
      const pending = this.multiManualPending || {};
      const completedResults = this.backtestResults && typeof this.backtestResults === 'object' ? this.backtestResults : {};
      for (const oid of others) {
        const oidKey = String(oid);
        const strategy = this.strategyList.find(s => String(s.id) === oidKey || s.id === oid);
        if (!strategy) continue;
        const strategyName = strategy.name || oidKey;
        if (pending[oidKey] && pending[oidKey].stepResponse) {
          const entry = pending[oidKey];
          const stepResponse = entry.stepResponse;
          const snapshots = (stepResponse.snapshots && Array.isArray(stepResponse.snapshots)) ? stepResponse.snapshots : [];
          const lastSnap = snapshots.length ? snapshots[snapshots.length - 1] : null;
          const lastDateStr = lastSnap ? (typeof lastSnap.time === 'string' ? lastSnap.time.replace(/-/g, '').slice(0, 8) : (lastSnap.time && lastSnap.time.toString && lastSnap.time.toString().replace(/-/g, '').slice(0, 8))) : '';
          const start = (this.form.date_range && this.form.date_range[0]) ? this.form.date_range[0].replace(/-/g, '') : '';
          const freqMapping = { '每日': 'daily', '每周': 'weekly', '每月': 'monthly', '每季度': 'quarterly', '每年': 'yearly', daily: 'daily', weekly: 'weekly', monthly: 'monthly', quarterly: 'quarterly', yearly: 'yearly' };
          const rebalanceFreq = freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly';
          const baseData = {
            start_date: start,
            end_date: endDateYyyymmdd,
            initial_cash: this.form.initial_cash,
            rebalance_freq: rebalanceFreq,
            commission_rate: this.form.commission_rate,
            slippage: this.form.slippage,
            lookback_days: 252,
            enable_vol_reset: this.form.enable_vol_reset,
            vol_reset_threshold: this.form.vol_reset_threshold
          };
          const needExtendPending = endDateYyyymmdd && lastDateStr && lastDateStr < endDateYyyymmdd && stepResponse.state && typeof stepResponse.state === 'object';
          const hasSnapshotsCoveringDate = endDateYyyymmdd && lastDateStr && lastDateStr >= endDateYyyymmdd;
          try {
            let dataAsOfDate = null;
            if (needExtendPending) {
              const extendPayload = {
                ...baseData,
                step_phase: 'continue',
                step_state: { state: stepResponse.state, remaining_preset_dates: [] },
                accumulated_snapshots: snapshots.map(s => ({
                  time: s.time,
                  total_value: s.total_value,
                  cash: s.cash,
                  holdings_value: s.holdings_value,
                  weights: (s.weights && typeof s.weights === 'object') ? s.weights : {},
                  is_rebalance_day: s.is_rebalance_day,
                  rebalance_type: s.rebalance_type,
                  rebalance_reason: s.rebalance_reason,
                  portfolio_volatility: s.portfolio_volatility,
                  monitoring_metrics: s.monitoring_metrics || {}
                })),
                accumulated_trades: (stepResponse.trades && Array.isArray(stepResponse.trades)) ? stepResponse.trades.map(t => ({
                  time: t.time,
                  thscode: t.thscode,
                  side: t.side,
                  quantity: t.quantity,
                  price: t.price,
                  commission: t.commission,
                  slippage_cost: t.slippage_cost
                })) : []
              };
              const extendResult = await this.$store.dispatch('strategy/runBacktest', { modelId: oidKey, data: extendPayload });
              dataAsOfDate = (extendResult && extendResult.data !== undefined) ? extendResult.data : extendResult;
            } else if (hasSnapshotsCoveringDate) {
              const metricsRes = await computeMetricsFromSnapshots(snapshots, endDateYyyymmdd);
              dataAsOfDate = (metricsRes && metricsRes.data !== undefined) ? metricsRes.data : metricsRes;
            } else {
              const runToDatePayload = { ...baseData, step_phase: 'run_to_date', run_to_date: endDateYyyymmdd };
              const runResult = await this.$store.dispatch('strategy/runBacktest', { modelId: oidKey, data: runToDatePayload });
              dataAsOfDate = (runResult && runResult.data !== undefined) ? runResult.data : runResult;
            }
            if (dataAsOfDate && !dataAsOfDate.phase) {
              metricsList.push({
                strategyId: oidKey,
                strategyName: (entry.strategy && entry.strategy.name) || strategyName,
                total_return: dataAsOfDate.total_return,
                annual_return: dataAsOfDate.annual_return,
                volatility: dataAsOfDate.volatility,
                max_drawdown: dataAsOfDate.max_drawdown,
                sharpe_ratio: dataAsOfDate.sharpe_ratio,
                calmar_ratio: dataAsOfDate.calmar_ratio
              });
            } else {
              const m = stepResponse.current_metrics || {};
              metricsList.push({
                strategyId: oidKey,
                strategyName: (entry.strategy && entry.strategy.name) || strategyName,
                total_return: m.total_return,
                annual_return: m.annual_return,
                volatility: m.volatility,
                max_drawdown: m.max_drawdown,
                sharpe_ratio: m.sharpe_ratio,
                calmar_ratio: m.calmar_ratio
              });
            }
          } catch (err) {
            console.warn('其他策略截至调仓日指标拉取失败，使用原暂停指标:', oidKey, err);
            const m = stepResponse.current_metrics || {};
            metricsList.push({
              strategyId: oidKey,
              strategyName: (entry.strategy && entry.strategy.name) || strategyName,
              total_return: m.total_return,
              annual_return: m.annual_return,
              volatility: m.volatility,
              max_drawdown: m.max_drawdown,
              sharpe_ratio: m.sharpe_ratio,
              calmar_ratio: m.calmar_ratio
            });
          }
          continue;
        }
        const completedEntry = completedResults[oidKey] || completedResults[strategyName];
        if (completedEntry && completedEntry.result && !completedEntry.result.phase) {
          const r = completedEntry.result;
          const snapshots = (r.snapshots && Array.isArray(r.snapshots)) ? r.snapshots : [];
          const lastSnap = snapshots.length ? snapshots[snapshots.length - 1] : null;
          const lastDateStr = lastSnap ? (typeof lastSnap.time === 'string' ? lastSnap.time.replace(/-/g, '').slice(0, 8) : (lastSnap.time && lastSnap.time.toString && lastSnap.time.toString().replace(/-/g, '').slice(0, 8))) : '';
          const hasState = completedEntry.step_state_at_end && completedEntry.step_state_at_end.state && typeof completedEntry.step_state_at_end.state === 'object';
          const needExtend = endDateYyyymmdd && lastDateStr && lastDateStr < endDateYyyymmdd && hasState;
          if (needExtend) {
            try {
              const start = (this.form.date_range && this.form.date_range[0]) ? this.form.date_range[0].replace(/-/g, '') : '';
              const freqMapping = { '每日': 'daily', '每周': 'weekly', '每月': 'monthly', '每季度': 'quarterly', '每年': 'yearly', daily: 'daily', weekly: 'weekly', monthly: 'monthly', quarterly: 'quarterly', yearly: 'yearly' };
              const rebalanceFreq = freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly';
              const baseData = {
                start_date: start,
                end_date: endDateYyyymmdd,
                initial_cash: this.form.initial_cash,
                rebalance_freq: rebalanceFreq,
                commission_rate: this.form.commission_rate,
                slippage: this.form.slippage,
                lookback_days: 252,
                enable_vol_reset: this.form.enable_vol_reset,
                vol_reset_threshold: this.form.vol_reset_threshold
              };
              const extendPayload = {
                ...baseData,
                step_phase: 'continue',
                step_state: completedEntry.step_state_at_end,
                accumulated_snapshots: snapshots.map(s => ({
                  time: s.time,
                  total_value: s.total_value,
                  cash: s.cash,
                  holdings_value: s.holdings_value,
                  weights: (s.weights && typeof s.weights === 'object') ? s.weights : {},
                  is_rebalance_day: s.is_rebalance_day,
                  rebalance_type: s.rebalance_type,
                  rebalance_reason: s.rebalance_reason,
                  portfolio_volatility: s.portfolio_volatility,
                  monitoring_metrics: s.monitoring_metrics || {}
                })),
                accumulated_trades: (r.trades && Array.isArray(r.trades)) ? r.trades.map(t => ({
                  time: t.time,
                  thscode: t.thscode,
                  side: t.side,
                  quantity: t.quantity,
                  price: t.price,
                  commission: t.commission,
                  slippage_cost: t.slippage_cost
                })) : []
              };
              const extendResult = await this.$store.dispatch('strategy/runBacktest', { modelId: oidKey, data: extendPayload });
              const extendData = (extendResult && extendResult.data !== undefined) ? extendResult.data : extendResult;
              if (extendData && !extendData.phase) {
                metricsList.push({
                  strategyId: oidKey,
                  strategyName: (completedEntry.strategy && completedEntry.strategy.name) || strategyName,
                  total_return: extendData.total_return,
                  annual_return: extendData.annual_return,
                  volatility: extendData.volatility,
                  max_drawdown: extendData.max_drawdown,
                  sharpe_ratio: extendData.sharpe_ratio,
                  calmar_ratio: extendData.calmar_ratio
                });
              } else {
                metricsList.push({
                  strategyId: oidKey,
                  strategyName: (completedEntry.strategy && completedEntry.strategy.name) || strategyName,
                  total_return: r.total_return,
                  annual_return: r.annual_return,
                  volatility: r.volatility,
                  max_drawdown: r.max_drawdown,
                  sharpe_ratio: r.sharpe_ratio,
                  calmar_ratio: r.calmar_ratio
                });
              }
            } catch (err) {
              console.warn('延续已完成策略至对比日失败，使用原结果指标:', oidKey, err);
              metricsList.push({
                strategyId: oidKey,
                strategyName: (completedEntry.strategy && completedEntry.strategy.name) || strategyName,
                total_return: r.total_return,
                annual_return: r.annual_return,
                volatility: r.volatility,
                max_drawdown: r.max_drawdown,
                sharpe_ratio: r.sharpe_ratio,
                calmar_ratio: r.calmar_ratio
              });
            }
            continue;
          }
          if (endDateYyyymmdd && lastDateStr && lastDateStr > endDateYyyymmdd) {
            try {
              const isManual = completedEntry.strategy && ((completedEntry.strategy.template_code || '').toString().toLowerCase().includes('manual'));
              if (isManual && snapshots.length > 0) {
                const metricsRes = await computeMetricsFromSnapshots(snapshots, endDateYyyymmdd);
                const dataAsOf = (metricsRes && metricsRes.data !== undefined) ? metricsRes.data : metricsRes;
                if (dataAsOf && typeof dataAsOf === 'object') {
                  metricsList.push({
                    strategyId: oidKey,
                    strategyName: (completedEntry.strategy && completedEntry.strategy.name) || strategyName,
                    total_return: dataAsOf.total_return,
                    annual_return: dataAsOf.annual_return,
                    volatility: dataAsOf.volatility,
                    max_drawdown: dataAsOf.max_drawdown,
                    sharpe_ratio: dataAsOf.sharpe_ratio,
                    calmar_ratio: dataAsOf.calmar_ratio
                  });
                  continue;
                }
              }
              const start = (this.form.date_range && this.form.date_range[0]) ? this.form.date_range[0].replace(/-/g, '') : '';
              const freqMapping = { '每日': 'daily', '每周': 'weekly', '每月': 'monthly', '每季度': 'quarterly', '每年': 'yearly', daily: 'daily', weekly: 'weekly', monthly: 'monthly', quarterly: 'quarterly', yearly: 'yearly' };
              const rebalanceFreq = freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly';
              const baseData = {
                start_date: start,
                end_date: endDateYyyymmdd,
                initial_cash: this.form.initial_cash,
                rebalance_freq: rebalanceFreq,
                commission_rate: this.form.commission_rate,
                slippage: this.form.slippage,
                lookback_days: 252,
                enable_vol_reset: this.form.enable_vol_reset,
                vol_reset_threshold: this.form.vol_reset_threshold
              };
              const runPayload = { ...baseData };
              if (isManual) {
                runPayload.step_phase = 'run_to_date';
                runPayload.run_to_date = endDateYyyymmdd;
              }
              if (strategy.enable_momentum_selection) {
                runPayload.enable_momentum_selection = true;
                runPayload.asset_selection_count = strategy.asset_selection_count || 8;
                const sp = this.form.multiStrategySelectionParams && this.form.multiStrategySelectionParams[oid];
                if (sp) {
                  runPayload.selector_type = sp.selector_type;
                  runPayload.momentum_windows = sp.momentum_windows;
                  runPayload.smom_windows = sp.smom_windows || sp.momentum_windows || '20,60,120,250';
                  if (sp.selector_type === 'hybrid') {
                    runPayload.macd_windows = sp.macd_windows || '40,80,120,160';
                    runPayload.reversal_windows = sp.reversal_windows || '10,22';
                  }
                } else {
                  runPayload.selector_type = strategy.selector_type || 'momentum';
                  runPayload.momentum_windows = strategy.momentum_windows || '20,60,120,250';
                  runPayload.smom_windows = strategy.smom_windows || strategy.momentum_windows || '20,60,120,250';
                  if ((strategy.selector_type || '') === 'hybrid') {
                    runPayload.macd_windows = strategy.macd_windows || '40,80,120,160';
                    runPayload.reversal_windows = strategy.reversal_windows || '10,22';
                  }
                }
              }
              const runResult = await this.$store.dispatch('strategy/runBacktest', { modelId: oidKey, data: runPayload });
              const dataAsOf = (runResult && runResult.data !== undefined) ? runResult.data : runResult;
              if (dataAsOf && !dataAsOf.phase) {
                metricsList.push({
                  strategyId: oidKey,
                  strategyName: (completedEntry.strategy && completedEntry.strategy.name) || strategyName,
                  total_return: dataAsOf.total_return,
                  annual_return: dataAsOf.annual_return,
                  volatility: dataAsOf.volatility,
                  max_drawdown: dataAsOf.max_drawdown,
                  sharpe_ratio: dataAsOf.sharpe_ratio,
                  calmar_ratio: dataAsOf.calmar_ratio
                });
              } else {
                metricsList.push({
                  strategyId: oidKey,
                  strategyName: (completedEntry.strategy && completedEntry.strategy.name) || strategyName,
                  total_return: r.total_return,
                  annual_return: r.annual_return,
                  volatility: r.volatility,
                  max_drawdown: r.max_drawdown,
                  sharpe_ratio: r.sharpe_ratio,
                  calmar_ratio: r.calmar_ratio
                });
              }
            } catch (e) {
              console.warn('按当前调仓日重算已完成策略绩效失败，使用原指标:', oidKey, e);
              metricsList.push({
                strategyId: oidKey,
                strategyName: (completedEntry.strategy && completedEntry.strategy.name) || strategyName,
                total_return: r.total_return,
                annual_return: r.annual_return,
                volatility: r.volatility,
                max_drawdown: r.max_drawdown,
                sharpe_ratio: r.sharpe_ratio,
                calmar_ratio: r.calmar_ratio
              });
            }
            continue;
          }
          metricsList.push({
            strategyId: oidKey,
            strategyName: (completedEntry.strategy && completedEntry.strategy.name) || strategyName,
            total_return: r.total_return,
            annual_return: r.annual_return,
            volatility: r.volatility,
            max_drawdown: r.max_drawdown,
            sharpe_ratio: r.sharpe_ratio,
            calmar_ratio: r.calmar_ratio
          });
          continue;
        }
        const start = (this.form.date_range && this.form.date_range[0]) ? this.form.date_range[0].replace(/-/g, '') : '';
        const freqMapping = { '每日': 'daily', '每周': 'weekly', '每月': 'monthly', '每季度': 'quarterly', '每年': 'yearly', daily: 'daily', weekly: 'weekly', monthly: 'monthly', quarterly: 'quarterly', yearly: 'yearly' };
        const rebalanceFreq = freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly';
        const baseData = {
          start_date: start,
          end_date: endDateYyyymmdd,
          initial_cash: this.form.initial_cash,
          rebalance_freq: rebalanceFreq,
          commission_rate: this.form.commission_rate,
          slippage: this.form.slippage,
          lookback_days: 252,
          enable_vol_reset: this.form.enable_vol_reset,
          vol_reset_threshold: this.form.vol_reset_threshold
        };
        if (this.form.run_max_leverage != null && this.form.run_max_leverage !== '' && !Number.isNaN(Number(this.form.run_max_leverage))) {
          const lev = Number(this.form.run_max_leverage);
          if (lev >= 1) baseData.max_leverage = lev;
        }
        const backtestData = { ...baseData };
        if (strategy.enable_momentum_selection) {
          backtestData.enable_momentum_selection = true;
          backtestData.asset_selection_count = strategy.asset_selection_count || 8;
          const sp = this.form.multiStrategySelectionParams && this.form.multiStrategySelectionParams[oid];
          if (sp) {
            backtestData.selector_type = sp.selector_type;
            backtestData.momentum_windows = sp.momentum_windows;
            backtestData.smom_windows = sp.smom_windows || sp.momentum_windows || '20,60,120,250';
            if (sp.selector_type === 'hybrid') {
              backtestData.macd_windows = sp.macd_windows || '40,80,120,160';
              backtestData.reversal_windows = sp.reversal_windows || '10,22';
            }
          } else {
            backtestData.selector_type = strategy.selector_type || 'momentum';
            backtestData.momentum_windows = strategy.momentum_windows || '20,60,120,250';
            backtestData.smom_windows = strategy.smom_windows || strategy.momentum_windows || '20,60,120,250';
            if ((strategy.selector_type || '') === 'hybrid') {
              backtestData.macd_windows = strategy.macd_windows || '40,80,120,160';
              backtestData.reversal_windows = strategy.reversal_windows || '10,22';
            }
          }
        }
        try {
          const result = await this.$store.dispatch('strategy/runBacktest', { modelId: oid, data: backtestData });
          const data = (result && result.data !== undefined) ? result.data : result;
          if (data && !data.phase) {
            metricsList.push({
              strategyId: oid,
              strategyName: strategy.name || oid,
              total_return: data.total_return,
              annual_return: data.annual_return,
              volatility: data.volatility,
              max_drawdown: data.max_drawdown,
              sharpe_ratio: data.sharpe_ratio,
              calmar_ratio: data.calmar_ratio
            });
          }
        } catch (e) {
          console.warn('其他策略截至日指标拉取失败:', oid, e);
        }
      }
      if (String(this.presetStepDialog.strategyId) === currentKey && this.presetStepDialog.visible) {
        this.presetStepDialog.otherStrategiesMetrics = metricsList;
      }
      this.presetStepDialog.loading = false;
    },
    /** 从 multiManualPending 中选出 next_preset_date 最小的一个（按时间线顺序步进） */
    pickNextMultiManualStep() {
      const pending = this.multiManualPending;
      if (!pending || Object.keys(pending).length === 0) return null;
      let minDate = null;
      let chosenId = null;
      for (const [id, entry] of Object.entries(pending)) {
        const d = entry.stepResponse && entry.stepResponse.next_preset_date;
        if (!d) continue;
        const ds = String(d);
        if (minDate == null || ds < minDate) {
          minDate = ds;
          chosenId = id;
        }
      }
      if (chosenId == null) return null;
      return pending[chosenId];
    },
    /** 用指定 entry 填充并打开预设调仓日步进对话框（多主观策略按时间线顺序） */
    openPresetStepDialogForEntry(entry) {
      const d = this.presetStepDialog;
      d.strategyId = entry.strategyId;
      d.strategy = entry.strategy;
      d.backtestData = { ...entry.backtestData };
      d.stepResponse = entry.stepResponse;
      const adjustmentsList = (this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[entry.strategyId]) || [];
      const presetForDate = adjustmentsList.find(adj => (adj.date || '').replace(/-/g, '').slice(0, 8) === (entry.stepResponse.next_preset_date || ''));
      const codes = (entry.strategy.asset_codes || []);
      const hasPreset = presetForDate && presetForDate.weights && Object.keys(presetForDate.weights).length > 0;
      if (hasPreset) {
        d.customWeights = codes.reduce((o, c) => ({ ...o, [c]: Number(presetForDate.weights[c]) || 0 }), {});
      } else {
        d.customWeights = codes.reduce((o, c) => ({ ...o, [c]: 0 }), {});
        if (codes.length) d.customWeights[codes[0]] = 1;
      }
      d.autoNormalize = presetForDate ? presetForDate.auto_normalize === true : false;
      // 主观策略步进：统一按预设权重调仓，不展示选项
      d.decision = hasPreset ? 'use_preset' : 'custom';
      d.otherStrategiesMetrics = [];
      d.visible = true;
      d.loading = !!entry.stepResponse.next_preset_date;
      if (entry.stepResponse.next_preset_date) {
        this.fetchOtherStrategiesMetricsForStep(entry.strategyId, entry.stepResponse.next_preset_date);
      } else {
        d.loading = false;
      }
    },
    async confirmPresetStepAndContinue() {
      const d = this.presetStepDialog;
      if (!d.stepResponse || !d.backtestData) return;
      // 主观策略步进：统一按预设权重调仓（有预设用 use_preset，无则用 custom+默认权重）
      const effectiveDecision = this.hasPresetWeightsForCurrentDate ? 'use_preset' : 'custom';
      if (effectiveDecision === 'custom') {
        const sum = this.presetStepCustomSum;
        if (sum === null || sum <= 0) {
          this.$message.warning('实时输入时权重和须大于 0');
          return;
        }
        const maxLev = this.getEffectiveMaxLeverage(d.strategy);
        if (sum > maxLev) {
          this.$message.warning(`总仓位权重不能超过最大杠杆 ${(maxLev * 100).toFixed(0)}%。当前步进调仓权重和 ${(sum * 100).toFixed(2)}%`);
          return;
        }
      }
      d.loading = true;
      try {
        const payload = { ...d.backtestData };
        payload.step_phase = 'continue';
        payload.step_state = {
          state: d.stepResponse.state,
          remaining_preset_dates: d.stepResponse.remaining_preset_dates || []
        };
        payload.preset_date_decision = {
          date: d.stepResponse.next_preset_date,
          action: effectiveDecision,
          auto_normalize: d.autoNormalize === true
        };
        if (effectiveDecision === 'custom') {
          payload.preset_date_decision.weights = { ...d.customWeights };
        } else if (effectiveDecision === 'use_preset') {
          const adjList = this.form.backtest_mode === 'multi' && d.strategyId
            ? (this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[d.strategyId]) || []
            : (this.form.manual_weight_adjustments || []);
          const preset = adjList.find(adj => (adj.date || '').replace(/-/g, '').slice(0, 8) === d.stepResponse.next_preset_date);
          if (preset && preset.weights && Object.keys(preset.weights).length > 0) {
            payload.preset_date_decision.weights = { ...preset.weights };
          }
        }
        payload.accumulated_snapshots = d.stepResponse.snapshots || [];
        payload.accumulated_trades = d.stepResponse.trades || [];
        const result = await this.$store.dispatch('strategy/runBacktest', {
          modelId: d.strategyId,
          data: payload
        });
        const resultData = (result && result.data !== undefined) ? result.data : result;
        if (resultData.phase === 'paused') {
          if (this.form.backtest_mode === 'multi' && this.multiManualPending && this.multiManualPending[d.strategyId] !== undefined) {
            const nextBacktestData = { ...payload };
            nextBacktestData.step_state = { state: resultData.state, remaining_preset_dates: resultData.remaining_preset_dates || [] };
            nextBacktestData.accumulated_snapshots = resultData.snapshots || [];
            nextBacktestData.accumulated_trades = resultData.trades || [];
            delete nextBacktestData.preset_date_decision;
            this.$set(this.multiManualPending, d.strategyId, {
              strategy: d.strategy,
              strategyId: d.strategyId,
              backtestData: nextBacktestData,
              stepResponse: resultData
            });
            const nextEntry = this.pickNextMultiManualStep();
            if (nextEntry) {
              this.openPresetStepDialogForEntry(nextEntry);
            }
            this.$message.success('已继续至下一调仓日');
          } else {
            d.stepResponse = resultData;
            const codes = (d.strategy && d.strategy.asset_codes) || [];
            const adjListNext = this.form.backtest_mode === 'multi' && d.strategyId
              ? (this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[d.strategyId]) || []
              : (this.form.manual_weight_adjustments || []);
            const presetForNext = adjListNext.find(adj => (adj.date || '').replace(/-/g, '').slice(0, 8) === (resultData.next_preset_date || ''));
            d.decision = (presetForNext && presetForNext.weights && Object.keys(presetForNext.weights).length > 0) ? 'use_preset' : 'custom';
            if (presetForNext && presetForNext.weights && Object.keys(presetForNext.weights).length > 0) {
              d.customWeights = codes.reduce((o, c) => ({ ...o, [c]: Number(presetForNext.weights[c]) || 0 }), {});
            } else {
              d.customWeights = codes.reduce((o, c) => ({ ...o, [c]: 0 }), {});
              if (codes.length) d.customWeights[codes[0]] = 1;
            }
            d.autoNormalize = presetForNext ? presetForNext.auto_normalize === true : false;
            d.otherStrategiesMetrics = [];
            if (this.form.backtest_mode === 'multi' && resultData.next_preset_date) {
              d.loading = true;
              this.fetchOtherStrategiesMetricsForStep(d.strategyId, resultData.next_preset_date);
            }
            this.$message.success('已继续至下一调仓日');
          }
        } else {
          let resultToStore = resultData;
          const backtestEndDate = (this.form.date_range && this.form.date_range[1]) ? this.form.date_range[1].replace(/-/g, '') : '';
          const snapshots = (resultData.snapshots && Array.isArray(resultData.snapshots)) ? resultData.snapshots : [];
          const lastSnap = snapshots.length ? snapshots[snapshots.length - 1] : null;
          const lastDateStr = lastSnap ? (typeof lastSnap.time === 'string' ? lastSnap.time.replace(/-/g, '').slice(0, 8) : (lastSnap.time && lastSnap.time.toString && lastSnap.time.toString().replace(/-/g, '').slice(0, 8))) : '';
          const hasState = resultData.step_state_at_end && resultData.step_state_at_end.state && typeof resultData.step_state_at_end.state === 'object';
          if (backtestEndDate && lastDateStr && lastDateStr < backtestEndDate && hasState) {
            try {
              const start = (this.form.date_range && this.form.date_range[0]) ? this.form.date_range[0].replace(/-/g, '') : '';
              const freqMapping = { '每日': 'daily', '每周': 'weekly', '每月': 'monthly', '每季度': 'quarterly', '每年': 'yearly', daily: 'daily', weekly: 'weekly', monthly: 'monthly', quarterly: 'quarterly', yearly: 'yearly' };
              const rebalanceFreq = freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly';
              const extendPayload = {
                start_date: start,
                end_date: backtestEndDate,
                initial_cash: this.form.initial_cash,
                rebalance_freq: rebalanceFreq,
                commission_rate: this.form.commission_rate,
                slippage: this.form.slippage,
                lookback_days: 252,
                enable_vol_reset: this.form.enable_vol_reset,
                vol_reset_threshold: this.form.vol_reset_threshold,
                step_phase: 'continue',
                step_state: resultData.step_state_at_end,
                accumulated_snapshots: snapshots.map(s => ({
                  time: s.time,
                  total_value: s.total_value,
                  cash: s.cash,
                  holdings_value: s.holdings_value,
                  weights: (s.weights && typeof s.weights === 'object') ? s.weights : {},
                  is_rebalance_day: s.is_rebalance_day,
                  rebalance_type: s.rebalance_type,
                  rebalance_reason: s.rebalance_reason,
                  portfolio_volatility: s.portfolio_volatility,
                  monitoring_metrics: s.monitoring_metrics || {}
                })),
                accumulated_trades: (resultData.trades && Array.isArray(resultData.trades)) ? resultData.trades.map(t => ({
                  time: t.time,
                  thscode: t.thscode,
                  side: t.side,
                  quantity: t.quantity,
                  price: t.price,
                  commission: t.commission,
                  slippage_cost: t.slippage_cost
                })) : []
              };
              const extendRes = await this.$store.dispatch('strategy/runBacktest', { modelId: d.strategyId, data: extendPayload });
              const extended = (extendRes && extendRes.data !== undefined) ? extendRes.data : extendRes;
              if (extended && !extended.phase) {
                resultToStore = { ...extended, record_id: resultData.record_id != null ? resultData.record_id : extended.record_id, remark: resultData.remark != null ? resultData.remark : (extended.remark || '') };
              }
            } catch (err) {
              console.warn('主观策略完成后延续至回测期末失败，使用最后调仓日结果:', d.strategyId, err);
            }
          }
          let recordId = resultData.record_id != null ? String(resultData.record_id) : (resultToStore && resultToStore.record_id != null ? String(resultToStore.record_id) : null);
          if (!recordId && d.strategyId) {
            try {
              const history = await this.$store.dispatch('strategy/fetchBacktestHistory', { modelId: d.strategyId, skip: 0, limit: 5 });
              const list = Array.isArray(history) ? history : (history && history.data) ? history.data : [];
              const latest = list[0];
              if (latest && (latest.id || latest._id)) {
                recordId = String(latest.id || latest._id);
                if (resultToStore && typeof resultToStore === 'object') resultToStore.record_id = recordId;
                console.log('[BacktestRecord] 主观策略步进完成 通过查询历史记录关联 record_id=', recordId);
              }
            } catch (e) {
              console.warn('[BacktestRecord] 主观策略步进完成 查询历史记录失败', e);
            }
          }
          const entry = {
            result: resultToStore,
            strategy: d.strategy,
            remark: (resultToStore && resultToStore.remark != null) ? resultToStore.remark : (resultData.remark != null ? resultData.remark : ''),
            record_id: recordId,
            step_state_at_end: resultData.step_state_at_end || null
          };
          if (this.form.backtest_mode === 'multi' && this.multiManualPending && this.multiManualPending[d.strategyId] !== undefined) {
            this.$delete(this.multiManualPending, d.strategyId);
            const manualResultKey = d.strategyId;
            if (this.backtestResults && typeof this.backtestResults === 'object') {
              this.backtestResults = { ...this.backtestResults, [manualResultKey]: entry };
            } else {
              this.backtestResults = { [manualResultKey]: entry };
            }
            const snapCount = (entry.result && entry.result.snapshots && Array.isArray(entry.result.snapshots)) ? entry.result.snapshots.length : 0;
            console.log('[多策略] 主观策略步进完成 已合并 key=', manualResultKey, 'strategyName=', d.strategy && d.strategy.name, 'snapshots=', snapCount, '当前总策略数=', Object.keys(this.backtestResults).length);
            const nextEntry = this.pickNextMultiManualStep();
            if (nextEntry) {
              this.openPresetStepDialogForEntry(nextEntry);
              this.$message.success(`「${d.strategy.name}」回测完成，请继续设置下一策略`);
            } else {
              this.presetStepDialog.visible = false;
              this.presetStepDialog.stepResponse = null;
              this.presetStepDialog.strategyId = null;
              this.presetStepDialog.strategy = null;
              this.presetStepDialog.backtestData = null;
              this.multiManualPending = {};
              this.$message.success('回测完成');
              this.$nextTick(() => {
                const el = document.querySelector('.backtest-result');
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
              });
            }
          } else {
            this.backtestModelId = d.strategyId;
            if (this.form.backtest_mode === 'multi' && this.backtestResults && typeof this.backtestResults === 'object') {
              this.backtestResults = { ...this.backtestResults, [d.strategyId]: entry };
            } else {
              this.backtestResults = { [d.strategyId]: entry };
            }
            console.log('[多策略] 主观策略步进完成(单策略或最后一策略) key=', d.strategyId, 'strategyName=', d.strategy && d.strategy.name);
            this.$message.success('回测完成');
            this.presetStepDialog.visible = false;
            this.presetStepDialog.stepResponse = null;
            this.presetStepDialog.strategyId = null;
            this.presetStepDialog.strategy = null;
            this.presetStepDialog.backtestData = null;
            this.$nextTick(() => {
              const el = document.querySelector('.backtest-result');
              if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
          }
        }
      } catch (error) {
        this.$message.error('继续回测失败：' + (error.response?.data?.detail || error.message));
      } finally {
        d.loading = false;
      }
    },
    /** 从策略模型的 parameters 中取 enable_vol_reset / vol_reset_threshold 作为回测表单默认值 */
    applyVolResetDefaultsFromStrategy(strategy) {
      if (!strategy || !strategy.parameters) return;
      const p = strategy.parameters;
      if (p.enable_vol_reset !== undefined && p.enable_vol_reset !== null) {
        this.form.enable_vol_reset = !!p.enable_vol_reset;
      }
      if (p.vol_reset_threshold !== undefined && p.vol_reset_threshold !== null) {
        const v = Number(p.vol_reset_threshold);
        if (!Number.isNaN(v) && v >= 0.01 && v <= 0.5) {
          this.form.vol_reset_threshold = v;
        }
      }
    },
    // 初始化单策略的选择器参数
    initSelectionParams(strategy) {
      if (!strategy) return;
      // 兼容处理：reversal/momentum_reversal 映射为 hybrid 以显示混合选择器参数
      const selectorType = strategy.selector_type || 'momentum';
      this.form.selector_type = (selectorType === 'reversal' || selectorType === 'momentum_reversal') ? 'hybrid' : selectorType;
      // 默认选择资产数量为资产池大小（或策略配置值）
      const poolSize = strategy.asset_codes?.length || 8;
      this.form.asset_selection_count = Math.min(strategy.asset_selection_count || poolSize, poolSize);
      this.form.momentum_windows = strategy.momentum_windows || '20,60,120,250';
      this.form.smom_windows = strategy.smom_windows || strategy.momentum_windows || '20,60,120,250';
      this.form.macd_windows = strategy.macd_windows || '40,80,120,160';
      this.form.reversal_windows = strategy.reversal_windows || '10,22';
      // 清空手动选择的资产
      this.form.selected_asset_codes = [];
      // 仅动量/量化策略拉取指数编制规则权重上限；主观策略不限制
      const code = (strategy.template_code || '').toString();
      const isManual = code === 'manual_allocation' || code === 'manual_allocation_strategy'
        || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
      if (!isManual && strategy.asset_codes && strategy.asset_codes.length > 0) {
        getMaxWeightsByCodes(strategy.asset_codes).then(res => {
          const data = (res && res.data && typeof res.data === 'object' && !Array.isArray(res.data)) ? res.data : {};
          this.maxWeightDict = data;
        }).catch(() => {
          this.maxWeightDict = {};
        });
      } else {
        this.maxWeightDict = {};
      }
    },
    // 判断资产是否被选中
    isAssetSelected(code) {
      return this.form.selected_asset_codes.includes(code);
    },
    // 切换资产选中状态
    toggleAssetSelection(code) {
      const idx = this.form.selected_asset_codes.indexOf(code);
      const maxCount = Number(this.form.asset_selection_count) || 1;
      
      if (idx >= 0) {
        // 已选中，取消选中
        this.form.selected_asset_codes.splice(idx, 1);
      } else {
        // 未选中
        if (this.form.selected_asset_codes.length >= maxCount) {
          this.$message.warning(`最多只能选择 ${maxCount} 个资产`);
          return;
        }
        this.form.selected_asset_codes.push(code);
      }
    },
    // 当「选择资产数量」变化时，清空已选资产（若已选数量超过新数量）
    onAssetSelectionCountChange(newCount) {
      if (this.form.selected_asset_codes.length > newCount) {
        this.form.selected_asset_codes = this.form.selected_asset_codes.slice(0, newCount);
        this.$message.info(`已自动调整为前 ${newCount} 个资产`);
      }
    },
    // ========== 多策略模式的资产选择方法 ==========
    // 获取指定策略的资产池（多策略模式）
    getStrategyAssetPool(strategyId) {
      const strategy = this.strategyList.find(s => s.id === strategyId);
      if (!strategy || !strategy.asset_codes) {
        return [];
      }
      return strategy.asset_codes.map(code => ({
        code,
        name: strategy.asset_names?.[code] || code
      }));
    },
    // 获取指定策略的资产池大小（多策略模式）
    getStrategyAssetPoolSize(strategyId) {
      const strategy = this.strategyList.find(s => s.id === strategyId);
      return strategy?.asset_codes?.length || 100;
    },
    // 判断多策略模式下指定资产是否被选中
    isMultiStrategyAssetSelected(strategyId, code) {
      const params = this.form.multiStrategySelectionParams[strategyId];
      if (!params || !params.selected_asset_codes) {
        return false;
      }
      return params.selected_asset_codes.includes(code);
    },
    // 切换多策略模式下指定资产的选中状态
    toggleMultiStrategyAssetSelection(strategyId, code) {
      if (!this.form.multiStrategySelectionParams[strategyId]) {
        this.$set(this.form.multiStrategySelectionParams, strategyId, {
          selected_asset_codes: []
        });
      }
      const params = this.form.multiStrategySelectionParams[strategyId];
      if (!params.selected_asset_codes) {
        this.$set(params, 'selected_asset_codes', []);
      }
      
      const idx = params.selected_asset_codes.indexOf(code);
      const maxCount = Number(params.asset_selection_count) || 1;
      
      if (idx >= 0) {
        // 已选中，取消选中
        params.selected_asset_codes.splice(idx, 1);
      } else {
        // 未选中
        if (params.selected_asset_codes.length >= maxCount) {
          this.$message.warning(`最多只能选择 ${maxCount} 个资产`);
          return;
        }
        params.selected_asset_codes.push(code);
      }
    },
    // 多策略模式下「选择资产数量」变化时的处理
    onMultiStrategyAssetSelectionCountChange(strategyId) {
      const params = this.form.multiStrategySelectionParams[strategyId];
      if (!params || !params.selected_asset_codes) {
        return;
      }
      const newCount = Number(params.asset_selection_count) || 0;
      if (params.selected_asset_codes.length > newCount) {
        params.selected_asset_codes = params.selected_asset_codes.slice(0, newCount);
        this.$message.info(`已自动调整为前 ${newCount} 个资产`);
      }
    },
    // 获取多策略模式下指定策略的已选资产数量
    getMultiStrategySelectedAssetCount(strategyId) {
      const params = this.form.multiStrategySelectionParams[strategyId];
      return params?.selected_asset_codes?.length || 0;
    },
    // 多策略模式下指定策略的已选资产数量是否匹配
    getMultiStrategySelectedAssetCountMatch(strategyId) {
      const params = this.form.multiStrategySelectionParams[strategyId];
      if (!params) return false;
      const selectedCount = params.selected_asset_codes?.length || 0;
      const expectedCount = Number(params.asset_selection_count) || 0;
      return selectedCount === expectedCount;
    },
    // 初始化多策略的选择器参数
    async initMultiStrategySelectionParams() {
      if (!this.form.multiStrategySelectionParams) {
        this.$set(this.form, 'multiStrategySelectionParams', {});
      }
      
      const selectedStrategies = this.selectedStrategies;
      
      // 为每个策略初始化选择器参数
      for (const strategy of selectedStrategies) {
        if (strategy.enable_momentum_selection) {
          // 如果策略信息不完整，尝试获取完整信息
          let fullStrategy = strategy;
          if (!strategy.selector_type && !strategy.asset_selection_count) {
            try {
              fullStrategy = await this.$store.dispatch('strategy/fetchStrategyModel', strategy.id);
            } catch (error) {
              console.error(`获取策略 ${strategy.id} 详情失败:`, error);
              // 使用列表中的信息
            }
          }
          
          // 初始化或更新该策略的选择器参数
          if (!this.form.multiStrategySelectionParams[strategy.id]) {
            // 兼容处理：reversal/momentum_reversal 映射为 hybrid 以显示混合选择器参数
            const selectorType = fullStrategy.selector_type || 'momentum';
            const normalizedSelectorType = (selectorType === 'reversal' || selectorType === 'momentum_reversal') ? 'hybrid' : selectorType;
            this.$set(this.form.multiStrategySelectionParams, strategy.id, {
              selector_type: normalizedSelectorType,
              asset_selection_count: Math.min(fullStrategy.asset_selection_count || 8, fullStrategy.asset_codes?.length || 8),
              momentum_windows: fullStrategy.momentum_windows || '20,60,120,250',
              smom_windows: fullStrategy.smom_windows || fullStrategy.momentum_windows || '20,60,120,250',
              macd_windows: fullStrategy.macd_windows || '40,80,120,160',
              reversal_windows: fullStrategy.reversal_windows || '10,22',
              selected_asset_codes: [] // 手动选择的资产代码列表
            });
          } else {
            // 如果参数已存在但可能不完整，更新缺失的字段
            const params = this.form.multiStrategySelectionParams[strategy.id];
            if (!params.selector_type) {
              // 兼容处理：reversal/momentum_reversal 映射为 hybrid
              const selectorType = fullStrategy.selector_type || 'momentum';
              params.selector_type = (selectorType === 'reversal' || selectorType === 'momentum_reversal') ? 'hybrid' : selectorType;
            }
            if (!params.asset_selection_count) {
              params.asset_selection_count = Math.min(fullStrategy.asset_selection_count || 8, fullStrategy.asset_codes?.length || 8);
            }
            if (!params.momentum_windows) params.momentum_windows = fullStrategy.momentum_windows || '20,60,120,250';
            if (!params.smom_windows) params.smom_windows = fullStrategy.smom_windows || fullStrategy.momentum_windows || '20,60,120,250';
            if (!params.macd_windows) params.macd_windows = fullStrategy.macd_windows || '40,80,120,160';
            if (!params.reversal_windows) params.reversal_windows = fullStrategy.reversal_windows || '10,22';
            // 确保 selected_asset_codes 存在
            if (!params.selected_asset_codes) {
              this.$set(params, 'selected_asset_codes', []);
            }
          }
        }
      }
      
      // 清理已取消选择的策略的参数
      Object.keys(this.form.multiStrategySelectionParams || {}).forEach(strategyId => {
        if (!selectedStrategies.find(s => s.id === strategyId)) {
          this.$delete(this.form.multiStrategySelectionParams, strategyId);
        }
      });
      Object.keys(this.form.multiStrategyManualAdjustments || {}).forEach(strategyId => {
        if (!selectedStrategies.find(s => s.id === strategyId)) {
          this.$delete(this.form.multiStrategyManualAdjustments, strategyId);
        }
      });
      Object.keys(this.form.multiStrategyRunManualWeights || {}).forEach(strategyId => {
        if (!selectedStrategies.find(s => s.id === strategyId)) {
          this.$delete(this.form.multiStrategyRunManualWeights, strategyId);
        }
      });
    },
    /** 主观策略时自检必填项，避免 el-form 对隐藏/动态表单项误报；返回 Promise<boolean> */
    validateManualStrategyForm() {
      return new Promise((resolve) => {
        this.$refs.form.clearValidate();
        const f = this.form;
        if (!f.strategy_ids && f.strategy_ids !== 0) {
          this.$message.warning('请选择策略');
          return resolve(false);
        }
        const nCash = Number(f.initial_cash);
        if (f.initial_cash === undefined || f.initial_cash === null || f.initial_cash === '' || !Number.isFinite(nCash) || nCash < 100000) {
          this.$message.warning('请输入初始资金（至少10万元）');
          return resolve(false);
        }
        if (!f.date_range || !Array.isArray(f.date_range) || f.date_range.length !== 2 || !f.date_range[0] || !f.date_range[1]) {
          this.$message.warning('请选择完整的回测时间范围');
          return resolve(false);
        }
        const nComm = Number(f.commission_rate);
        if (f.commission_rate === undefined || f.commission_rate === null || f.commission_rate === '' || !Number.isFinite(nComm) || nComm < 0) {
          this.$message.warning('请输入手续费率');
          return resolve(false);
        }
        const nSlip = Number(f.slippage);
        if (f.slippage === undefined || f.slippage === null || f.slippage === '' || !Number.isFinite(nSlip) || nSlip < 0) {
          this.$message.warning('请输入滑点');
          return resolve(false);
        }
        if (!f.manual_weight_adjustments || f.manual_weight_adjustments.length === 0) {
          this.$message.warning('主观策略需至少预设一个调仓日期（权重可留空，到该日再选择）');
          return resolve(false);
        }
        for (let i = 0; i < f.manual_weight_adjustments.length; i++) {
          if (!f.manual_weight_adjustments[i].date) {
            this.$message.warning(`调仓日 ${i + 1} 的日期不能为空`);
            return resolve(false);
          }
        }
        resolve(true);
      });
    },
    /** 多策略且含主观策略时自检必填项，避免 el-form 对预设调仓区块误报 */
    validateMultiStrategyWithManualForm() {
      return new Promise((resolve) => {
        if (this.$refs.form) this.$refs.form.clearValidate();
        const f = this.form;
        const ids = Array.isArray(f.strategy_ids) ? f.strategy_ids : (f.strategy_ids ? [f.strategy_ids] : []);
        if (ids.length < 2) {
          this.$message.warning('多策略对比请至少选择 2 个策略');
          return resolve(false);
        }
        if (ids.length > 5) {
          this.$message.warning('多策略对比最多选择 5 个策略');
          return resolve(false);
        }
        const nCash = Number(f.initial_cash);
        if (f.initial_cash === undefined || f.initial_cash === null || f.initial_cash === '' || !Number.isFinite(nCash) || nCash < 100000) {
          this.$message.warning('请输入初始资金（至少10万元）');
          return resolve(false);
        }
        if (!f.date_range || !Array.isArray(f.date_range) || f.date_range.length !== 2 || !f.date_range[0] || !f.date_range[1]) {
          this.$message.warning('请选择完整的回测时间范围');
          return resolve(false);
        }
        const nComm = Number(f.commission_rate);
        if (f.commission_rate === undefined || f.commission_rate === null || f.commission_rate === '' || !Number.isFinite(nComm) || nComm < 0) {
          this.$message.warning('请输入手续费率');
          return resolve(false);
        }
        const nSlip = Number(f.slippage);
        if (f.slippage === undefined || f.slippage === null || f.slippage === '' || !Number.isFinite(nSlip) || nSlip < 0) {
          this.$message.warning('请输入滑点');
          return resolve(false);
        }
        const manualList = this.selectedStrategiesWithManual || [];
        for (const s of manualList) {
          const list = (f.multiStrategyManualAdjustments && f.multiStrategyManualAdjustments[s.id]) || [];
          if (list.length === 0) {
            this.$message.warning(`主观策略「${s.name || s.id}」需至少预设一个调仓日期`);
            return resolve(false);
          }
          for (let i = 0; i < list.length; i++) {
            if (!list[i].date) {
              this.$message.warning(`主观策略「${s.name || s.id}」调仓日 ${i + 1} 的日期不能为空`);
              return resolve(false);
            }
          }
        }
        resolve(true);
      });
    },
    handleExecute() {
      const runValidation = () => {
        // 主观策略（单策略或多策略含主观）时用自检避免 el-form 对预设调仓区块误报
        if (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) {
          return this.validateManualStrategyForm();
        }
        if (this.form.backtest_mode === 'multi' && this.selectedStrategiesWithManual.length > 0) {
          return this.validateMultiStrategyWithManualForm();
        }
        return new Promise((resolve) => {
          this.$refs.form.validate((valid) => resolve(valid));
        });
      };
      runValidation().then(async (valid) => {
        if (!valid) return;

        // 验证策略选择并规范化 strategy_ids
        let strategyIds = [];
        if (this.form.backtest_mode === 'multi') {
          // 多策略模式：确保是数组
          if (!Array.isArray(this.form.strategy_ids)) {
            strategyIds = this.form.strategy_ids ? [this.form.strategy_ids] : [];
          } else {
            strategyIds = [...this.form.strategy_ids]; // 创建副本
          }
          
          if (strategyIds.length === 0) {
            this.$message.warning('请至少选择一个策略');
            return;
          }
          if (strategyIds.length < 2) {
            this.$message.warning('多策略对比模式需要选择至少2个策略');
            return;
          }
          if (strategyIds.length > 5) {
            this.$message.warning('多策略对比最多选择5个策略');
            return;
          }
        } else {
          // 单策略模式：确保是单个值
          if (Array.isArray(this.form.strategy_ids)) {
            strategyIds = this.form.strategy_ids.length > 0 ? [this.form.strategy_ids[0]] : [];
          } else {
            strategyIds = this.form.strategy_ids ? [this.form.strategy_ids] : [];
          }
          
          if (strategyIds.length === 0) {
            this.$message.warning('请选择一个策略');
            return;
          }
        }

        // 验证日期范围
        if (!this.form.date_range || this.form.date_range.length !== 2) {
          this.$message.warning('请选择完整的回测时间范围');
          return;
        }

        if (new Date(this.form.date_range[0]) >= new Date(this.form.date_range[1])) {
          this.$message.warning('起始日期必须早于结束日期');
          return;
        }

        // 主观配置策略：至少有一个资产权重大于 0（模型默认或本次回测覆盖）
        if (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) {
          const modelSum = Object.values(this.modelManualWeights).reduce((s, v) => s + (Number(v) || 0), 0);
          const runSum = this.runManualWeightsSum;
          if ((!modelSum || modelSum < 1e-6) && (runSum == null || runSum < 1e-6)) {
            this.$message.warning('主观配置策略请至少为一个资产配置权重大于 0（在「权重初始化（本次回测）」中填写，或先在策略模型中保存权重初始化）');
            return;
          }
          if (!this.form.manual_weight_adjustments || this.form.manual_weight_adjustments.length === 0) {
            this.$message.warning('主观策略需至少预设一个调仓日期（权重可留空，到该日再选择）');
            return;
          }
          for (let i = 0; i < this.form.manual_weight_adjustments.length; i++) {
            const adj = this.form.manual_weight_adjustments[i];
            if (!adj.date) {
              this.$message.warning(`调仓日 ${i + 1} 的日期不能为空`);
              return;
            }
          }
          const maxLev = this.getEffectiveMaxLeverage(this.selectedStrategyInfo);
          if (runSum !== null && runSum > maxLev) {
            this.$message.warning(`总仓位权重不能超过最大杠杆 ${(maxLev * 100).toFixed(0)}%。当前权重初始化总和 ${(runSum * 100).toFixed(2)}%`);
            return;
          }
          for (let i = 0; i < (this.form.manual_weight_adjustments || []).length; i++) {
            const sumAdj = this.getAdjustmentWeightSum(i);
            if (sumAdj !== null && sumAdj > maxLev) {
              this.$message.warning(`预设调仓日 ${i + 1} 的权重总和不能超过最大杠杆 ${(maxLev * 100).toFixed(0)}%。当前 ${(sumAdj * 100).toFixed(2)}%`);
              return;
            }
          }
        }

        // 多策略模式：每个主观策略需至少一个预设调仓日
        if (this.form.backtest_mode === 'multi') {
          const manualList = this.selectedStrategiesWithManual || [];
          for (const s of manualList) {
            const list = (this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[s.id]) || [];
            if (list.length === 0) {
              this.$message.warning(`主观策略「${s.name || s.id}」需至少预设一个调仓日期（权重可留空，到该日再选择）`);
              return;
            }
            for (let i = 0; i < list.length; i++) {
              if (!list[i].date) {
                this.$message.warning(`主观策略「${s.name || s.id}」调仓日 ${i + 1} 的日期不能为空`);
                return;
              }
            }
            const maxLev = this.getEffectiveMaxLeverage(s);
            const runSum = this.getMultiStrategyRunManualWeightsSum(s.id);
            if (runSum !== null && runSum > maxLev) {
              this.$message.warning(`主观策略「${s.name || s.id}」权重初始化总和不能超过最大杠杆 ${(maxLev * 100).toFixed(0)}%。当前 ${(runSum * 100).toFixed(2)}%`);
              return;
            }
            for (let i = 0; i < list.length; i++) {
              const sumAdj = this.getMultiStrategyAdjustmentWeightSum(s.id, i);
              if (sumAdj !== null && sumAdj > maxLev) {
                this.$message.warning(`主观策略「${s.name || s.id}」预设调仓日 ${i + 1} 的权重总和不能超过最大杠杆 ${(maxLev * 100).toFixed(0)}%。当前 ${(sumAdj * 100).toFixed(2)}%`);
                return;
              }
            }
          }
        }

        // 动量选择器由策略模型配置，回测时由选择器自动选资产，无需在回测页配置「选择资产数量」与「具体资产」

        // 若用户修改了调仓日或权重，弹窗确认是否同步回策略模型
        if (this.hasManualAdjustmentsModified) {
          this.syncConfirmDialog.visible = true;
          const choice = await new Promise(resolve => {
            this.syncConfirmDialog.resolve = resolve;
          });
          if (choice === 'cancel') return;
          if (choice === 'syncAndRun') {
            try {
              await this.syncAllModifiedStrategies();
            } catch (e) {
              this.syncConfirmDialog.visible = false;
              this.syncConfirmDialog.loading = false;
              return;
            }
            this.syncConfirmDialog.visible = false;
            this.syncConfirmDialog.loading = false;
          }
        }

        this.executing = true;
        this.backtestResults = null;

        try {
          const results = {};
          // 多策略时先跑非主观策略（一次性到结束日），再跑主观策略（可能步进暂停），保证对比结果包含所有策略
          const isMulti = this.form.backtest_mode === 'multi';
          const nonManualIds = isMulti ? strategyIds.filter(id => {
            const s = this.strategyList.find(r => r.id === id);
            return s && !this.isStrategyManual(s);
          }) : [];
          const manualIds = isMulti ? strategyIds.filter(id => {
            const s = this.strategyList.find(r => r.id === id);
            return s && this.isStrategyManual(s);
          }) : [];
          const runOrder = isMulti ? [...nonManualIds, ...manualIds] : strategyIds;
          // 多主观策略同步步进：多个主观策略均 start 后按时间线顺序弹窗；暂存本轮回测的 pending
          const multiManualPending = {};

          for (const strategyId of runOrder) {
            const strategy = this.strategyList.find(s => s.id === strategyId);
            if (!strategy) continue;

            try {
              // 调仓频率映射：中文 -> 英文
              const freqMapping = {
                '每日': 'daily',
                '每周': 'weekly',
                '每月': 'monthly',
                '每季度': 'quarterly',
                '每年': 'yearly',
                'daily': 'daily',
                'weekly': 'weekly',
                'monthly': 'monthly',
                'quarterly': 'quarterly',
                'yearly': 'yearly'
              };
              
              const rebalanceFreq = freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly';
              
              // 构建回测请求数据
              const backtestData = {
                start_date: this.form.date_range[0].replace(/-/g, ''),
                end_date: this.form.date_range[1].replace(/-/g, ''),
                initial_cash: this.form.initial_cash,
                rebalance_freq: rebalanceFreq,
                commission_rate: this.form.commission_rate,
                slippage: this.form.slippage,
                lookback_days: 252,  // 默认252天（约1年交易日）
                enable_vol_reset: this.form.enable_vol_reset,
                vol_reset_threshold: this.form.vol_reset_threshold
              };
              // 杠杆倍数限制（本次回测覆盖策略模型配置；用于限制初始化/预设调仓日/步进调仓权重和）
              if (this.form.run_max_leverage != null && this.form.run_max_leverage !== '' && !Number.isNaN(Number(this.form.run_max_leverage))) {
                const lev = Number(this.form.run_max_leverage);
                if (lev >= 1) backtestData.max_leverage = lev;
              }
              // 主观配置策略：权重初始化（本次回测覆盖；若模型未配置则必填）
              if (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) {
                const mw = this.form.run_manual_weights || {};
                const sum = Object.values(mw).reduce((s, v) => s + (Number(v) || 0), 0);
                if (sum >= 1e-6) {
                  backtestData.manual_weights = { ...mw };
                }
              }
              // 主观策略：预设调仓日期与权重（单策略或多策略中的主观策略）
              const isManualStrategy = this.form.backtest_mode === 'single' ? this.isManualAllocationStrategy : this.isStrategyManual(strategy);
              const manualAdjustmentsList = this.form.backtest_mode === 'single'
                ? (this.form.manual_weight_adjustments || [])
                : (this.form.multiStrategyManualAdjustments && this.form.multiStrategyManualAdjustments[strategyId]) || [];
              if (isManualStrategy && manualAdjustmentsList.length > 0) {
                backtestData.manual_weight_adjustments = manualAdjustmentsList
                  .filter(adj => adj.date)
                  .map(adj => ({
                    date: (adj.date || '').replace(/-/g, '').slice(0, 8),
                    weights: adj.weights && Object.keys(adj.weights).length > 0 ? { ...adj.weights } : undefined,
                    auto_normalize: adj.auto_normalize === true
                  }));
                backtestData.step_phase = 'start';
                // 多策略主观：优先用本次回测权重初始化（multiStrategyRunManualWeights），无则用首个预设日权重
                if (this.form.backtest_mode === 'multi') {
                  const runWeights = this.form.multiStrategyRunManualWeights && this.form.multiStrategyRunManualWeights[strategyId];
                  const runSum = runWeights && typeof runWeights === 'object' ? Object.values(runWeights).reduce((s, v) => s + (Number(v) || 0), 0) : 0;
                  if (runSum >= 1e-6) {
                    backtestData.manual_weights = { ...runWeights };
                  } else {
                    const firstWithWeights = manualAdjustmentsList.find(adj => adj.weights && Object.keys(adj.weights).length > 0);
                    if (firstWithWeights && firstWithWeights.weights) {
                      const sum = Object.values(firstWithWeights.weights).reduce((s, v) => s + (Number(v) || 0), 0);
                      if (sum >= 1e-6) backtestData.manual_weights = { ...firstWithWeights.weights };
                    }
                  }
                }
              }

              // 动量选择器参数：单策略且界面显示「动量资产选择器配置」时始终提交表单值，保证与持仓权重资产数一致
              const strategyHasSelection = strategy.enable_momentum_selection === true;
              const singleModeWithSelection = this.form.backtest_mode === 'single' && this.hasMomentumSelection;
              
              if (singleModeWithSelection || strategyHasSelection) {
                // 资产数量与具体资产由动量选择器根据策略配置自动决定，不传 selected_asset_codes
                backtestData.enable_momentum_selection = true;
                backtestData.asset_selection_count = strategy.asset_selection_count || 8;
                if (this.form.backtest_mode === 'multi') {
                  const selectionParams = this.form.multiStrategySelectionParams[strategyId];
                  if (selectionParams) {
                    backtestData.selector_type = selectionParams.selector_type;
                    backtestData.momentum_windows = selectionParams.momentum_windows;
                    backtestData.smom_windows = selectionParams.smom_windows || selectionParams.momentum_windows || '20,60,120,250';
                    if (selectionParams.selector_type === 'hybrid') {
                      backtestData.macd_windows = selectionParams.macd_windows || '40,80,120,160';
                      backtestData.reversal_windows = selectionParams.reversal_windows || '10,22';
                    }
                  } else {
                    backtestData.selector_type = strategy.selector_type || 'momentum';
                    backtestData.momentum_windows = strategy.momentum_windows || '20,60,120,250';
                    backtestData.smom_windows = strategy.smom_windows || strategy.momentum_windows || '20,60,120,250';
                    if ((strategy.selector_type || '') === 'hybrid') {
                      backtestData.macd_windows = strategy.macd_windows || '40,80,120,160';
                      backtestData.reversal_windows = strategy.reversal_windows || '10,22';
                    }
                  }
                } else {
                  backtestData.selector_type = this.form.selector_type;
                  backtestData.momentum_windows = this.form.momentum_windows;
                  backtestData.smom_windows = this.form.smom_windows || this.form.momentum_windows || '20,60,120,250';
                  if (this.form.selector_type === 'hybrid') {
                    backtestData.macd_windows = this.form.macd_windows || '40,80,120,160';
                    backtestData.reversal_windows = this.form.reversal_windows || '10,22';
                  }
                }
              }
              
              const result = await this.$store.dispatch('strategy/runBacktest', {
                modelId: strategyId,
                data: backtestData
              });

              // 处理返回结果（统一解包 code/data 结构，保证 record_id 可用）
              const resultData = (result && result.data !== undefined) ? result.data : result;
              let recordId = resultData && (resultData.record_id != null ? String(resultData.record_id) : (result && result.data && result.data.record_id != null ? String(result.data.record_id) : null));
              console.log('[BacktestRecord] 回测返回 raw_result_keys=', result ? Object.keys(result) : [], 'resultData_record_id=', resultData && resultData.record_id, 'recordId=', recordId);
              // 若响应中无 record_id，则查询该策略最新回测记录进行关联（先保存再查询关联）
              if (!recordId && strategyId) {
                try {
                  const history = await this.$store.dispatch('strategy/fetchBacktestHistory', { modelId: strategyId, skip: 0, limit: 5 });
                  const list = Array.isArray(history) ? history : (history && history.data) ? history.data : [];
                  const latest = list[0];
                  if (latest && (latest.id || latest._id)) {
                    recordId = String(latest.id || latest._id);
                    if (resultData && typeof resultData === 'object') resultData.record_id = recordId;
                    console.log('[BacktestRecord] 通过查询历史记录关联 record_id=', recordId);
                  } else {
                    console.warn('[BacktestRecord] 查询历史记录无最新记录 modelId=', strategyId, 'list_length=', list.length);
                  }
                } catch (e) {
                  console.warn('[BacktestRecord] 查询历史记录失败', e);
                }
              }

              // 主观策略步进回测：到预设调仓日暂停，弹出对话框由用户选择 预设权重/实时输入/不调仓（支持单策略与多策略）
              const manualPaused = resultData && resultData.phase === 'paused' && (
                (this.form.backtest_mode === 'single' && this.isManualAllocationStrategy) ||
                (this.form.backtest_mode === 'multi' && this.isStrategyManual(strategy))
              );
              if (manualPaused) {
                if (this.form.backtest_mode === 'multi') {
                  // 多主观策略同步步进：暂存该策略的步进状态（键统一为字符串，便于与 fetchOtherStrategiesMetricsForStep 一致）
                  const idKey = String(strategyId);
                  multiManualPending[idKey] = {
                    strategy,
                    strategyId: idKey,
                    backtestData: { ...backtestData },
                    stepResponse: resultData
                  };
                  continue;
                }
                // 单策略：先展示已有结果，再弹窗让步进
                this.presetStepDialog.strategyId = strategyId;
                this.presetStepDialog.strategy = strategy;
                this.presetStepDialog.backtestData = { ...backtestData };
                this.presetStepDialog.stepResponse = resultData;
                this.presetStepDialog.decision = 'skip';
                const adjustmentsListSingle = (this.form.manual_weight_adjustments || []);
                const presetForDateSingle = adjustmentsListSingle.find(
                  adj => (adj.date || '').replace(/-/g, '').slice(0, 8) === (resultData.next_preset_date || '')
                );
                const codesSingle = (strategy.asset_codes || []);
                if (presetForDateSingle && presetForDateSingle.weights && Object.keys(presetForDateSingle.weights).length > 0) {
                  this.presetStepDialog.customWeights = codesSingle.reduce((o, c) => ({ ...o, [c]: Number(presetForDateSingle.weights[c]) || 0 }), {});
                } else {
                  this.presetStepDialog.customWeights = codesSingle.reduce((o, c) => ({ ...o, [c]: 0 }), {});
                  if (codesSingle.length) this.presetStepDialog.customWeights[codesSingle[0]] = 1;
                }
                this.presetStepDialog.autoNormalize = presetForDateSingle ? presetForDateSingle.auto_normalize === true : false;
                this.presetStepDialog.otherStrategiesMetrics = [];
                this.presetStepDialog.visible = true;
                this.presetStepDialog.loading = false;
                this.executing = false;
                return;
              }

              // 单策略 + 启用波动率重置：若存在波动率重置日，弹出步进选择对话框，由用户逐日选择后重新回测
              if (this.form.backtest_mode === 'single' && this.form.enable_vol_reset && resultData.snapshots) {
                const volResetSnapshots = resultData.snapshots.filter(s =>
                  s.is_rebalance_day && (s.rebalance_type === 'vol_reset' || (s.rebalance_reason && String(s.rebalance_reason).indexOf('波动率重置') >= 0))
                );
                if (volResetSnapshots.length > 0) {
                  this.backtestModelId = strategyId;
                  this.openVolResetDecisionDialog(strategyId, strategy, backtestData, resultData, volResetSnapshots);
                  this.executing = false;
                  return;
                }
              }

              const rid = recordId != null ? String(recordId) : (resultData && resultData.record_id != null ? String(resultData.record_id) : (resultData && resultData.result && resultData.result.record_id != null ? String(resultData.result.record_id) : null));
              const resultKey = isMulti ? String(strategyId) : strategy.name;
              results[resultKey] = {
                result: resultData,
                strategy: strategy,
                remark: resultData.remark != null ? resultData.remark : '',
                record_id: rid
              };
              if (this.form.backtest_mode === 'single') {
                this.backtestModelId = strategyId;
              }
              const snapCount = (resultData && resultData.snapshots && Array.isArray(resultData.snapshots)) ? resultData.snapshots.length : 0;
              console.log('[BacktestRecord] 结果写入 key=', resultKey, 'strategyName=', strategy.name, 'record_id=', rid, 'snapshots=', snapCount, 'backtestModelId=', this.form.backtest_mode === 'single' ? strategyId : undefined);
            } catch (error) {
              console.error(`策略 ${strategy.name} 回测失败:`, error);
              console.error('完整错误信息:', error.response);
              
              // 提取详细错误信息
              let errorDetail = '未知错误';
              if (error.response) {
                if (error.response.data) {
                  if (error.response.data.detail) {
                    errorDetail = error.response.data.detail;
                  } else if (error.response.data.message) {
                    errorDetail = error.response.data.message;
                  } else if (typeof error.response.data === 'string') {
                    errorDetail = error.response.data;
                  }
                } else if (error.response.statusText) {
                  errorDetail = `${error.response.status} ${error.response.statusText}`;
                }
              } else if (error.message) {
                errorDetail = error.message;
              }
              
              // 如果是多行错误信息，使用换行符分隔
              const errorMsg = typeof errorDetail === 'string' && errorDetail.includes('\n')
                ? errorDetail.split('\n').join('<br/>')
                : errorDetail;
              
              // 显示错误消息
              // 对于数据不足的错误，使用更友好的显示方式
              let displayMessage = `策略 "${strategy.name}" 回测失败：${errorMsg}`;
              
              // 如果是数据不足的错误，使用对话框显示完整信息
              if (errorDetail.includes('没有资产满足最小历史数据要求') || 
                  errorDetail.includes('可用数据情况') || 
                  errorDetail.includes('建议：')) {
                this.$alert(
                  displayMessage,
                  '回测失败 - 数据不足',
                  {
                    confirmButtonText: '确定',
                    type: 'error',
                    dangerouslyUseHTMLString: true,
                    customClass: 'backtest-error-dialog'
                  }
                );
              } else {
                this.$message({
                  message: displayMessage,
                  type: 'error',
                  duration: 10000, // 延长显示时间
                  dangerouslyUseHTMLString: true,
                  showClose: true
                });
              }
              
              // 如果是500错误，提供更多帮助信息
              if (error.response && error.response.status === 500) {
                console.warn('回测500错误，可能的原因：');
                console.warn('1. 策略参数配置错误');
                console.warn('2. 策略算法实现问题');
                console.warn('3. 数据格式不匹配');
                console.warn('4. 请查看后端日志获取详细错误堆栈');
              }
            }
          }

          // 多主观策略同步步进：所有主观策略均已 start 并暂存于 multiManualPending，按时间线顺序弹窗
          if (isMulti && Object.keys(multiManualPending).length > 0) {
            this.multiManualPending = multiManualPending;
            if (Object.keys(results).length > 0) {
              this.backtestResults = { ...results };
            }
            console.log('[多策略] 主观策略步进暂停 已收集策略数=', Object.keys(results).length, 'keys=', Object.keys(results), 'pending主观数=', Object.keys(multiManualPending).length);
            const nextEntry = this.pickNextMultiManualStep();
            if (nextEntry) {
              this.openPresetStepDialogForEntry(nextEntry);
            }
            this.executing = false;
            return;
          }

          if (Object.keys(results).length > 0) {
            this.backtestResults = results;
            const keys = Object.keys(results);
            console.log('[多策略] 回测完成 策略数=', keys.length, 'keys=', keys);
            keys.forEach(k => {
              const r = results[k];
              const snap = (r && r.result && r.result.snapshots) ? r.result.snapshots.length : 0;
              console.log('[多策略] 主观策略回测数据 key=', k, 'strategyName=', (r && r.strategy && r.strategy.name) || k, 'snapshots=', snap, 'hasResult=', !!(r && r.result));
            });
            this.$message.success(`回测完成！共运行 ${keys.length} 个策略`);
            
            // 滚动到结果区域
            this.$nextTick(() => {
              const resultElement = document.querySelector('.backtest-result');
              if (resultElement) {
                resultElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }
            });
          } else {
            this.$message.error('所有策略回测均失败');
          }
        } catch (error) {
          console.error('回测执行失败:', error);
          this.$message.error('回测执行失败：' + (error.response?.data?.detail || error.message));
        } finally {
          this.executing = false;
        }
      });
    },
    handleReset() {
      this.$refs.form.resetFields();
      this.form = {
        backtest_mode: 'single',
        strategy_ids: null, // 单策略模式为 null，多策略模式为 []
        initial_cash: 1000000,
        rebalance_freq: 'monthly',
        date_range: [
          dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
          dayjs().format('YYYY-MM-DD')
        ],
        commission_rate: 0.0003,
        slippage: 0.0005,
        enable_vol_reset: true,
        vol_reset_threshold: 0.06,
        // 动量选择器参数（单策略模式使用）
        selector_type: 'momentum',
        asset_selection_count: 8,
        min_history_days: 260,
        momentum_windows: '22,65,260',
        tie_break_window: 22,
        // 多策略模式的选择器参数
        multiStrategySelectionParams: {},
        enable_interactive_adjustment: false,
        manual_weight_adjustments: [],
        run_manual_weights: {},
        multiStrategyManualAdjustments: {},
        multiStrategyRunManualWeights: {}
      };
      this.backtestResults = null;
      this.backtestModelId = null;
      this.selectedStrategyInfo = null;
    },
    handleViewHistory() {
      this.$message.info('历史记录功能开发中...');
      // TODO: 跳转到历史记录页面
    },
    getStatusTagType(status) {
      // 根据策略状态返回对应的标签类型
      const statusMap = {
        '草稿': 'info',
        '已发布': 'success',
        '已归档': 'warning'
      };
      return statusMap[status] || 'info';
    },
    getParameterLabel(key) {
      // 获取参数的中文标签
      if (this.selectedStrategyInfo && this.selectedStrategyInfo.parameter_labels) {
        return this.selectedStrategyInfo.parameter_labels[key] || key;
      }
      // 如果没有 parameter_labels，尝试使用常见的参数名称映射
      const commonLabels = {
        'target_return': '目标年化收益率',
        'target_vol': '目标年化波动率',
        'lookback_days': '历史数据回看期',
        'risk_free_rate': '无风险利率',
        'min_weight': '单资产最小权重',
        'max_weight': '单资产最大权重',
        'maxiter': '最大迭代次数',
        'optimization_mode': '优化模式',
        'risk_budget_both': '交集资产风险预算',
        'risk_budget_single': '单一模型资产风险预算',
        'max_total_leverage': '最大杠杆倍数',
        'max_weight_dict': '单资产最大权重配置',
        'min_history_days': '最小历史数据要求',
        'enable_vol_reset': '启用波动率阈值重置',
        'vol_reset_threshold': '波动率重置阈值',
        'rebalance_frequency': '调仓频率'
      };
      return commonLabels[key] || key;
    },
    formatParameterValue(value) {
      // 格式化参数值显示
      if (value === null || value === undefined) {
        return '-';
      }
      
      // 如果是对象（如字典），格式化为 JSON 字符串
      if (typeof value === 'object') {
        try {
          return JSON.stringify(value, null, 2);
        } catch (e) {
          return String(value);
        }
      }
      
      // 如果是数字，保留适当的小数位数
      if (typeof value === 'number') {
        // 如果是整数，不显示小数
        if (Number.isInteger(value)) {
          return value.toString();
        }
        // 如果是小数，保留最多4位小数
        return value.toFixed(4).replace(/\.?0+$/, '');
      }
      
      // 如果是布尔值
      if (typeof value === 'boolean') {
        return value ? '是' : '否';
      }
      
      return String(value);
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
  max-width: 1200px;
  margin: 0 auto;
}

.card-header {
  font-weight: 500;
  font-size: 16px;
}

.el-form {
  max-width: 800px;
}

/* 表单标签不换行，避免中文标签断行不美观 */
.backtest-form ::v-deep .el-form-item__label {
  white-space: nowrap;
}

/* 资产选择标签样式 */
.asset-selection-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.asset-tag {
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}

.asset-tag:hover {
  transform: scale(1.05);
}

.asset-tag-selected {
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.4);
}

/* 预设调仓日对话框：当前绩效指标 */
.metric-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.metric-label {
  font-size: 12px;
  color: #909399;
}
.metric-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
</style>
