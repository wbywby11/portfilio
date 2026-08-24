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

        <el-form :model="form" :rules="rules" ref="form" label-width="120px" style="max-width: 900px;">
          <!-- 回测模式 -->
          <el-form-item>
            <span slot="label">回测模式
              <el-tooltip content="单策略回测：查看单个策略或组合的完整回测结果；多策略对比：同时运行2-10个策略/组合" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <el-radio-group v-model="form.backtest_mode">
              <el-radio-button label="single">单策略回测</el-radio-button>
              <el-radio-button label="multi">多策略对比</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <!-- 策略/组合选择 -->
          <el-form-item prop="strategy_ids">
            <span slot="label">选择策略
              <el-tooltip content="选择要回测的策略模型或投资组合，多策略对比模式下需要选择2-10个" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <!-- 单策略模式：分组下拉 -->
            <el-select
              v-if="form.backtest_mode === 'single'"
              v-model="form.strategy_ids"
              placeholder="请选择策略或组合"
              style="width: 100%;"
              @change="handleStrategyChange"
            >
              <el-option-group label="策略模型">
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
              </el-option-group>
              <el-option-group v-if="portfolioList.length > 0" label="投资组合">
                <el-option
                  v-for="p in portfolioList"
                  :key="`portfolio:${p.id}`"
                  :label="`${p.name}（组合）`"
                  :value="`portfolio:${p.id}`"
                >
                  <span style="float: left">{{ p.name }}</span>
                  <span style="float: right; color: #8492a6; font-size: 13px">
                    {{ (p.sub_strategies || []).length }}个子策略
                    <el-tag size="mini" type="success" style="margin-left: 4px;">组合</el-tag>
                  </span>
                </el-option>
              </el-option-group>
            </el-select>
            <!-- 多策略模式 - 使用多选框，策略+组合分组显示 -->
            <div v-else style="width: 100%;">
              <el-checkbox-group v-model="form.strategy_ids" @change="handleStrategyChange" style="width: 100%;">
                <div style="max-height: 360px; overflow-y: auto; border: 1px solid #DCDFE6; border-radius: 4px; padding: 10px;">
                  <!-- 策略模型分组 -->
                  <div style="font-weight: 600; color: #606266; margin-bottom: 8px; font-size: 13px;">策略模型</div>
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
                  <!-- 投资组合分组 -->
                  <template v-if="portfolioList.length > 0">
                    <div style="border-top: 2px solid #E4E7ED; margin-top: 8px; padding-top: 10px; font-weight: 600; color: #606266; margin-bottom: 8px; font-size: 13px;">投资组合</div>
                    <el-checkbox
                      v-for="(p, index) in portfolioList"
                      :key="`portfolio:${p.id}`"
                      :label="`portfolio:${p.id}`"
                      style="display: block; margin-bottom: 10px; padding: 8px;"
                      :style="{'border-bottom': index < portfolioList.length - 1 ? '1px solid #F0F0F0' : 'none'}"
                    >
                      <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                        <span style="flex: 1; font-weight: 500;">{{ p.name }}</span>
                        <span style="color: #8492a6; font-size: 12px; margin-right: 8px;">
                          {{ (p.sub_strategies || []).length }}个子策略
                        </span>
                        <el-tag size="mini" type="success">组合</el-tag>
                      </div>
                    </el-checkbox>
                  </template>
                </div>
              </el-checkbox-group>
            </div>
            <div v-if="strategyList.length === 0 && portfolioList.length === 0" style="margin-top: 10px;">
              <el-alert
                title="提示"
                type="warning"
                :closable="false"
                show-icon
              >
                暂无可用策略或组合，请先创建策略模型或投资组合
              </el-alert>
            </div>
            <!-- 多策略模式下显示已选择数量 -->
            <div v-else-if="form.backtest_mode === 'multi'" style="margin-top: 10px;">
              <span v-if="selectedStrategyCount > 0" style="color: #409EFF; font-size: 13px; font-weight: 500;">
                已选择 {{ selectedStrategyCount }} 项
                <span v-if="selectedStrategyCount < 2" style="color: #F56C6C; margin-left: 10px;">
                  （至少需要选择2项）
                </span>
                <span v-else-if="selectedStrategyCount > 10" style="color: #F56C6C; margin-left: 10px;">
                  （最多只能选择10项）
                </span>
              </span>
            </div>
          </el-form-item>

          <!-- 多策略对比 -->

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
                  主观策略<strong>不设</strong>周期性调仓与波动率阈值重置，仅在下方预设的日期调仓。若策略模型中已配置调仓日与权重，将自动带出；否则请在此添加。每个调仓日可填预设权重——回测将<strong>直接按预设仓位完整执行</strong>。请至少添加一个调仓日。
                </div>
                <SubjectiveWeightsMatrixTable
                  :asset-codes="(selectedStrategyInfo && selectedStrategyInfo.asset_codes) || []"
                  :resolve-label="resolveSingleAssetLabel"
                  :adjustments="form.manual_weight_adjustments"
                  :max-leverage="runMaxLeverage || getMaxLeverageForStrategy(selectedStrategyInfo)"
                  @update:adjustments="onManualAdjustmentsUpdate"
                />
              </el-card>
            </el-form-item>
          </template>

          <!-- 多策略对比：杠杆倍数限制 + 主观策略预设调仓日期与权重 -->
          <template v-if="form.backtest_mode === 'multi' && selectedStrategiesWithManual.length > 0">
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
                  <i class="el-icon-date"></i> 多策略中的主观策略需至少一个调仓日
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
                    <SubjectiveWeightsMatrixTable
                      :asset-codes="s.asset_codes || []"
                      :resolve-label="(code) => resolveMultiAssetLabel(s, code)"
                      :adjustments="getMultiStrategyManualAdjustmentsList(s.id)"
                      :max-leverage="getEffectiveMaxLeverage(s)"
                      @update:adjustments="(val) => onMultiStrategyAdjustmentsUpdate(s.id, val)"
                    />
                    </el-form>
                  </el-collapse-item>
                </el-collapse>
              </el-card>
            </el-form-item>
          </template>

          <!-- 回测时间 -->
          <el-form-item prop="date_range">
            <span slot="label">回测时间
              <el-tooltip content="回测的时间区间，系统将从开始日期到结束日期进行模拟交易" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
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
          </el-form-item>

          <!-- 交易成本 -->
          <el-divider content-position="left">交易成本</el-divider>
          
          <el-form-item prop="commission_rate">
            <span slot="label">手续费率
              <el-tooltip content="交易手续费率，默认0.03%（万三），包含买卖双向成本；范围0-0.01，步长0.0001" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <el-input-number
              v-model="form.commission_rate"
              :min="0"
              :max="0.01"
              :step="0.0001"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
          </el-form-item>

          <el-form-item prop="slippage">
            <span slot="label">滑点
              <el-tooltip content="市场冲击成本（滑点），默认0.05%（万五），用于模拟大额交易对价格的影响；范围0-0.01，步长0.0001" placement="top">
                <i class="el-icon-question" style="color: #909399; cursor: help;"></i>
              </el-tooltip>
            </span>
            <el-input-number
              v-model="form.slippage"
              :min="0"
              :max="0.01"
              :step="0.0001"
              :precision="4"
              style="width: 200px;"
            ></el-input-number>
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
          title="请配置回测参数后点击执行回测"
          type="info"
          :closable="false"
          show-icon
          style="margin-top: 20px;"
        ></el-alert>
      </el-card>

      <!-- 回测结果展示 -->
      <backtest-result
        v-if="backtestResults"
        :results="backtestResults"
        :mode="form.backtest_mode"
        :config="form"
        :model-id="backtestModelId"
      ></backtest-result>

      <!-- 策略多维验证（第5层增强） -->
      <!--
        暂时隐藏：敏感度 / 情景推演 / 鲁棒性的产品效果尚未确定，
        后端 API 已就绪（/api/v1/backtests/{sensitivity,scenario,robustness}），
        待产品方案明确后再开放前端展示。
        当前策略验证仍以「单策略回测 + 多策略对比」为主。
      -->



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
import SubjectiveWeightsMatrixTable from '@/components/SubjectiveWeightsMatrixTable.vue';
import { getMaxWeightsByCodes, computeMetricsFromSnapshots } from '@/api/strategy';

export default {
  name: 'BacktestExecution',
  components: {
    BacktestResult,
    SubjectiveWeightsMatrixTable
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
        enable_vol_reset: false,  // 所有策略默认关闭波动率重置
        vol_reset_threshold: 0.06,
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
        run_max_leverage: null,
      },
      executing: false,
      backtestResults: null,
      backtestModelId: null,
      selectedStrategyInfo: null,

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
      },
      // 组合回测
      portfolioList: []
    };
  },
  computed: {
    ...mapState('strategy', ['strategyModelList']),
    // 为了兼容性，提供 strategyList 作为 strategyModelList 的别名
    strategyList() {
      return this.strategyModelList || [];
    },
    selectedStrategies() {
      if (!this.form.strategy_ids) return [];
      const ids = Array.isArray(this.form.strategy_ids) ? this.form.strategy_ids : [this.form.strategy_ids];
      return ids.map(id => this.strategyList.find(s => s.id === id)).filter(Boolean);
    },
    // 检查是否有策略启用了动量选择器（选择器参数由策略模型配置，回测页不展示）
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
        // 策略切换时清空交互式权重调整
        this.form.enable_interactive_adjustment = false;
        this.form.manual_weight_adjustments = [];
        // 主观配置策略：预设调仓日由 updateSelectedStrategyInfo 中 initManualWeightAdjustmentsFromStrategy 加载
        this.$nextTick(() => {
          this.syncRunManualWeights();
          if (this.isManualAllocationStrategy && this.$refs.form) this.$refs.form.clearValidate();
        });
        // 如果是多策略模式，初始化主观策略的调仓日与权重
        if (this.form.backtest_mode === 'multi') {
          this.$nextTick(() => {
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
    this.loadPortfolioList();  // 加载组合列表（用于组合回测模式）
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
    // 加载组合列表（用于组合回测模式）
    async loadPortfolioList() {
      try {
        const { getPortfolioList } = await import('@/api/portfolio');
        const res = await getPortfolioList();
        this.portfolioList = res.data || [];
      } catch (error) {
        console.error('加载组合列表失败:', error);
        this.portfolioList = [];
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
    /** 单策略主观：解析资产代码到展示名称 */
    resolveSingleAssetLabel(code) {
      const s = this.selectedStrategyInfo;
      if (s && s.asset_names && s.asset_names[code]) {
        return code + ' - ' + s.asset_names[code];
      }
      return code;
    },
    /** 多策略主观：解析资产代码到展示名称 */
    resolveMultiAssetLabel(strategy, code) {
      if (strategy && strategy.asset_names && strategy.asset_names[code]) {
        return code + ' - ' + strategy.asset_names[code];
      }
      return code;
    },
    /** 矩阵表更新单策略预设调仓数据 */
    onManualAdjustmentsUpdate(val) {
      this.form.manual_weight_adjustments = Array.isArray(val) ? val : [];
      if (this.$refs.form) this.$refs.form.clearValidate();
    },
    /** 矩阵表更新多策略某个主观策略的预设调仓数据 */
    onMultiStrategyAdjustmentsUpdate(strategyId, val) {
      const m = this.form.multiStrategyManualAdjustments || {};
      this.$set(this.form, 'multiStrategyManualAdjustments', {
        ...m,
        [strategyId]: Array.isArray(val) ? val : []
      });
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
          tie_break_window: model.tie_break_window ?? 22
        };
        if (model.enable_momentum_selection && ['hybrid', 'reversal', 'momentum_reversal'].includes(model.selector_type)) {
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
        
        // 限制最多选择10个策略
        if (this.form.strategy_ids && this.form.strategy_ids.length > 10) {
          this.$message.warning('多策略对比最多选择10个策略，已自动保留前10个');
          this.form.strategy_ids = this.form.strategy_ids.slice(0, 10);
        }
        
        // 为多策略模式的所有策略构建 asset_names 映射
        this.$nextTick(async () => {
          const strategies = this.selectedStrategies || [];
          for (const strategy of strategies) {
            await this.buildAssetNamesForStrategy(strategy);
          }
        });
      } else {
        // 单策略模式：确保 strategy_ids 是单个值
        if (Array.isArray(this.form.strategy_ids)) {
          this.form.strategy_ids = this.form.strategy_ids.length > 0 ? this.form.strategy_ids[0] : null;
        }
      }
      this.updateSelectedStrategyInfo();
    },
    async updateSelectedStrategyInfo() {
      // 更新选中的策略信息(用于显示资产池和参数等)
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
        // 组合ID：不需要加载策略详情
        if (String(strategyId).startsWith('portfolio:')) {
          this.selectedStrategyInfo = null;
          return;
        }
        // 先从列表中查找
        const strategy = this.strategyList.find(s => s.id === strategyId);
        const code = strategy && (strategy.template_code || '').toString();
        const isManual = code === 'manual_allocation' || code === 'manual_allocation_strategy'
          || (code.toLowerCase && code.toLowerCase().includes('manual') && code.toLowerCase().includes('allocation'));
        const hasManualWeights = strategy && strategy.parameters && typeof strategy.parameters.manual_weights === 'object' && strategy.parameters.manual_weights !== null;
        // 列表信息不完整,或为主观配置策略时拉取完整策略(保证权重初始化与预设调仓日能带出)
        const needFull = strategy && (
          !strategy.parameters ||
          !strategy.parameter_labels ||
          isManual
        );
        if (needFull) {
          try {
            const fullStrategy = await this.$store.dispatch('strategy/fetchStrategyModel', strategyId);
            this.selectedStrategyInfo = fullStrategy;
            // 构建 asset_names 映射
            await this.buildAssetNamesForStrategy(this.selectedStrategyInfo);
            this.initSelectionParams(fullStrategy);
          } catch (error) {
            console.error('获取策略详情失败:', error);
            this.selectedStrategyInfo = strategy;
            // 构建 asset_names 映射
            await this.buildAssetNamesForStrategy(this.selectedStrategyInfo);
            this.initSelectionParams(strategy);
          }
        } else {
          this.selectedStrategyInfo = strategy;
          // 构建 asset_names 映射
          await this.buildAssetNamesForStrategy(this.selectedStrategyInfo);
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

      // 多策略模式：清理已取消选择的策略的调仓日/权重参数
      if (this.form.backtest_mode === 'multi') {
        this.cleanupDeselectedStrategies();
      }
    },
    /** 为策略构建 asset_names 映射(从资产库获取名称) */
    async buildAssetNamesForStrategy(strategy) {
      if (!strategy || !strategy.asset_codes || strategy.asset_codes.length === 0) {
        return;
      }
      // 如果已有 asset_names,跳过
      if (strategy.asset_names && Object.keys(strategy.asset_names).length > 0) {
        return;
      }
      try {
        // 从资产库获取所有资产选项
        const assetOptions = await this.$store.dispatch('asset/fetchAssetOptions');
        // 构建 code -> name 映射
        const assetNames = {};
        strategy.asset_codes.forEach(code => {
          const asset = assetOptions.find(a => a.code === code);
          assetNames[code] = asset ? asset.name : code;
        });
        // 设置到策略对象上
        this.$set(strategy, 'asset_names', assetNames);
      } catch (error) {
        console.error('获取资产名称失败:', error);
        // 失败时使用 code 作为 name
        const assetNames = {};
        strategy.asset_codes.forEach(code => {
          assetNames[code] = code;
        });
        this.$set(strategy, 'asset_names', assetNames);
      }
    },
    /** 从模型带出权重初始化到 form.run_manual_weights,供本次回测使用或覆盖 */
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
    // 初始化单策略的权重上限（maxWeightDict）
    initSelectionParams(strategy) {
      if (!strategy) return;
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
    // ========== 多策略模式的资产选择方法（已移除，选择器参数由策略模型配置） ==========
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
    // ========== 多策略模式的资产选择方法（已移除，选择器参数由策略模型配置） ==========
    // 清理已取消选择的策略的多策略参数（调仓日/权重）
    cleanupDeselectedStrategies() {
      const selectedStrategies = this.selectedStrategies;
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
          this.$message.warning('主观策略需至少预设一个调仓日期');
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
        if (ids.length > 10) {
          this.$message.warning('多策略对比最多选择 10 个策略');
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
          if (strategyIds.length > 10) {
            this.$message.warning('多策略对比最多选择10个策略');
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
            this.$message.warning('请选择一个策略或组合');
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
            this.$message.warning('主观策略需至少预设一个调仓日期');
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
              this.$message.warning(`主观策略「${s.name || s.id}」需至少预设一个调仓日期`);
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
          // 组合ID不参与主观策略分类，始终作为非主观项处理
          const nonManualIds = isMulti ? strategyIds.filter(id => {
            if (String(id).startsWith('portfolio:')) return true; // 组合视为非主观
            const s = this.strategyList.find(r => r.id === id);
            return s && !this.isStrategyManual(s);
          }) : [];
          const manualIds = isMulti ? strategyIds.filter(id => {
            if (String(id).startsWith('portfolio:')) return false; // 组合不参与主观分类
            const s = this.strategyList.find(r => r.id === id);
            return s && this.isStrategyManual(s);
          }) : [];
          const runOrder = isMulti ? [...nonManualIds, ...manualIds] : strategyIds;

          for (const strategyId of runOrder) {
            // 组合ID：调用组合回测API
            if (String(strategyId).startsWith('portfolio:')) {
              const portfolioId = String(strategyId).replace(/^portfolio:/, '');
              const portfolio = this.portfolioList.find(p => p.id === portfolioId);
              try {
                const { runPortfolioBacktest } = await import('@/api/portfolio');
                const startDate = this.form.date_range[0].replace(/-/g, '');
                const endDate = this.form.date_range[1].replace(/-/g, '');
                const freqMapping = {
                  '每日': 'daily', '每周': 'weekly', '每月': 'monthly',
                  '每季度': 'quarterly', '每年': 'yearly',
                  'daily': 'daily', 'weekly': 'weekly', 'monthly': 'monthly',
                  'quarterly': 'quarterly', 'yearly': 'yearly'
                };
                const res = await runPortfolioBacktest(portfolioId, {
                  start_date: startDate,
                  end_date: endDate,
                  initial_nav: this.form.initial_cash,
                  rebalance_freq: freqMapping[this.form.rebalance_freq] || this.form.rebalance_freq || 'monthly',
                  mother_vol_target: this.form.enable_vol_reset ? this.form.vol_reset_threshold : null
                });
                const data = res.data || res;
                // 组合回测结果转换为与策略回测相同的结构
                const portfolioName = portfolio ? portfolio.name : `组合${portfolioId}`;
                results[strategyId] = {
                  result: {
                    total_return: data.total_return,
                    annual_return: data.annual_return,
                    annual_volatility: data.annual_volatility,
                    // SingleStrategyResult 读的是 volatility 字段（单策略后端 BacktestResultOut 的命名），组合后端返回 annual_volatility，需映射
                    volatility: data.annual_volatility,
                    sharpe_ratio: data.sharpe_ratio,
                    max_drawdown: data.max_drawdown,
                    calmar_ratio: data.calmar_ratio,
                    // 携带交易明细与胜率，避免交易次数/胜率为空
                    trades: data.trades || [],
                    win_rate: data.win_rate != null ? data.win_rate : null,
                    // 后端如实上报的数据质量告警与子策略归因
                    warnings: data.warnings || [],
                    attribution: data.attribution || null,
                    snapshots: (data.equity_curve || []).map(pt => ({
                      time: pt.date,
                      total_value: pt.value,
                      // 携带后端已算好的回撤/调仓/穿透权重，避免 SingleStrategyResult 回撤图全为0、持仓图为空
                      drawdown: pt.drawdown != null ? pt.drawdown : 0,
                      is_rebalance_day: !!pt.is_rebalance_day,
                      weights: pt.weights || {}
                    }))
                  },
                  strategy: {
                    id: strategyId,
                    name: portfolioName,
                    template_code: 'PORTFOLIO',
                    status: '已发布'
                  },
                  record_id: data.backtest_record_id || null,
                  remark: ''
                };
              } catch (error) {
                console.error(`组合 ${portfolioId} 回测失败:`, error);
                this.$message.error(`组合回测失败：${error.response?.data?.detail || error.message || '未知错误'}`);
              }
              continue; // 跳过后续策略回测逻辑
            }

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

              // 资产选择器：仅标记启用，具体参数由策略模型配置决定（后端从 model_data 读取）
              if (strategy.enable_momentum_selection === true) {
                backtestData.enable_momentum_selection = true;
                backtestData.asset_selection_count = strategy.asset_selection_count || (strategy.asset_codes && strategy.asset_codes.length) || 5;
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
        enable_vol_reset: false,  // 所有策略默认关闭波动率重置
        vol_reset_threshold: 0.06,
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
