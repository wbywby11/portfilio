<template>
  <div class="asset-detail">
    <el-descriptions :column="2" border v-if="asset">
      <el-descriptions-item label="资产代码" :span="1">
        <el-tag>{{ asset.code }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="资产名称" :span="1">
        {{ asset.name }}
      </el-descriptions-item>
      
      <el-descriptions-item label="资产分类" :span="1">
        <el-tag :type="getAssetTypeTagType(asset.asset_type)">
          {{ asset.asset_type }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="交易所" :span="1">
        {{ asset.exchange || '-' }}
      </el-descriptions-item>
      
      <el-descriptions-item label="状态" :span="1">
        <el-tag :type="asset.is_active ? 'success' : 'info'">
          {{ asset.is_active ? '启用' : '禁用' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="创建时间" :span="1">
        {{ formatDate(asset.created_at) }}
      </el-descriptions-item>
      
      <el-descriptions-item label="更新时间" :span="1">
        {{ formatDate(asset.updated_at) }}
      </el-descriptions-item>
      <el-descriptions-item label="资产描述" :span="2">
        {{ asset.description || '-' }}
      </el-descriptions-item>
    </el-descriptions>

    <!-- 期货类特殊参数 -->
    <el-divider content-position="left" v-if="asset && asset.asset_type === '期货类'">
      <span style="font-size: 16px; font-weight: 600;">期货展期参数</span>
    </el-divider>
    <el-descriptions :column="2" border v-if="asset && asset.asset_type === '期货类'">
      <el-descriptions-item label="展期天数 k" :span="1">
        <span>{{ asset.rollover_days !== null && asset.rollover_days !== undefined ? asset.rollover_days : '-' }}</span>
        <el-tooltip content="展期天数，用于计算期货合约展期时的加权平均收益率" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-descriptions-item>
      <el-descriptions-item label="持仓量阈值 th" :span="1">
        <span>{{ asset.rollover_threshold !== null && asset.rollover_threshold !== undefined ? asset.rollover_threshold : '-' }}</span>
        <el-tooltip content="持仓量阈值，用于判断主力合约切换的临界值" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-descriptions-item>
      <el-descriptions-item label="观察窗口起点 p" :span="1">
        <span>{{ asset.rollover_window_p !== null && asset.rollover_window_p !== undefined ? asset.rollover_window_p : '-' }}</span>
        <el-tooltip content="观察窗口起点参数 p，用于计算展期时的观察窗口（LTD-p）" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-descriptions-item>
      <el-descriptions-item label="观察窗口终点 q" :span="1">
        <span>{{ asset.rollover_window_q !== null && asset.rollover_window_q !== undefined ? asset.rollover_window_q : '-' }}</span>
        <el-tooltip content="观察窗口终点参数 q，用于计算展期时的观察窗口（LTD-q）" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-descriptions-item>
    </el-descriptions>

    <!-- 现货类特殊参数 -->
    <el-divider content-position="left" v-if="asset && asset.asset_type === '现货类'">
      <span style="font-size: 16px; font-weight: 600;">现货替代参数</span>
    </el-divider>
    <el-descriptions :column="2" border v-if="asset && asset.asset_type === '现货类'">
      <el-descriptions-item label="替代标的代码" :span="1">
        <el-tag v-if="asset.substitute_code" type="info">{{ asset.substitute_code }}</el-tag>
        <span v-else>-</span>
        <el-tooltip content="上市前使用的替代标的代码，用于计算ETF上市前的历史收益" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-descriptions-item>
      <el-descriptions-item label="切换日期" :span="1">
        <span>{{ asset.switch_date ? formatSwitchDate(asset.switch_date) : '-' }}</span>
        <el-tooltip content="从替代标的切换到实际ETF的日期，格式为YYYYMMDD" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-descriptions-item>
    </el-descriptions>

    <!-- 加载中状态 -->
    <div v-if="loading" v-loading="loading" element-loading-text="加载中..." class="loading-container"></div>

    <!-- 错误状态 -->
    <el-empty v-if="!loading && !asset" description="资产信息加载失败"></el-empty>
  </div>
</template>

<script>
import { getAssetDetail } from '@/api/asset';

export default {
  name: 'AssetDetail',
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    assetId: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      asset: null,
      loading: false
    };
  },
  created() {
    if (this.assetId) {
      this.loadAsset();
    }
  },
  watch: {
    assetId(newVal) {
      if (newVal) {
        this.loadAsset();
      } else {
        this.asset = null;
      }
    }
  },
  methods: {
    async loadAsset() {
      if (!this.assetId) return;
      
      this.loading = true;
      try {
        const response = await getAssetDetail(this.assetId);
        // 处理响应数据，后端返回格式为 { code: 200, message: "success", data: {...} }
        if (response && response.data) {
          this.asset = response.data;
        } else if (response && !response.data && response.id) {
          // 兼容直接返回资产对象的情况
          this.asset = response;
        } else {
          this.asset = null;
        }
      } catch (error) {
        console.error('加载资产详情失败:', error);
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || error.message || '未知错误';
        this.$message.error('加载资产详情失败：' + errorMsg);
        this.asset = null;
      } finally {
        this.loading = false;
      }
    },
    getAssetTypeTagType(assetType) {
      const typeMap = {
        '指数类': 'primary',
        '现货类': 'success',
        '期货类': 'warning',
        '股票': 'info',
        '债券': '',
        '商品': 'warning',
        '货币': 'success',
        '基金': 'primary',
        '指数': 'primary',
        '数字货币': 'danger'
      };
      return typeMap[assetType] || '';
    },
    formatDate(dateStr) {
      if (!dateStr) return '-';
      // 如果是 YYYY-MM-DD 格式，直接返回
      if (typeof dateStr === 'string' && dateStr.length === 10) {
        return dateStr;
      }
      // 尝试解析其他格式
      try {
        const date = new Date(dateStr);
        return date.toISOString().split('T')[0];
      } catch (e) {
        return dateStr;
      }
    },
    formatSwitchDate(dateStr) {
      if (!dateStr) return '-';
      // 如果是 YYYYMMDD 格式，转换为 YYYY-MM-DD
      if (typeof dateStr === 'string' && dateStr.length === 8 && /^\d+$/.test(dateStr)) {
        return `${dateStr.substring(0, 4)}-${dateStr.substring(4, 6)}-${dateStr.substring(6, 8)}`;
      }
      return dateStr;
    }
  }
};
</script>

<style scoped>
.asset-detail {
  padding: 20px;
}

.loading-container {
  min-height: 200px;
  position: relative;
}

.el-divider {
  margin: 20px 0;
}
</style>
