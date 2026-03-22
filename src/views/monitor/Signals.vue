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
      <!-- ==================== Section 1: 风险预警区 ==================== -->
      <div class="section-block alert-section">
        <div class="section-header">
          <i class="el-icon-warning-outline"></i>
          <span>风险预警</span>
        </div>
        
        <!-- 待执行调仓预警 -->
        <el-alert
          v-if="pendingRebalance"
          :title="pendingAlertTitle"
          type="warning"
          :description="pendingAlertDesc"
          show-icon
          :closable="false"
          class="alert-item">
        </el-alert>
        
        <!-- 波动率超阈值预警 -->
        <el-alert
          v-if="volStatus === 'danger'"
          title="波动率预警"
          type="error"
          :description="'当前波动率 ' + formatPercent(currentVolatility) + ' 已超过阈值 ' + formatPercent(volThreshold)"
          show-icon
          :closable="false"
          class="alert-item">
        </el-alert>
        
        <!-- 波动率临界预警 -->
        <el-alert
          v-if="volStatus === 'warning'"
          title="波动率接近阈值"
          type="warning"
          :description="'当前波动率 ' + formatPercent(currentVolatility) + '，距触发阈值还差 ' + formatPercent(distanceToTrigger)"
          show-icon
          :closable="false"
          class="alert-item">
        </el-alert>
        
        <el-alert
          v-if="volStatus === 'nodata'"
          title="暂无信号数据"
          type="info"
          description="请先完成日常监控初始化并运行，或等待数据加载。"
          show-icon
          :closable="false"
          class="alert-item">
        </el-alert>

        <!-- 无风险提示 -->
        <el-alert
          v-if="!pendingRebalance && volStatus === 'normal'"
          title="无待处理事项"
          type="success"
          description="当前波动率正常，无待执行调仓"
          show-icon
          :closable="false"
          class="alert-item">
        </el-alert>
      </div>

      <!-- ==================== Section 2: 波动率监控区 ==================== -->
      <div class="section-block">
        <div class="section-header">
          <i class="el-icon-odometer"></i>
          <span>波动率监控</span>
          <el-tag :type="volStatusType" size="small" style="margin-left: 10px;">{{ volStatusText }}</el-tag>
        </div>
        
        <el-row :gutter="20">
          <!-- 左侧：波动率状态面板 -->
          <el-col :span="10">
            <el-card class="vol-panel" shadow="hover">
              <!-- 波动率大数字 -->
              <div class="vol-display">
                <div class="vol-value" :class="volValueClass">
                  {{ formatPercent(currentVolatility) }}
                </div>
                <div class="vol-label">当前组合波动率</div>
              </div>
              
              <!-- 进度条 -->
              <div class="vol-progress-wrapper">
                <el-progress
                  :percentage="volProgressPercent"
                  :color="volProgressColors"
                  :stroke-width="24"
                  :show-text="false">
                </el-progress>
                <div class="vol-progress-labels">
                  <span>0%</span>
                  <span>阈值: {{ formatPercent(volThreshold) }}</span>
                </div>
              </div>
              
              <!-- 距触发阈值 -->
              <div class="vol-distance" v-if="volStatus !== 'danger'">
                距触发阈值: <strong :style="{ color: distanceColor }">{{ formatPercent(distanceToTrigger) }}</strong>
              </div>
              <div class="vol-distance" v-else>
                <el-tag type="danger" size="medium">已超过阈值</el-tag>
              </div>
              
              <!-- 各窗口波动率 -->
              <div class="vol-windows">
                <div class="vol-window-item" v-for="(val, key) in volWindows" :key="key">
                  <span class="window-label">{{ key }}</span>
                  <span class="window-value">{{ formatPercent(val) }}</span>
                </div>
              </div>
            </el-card>
          </el-col>
          
          <!-- 右侧：波动率趋势图 -->
          <el-col :span="14">
            <el-card shadow="hover" class="chart-card">
              <div slot="header">
                <span>波动率趋势（近30日）</span>
              </div>
              <div class="chart-container" ref="volChart" style="height: 320px;"></div>
            </el-card>
          </el-col>
        </el-row>
      </div>

      <!-- ==================== Section 3: 调仓规划区 ==================== -->
      <div class="section-block">
        <div class="section-header">
          <i class="el-icon-date"></i>
          <span>调仓规划</span>
        </div>
        
        <!-- 调仓概览卡片 -->
        <el-row :gutter="20" class="rebalance-overview">
          <el-col :span="12">
            <el-card shadow="hover" class="overview-card">
              <div class="overview-icon success">
                <i class="el-icon-finished"></i>
              </div>
              <div class="overview-content">
                <div class="overview-label">上次调仓日期</div>
                <div class="overview-value">{{ lastRebalanceDate || '-' }}</div>
                <div class="overview-sub" v-if="lastRebalanceType">
                  <el-tag :type="getRebalanceTypeTag(lastRebalanceType)" size="mini">
                    {{ getRebalanceTypeLabel(lastRebalanceType) }}
                  </el-tag>
                </div>
              </div>
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="hover" class="overview-card" v-if="pendingRebalance">
              <div class="overview-icon warning">
                <i class="el-icon-bell"></i>
              </div>
              <div class="overview-content">
                <div class="overview-label">待执行调仓</div>
                <div class="overview-value">{{ pendingRebalance && pendingRebalance.execute_date }}</div>
                <div class="overview-sub">
                  <el-tag type="warning" size="mini">
                    {{ getPendingTypeLabel(pendingRebalance && pendingRebalance.type) }}
                  </el-tag>
                </div>
              </div>
            </el-card>
            <el-card shadow="hover" class="overview-card" v-else>
              <div class="overview-icon info">
                <i class="el-icon-check"></i>
              </div>
              <div class="overview-content">
                <div class="overview-label">待执行调仓</div>
                <div class="overview-value" style="color: #67C23A;">无</div>
                <div class="overview-sub">
                  <el-tag type="info" size="mini">暂无待执行</el-tag>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
        
        <!-- 调仓历史记录表 -->
        <el-card shadow="hover" class="history-card">
          <div slot="header">
            <span>调仓历史记录</span>
            <el-tag type="info" size="small" style="margin-left: 10px;">近20条</el-tag>
          </div>
          
          <el-table 
            :data="rebalanceHistory" 
            size="small" 
            stripe 
            border 
            row-key="id"
            :expand-row-keys="expandedRows"
            @expand-change="handleExpandChange">
            <el-table-column type="expand">
              <template slot-scope="scope">
                <div class="expand-content" v-if="scope.row.old_weights || scope.row.new_weights">
                  <div class="expand-title">权重变化详情</div>
                  <el-table :data="getWeightsComparison(scope.row)" size="mini" stripe>
                    <el-table-column prop="asset" label="资产" width="150"></el-table-column>
                    <el-table-column label="调仓前" align="right" width="100">
                      <template slot-scope="inner">
                        {{ formatPercent(inner.row.before) }}
                      </template>
                    </el-table-column>
                    <el-table-column label="调仓后" align="right" width="100">
                      <template slot-scope="inner">
                        {{ formatPercent(inner.row.after) }}
                      </template>
                    </el-table-column>
                    <el-table-column label="变动" align="right" width="100">
                      <template slot-scope="inner">
                        <span :class="getChangeClass(inner.row.change)">
                          {{ formatPercent(inner.row.change, true) }}
                        </span>
                      </template>
                    </el-table-column>
                    <el-table-column prop="direction" label="方向" align="center" width="80">
                      <template slot-scope="inner">
                        <el-tag :type="getDirectionTag(inner.row.direction)" size="mini">
                          {{ inner.row.direction }}
                        </el-tag>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
                <div class="expand-content" v-else>
                  <el-empty description="无权重变化数据" :image-size="60"></el-empty>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="date" label="执行日期" width="120" align="center"></el-table-column>
            <el-table-column prop="typeLabel" label="调仓类型" width="120" align="center">
              <template slot-scope="scope">
                <el-tag :type="getRebalanceTypeTag(scope.row.type)" size="mini">
                  {{ scope.row.typeLabel }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="触发原因" min-width="200">
              <template slot-scope="scope">
                {{ scope.row.description || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="trading_cost" label="交易成本" width="100" align="right">
              <template slot-scope="scope">
                {{ scope.row.trading_cost ? scope.row.trading_cost.toFixed(4) : '-' }}
              </template>
            </el-table-column>
          </el-table>
          
          <el-empty v-if="rebalanceHistory.length === 0" description="暂无调仓历史记录"></el-empty>
        </el-card>
      </div>
    </div>

    <!-- ==================== 待执行调仓详情弹窗 ==================== -->
    <el-dialog title="待执行调仓详情" :visible.sync="pendingDetailVisible" width="600px">
      <div v-if="pendingRebalance">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="调仓类型">
            <el-tag :type="getPendingTypeTag(pendingRebalance && pendingRebalance.type)" size="small">
              {{ getPendingTypeLabel(pendingRebalance && pendingRebalance.type) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="信号日期">{{ pendingRebalance && pendingRebalance.signal_date }}</el-descriptions-item>
          <el-descriptions-item label="执行日期">{{ pendingRebalance && pendingRebalance.execute_date }}</el-descriptions-item>
          <el-descriptions-item label="缩放系数" v-if="pendingRebalance && pendingRebalance.scale_factor">
            {{ pendingRebalance.scale_factor.toFixed(4) }}
          </el-descriptions-item>
        </el-descriptions>
        
        <div style="margin-top: 15px;" v-if="pendingWeightsList.length > 0">
          <div class="section-title-small">目标权重</div>
          <el-table :data="pendingWeightsList" size="mini" stripe border max-height="250">
            <el-table-column prop="asset" label="资产" width="150"></el-table-column>
            <el-table-column prop="weight" label="目标权重" align="right">
              <template slot-scope="scope">
                {{ formatPercent(scope.row.weight) }}
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
      <span slot="footer">
        <el-button @click="pendingDetailVisible = false">关闭</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import { mapState } from 'vuex';

export default {
  name: 'Signals',
  data: function() {
    return {
      loading: false,
      volChart: null,
      expandedRows: [],
      pendingDetailVisible: false,
      volProgressColors: [
        { color: '#67C23A', percentage: 70 },
        { color: '#E6A23C', percentage: 90 },
        { color: '#F56C6C', percentage: 100 }
      ]
    };
  },
  computed: {
    ...mapState('monitor', ['signals', 'events', 'monitorState']),
    
    // ===== 波动率相关 =====
    volReset: function() {
      return (this.signals && this.signals.vol_reset) ? this.signals.vol_reset : null;
    },
    currentVolatility: function() {
      if (!this.volReset) return null;
      var v = this.volReset.current_volatility;
      if (v === undefined || v === null) return null;
      return v;
    },
    volThreshold: function() {
      if (!this.volReset) return null;
      var threshold = this.volReset.threshold;
      if (threshold !== undefined && threshold !== null) {
        return threshold > 1 ? threshold / 100 : threshold;
      }
      return null;
    },
    volStatus: function() {
      if (!this.signals || !this.volReset) return 'nodata';
      if (this.currentVolatility === null || this.volThreshold === null || this.volThreshold <= 0) {
        return 'nodata';
      }
      var status = this.volReset.status;
      if (status) return status;
      var ratio = this.currentVolatility / this.volThreshold;
      if (ratio >= 1) return 'danger';
      if (ratio >= 0.85) return 'warning';
      return 'normal';
    },
    volStatusType: function() {
      var status = this.volStatus;
      if (status === 'nodata') return 'info';
      if (status === 'danger') return 'danger';
      if (status === 'warning') return 'warning';
      return 'success';
    },
    volStatusText: function() {
      var status = this.volStatus;
      if (status === 'nodata') return '未加载';
      if (status === 'danger') return '已触发';
      if (status === 'warning') return '预警';
      return '正常';
    },
    volValueClass: function() {
      var status = this.volStatus;
      if (status === 'nodata') return 'vol-normal';
      if (status === 'danger') return 'vol-danger';
      if (status === 'warning') return 'vol-warning';
      return 'vol-normal';
    },
    volProgressPercent: function() {
      if (this.currentVolatility === null || !this.volThreshold || this.volThreshold <= 0) return 0;
      return Math.min(Math.round(this.currentVolatility / this.volThreshold * 100), 100);
    },
    distanceToTrigger: function() {
      if (!this.volReset) return null;
      if (this.volReset.distance_to_trigger !== undefined && this.volReset.distance_to_trigger !== null) {
        var dist = this.volReset.distance_to_trigger;
        return dist > 1 ? dist / 100 : dist;
      }
      if (this.currentVolatility === null || this.volThreshold === null) return null;
      return Math.max(0, this.volThreshold - this.currentVolatility);
    },
    distanceColor: function() {
      if (this.volStatus === 'nodata' || !this.volThreshold || this.volThreshold <= 0) return '#909399';
      var cv = this.currentVolatility;
      if (cv === null) return '#909399';
      var ratio = cv / this.volThreshold;
      if (ratio >= 0.9) return '#F56C6C';
      if (ratio >= 0.7) return '#E6A23C';
      return '#67C23A';
    },
    volWindows: function() {
      return (this.volReset && this.volReset.vol_windows) ? this.volReset.vol_windows : {};
    },
    volatilityHistory: function() {
      return (this.signals && this.signals.volatility_history) || [];
    },
    
    // ===== 调仓相关 =====
    lastRebalanceDate: function() {
      var signals = this.$store.state.monitor.signals;
      // 优先用顶层 last_rebalance_date
      if (signals && signals.last_rebalance_date) {
        return signals.last_rebalance_date;
      }
      // 回退到 monthly_rebalance.last_date
      if (this.monthlyRebalance && this.monthlyRebalance.last_date) {
        return this.monthlyRebalance.last_date;
      }
      // 最后从历史记录取
      if (this.rebalanceHistory.length > 0) {
        return this.rebalanceHistory[0].date;
      }
      return null;
    },
    lastRebalanceType: function() {
      if (this.rebalanceHistory.length > 0) return this.rebalanceHistory[0].type;
      return null;
    },
    pendingRebalance: function() {
      return (this.signals && this.signals.pending_rebalance) || null;
    },
    pendingAlertTitle: function() {
      if (!this.pendingRebalance) return '';
      return '待执行调仓 - ' + this.getPendingTypeLabel(this.pendingRebalance.type);
    },
    pendingAlertDesc: function() {
      if (!this.pendingRebalance) return '';
      return '执行日期: ' + this.pendingRebalance.execute_date;
    },
    pendingWeightsList: function() {
      if (!this.pendingRebalance || !this.pendingRebalance.weights) return [];
      var weights = this.pendingRebalance.weights;
      return Object.keys(weights).map(function(asset) {
        return { asset: asset, weight: weights[asset] };
      });
    },
    rebalanceHistory: function() {
      // 直接使用后端 signalStatus 中的 rebalance_history
      var signals = this.$store.state.monitor.signals;
      if (signals && signals.rebalance_history && Array.isArray(signals.rebalance_history)) {
        var self = this;
        return signals.rebalance_history.map(function(e, idx) {
          return {
            id: e.id || ('rebalance_' + idx),
            date: e.date,
            type: e.type,
            typeLabel: self.getRebalanceTypeLabel(e.type),
            description: e.description,
            trading_cost: e.trading_cost,
            scale_factor: e.scale_factor,
            old_weights: e.old_weights,
            new_weights: e.new_weights
          };
        }).slice(0, 20);
      }
      return [];
    }
  },
  created: function() {
    this.loadData();
  },
  mounted: function() {
    var self = this;
    this.$nextTick(function() {
      self.initChart();
    });
  },
  beforeDestroy: function() {
    if (this.volChart) {
      this.volChart.dispose();
    }
  },
  methods: {
    loadData: async function() {
      this.loading = true;
      try {
        // 调仓历史现在从 signalStatus 获取，不需要单独 fetchEvents
        await this.$store.dispatch('monitor/fetchSignals');
        this.updateChart();
      } catch (error) {
        this.$message.error('加载数据失败：' + error.message);
      } finally {
        this.loading = false;
      }
    },
    refreshData: async function() {
      await this.loadData();
      this.$message.success('数据已刷新');
    },
    initChart: function() {
      if (!this.$refs.volChart) return;
      this.volChart = echarts.init(this.$refs.volChart);
      this.updateChart();
      
      var self = this;
      window.addEventListener('resize', function() {
        if (self.volChart) self.volChart.resize();
      });
    },
    updateChart: function() {
      if (!this.volChart) return;
      
      var history = this.volatilityHistory;
      var dates = history.map(function(v) { return v.date; });
      var values = history.map(function(v) {
        var val = v.volatility !== undefined ? v.volatility : v.value;
        // 转为百分比
        return val > 1 ? val : (val * 100);
      });
      
      var thresholdPct = (this.volThreshold != null && !Number.isNaN(this.volThreshold))
        ? this.volThreshold * 100
        : 6;
      
      var option = {
        tooltip: {
          trigger: 'axis',
          formatter: function(params) {
            var p = params[0];
            return p.axisValue + '<br/>波动率: ' + Number(p.value).toFixed(2) + '%';
          }
        },
        grid: {
          left: '10%',
          right: '5%',
          bottom: '15%',
          top: '10%'
        },
        xAxis: {
          type: 'category',
          data: dates,
          axisLabel: { rotate: 45, fontSize: 10 }
        },
        yAxis: {
          type: 'value',
          name: '波动率(%)',
          axisLabel: { formatter: function(v) { return v.toFixed(1) + '%'; } }
        },
        series: [{
          name: '组合波动率',
          type: 'line',
          data: values,
          smooth: true,
          lineStyle: { width: 2, color: '#409EFF' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(64,158,255,0.3)' },
              { offset: 1, color: 'rgba(64,158,255,0.05)' }
            ])
          },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{
              yAxis: thresholdPct,
              lineStyle: { color: '#F56C6C', type: 'dashed', width: 2 },
              label: { formatter: '阈值 ' + thresholdPct.toFixed(1) + '%', position: 'end' }
            }]
          }
        }]
      };
      
      this.volChart.setOption(option);
    },
    formatPercent: function(val, showSign) {
      if (val === null || val === undefined) return '-';
      // 检测是否已是百分比数字（>1）
      var pct = val > 1 ? val : (val * 100);
      var formatted = pct.toFixed(2);
      if (showSign && pct > 0) return '+' + formatted + '%';
      return formatted + '%';
    },
    handleExpandChange: function(row, expandedRows) {
      this.expandedRows = expandedRows.map(function(r) { return r.id; });
    },
    getWeightsComparison: function(row) {
      var oldWeights = row.old_weights || {};
      var newWeights = row.new_weights || {};
      var assetSet = {};
      Object.keys(oldWeights).forEach(function(k) { assetSet[k] = true; });
      Object.keys(newWeights).forEach(function(k) { assetSet[k] = true; });
      var assets = Object.keys(assetSet);
      
      return assets
        .map(function(asset) {
          var before = oldWeights[asset] || 0;
          var after = newWeights[asset] || 0;
          var change = after - before;
          
          var direction = '不变';
          if (Math.abs(before) < 1e-6 && after > 1e-6) {
            direction = '新增';
          } else if (before > 1e-6 && Math.abs(after) < 1e-6) {
            direction = '清仓';
          } else if (change > 1e-6) {
            direction = '增持';
          } else if (change < -1e-6) {
            direction = '减持';
          }
          
          return { asset: asset, before: before, after: after, change: change, direction: direction };
        })
        .filter(function(item) { return Math.abs(item.before) > 1e-6 || Math.abs(item.after) > 1e-6; })
        .sort(function(a, b) { return Math.abs(b.change) - Math.abs(a.change); });
    },
    getRebalanceTypeTag: function(type) {
      var map = {
        // 新格式
        'init': 'success',
        'monthly': 'primary',
        'vol_reset': 'danger',
        'vol_reset_trigger': 'warning',
        'subjective': 'warning',
        // 旧格式兼容
        'monthly_rebalance': 'primary',
        'vol_reset_execute': 'danger',
        'subjective_rebalance': 'warning'
      };
      return map[type] || 'info';
    },
    getRebalanceTypeLabel: function(type) {
      var map = {
        // 新格式
        'init': '策略初始化',
        'monthly': '月度调仓',
        'vol_reset': '波动率重置',
        'vol_reset_trigger': '波动率重置(触发)',
        'subjective': '主观调仓',
        // 旧格式兼容
        'monthly_rebalance': '月度调仓',
        'vol_reset_execute': '波动率重置',
        'subjective_rebalance': '主观调仓'
      };
      return map[type] || type;
    },
    getPendingTypeTag: function(type) {
      var map = {
        'monthly': 'primary',
        'vol_reset': 'warning',
        'subjective': 'success'
      };
      return map[type] || 'info';
    },
    getPendingTypeLabel: function(type) {
      var map = {
        'monthly': '月度调仓',
        'vol_reset': '波动率重置',
        'subjective': '主观调仓'
      };
      return map[type] || type;
    },
    getDirectionTag: function(direction) {
      var map = {
        '新增': 'success',
        '清仓': 'danger',
        '增持': 'primary',
        '减持': 'warning',
        '不变': 'info'
      };
      return map[direction] || 'info';
    },
    getChangeClass: function(change) {
      if (change > 0) return 'number-positive';
      if (change < 0) return 'number-negative';
      return '';
    },
    viewPendingDetail: function() {
      this.pendingDetailVisible = true;
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

/* Section 通用样式 */
.section-block {
  margin-bottom: 25px;
}

.section-header {
  display: flex;
  align-items: center;
  margin-bottom: 15px;
  font-size: 16px;
  font-weight: 500;
  color: #303133;
}

.section-header i {
  margin-right: 8px;
  font-size: 18px;
  color: #409EFF;
}

/* 风险预警区 */
.alert-section {
  background: #fff;
  padding: 20px;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0,0,0,0.05);
}

.alert-item {
  margin-bottom: 10px;
}

.alert-item:last-child {
  margin-bottom: 0;
}

/* 波动率面板 */
.vol-panel {
  height: 100%;
}

.vol-display {
  text-align: center;
  padding: 20px 0;
}

.vol-value {
  font-size: 56px;
  font-weight: 600;
  line-height: 1;
}

.vol-label {
  font-size: 14px;
  color: #909399;
  margin-top: 10px;
}

.vol-normal { color: #67C23A; }
.vol-warning { color: #E6A23C; }
.vol-danger { color: #F56C6C; }

.vol-progress-wrapper {
  padding: 0 20px;
  margin: 20px 0;
}

.vol-progress-labels {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}

.vol-distance {
  text-align: center;
  padding: 15px 0;
  font-size: 14px;
  color: #606266;
  border-top: 1px solid #EBEEF5;
  border-bottom: 1px solid #EBEEF5;
}

.vol-windows {
  display: flex;
  justify-content: space-around;
  padding: 15px 10px;
}

.vol-window-item {
  text-align: center;
}

.window-label {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-bottom: 5px;
}

.window-value {
  font-size: 16px;
  font-weight: 500;
  color: #303133;
}

/* 图表卡片 */
.chart-card {
  height: 100%;
}

.chart-container {
  width: 100%;
}

/* 调仓概览 */
.rebalance-overview {
  margin-bottom: 20px;
}

.overview-card {
  display: flex;
  align-items: center;
  padding: 15px;
}

.overview-card >>> .el-card__body {
  display: flex;
  align-items: center;
  width: 100%;
}

.overview-icon {
  width: 50px;
  height: 50px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 15px;
  flex-shrink: 0;
}

.overview-icon i {
  font-size: 24px;
  color: #fff;
}

.overview-icon.primary { background: linear-gradient(135deg, #409EFF 0%, #66b1ff 100%); }
.overview-icon.success { background: linear-gradient(135deg, #67C23A 0%, #85ce61 100%); }
.overview-icon.warning { background: linear-gradient(135deg, #E6A23C 0%, #ebb563 100%); }
.overview-icon.info { background: linear-gradient(135deg, #909399 0%, #a6a9ad 100%); }

.overview-content {
  flex: 1;
}

.overview-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 5px;
}

.overview-value {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 5px;
}

.overview-sub {
  margin-top: 5px;
}

/* 历史记录卡片 */
.history-card {
  background: #fff;
}

.expand-content {
  padding: 15px 20px;
  background: #fafafa;
}

.expand-title {
  font-size: 14px;
  font-weight: 500;
  color: #606266;
  margin-bottom: 10px;
}

.section-title-small {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 10px;
}

/* 数字颜色 */
.number-positive { color: #67C23A; }
.number-negative { color: #F56C6C; }
</style>
