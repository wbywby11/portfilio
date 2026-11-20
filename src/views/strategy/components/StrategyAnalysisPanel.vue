<template>
  <el-card shadow="never" class="analysis-card">
    <div slot="header" class="analysis-header">
      <span class="analysis-title">策略多维验证</span>
      <span class="analysis-sub">基于所选策略模型与上方回测区间独立重跑，不依赖上方回测结果</span>
    </div>

    <el-empty
      v-if="!strategy || isPortfolio"
      :image-size="70"
      :description="isPortfolio
        ? '投资组合不支持多维验证，请在「选择策略」中改为单个策略模型'
        : '请先在「选择策略」中选择要验证的策略模型'"
    ></el-empty>

    <el-tabs v-else v-model="activeTab">
      <!-- ── 参数敏感度 ─────────────────────────────────────────────── -->
      <el-tab-pane label="参数敏感度" name="sensitivity">
        <div class="analysis-toolbar">
          <span class="analysis-field-label">扫描参数</span>
          <el-select
            v-model="sensitivity.paramName"
            size="small"
            style="width: 220px;"
            :disabled="!numericParams.length"
            @change="handleParamNameChange"
          >
            <el-option
              v-for="p in numericParams"
              :key="p.name"
              :label="p.label"
              :value="p.name"
            ></el-option>
          </el-select>
          <span class="analysis-field-label">参数值</span>
          <el-input
            v-model="sensitivity.valuesText"
            size="small"
            style="width: 240px;"
            placeholder="多个值用逗号分隔，如 8,10,12"
            :disabled="!numericParams.length"
          ></el-input>
          <el-button
            type="primary"
            size="small"
            :loading="sensitivity.loading"
            :disabled="!canRun || !numericParams.length"
            @click="handleSensitivityRun"
          >运行分析</el-button>
        </div>
        <div class="analysis-hint">
          每个参数值独立跑一次完整回测（单次最多 10 个值），用于判断绩效对该参数的敏感程度。
        </div>

        <el-alert
          v-if="!numericParams.length"
          type="warning"
          :closable="false"
          show-icon
          title="该策略模型没有可扫描的数值参数"
          style="margin-top: 12px;"
        ></el-alert>
        <el-alert
          v-if="sensitivity.error"
          type="error"
          :closable="false"
          show-icon
          :title="sensitivity.error"
          style="margin-top: 12px;"
        ></el-alert>

        <template v-if="sensitivity.result">
          <div class="analysis-summary">
            共 {{ sensitivity.result.total_runs }} 次回测，成功 {{ sensitivity.result.successful_runs }} 次
          </div>
          <el-table :data="sensitivityRows" size="small" border style="width: 100%;">
            <el-table-column :label="sensitivityParamLabel" width="140" align="right">
              <template slot-scope="{ row }">{{ row.paramValue }}</template>
            </el-table-column>
            <el-table-column label="年化收益（260日）" width="130" align="right">
              <template slot-scope="{ row }">
                <span :class="pctClass(row.m && row.m.annual_return)">{{ pct(row.m && row.m.annual_return) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="年化收益（365日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_return_365) }}</template>
            </el-table-column>
            <el-table-column label="年化波动（260日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_vol) }}</template>
            </el-table-column>
            <el-table-column label="年化波动（365日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_vol_365) }}</template>
            </el-table-column>
            <el-table-column label="夏普（260日）" width="105" align="right">
              <template slot-scope="{ row }">{{ num(row.m && row.m.sharpe) }}</template>
            </el-table-column>
            <el-table-column label="夏普（365日）" width="105" align="right">
              <template slot-scope="{ row }">{{ num(row.m && row.m.sharpe_365) }}</template>
            </el-table-column>
            <el-table-column label="最大回撤" width="110" align="right">
              <template slot-scope="{ row }">
                <span class="number-negative">{{ pct(row.m && row.m.max_drawdown) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="总收益" width="110" align="right">
              <template slot-scope="{ row }">
                <span :class="pctClass(row.m && row.m.total_return)">{{ pct(row.m && row.m.total_return) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="成交笔数" width="100" align="right">
              <template slot-scope="{ row }">{{ intText(row.m && row.m.n_trades) }}</template>
            </el-table-column>
            <el-table-column label="状态" min-width="90" align="center">
              <template slot-scope="{ row }">
                <span v-if="row.m" class="analysis-pass">成功</span>
                <el-tooltip v-else :content="row.error || '回测未返回指标'" placement="top">
                  <span class="analysis-fail">失败</span>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="sensitivityFailedCount > 0" class="analysis-hint">
            失败的参数值不产生指标，悬停「失败」可查看原因。
          </div>
        </template>
      </el-tab-pane>

      <!-- ── 情景推演 ───────────────────────────────────────────────── -->
      <el-tab-pane label="情景推演" name="scenario">
        <div
          v-for="(row, index) in scenario.rows"
          :key="row.key"
          class="scenario-row"
        >
          <el-select
            v-model="row.asset"
            size="small"
            filterable
            placeholder="选择资产"
            style="width: 260px;"
          >
            <el-option
              v-for="a in assetOptions"
              :key="a.code"
              :label="a.label"
              :value="a.code"
            ></el-option>
          </el-select>
          <el-input-number
            v-model="row.shockPct"
            size="small"
            :min="-95"
            :max="500"
            :step="1"
            :precision="1"
            style="width: 150px;"
          ></el-input-number>
          <span class="analysis-unit">%</span>
          <el-button
            type="text"
            icon="el-icon-delete"
            :disabled="scenario.rows.length === 1"
            @click="handleRemoveScenarioRow(index)"
          ></el-button>
        </div>
        <div class="analysis-toolbar">
          <el-button size="small" icon="el-icon-plus" @click="handleAddScenarioRow">新增资产</el-button>
          <el-button
            type="primary"
            size="small"
            :loading="scenario.loading"
            :disabled="!canRun || !assetOptions.length"
            @click="handleScenarioRun"
          >运行推演</el-button>
        </div>
        <div class="analysis-hint">
          冲击自回测起始日的下一个交易日起生效：该资产价格整体乘以（1 + 冲击幅度），此后保持同一比例，
          用于观察极端行情下的组合表现。正数为上涨，负数为下跌。
        </div>

        <el-alert
          v-if="!assetOptions.length"
          type="warning"
          :closable="false"
          show-icon
          title="该策略模型没有资产池，无法设置情景冲击"
          style="margin-top: 12px;"
        ></el-alert>
        <el-alert
          v-if="scenario.error"
          type="error"
          :closable="false"
          show-icon
          :title="scenario.error"
          style="margin-top: 12px;"
        ></el-alert>

        <template v-if="scenario.result">
          <div class="analysis-summary">{{ scenario.result.scenario_desc }}</div>
          <el-table :data="scenarioRows" size="small" border style="width: 100%;">
            <el-table-column label="口径" width="150">
              <template slot-scope="{ row }">{{ row.label }}</template>
            </el-table-column>
            <el-table-column label="年化收益（260日）" width="130" align="right">
              <template slot-scope="{ row }">
                <span :class="pctClass(row.m && row.m.annual_return)">{{ pct(row.m && row.m.annual_return) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="年化收益（365日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_return_365) }}</template>
            </el-table-column>
            <el-table-column label="年化波动（260日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_vol) }}</template>
            </el-table-column>
            <el-table-column label="年化波动（365日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_vol_365) }}</template>
            </el-table-column>
            <el-table-column label="夏普（260日）" width="105" align="right">
              <template slot-scope="{ row }">{{ num(row.m && row.m.sharpe) }}</template>
            </el-table-column>
            <el-table-column label="夏普（365日）" width="105" align="right">
              <template slot-scope="{ row }">{{ num(row.m && row.m.sharpe_365) }}</template>
            </el-table-column>
            <el-table-column label="最大回撤" width="110" align="right">
              <template slot-scope="{ row }">
                <span class="number-negative">{{ pct(row.m && row.m.max_drawdown) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="Calmar" width="90" align="right">
              <template slot-scope="{ row }">{{ num(row.m && row.m.calmar) }}</template>
            </el-table-column>
            <el-table-column label="总收益" width="110" align="right">
              <template slot-scope="{ row }">
                <span :class="pctClass(row.m && row.m.total_return)">{{ pct(row.m && row.m.total_return) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="成交笔数" width="100" align="right">
              <template slot-scope="{ row }">{{ intText(row.m && row.m.n_trades) }}</template>
            </el-table-column>
            <el-table-column label="手续费" width="110" align="right">
              <template slot-scope="{ row }">{{ money(row.m && row.m.total_commission) }}</template>
            </el-table-column>
            <el-table-column label="滑点" width="110" align="right">
              <template slot-scope="{ row }">{{ money(row.m && row.m.total_slippage) }}</template>
            </el-table-column>
          </el-table>
          <div v-if="scenarioErrors.length" class="analysis-hint">
            {{ scenarioErrors.join('；') }}
          </div>
        </template>
      </el-tab-pane>

      <!-- ── 鲁棒性检验 ─────────────────────────────────────────────── -->
      <el-tab-pane label="鲁棒性检验" name="robustness">
        <div class="analysis-toolbar">
          <span class="analysis-field-label">子区间数量</span>
          <el-input-number
            v-model="robustness.nWindows"
            size="small"
            :min="2"
            :max="20"
            :step="1"
            style="width: 140px;"
          ></el-input-number>
          <el-button
            type="primary"
            size="small"
            :loading="robustness.loading"
            :disabled="!canRun"
            @click="handleRobustnessRun"
          >运行检验</el-button>
        </div>
        <div class="analysis-hint">
          将回测区间等分为若干子区间，每个子区间独立重跑；区间过短时后端会自动减少子区间数量。
        </div>

        <el-alert
          v-if="robustness.error"
          type="error"
          :closable="false"
          show-icon
          :title="robustness.error"
          style="margin-top: 12px;"
        ></el-alert>

        <template v-if="robustness.result">
          <div class="analysis-summary">
            实际 {{ robustness.result.n_windows }} 个子区间，成功 {{ robustness.result.successful_runs }} 个
          </div>

          <div class="analysis-block-title">指标稳定性</div>
          <el-table :data="robustnessSummaryRows" size="small" border style="width: 100%;">
            <el-table-column prop="label" label="指标" width="140"></el-table-column>
            <el-table-column label="均值" width="110" align="right">
              <template slot-scope="{ row }">
                <span :class="row.kind === 'pct' ? pctClass(row.mean) : ''">{{ row.kind === 'pct' ? pct(row.mean) : num(row.mean) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="标准差" width="110" align="right">
              <template slot-scope="{ row }">{{ row.kind === 'pct' ? pct(row.std) : num(row.std) }}</template>
            </el-table-column>
            <el-table-column label="最小" width="110" align="right">
              <template slot-scope="{ row }">
                <span :class="row.kind === 'pct' ? pctClass(row.min) : ''">{{ row.kind === 'pct' ? pct(row.min) : num(row.min) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="中位数" width="110" align="right">
              <template slot-scope="{ row }">{{ row.kind === 'pct' ? pct(row.median) : num(row.median) }}</template>
            </el-table-column>
            <el-table-column label="最大" width="110" align="right">
              <template slot-scope="{ row }">
                <span :class="row.kind === 'pct' ? pctClass(row.max) : ''">{{ row.kind === 'pct' ? pct(row.max) : num(row.max) }}</span>
              </template>
            </el-table-column>
          </el-table>

          <div class="analysis-block-title">子区间明细</div>
          <el-table :data="robustnessWindowRows" size="small" border style="width: 100%;">
            <el-table-column prop="window_index" label="窗口" width="70" align="center"></el-table-column>
            <el-table-column label="区间" min-width="190">
              <template slot-scope="{ row }">{{ row.start_date }} 至 {{ row.end_date }}</template>
            </el-table-column>
            <el-table-column label="年化收益（260日）" width="130" align="right">
              <template slot-scope="{ row }">
                <span :class="pctClass(row.m && row.m.annual_return)">{{ pct(row.m && row.m.annual_return) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="年化收益（365日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_return_365) }}</template>
            </el-table-column>
            <el-table-column label="年化波动（260日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_vol) }}</template>
            </el-table-column>
            <el-table-column label="年化波动（365日）" width="130" align="right">
              <template slot-scope="{ row }">{{ pct(row.m && row.m.annual_vol_365) }}</template>
            </el-table-column>
            <el-table-column label="夏普（260日）" width="105" align="right">
              <template slot-scope="{ row }">{{ num(row.m && row.m.sharpe) }}</template>
            </el-table-column>
            <el-table-column label="夏普（365日）" width="105" align="right">
              <template slot-scope="{ row }">{{ num(row.m && row.m.sharpe_365) }}</template>
            </el-table-column>
            <el-table-column label="最大回撤" width="110" align="right">
              <template slot-scope="{ row }">
                <span class="number-negative">{{ pct(row.m && row.m.max_drawdown) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" min-width="90" align="center">
              <template slot-scope="{ row }">
                <span v-if="row.m" class="analysis-pass">成功</span>
                <el-tooltip v-else :content="row.error || '回测未返回指标'" placement="top">
                  <span class="analysis-fail">失败</span>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<script>
import {
  runSensitivityAnalysis,
  runScenarioAnalysis,
  runRobustnessCheck
} from '@/api/strategy';

/** 汇总统计中按百分比展示的指标 */
const PCT_KEYS = ['annual_return', 'annual_vol', 'sharpe', 'max_drawdown'];
/** 情景对比差异行只对收益风险指标做差，成本类指标口径不同不参与 */
const DELTA_KEYS = ['annual_return', 'annual_vol', 'sharpe', 'max_drawdown', 'calmar', 'total_return'];

export default {
  name: 'StrategyAnalysisPanel',
  props: {
    /** 当前选中的策略模型（完整对象，含 parameters/asset_codes/asset_names） */
    strategy: {
      type: Object,
      default: null
    },
    /** 当前选择是否为投资组合（组合不支持按单模型分析） */
    isPortfolio: {
      type: Boolean,
      default: false
    },
    /** 回测区间 ['YYYY-MM-DD', 'YYYY-MM-DD'] */
    dateRange: {
      type: Array,
      default: () => []
    },
    initialCash: {
      type: Number,
      default: 1000000
    }
  },
  data() {
    return {
      activeTab: 'sensitivity',
      // 按需拉取的完整模型（参数与资产池以它为准，失败时回退 props.strategy）
      modelDetail: null,
      // 情景行自增 key（删除中间行时不复用输入组件状态）
      scenarioRowSeq: 1,
      sensitivity: {
        paramName: '',
        valuesText: '',
        loading: false,
        result: null,
        error: ''
      },
      scenario: {
        rows: [{ key: 1, asset: '', shockPct: -10 }],
        loading: false,
        result: null,
        error: ''
      },
      robustness: {
        nWindows: 5,
        loading: false,
        result: null,
        error: ''
      }
    };
  },
  computed: {
    /** 模型参数：优先取完整模型，其次取列表对象 */
    strategyParameters() {
      const detail = (this.modelDetail && this.modelDetail.parameters) || null;
      if (detail && Object.keys(detail).length) return detail;
      return (this.strategy && this.strategy.parameters) || {};
    },
    /** 可扫描的数值参数（布尔、字符串、对象不参与敏感度扫描） */
    numericParams() {
      const params = this.strategyParameters;
      const labels = this.paramLabels;
      return Object.keys(params)
        .filter(key => typeof params[key] === 'number' && Number.isFinite(params[key]))
        .map(key => ({
          name: key,
          label: labels[key] ? `${labels[key]}（${key}）` : key,
          value: params[key]
        }));
    },
    paramLabels() {
      const detailLabels = (this.modelDetail && this.modelDetail.parameter_labels) || {};
      const listLabels = (this.strategy && this.strategy.parameter_labels) || {};
      return { ...listLabels, ...detailLabels };
    },
    assetCodes() {
      const detail = (this.modelDetail && this.modelDetail.asset_codes) || [];
      if (detail.length) return detail;
      return (this.strategy && this.strategy.asset_codes) || [];
    },
    assetNames() {
      const listNames = (this.strategy && this.strategy.asset_names) || {};
      const detailNames = (this.modelDetail && this.modelDetail.asset_names) || {};
      return { ...listNames, ...detailNames };
    },
    assetOptions() {
      return this.assetCodes.map(code => ({ code, label: this.assetLabel(code) }));
    },
    /** 时间区间与模型就绪才允许发起分析 */
    canRun() {
      const [start, end] = this.dateRange || [];
      return !!(
        this.strategy &&
        !this.isPortfolio &&
        this.toApiDate(start) &&
        this.toApiDate(end)
      );
    },
    sensitivityParamLabel() {
      const hit = this.numericParams.find(p => p.name === this.sensitivity.paramName);
      return hit ? hit.label : '参数值';
    },
    sensitivityRows() {
      const list = (this.sensitivity.result && this.sensitivity.result.results) || [];
      return list.map(item => ({
        paramValue: item.param_value,
        m: item.metrics || null,
        error: item.error || ''
      }));
    },
    sensitivityFailedCount() {
      return this.sensitivityRows.filter(row => !row.m).length;
    },
    scenarioRows() {
      const result = this.scenario.result;
      if (!result) return [];
      const baseline = result.baseline_metrics || null;
      const shocked = result.scenario_metrics || null;
      const rows = [
        { label: '基线（未冲击）', m: baseline, error: result.baseline_error || '' },
        { label: '情景（已冲击）', m: shocked, error: result.scenario_error || '' }
      ];
      if (baseline && shocked) {
        const delta = {};
        DELTA_KEYS.forEach(key => {
          const a = baseline[key];
          const b = shocked[key];
          delta[key] = (a == null || b == null) ? null : Number(b) - Number(a);
        });
        rows.push({ label: '差异（情景 - 基线）', m: delta, error: '', isDelta: true });
      }
      return rows;
    },
    scenarioErrors() {
      const result = this.scenario.result;
      if (!result) return [];
      const messages = [];
      if (result.baseline_error) messages.push(`基线回测失败：${result.baseline_error}`);
      if (result.scenario_error) messages.push(`情景回测失败：${result.scenario_error}`);
      return messages;
    },
    robustnessSummaryRows() {
      const stats = (this.robustness.result && this.robustness.result.summary_stats) || {};
      const labelMap = {
        annual_return: '年化收益',
        annual_vol: '年化波动',
        sharpe: '夏普',
        max_drawdown: '最大回撤'
      };
      return PCT_KEYS
        .filter(key => stats[key])
        .map(key => ({
          key,
          label: labelMap[key],
          kind: key === 'sharpe' ? 'num' : 'pct',
          mean: stats[key].mean,
          std: stats[key].std,
          min: stats[key].min,
          max: stats[key].max,
          median: stats[key].median
        }));
    },
    robustnessWindowRows() {
      const list = (this.robustness.result && this.robustness.result.windows) || [];
      return list.map(item => ({
        window_index: item.window_index,
        start_date: this.displayDate(item.start_date),
        end_date: this.displayDate(item.end_date),
        m: item.metrics || null,
        error: item.error || ''
      }));
    }
  },
  watch: {
    'strategy.id': {
      immediate: true,
      handler(strategyId) {
        this.handleStrategyChange(strategyId);
      }
    },
    dateRange: {
      deep: true,
      handler() {
        // 结果绑定发起时的区间，区间变化后旧结果不再可信
        this.resetResults();
      }
    },
    initialCash() {
      this.resetResults();
    },
    numericParams: {
      immediate: true,
      handler(list) {
        if (!list.length) {
          this.sensitivity.paramName = '';
          this.sensitivity.valuesText = '';
          return;
        }
        const exists = list.some(p => p.name === this.sensitivity.paramName);
        if (!exists) {
          const first = list[0];
          this.sensitivity.paramName = first.name;
          this.sensitivity.valuesText = String(first.value);
        }
      }
    }
  },
  methods: {
    async handleStrategyChange(strategyId) {
      this.resetResults();
      this.modelDetail = null;
      this.scenario.rows = [{ key: 1, asset: '', shockPct: -10 }];
      this.scenarioRowSeq = 1;
      if (!strategyId || String(strategyId).startsWith('portfolio:')) return;
      try {
        const model = await this.$store.dispatch('strategy/fetchStrategyModel', strategyId);
        // 异步返回时用户可能已切换策略，避免用旧模型覆盖新选择
        if (this.strategy && this.strategy.id === strategyId) {
          this.modelDetail = model || null;
        }
      } catch (error) {
        console.error('加载策略模型参数失败:', strategyId, error);
        this.modelDetail = null;
      }
    },
    resetResults() {
      this.sensitivity.result = null;
      this.sensitivity.error = '';
      this.scenario.result = null;
      this.scenario.error = '';
      this.robustness.result = null;
      this.robustness.error = '';
    },
    handleParamNameChange(name) {
      const hit = this.numericParams.find(p => p.name === name);
      this.sensitivity.valuesText = hit ? String(hit.value) : '';
      this.sensitivity.result = null;
      this.sensitivity.error = '';
    },
    handleAddScenarioRow() {
      this.scenarioRowSeq += 1;
      this.scenario.rows.push({ key: this.scenarioRowSeq, asset: '', shockPct: -10 });
    },
    handleRemoveScenarioRow(index) {
      this.scenario.rows.splice(index, 1);
    },
    async handleSensitivityRun() {
      if (!this.canRun) {
        this.$message.warning('请先选择策略模型并配置完整的回测时间');
        return;
      }
      const paramName = this.sensitivity.paramName;
      if (!paramName) {
        this.$message.warning('请选择要扫描的参数');
        return;
      }
      const values = this.parseValues(this.sensitivity.valuesText);
      if (!values.length) {
        this.$message.warning('请输入至少一个数值作为参数值');
        return;
      }
      if (values.length > 10) {
        this.$message.warning('单次最多扫描 10 个参数值，请精简后重试');
        return;
      }
      this.sensitivity.loading = true;
      this.sensitivity.error = '';
      this.sensitivity.result = null;
      try {
        const res = await runSensitivityAnalysis({
          ...this.baseRequest(),
          param_name: paramName,
          param_values: values
        });
        const data = (res && res.data) || res || {};
        this.sensitivity.result = data;
        this.$message.success(
          `敏感度分析完成：${paramName} 共 ${data.total_runs || 0} 次回测，成功 ${data.successful_runs || 0} 次`
        );
      } catch (error) {
        this.sensitivity.error = this.errorText(error);
        this.$message.error(`敏感度分析失败：${this.sensitivity.error}`);
      } finally {
        this.sensitivity.loading = false;
      }
    },
    async handleScenarioRun() {
      if (!this.canRun) {
        this.$message.warning('请先选择策略模型并配置完整的回测时间');
        return;
      }
      const usable = this.scenario.rows.filter(row => row.asset);
      if (!usable.length) {
        this.$message.warning('请至少选择一只资产并填写冲击幅度');
        return;
      }
      const codes = usable.map(row => row.asset);
      const duplicated = codes.filter((code, index) => codes.indexOf(code) !== index);
      if (duplicated.length) {
        this.$message.warning(`资产重复：${[...new Set(duplicated)].join('、')}，请合并为一行`);
        return;
      }
      for (const row of usable) {
        const shock = Number(row.shockPct);
        if (!Number.isFinite(shock)) {
          this.$message.warning(`资产 ${row.asset} 的冲击幅度无效`);
          return;
        }
        if (shock <= -100) {
          this.$message.warning(`资产 ${row.asset} 的跌幅必须大于 -100%`);
          return;
        }
      }
      const scenario = {};
      usable.forEach(row => {
        scenario[row.asset] = Number(row.shockPct) / 100;
      });
      this.scenario.loading = true;
      this.scenario.error = '';
      this.scenario.result = null;
      try {
        const res = await runScenarioAnalysis({ ...this.baseRequest(), scenario });
        const data = (res && res.data) || res || {};
        this.scenario.result = data;
        if (data.baseline_error || data.scenario_error) {
          this.$message.warning('情景推演完成，但有回测未返回指标，详见结果区');
        } else {
          this.$message.success('情景推演完成：已对比基线与冲击后绩效');
        }
      } catch (error) {
        this.scenario.error = this.errorText(error);
        this.$message.error(`情景推演失败：${this.scenario.error}`);
      } finally {
        this.scenario.loading = false;
      }
    },
    async handleRobustnessRun() {
      if (!this.canRun) {
        this.$message.warning('请先选择策略模型并配置完整的回测时间');
        return;
      }
      const nWindows = Number(this.robustness.nWindows);
      this.robustness.loading = true;
      this.robustness.error = '';
      this.robustness.result = null;
      try {
        const res = await runRobustnessCheck({ ...this.baseRequest(), n_windows: nWindows });
        const data = (res && res.data) || res || {};
        this.robustness.result = data;
        this.$message.success(
          `鲁棒性检验完成：${data.n_windows || 0} 个子区间，成功 ${data.successful_runs || 0} 个`
        );
      } catch (error) {
        this.robustness.error = this.errorText(error);
        this.$message.error(`鲁棒性检验失败：${this.robustness.error}`);
      } finally {
        this.robustness.loading = false;
      }
    },
    /** 三个分析接口共用的模型与区间参数 */
    baseRequest() {
      const [start, end] = this.dateRange || [];
      return {
        model_id: (this.strategy && this.strategy.id) || '',
        start_date: this.toApiDate(start),
        end_date: this.toApiDate(end),
        initial_cash: Number(this.initialCash) || 1000000
      };
    },
    parseValues(text) {
      const values = String(text || '')
        .split(/[,，\s]+/)
        .map(item => item.trim())
        .filter(Boolean)
        .map(Number)
        .filter(value => Number.isFinite(value));
      return [...new Set(values)];
    },
    toApiDate(value) {
      const text = String(value || '').replace(/[-/]/g, '').trim();
      return /^\d{8}$/.test(text) ? text : '';
    },
    displayDate(value) {
      const text = String(value || '').replace(/-/g, '');
      if (/^\d{8}$/.test(text)) {
        return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
      }
      return value || '—';
    },
    assetLabel(code) {
      const name = this.assetNames[code];
      return name ? `${code} - ${name}` : code;
    },
    pct(value) {
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : '—';
    },
    pctClass(value) {
      if (value === null || value === undefined || value === '') return 'number-neutral';
      const number = Number(value);
      if (!Number.isFinite(number) || number === 0) return 'number-neutral';
      return number > 0 ? 'number-positive' : 'number-negative';
    },
    num(value) {
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(2) : '—';
    },
    intText(value) {
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      return Number.isFinite(number) ? String(Math.round(number)) : '—';
    },
    money(value) {
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      if (!Number.isFinite(number)) return '—';
      return number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    errorText(error) {
      const detail = error && error.response && error.response.data && error.response.data.detail;
      if (typeof detail === 'string' && detail) return detail;
      if (Array.isArray(detail)) {
        return detail.map(item => item.msg || JSON.stringify(item)).join('；');
      }
      return (error && error.message) || '未知错误';
    }
  }
};
</script>

<style scoped>
.analysis-header {
  display: flex;
  align-items: baseline;
}

.analysis-title {
  flex-shrink: 0;
  white-space: nowrap;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.analysis-sub {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}

.analysis-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 8px;
}

.analysis-toolbar > * {
  margin-right: 10px;
  margin-bottom: 8px;
}

.analysis-field-label {
  font-size: 13px;
  color: #606266;
}

.analysis-unit {
  font-size: 13px;
  color: #606266;
}

.analysis-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.7;
  margin-top: 4px;
}

.analysis-summary {
  margin: 12px 0 8px;
  font-size: 13px;
  color: #606266;
}

.analysis-block-title {
  margin: 16px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.analysis-pass {
  color: #67C23A;
}

.analysis-fail {
  color: #F56C6C;
  cursor: help;
}

.scenario-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.scenario-row > * {
  margin-right: 10px;
}
</style>
