<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑组合' : '创建组合' }}</h2>
      <el-button @click="$router.back()">返回</el-button>
    </div>

    <div :class="{'page-content': !isDialog}">
      <el-card shadow="never">
        <!-- 来源选择 -->
        <el-form :model="form" :rules="rules" ref="form" label-width="140px" style="max-width: 900px;">
          <el-divider content-position="left">组合来源</el-divider>
          <el-form-item label="创建方式">
            <el-radio-group v-model="form.sourceType" @change="handleSourceChange" :disabled="isEdit">
              <el-radio-button label="manual">手工创建</el-radio-button>
              <el-radio-button label="single_strategy">单策略驱动</el-radio-button>
              <el-radio-button label="portfolio_model">组合模型</el-radio-button>
            </el-radio-group>
            <span v-if="isEdit" style="margin-left: 10px; color: #909399; font-size: 12px;">编辑模式下创建方式不可更改</span>
          </el-form-item>

          <!-- 基本信息 -->
          <el-divider content-position="left">基本信息</el-divider>
          <el-form-item label="组合名称" prop="name">
            <el-input v-model="form.name" placeholder="请输入组合名称" style="width: 400px;"></el-input>
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" type="textarea" :rows="2" placeholder="组合描述信息（可选）" style="width: 500px;"></el-input>
          </el-form-item>
          <el-form-item label="初始资金">
            <el-input-number v-model="form.initial_capital" :min="100000" :max="100000000" :step="100000" style="width: 250px;" :disabled="isEdit"></el-input-number>
            <span style="margin-left: 10px; color: #909399;">元</span>
          </el-form-item>
          <!-- 手工创建：持仓配置 -->
          <template v-if="form.sourceType === 'manual'">
            <el-divider content-position="left">持仓配置</el-divider>
            <el-form-item label="持仓列表">
              <el-button type="primary" icon="el-icon-plus" size="small" @click="addPosition" style="margin-bottom: 10px;">
                添加持仓
              </el-button>
              <el-table :data="form.positions" style="width: 100%;" size="small">
                <el-table-column label="资产代码" width="180">
                  <template slot-scope="scope">
                    <el-input v-model="scope.row.asset_code" placeholder="如 000300.SH" size="small"></el-input>
                  </template>
                </el-table-column>
                <el-table-column label="资产名称" width="150">
                  <template slot-scope="scope">
                    <el-input v-model="scope.row.asset_name" placeholder="如 沪深300" size="small"></el-input>
                  </template>
                </el-table-column>
                <el-table-column label="权重" width="150">
                  <template slot-scope="scope">
                    <el-input-number v-model="scope.row.weight" :min="0" :max="1" :step="0.05" :precision="4" size="small" controls-position="right"></el-input-number>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="80">
                  <template slot-scope="scope">
                    <el-button type="text" size="small" @click="removePosition(scope.$index)" style="color:#f56c6c">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-form-item>
          </template>

          <!-- 单策略驱动 -->
          <template v-if="form.sourceType === 'single_strategy'">
            <el-divider content-position="left">策略选择</el-divider>
            <el-form-item label="选择策略模型" prop="model_id">
              <el-select v-model="form.model_id" placeholder="请选择已发布的策略模型" filterable style="width: 100%;">
                <el-option
                  v-for="s in publishedStrategies"
                  :key="s.id"
                  :label="`${s.name} (${s.template_code})`"
                  :value="s.id"
                >
                  <span style="float: left">{{ s.name }}</span>
                  <span style="float: right; color: #8492a6; font-size: 12px">{{ s.template_code }}</span>
                </el-option>
              </el-select>
            </el-form-item>
          </template>

          <!-- 组合模型驱动 -->
          <template v-if="form.sourceType === 'portfolio_model'">
            <el-divider content-position="left">选择策略</el-divider>
            <el-form-item label="选择已发布策略">
              <el-select v-model="form.selectedStrategyIds" multiple placeholder="请选择要组合的策略（可多选）" filterable style="width: 100%;" @change="handleStrategiesChange">
                <el-option
                  v-for="s in portfolioModels"
                  :key="s.id"
                  :label="s.name"
                  :value="s.id"
                >
                  <span style="float: left">{{ s.name }}</span>
                  <span style="float: right; color: #8492a6; font-size: 12px">{{ s.template_code }}</span>
                </el-option>
              </el-select>
            </el-form-item>

            <!-- 选中策略后展示权重配置 -->
            <template v-if="customWeights.length > 0">
              <el-divider content-position="left">策略权重配置</el-divider>
              <el-form-item label="权重配置">
                <el-table :data="customWeights" size="small" border style="width: 100%;">
                  <el-table-column prop="name" label="策略名称" min-width="180"></el-table-column>
                  <el-table-column label="权重" width="200" align="center">
                    <template slot-scope="scope">
                      <el-input-number
                        v-if="form.weight_method === 'custom'"
                        v-model="scope.row.weight"
                        :min="0" :max="1" :step="0.05" :precision="4"
                        size="small" controls-position="right"
                        style="width: 150px;"
                      ></el-input-number>
                      <el-tag v-else-if="form.weight_method === 'quadrant'" size="small" type="info">象限动态调权</el-tag>
                      <span v-else>{{ (scope.row.weight * 100).toFixed(1) }}%</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="80" align="center">
                    <template slot-scope="scope">
                      <el-button type="text" size="small" @click="removeStrategy(scope.$index)" style="color:#f56c6c">移除</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <div v-if="form.weight_method === 'custom'" style="margin-top: 8px; color: #909399; font-size: 12px;">
                  权重总和: {{ customWeightSum.toFixed(4) }}
                  <span v-if="Math.abs(customWeightSum - 1) > 0.001" style="color: #f56c6c; margin-left: 8px;">（权重之和应为 1）</span>
                </div>
              </el-form-item>
            </template>

            <!-- 权重构建方法 -->
            <el-divider content-position="left">权重方法</el-divider>
            <el-form-item label="权重构建方法">
              <el-radio-group v-model="form.weight_method" @change="handleWeightMethodChange">
                <el-radio label="custom">自定义权重</el-radio>
                <el-radio label="equal_weight">等权分配</el-radio>
                <el-radio label="risk_parity">风险平价</el-radio>
                <el-radio label="min_variance">最小方差</el-radio>
                <el-radio label="quadrant">四象限调权</el-radio>
              </el-radio-group>
              <div style="margin-top: 8px; color: #909399; font-size: 12px;">
                <span v-if="form.weight_method === 'custom'">手动设置每个策略的权重配比</span>
                <span v-else-if="form.weight_method === 'equal_weight'">所有策略等比例分配（1/N）</span>
                <span v-else-if="form.weight_method === 'risk_parity'">基于历史波动率的风险贡献均等化（回测时计算）</span>
                <span v-else-if="form.weight_method === 'min_variance'">最小化整体波动率的优化配置（回测时计算）</span>
                <span v-else-if="form.weight_method === 'quadrant'">基于信号标的四象限信号动态调权，支持事件驱动 / 月度象限 / 月度逆波动率三种模式</span>
              </div>
            </el-form-item>

            <!-- 四象限调权参数 -->
            <template v-if="form.weight_method === 'quadrant'">
              <el-form-item label="调仓模式">
                <el-radio-group v-model="form.quadrant.rebalance_mode">
                  <el-radio label="signal_driven">信号触发</el-radio>
                  <el-radio label="monthly_quadrant">月度象限</el-radio>
                  <el-radio label="monthly_inv_vol">月度逆波动率</el-radio>
                </el-radio-group>
                <div style="margin-top: 6px; color: #909399; font-size: 12px;">
                  <span v-if="form.quadrant.rebalance_mode === 'signal_driven'">象限切换即触发再平衡（T+2 生效），逆波动率基础权重 × 象限放大</span>
                  <span v-else-if="form.quadrant.rebalance_mode === 'monthly_quadrant'">每月定期再平衡，逆波动率基础权重 × 象限放大缩放</span>
                  <span v-else>每月定期再平衡，仅按波动率倒数分配权重（无需信号标的）</span>
                </div>
              </el-form-item>

              <!-- 信号标的（仅 signal_driven / monthly_quadrant 模式） -->
              <el-form-item v-if="form.quadrant.rebalance_mode !== 'monthly_inv_vol'" label="信号标的">
                <el-input v-model="form.quadrant.signal_code" placeholder="如 600905.SH" style="width: 250px;"></el-input>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">用于判定四象限的标的资产</span>
              </el-form-item>

              <!-- 象限放大倍数（仅 signal_driven / monthly_quadrant 模式） -->
              <el-form-item v-if="form.quadrant.rebalance_mode !== 'monthly_inv_vol'" label="象限放大倍数">
                <el-input-number v-model="form.quadrant.boost_factor" :min="1" :max="5" :step="0.1" :precision="2" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">当前象限侧重策略的权重放大倍数（默认 1.5）</span>
              </el-form-item>

              <el-form-item label="波动率窗口">
                <el-input-number v-model="form.quadrant.vol_window" :min="20" :max="500" :step="10" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">逆波动率基础权重的计算窗口（交易日，默认 252）</span>
              </el-form-item>

              <!-- 象限 → 侧重策略映射（仅 signal_driven / monthly_quadrant 模式） -->
              <template v-if="form.quadrant.rebalance_mode !== 'monthly_inv_vol'">
                <el-divider content-position="left">象限侧重策略</el-divider>
                <el-alert type="info" :closable="false" style="margin-bottom: 12px;">
                  为每个象限指定当前行情下应侧重加权的子策略，未指定则使用逆波动率基础权重
                </el-alert>
                <el-form-item label="上涨 + 低波">
                  <el-select v-model="form.quadrant.quadrant_strategy_map.up_low_vol" placeholder="选择侧重策略" style="width: 220px;">
                    <el-option v-for="w in customWeights" :key="w.model_id" :label="w.name" :value="w.model_id"></el-option>
                  </el-select>
                  <span style="margin-left: 8px; color: #909399; font-size: 12px;">趋势上行且波动收缩，侧重方向性收益策略</span>
                </el-form-item>
                <el-form-item label="上涨 + 高波">
                  <el-select v-model="form.quadrant.quadrant_strategy_map.up_high_vol" placeholder="选择侧重策略" style="width: 220px;">
                    <el-option v-for="w in customWeights" :key="w.model_id" :label="w.name" :value="w.model_id"></el-option>
                  </el-select>
                  <span style="margin-left: 8px; color: #909399; font-size: 12px;">趋势上行但波动放大，侧重多资产分散策略</span>
                </el-form-item>
                <el-form-item label="下跌 + 低波">
                  <el-select v-model="form.quadrant.quadrant_strategy_map.down_low_vol" placeholder="选择侧重策略" style="width: 220px;">
                    <el-option v-for="w in customWeights" :key="w.model_id" :label="w.name" :value="w.model_id"></el-option>
                  </el-select>
                  <span style="margin-left: 8px; color: #909399; font-size: 12px;">趋势下行但波动收敛，侧重防御型策略</span>
                </el-form-item>
                <el-form-item label="下跌 + 高波">
                  <el-select v-model="form.quadrant.quadrant_strategy_map.down_high_vol" placeholder="选择侧重策略" style="width: 220px;">
                    <el-option v-for="w in customWeights" :key="w.model_id" :label="w.name" :value="w.model_id"></el-option>
                  </el-select>
                  <span style="margin-left: 8px; color: #909399; font-size: 12px;">趋势下行且波动放大，侧重对冲型策略</span>
                </el-form-item>
              </template>
            </template>
          </template>

          <!-- 产品层配置（策略组合 + 短债 + 现金的目标波动率配置） -->
          <template v-if="showProductLayer">
            <el-divider content-position="left">产品层配置</el-divider>
            <el-form-item label="启用产品层">
              <el-switch v-model="form.productLayer.enabled"></el-switch>
              <span style="margin-left: 10px; color: #909399; font-size: 12px;">
                在策略组合之上叠加短债 + 现金，按目标波动率求解配比（月度调仓）；关闭时回测/监控输出纯策略组合结果
              </span>
            </el-form-item>
            <template v-if="form.productLayer.enabled">
              <el-form-item label="目标波动率">
                <el-input-number v-model="volTargetProductPct" :min="0.5" :max="10" :step="0.5" :precision="1" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">%（年化，默认 2）</span>
              </el-form-item>
              <el-form-item label="现金固定比例">
                <el-input-number v-model="cashFixedPct" :min="0" :max="50" :step="5" :precision="0" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">%（默认 15，其余部分在策略组合与短债间求解分配）</span>
              </el-form-item>
              <el-form-item label="波动率窗口">
                <el-input-number v-model="form.productLayer.vol_window" :min="20" :max="252" :step="5" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">已实现波动率的滚动窗口（交易日，默认 60）</span>
              </el-form-item>
              <el-form-item label="短债资产">
                <el-input v-model="form.productLayer.bond_code" placeholder="如 CBA11321.CS" style="width: 250px;"></el-input>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">短债专户净值代码（默认 CBA11321.CS）</span>
              </el-form-item>
              <el-form-item label="现金代理资产">
                <el-input v-model="form.productLayer.cash_code" placeholder="如 511360.SH" style="width: 250px;"></el-input>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">现金收益代理（默认 511360.SH 短融ETF）</span>
              </el-form-item>
            </template>
          </template>

          <!-- 母层波动率定标（组合层按目标波动率逐日缩放收益，leverage = clip(目标vol/实现vol, 上下界)） -->
          <template v-if="showProductLayer">
            <el-divider content-position="left">母层波动率定标</el-divider>
            <el-form-item label="启用定标">
              <el-switch v-model="volControlEnabled"></el-switch>
              <span style="margin-left: 10px; color: #909399; font-size: 12px;">
                启用后组合收益按目标波动率逐日缩放：leverage = clip(目标vol / 实现vol, 上下界)
              </span>
            </el-form-item>
            <template v-if="volControlEnabled">
              <el-form-item label="目标波动率">
                <el-input-number v-model="volTargetPct" :min="0.5" :max="20" :step="0.5" :precision="1" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">%（年化，如 3 = 3%）</span>
              </el-form-item>
              <el-form-item label="估计方法">
                <el-radio-group v-model="form.vol_method">
                  <el-radio label="rolling">滚动窗口标准差</el-radio>
                  <el-radio label="ewma">指数加权（EWMA）</el-radio>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="短期窗口">
                <el-input-number v-model="form.vol_lookback_short" :min="5" :max="60" :step="1" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">交易日（默认 20）</span>
              </el-form-item>
              <el-form-item label="长期窗口">
                <el-input-number v-model="form.vol_lookback_long" :min="20" :max="260" :step="5" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">交易日（默认 60，与短窗取平均作为波动率估计）</span>
              </el-form-item>
              <el-form-item label="年化因子">
                <el-input-number v-model="form.vol_annualize_factor" :min="52" :max="365" :step="1" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">期货默认 260，股票常用 252</span>
              </el-form-item>
              <el-form-item label="杠杆下界">
                <el-input-number v-model="volLeverageMin" :min="0" :max="1" :step="0.05" :precision="2" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">定标杠杆最小倍数（默认 0.1）</span>
              </el-form-item>
              <el-form-item label="杠杆上界">
                <el-input-number v-model="volLeverageMax" :min="1" :max="10" :step="0.5" :precision="1" style="width: 200px;"></el-input-number>
                <span style="margin-left: 10px; color: #909399; font-size: 12px;">定标杠杆最大倍数（默认 5.0）</span>
              </el-form-item>
            </template>
          </template>

          <!-- 提交 -->
          <el-divider></el-divider>
          <el-form-item>
            <el-button type="primary" @click="handleSubmit" :loading="submitting" :disabled="submitting">
              {{ submitting ? (isEdit ? '保存中...' : '创建中...') : (isEdit ? '保存修改' : '确认创建') }}
            </el-button>
            <el-button @click="handleCancel">取消</el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </div>
  </div>
</template>

<script>
import { getStrategyModelList } from '@/api/strategy';
import { getPortfolio, updatePortfolio } from '@/api/portfolio';

export default {
  name: 'PortfolioCreate',
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    id: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      isEdit: false,
      editId: null,
      form: {
        sourceType: 'portfolio_model',
        name: '',
        initial_capital: 10000000,
        // manual
        positions: [],
        // single_strategy
        model_id: '',
        // portfolio_model
        selectedStrategyIds: [],
        weight_method: 'custom',
        quadrant: {
          rebalance_mode: 'signal_driven',
          signal_code: '600905.SH',
          boost_factor: 1.5,
          vol_window: 252,
          quadrant_strategy_map: {
            up_low_vol: '',
            up_high_vol: '',
            down_low_vol: '',
            down_high_vol: ''
          }
        },
        // 产品层（策略组合 + 短债 + 现金的目标波动率配置）
        productLayer: {
          enabled: false,
          vol_window: 60,
          bond_code: 'CBA11321.CS',
          cash_code: '511360.SH'
        },
        vol_lookback_short: 20,
        vol_lookback_long: 60,
        vol_method: 'rolling',
        vol_annualize_factor: 260,
        status: 'active',
        description: ''
      },
      rules: {
        name: [{ required: true, message: '请输入组合名称', trigger: 'blur' }]
      },
      volControlEnabled: false,
      volTargetPct: 8,
      // 母层定标杠杆界限
      volLeverageMin: 0.1,
      volLeverageMax: 5.0,
      // 产品层参数（百分比展示）
      volTargetProductPct: 2,
      cashFixedPct: 15,
      submitting: false,
      strategyList: [],
      customWeights: []
    };
  },
  computed: {
    publishedStrategies() {
      return this.strategyList.filter(s =>
        (s.status === '已发布' || s.status === 'published') && !s.is_portfolio
      );
    },
    portfolioModels() {
      return this.strategyList.filter(s =>
        (s.status === '已发布' || s.status === 'published') && !s.is_portfolio
      );
    },
    customWeightSum() {
      return this.customWeights.reduce((sum, w) => sum + (w.weight || 0), 0);
    },
    // 产品层配置区展示条件：组合模型来源新建；或编辑已有的多策略/四象限组合
    showProductLayer() {
      return this.form.sourceType === 'portfolio_model'
        || (this.isEdit && (this.form.weight_method === 'quadrant' || this.customWeights.length > 0));
    }
  },
  created() {
    // 弹窗模式使用 prop.id，路由模式使用 route.params.id
    const routeId = this.$route ? this.$route.params.id : null;
    const propId = this.id;
    const targetId = propId || routeId;
    this.isEdit = !!targetId;
    if (this.isEdit) {
      this.editId = targetId;
      this.loadStrategies().then(() => this.loadPortfolio());
    } else {
      this.loadStrategies();
    }
  },
  methods: {
    async loadPortfolio() {
      try {
        const res = await getPortfolio(this.editId);
        const p = res.data || res;
        this.form.name = p.name || '';
        this.form.description = p.description || '';
        this.form.status = p.status || 'active';
        this.form.sourceType = p.source || 'portfolio_model';
        // 显示模式按实际数据语义判定（存量组合 source 可能误标为 manual，
        // 但实际带 sub_strategies，须按策略选择结果展示，否则编辑页退化为空白持仓页）
        if ((p.sub_strategies || []).length > 0) {
          this.form.sourceType = 'portfolio_model';
        } else if (p.source === 'single_strategy' || p.model_id) {
          this.form.sourceType = 'single_strategy';
        }
        this.form.initial_capital = p.initial_capital || 10000000;
        this.form.weight_method = p.weight_method || 'custom';
        if (p.weight_model_params && this.form.weight_method === 'quadrant') {
          this.form.quadrant.rebalance_mode = p.weight_model_params.rebalance_mode || 'signal_driven';
          this.form.quadrant.signal_code = p.weight_model_params.signal_code || '600905.SH';
          this.form.quadrant.boost_factor = p.weight_model_params.boost_factor != null ? p.weight_model_params.boost_factor : 1.5;
          this.form.quadrant.vol_window = p.weight_model_params.vol_window != null ? p.weight_model_params.vol_window : 252;
          if (p.weight_model_params.quadrant_strategy_map) {
            this.form.quadrant.quadrant_strategy_map = {
              up_low_vol: p.weight_model_params.quadrant_strategy_map.up_low_vol || '',
              up_high_vol: p.weight_model_params.quadrant_strategy_map.up_high_vol || '',
              down_low_vol: p.weight_model_params.quadrant_strategy_map.down_low_vol || '',
              down_high_vol: p.weight_model_params.quadrant_strategy_map.down_high_vol || ''
            };
          }
        }
        this.form.vol_lookback_short = p.vol_lookback_short || 20;
        this.form.vol_lookback_long = p.vol_lookback_long || 60;
        this.form.vol_method = p.vol_method || 'rolling';
        this.form.vol_annualize_factor = p.vol_annualize_factor != null ? p.vol_annualize_factor : 260;
        this.volTargetPct = (p.vol_target || 0.08) * 100;
        this.volControlEnabled = !!p.vol_target;
        this.volLeverageMin = p.vol_leverage_min != null ? p.vol_leverage_min : 0.1;
        this.volLeverageMax = p.vol_leverage_max != null ? p.vol_leverage_max : 5.0;

        // 产品层配置回显
        const pl = (p.weight_model_params || {}).product_layer;
        if (pl && typeof pl === 'object') {
          this.form.productLayer.enabled = !!pl.enabled;
          this.form.productLayer.vol_window = pl.vol_window != null ? pl.vol_window : 60;
          this.form.productLayer.bond_code = pl.bond_code || 'CBA11321.CS';
          this.form.productLayer.cash_code = pl.cash_code || '511360.SH';
          this.volTargetProductPct = pl.vol_target != null ? pl.vol_target * 100 : 2;
          this.cashFixedPct = pl.cash_fixed != null ? pl.cash_fixed * 100 : 15;
        }

        // 加载子策略列表
        if (p.sub_strategies && p.sub_strategies.length) {
          this.form.selectedStrategyIds = p.sub_strategies.map(s => s.model_id);
          this.customWeights = p.sub_strategies.map(s => ({
            model_id: s.model_id,
            name: s.name,
            weight: s.weight
          }));
        }

        // 单策略
        if (p.source === 'single_strategy' && p.model_id) {
          this.form.model_id = p.model_id;
        }
      } catch (e) {
        this.$message.error('加载组合数据失败: ' + (e.message || e));
      }
    },
    async loadStrategies() {
      try {
        const res = await getStrategyModelList({ include_portfolio: true });
        this.strategyList = res.data || res || [];
      } catch (e) {
        console.error('加载策略列表失败:', e);
      }
    },
    handleSourceChange() {
      this.customWeights = [];
    },
    handleStrategiesChange(ids) {
      // 保留已有的权重设置，新增的策略给默认权重
      const existingMap = {};
      this.customWeights.forEach(w => { existingMap[w.model_id] = w.weight; });
      const n = ids.length || 1;
      const autoEqual = this.form.weight_method === 'equal_weight' || this.form.weight_method === 'quadrant';
      this.customWeights = ids.map(id => {
        const s = this.portfolioModels.find(m => m.id === id);
        return {
          name: s ? s.name : id,
          model_id: id,
          weight: existingMap[id] !== undefined ? existingMap[id] : (autoEqual ? 1 / n : 0)
        };
      });
      // 等权/象限模式下自动均分（象限模式以此为初始权重，回测时由模型动态覆盖）
      if (autoEqual) {
        this.customWeights.forEach(w => { w.weight = 1 / n; });
      }
    },
    removeStrategy(index) {
      const removed = this.customWeights.splice(index, 1);
      if (removed.length > 0) {
        this.form.selectedStrategyIds = this.form.selectedStrategyIds.filter(id => id !== removed[0].model_id);
      }
      if (this.form.weight_method === 'equal_weight' && this.customWeights.length > 0) {
        const n = this.customWeights.length;
        this.customWeights.forEach(w => { w.weight = 1 / n; });
      }
    },
    handleWeightMethodChange() {
      if ((this.form.weight_method === 'equal_weight' || this.form.weight_method === 'quadrant') && this.customWeights.length > 0) {
        const n = this.customWeights.length;
        this.customWeights.forEach(w => { w.weight = 1 / n; });
      }
    },
    addPosition() {
      this.form.positions.push({ asset_code: '', asset_name: '', weight: 0 });
    },
    removePosition(index) {
      this.form.positions.splice(index, 1);
    },
    async handleSubmit() {
      try {
        await this.$refs.form.validate();
      } catch { return; }

      this.submitting = true;
      try {
        if (this.isEdit) {
          await this.submitUpdate();
        } else if (this.form.sourceType === 'manual') {
          await this.createManual();
        } else if (this.form.sourceType === 'single_strategy') {
          await this.createFromSingleModel();
        } else {
          await this.createFromPortfolioModel();
        }
        this.$message.success(this.isEdit ? '组合已更新' : '组合创建成功');
        if (this.isDialog) {
          this.$emit('success');
        } else {
          this.$router.push({ name: 'PortfolioList' });
        }
      } catch (error) {
        const detail = error.response?.data?.detail;
        let msg = error.response?.data?.message || error.message;
        if (detail) {
          msg = Array.isArray(detail)
            ? detail.map(e => (e.loc ? e.loc.join('.') + ': ' : '') + (e.msg || '')).join('; ')
            : String(detail);
        }
        this.$message.error('创建失败: ' + msg);
      } finally {
        this.submitting = false;
      }
    },
    async createManual() {
      const payload = {
        name: this.form.name,
        initial_capital: this.form.initial_capital,
        positions: this.form.positions.filter(p => p.asset_code && p.weight > 0)
      };
      await this.$store.dispatch('portfolio/createPortfolio', payload);
    },
    async createFromSingleModel() {
      if (!this.form.model_id) {
        throw new Error('请选择策略模型');
      }
      const payload = {
        model_id: this.form.model_id,
        name: this.form.name,
        initial_capital: this.form.initial_capital
      };
      await this.$store.dispatch('portfolio/createFromModel', payload);
    },
    buildWeightModelParams() {
      // 组装 weight_model_params：象限参数 + 产品层配置（product_layer 始终携带，
      // 以 enabled 字段控制启停，避免编辑保存时覆盖已有配置）
      const wmp = this.form.weight_method === 'quadrant' ? {
        rebalance_mode: this.form.quadrant.rebalance_mode,
        signal_code: this.form.quadrant.signal_code,
        boost_factor: this.form.quadrant.boost_factor,
        vol_window: this.form.quadrant.vol_window,
        quadrant_strategy_map: this.form.quadrant.rebalance_mode !== 'monthly_inv_vol'
          ? this.form.quadrant.quadrant_strategy_map : undefined
      } : {};
      wmp.product_layer = {
        enabled: this.form.productLayer.enabled,
        controller: 'vol_target',
        vol_target: this.volTargetProductPct / 100,
        cash_fixed: this.cashFixedPct / 100,
        vol_window: this.form.productLayer.vol_window,
        annualize_factor: 252,
        bond_code: this.form.productLayer.bond_code || 'CBA11321.CS',
        cash_code: this.form.productLayer.cash_code || '511360.SH'
      };
      return wmp;
    },
    async createFromPortfolioModel() {
      if (!this.form.selectedStrategyIds.length) {
        throw new Error('请至少选择一个策略');
      }
      if (this.form.weight_method === 'custom' && Math.abs(this.customWeightSum - 1) > 0.001) {
        throw new Error('自定义权重之和必须为 1');
      }
      const payload = {
        strategy_ids: this.form.selectedStrategyIds,
        name: this.form.name,
        initial_capital: this.form.initial_capital,
        weight_method: this.form.weight_method,
        weight_model_params: this.buildWeightModelParams(),
        vol_target: this.volControlEnabled ? (this.volTargetPct / 100) : null,
        vol_lookback_short: this.form.vol_lookback_short,
        vol_lookback_long: this.form.vol_lookback_long,
        vol_method: this.form.vol_method,
        vol_annualize_factor: this.form.vol_annualize_factor,
        vol_leverage_min: this.volControlEnabled ? this.volLeverageMin : null,
        vol_leverage_max: this.volControlEnabled ? this.volLeverageMax : null,
        sub_strategy_weights: this.customWeights.map(w => ({
          model_id: w.model_id,
          weight: w.weight
        }))
      };
      await this.$store.dispatch('portfolio/createFromStrategies', payload);
    },
    async submitUpdate() {
      const payload = {
        name: this.form.name,
        description: this.form.description,
        status: this.form.status,
        weight_method: this.form.weight_method,
        weight_model_params: this.buildWeightModelParams(),
        vol_target: this.volControlEnabled ? (this.volTargetPct / 100) : null,
        vol_lookback_short: this.form.vol_lookback_short,
        vol_lookback_long: this.form.vol_lookback_long,
        vol_method: this.form.vol_method,
        vol_annualize_factor: this.form.vol_annualize_factor,
        vol_leverage_min: this.volControlEnabled ? this.volLeverageMin : null,
        vol_leverage_max: this.volControlEnabled ? this.volLeverageMax : null
      };
      // 如果是组合模型类型，附带子策略权重
      if (this.form.sourceType === 'portfolio_model' && this.customWeights.length > 0) {
        if (this.form.weight_method === 'custom' && Math.abs(this.customWeightSum - 1) > 0.001) {
          throw new Error('自定义权重之和必须为 1');
        }
        payload.sub_strategies = this.customWeights.map(w => ({
          model_id: w.model_id,
          name: w.name,
          weight: w.weight
        }));
      }
      await updatePortfolio(this.editId, payload);
    },
    handleCancel() {
      if (this.isDialog) {
        this.$emit('close');
      } else {
        this.$router.back();
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
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #303133;
  margin: 0;
}
</style>
