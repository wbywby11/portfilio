<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">信号监测</h2>
      <div>
        <el-button type="primary" icon="el-icon-refresh" @click="refreshData" :loading="loading">
          刷新数据
        </el-button>
      </div>
    </div>

    <div class="page-content" v-loading="loading">
      <el-row :gutter="20">
        <!-- 波动率监测面板 -->
        <el-col :span="12">
          <el-card class="info-card">
            <div slot="header" class="card-header">
              <span>波动率监测</span>
              <el-tag :type="volStatusType" size="small">{{ volStatusText }}</el-tag>
            </div>
            
            <div class="vol-display">
              <div class="vol-value" :class="volValueClass">
                {{ formatPercent(currentVolatility) }}
              </div>
              <div class="vol-label">当前波动率</div>
            </div>
            
            <el-progress
              :percentage="volPercentage"
              :color="volProgressColors"
              :stroke-width="20"
              :format="volProgressFormat"
              style="margin: 20px 0;"
            ></el-progress>
            
            <div class="vol-threshold">
              <span>波动率阈值: </span>
              <strong>{{ formatPercent(volThreshold) }}</strong>
            </div>

            <!-- 波动率趋势图 -->
            <div class="chart-container" ref="volChart" style="height: 250px; margin-top: 20px;"></div>
          </el-card>
        </el-col>

        <!-- 月度调仓日历 -->
        <el-col :span="12">
          <el-card class="info-card">
            <div slot="header" class="card-header">
              <span>月度调仓日历</span>
              <el-tag type="info" size="small" v-if="daysToNextRebalance !== null">
                距下次调仓 {{ daysToNextRebalance }} 天
              </el-tag>
            </div>
            
            <el-table :data="rebalanceCalendar" size="small" stripe border>
              <el-table-column prop="month" label="月份" width="100" align="center"></el-table-column>
              <el-table-column prop="calculate_date" label="计算日(月末)" width="120" align="center"></el-table-column>
              <el-table-column prop="execute_date" label="执行日(T+2)" width="120" align="center"></el-table-column>
              <el-table-column prop="status" label="状态" width="80" align="center">
                <template slot-scope="scope">
                  <el-tag :type="getCalendarStatusType(scope.row.status)" size="mini">
                    {{ scope.row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" align="center">
                <template slot-scope="scope">
                  <el-button
                    v-if="scope.row.status === '已执行'"
                    type="text"
                    size="small"
                    @click="viewRebalanceDetail(scope.row)"
                  >
                    详情
                  </el-button>
                  <span v-else style="color: #c0c4cc;">-</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20" style="margin-top: 20px;">
        <!-- Pending 调仓详情 -->
        <el-col :span="12">
          <el-card class="info-card">
            <div slot="header" class="card-header">
              <span>待执行调仓</span>
            </div>
            
            <div v-if="pendingRebalance">
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="调仓类型">
                  <el-tag :type="getPendingTypeTag(pendingRebalance.type)" size="small">
                    {{ getPendingTypeLabel(pendingRebalance.type) }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="信号日期">{{ pendingRebalance.signal_date }}</el-descriptions-item>
                <el-descriptions-item label="执行日期">{{ pendingRebalance.execute_date }}</el-descriptions-item>
                <el-descriptions-item label="缩放系数" v-if="pendingRebalance.scale_factor">
                  {{ pendingRebalance.scale_factor.toFixed(4) }}
                </el-descriptions-item>
              </el-descriptions>
              
              <div style="margin-top: 15px;">
                <div class="section-title">目标权重</div>
                <el-table :data="pendingWeightsList" size="mini" stripe border max-height="200">
                  <el-table-column prop="asset" label="资产" width="150"></el-table-column>
                  <el-table-column prop="weight" label="目标权重" align="right">
                    <template slot-scope="scope">
                      {{ formatPercent(scope.row.weight) }}
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </div>
            
            <el-empty v-else description="暂无待执行调仓"></el-empty>
          </el-card>
        </el-col>

        <!-- 波动率重置历史 -->
        <el-col :span="12">
          <el-card class="info-card">
            <div slot="header" class="card-header">
              <span>波动率重置历史</span>
            </div>
            
            <el-table :data="volResetHistory" size="small" stripe border max-height="350">
              <el-table-column prop="trigger_date" label="触发日期" width="110" align="center"></el-table-column>
              <el-table-column prop="execute_date" label="执行日期" width="110" align="center"></el-table-column>
              <el-table-column prop="trigger_volatility" label="触发波动率" width="100" align="right">
                <template slot-scope="scope">
                  {{ formatPercent(scope.row.trigger_volatility) }}
                </template>
              </el-table-column>
              <el-table-column prop="scale_factor" label="缩放系数" width="90" align="right">
                <template slot-scope="scope">
                  {{ scope.row.scale_factor ? scope.row.scale_factor.toFixed(4) : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" align="center">
                <template slot-scope="scope">
                  <el-button type="text" size="small" @click="viewVolResetDetail(scope.row)">
                    详情
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            
            <el-empty v-if="volResetHistory.length === 0" description="暂无波动率重置记录"></el-empty>
          </el-card>
        </el-col>
      </el-row>

      <!-- 调仓历史记录 -->
      <el-row :gutter="20" style="margin-top: 20px;">
        <el-col :span="24">
          <el-card class="info-card">
            <div slot="header" class="card-header">
              <span>调仓历史记录</span>
              <el-tag type="info" size="small">近20条</el-tag>
            </div>
            
            <el-table :data="rebalanceHistory" size="small" stripe border max-height="400">
              <el-table-column prop="date" label="执行日期" width="120" align="center"></el-table-column>
              <el-table-column prop="typeLabel" label="调仓类型" width="120" align="center">
                <template slot-scope="scope">
                  <el-tag :type="getRebalanceTypeTag(scope.row.type)" size="mini">
                    {{ scope.row.typeLabel }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="description" label="说明" min-width="180">
                <template slot-scope="scope">
                  {{ scope.row.description || '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="trading_cost" label="交易成本" width="100" align="right">
                <template slot-scope="scope">
                  {{ scope.row.trading_cost ? scope.row.trading_cost.toFixed(2) : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" align="center" fixed="right">
                <template slot-scope="scope">
                  <el-button type="text" size="small" @click="viewRebalanceEventDetail(scope.row)">
                    详情
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            
            <el-empty v-if="rebalanceHistory.length === 0" description="暂无调仓历史记录"></el-empty>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 波动率重置详情弹窗 -->
    <el-dialog title="波动率重置详情" :visible.sync="volResetDetailVisible" width="700px">
      <div v-if="currentVolReset">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="触发日期">{{ currentVolReset.trigger_date }}</el-descriptions-item>
          <el-descriptions-item label="执行日期">{{ currentVolReset.execute_date }}</el-descriptions-item>
          <el-descriptions-item label="触发波动率">{{ formatPercent(currentVolReset.trigger_volatility) }}</el-descriptions-item>
          <el-descriptions-item label="缩放系数">{{ currentVolReset.scale_factor ? currentVolReset.scale_factor.toFixed(4) : '-' }}</el-descriptions-item>
        </el-descriptions>
        
        <div style="margin-top: 20px;" v-if="currentVolReset.weights_before || currentVolReset.weights_after">
          <div class="section-title">权重变化</div>
          <el-table :data="volResetWeightsComparison" size="small" stripe border>
            <el-table-column prop="asset" label="资产" width="150"></el-table-column>
            <el-table-column prop="before" label="重置前权重" align="right">
              <template slot-scope="scope">
                {{ formatPercent(scope.row.before) }}
              </template>
            </el-table-column>
            <el-table-column prop="after" label="重置后权重" align="right">
              <template slot-scope="scope">
                {{ formatPercent(scope.row.after) }}
              </template>
            </el-table-column>
            <el-table-column label="变化" align="right">
              <template slot-scope="scope">
                <span :class="getChangeClass(scope.row.after - scope.row.before)">
                  {{ formatPercent(scope.row.after - scope.row.before, true) }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
      <span slot="footer">
        <el-button @click="volResetDetailVisible = false">关闭</el-button>
      </span>
    </el-dialog>

    <!-- 调仓详情弹窗 -->
    <el-dialog title="调仓详情" :visible.sync="rebalanceDetailVisible" width="800px">
      <div v-if="currentRebalance">
        <!-- 基本信息 -->
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="调仓类型">
            <el-tag :type="getRebalanceTypeTag(currentRebalance.type)" size="small">
              {{ currentRebalance.typeLabel }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="执行日期">{{ currentRebalance.date }}</el-descriptions-item>
          <el-descriptions-item label="计算日期" v-if="currentRebalance.calc_date">
            {{ currentRebalance.calc_date }}
          </el-descriptions-item>
          <el-descriptions-item label="交易成本">
            {{ currentRebalance.trading_cost ? currentRebalance.trading_cost.toFixed(2) : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="触发原因" :span="2" v-if="currentRebalance.description">
            {{ currentRebalance.description }}
          </el-descriptions-item>
        </el-descriptions>
        
        <!-- 权重对比表格 -->
        <div style="margin-top: 20px;" v-if="rebalanceWeightsComparison.length > 0">
          <div class="section-title">调仓前后权重对比</div>
          <el-table :data="rebalanceWeightsComparison" size="small" stripe border max-height="350">
            <el-table-column prop="asset" label="资产" width="150"></el-table-column>
            <el-table-column label="调仓前权重" align="right" width="120">
              <template slot-scope="scope">
                {{ formatPercent(scope.row.before) }}
              </template>
            </el-table-column>
            <el-table-column label="调仓后权重" align="right" width="120">
              <template slot-scope="scope">
                {{ formatPercent(scope.row.after) }}
              </template>
            </el-table-column>
            <el-table-column label="变动" align="right" width="100">
              <template slot-scope="scope">
                <span :class="getChangeClass(scope.row.change)">
                  {{ formatPercent(scope.row.change, true) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="direction" label="方向" align="center" width="80">
              <template slot-scope="scope">
                <el-tag :type="getDirectionTag(scope.row.direction)" size="mini">
                  {{ scope.row.direction }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          
          <!-- 汇总信息 -->
          <div class="weights-summary">
            <span>调仓前总权重: {{ formatPercent(rebalanceSummary.beforeTotal) }}</span>
            <span>调仓后总权重: {{ formatPercent(rebalanceSummary.afterTotal) }}</span>
          </div>
        </div>
        
        <!-- 无权重数据时的提示 -->
        <el-empty v-if="rebalanceWeightsComparison.length === 0" description="该调仓记录无权重明细数据"></el-empty>
      </div>
      <span slot="footer">
        <el-button @click="rebalanceDetailVisible = false">关闭</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import { mapState } from 'vuex';

export default {
  name: 'Signals',
  data() {
    return {
      loading: false,
      volThreshold: 0.06,  // 6%波动率阈值
      volResetDetailVisible: false,
      currentVolReset: null,
      volChart: null,
      volProgressColors: [
        { color: '#67c23a', percentage: 60 },
        { color: '#e6a23c', percentage: 80 },
        { color: '#f56c6c', percentage: 100 }
      ],
      // 调仓详情相关
      rebalanceDetailVisible: false,
      currentRebalance: null,
      allRebalanceEvents: []  // 所有调仓事件
    };
  },
  computed: {
    ...mapState('monitor', ['signals', 'events', 'monitorState']),
    
    currentVolatility() {
      return this.signals?.vol_reset?.current_volatility || 0;
    },
    
    volPercentage() {
      if (!this.volThreshold) return 0;
      const pct = (this.currentVolatility / this.volThreshold) * 100;
      return Math.min(pct, 100);
    },
    
    volStatusType() {
      const ratio = this.currentVolatility / this.volThreshold;
      if (ratio < 0.7) return 'success';
      if (ratio < 0.9) return 'warning';
      return 'danger';
    },
    
    volStatusText() {
      const ratio = this.currentVolatility / this.volThreshold;
      if (ratio < 0.7) return '正常';
      if (ratio < 0.9) return '接近阈值';
      if (ratio < 1) return '即将触发';
      return '已超阈值';
    },
    
    volValueClass() {
      const ratio = this.currentVolatility / this.volThreshold;
      if (ratio < 0.7) return 'vol-normal';
      if (ratio < 0.9) return 'vol-warning';
      return 'vol-danger';
    },
    
    daysToNextRebalance() {
      // 从 monthly_rebalance.next_date 计算天数
      const nextDate = this.signals?.monthly_rebalance?.next_date;
      if (!nextDate) return null;
      const today = new Date();
      const target = new Date(nextDate);
      const diffTime = target - today;
      return Math.max(0, Math.ceil(diffTime / (1000 * 60 * 60 * 24)));
    },
    
    rebalanceCalendar() {
      // 后端可能不提供此字段，返回空数组
      return this.signals?.rebalance_calendar || [];
    },
    
    pendingRebalance() {
      return this.signals?.pending_rebalance || null;
    },
    
    pendingWeightsList() {
      if (!this.pendingRebalance?.weights) return [];
      return Object.entries(this.pendingRebalance.weights).map(([asset, weight]) => ({
        asset,
        weight
      }));
    },
    
    volResetHistory() {
      if (!this.events) return [];
      return this.events.filter(e => e.type === 'vol_reset').slice(0, 10);
    },
    
    volResetWeightsComparison() {
      if (!this.currentVolReset) return [];
      const before = this.currentVolReset.weights_before || {};
      const after = this.currentVolReset.weights_after || {};
      const assets = [...new Set([...Object.keys(before), ...Object.keys(after)])];
      return assets.map(asset => ({
        asset,
        before: before[asset] || 0,
        after: after[asset] || 0
      }));
    },
    
    // 调仓历史记录（所有类型）
    rebalanceHistory() {
      const typeLabels = {
        'monthly_rebalance': '月度调仓',
        'vol_reset_execute': '波动率重置',
        'subjective_rebalance': '主观调仓'
      };
      
      return this.allRebalanceEvents
        .filter(e => ['monthly_rebalance', 'vol_reset_execute', 'subjective_rebalance'].includes(e.type))
        .map(e => ({
          ...e,
          typeLabel: typeLabels[e.type] || e.type
        }))
        .sort((a, b) => (b.date || '').localeCompare(a.date || ''))
        .slice(0, 20);
    },
    
    // 调仓权重对比
    rebalanceWeightsComparison() {
      if (!this.currentRebalance) return [];
      const oldWeights = this.currentRebalance.old_weights || {};
      const newWeights = this.currentRebalance.new_weights || {};
      const assets = [...new Set([...Object.keys(oldWeights), ...Object.keys(newWeights)])];
      
      return assets
        .map(asset => {
          const before = oldWeights[asset] || 0;
          const after = newWeights[asset] || 0;
          const change = after - before;
          
          let direction = '不变';
          if (Math.abs(before) < 1e-6 && after > 1e-6) {
            direction = '新增';
          } else if (before > 1e-6 && Math.abs(after) < 1e-6) {
            direction = '清仓';
          } else if (change > 1e-6) {
            direction = '增持';
          } else if (change < -1e-6) {
            direction = '减持';
          }
          
          return { asset, before, after, change, direction };
        })
        .filter(item => Math.abs(item.before) > 1e-6 || Math.abs(item.after) > 1e-6)
        .sort((a, b) => Math.abs(b.change) - Math.abs(a.change));
    },
    
    // 调仓汇总
    rebalanceSummary() {
      if (!this.currentRebalance) {
        return { beforeTotal: 0, afterTotal: 0 };
      }
      const oldWeights = this.currentRebalance.old_weights || {};
      const newWeights = this.currentRebalance.new_weights || {};
      const beforeTotal = Object.values(oldWeights).reduce((sum, v) => sum + (v || 0), 0);
      const afterTotal = Object.values(newWeights).reduce((sum, v) => sum + (v || 0), 0);
      return { beforeTotal, afterTotal };
    }
  },
  created() {
    this.loadData();
  },
  mounted() {
    this.$nextTick(() => {
      this.initChart();
    });
  },
  beforeDestroy() {
    if (this.volChart) {
      this.volChart.dispose();
    }
  },
  methods: {
    async loadData() {
      this.loading = true;
      try {
        await Promise.all([
          this.$store.dispatch('monitor/fetchSignals'),
          this.$store.dispatch('monitor/fetchEvents', { type: 'vol_reset', limit: 50 }),
          this.fetchAllRebalanceEvents()
        ]);
        this.updateChart();
      } catch (error) {
        this.$message.error('加载数据失败：' + error.message);
      } finally {
        this.loading = false;
      }
    },
    
    async fetchAllRebalanceEvents() {
      // 获取所有调仓事件（不指定 type 以获取全部）
      try {
        const res = await this.$store.dispatch('monitor/fetchEvents', { limit: 100 });
        const data = Array.isArray(res) ? res : (res && res.data ? res.data : []);
        this.allRebalanceEvents = data;
      } catch (error) {
        console.error('获取调仓事件失败:', error);
        this.allRebalanceEvents = [];
      }
    },
    
    async refreshData() {
      await this.loadData();
      this.$message.success('数据已刷新');
    },
    
    initChart() {
      if (!this.$refs.volChart) return;
      this.volChart = echarts.init(this.$refs.volChart);
      this.updateChart();
      
      window.addEventListener('resize', () => {
        this.volChart && this.volChart.resize();
      });
    },
    
    updateChart() {
      if (!this.volChart) return;
      
      const volHistory = this.signals?.volatility_history || [];
      const dates = volHistory.map(v => v.date);
      const values = volHistory.map(v => (v.value * 100).toFixed(2));
      
      const option = {
        title: {
          text: '波动率趋势(近30日)',
          textStyle: { fontSize: 14, fontWeight: 'normal' }
        },
        tooltip: {
          trigger: 'axis',
          formatter: '{b}<br/>波动率: {c}%'
        },
        grid: {
          left: '10%',
          right: '5%',
          bottom: '15%',
          top: '15%'
        },
        xAxis: {
          type: 'category',
          data: dates,
          axisLabel: {
            rotate: 45,
            fontSize: 10
          }
        },
        yAxis: {
          type: 'value',
          axisLabel: {
            formatter: '{value}%'
          }
        },
        series: [{
          name: '波动率',
          type: 'line',
          data: values,
          smooth: true,
          lineStyle: { width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
              { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
            ])
          },
          markLine: {
            silent: true,
            data: [{
              yAxis: this.volThreshold * 100,
              lineStyle: { color: '#f56c6c', type: 'dashed' },
              label: { formatter: '阈值 {c}%' }
            }]
          }
        }]
      };
      
      this.volChart.setOption(option);
    },
    
    formatPercent(val, showSign = false) {
      if (val === null || val === undefined) return '-';
      const pct = (val * 100).toFixed(2);
      if (showSign && val > 0) return '+' + pct + '%';
      return pct + '%';
    },
    
    volProgressFormat() {
      return this.formatPercent(this.currentVolatility);
    },
    
    getCalendarStatusType(status) {
      const map = {
        '已执行': 'success',
        '待执行': 'warning',
        '未到': 'info'
      };
      return map[status] || 'info';
    },
    
    getPendingTypeTag(type) {
      const map = {
        'monthly': 'primary',
        'vol_reset': 'warning',
        'subjective': 'success'
      };
      return map[type] || '';
    },
    
    getPendingTypeLabel(type) {
      const map = {
        'monthly': '月度调仓',
        'vol_reset': '波动率重置',
        'subjective': '主观调仓'
      };
      return map[type] || type;
    },
    
    viewVolResetDetail(row) {
      this.currentVolReset = row;
      this.volResetDetailVisible = true;
    },
    
    // 查看调仓日历中的详情
    viewRebalanceDetail(row) {
      // 从 allRebalanceEvents 中查找对应日期的调仓事件
      const event = this.allRebalanceEvents.find(e => 
        e.date === row.execute_date && 
        ['monthly_rebalance', 'vol_reset_execute', 'subjective_rebalance'].includes(e.type)
      );
      
      if (event) {
        const typeLabels = {
          'monthly_rebalance': '月度调仓',
          'vol_reset_execute': '波动率重置',
          'subjective_rebalance': '主观调仓'
        };
        this.currentRebalance = {
          ...event,
          typeLabel: typeLabels[event.type] || event.type
        };
        this.rebalanceDetailVisible = true;
      } else {
        this.$message.warning('未找到该日期的调仓详情记录');
      }
    },
    
    // 查看调仓历史记录的详情
    viewRebalanceEventDetail(row) {
      this.currentRebalance = row;
      this.rebalanceDetailVisible = true;
    },
    
    // 获取调仓类型 tag
    getRebalanceTypeTag(type) {
      const map = {
        'monthly_rebalance': 'primary',
        'vol_reset_execute': 'warning',
        'subjective_rebalance': 'success'
      };
      return map[type] || 'info';
    },
    
    // 获取方向 tag
    getDirectionTag(direction) {
      const map = {
        '新增': 'success',
        '清仓': 'danger',
        '增持': 'primary',
        '减持': 'warning',
        '不变': 'info'
      };
      return map[direction] || 'info';
    },
    
    getChangeClass(change) {
      if (change > 0) return 'number-positive';
      if (change < 0) return 'number-negative';
      return '';
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

.page-content {
  background: #f5f7fa;
  padding: 20px;
  border-radius: 4px;
}

.info-card {
  margin-bottom: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.vol-display {
  text-align: center;
  padding: 20px 0;
}

.vol-value {
  font-size: 48px;
  font-weight: 600;
  line-height: 1;
}

.vol-label {
  font-size: 14px;
  color: #909399;
  margin-top: 10px;
}

.vol-normal {
  color: #67c23a;
}

.vol-warning {
  color: #e6a23c;
}

.vol-danger {
  color: #f56c6c;
}

.vol-threshold {
  text-align: center;
  color: #606266;
  font-size: 14px;
}

.section-title {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 10px;
}

.number-positive {
  color: #67c23a;
}

.number-negative {
  color: #f56c6c;
}

.chart-container {
  border-top: 1px solid #ebeef5;
  padding-top: 15px;
}

/* 调仓详情样式 */
.weights-summary {
  display: flex;
  justify-content: space-around;
  padding: 15px;
  margin-top: 15px;
  background-color: #f5f7fa;
  border-radius: 4px;
}

.weights-summary span {
  font-size: 14px;
  color: #606266;
}
</style>
