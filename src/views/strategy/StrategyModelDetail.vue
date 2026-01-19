<template>
  <div class="page-container">
    <div class="page-header">
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
      </div>
    </div>

    <div class="page-content" v-loading="loading">
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
                  <el-button
                    type="text"
                    size="small"
                    @click="viewBacktestDetail(record)"
                    style="margin-top: 10px;"
                  >
                    查看详情
                  </el-button>
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
  </div>
</template>

<script>
import dayjs from 'dayjs';
import * as echarts from 'echarts';
import BacktestDialog from '@/components/BacktestDialog.vue';
import BacktestDetailDialog from '@/components/BacktestDetailDialog.vue';

export default {
  name: 'StrategyModelDetail',
  components: {
    BacktestDialog,
    BacktestDetailDialog
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
      }
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
    this.modelId = this.$route.params.id;
    this.loadData();
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
    handleEdit() {
      this.$router.push(`/strategy/model/edit/${this.modelId}`);
    },
    viewBacktestDetail(record) {
      this.currentBacktestRecord = record;
      this.backtestDetailVisible = true;
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
