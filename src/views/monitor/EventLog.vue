<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">事件日志</h2>
      <div>
        <el-button type="primary" icon="el-icon-refresh" @click="refreshData" :loading="loading">
          刷新
        </el-button>
      </div>
    </div>

    <div class="page-content">
      <!-- 筛选栏 -->
      <el-card shadow="never" style="margin-bottom: 20px;">
        <el-form :inline="true" size="small">
          <el-form-item label="事件类型">
            <el-select v-model="filterType" placeholder="全部类型" clearable style="width: 150px;">
              <el-option label="全部" value=""></el-option>
              <el-option label="初始化" value="init"></el-option>
              <el-option label="月度调仓" value="monthly"></el-option>
              <el-option label="波动率重置" value="vol_reset"></el-option>
              <el-option label="主观调仓" value="subjective"></el-option>
            </el-select>
          </el-form-item>
          
          <el-form-item label="日期范围">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              value-format="yyyy-MM-dd"
              style="width: 280px;"
            ></el-date-picker>
          </el-form-item>
          
          <el-form-item>
            <el-button type="primary" icon="el-icon-search" @click="handleSearch">查询</el-button>
            <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 时间线视图 -->
      <el-card shadow="never" v-loading="loading">
        <div class="timeline-container">
          <el-timeline>
            <el-timeline-item
              v-for="(event, index) in filteredEvents"
              :key="index"
              :timestamp="event.date"
              placement="top"
              :color="getEventColor(event.type)"
              :icon="getEventIcon(event.type)"
            >
              <el-card class="event-card" @click.native="viewEventDetail(event)">
                <div class="event-header">
                  <el-tag :type="getEventTagType(event.type)" size="small">
                    {{ getEventTypeLabel(event.type) }}
                  </el-tag>
                  <span class="event-time">{{ event.time || '' }}</span>
                </div>
                <div class="event-summary">
                  {{ getEventSummary(event) }}
                </div>
                <div class="event-action">
                  <el-button type="text" size="small">
                    查看详情 <i class="el-icon-arrow-right"></i>
                  </el-button>
                </div>
              </el-card>
            </el-timeline-item>
          </el-timeline>
          
          <el-empty v-if="filteredEvents.length === 0" description="暂无事件记录"></el-empty>
          
          <!-- 加载更多 -->
          <div class="load-more" v-if="hasMore && filteredEvents.length > 0">
            <el-button type="text" @click="loadMore" :loading="loadingMore">
              {{ loadingMore ? '加载中...' : '加载更多' }}
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 事件详情弹窗 -->
    <el-dialog
      :title="'事件详情 - ' + getEventTypeLabel(currentEvent && currentEvent.type)"
      :visible.sync="detailDialogVisible"
      width="750px"
    >
      <div v-if="currentEvent">
        <!-- 基本信息 -->
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="事件类型">
            <el-tag :type="getEventTagType(currentEvent.type)" size="small">
              {{ getEventTypeLabel(currentEvent.type) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="事件日期">{{ currentEvent.date }}</el-descriptions-item>
          <el-descriptions-item label="事件ID" v-if="currentEvent.event_id">
            {{ currentEvent.event_id }}
          </el-descriptions-item>
          <el-descriptions-item label="描述" :span="2" v-if="currentEvent.description">
            {{ currentEvent.description }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- 调仓事件：显示权重对比 -->
        <div v-if="isRebalanceEvent && (currentEvent.weights_before || currentEvent.weights_after)" style="margin-top: 20px;">
          <div class="section-title">调仓前后权重对比</div>
          <el-table :data="weightsComparison" size="small" stripe border max-height="350">
            <el-table-column prop="asset" label="资产" width="150"></el-table-column>
            <el-table-column prop="before" label="调仓前" align="right">
              <template slot-scope="scope">
                {{ formatPercent(scope.row.before) }}
              </template>
            </el-table-column>
            <el-table-column prop="after" label="调仓后" align="right">
              <template slot-scope="scope">
                {{ formatPercent(scope.row.after) }}
              </template>
            </el-table-column>
            <el-table-column label="变化" align="right" width="100">
              <template slot-scope="scope">
                <span :class="getChangeClass(scope.row.change)">
                  {{ formatPercent(scope.row.change, true) }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 波动率重置事件：显示额外信息 -->
        <div v-if="currentEvent.type === 'vol_reset'" style="margin-top: 20px;">
          <div class="section-title">波动率重置信息</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="触发波动率">
              {{ formatPercent(currentEvent.trigger_volatility) }}
            </el-descriptions-item>
            <el-descriptions-item label="波动率阈值">
              {{ formatPercent(currentEvent.threshold || 0.06) }}
            </el-descriptions-item>
            <el-descriptions-item label="缩放系数">
              {{ currentEvent.scale_factor ? currentEvent.scale_factor.toFixed(4) : '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="执行日期">
              {{ currentEvent.execute_date || currentEvent.date }}
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <!-- 主观调仓事件：显示指令信息 -->
        <div v-if="currentEvent.type === 'subjective'" style="margin-top: 20px;">
          <div class="section-title">主观调仓信息</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="指令ID">
              {{ currentEvent.override_id || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="操作人">
              {{ currentEvent.operator || '系统' }}
            </el-descriptions-item>
            <el-descriptions-item label="调仓说明" :span="2">
              {{ currentEvent.override_description || currentEvent.description || '-' }}
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <!-- 初始化事件：显示初始配置 -->
        <div v-if="currentEvent.type === 'init'" style="margin-top: 20px;">
          <div class="section-title">初始配置</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="初始净值">
              {{ currentEvent.initial_nav || 100 }}
            </el-descriptions-item>
            <el-descriptions-item label="基准日期">
              {{ currentEvent.base_date || currentEvent.date }}
            </el-descriptions-item>
          </el-descriptions>
          
          <div v-if="currentEvent.initial_weights" style="margin-top: 15px;">
            <div class="section-title">初始权重</div>
            <el-table :data="initialWeightsList" size="mini" stripe border max-height="250">
              <el-table-column prop="asset" label="资产" width="150"></el-table-column>
              <el-table-column prop="weight" label="权重" align="right">
                <template slot-scope="scope">
                  {{ formatPercent(scope.row.weight) }}
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>

        <!-- 完整数据（JSON格式，可折叠） -->
        <el-collapse style="margin-top: 20px;">
          <el-collapse-item title="查看原始数据" name="raw">
            <pre class="raw-data">{{ JSON.stringify(currentEvent, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
      
      <span slot="footer">
        <el-button @click="detailDialogVisible = false">关闭</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { mapState } from 'vuex';

export default {
  name: 'EventLog',
  data() {
    return {
      loading: false,
      loadingMore: false,
      filterType: '',
      dateRange: [],
      detailDialogVisible: false,
      currentEvent: null,
      pageSize: 50,
      currentPage: 1,
      hasMore: true
    };
  },
  computed: {
    ...mapState('monitor', ['events']),
    
    filteredEvents() {
      let result = this.events || [];
      
      if (this.filterType) {
        result = result.filter(e => e.type === this.filterType);
      }
      
      if (this.dateRange && this.dateRange.length === 2) {
        result = result.filter(e => {
          const date = e.date;
          return date >= this.dateRange[0] && date <= this.dateRange[1];
        });
      }
      
      return result.slice(0, this.currentPage * this.pageSize);
    },
    
    isRebalanceEvent() {
      if (!this.currentEvent) return false;
      return ['monthly', 'vol_reset', 'subjective'].includes(this.currentEvent.type);
    },
    
    weightsComparison() {
      if (!this.currentEvent) return [];
      const before = this.currentEvent.weights_before || {};
      const after = this.currentEvent.weights_after || {};
      const assets = [...new Set([...Object.keys(before), ...Object.keys(after)])];
      return assets.map(asset => ({
        asset,
        before: before[asset] || 0,
        after: after[asset] || 0,
        change: (after[asset] || 0) - (before[asset] || 0)
      }));
    },
    
    initialWeightsList() {
      if (!this.currentEvent?.initial_weights) return [];
      return Object.entries(this.currentEvent.initial_weights).map(([asset, weight]) => ({
        asset,
        weight
      }));
    }
  },
  created() {
    this.loadData();
  },
  methods: {
    async loadData() {
      this.loading = true;
      try {
        await this.$store.dispatch('monitor/fetchEvents', {
          type: this.filterType || undefined,
          limit: 100
        });
        this.hasMore = (this.events || []).length >= this.currentPage * this.pageSize;
      } catch (error) {
        this.$message.error('加载事件日志失败：' + error.message);
      } finally {
        this.loading = false;
      }
    },
    
    async refreshData() {
      this.currentPage = 1;
      await this.loadData();
      this.$message.success('数据已刷新');
    },
    
    handleSearch() {
      this.currentPage = 1;
      this.loadData();
    },
    
    handleReset() {
      this.filterType = '';
      this.dateRange = [];
      this.currentPage = 1;
      this.loadData();
    },
    
    async loadMore() {
      this.loadingMore = true;
      this.currentPage++;
      // 模拟加载延迟
      await new Promise(resolve => setTimeout(resolve, 300));
      this.hasMore = (this.events || []).length >= this.currentPage * this.pageSize;
      this.loadingMore = false;
    },
    
    viewEventDetail(event) {
      this.currentEvent = event;
      this.detailDialogVisible = true;
    },
    
    getEventColor(type) {
      const map = {
        'init': '#409eff',      // 蓝色
        'monthly': '#67c23a',   // 绿色
        'vol_reset': '#e6a23c', // 橙色
        'subjective': '#9b59b6' // 紫色
      };
      return map[type] || '#909399';
    },
    
    getEventIcon(type) {
      const map = {
        'init': 'el-icon-star-on',
        'monthly': 'el-icon-date',
        'vol_reset': 'el-icon-warning',
        'subjective': 'el-icon-edit'
      };
      return map[type] || 'el-icon-info';
    },
    
    getEventTagType(type) {
      const map = {
        'init': '',
        'monthly': 'success',
        'vol_reset': 'warning',
        'subjective': ''
      };
      return map[type] || 'info';
    },
    
    getEventTypeLabel(type) {
      const map = {
        'init': '初始化',
        'monthly': '月度调仓',
        'vol_reset': '波动率重置',
        'subjective': '主观调仓'
      };
      return map[type] || type || '未知';
    },
    
    getEventSummary(event) {
      switch (event.type) {
        case 'init':
          return `系统初始化，初始净值 ${event.initial_nav || 100}`;
        case 'monthly':
          return `月度调仓执行${event.description ? '：' + event.description : ''}`;
        case 'vol_reset':
          return `波动率触发重置，触发值 ${this.formatPercent(event.trigger_volatility)}，缩放系数 ${event.scale_factor?.toFixed(4) || '-'}`;
        case 'subjective':
          return `主观调仓${event.override_description ? '：' + event.override_description : ''}`;
        default:
          return event.description || '事件记录';
      }
    },
    
    formatPercent(val, showSign = false) {
      if (val === null || val === undefined) return '-';
      const pct = (val * 100).toFixed(2);
      if (showSign && val > 0) return '+' + pct + '%';
      return pct + '%';
    },
    
    getChangeClass(change) {
      if (change > 0.0001) return 'number-positive';
      if (change < -0.0001) return 'number-negative';
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

.timeline-container {
  min-height: 400px;
}

.event-card {
  cursor: pointer;
  transition: box-shadow 0.2s;
}

.event-card:hover {
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.event-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.event-time {
  font-size: 12px;
  color: #909399;
}

.event-summary {
  font-size: 14px;
  color: #606266;
  line-height: 1.5;
}

.event-action {
  margin-top: 10px;
  text-align: right;
}

.load-more {
  text-align: center;
  padding: 20px 0;
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

.raw-data {
  background: #f5f7fa;
  padding: 15px;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
  max-height: 300px;
}
</style>
