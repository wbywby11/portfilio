<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">组合详情</h2>
      <div>
        <el-button
          v-if="!linkedModelLive"
          type="primary"
          plain
          icon="el-icon-upload2"
          :loading="livePublishing"
          @click="handleLivePublish"
        >
          实盘发布
        </el-button>
        <el-tag v-if="linkedModelLive" type="success" size="small" style="margin-right:12px;">已实盘发布</el-tag>
        <el-button
          v-if="linkedModelLive"
          type="danger"
          plain
          icon="el-icon-close"
          :loading="liveUnpublishing"
          @click="handleLiveUnpublish"
        >
          取消实盘
        </el-button>
        <el-button @click="$router.back()">返回</el-button>
        <el-button type="primary" icon="el-icon-refresh" @click="loadData">刷新</el-button>
      </div>
    </div>

    <div :class="{'page-content': !isDialog}" v-loading="loading">
      <el-row :gutter="20">
        <!-- 左栏：基本信息 + 子策略 + 参数版本 + 策略报告 -->
        <el-col :span="16">
          <!-- 基本信息 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>基本信息</span>
              <el-tag :type="getSourceTagType(portfolio.source)" size="small">
                {{ getSourceLabel(portfolio.source) }}
              </el-tag>
            </div>

            <el-descriptions :column="2" border>
              <el-descriptions-item label="组合名称">{{ portfolio.name }}</el-descriptions-item>
              <el-descriptions-item label="权重方法" v-if="portfolio.weight_method">
                <el-tag type="warning" size="small">{{ getWeightMethodLabel(portfolio.weight_method) }}</el-tag>
                <el-tag v-if="portfolio.weight_method === 'quadrant' && portfolio.weight_model_params && portfolio.weight_model_params.rebalance_mode" size="small" style="margin-left: 6px;">
                  {{ getRebalanceModeLabel(portfolio.weight_model_params.rebalance_mode) }}
                </el-tag>
                <el-tag v-if="productLayerEnabled" type="success" size="small" style="margin-left: 6px;">
                  产品层 · 目标波动 {{ productLayerVolTarget }}%
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="调仓频率" v-if="portfolio.rebalance_frequency">
                {{ portfolio.rebalance_frequency }}
              </el-descriptions-item>
              <el-descriptions-item label="初始资金">
                ¥{{ formatNumber(portfolio.initial_capital) }}
              </el-descriptions-item>
              <el-descriptions-item label="当前市值">
                ¥{{ formatNumber(portfolio.current_capital) }}
              </el-descriptions-item>
              <el-descriptions-item label="波动率目标" v-if="portfolio.vol_target">
                <el-tag type="success" size="small">{{ (portfolio.vol_target * 100).toFixed(0) }}%</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">
                {{ formatDate(portfolio.created_at) }}
              </el-descriptions-item>
              <el-descriptions-item label="关联模型" v-if="portfolio.model_id">
                <el-link type="primary" @click="viewModel(portfolio.model_id)">查看策略模型</el-link>
              </el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">
                {{ portfolio.description || '暂无描述' }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <!-- 子策略配置 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header" style="cursor: pointer;" @click="subStrategiesExpanded = !subStrategiesExpanded">
              <span>
                子策略配置
                <el-tag size="mini" style="margin-left: 8px;">
                  {{ portfolio.sub_strategies ? portfolio.sub_strategies.length : 0 }} 个
                </el-tag>
              </span>
              <i :class="subStrategiesExpanded ? 'el-icon-arrow-up' : 'el-icon-arrow-down'" style="color: #909399;"></i>
            </div>

            <div v-show="subStrategiesExpanded">
              <div v-if="portfolio.sub_strategies && portfolio.sub_strategies.length">
                <div
                  v-for="(sub, idx) in portfolio.sub_strategies"
                  :key="sub.model_id"
                  class="sub-strategy-block"
                >
                  <div class="sub-strategy-header" @click.stop="toggleSubStrategy(idx)">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <el-tag size="small" type="primary">{{ ((sub.weight || 0) * 100).toFixed(1) }}%</el-tag>
                      <span style="font-weight: 500; color: #303133; font-size: 13px;">{{ sub.name || sub.model_id }}</span>
                      <el-tag v-if="sub.template_code" size="mini" type="info">{{ sub.template_code }}</el-tag>
                    </div>
                    <i :class="expandedSubIdx === idx ? 'el-icon-arrow-up' : 'el-icon-arrow-down'" style="color: #909399;"></i>
                  </div>

                  <!-- 子策略参数详情 -->
                  <div v-if="expandedSubIdx === idx" class="sub-strategy-params">
                    <div v-if="subStrategyDetails[sub.model_id]">
                      <!-- 分配策略参数 -->
                      <div v-if="subStrategyDetails[sub.model_id].parameters && Object.keys(subStrategyDetails[sub.model_id].parameters).length">
                        <div style="font-size: 12px; color: #909399; margin-bottom: 6px; font-weight: 500;">分配策略参数</div>
                        <el-descriptions :column="2" border size="mini">
                          <el-descriptions-item
                            v-for="(value, key) in subStrategyDetails[sub.model_id].parameters"
                            :key="key"
                            :label="getParamLabel(key)"
                          >
                            <div style="white-space: pre-wrap;">{{ formatParamVal(value) }}</div>
                          </el-descriptions-item>
                        </el-descriptions>
                      </div>
                      <!-- 资产列表 -->
                      <div v-if="subStrategyDetails[sub.model_id].asset_codes && subStrategyDetails[sub.model_id].asset_codes.length" style="margin-top: 10px;">
                        <div style="font-size: 12px; color: #909399; margin-bottom: 6px; font-weight: 500;">选择资产</div>
                        <el-tag
                          v-for="code in subStrategyDetails[sub.model_id].asset_codes"
                          :key="code"
                          style="margin-right: 6px; margin-bottom: 4px;"
                          size="mini"
                        >{{ code }}</el-tag>
                      </div>
                      <!-- 风险控制 -->
                      <div v-if="subStrategyDetails[sub.model_id].controller_code" style="margin-top: 10px;">
                        <div style="font-size: 12px; color: #909399; margin-bottom: 6px; font-weight: 500;">风险控制</div>
                        <el-descriptions :column="2" border size="mini">
                          <el-descriptions-item label="控制器">{{ subStrategyDetails[sub.model_id].controller_code }}</el-descriptions-item>
                          <template v-if="subStrategyDetails[sub.model_id].controller_parameters">
                            <el-descriptions-item
                              v-for="(v, k) in subStrategyDetails[sub.model_id].controller_parameters"
                              :key="'ctrl_' + k"
                              :label="k"
                            >{{ formatParamVal(v) }}</el-descriptions-item>
                          </template>
                        </el-descriptions>
                      </div>
                    </div>
                    <div v-else style="color: #909399; text-align: center; padding: 10px; font-size: 12px;">
                      <i class="el-icon-loading" v-if="loadingSubDetails"></i>
                      <span v-else>加载参数中...</span>
                    </div>
                  </div>
                </div>
              </div>
              <el-empty v-else description="暂无子策略配置" :image-size="40"></el-empty>
            </div>
          </el-card>

          <!-- 配置版本 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>参数版本</span>
              <span v-if="paramVersions.length > 0" style="color: #909399; font-size: 12px;">
                共 {{ paramVersions.length }} 个版本
              </span>
            </div>

            <!-- 当前子策略配置（始终显示） -->
            <div v-if="portfolio.sub_strategies && portfolio.sub_strategies.length">
              <div style="font-size: 13px; color: #606266; font-weight: 600; margin-bottom: 10px;">当前子策略配置</div>
              <el-table :data="portfolio.sub_strategies" size="mini" border>
                <el-table-column prop="name" label="子策略" />
                <el-table-column prop="weight" label="权重" width="80" align="right">
                  <template slot-scope="{ row }">{{ (row.weight * 100).toFixed(1) }}%</template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 历史版本（折叠区） -->
            <div v-if="paramVersions.length > 0" style="margin-top: 20px;">
              <el-divider content-position="left">
                <span
                  style="cursor: pointer; color: #409EFF; font-size: 13px;"
                  @click="paramHistoryExpanded = !paramHistoryExpanded"
                >
                  历史版本
                  <i :class="paramHistoryExpanded ? 'el-icon-arrow-up' : 'el-icon-arrow-down'"></i>
                </span>
              </el-divider>
              <div v-show="paramHistoryExpanded">
                <el-timeline>
                  <el-timeline-item
                    v-for="ver in paramVersions"
                    :key="ver.id"
                    :timestamp="formatDate(ver.created_at)"
                    placement="top"
                  >
                    <el-card shadow="hover" class="history-item" @click.native="toggleVersionDetail(ver.id)">
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                          <el-tag size="mini" type="info" style="margin-right: 8px;">v{{ ver.version }}</el-tag>
                          <span style="font-size: 12px; color: #606266;">{{ ver.change_summary || '配置变更' }}</span>
                        </div>
                        <i :class="expandedVersionId === ver.id ? 'el-icon-arrow-up' : 'el-icon-arrow-down'" style="color: #909399;"></i>
                      </div>
                      <div v-if="expandedVersionId === ver.id" style="margin-top: 12px; border-top: 1px solid #ebeef5; padding-top: 12px;">
                        <el-descriptions :column="2" size="mini" border>
                          <el-descriptions-item v-for="(value, key) in ver.allocator_params" :key="key" :label="getParamLabel(key)">
                            {{ formatParamVal(value) }}
                          </el-descriptions-item>
                        </el-descriptions>
                      </div>
                    </el-card>
                  </el-timeline-item>
                </el-timeline>
              </div>
            </div>

            <el-empty v-if="!paramVersions.length && (!portfolio.sub_strategies || !portfolio.sub_strategies.length)" description="暂无配置变更记录" :image-size="40"></el-empty>
          </el-card>

          <!-- 策略报告（预留，与策略详情一致） -->
          <el-card shadow="never" class="info-card" v-if="backtestHistory.length > 0">
            <div slot="header" class="card-header">
              <span>组合报告</span>
              <el-button type="primary" size="mini" :loading="reportLoading" @click="generateReport">
                {{ portfolioReport ? '重新生成' : '生成报告' }}
              </el-button>
            </div>
            <div v-if="portfolioReport" class="portfolio-report">
              <el-row :gutter="16" class="metrics-row">
                <el-col :span="4">
                  <div class="metric-card">
                    <div class="metric-label">年化收益</div>
                    <div class="metric-value" :style="{color: (portfolioReport.annual_return||0) >= 0 ? '#f56c6c' : '#67c23a', fontSize: '16px'}">
                      {{ ((portfolioReport.annual_return||0)*100).toFixed(2) }}%
                    </div>
                  </div>
                </el-col>
                <el-col :span="4">
                  <div class="metric-card">
                    <div class="metric-label">年化波动</div>
                    <div class="metric-value" style="fontSize: 16px;">{{ ((portfolioReport.annual_vol||0)*100).toFixed(2) }}%</div>
                  </div>
                </el-col>
                <el-col :span="4">
                  <div class="metric-card">
                    <div class="metric-label">夏普比率</div>
                    <div class="metric-value" :style="{color: (portfolioReport.sharpe||0) >= 1 ? '#f56c6c' : '#e6a23c', fontSize: '16px', fontWeight: 600}">
                      {{ (portfolioReport.sharpe||0).toFixed(2) }}
                    </div>
                  </div>
                </el-col>
                <el-col :span="4">
                  <div class="metric-card">
                    <div class="metric-label">最大回撤</div>
                    <div class="metric-value" style="color: #f56c6c; fontSize: 16px;">{{ ((portfolioReport.max_drawdown||0)*100).toFixed(2) }}%</div>
                  </div>
                </el-col>
              </el-row>
              <!-- 子策略分解 -->
              <div v-if="portfolioReport.sub_strategy_decomposition && portfolioReport.sub_strategy_decomposition.length" style="margin-top: 16px;">
                <div style="font-size: 13px; color: #606266; font-weight: 500; margin-bottom: 8px;">子策略分解</div>
                <el-table :data="portfolioReport.sub_strategy_decomposition" size="small" border>
                  <el-table-column prop="sub_name" label="子策略" width="120" />
                  <el-table-column prop="weight" label="权重" width="80" align="right">
                    <template slot-scope="{ row }">{{ (row.weight * 100).toFixed(0) }}%</template>
                  </el-table-column>
                  <el-table-column label="年化收益" width="100" align="right">
                    <template slot-scope="{ row }">
                      <span :style="{color: row.annual_return >= 0 ? '#f56c6c' : '#67c23a'}">{{ (row.annual_return * 100).toFixed(2) }}%</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="波动" width="90" align="right">
                    <template slot-scope="{ row }">{{ (row.annual_vol * 100).toFixed(2) }}%</template>
                  </el-table-column>
                  <el-table-column label="夏普" width="80" align="right">
                    <template slot-scope="{ row }">{{ row.sharpe.toFixed(2) }}</template>
                  </el-table-column>
                  <el-table-column label="回撤" width="90" align="right">
                    <template slot-scope="{ row }"><span style="color:#f56c6c">{{ (row.max_drawdown * 100).toFixed(2) }}%</span></template>
                  </el-table-column>
                </el-table>
              </div>
            </div>
            <div v-else-if="!reportLoading" style="color: #909399; text-align: center; padding: 20px; font-size: 13px;">
              点击「生成报告」对回测结果进行全面评估
            </div>
          </el-card>
        </el-col>

        <!-- 右栏：历史回测记录 -->
        <el-col :span="8">
          <el-card shadow="never" class="history-card">
            <div slot="header">
              <span>历史回测记录</span>
              <span style="float: right; font-size: 12px; color: #909399;">
                共 {{ backtestHistory.length }} 条
              </span>
            </div>
            <el-timeline v-if="backtestHistory.length > 0">
              <el-timeline-item
                v-for="record in backtestHistory"
                :key="record.id"
                :timestamp="formatDate(record.created_at)"
                placement="top"
              >
                <el-card shadow="hover" class="history-item">
                  <div class="history-info">
                    <div style="margin-bottom: 8px; color: #606266; font-weight: 500;">
                      {{ formatDateShort(record.start_date) }} ~ {{ formatDateShort(record.end_date) }}
                    </div>
                    <div style="margin-bottom: 5px; font-size: 12px; color: #909399;">
                      初始资金: ¥{{ (record.initial_capital || 0).toLocaleString() }}
                    </div>
                    <div v-if="record.remark || editingRecordId === record.id" style="margin-bottom: 5px; font-size: 12px; color: #606266;">
                      <span v-if="editingRecordId !== record.id">备注: {{ record.remark || '-' }}</span>
                      <span v-else style="display: flex; align-items: center; gap: 8px;">
                        <el-input v-model="editingRemark" size="small" placeholder="输入备注" maxlength="200" show-word-limit style="flex: 1;"></el-input>
                        <el-button type="primary" size="mini" @click="saveRemark(record)">保存</el-button>
                        <el-button size="mini" @click="editingRecordId = null; editingRemark = ''">取消</el-button>
                      </span>
                    </div>
                  </div>
                  <div class="history-metrics">
                    <div>总收益: <span :style="{ color: getReturnColor(record.result.total_return) }">
                      {{ (record.result.total_return * 100).toFixed(2) }}%
                    </span></div>
                    <div>年化收益: <span :style="{ color: getReturnColor(record.result.annual_return) }">
                      {{ (record.result.annual_return * 100).toFixed(2) }}%
                    </span></div>
                    <div>年化波动: {{ record.result.annual_volatility ? (record.result.annual_volatility * 100).toFixed(2) + '%' : '-' }}</div>
                    <div>夏普比率: {{ record.result.sharpe_ratio ? record.result.sharpe_ratio.toFixed(3) : '-' }}</div>
                    <div>最大回撤: <span style="color: #f56c6c;">
                      {{ (record.result.max_drawdown * 100).toFixed(2) }}%
                    </span></div>
                  </div>
                  <div style="margin-top: 10px;">
                    <el-button type="text" size="small" @click="viewBacktestDetail(record)">查看详情</el-button>
                    <el-button type="text" size="small" @click="editingRecordId = record.id; editingRemark = record.remark || ''">
                      {{ editingRecordId === record.id ? '' : '编辑备注' }}
                    </el-button>
                  </div>
                </el-card>
              </el-timeline-item>
            </el-timeline>
            <div v-else style="color: #909399; text-align: center; padding: 20px;">
              暂无回测记录
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 回测详情弹窗 -->
    <backtest-detail-dialog
      v-model="backtestDetailVisible"
      :record="currentBacktestRecord"
    />

    <!-- 策略详情弹窗 -->
    <el-dialog title="策略详情" :visible.sync="modelDetailVisible" width="1200px" append-to-body>
      <strategy-model-detail v-if="modelDetailVisible" is-dialog :id="currentModelId" />
    </el-dialog>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import BacktestDetailDialog from '@/components/BacktestDetailDialog.vue';
import * as portfolioApi from '@/api/portfolio';
import { getStrategyModel, getParamVersions, generatePortfolioReport, updateBacktestRemark, livePublishModel, liveUnpublishModel } from '@/api/strategy';

export default {
  name: 'PortfolioDetail',
  components: {
    BacktestDetailDialog,
    StrategyModelDetail: () => import('../strategy/StrategyModelDetail.vue')
  },
  props: {
    isDialog: { type: Boolean, default: false },
    id: { type: String, default: '' }
  },
  data() {
    return {
      portfolioId: null,
      portfolio: {},
      loading: false,
      // 子策略
      subStrategyDetails: {},
      expandedSubIdx: null,
      loadingSubDetails: false,
      subStrategiesExpanded: true,
      // 配置版本
      paramVersions: [],
      paramHistoryExpanded: false,
      expandedVersionId: null,
      // 回测历史
      backtestHistory: [],
      backtestDetailVisible: false,
      currentBacktestRecord: {
        id: '', start_date: '', end_date: '', initial_capital: 0, result: {}, created_at: ''
      },
      // 备注编辑
      editingRecordId: null,
      editingRemark: '',
      // 策略报告
      portfolioReport: null,
      reportLoading: false,
      // 弹窗
      modelDetailVisible: false,
      currentModelId: '',
      // 实盘发布
      livePublishing: false,
      liveUnpublishing: false,
      linkedModelLive: false
    };
  },
  created() {
    this.portfolioId = this.isDialog ? this.id : this.$route.params.id;
    this.loadData();
  },
  computed: {
    linkedModelId() {
      return this.portfolio.portfolio_model_id || this.portfolio.model_id || '';
    },
    productLayerEnabled() {
      const pl = (this.portfolio.weight_model_params || {}).product_layer;
      return !!(pl && pl.enabled);
    },
    productLayerVolTarget() {
      const pl = (this.portfolio.weight_model_params || {}).product_layer || {};
      return pl.vol_target != null ? (pl.vol_target * 100).toFixed(1).replace(/\.0$/, '') : '2';
    }
  },
  watch: {
    id(newVal) {
      if (this.isDialog && newVal) {
        this.portfolioId = newVal;
        this.loadData();
      }
    }
  },
  methods: {
    async loadData() {
      this.loading = true;
      try {
        const portfolioRes = await portfolioApi.getPortfolio(this.portfolioId);
        this.portfolio = portfolioRes.data || {};

        await Promise.all([
          this.loadSubStrategyDetails(),
          this.loadParamVersions(),
          this.loadBacktestHistory(),
          this.loadLinkedModelStatus()
        ]);
      } catch (error) {
        this.$message.error('加载数据失败：' + (error.response?.data?.message || error.message));
      } finally {
        this.loading = false;
      }
    },

    async loadLinkedModelStatus() {
      // 优先使用后端组合接口返回的实盘状态
      if (this.portfolio.live_publish_enabled !== undefined) {
        this.linkedModelLive = !!this.portfolio.live_publish_enabled;
        if (this.linkedModelId) return; // 已有状态且有模型ID，无需再查
      }
      const mid = this.linkedModelId;
      if (!mid) return;
      try {
        const res = await getStrategyModel(mid);
        const model = res.data || {};
        this.linkedModelLive = !!model.live_publish_enabled;
      } catch { /* ignore */ }
    },

    getPublishTargetIds() {
      // 优先组合模型ID，否则回退到子策略模型
      const direct = this.linkedModelId;
      if (direct) return [direct];
      const subIds = (this.portfolio.sub_strategies || [])
        .map(s => s.model_id)
        .filter(Boolean);
      return [...new Set(subIds)];
    },

    async handleLivePublish() {
      const ids = this.getPublishTargetIds();
      if (!ids.length) {
        this.$message.warning('该组合无关联策略模型且无子策略，无法实盘发布');
        return;
      }
      try {
        await this.$confirm(
          `确认将组合「${this.portfolio.name}」实盘发布？发布后可在日常监控中跟踪。`,
          '实盘发布',
          { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
        );
      } catch { return; }
      this.livePublishing = true;
      try {
        for (const mid of ids) {
          await livePublishModel(mid, { source: 'portfolio_detail' });
        }
        this.$message.success('实盘发布成功，可在日常监控中添加该组合');
        this.linkedModelLive = true;
      } catch (e) {
        this.$message.error('实盘发布失败：' + (e.response?.data?.detail || e.message));
      } finally {
        this.livePublishing = false;
      }
    },

    async handleLiveUnpublish() {
      const ids = this.getPublishTargetIds();
      if (!ids.length) return;
      try {
        await this.$confirm(
          `确认取消组合「${this.portfolio.name}」的实盘发布？取消后将不再出现在日常监控准入列表中。`,
          '取消实盘发布',
          { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
        );
      } catch { return; }
      this.liveUnpublishing = true;
      try {
        for (const mid of ids) {
          await liveUnpublishModel(mid, { source: 'portfolio_detail' });
        }
        this.$message.success('已取消实盘发布');
        this.linkedModelLive = false;
      } catch (e) {
        this.$message.error('取消实盘失败：' + (e.response?.data?.detail || e.message));
      } finally {
        this.liveUnpublishing = false;
      }
    },

    async loadSubStrategyDetails() {
      if (!this.portfolio.sub_strategies || !this.portfolio.sub_strategies.length) return;
      this.loadingSubDetails = true;
      try {
        const promises = this.portfolio.sub_strategies.map(sub =>
          getStrategyModel(sub.model_id).catch(() => null)
        );
        const results = await Promise.all(promises);
        const details = {};
        results.forEach(res => {
          if (res) {
            const model = res.data || res;
            details[model.id] = model;
          }
        });
        this.subStrategyDetails = details;
      } catch (e) {
        console.error('加载子策略详情失败:', e);
      } finally {
        this.loadingSubDetails = false;
      }
    },

    async loadParamVersions() {
      const modelId = this.portfolio.portfolio_model_id || this.portfolio.model_id;
      if (!modelId) return;
      try {
        const res = await getParamVersions(modelId);
        this.paramVersions = Array.isArray(res) ? res : (res.data || []);
      } catch (e) {
        console.error('加载配置版本失败:', e);
      }
    },

    async loadBacktestHistory() {
      try {
        const res = await portfolioApi.getPortfolioBacktests(this.portfolioId);
        const list = Array.isArray(res) ? res : (res.data || []);
        list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        this.backtestHistory = list;
      } catch (e) {
        console.warn('加载回测历史失败:', e);
      }
    },

    toggleSubStrategy(idx) {
      this.expandedSubIdx = this.expandedSubIdx === idx ? null : idx;
    },

    toggleVersionDetail(verId) {
      this.expandedVersionId = this.expandedVersionId === verId ? null : verId;
    },

    viewBacktestDetail(record) {
      this.currentBacktestRecord = record;
      this.backtestDetailVisible = true;
    },

    viewModel(modelId) {
      this.currentModelId = modelId;
      this.modelDetailVisible = true;
    },

    async generateReport() {
      this.reportLoading = true;
      try {
        const modelId = this.portfolio.portfolio_model_id || this.portfolio.model_id;
        const res = await generatePortfolioReport({ model_id: modelId });
        this.portfolioReport = res.data || res;
      } catch (e) {
        const msg = e.response?.data?.detail || e.message || '生成报告失败';
        this.$message.error('组合报告生成失败：' + msg);
      } finally {
        this.reportLoading = false;
      }
    },

    async saveRemark(record) {
      try {
        const modelId = this.portfolio.portfolio_model_id || this.portfolio.model_id || this.portfolioId;
        await updateBacktestRemark(modelId, record.id, this.editingRemark);
        this.$message.success('备注已更新');
        this.editingRecordId = null;
        this.editingRemark = '';
        await this.loadBacktestHistory();
      } catch (err) {
        this.$message.error(err.response?.data?.detail || err.message || '更新失败');
      }
    },

    // ============================================================
    // 格式化
    // ============================================================
    formatNumber(num) {
      return new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num || 0);
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-';
    },
    formatDateShort(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '-';
    },
    getReturnColor(value) {
      return value >= 0 ? '#67c23a' : '#f56c6c';
    },
    getSourceTagType(source) {
      const map = { manual: 'info', single_strategy: '', portfolio_model: 'success' };
      return map[source] || 'info';
    },
    getSourceLabel(source) {
      const map = { manual: '手工创建', single_strategy: '单策略驱动', portfolio_model: '组合模型' };
      return map[source] || source || '—';
    },
    getWeightMethodLabel(method) {
      const map = { equal_weight: '等权', risk_parity: '风险平价', min_variance: '最小方差', custom: '自定义', quadrant: '四象限调权' };
      return map[method] || method || '—';
    },
    getRebalanceModeLabel(mode) {
      const map = { signal_driven: '信号触发', monthly_quadrant: '月度象限', monthly_inv_vol: '月度逆波动率' };
      return map[mode] || mode || '—';
    },
    getParamLabel(key) {
      // 与后端 schema 定义对齐的标准标签
      const map = {
        // 通用参数
        lookback_days: '历史数据回看期',
        rebalance_frequency: '调仓频率',
        
        // 风险平价 / 均值方差
        min_weight: '单资产最小权重',
        max_weight: '单资产最大权重',
        maxiter: '最大迭代次数',
        cov_method: '协方差估计方法',
        
        // 波动率控制
        target_vol: '目标年化波动率',
        vol_windows: '波动率计算窗口',
        vol_control_type: '波动率控制器类型',
        enable_vol_reset: '启用波动率阈值重置',
        vol_reset_threshold: '波动率重置阈值',
        vol_trigger_threshold: '波动率触发阈值',
        
        // 风险预算
        risk_budget: '风险预算',
        budget_source: '预算来源模式',
        budget_allocation_method: '预算分配方式',
        max_total_leverage: '最大杠杆倍数',
        
        // 资产选择
        select_count: '选择资产数量',
        
        // 组合特定
        vol_target: '波动率目标',
        vol_lookback_short: '短期窗口',
        vol_lookback_long: '长期窗口',
        momentum_enabled: '动量过滤',
        momentum_top_n: '动量TopN',
        ema_halflife: 'EMA半衰期',
      };
      return map[key] || key;
    },
    formatParamVal(value) {
      if (value === null || value === undefined) return '-';
      if (typeof value === 'boolean') return value ? '是' : '否';
      if (Array.isArray(value)) return value.join(', ');
      if (typeof value === 'object') return JSON.stringify(value, null, 2);
      return String(value);
    }
  }
};
</script>

<style scoped>
.page-container { padding: 20px; }
.page-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;
}
.page-title { font-size: 20px; font-weight: 500; color: #303133; margin: 0; }
.info-card { margin-bottom: 20px; }
.card-header {
  display: flex; justify-content: space-between; align-items: center; font-weight: 500;
}

/* 子策略块 */
.sub-strategy-block {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  margin-bottom: 8px;
  overflow: hidden;
}
.sub-strategy-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  background: #fafafa;
  transition: background 0.2s;
}
.sub-strategy-header:hover { background: #f0f2f5; }
.sub-strategy-params {
  padding: 10px 12px;
  border-top: 1px solid #ebeef5;
  background: #fff;
}

/* 报告 */
.metrics-row { margin-top: 10px; }
.metric-card {
  text-align: center;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 4px;
}
.metric-label { font-size: 14px; color: #909399; margin-bottom: 10px; }
.metric-value { font-size: 24px; font-weight: 600; color: #303133; }

/* 右栏回测历史 */
.history-card {
  max-height: calc(100vh - 140px);
  overflow-y: auto;
}
.history-item { margin-bottom: 10px; }
.history-info { margin-bottom: 6px; }
.history-metrics {
  font-size: 13px;
  line-height: 1.8;
  color: #606266;
}
</style>
