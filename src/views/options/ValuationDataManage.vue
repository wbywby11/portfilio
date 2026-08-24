<template>
  <div class="valuation-data-page">
    <!-- 顶部标题 -->
    <div class="page-header">
      <h2 class="page-title">估值数据</h2>
      <p class="page-desc">查看系统行情数据状态，选择标的资产查看详细行情</p>
    </div>

    <!-- 标的选择区 -->
    <div class="selector-card">
      <div class="selector-row">
        <span class="selector-label">选择标的</span>
        <el-select
          v-model="selectedCode"
          placeholder="选择标的资产"
          filterable
          size="medium"
          style="width: 280px;"
          @change="handleCodeChange"
        >
          <el-option
            v-for="asset in assets"
            :key="asset.asset_code"
            :value="asset.asset_code"
            :label="asset.asset_code"
          >
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>{{ asset.asset_code }}</span>
              <span style="color: #909399; font-size: 12px;">
                {{ asset.count }} 条 | {{ asset.latest_date }}
              </span>
            </div>
          </el-option>
        </el-select>
        <el-button
          icon="el-icon-refresh"
          size="small"
          @click="loadAssets"
          :loading="assetsLoading"
          style="margin-left: 8px;"
        >
          刷新
        </el-button>
      </div>
    </div>

    <!-- 数据概览卡片 -->
    <div v-if="selectedAsset" class="overview-cards">
      <el-row :gutter="16">
        <el-col :span="6">
          <div class="stat-card">
            <div class="stat-label">数据条数</div>
            <div class="stat-value">{{ selectedAsset.count.toLocaleString() }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-card">
            <div class="stat-label">数据起始</div>
            <div class="stat-value stat-value-sm">{{ selectedAsset.earliest_date || '-' }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-card">
            <div class="stat-label">数据截止</div>
            <div class="stat-value stat-value-sm">{{ selectedAsset.latest_date || '-' }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat-card">
            <div class="stat-label">最新收盘</div>
            <div class="stat-value stat-value-lg">{{ selectedAsset.latest_close != null ? selectedAsset.latest_close.toFixed(4) : '-' }}</div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 数据状态标签 -->
    <div v-if="selectedAsset" class="data-status">
      <el-tag :type="selectedAsset.count > 100 ? 'success' : (selectedAsset.count > 0 ? 'warning' : 'danger')" effect="dark" size="small">
        {{ selectedAsset.count > 100 ? '数据齐全' : (selectedAsset.count > 0 ? '数据不足' : '无数据') }}
      </el-tag>
      <span v-if="selectedAsset.latest_date" style="margin-left: 12px; color: #909399; font-size: 13px;">
        最近更新: {{ selectedAsset.latest_date }}
      </span>
    </div>

    <!-- 行情表格 -->
    <div v-if="selectedCode" class="table-area">
      <vxe-table
        :data="priceData"
        :loading="pricesLoading"
        border
        stripe
        height="420"
        :scroll-y="{enabled: true, gt: 0}"
        show-overflow="title"
      >
        <vxe-column field="date" title="日期" width="120" sortable />
        <vxe-column field="close" title="收盘" min-width="120" align="right">
          <template #default="{ row }">
            <span style="font-weight: 600;">{{ row.close != null ? row.close.toFixed(4) : '-' }}</span>
          </template>
        </vxe-column>
        <vxe-column field="open" title="开盘" min-width="120" align="right">
          <template #default="{ row }">{{ row.open != null ? row.open.toFixed(4) : '-' }}</template>
        </vxe-column>
        <vxe-column field="high" title="最高" min-width="120" align="right">
          <template #default="{ row }">{{ row.high != null ? row.high.toFixed(4) : '-' }}</template>
        </vxe-column>
        <vxe-column field="low" title="最低" min-width="120" align="right">
          <template #default="{ row }">{{ row.low != null ? row.low.toFixed(4) : '-' }}</template>
        </vxe-column>
        <vxe-column field="volume" title="成交量" min-width="130" align="right">
          <template #default="{ row }">{{ row.volume != null ? row.volume.toLocaleString() : '-' }}</template>
        </vxe-column>
        <vxe-column field="amount" title="成交额" min-width="140" align="right">
          <template #default="{ row }">{{ row.amount != null ? row.amount.toLocaleString() : '-' }}</template>
        </vxe-column>
      </vxe-table>
    </div>

    <!-- 空状态 -->
    <div v-if="!selectedCode && !assetsLoading" class="empty-state">
      <i class="el-icon-data-board empty-icon"></i>
      <div class="empty-title">请选择标的资产</div>
      <div class="empty-hint">从上方下拉框选择一个标的，查看其行情数据</div>
    </div>

    <!-- 加载中标签无数据 -->
    <div v-if="selectedCode && !pricesLoading && priceData.length === 0" class="empty-state">
      <i class="el-icon-warning-outline empty-icon"></i>
      <div class="empty-title">暂无行情数据</div>
      <div class="empty-hint">{{ selectedCode }} 当前没有可用的行情数据</div>
    </div>
  </div>
</template>

<script>
import { getValuationDataAssets, getValuationDataPrices } from '@/api/optionPricing';

export default {
  name: 'ValuationDataManage',
  data() {
    return {
      assets: [],
      assetsLoading: false,
      selectedCode: '',
      selectedAsset: null,
      priceData: [],
      pricesLoading: false,
    };
  },
  created() {
    this.loadAssets();
  },
  methods: {
    async loadAssets() {
      this.assetsLoading = true;
      try {
        const res = await getValuationDataAssets();
        this.assets = (res.data && res.data.data) || res.data || [];
        // 如果已选中标的，更新其概览信息
        if (this.selectedCode) {
          this.selectedAsset = this.assets.find(a => a.asset_code === this.selectedCode) || null;
        }
      } catch (e) {
        this.$message.error('加载标的列表失败');
      } finally {
        this.assetsLoading = false;
      }
    },
    async handleCodeChange(code) {
      this.selectedAsset = this.assets.find(a => a.asset_code === code) || null;
      if (code) {
        await this.loadPrices(code);
      } else {
        this.priceData = [];
      }
    },
    async loadPrices(code) {
      this.pricesLoading = true;
      try {
        const res = await getValuationDataPrices(code, { limit: 200 });
        this.priceData = (res.data && res.data.data) || res.data || [];
      } catch (e) {
        this.$message.error('加载行情数据失败');
        this.priceData = [];
      } finally {
        this.pricesLoading = false;
      }
    },
  }
};
</script>

<style scoped>
.valuation-data-page {
  padding: 0;
}
.page-header {
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}
.page-desc {
  margin: 4px 0 0;
  color: #909399;
  font-size: 13px;
}
.selector-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.selector-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.selector-label {
  font-size: 14px;
  font-weight: 500;
  color: #606266;
  white-space: nowrap;
}
.overview-cards {
  margin-bottom: 16px;
}
.stat-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 16px;
  text-align: center;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.stat-value {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}
.stat-value-sm {
  font-size: 15px;
}
.stat-value-lg {
  font-size: 24px;
  color: #409eff;
}
.data-status {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
}
.table-area {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 0;
  color: #909399;
}
.empty-icon {
  font-size: 48px;
  color: #dcdfe6;
  margin-bottom: 12px;
}
.empty-title {
  font-size: 15px;
  color: #606266;
  margin-bottom: 4px;
}
.empty-hint {
  font-size: 13px;
}
</style>
