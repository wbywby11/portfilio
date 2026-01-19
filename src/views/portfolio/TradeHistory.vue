<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">调仓历史</h2>
      <div>
        <el-button @click="$router.back()">返回</el-button>
        <el-button type="primary" icon="el-icon-download" @click="exportHistory">导出历史</el-button>
      </div>
    </div>

    <div class="page-content">
      <!-- 组合信息 -->
      <el-descriptions :column="4" border size="small" style="margin-bottom: 20px;">
        <el-descriptions-item label="组合名称">{{ portfolio.name }}</el-descriptions-item>
        <el-descriptions-item label="当前市值">{{ formatNumber(portfolio.totalValue) }} 元</el-descriptions-item>
        <el-descriptions-item label="调仓次数">{{ tradeHistory.length }} 次</el-descriptions-item>
        <el-descriptions-item label="累计换手率">{{ totalTurnover.toFixed(2) }}%</el-descriptions-item>
      </el-descriptions>

      <!-- 筛选条件 -->
      <el-card shadow="never" style="margin-bottom: 20px;">
        <el-form :inline="true" size="small">
          <el-form-item label="调仓类型">
            <el-select v-model="filterType" placeholder="全部" clearable style="width: 150px;">
              <el-option label="初始建仓" value="initial"></el-option>
              <el-option label="定期再平衡" value="periodic"></el-option>
              <el-option label="阈值触发" value="threshold"></el-option>
              <el-option label="模型更新" value="model"></el-option>
              <el-option label="手动调仓" value="manual"></el-option>
            </el-select>
          </el-form-item>
          
          <el-form-item label="时间范围">
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
          
          <el-form-item label="涉及资产">
            <el-input v-model="filterAsset" placeholder="资产代码/名称" clearable style="width: 180px;"></el-input>
          </el-form-item>
          
          <el-form-item>
            <el-button type="primary" icon="el-icon-search" @click="handleSearch">查询</el-button>
            <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 调仓历史时间线 -->
      <el-timeline>
        <el-timeline-item
          v-for="(record, index) in filteredHistory"
          :key="index"
          :timestamp="record.timestamp"
          placement="top"
          :type="getRecordType(record.type)"
          :icon="getRecordIcon(record.type)"
        >
          <el-card class="trade-record-card">
            <div slot="header" class="trade-record-header">
              <div class="record-title">
                <span class="record-type-tag">
                  <el-tag :type="getRecordType(record.type)" size="small">
                    {{ getRecordTypeLabel(record.type) }}
                  </el-tag>
                </span>
                <span class="record-id">#{{ record.id }}</span>
                <span v-if="record.modelId" class="record-model">
                  <i class="el-icon-link"></i> 关联模型: {{ record.modelName }}
                </span>
              </div>
              <div class="record-actions">
                <el-button type="text" size="small" @click="viewDetail(record)">查看详情</el-button>
                <el-button type="text" size="small" @click="viewSnapshot(record)">持仓快照</el-button>
              </div>
            </div>

            <!-- 调仓概览 -->
            <div class="trade-overview">
              <el-row :gutter="20">
                <el-col :span="16">
                  <div class="overview-item">
                    <span class="label">调仓原因：</span>
                    <span class="value">{{ record.reason }}</span>
                  </div>
                  <div class="overview-item" v-if="record.description">
                    <span class="label">详细说明：</span>
                    <span class="value">{{ record.description }}</span>
                  </div>
                  <div class="overview-item">
                    <span class="label">操作人员：</span>
                    <span class="value">{{ record.operator }}</span>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="overview-stats">
                    <div class="stat-item">
                      <div class="stat-label">换手率</div>
                      <div class="stat-value">{{ record.turnover }}%</div>
                    </div>
                    <div class="stat-item">
                      <div class="stat-label">交易成本</div>
                      <div class="stat-value">￥{{ formatNumber(record.totalCost) }}</div>
                    </div>
                  </div>
                </el-col>
              </el-row>
            </div>

            <!-- 交易明细摘要 -->
            <el-divider></el-divider>
            <div class="trade-summary">
              <el-tag size="small" type="success" v-if="record.buyCount > 0">
                <i class="el-icon-top"></i> 买入 {{ record.buyCount }} 笔
              </el-tag>
              <el-tag size="small" type="danger" v-if="record.sellCount > 0" style="margin-left: 10px;">
                <i class="el-icon-bottom"></i> 卖出 {{ record.sellCount }} 笔
              </el-tag>
              <span style="margin-left: 15px; color: #909399; font-size: 13px;">
                总交易额：￥{{ formatNumber(record.totalAmount) }}
              </span>
            </div>

            <!-- 审批信息 -->
            <div v-if="record.approval" class="approval-info">
              <el-divider></el-divider>
              <div class="approval-item">
                <span class="label">审批状态：</span>
                <el-tag :type="getApprovalType(record.approval.status)" size="small">
                  {{ getApprovalLabel(record.approval.status) }}
                </el-tag>
              </div>
              <div class="approval-item" v-if="record.approval.approver">
                <span class="label">审批人：</span>
                <span>{{ record.approval.approver }}</span>
              </div>
              <div class="approval-item" v-if="record.approval.comment">
                <span class="label">审批意见：</span>
                <span>{{ record.approval.comment }}</span>
              </div>
            </div>
          </el-card>
        </el-timeline-item>
      </el-timeline>

      <el-empty v-if="filteredHistory.length === 0" description="暂无调仓记录"></el-empty>
    </div>

    <!-- 调仓详情对话框 -->
    <el-dialog
      title="调仓详情"
      :visible.sync="detailDialogVisible"
      width="80%"
      top="5vh"
    >
      <div v-if="currentRecord">
        <!-- 基本信息 -->
        <el-descriptions title="调仓信息" :column="2" border size="small">
          <el-descriptions-item label="调仓时间">{{ currentRecord.timestamp }}</el-descriptions-item>
          <el-descriptions-item label="调仓类型">
            <el-tag :type="getRecordType(currentRecord.type)" size="small">
              {{ getRecordTypeLabel(currentRecord.type) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="操作人员">{{ currentRecord.operator }}</el-descriptions-item>
          <el-descriptions-item label="换手率">{{ currentRecord.turnover }}%</el-descriptions-item>
          <el-descriptions-item label="调仓前总资产">￥{{ formatNumber(currentRecord.beforeTotal) }}</el-descriptions-item>
          <el-descriptions-item label="调仓后总资产">￥{{ formatNumber(currentRecord.afterTotal) }}</el-descriptions-item>
        </el-descriptions>

        <!-- 交易明细 -->
        <h3 style="margin: 20px 0 10px;">交易明细</h3>
        <el-table :data="currentRecord.trades" border size="small">
          <el-table-column prop="assetCode" label="资产代码" width="120"></el-table-column>
          <el-table-column prop="assetName" label="资产名称" width="150"></el-table-column>
          <el-table-column prop="direction" label="买卖方向" width="100" align="center">
            <template slot-scope="scope">
              <el-tag :type="scope.row.direction === 'buy' ? 'success' : 'danger'" size="mini">
                {{ scope.row.direction === 'buy' ? '买入' : '卖出' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="交易数量" width="120" align="right">
            <template slot-scope="scope">
              {{ formatNumber(scope.row.quantity) }}
            </template>
          </el-table-column>
          <el-table-column prop="price" label="交易价格" width="120" align="right">
            <template slot-scope="scope">
              {{ scope.row.price.toFixed(4) }}
            </template>
          </el-table-column>
          <el-table-column prop="amount" label="交易金额" width="150" align="right">
            <template slot-scope="scope">
              {{ formatNumber(scope.row.amount) }}
            </template>
          </el-table-column>
          <el-table-column prop="cost" label="交易成本" width="120" align="right">
            <template slot-scope="scope">
              {{ formatNumber(scope.row.cost) }}
            </template>
          </el-table-column>
          <el-table-column label="权重变化" align="center">
            <template slot-scope="scope">
              <span>{{ scope.row.weightBefore }}% → {{ scope.row.weightAfter }}%</span>
            </template>
          </el-table-column>
        </el-table>

        <!-- 调仓原因 -->
        <h3 style="margin: 20px 0 10px;">调仓原因</h3>
        <el-input
          type="textarea"
          :rows="3"
          :value="currentRecord.description"
          readonly
        ></el-input>
      </div>
      
      <span slot="footer">
        <el-button @click="detailDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="downloadDetail">下载报告</el-button>
      </span>
    </el-dialog>

    <!-- 持仓快照对话框 -->
    <el-dialog
      title="持仓快照"
      :visible.sync="snapshotDialogVisible"
      width="70%"
    >
      <div v-if="currentSnapshot">
        <div class="snapshot-info" style="margin-bottom: 15px;">
          <el-tag type="info" size="small">日期: {{ currentSnapshot.date }}</el-tag>
          <el-tag type="warning" size="small" style="margin-left: 10px;" v-if="currentSnapshot.rebalance_reason">
            调整原因: {{ currentSnapshot.rebalance_reason }}
          </el-tag>
        </div>
        <el-tabs v-model="snapshotTab">
          <el-tab-pane label="调仓后持仓" name="after">
            <el-table :data="currentSnapshot.after" border size="small">
              <el-table-column prop="asset_code" label="资产代码" width="120"></el-table-column>
              <el-table-column prop="asset_name" label="资产名称" width="150"></el-table-column>
              <el-table-column prop="shares" label="持仓数量" align="right">
                <template slot-scope="scope">
                  {{ scope.row.shares ? scope.row.shares.toFixed(2) : '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="price" label="成本价" align="right">
                <template slot-scope="scope">
                  {{ scope.row.price ? scope.row.price.toFixed(4) : '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="market_value" label="市值" align="right">
                <template slot-scope="scope">
                  {{ formatNumber(scope.row.market_value) }}
                </template>
              </el-table-column>
              <el-table-column prop="weight" label="权重" align="right">
                <template slot-scope="scope">
                  {{ scope.row.weight ? (scope.row.weight * 100).toFixed(2) + '%' : '-' }}
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          
          <el-tab-pane label="调仓前持仓" name="before">
            <el-table :data="currentSnapshot.before" border size="small">
              <el-table-column prop="asset_code" label="资产代码" width="120"></el-table-column>
              <el-table-column prop="asset_name" label="资产名称" width="150"></el-table-column>
              <el-table-column prop="shares" label="持仓数量" align="right">
                <template slot-scope="scope">
                  {{ scope.row.shares ? scope.row.shares.toFixed(2) : '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="price" label="成本价" align="right">
                <template slot-scope="scope">
                  {{ scope.row.price ? scope.row.price.toFixed(4) : '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="market_value" label="市值" align="right">
                <template slot-scope="scope">
                  {{ formatNumber(scope.row.market_value) }}
                </template>
              </el-table-column>
              <el-table-column prop="weight" label="权重" align="right">
                <template slot-scope="scope">
                  {{ scope.row.weight ? (scope.row.weight * 100).toFixed(2) + '%' : '-' }}
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
      
      <span slot="footer">
        <el-button @click="snapshotDialogVisible = false">关闭</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import dayjs from 'dayjs';

export default {
  name: 'TradeHistory',
  data() {
    return {
      portfolio: {},
      tradeHistory: [],
      filterType: '',
      dateRange: [],
      filterAsset: '',
      detailDialogVisible: false,
      snapshotDialogVisible: false,
      currentRecord: null,
      currentSnapshot: null,
      snapshotTab: 'after'
    };
  },
  computed: {
    filteredHistory() {
      let result = this.tradeHistory;
      
      if (this.filterType) {
        result = result.filter(r => r.type === this.filterType);
      }
      
      if (this.dateRange && this.dateRange.length === 2) {
        result = result.filter(r => {
          const date = r.timestamp.split(' ')[0];
          return date >= this.dateRange[0] && date <= this.dateRange[1];
        });
      }
      
      if (this.filterAsset) {
        result = result.filter(r => {
          return r.trades.some(t => 
            t.assetCode.includes(this.filterAsset) || 
            t.assetName.includes(this.filterAsset)
          );
        });
      }
      
      return result;
    },
    totalTurnover() {
      return this.tradeHistory.reduce((sum, r) => sum + r.turnover, 0);
    }
  },
  created() {
    this.loadData();
  },
  methods: {
    loadData() {
      const id = this.$route.params.id;
      this.portfolio = this.$store.getters['portfolio/getPortfolioById'](id) || {};
      
      // 模拟调仓历史数据
      this.tradeHistory = this.generateMockHistory();
    },
    generateMockHistory() {
      // 生成模拟数据
      return [
        {
          id: 'T001',
          timestamp: dayjs().subtract(30, 'day').format('YYYY-MM-DD HH:mm:ss'),
          type: 'initial',
          reason: '初始建仓',
          description: '根据策略模型建立初始持仓',
          operator: '系统管理员',
          modelId: 'M001',
          modelName: '均值方差模型',
          turnover: 100,
          totalAmount: 100000,
          totalCost: 100,
          buyCount: 5,
          sellCount: 0,
          beforeTotal: 0,
          afterTotal: 100000,
          trades: [
            { assetCode: '000300.SH', assetName: '沪深300', direction: 'buy', quantity: 1000, price: 40.5, amount: 40500, cost: 40.5, weightBefore: 0, weightAfter: 40.5 },
            { assetCode: '000905.SH', assetName: '中证500', direction: 'buy', quantity: 800, price: 30.2, amount: 24160, cost: 24.16, weightBefore: 0, weightAfter: 24.16 }
          ]
        },
        {
          id: 'T002',
          timestamp: dayjs().subtract(7, 'day').format('YYYY-MM-DD HH:mm:ss'),
          type: 'periodic',
          reason: '定期再平衡',
          description: '按照每月定期再平衡策略执行',
          operator: '系统自动',
          turnover: 15.6,
          totalAmount: 15600,
          totalCost: 15.6,
          buyCount: 2,
          sellCount: 1,
          beforeTotal: 105000,
          afterTotal: 104984.4,
          trades: [
            { assetCode: '000300.SH', assetName: '沪深300', direction: 'sell', quantity: 200, price: 42.1, amount: 8420, cost: 8.42, weightBefore: 40.5, weightAfter: 38.2 },
            { assetCode: '000905.SH', assetName: '中证500', direction: 'buy', quantity: 100, price: 31.5, amount: 3150, cost: 3.15, weightBefore: 24.16, weightAfter: 26.8 }
          ],
          approval: {
            status: 'approved',
            approver: '投资经理',
            comment: '同意执行'
          }
        }
      ];
    },
    handleSearch() {
      // 搜索逻辑已在 computed 中实现
    },
    handleReset() {
      this.filterType = '';
      this.dateRange = [];
      this.filterAsset = '';
    },
    viewDetail(record) {
      this.currentRecord = record;
      this.detailDialogVisible = true;
    },
    viewSnapshot(record) {
      // 生成快照数据
      this.currentSnapshot = {
        date: record.timestamp.split(' ')[0],
        rebalance_reason: record.reason,
        before: [
          { asset_code: '000300.SH', asset_name: '沪深300', shares: 1000, price: 40.5, market_value: 42100, weight: 0.405 },
          { asset_code: '000905.SH', asset_name: '中证500', shares: 800, price: 30.2, market_value: 25200, weight: 0.2416 }
        ],
        after: [
          { asset_code: '000300.SH', asset_name: '沪深300', shares: 800, price: 42.1, market_value: 33680, weight: 0.382 },
          { asset_code: '000905.SH', asset_name: '中证500', shares: 900, price: 31.2, market_value: 28080, weight: 0.268 }
        ]
      };
      this.snapshotDialogVisible = true;
      this.snapshotTab = 'after';
    },
    exportHistory() {
      this.$message.success('导出功能开发中...');
    },
    downloadDetail() {
      this.$message.success('下载功能开发中...');
    },
    formatNumber(num) {
      return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num || 0);
    },
    getRecordType(type) {
      const map = {
        initial: 'primary',
        periodic: 'success',
        threshold: 'warning',
        model: 'info',
        manual: ''
      };
      return map[type] || '';
    },
    getRecordIcon(type) {
      const map = {
        initial: 'el-icon-star-on',
        periodic: 'el-icon-time',
        threshold: 'el-icon-warning',
        model: 'el-icon-data-analysis',
        manual: 'el-icon-edit'
      };
      return map[type] || 'el-icon-circle-check';
    },
    getRecordTypeLabel(type) {
      const map = {
        initial: '初始建仓',
        periodic: '定期再平衡',
        threshold: '阈值触发',
        model: '模型更新',
        manual: '手动调仓'
      };
      return map[type] || type;
    },
    getApprovalType(status) {
      const map = {
        pending: 'warning',
        approved: 'success',
        rejected: 'danger'
      };
      return map[status] || 'info';
    },
    getApprovalLabel(status) {
      const map = {
        pending: '待审批',
        approved: '已批准',
        rejected: '已拒绝'
      };
      return map[status] || status;
    }
  }
};
</script>

<style scoped>
.trade-record-card {
  margin-bottom: 0;
}

.trade-record-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.record-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.record-id {
  font-weight: 600;
  color: #303133;
}

.record-model {
  color: #909399;
  font-size: 13px;
}

.trade-overview {
  padding: 15px 0;
}

.overview-item {
  margin-bottom: 10px;
  font-size: 14px;
}

.overview-item .label {
  color: #909399;
  margin-right: 8px;
}

.overview-item .value {
  color: #303133;
}

.overview-stats {
  display: flex;
  justify-content: space-around;
  text-align: center;
}

.stat-item {
  flex: 1;
}

.stat-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 5px;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.trade-summary {
  padding: 10px 0;
}

.approval-info {
  padding-top: 10px;
}

.approval-item {
  margin-bottom: 8px;
  font-size: 13px;
}

.approval-item .label {
  color: #909399;
  margin-right: 8px;
}
</style>
