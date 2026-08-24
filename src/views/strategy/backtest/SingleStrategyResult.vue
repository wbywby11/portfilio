<template>
  <div class="single-strategy-result">
    <h3 style="margin-bottom: 20px;">📈 回测结果：{{ strategyName }}</h3>

    <!-- 数据质量提示：后端如实上报，指标不做任何钳制 -->
    <el-alert
      v-if="warnings.length > 0"
      type="warning"
      title="数据质量提示（指标未做修正，请结合下列情况解读）"
      :closable="false"
      show-icon
      style="margin-bottom: 20px;"
    >
      <div v-for="(w, i) in warnings" :key="i" style="font-size: 12px; line-height: 1.8;">{{ w }}</div>
    </el-alert>

    <!-- 核心绩效指标 -->
    <el-card shadow="never" style="margin-bottom: 20px;">
      <div slot="header">
        <span>核心绩效指标</span>
      </div>
      <el-row :gutter="20">
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">总收益率</div>
            <div class="metric-value" :class="getReturnClass(result.total_return)">
              {{ formatPercent(result.total_return) }}
            </div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">年化收益率</div>
            <div class="metric-value" :class="getReturnClass(result.annual_return)">
              {{ formatPercent(result.annual_return) }}
            </div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">夏普比率</div>
            <div class="metric-value">{{ formatNumber(result.sharpe_ratio, 3) }}</div>
          </div>
        </el-col>
      </el-row>
      <el-row :gutter="20" style="margin-top: 20px;">
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">年化波动率</div>
            <div class="metric-value">{{ formatPercent(result.volatility) }}</div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">最大回撤</div>
            <div class="metric-value" :class="getReturnClass(result.max_drawdown)">
              {{ formatPercent(result.max_drawdown) }}
            </div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">Calmar比率</div>
            <div class="metric-value">{{ formatNumber(result.calmar_ratio, 3) }}</div>
          </div>
        </el-col>
      </el-row>
      <el-row :gutter="20" style="margin-top: 20px;">
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">交易次数</div>
            <div class="metric-value">{{ tradeCount }}</div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">收益回撤比</div>
            <div class="metric-value">
              {{ result.max_drawdown ? formatNumber(result.total_return / Math.abs(result.max_drawdown), 3) : '-' }}
            </div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="metric-item">
            <div class="metric-label">胜率</div>
            <div class="metric-value">
              {{ result.win_rate != null ? formatPercent(result.win_rate) : '-' }}
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 交易成本分析（优先用后端统一统计，避免前后端口径不一） -->
    <el-card shadow="never" style="margin-bottom: 20px;" v-if="totalCost > 0 || tradeCount > 0">
      <div slot="header">
        <span>💰 交易成本分析</span>
      </div>
      <el-row :gutter="20">
        <el-col :span="6">
          <div class="metric-item">
            <div class="metric-label">总手续费</div>
            <div class="metric-value">￥{{ formatCurrency(totalCommission) }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="metric-item">
            <div class="metric-label">总滑点成本</div>
            <div class="metric-value">￥{{ formatCurrency(totalSlippage) }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="metric-item">
            <div class="metric-label">总交易成本</div>
            <div class="metric-value">￥{{ formatCurrency(totalCost) }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="metric-item">
            <div class="metric-label">成本占比</div>
            <div class="metric-value">{{ formatPercent(costRatio) }}</div>
          </div>
        </el-col>
      </el-row>
      <div v-if="turnover != null" style="margin-top: 12px; font-size: 12px; color: #909399;">
        累计换手率（单边成交额 / 期初净值）：{{ formatPercent(turnover) }}
      </div>
    </el-card>

    <!-- 净值曲线和回撤 -->
    <el-card shadow="never" style="margin-bottom: 20px;" v-if="navData && navData.length > 0">
      <div slot="header">
        <span>净值与回撤走势</span>
      </div>
      <el-row :gutter="20">
        <el-col :span="12">
          <div :id="`nav-chart-${chartId}`" style="height: 400px; width: 100%;"></div>
        </el-col>
        <el-col :span="12">
          <div :id="`drawdown-chart-${chartId}`" style="height: 400px; width: 100%;"></div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 持仓权重变化 -->
    <el-card shadow="never" style="margin-bottom: 20px;" v-if="positionData && positionData.length > 0">
      <div slot="header">
        <span>持仓权重变化</span>
      </div>
      <el-alert
        v-if="manualAdjustmentDates.length > 0"
        title="本次回测包含交互式权重调整"
        type="info"
        :closable="false"
        style="margin-bottom: 12px;"
      >
        <span>人工干预调仓日期：{{ manualAdjustmentDates.join('、') }}</span>
      </el-alert>
      <div class="position-chart-legend" style="margin-bottom: 8px; font-size: 12px; color: #606266;">
        <span style="margin-right: 16px;"><span style="display:inline-block;width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-bottom:7px solid #67C23A;vertical-align:middle;margin-right:4px;"></span> 权重初始化</span>
        <span style="margin-right: 16px;"><span style="display:inline-block;width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-bottom:7px solid #E6A23C;vertical-align:middle;margin-right:4px;"></span> 人工干预调仓</span>
        <span><span style="display:inline-block;width:6px;height:6px;background:#409EFF;border-radius:50%;vertical-align:middle;margin-right:4px;"></span> 自动调仓（周期性/波动率重置）</span>
      </div>
      <div :id="`position-chart-${chartId}`" style="height: 400px; width: 100%;"></div>
    </el-card>

    <!-- 波动率监控 -->
    <el-card shadow="never" style="margin-bottom: 20px;" v-if="volatilityData && volatilityData.length > 0">
      <div slot="header">
        <span>组合波动率监控</span>
      </div>
      <div class="volatility-chart-legend" style="margin-bottom: 8px; font-size: 12px; color: #606266;">
        <strong>图注：</strong>
        <span style="margin-right: 20px;"><span style="display:inline-block;width:8px;height:8px;background:#E6A23C;border-radius:50%;vertical-align:middle;margin-right:6px;"></span>橙色圆点 = 人工干预调仓日</span>
        <span style="margin-right: 20px;"><span style="display:inline-block;width:8px;height:8px;background:#409EFF;border-radius:50%;vertical-align:middle;margin-right:6px;"></span>蓝色圆点 = 波动率重置调仓日</span>
        <span style="color:#909399;">（图上仅显示圆点，悬停可查看当日详情）</span>
      </div>
      <div :id="`volatility-chart-${chartId}`" style="height: 400px; width: 100%;"></div>
    </el-card>

    <!-- 子策略归因（仅组合回测返回）：逐日贡献精确可加，Σ贡献 + 残差 = 组合总收益 -->
    <el-card shadow="never" style="margin-bottom: 20px;" v-if="attributionRows.length > 0">
      <div slot="header">
        <span>子策略收益归因</span>
      </div>
      <el-table :data="attributionRows" size="mini" border style="width: 100%;">
        <el-table-column prop="name" label="子策略" min-width="140"></el-table-column>
        <el-table-column label="平均生效权重" width="120" align="right">
          <template slot-scope="{ row }">{{ formatPercent(row.avg_weight) }}</template>
        </el-table-column>
        <el-table-column label="子策略区间收益" width="130" align="right">
          <template slot-scope="{ row }">{{ formatPercent(row.sub_return) }}</template>
        </el-table-column>
        <el-table-column label="对组合贡献" width="120" align="right">
          <template slot-scope="{ row }">
            <span :class="getReturnClass(row.contribution)">{{ formatPercent(row.contribution) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="贡献占比" width="100" align="right">
          <template slot-scope="{ row }">{{ formatPercent(row.contribution_pct) }}</template>
        </el-table-column>
        <el-table-column label="相对等权基准" width="130" align="right">
          <template slot-scope="{ row }">
            <span :class="getReturnClass(row.allocation_effect)">{{ formatPercent(row.allocation_effect) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top: 10px; font-size: 12px; color: #909399; line-height: 1.8;">
        组合总收益 {{ formatPercent(attribution.total_return) }}
        = 已解释 {{ formatPercent(attribution.explained) }}
        + 残差 {{ formatPercent(attribution.residual) }}；
        「相对等权基准」= 本策略贡献 − 等权买入持有下的贡献（基准收益 {{ formatPercent(attribution.benchmark_return) }}）。
        <span v-if="attribution.method !== 'exact'">当前为静态权重近似口径，残差偏大属正常。</span>
      </div>
    </el-card>

    <!-- 分析与记录笔记（与策略详情页「历史回测记录」卡片编辑备注方式一致，仅当本次回测已关联记录时可编辑保存） -->
    <el-card shadow="never" style="margin-bottom: 20px;" class="remark-card">
      <div slot="header" class="remark-header">
        <span>📝 分析与记录笔记</span>
        <el-button v-if="canSaveRemark && !editingRemark" type="text" size="small" @click="startEditRemark">编辑备注</el-button>
        <span v-if="!canSaveRemark" style="color: #909399; font-size: 12px; margin-left: 8px;">（未关联回测记录，仅可查看）</span>
      </div>
      <!-- 已关联记录：与历史回测卡片一致的编辑/保存交互 -->
      <template v-if="canSaveRemark">
        <div v-if="!editingRemark" class="remark-content">
          <p v-if="displayRemark" style="white-space: pre-wrap; color: #606266; margin: 0;">{{ displayRemark }}</p>
          <p v-else style="color: #909399; margin: 0;">暂无备注。点击「编辑备注」添加本回测的分析与记录笔记，将保存到策略回测记录。</p>
        </div>
        <div v-else class="remark-edit">
          <el-input
            v-model="localRemark"
            type="textarea"
            :rows="4"
            placeholder="填写本回测的分析结论、记录要点等，将保存到策略回测记录"
            maxlength="500"
            show-word-limit
          ></el-input>
          <div style="margin-top: 10px;">
            <el-button type="primary" size="small" @click="saveRemark">保存</el-button>
            <el-button size="small" @click="cancelEditRemark">取消</el-button>
          </div>
        </div>
      </template>
      <!-- 未关联记录：仅展示已有备注，不提供保存，引导至策略详情页历史记录 -->
      <div v-else class="remark-content">
        <p v-if="displayRemark" style="white-space: pre-wrap; color: #606266; margin: 0;">{{ displayRemark }}</p>
        <p v-else style="color: #909399; margin: 0;">暂无备注。</p>
        <p style="color: #909399; font-size: 12px; margin: 8px 0 0 0;">本次回测未关联到可保存的记录，无法在此保存备注。请到「策略详情」页的「历史回测记录」中查找本回测并编辑备注。</p>
      </div>
    </el-card>

    <!-- 交易明细 -->
    <el-card shadow="never" v-if="result.trades && result.trades.length > 0">
      <div slot="header">
        <span>📋 交易明细</span>
      </div>
      <el-table :data="tradeTableData" border stripe max-height="400">
        <el-table-column prop="strategy_name" label="来源策略" width="140" v-if="hasStrategyNameInTrades">
          <template slot-scope="scope">
            <el-tag size="small" v-if="scope.row.strategy_name">{{ scope.row.strategy_name }}</el-tag>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="time" label="时间" width="120">
          <template slot-scope="scope">
            {{ formatDate(scope.row.time) }}
          </template>
        </el-table-column>
        <el-table-column prop="rebalanceLabel" label="调仓类型" width="110" align="center">
          <template slot-scope="scope">
            <el-tag :type="rebalanceLabelTagType(scope.row.rebalanceLabel)" size="small">
              {{ scope.row.rebalanceLabel || '—' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="thscode" label="资产代码" width="120"></el-table-column>
        <el-table-column prop="side" label="方向" width="80">
          <template slot-scope="scope">
            <el-tag :type="scope.row.side === 'buy' ? 'success' : 'danger'" size="small">
              {{ scope.row.side === 'buy' ? '买入' : '卖出' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="120" align="right">
          <template slot-scope="scope">
            {{ formatNumber(scope.row.quantity, 2) }}
          </template>
        </el-table-column>
        <el-table-column prop="price" label="价格" width="100" align="right">
          <template slot-scope="scope">
            {{ formatNumber(scope.row.price, 4) }}
          </template>
        </el-table-column>
        <el-table-column prop="commission" label="手续费" width="120" align="right">
          <template slot-scope="scope">
            ￥{{ formatCurrency(scope.row.commission) }}
          </template>
        </el-table-column>
        <el-table-column prop="slippage_cost" label="滑点成本" width="120" align="right">
          <template slot-scope="scope">
            ￥{{ formatCurrency(scope.row.slippage_cost) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import { debounce } from 'lodash';
import { updateBacktestRemark } from '@/api/strategy';
import { downsampleParallel } from '@/utils/downsample';

export default {
  name: 'SingleStrategyResult',
  props: {
    strategyName: {
      type: String,
      required: true
    },
    result: {
      type: Object,
      required: true
    },
    strategy: {
      type: Object,
      default: null
    },
    remark: {
      type: String,
      default: ''
    },
    recordId: {
      type: String,
      default: null
    },
    modelId: {
      type: String,
      default: null
    },
    /** 多策略对比时由父组件传入唯一 id（如 strategyId），避免同名策略导致图表 DOM id 冲突 */
    uniqueChartId: {
      type: String,
      default: null
    },
    /** 是否在多策略对比中展示（来自 MultiStrategyComparison），用于调整持仓权重图标注延迟与布局 */
    isMultiStrategy: {
      type: Boolean,
      default: false
    }
  },
  data() {
    return {
      editingRemark: false,
      localRemark: '',
      savedRemark: null, // 保存后本地显示，优先于 prop remark
      chartInstances: {} // 存储图表实例，用于清理
    };
  },
  computed: {
    /** 是否已关联回测记录（与历史回测卡片一致：有 modelId + recordId 才可保存备注） */
    canSaveRemark() {
      const mid = this.modelId != null && String(this.modelId).trim() !== '';
      const rid = this.recordId != null && String(this.recordId).trim() !== '';
      return mid && rid;
    },
    displayRemark() {
      return this.savedRemark !== null ? this.savedRemark : (this.remark || '');
    },
    chartId() {
      // 多策略对比时优先用传入的 uniqueChartId（如 strategyId）保证唯一，避免同名策略 DOM id 冲突导致只有第一个有图
      const base = (this.uniqueChartId != null && String(this.uniqueChartId).trim() !== '') ? String(this.uniqueChartId) : this.strategyName;
      return (base || '').replace(/[^a-zA-Z0-9_-]/g, '_') || 'default';
    },
    navData() {
      if (!this.result) return [];
      const snapshots = this.result.snapshots;
      if (snapshots && snapshots.length > 0) {
        const initialValue = snapshots[0].total_value || 1000000;
        return snapshots.map(s => ({
          date: this.formatDate(s.time),
          nav: s.total_value / initialValue,
          drawdown: s.drawdown != null ? s.drawdown : 0,
          time: s.time
        }));
      }
      if (this.result.equity_curve && this.result.equity_curve.length > 0) {
        const curve = this.result.equity_curve;
        const initialValue = (curve[0] && (curve[0].value != null ? curve[0].value : curve[0].unit_value)) || 1000000;
        return curve.map(p => {
          const v = p.value != null ? p.value : (p.unit_value != null ? p.unit_value * (initialValue || 1) : 0);
          return {
            date: this.formatDate(p.date),
            nav: initialValue ? v / initialValue : 1,
            drawdown: p.drawdown != null ? p.drawdown : 0,
            time: p.date
          };
        });
      }
      return [];
    },
    positionData() {
      if (!this.result || !this.result.snapshots || this.result.snapshots.length === 0) return [];
      // 只显示调仓日的持仓权重（含 rebalance_type 用于标识交互式调整等）
      return this.result.snapshots
        .filter(s => s.is_rebalance_day)
        .map(s => ({
          date: this.formatDate(s.time),
          weights: s.weights || {},
          time: s.time,
          rebalance_type: s.rebalance_type,
          rebalance_reason: s.rebalance_reason
        }));
    },
    volatilityData() {
      // 只展示后端（策略/控制层）给出的监控波动率。
      // 前端不再自行滞后估算：那一套公式（滚动21日×√252）与策略实际监控口径（多窗口取最大值）
      // 不一致，会把一个不存在的指标当成策略阈值展示。无数据时整张图隐藏。
      if (!this.result || !this.result.snapshots || this.result.snapshots.length === 0) return [];
      const withVol = this.result.snapshots.filter(
        s => s.portfolio_volatility !== null && s.portfolio_volatility !== undefined && s.portfolio_volatility !== 0
      );
      return withVol.map(s => ({
        date: this.formatDate(s.time),
        volatility: s.portfolio_volatility,
        time: s.time,
        isVolReset: s.rebalance_type === 'vol_reset' || (s.rebalance_reason && s.rebalance_reason.indexOf('波动率重置') >= 0),
        isRebalanceDay: !!s.is_rebalance_day,
        isManualAdjustment: s.rebalance_type === 'manual_adjustment' || (s.rebalance_reason && s.rebalance_reason.indexOf('交互式') >= 0)
      }));
    },
    tradeTableData() {
      if (!this.result.trades) return [];
      return this.result.trades.map(t => ({
        time: t.time,
        strategy_name: t.strategy_name || null,
        thscode: t.thscode,
        side: t.side,
        quantity: t.quantity,
        price: t.price,
        commission: t.commission || 0,
        slippage_cost: t.slippage_cost || 0,
        rebalanceLabel: t.rebalance_label || this.rebalanceLabelFromTypeReason(t.rebalance_type, t.rebalance_reason)
      }));
    },
    /** 交易明细中是否包含策略来源名称（组合回测时有值） */
    hasStrategyNameInTrades() {
      if (!this.result.trades || this.result.trades.length === 0) return false;
      return this.result.trades.some(t => t.strategy_name);
    },
    /** 后端如实上报的数据质量告警（指标不做钳制，仅提示解读口径） */
    warnings() {
      const list = this.result && this.result.warnings;
      return Array.isArray(list) ? list : [];
    },
    /** 成交笔数：优先用后端统计，缺失时回退交易明细条数 */
    tradeCount() {
      if (this.result && this.result.n_trades != null) return this.result.n_trades;
      return (this.result && this.result.trades) ? this.result.trades.length : 0;
    },
    /** 累计换手率（后端统计口径：单边成交额 / 期初净值），后端未给出时不展示 */
    turnover() {
      return (this.result && this.result.turnover != null) ? this.result.turnover : null;
    },
    totalCommission() {
      // 优先用后端统一统计，避免与后端成本口径出现两套算法
      if (this.result && this.result.total_commission != null) return this.result.total_commission;
      if (!this.result.trades) return 0;
      return this.result.trades.reduce((sum, t) => sum + (t.commission || 0), 0);
    },
    totalSlippage() {
      if (this.result && this.result.total_slippage != null) return this.result.total_slippage;
      if (!this.result.trades) return 0;
      return this.result.trades.reduce((sum, t) => sum + (t.slippage_cost || 0), 0);
    },
    totalCost() {
      return this.totalCommission + this.totalSlippage;
    },
    costRatio() {
      if (!this.result.snapshots || this.result.snapshots.length === 0) return 0;
      const initialValue = this.result.snapshots[0].total_value || 1000000;
      return this.totalCost / initialValue;
    },
    /** 子策略收益归因（仅组合回测返回） */
    attribution() {
      return (this.result && this.result.attribution) ? this.result.attribution : {};
    },
    /** 归因表格数据：按对组合贡献降序 */
    attributionRows() {
      const bySub = this.attribution.by_sub;
      if (!bySub || typeof bySub !== 'object') return [];
      return Object.keys(bySub)
        .map(name => Object.assign({ name }, bySub[name]))
        .sort((a, b) => (b.contribution || 0) - (a.contribution || 0));
    },
    manualAdjustmentDates() {
      if (!this.result.snapshots) return [];
      return this.result.snapshots
        .filter(s => s.is_rebalance_day && s.rebalance_type === 'manual_adjustment' && s.rebalance_reason !== '期初建仓' && !(s.rebalance_reason || '').includes('期初建仓'))
        .map(s => this.formatDate(s.time));
    }
  },
  watch: {
    result: {
      handler(newVal) {
        if (newVal && ((newVal.snapshots && newVal.snapshots.length > 0) || (newVal.equity_curve && newVal.equity_curve.length > 0))) {
          this.$nextTick(() => {
            setTimeout(() => this.initAllCharts(), 150);
          });
        }
      },
      deep: true
    },
    navData() {
      if (this.navData && this.navData.length > 0) {
        this.$nextTick(() => {
          setTimeout(() => {
            this.initNavChart();
            this.initDrawdownChart();
          }, 100);
        });
      }
    },
    positionData() {
      if (this.positionData && this.positionData.length > 0) {
        this.$nextTick(() => {
          setTimeout(() => {
            this.initPositionChart();
          }, 100);
        });
      }
    },
    volatilityData() {
      if (this.volatilityData && this.volatilityData.length > 0) {
        this.$nextTick(() => {
          setTimeout(() => {
            this.initVolatilityChart();
          }, 100);
        });
      }
    }
  },
  mounted() {
    console.log('[BacktestRecord] SingleStrategyResult mounted', 'strategyName=', this.strategyName, 'modelId=', this.modelId, 'recordId=', this.recordId, 'canSaveRemark=', this.canSaveRemark);
    // 创建防抖的 resize handler（所有图表共享一个）
    this._resizeHandler = debounce(() => {
      Object.values(this.chartInstances).forEach(chart => {
        if (chart && !chart.isDisposed()) {
          chart.resize();
          // position chart 需要额外更新 graphic 定位
          if (chart._updateGraphicPositions) {
            setTimeout(chart._updateGraphicPositions, this.isMultiStrategy ? 150 : 50);
          }
        }
      });
    }, 200);
    window.addEventListener('resize', this._resizeHandler);
    // 延迟初始化，确保DOM完全渲染
    setTimeout(() => {
      this.initAllCharts();
    }, 300);
  },
  beforeDestroy() {
    // 移除统一的 resize 监听器
    if (this._resizeHandler) {
      window.removeEventListener('resize', this._resizeHandler);
      this._resizeHandler = null;
    }
    // 销毁所有图表实例
    Object.values(this.chartInstances).forEach(chart => {
      if (chart && typeof chart.dispose === 'function') {
        chart.dispose();
      }
    });
    this.chartInstances = {};
  },
  methods: {
    startEditRemark() {
      this.editingRemark = true;
      this.localRemark = this.displayRemark;
    },
    cancelEditRemark() {
      this.editingRemark = false;
      this.localRemark = this.displayRemark;
    },
    /** 兼容旧数据：根据 rebalance_type / rebalance_reason 推导调仓类型文案 */
    rebalanceLabelFromTypeReason(type, reason) {
      const r = (reason || '').trim();
      const t = (type || '').trim();
      if (/期初建仓/.test(r) || (t === 'manual_adjustment' && (/期初建仓/.test(r) || !r))) return '初始化仓位';
      if (t === 'manual_adjustment') return '主观调仓';
      if (t === 'vol_reset') return '波动率重置';
      if (t === 'regular' || /周期性/.test(r)) return '周期性调仓';
      return null;
    },
    rebalanceLabelTagType(label) {
      if (!label) return 'info';
      if (label === '初始化仓位') return 'success';
      if (label === '主观调仓') return 'warning';
      if (label === '周期性调仓') return 'primary';
      if (label === '波动率重置') return '';
      return 'info';
    },
    /** 保存备注（与策略详情页历史回测卡片 saveRemark(record) 同一接口，仅在有 canSaveRemark 时展示按钮） */
    async saveRemark() {
      console.log('[BacktestRecord] saveRemark 调用 modelId=', this.modelId, 'recordId=', this.recordId, 'canSaveRemark=', this.canSaveRemark);
      if (!this.canSaveRemark) {
        this.$message.warning('未关联回测记录，无法保存。请到策略详情页「历史回测记录」中编辑备注。');
        return;
      }
      try {
        await updateBacktestRemark(this.modelId, this.recordId, this.localRemark);
        this.savedRemark = this.localRemark;
        this.$message.success('备注已保存');
        this.editingRemark = false;
        console.log('[BacktestRecord] saveRemark 成功');
      } catch (err) {
        console.error('[BacktestRecord] saveRemark 失败', err.response || err);
        this.$message.error(err.response?.data?.detail || err.message || '保存失败');
      }
    },
    initAllCharts() {
      this.$nextTick(() => {
        const navEl = document.getElementById(`nav-chart-${this.chartId}`);
        const hasSize = navEl && navEl.offsetWidth > 0 && navEl.offsetHeight > 0;
        if (!hasSize) return;
        // 分帧渲染：逐个 requestAnimationFrame 降低主线程阻塞
        const tasks = [];
        if (this.navData && this.navData.length > 0) {
          tasks.push(() => this.initNavChart());
          tasks.push(() => this.initDrawdownChart());
        }
        if (this.positionData && this.positionData.length > 0) {
          tasks.push(() => this.initPositionChart());
        }
        if (this.volatilityData && this.volatilityData.length > 0) {
          tasks.push(() => this.initVolatilityChart());
        }
        const runNext = (index) => {
          if (index >= tasks.length) return;
          requestAnimationFrame(() => {
            tasks[index]();
            runNext(index + 1);
          });
        };
        runNext(0);
      });
    },
    initNavChart() {
      const chartDom = document.getElementById(`nav-chart-${this.chartId}`);
      if (!chartDom || chartDom.offsetWidth === 0) return;
      const key = `nav-chart-${this.chartId}`;
      let myChart = this.chartInstances[key];
      if (!myChart || myChart.isDisposed()) {
        myChart = echarts.init(chartDom);
        this.chartInstances[key] = myChart;
      }
      
      let dates = this.navData.map(d => d.date);
      let navs = this.navData.map(d => d.nav);
      let drawdowns = this.navData.map(d => (d.drawdown || 0) * 100);

      // 降采样：限制最多 500 个数据点，避免大数据量时 ECharts 卡顿
      const sampledNav = downsampleParallel(dates, navs, 500);
      dates = sampledNav.dates;
      navs = sampledNav.values;
      const sampledDD = downsampleParallel(dates, drawdowns, 500);
      drawdowns = sampledDD.values;

      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: (params) => {
            let html = `${params[0].axisValue}<br />`;
            params.forEach(p => {
              if (p.seriesName === '净值') {
                html += `${p.marker} ${p.seriesName}: ${p.value != null ? p.value.toFixed(4) : '-'}<br />`;
              } else if (p.seriesName === '回撤') {
                html += `${p.marker} ${p.seriesName}: ${p.value != null ? p.value.toFixed(2) + '%' : '-'}<br />`;
              }
            });
            return html;
          }
        },
        legend: {
          data: ['净值', '回撤']
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: dates
        },
        yAxis: [
          {
            type: 'value',
            name: '净值',
            position: 'left',
            scale: true,
            axisLabel: {
              formatter: '{value}'
            }
          },
          {
            type: 'value',
            name: '回撤',
            position: 'right',
            axisLabel: {
              formatter: '{value}%'
            }
          }
        ],
        series: [
          {
            name: '净值',
            type: 'line',
            yAxisIndex: 0,
            data: navs,
            smooth: true,
            itemStyle: {
              color: '#409EFF'
            },
            markLine: {
              data: [
                { yAxis: 1.0, name: '基准线', lineStyle: { color: '#909399', type: 'dashed' } }
              ]
            }
          },
          {
            name: '回撤',
            type: 'line',
            yAxisIndex: 1,
            data: drawdowns,
            smooth: true,
            lineStyle: { width: 1.5 },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(245, 108, 108, 0.3)' },
                  { offset: 1, color: 'rgba(245, 108, 108, 0.02)' }
                ]
              }
            },
            itemStyle: {
              color: '#F56C6C'
            }
          }
        ]
      };

      myChart.setOption(option, true);
      
      // 延迟resize，确保容器有正确的尺寸
      setTimeout(() => {
        myChart.resize();
      }, 100);
    },
    initDrawdownChart() {
      const chartDom = document.getElementById(`drawdown-chart-${this.chartId}`);
      if (!chartDom || chartDom.offsetWidth === 0) return;
      const key = `drawdown-chart-${this.chartId}`;
      let myChart = this.chartInstances[key];
      if (!myChart || myChart.isDisposed()) {
        myChart = echarts.init(chartDom);
        this.chartInstances[key] = myChart;
      }
      
      let dates = this.navData.map(d => d.date);
      let drawdowns = this.navData.map(d => (d.drawdown || 0) * 100);

      // 降采样：限制最多 500 个数据点
      const sampledDD = downsampleParallel(dates, drawdowns, 500);
      dates = sampledDD.dates;
      drawdowns = sampledDD.values;

      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: (params) => {
            const param = params[0];
            return `${param.name}<br/>回撤: ${param.value.toFixed(2)}%`;
          }
        },
        title: {
          text: '回撤走势',
          left: 'center',
          textStyle: {
            fontSize: 14
          }
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: dates
        },
        yAxis: {
          type: 'value',
          name: '回撤 (%)',
          axisLabel: {
            formatter: '{value}%'
          }
        },
        series: [
          {
            name: '回撤',
            type: 'line',
            data: drawdowns,
            smooth: true,
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(245, 108, 108, 0.3)' },
                  { offset: 1, color: 'rgba(245, 108, 108, 0.1)' }
                ]
              }
            },
            itemStyle: {
              color: '#F56C6C'
            }
          }
        ]
      };

      myChart.setOption(option, true);
      
      // 延迟resize，确保容器有正确的尺寸
      setTimeout(() => {
        myChart.resize();
      }, 100);
    },
    initPositionChart() {
      const chartDom = document.getElementById(`position-chart-${this.chartId}`);
      if (!chartDom || chartDom.offsetWidth === 0) return;
      const key = `position-chart-${this.chartId}`;
      let myChart = this.chartInstances[key];
      if (!myChart || myChart.isDisposed()) {
        myChart = echarts.init(chartDom);
        this.chartInstances[key] = myChart;
      }

      const snapshots = this.result.snapshots || [];
      if (snapshots.length === 0) return;

      // 横轴：整个回测周期内所有交易日（非仅调仓日）
      const allDates = snapshots.map(s => this.formatDate(s.time));
      // 按日填充有效权重：当日为调仓日用当日权重，否则用最近一次调仓的权重
      let lastWeights = {};
      const dailyWeights = []; // dailyWeights[i] = { weights, rebalance_type, rebalance_reason } for allDates[i]
      snapshots.forEach((s, i) => {
        if (s.is_rebalance_day && s.weights) {
          lastWeights = { ...(s.weights || {}) };
        }
        dailyWeights.push({
          weights: { ...lastWeights },
          rebalance_type: s.is_rebalance_day ? (s.rebalance_type || null) : null,
          rebalance_reason: s.is_rebalance_day ? (s.rebalance_reason || null) : null
        });
      });

      // 收集资产代码
      const allAssets = new Set();
      dailyWeights.forEach(p => Object.keys(p.weights || {}).forEach(asset => allAssets.add(asset)));
      const assets = Array.from(allAssets);

      const assetNames = this.result.asset_names || {};
      const assetDisplayNames = {};
      assets.forEach(code => {
        const name = assetNames[code];
        assetDisplayNames[code] = (name && name.trim() && name !== code) ? `${code} - ${name}` : code;
      });

      // 系列数据：每个日期一个权重值
      const series = assets.map(asset => {
        const weights = allDates.map((_, i) => (dailyWeights[i].weights[asset] || 0) * 100);
        return {
          name: assetDisplayNames[asset],
          type: 'line',
          stack: 'total',
          areaStyle: {},
          emphasis: { focus: 'series' },
          data: weights
        };
      });

      // 纵轴边界：做空策略存在负权重，下界取「各日权重和」最小值（堆叠模式下即负向堆叠底边）；
      // 上限同时覆盖「单资产最大权重」，避免做空对冲场景单权重超出日权重和被裁剪；
      // 纯多头策略（无负权重）上下界行为与历史一致
      let maxWeightSumPercent = 0;
      let minWeightSumPercent = 0;
      let maxSingleWeightPercent = 0;
      dailyWeights.forEach(p => {
        const ws = Object.values(p.weights || {});
        const sum = ws.reduce((s, w) => s + (Number(w) || 0), 0) * 100;
        maxWeightSumPercent = Math.max(maxWeightSumPercent, sum);
        minWeightSumPercent = Math.min(minWeightSumPercent, sum);
        ws.forEach(w => {
          const v = (Number(w) || 0) * 100;
          if (v > maxSingleWeightPercent) maxSingleWeightPercent = v;
        });
      });
      const upperBoundPercent = Math.max(maxWeightSumPercent, maxSingleWeightPercent);
      const yAxisMax = upperBoundPercent <= 100 ? 100 : Math.max(100, Math.ceil(upperBoundPercent / 5) * 5);
      const yAxisMin = minWeightSumPercent >= 0 ? 0 : Math.floor(minWeightSumPercent / 5) * 5;

      const getRebalanceTypeLabel = (dayInfo) => {
        if (!dayInfo || !dayInfo.rebalance_type) return '持仓不变';
        const t = dayInfo.rebalance_type;
        const r = dayInfo.rebalance_reason || '';
        if (t === 'manual_adjustment' && (r === '期初建仓' || (r && r.indexOf('期初建仓') >= 0))) return '权重初始化';
        if (t === 'manual_adjustment' || r.indexOf('交互式') >= 0 || r.indexOf('预设') >= 0) return '人工干预调仓';
        if (t === 'vol_reset' || r.indexOf('波动率重置') >= 0) return '自动调仓（波动率重置）';
        return '自动调仓（周期性）';
      };

      const manualAndInitDates = dailyWeights.map((p, i) => {
        const label = getRebalanceTypeLabel(p);
        if (label === '权重初始化' || label === '人工干预调仓') return { date: allDates[i], label, index: i };
        return null;
      }).filter(Boolean);
      const markLineData = manualAndInitDates.map(({ date, label }) => ({
        xAxis: date,
        lineStyle: { color: label === '权重初始化' ? '#67C23A' : '#E6A23C', type: 'solid', width: 2 },
        label: { show: false }
      }));

      // 纵轴标签「权重(%)」置于最上方，调仓标注在其下方（margin 区）、与调仓竖线水平对齐
      const Y_LABEL_TOP = 2;
      const REBALANCE_LABEL_TOP_BASE = 26; // 位于「权重(%)」下方、grid 上方
      const yAxisLabelGraphic = {
        type: 'text',
        left: 25,
        top: Y_LABEL_TOP,
        rotation: 0,
        style: { text: '权重 (%)', fontSize: 12, fill: '#333', fontWeight: 'normal' },
        z: 100
      };
      const n = allDates.length;
      const graphicLabels = [
        yAxisLabelGraphic,
        ...manualAndInitDates.map(({ label, index }) => {
          const pct = n > 1 ? 22 + (index / (n - 1)) * 56 : 50;
          return {
            type: 'text',
            left: pct + '%',
            top: REBALANCE_LABEL_TOP_BASE,
            rotation: 0,
            style: {
              text: label === '权重初始化' ? '权重初始化' : '人工干预',
              fontSize: 12,
              fill: label === '权重初始化' ? '#67C23A' : '#E6A23C',
              fontWeight: 'normal'
            },
            z: 100
          };
        })
      ];

      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          confine: true,
          padding: 10,
          extraCssText: 'max-width: 320px;',
          formatter: (params) => {
            const date = params[0].axisValue;
            const idx = allDates.indexOf(date);
            const dayInfo = idx >= 0 ? dailyWeights[idx] : null;
            const typeLabel = getRebalanceTypeLabel(dayInfo);
            let result = `${date}<br /><strong>调仓类型：${typeLabel}</strong><br />`;
            params.forEach(param => {
              const value = param.value;
              const weight = Array.isArray(value) ? value[value.length - 1] : value;
              if (weight !== undefined && weight !== null) {
                result += `${param.seriesName}: ${parseFloat(weight).toFixed(2)}%<br />`;
              } else {
                result += `${param.seriesName}: -<br />`;
              }
            });
            return result;
          }
        },
        legend: {
          data: assets.map(code => assetDisplayNames[code]),
          bottom: 0,
          type: 'scroll'
        },
        grid: {
          left: 80,
          right: '4%',
          top: 70,
          bottom: '22%',
          containLabel: true
        },
        graphic: graphicLabels,
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: allDates
        },
        yAxis: {
          type: 'value',
          name: '',
          nameGap: 25,
          axisLabel: {
            formatter: '{value}%',
            margin: 10
          },
          min: yAxisMin,
          max: yAxisMax
        },
        series: series.map((s, i) => ({
          ...s,
          markLine: i === 0 && markLineData.length > 0 ? { symbol: 'none', data: markLineData } : undefined
        }))
      };

      myChart.setOption(option, true);
      myChart.resize();

      // 使用 convertToPixel 精确对齐文字与调仓竖线，重叠时错行展示，文字横向（与图1单策略一致）
      const updateGraphicPositions = () => {
        if (!chartDom || chartDom.offsetWidth === 0) return;
        try {
          const LABEL_GAP = 8;
          const ROW_HEIGHT = 18;
          const FONT_SIZE = 12;
          const charWidth = 12;
          const chartWidth = chartDom.offsetWidth || 400;

          const rawEls = manualAndInitDates.map(({ date, label, index }) => {
            // 与 markLine 竖线对齐：优先用 date 获取类别中心像素，fallback 用 index+0.5
            let point = myChart.convertToPixel({ gridIndex: 0 }, [date, 0]);
            if (!point || point[0] == null) {
              point = myChart.convertToPixel({ gridIndex: 0 }, [index + 0.5, 0]);
            }
            if (point && point[0] != null) {
              const text = label === '权重初始化' ? '权重初始化' : '人工干预';
              const textWidth = text.length * charWidth;
              const centerX = point[0];
              let left = centerX - textWidth / 2;
              // 优先保证与竖线对齐，仅避免超出图表边界
              left = Math.max(0, Math.min(left, chartWidth - textWidth - 8));
              return { left, textWidth, text, label, point: centerX };
            }
            return null;
          }).filter(Boolean);

          // 按 left 排序，重叠时错行
          rawEls.sort((a, b) => a.left - b.left);
          const positioned = [];
          for (let i = 0; i < rawEls.length; i++) {
            const curr = rawEls[i];
            let row = 0;
            for (;;) {
              const conflict = positioned.filter(p => p.row === row).some(p =>
                curr.left < p.left + p.textWidth + LABEL_GAP && curr.left + curr.textWidth + LABEL_GAP > p.left
              );
              if (!conflict) break;
              row++;
            }
            positioned.push({ ...curr, row });
          }

          const rebalanceEls = positioned.map(({ left, textWidth, text, label, row }) => ({
            type: 'text',
            left: Math.round(left),
            top: REBALANCE_LABEL_TOP_BASE + row * ROW_HEIGHT,
            rotation: 0,
            bounding: 'raw',
            style: {
              text,
              fontSize: FONT_SIZE,
              fill: label === '权重初始化' ? '#67C23A' : '#E6A23C',
              fontWeight: 'normal'
            },
            z: 100
          }));
          const yLabelEl = { type: 'text', left: 25, top: 2, rotation: 0, bounding: 'raw', style: { text: '权重 (%)', fontSize: 12, fill: '#333', fontWeight: 'normal' }, z: 100 };
          const els = [yLabelEl, ...rebalanceEls];

          if (els.length > 0) {
            myChart.setOption({ graphic: els }, { replaceMerge: ['graphic'] });
          }
        } catch (e) {
          // 保持初始百分比定位
        }
      };
      const graphicDelay = this.isMultiStrategy ? 550 : 250;
      setTimeout(updateGraphicPositions, graphicDelay);

      // 为 position chart 额外注册 graphic 定位更新（由统一 resize handler 触发后补偿）
      myChart._updateGraphicPositions = updateGraphicPositions;
    },
    initVolatilityChart() {
      const chartDom = document.getElementById(`volatility-chart-${this.chartId}`);
      if (!chartDom || chartDom.offsetWidth === 0) return;
      const key = `volatility-chart-${this.chartId}`;
      let myChart = this.chartInstances[key];
      if (!myChart || myChart.isDisposed()) {
        myChart = echarts.init(chartDom);
        this.chartInstances[key] = myChart;
      }
      // 降采样波动率数据：保留完整元数据用于 tooltip 和 markPoint
      const MAX_VOL_POINTS = 500;
      let sampledVolData = this.volatilityData;
      if (this.volatilityData.length > MAX_VOL_POINTS) {
        const step = (this.volatilityData.length - 1) / (MAX_VOL_POINTS - 1);
        const indices = [];
        for (let k = 0; k < MAX_VOL_POINTS; k++) {
          indices.push(Math.round(k * step));
        }
        sampledVolData = indices.map(idx => this.volatilityData[idx]);
      }

      const dates = sampledVolData.map(d => d.date);
      const volatilities = sampledVolData.map(d => (d.volatility || 0) * 100);

      // 调仓类型文案（波动率图按日，仅调仓日有含义）
      const getVolRebalanceLabel = (d) => {
        if (!d || !d.isRebalanceDay) return '';
        if (d.isManualAdjustment) return '人工干预调仓';
        if (d.isVolReset) return '自动调仓（波动率重置）';
        return '自动调仓（周期性）';
      };

      // 波动率重置日：markPoint 标注
      const volResetPoints = sampledVolData
        .map((d, i) => (d.isVolReset ? { name: '波动率重置', coord: [i, (d.volatility || 0) * 100] } : null))
        .filter(Boolean);
      // 人工干预调仓日：markPoint 标注（与波动率重置区分）
      const manualPoints = sampledVolData
        .map((d, i) => (d.isRebalanceDay && d.isManualAdjustment ? { name: '人工干预', coord: [i, (d.volatility || 0) * 100] } : null))
        .filter(Boolean);

      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          formatter: (params) => {
            const param = params[0];
            const idx = param.dataIndex;
            const d = sampledVolData[idx];
            const typeLabel = getVolRebalanceLabel(d);
            let html = `${param.name}<br/>组合波动率: ${(param.value != null ? param.value : 0).toFixed(2)}%`;
            if (typeLabel) html += `<br/><strong>调仓类型：${typeLabel}</strong>`;
            if (d && d.isVolReset) html += '<br/><span style="color:#E6A23C">◆ 波动率重置</span>';
            if (d && d.isManualAdjustment) html += '<br/><span style="color:#E6A23C">◆ 人工干预</span>';
            return html;
          }
        },
        grid: {
          left: '8%',
          right: '14%',
          bottom: '3%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: dates
        },
        yAxis: {
          type: 'value',
          name: '年化波动率 (%)',
          axisLabel: {
            formatter: '{value}%'
          }
        },
        series: [
          {
            name: '组合波动率',
            type: 'line',
            data: volatilities,
            smooth: true,
            itemStyle: {
              color: '#409EFF'
            },
            markPoint: (volResetPoints.length > 0 || manualPoints.length > 0) ? {
              symbol: 'circle',
              symbolSize: 8,
              data: [
                ...volResetPoints.map(p => ({ ...p, name: '波动率重置', itemStyle: { color: '#409EFF' }, label: { show: false } })),
                ...manualPoints.map(p => ({ ...p, name: '人工干预', itemStyle: { color: '#E6A23C' }, label: { show: false } }))
              ],
              emphasis: {
                label: { show: true, formatter: '{b}' }
              }
            } : undefined
          }
        ]
      };

      myChart.setOption(option, true);
      
      // 延迟resize，确保容器有正确的尺寸
      setTimeout(() => {
        myChart.resize();
      }, 100);
    },
    formatPercent(num) {
      if (num === null || num === undefined) return '-';
      return (num * 100).toFixed(2) + '%';
    },
    formatNumber(num, precision = 2) {
      if (num === null || num === undefined) return '-';
      return parseFloat(num).toFixed(precision);
    },
    formatCurrency(num) {
      if (num === null || num === undefined) return '0.00';
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num);
    },
    formatDate(dateStr) {
      if (!dateStr) return '-';
      if (typeof dateStr === 'string') {
        return dateStr.substring(0, 10);
      }
      try {
        const date = new Date(dateStr);
        return date.toISOString().split('T')[0];
      } catch (e) {
        return dateStr;
      }
    },
    getReturnClass(ret) {
      if (ret > 0) return 'positive';
      if (ret < 0) return 'negative';
      return '';
    }
  }
};
</script>

<style scoped>
.single-strategy-result {
  padding: 20px 0;
}

.metric-item {
  text-align: center;
  padding: 15px;
  background: #f5f7fa;
  border-radius: 4px;
}

.metric-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.metric-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.metric-value.positive {
  color: #F56C6C;
}

.metric-value.negative {
  color: #67C23A;
}

[id^="nav-chart-"],
[id^="drawdown-chart-"],
[id^="position-chart-"],
[id^="volatility-chart-"] {
  width: 100%;
  min-height: 400px;
}

.remark-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
