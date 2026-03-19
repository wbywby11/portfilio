<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">策略详情</h2>
      <div>
        <el-button @click="$router.back()">返回</el-button>
        <el-button
          type="primary"
          @click="handleBacktest"
          :disabled="model.status === '已发布' || model.status === 'published'"
          :loading="backtesting"
        >
          {{ backtesting ? '回测中...' : '运行回测' }}
        </el-button>
        <el-button
          type="success"
          @click="handlePublish"
          :disabled="model.status === '已发布' || model.status === 'published' || !hasBacktestResult"
        >
          发布策略
        </el-button>
        <el-button
          type="primary"
          @click="handleLivePublish"
          :disabled="model.status === '已归档' || model.status === 'archived'"
        >
          {{ model.live_publish_enabled ? '发布到最新实盘' : '实盘发布' }}
        </el-button>
        <el-button
          type="warning"
          icon="el-icon-plus"
          @click="handleCreatePortfolio"
          :disabled="model.status !== '已发布' && model.status !== 'published'"
        >
          创建模拟组合
        </el-button>
      </div>
    </div>
    <div v-else style="margin-bottom: 20px; display: flex; justify-content: flex-end; gap: 10px;">
        <el-button
          type="primary"
          size="small"
          @click="handleBacktest"
          :disabled="model.status === '已发布' || model.status === 'published'"
          :loading="backtesting"
        >
          {{ backtesting ? '回测中...' : '运行回测' }}
        </el-button>
        <el-button
          type="success"
          size="small"
          @click="handlePublish"
          :disabled="model.status === '已发布' || model.status === 'published' || !hasBacktestResult"
        >
          发布策略
        </el-button>
        <el-button
          type="primary"
          size="small"
          @click="handleLivePublish"
          :disabled="model.status === '已归档' || model.status === 'archived'"
        >
          {{ model.live_publish_enabled ? '发布到最新实盘' : '实盘发布' }}
        </el-button>
        <el-button
          type="warning"
          size="small"
          icon="el-icon-plus"
          @click="handleCreatePortfolio"
          :disabled="model.status !== '已发布' && model.status !== 'published'"
        >
          创建模拟组合
        </el-button>
    </div>

    <div :class="{'page-content': !isDialog}" v-loading="loading">
      <el-row :gutter="20">
        <el-col :span="16">
          <!-- 基本信息 -->
          <el-card shadow="never" class="info-card">
            <div slot="header" class="card-header">
              <span>基本信息</span>
              <el-button type="text" size="small" @click="handleEdit">编辑</el-button>
            </div>

            <el-descriptions :column="2" border>
              <el-descriptions-item label="策略名称">{{ model.name }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="getStatusType(model.status)" size="small">
                  {{ getStatusLabel(model.status) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="算法模板">
                {{ model.template_name || model.template_code }}
              </el-descriptions-item>
              <el-descriptions-item label="调仓频率">{{ model.rebalance_frequency }}</el-descriptions-item>
              <el-descriptions-item label="业绩基准" v-if="model.benchmark_name">
                {{ model.benchmark_name }}
              </el-descriptions-item>
              <el-descriptions-item label="创建时间" :span="2">
                {{ formatDate(model.created_at) }}
              </el-descriptions-item>
              <el-descriptions-item label="策略描述" :span="2">
                {{ model.description || '暂无描述' }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <!-- 资产选择配置 -->
          <el-card shadow="never" class="info-card" v-if="model.enable_momentum_selection">
            <div slot="header">资产选择配置</div>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="启用状态">
                <el-tag type="success" size="small">已启用</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="选择器类型">
                {{ getSelectorName(model.selector_type) }}
              </el-descriptions-item>
              <el-descriptions-item label="选择资产数量">
                {{ model.asset_selection_count || '未设置' }}
              </el-descriptions-item>
              <el-descriptions-item label="最小历史数据要求">
                {{ model.min_history_days || 260 }} 天
              </el-descriptions-item>
              <el-descriptions-item label="动量窗口" v-if="model.momentum_windows">
                {{ model.momentum_windows }}
              </el-descriptions-item>
              <el-descriptions-item label="并列决胜窗口" v-if="model.tie_break_window">
                {{ model.tie_break_window }} 天
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <!-- 策略参数 -->
          <el-card shadow="never" class="info-card">
            <div slot="header">策略参数</div>
            <el-descriptions :column="2" border v-if="model.parameters && Object.keys(model.parameters).length > 0">
              <el-descriptions-item
                v-for="(value, key) in model.parameters"
                :key="key"
                :label="getParameterLabel(key)"
              >
                <div style="white-space: pre-wrap;">{{ formatParameterValue(value) }}</div>
              </el-descriptions-item>
            </el-descriptions>
            <div v-else style="color: #909399; text-align: center; padding: 20px;">
              暂无参数
            </div>
          </el-card>

          <!-- 资产列表 -->
          <el-card shadow="never" class="info-card">
            <div slot="header">选择的资产</div>
            <el-tag
              v-for="code in model.asset_codes"
              :key="code"
              style="margin-right: 10px; margin-bottom: 10px;"
            >
              {{ code }} - {{ model.asset_names && model.asset_names[code] || '未知资产' }}
            </el-tag>
            <div v-if="!model.asset_codes || model.asset_codes.length === 0" style="color: #909399; text-align: center; padding: 20px;">
              未选择资产
            </div>
          </el-card>

          <!-- 回测结果 -->
          <el-card shadow="never" class="info-card" v-if="hasBacktestResult">
            <div slot="header">
              <span>最新回测结果</span>
              <span style="float: right; color: #909399; font-size: 13px;">
                回测时间: {{ formatDate(latestBacktest.created_at) }}
              </span>
            </div>

            <el-row :gutter="20" class="metrics-row">
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">总收益率</div>
                  <div class="metric-value" :style="{ color: getReturnColor(latestBacktest.result.total_return) }">
                    {{ (latestBacktest.result.total_return * 100).toFixed(2) }}%
                  </div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">年化收益率</div>
                  <div class="metric-value" :style="{ color: getReturnColor(latestBacktest.result.annual_return) }">
                    {{ (latestBacktest.result.annual_return * 100).toFixed(2) }}%
                  </div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">年化波动率</div>
                  <div class="metric-value">
                    {{ (latestBacktest.result.annual_volatility * 100).toFixed(2) }}%
                  </div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">夏普比率</div>
                  <div class="metric-value" :style="{ color: latestBacktest.result.sharpe_ratio > 0 ? '#67c23a' : '#909399' }">
                    {{ latestBacktest.result.sharpe_ratio ? latestBacktest.result.sharpe_ratio.toFixed(3) : '-' }}
                  </div>
                </div>
              </el-col>
            </el-row>

            <el-row :gutter="20" class="metrics-row" style="margin-top: 15px;">
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">最大回撤</div>
                  <div class="metric-value" style="color: #f56c6c;">
                    {{ (latestBacktest.result.max_drawdown * 100).toFixed(2) }}%
                  </div>
                </div>
              </el-col>
              <el-col :span="6" v-if="latestBacktest.result.calmar_ratio">
                <div class="metric-card">
                  <div class="metric-label">卡玛比率</div>
                  <div class="metric-value">
                    {{ latestBacktest.result.calmar_ratio.toFixed(3) }}
                  </div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">回测区间</div>
                  <div class="metric-value" style="font-size: 14px;">
                    {{ formatDateShort(latestBacktest.start_date) }}
                    <br>
                    {{ formatDateShort(latestBacktest.end_date) }}
                  </div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="metric-card">
                  <div class="metric-label">初始资金</div>
                  <div class="metric-value" style="font-size: 16px;">
                    ￥{{ latestBacktest.initial_capital.toLocaleString() }}
                  </div>
                </div>
              </el-col>
            </el-row>

            <el-row :gutter="20" class="metrics-row" style="margin-top: 15px;" v-if="latestBacktest.benchmark_name">
              <el-col :span="12">
                <div class="metric-card">
                  <div class="metric-label">业绩基准</div>
                  <div class="metric-value">
                    {{ latestBacktest.benchmark_code ? latestBacktest.benchmark_code + ' - ' + latestBacktest.benchmark_name : latestBacktest.benchmark_name }}
                  </div>
                </div>
              </el-col>
              <el-col :span="12"></el-col>
            </el-row>

            <!-- 回测图表区域 -->
            <div v-if="latestBacktest.result.equity_curve" style="margin-top: 20px;">
              <div ref="equityChart" style="width: 100%; height: 400px;"></div>
            </div>
          </el-card>
        </el-col>

        <el-col :span="8">
          <!-- 历史回测记录 -->
          <el-card shadow="never" class="history-card">
            <div slot="header">
              <span>历史回测记录</span>
              <span style="float: right; font-size: 12px; color: #909399;">
                共 {{ backtestPagination.total }} 条
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
                      初始资金: ￥{{ record.initial_capital.toLocaleString() }}
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
                    <div>夏普比率: {{ record.result.sharpe_ratio ? record.result.sharpe_ratio.toFixed(3) : '-' }}</div>
                    <div>最大回撤: <span style="color: #f56c6c;">
                      {{ (record.result.max_drawdown * 100).toFixed(2) }}%
                    </span></div>
                  </div>
                  <div style="margin-top: 10px;">
                    <el-button type="text" size="small" @click="viewBacktestDetail(record)">查看详情</el-button>
                    <el-button type="text" size="small" @click="editingRecordId = record.id; editingRemark = record.remark || ''">{{ editingRecordId === record.id ? '' : '编辑备注' }}</el-button>
                  </div>
                </el-card>
              </el-timeline-item>
            </el-timeline>
            <div v-else style="color: #909399; text-align: center; padding: 20px;">
              暂无回测记录
            </div>
            
            <!-- 分页 -->
            <div v-if="backtestPagination.total > backtestPagination.limit" style="text-align: center; margin-top: 20px;">
              <el-pagination
                small
                layout="prev, pager, next"
                :current-page="currentPage"
                :page-size="backtestPagination.limit"
                :total="backtestPagination.total"
                @current-change="handleBacktestPageChange"
              >
              </el-pagination>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 回测配置对话框 -->
    <backtest-dialog
      v-model="backtestDialogVisible"
      :model-id="modelId"
      @success="handleBacktestSuccess"
    />

    <!-- 回测详情对话框 -->
    <backtest-detail-dialog
      v-model="backtestDetailVisible"
      :record="currentBacktestRecord"
    />

    <!-- 创建模拟组合对话框 -->
    <el-dialog
      title="创建模拟组合"
      :visible.sync="createPortfolioVisible"
      width="600px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form
        ref="portfolioForm"
        :model="portfolioForm"
        :rules="portfolioRules"
        label-width="120px"
      >
        <el-form-item label="组合名称" prop="name">
          <el-input
            v-model="portfolioForm.name"
            placeholder="请输入组合名称"
            maxlength="50"
            show-word-limit
          ></el-input>
        </el-form-item>

        <el-form-item label="组合描述" prop="description">
          <el-input
            type="textarea"
            v-model="portfolioForm.description"
            placeholder="请输入组合描述"
            :rows="3"
            maxlength="200"
            show-word-limit
          ></el-input>
        </el-form-item>

        <el-form-item label="初始资金" prop="initial_capital">
          <el-input-number
            v-model="portfolioForm.initial_capital"
            :min="100000"
            :max="1000000000"
            :step="100000"
            :precision="2"
            controls-position="right"
            style="width: 100%;"
          ></el-input-number>
          <span style="margin-left: 10px; color: #909399;">元</span>
        </el-form-item>

        <el-form-item label="建仓日期" prop="inception_date">
          <el-date-picker
            v-model="portfolioForm.inception_date"
            type="date"
            placeholder="选择建仓日期"
            value-format="yyyy-MM-dd"
            style="width: 100%;"
          ></el-date-picker>
        </el-form-item>

        <el-form-item label="策略模型">
          <el-input :value="model.name" disabled></el-input>
        </el-form-item>

        <el-form-item label="资产列表">
          <el-tag
            v-for="code in model.asset_codes"
            :key="code"
            style="margin-right: 10px; margin-bottom: 5px;"
          >
            {{ code }}
          </el-tag>
        </el-form-item>
      </el-form>

      <div slot="footer" class="dialog-footer">
        <el-button @click="createPortfolioVisible = false">取消</el-button>
        <el-button
          type="primary"
          @click="handleConfirmCreatePortfolio"
          :loading="creatingPortfolio"
        >
          确定创建
        </el-button>
      </div>
    </el-dialog>

    <!-- 策略编辑弹窗 -->
    <el-dialog
      title="编辑策略"
      :visible.sync="editDialogVisible"
      width="1000px"
      append-to-body
    >
      <strategy-model-form
        v-if="editDialogVisible"
        is-dialog
        :id="modelId"
        @success="handleEditSuccess"
        @close="editDialogVisible = false"
      />
    </el-dialog>

    <!-- 组合详情弹窗 -->
    <el-dialog
      title="组合详情"
      :visible.sync="portfolioDetailVisible"
      width="1200px"
      append-to-body
    >
      <portfolio-detail
        v-if="portfolioDetailVisible"
        is-dialog
        :id="newPortfolioId"
      />
    </el-dialog>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import * as echarts from 'echarts';
import BacktestDialog from '@/components/BacktestDialog.vue';
import BacktestDetailDialog from '@/components/BacktestDetailDialog.vue';
import { updateBacktestRemark } from '@/api/strategy';

export default {
  name: 'StrategyModelDetail',
  components: {
    BacktestDialog,
    BacktestDetailDialog,
    StrategyModelForm: () => import('./StrategyModelForm.vue'),
    PortfolioDetail: () => import('@/views/portfolio/PortfolioDetail.vue')
  },
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
      modelId: null,
      model: {
        name: '',
        status: 'draft',
        template_code: '',
        description: '',
        parameters: {},
        asset_codes: [],
        rebalance_frequency: '',
        created_at: null
      },
      backtestHistory: [],
      backtestPagination: {
        skip: 0,
        limit: 10,
        total: 0
      },
      loading: false,
      backtesting: false,
      equityChart: null,
      backtestDialogVisible: false,
      backtestDetailVisible: false,
      currentBacktestRecord: {
        id: '',
        start_date: '',
        end_date: '',
        initial_capital: 0,
        result: {},
        created_at: ''
      },
      createPortfolioVisible: false,
      creatingPortfolio: false,
      portfolioForm: {
        name: '',
        description: '',
        initial_capital: 1000000,
        inception_date: ''
      },
      portfolioRules: {
        name: [
          { required: true, message: '请输入组合名称', trigger: 'blur' },
          { min: 2, max: 50, message: '长度在2到50个字符', trigger: 'blur' }
        ],
        initial_capital: [
          { required: true, message: '请输入初始资金', trigger: 'blur' }
        ],
        inception_date: [
          { required: true, message: '请选择建仓日期', trigger: 'change' }
        ]
      },
      editDialogVisible: false,
      portfolioDetailVisible: false,
      newPortfolioId: '',
      editingRecordId: null,
      editingRemark: ''
    };
  },
  computed: {
    hasBacktestResult() {
      return this.backtestHistory.length > 0;
    },
    latestBacktest() {
      return this.backtestHistory[0] || null;
    },
    currentPage() {
      return Math.floor(this.backtestPagination.skip / this.backtestPagination.limit) + 1;
    }
  },
  created() {
    this.modelId = this.isDialog ? this.id : this.$route.params.id;
    this.loadData();
  },
  watch: {
    id(newVal) {
      if (this.isDialog && newVal) {
        this.modelId = newVal;
        this.loadData();
      }
    }
  },
  mounted() {
    this.initChart();
  },
  beforeDestroy() {
    if (this.equityChart) {
      this.equityChart.dispose();
    }
  },
  methods: {
    async loadData() {
      this.loading = true;
      try {
        // 加载策略模型详情
        this.model = await this.$store.dispatch('strategy/fetchStrategyModel', this.modelId);
        
        // 加载回测历史
        await this.loadBacktestHistory();
        
        // 渲染最新回测结果图表
        if (this.hasBacktestResult) {
          this.$nextTick(() => {
            this.renderEquityChart();
          });
        }
      } catch (error) {
        this.$message.error('加载数据失败');
      } finally {
        this.loading = false;
      }
    },
    async loadBacktestHistory(keepPosition = false) {
      try {
        // 如果不保持位置，重置到第一页
        if (!keepPosition) {
          this.backtestPagination.skip = 0;
        }
        
        const res = await this.$store.dispatch('strategy/fetchBacktestHistory', {
          modelId: this.modelId,
          skip: this.backtestPagination.skip,
          limit: this.backtestPagination.limit
        });
        
        this.backtestHistory = res;
        
        // 获取总数：先查询一次大limit的请求来估算总数
        // 或者后端返回 total 字段
        if (res.length === this.backtestPagination.limit) {
          // 如果返回条数等于 limit，可能还有更多
          // 这里估算总数：当前 skip + limit + 1
          this.backtestPagination.total = this.backtestPagination.skip + this.backtestPagination.limit + 1;
        } else {
          // 如果返回条数少于 limit，说明已经是最后一页
          this.backtestPagination.total = this.backtestPagination.skip + res.length;
        }
      } catch (error) {
        console.error('加载回测历史失败:', error);
      }
    },
    handleBacktestPageChange(page) {
      this.backtestPagination.skip = (page - 1) * this.backtestPagination.limit;
      this.loadBacktestHistory(true);
    },
    async handleBacktest() {
      this.backtestDialogVisible = true;
    },
    async handleBacktestSuccess(result) {
      // 回测完成后，重新加载数据并显示结果
      await this.loadData();
      
      // 如果有最新的回测结果，自动打开详情
      if (this.hasBacktestResult) {
        this.$message.success('回测完成，点击历史记录中的“查看详情”按钮查看完整报告');
      }
    },
    async handlePublish() {
      this.$confirm('确定要发布该策略吗？发布后策略将可以被其他模块使用。', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('strategy/publishModel', this.modelId);
          this.$message.success('发布成功');
          await this.loadData();
        } catch (error) {
          this.$message.error('发布失败：' + (error.response?.data?.detail || error.message));
        }
      }).catch(() => {});
    },
    async handleLivePublish() {
      const actionText = this.model.live_publish_enabled ? '更新到最新实盘版本' : '实盘发布';
      this.$confirm(`确定要${actionText}吗？新版本将于次交易日生效。`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('strategy/livePublishModel', {
            modelId: this.modelId,
            data: { source: 'strategy' }
          });
          this.$message.success(`${actionText}成功`);
          await this.loadData();
        } catch (error) {
          this.$message.error(`${actionText}失败：` + (error.response?.data?.detail || error.message));
        }
      }).catch(() => {});
    },
    handleEdit() {
      this.editDialogVisible = true;
    },
    handleEditSuccess() {
      this.editDialogVisible = false;
      this.loadData().then(() => {
        if (this.model.live_publish_enabled) {
          this.$confirm('策略配置已修改，是否同步发布到最新实盘版本？', '提示', {
            confirmButtonText: '同步发布',
            cancelButtonText: '稍后处理',
            type: 'warning'
          }).then(async () => {
            try {
              await this.$store.dispatch('strategy/livePublishModel', {
                modelId: this.modelId,
                data: { source: 'strategy' }
              });
              this.$message.success('已同步发布到最新实盘版本');
              await this.loadData();
            } catch (error) {
              this.$message.error('同步发布失败：' + (error.response?.data?.detail || error.message));
            }
          }).catch(() => {});
        }
      });
    },
    handleCreatePortfolio() {
      // 重置表单
      this.portfolioForm = {
        name: `${this.model.name}-模拟组合`,
        description: `基于策略模型「${this.model.name}」创建的模拟组合`,
        initial_capital: 1000000,
        inception_date: new Date().toISOString().split('T')[0]
      };
      this.createPortfolioVisible = true;
    },
    async handleConfirmCreatePortfolio() {
      try {
        // 验证表单
        await this.$refs.portfolioForm.validate();
        
        this.creatingPortfolio = true;

        // 根据最新回测结果获取最近一次的持仓快照
        let positions = [];
        if (this.hasBacktestResult && this.latestBacktest.result && this.latestBacktest.result.position_records) {
          const positionRecords = this.latestBacktest.result.position_records;
          if (positionRecords.length > 0) {
            // 获取最后一次调仓的持仓
            const lastRecord = positionRecords[positionRecords.length - 1];
            positions = lastRecord.positions.map(pos => ({
              asset_code: pos.asset_code,
              asset_name: pos.asset_name,
              weight: pos.weight
            }));
          }
        }
        
        // 如果没有回测结果，使用平均权重
        if (positions.length === 0 && this.model.asset_codes && this.model.asset_codes.length > 0) {
          const equalWeight = 1.0 / this.model.asset_codes.length;
          positions = this.model.asset_codes.map(code => ({
            asset_code: code,
            asset_name: this.model.asset_names && this.model.asset_names[code] || code,
            weight: equalWeight
          }));
        }

        // 构造请求数据
        const portfolioData = {
          name: this.portfolioForm.name,
          portfolio_type: '模型驱动',
          description: this.portfolioForm.description,
          model_id: this.modelId,
          initial_capital: this.portfolioForm.initial_capital,
          inception_date: new Date(this.portfolioForm.inception_date).toISOString(),
          created_by: '系统',
          positions: positions
        };

        // 调用API创建组合
        const portfolioId = await this.$store.dispatch('portfolio/createPortfolio', portfolioData);
        
        this.$message.success('组合创建成功！');
        this.createPortfolioVisible = false;
        
        // 询问是否跳转到组合详情
        this.$confirm('组合已创建成功，是否立即查看组合详情？', '提示', {
          confirmButtonText: '查看详情',
          cancelButtonText: '留在当前页',
          type: 'success'
        }).then(() => {
          this.newPortfolioId = portfolioId;
          this.portfolioDetailVisible = true;
        }).catch(() => {});
        
      } catch (error) {
        if (error !== false) { // 表单验证失败不显示错误
          this.$message.error('创建组合失败：' + (error.response?.data?.message || error.message || '未知错误'));
        }
      } finally {
        this.creatingPortfolio = false;
      }
    },
    viewBacktestDetail(record) {
      this.currentBacktestRecord = record;
      this.backtestDetailVisible = true;
    },
    async saveRemark(record) {
      try {
        await updateBacktestRemark(this.modelId, record.id, this.editingRemark);
        this.$message.success('备注已更新');
        this.editingRecordId = null;
        this.editingRemark = '';
        await this.loadBacktestHistory(true);
      } catch (err) {
        this.$message.error(err.response?.data?.detail || err.message || '更新失败');
      }
    },
    initChart() {
      if (this.$refs.equityChart) {
        this.equityChart = echarts.init(this.$refs.equityChart);
      }
    },
    renderEquityChart() {
      if (!this.equityChart || !this.latestBacktest || !this.latestBacktest.result.equity_curve) {
        return;
      }

      const equityCurve = this.latestBacktest.result.equity_curve;
      const dates = equityCurve.map(item => item.date);
      const values = equityCurve.map(item => item.value);

      const option = {
        title: {
          text: '权益曲线',
          left: 'center'
        },
        tooltip: {
          trigger: 'axis'
        },
        xAxis: {
          type: 'category',
          data: dates,
          boundaryGap: false
        },
        yAxis: {
          type: 'value',
          axisLabel: {
            formatter: '{value}'
          }
        },
        series: [
          {
            name: '权益',
            type: 'line',
            data: values,
            smooth: true,
            lineStyle: {
              width: 2,
              color: '#409EFF'
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [{
                  offset: 0, color: 'rgba(64, 158, 255, 0.3)'
                }, {
                  offset: 1, color: 'rgba(64, 158, 255, 0.05)'
                }]
              }
            }
          }
        ]
      };

      this.equityChart.setOption(option);
    },
    getStatusType(status) {
      const map = {
        '草稿': 'info',
        '已发布': 'success',
        '已归档': '',
        // 兼容英文状态
        'draft': 'info',
        'published': 'success',
        'archived': ''
      };
      return map[status] || 'info';
    },
    getStatusLabel(status) {
      const map = {
        '草稿': '草稿',
        '已发布': '已发布',
        '已归档': '已归档',
        // 兼容英文状态
        'draft': '草稿',
        'published': '已发布',
        'archived': '已归档'
      };
      return map[status] || status;
    },
    getReturnColor(value) {
      return value >= 0 ? '#67c23a' : '#f56c6c';
    },
    // 获取参数的中文标签
    getParameterLabel(key) {
      // 如果后端返回了 parameter_labels，使用中文标签
      if (this.model.parameter_labels && this.model.parameter_labels[key]) {
        return this.model.parameter_labels[key];
      }
      // 否则返回原始 key
      return key;
    },
    // 格式化参数值
    formatParameterValue(value) {
      if (value === null || value === undefined) {
        return '-';
      }
      if (typeof value === 'boolean') {
        return value ? '是' : '否';
      }
      if (Array.isArray(value)) {
        return value.join(', ');
      }
      if (typeof value === 'object') {
        return JSON.stringify(value, null, 2);
      }
      return value;
    },
    // 获取选择器名称
    getSelectorName(selectorType) {
      // 兼容处理：将旧的选择器类型映射为 momentum
      const normalizedType = (selectorType === 'reversal' || selectorType === 'momentum_reversal') ? 'momentum' : selectorType;
      const map = {
        'momentum': '动量选择器',
        'hybrid': '混合动量选择器'
      };
      return map[normalizedType] || normalizedType || '未知';
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-';
    },
    formatDateShort(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '-';
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

.info-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

.metrics-row {
  margin-top: 10px;
}

.metric-card {
  text-align: center;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 4px;
}

.metric-label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 10px;
}

.metric-value {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}

.history-card {
  max-height: calc(100vh - 140px);
  overflow-y: auto;
}

.history-item {
  margin-bottom: 10px;
}

.history-metrics {
  font-size: 13px;
  line-height: 1.8;
  color: #606266;
}
</style>
