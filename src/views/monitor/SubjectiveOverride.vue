<template>
  <div class="page-container">
    <div class="page-content" v-loading="loading">
      <!-- 新增调仓按钮 -->
      <div class="override-toolbar">
        <el-button type="primary" icon="el-icon-plus" @click="showAddForm">
          新增主观调仓
        </el-button>
      </div>
      <!-- 新增主观调仓表单 -->
      <el-card class="info-card" v-if="formVisible">
        <div slot="header" class="card-header">
          <span>新增主观调仓指令</span>
          <el-button type="text" @click="formVisible = false">
            <i class="el-icon-close"></i>
          </el-button>
        </div>
        
        <el-form ref="form" :model="form" :rules="rules" label-width="120px" size="small">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="执行日期" prop="execute_date">
                <el-date-picker
                  v-model="form.execute_date"
                  type="date"
                  placeholder="选择执行日期"
                  value-format="yyyy-MM-dd"
                  :picker-options="datePickerOptions"
                  style="width: 100%;"
                ></el-date-picker>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="权重合计">
                <div class="weight-stats">
                  <div class="weight-stat-item" :class="weightSumClass">
                    <span class="stat-label">总权重</span>
                    <span class="stat-value">{{ weightSumPercent.toFixed(2) }}%</span>
                  </div>
                  <div class="weight-stat-item" :class="leverageClass">
                    <span class="stat-label">等效杠杆</span>
                    <span class="stat-value">{{ equivalentLeverage.toFixed(2) }}x</span>
                  </div>
                </div>
                <div class="weight-tip" v-if="weightSumPercent > 100 && weightSumPercent <= maxLeverage * 100">
                  <i class="el-icon-warning"></i> 当前为杠杆配置
                </div>
              </el-form-item>
            </el-col>
          </el-row>
          
          <el-form-item label="目标权重" prop="weights">
            <div class="weights-grid">
              <div v-for="asset in assetList" :key="asset.key" class="weight-item">
                <div class="weight-label">
                  <span>{{ asset.name }}</span>
                  <span class="weight-cap-hint">
                    上限: {{ getWeightCap(asset.key) }}%
                  </span>
                  <span class="current-weight" v-if="getCurrentWeight(asset.key) !== undefined">
                    当前: {{ (getCurrentWeight(asset.key) * 100).toFixed(2) }}%
                  </span>
                </div>
                <div class="weight-input-wrapper">
                  <el-input-number
                    v-model="form.weights[asset.key]"
                    :min="0"
                    :max="getWeightCap(asset.key)"
                    :step="0.5"
                    :precision="2"
                    controls-position="right"
                    size="small"
                    style="width: calc(100% - 24px);"
                  ></el-input-number>
                  <span class="percent-sign">%</span>
                </div>
              </div>
            </div>
          </el-form-item>
          
          <el-form-item label="调仓说明" prop="description">
            <el-input
              type="textarea"
              v-model="form.description"
              :rows="3"
              placeholder="请输入调仓原因或备注说明"
              maxlength="500"
              show-word-limit
            ></el-input>
          </el-form-item>
          
          <el-form-item>
            <el-button type="primary" @click="handleSubmit" :loading="submitting">
              {{ submitting ? '提交中...' : '提交指令' }}
            </el-button>
            <el-button @click="resetForm">重置</el-button>
            <el-button @click="formVisible = false">取消</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 待执行指令列表 -->
      <el-card class="info-card">
        <div slot="header" class="card-header">
          <span>待执行指令</span>
          <el-tag type="warning" size="small">{{ pendingOverrides.length }} 条</el-tag>
        </div>
        
        <el-table :data="pendingOverrides" size="small" stripe border>
          <el-table-column prop="override_id" label="指令ID" width="120"></el-table-column>
          <el-table-column prop="execute_date" label="执行日期" width="120" align="center"></el-table-column>
          <el-table-column prop="description" label="说明" show-overflow-tooltip></el-table-column>
          <el-table-column label="总权重" width="100" align="right">
            <template slot-scope="scope">
              {{ formatTotalWeight(scope.row.weights) }}
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90" align="center">
            <template slot-scope="scope">
              <el-tag :type="getStatusTagType(scope.row.status)" size="mini">
                {{ getStatusLabel(scope.row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center">
            <template slot-scope="scope">
              <el-button
                v-if="scope.row.status === 'pending'"
                type="text"
                size="small"
                style="color: #f56c6c;"
                @click="handleCancel(scope.row)"
              >
                取消
              </el-button>
              <el-button type="text" size="small" @click="viewDetail(scope.row)">
                详情
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        
        <el-empty v-if="pendingOverrides.length === 0" description="暂无待执行指令"></el-empty>
      </el-card>

      <!-- 历史指令记录 -->
      <el-card class="info-card">
        <div slot="header" class="card-header">
          <span>历史指令记录</span>
          <el-select v-model="historyStatusFilter" placeholder="状态筛选" size="mini" clearable style="width: 120px;">
            <el-option label="全部" value=""></el-option>
            <el-option label="已执行" value="executed"></el-option>
            <el-option label="已取消" value="cancelled"></el-option>
          </el-select>
        </div>
        
        <el-table :data="filteredHistoryOverrides" size="small" stripe border max-height="400">
          <el-table-column prop="override_id" label="指令ID" width="120"></el-table-column>
          <el-table-column prop="execute_date" label="执行日期" width="120" align="center"></el-table-column>
          <el-table-column prop="description" label="说明" show-overflow-tooltip></el-table-column>
          <el-table-column label="总权重" width="100" align="right">
            <template slot-scope="scope">
              {{ formatTotalWeight(scope.row.weights) }}
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90" align="center">
            <template slot-scope="scope">
              <el-tag :type="getStatusTagType(scope.row.status)" size="mini">
                {{ getStatusLabel(scope.row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template slot-scope="scope">
              <el-button type="text" size="small" @click="viewDetail(scope.row)">
                详情
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        
        <el-empty v-if="filteredHistoryOverrides.length === 0" description="暂无历史记录"></el-empty>
      </el-card>
    </div>

    <!-- 指令详情弹窗 -->
    <el-dialog title="指令详情" :visible.sync="detailDialogVisible" width="600px">
      <div v-if="currentOverride">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="指令ID">{{ currentOverride.override_id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusTagType(currentOverride.status)" size="small">
              {{ getStatusLabel(currentOverride.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="执行日期">{{ currentOverride.execute_date }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ currentOverride.created_at }}</el-descriptions-item>
          <el-descriptions-item label="说明" :span="2">{{ currentOverride.description || '-' }}</el-descriptions-item>
        </el-descriptions>
        
        <div style="margin-top: 20px;">
          <div class="section-title">权重对比</div>
          <el-table :data="currentOverrideWeightsList" size="mini" stripe border max-height="300">
            <el-table-column prop="asset" label="资产" width="120"></el-table-column>
            <el-table-column label="当前权重" align="right" width="100">
              <template slot-scope="scope">
                {{ (scope.row.currentWeight * 100).toFixed(2) }}%
              </template>
            </el-table-column>
            <el-table-column label="目标权重" align="right" width="100">
              <template slot-scope="scope">
                {{ (scope.row.weight * 100).toFixed(2) }}%
              </template>
            </el-table-column>
            <el-table-column label="变动" align="right" width="120">
              <template slot-scope="scope">
                <span :class="getChangeClass(scope.row.change)">
                  {{ formatChange(scope.row.change) }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>
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
  name: 'SubjectiveOverride',
  data() {
    const validateWeights = (rule, value, callback) => {
      // 百分比形式，sum 是百分数（如 100 表示 100%）
      const sum = Object.values(value).reduce((a, b) => a + (b || 0), 0);
      const maxLeveragePercent = 4.0 * 100;  // MAX_LEVERAGE * 100 = 400%
      if (sum > maxLeveragePercent) {
        callback(new Error('总权重不能超过 ' + maxLeveragePercent + '%（最大杠杆 4.0x）'));
      } else {
        callback();
      }
    };
    
    return {
      loading: false,
      submitting: false,
      formVisible: false,
      detailDialogVisible: false,
      historyStatusFilter: '',
      currentOverride: null,
      form: {
        execute_date: '',
        weights: {},
        description: ''
      },
      rules: {
        execute_date: [
          { required: true, message: '请选择执行日期', trigger: 'change' }
        ],
        weights: [
          { validator: validateWeights, trigger: 'change' }
        ]
      },
      datePickerOptions: {
        // 允许选择任何日期，与原始 Streamlit 行为一致
      },
      // 权重上限配置（来自 config.py WEIGHT_CAPS，转为百分比形式）
      weightCaps: {
        '沪深300': 10,
        '创业板指': 10,
        '红利低波': 10,
        '恒生科技': 10,
        '标普500': 15,
        '德国DAX': 10,
        '中国10年国债': 60,
        '中国2年国债': 90,
        '布伦特原油': 10,
        '黄金': 10,
        '铁矿石': 10,
        '中国有色金属': 10
      },
      maxLeverage: 4.0,  // MAX_LEVERAGE
      assetList: [
        { key: '沪深300', name: '沪深300' },
        { key: '创业板指', name: '创业板指' },
        { key: '红利低波', name: '红利低波' },
        { key: '恒生科技', name: '恒生科技' },
        { key: '标普500', name: '标普500' },
        { key: '德国DAX', name: '德国DAX' },
        { key: '中国10年国债', name: '中国10年国债' },
        { key: '中国2年国债', name: '中国2年国债' },
        { key: '布伦特原油', name: '布伦特原油' },
        { key: '黄金', name: '黄金' },
        { key: '铁矿石', name: '铁矿石' },
        { key: '中国有色金属', name: '中国有色金属' }
      ]
    };
  },
  computed: {
    ...mapState('monitor', ['subjectiveOverrides', 'monitorState']),
    
    currentWeights() {
      // 使用 Vue 2 兼容写法，避免可选链操作符
      return (this.monitorState && this.monitorState.target_weights) || {};
    },
    
    // 百分比形式的总权重（如 120 表示 120%）
    weightSumPercent() {
      return Object.values(this.form.weights).reduce((sum, w) => sum + (w || 0), 0);
    },
    
    // 等效杠杆
    equivalentLeverage() {
      return this.weightSumPercent / 100;
    },
    
    weightSumClass() {
      const sum = this.weightSumPercent;
      if (sum >= 99 && sum <= 101) return 'weight-sum-valid';
      if (sum > 101 && sum <= this.maxLeverage * 100) return 'weight-sum-warning';
      if (sum > this.maxLeverage * 100) return 'weight-sum-invalid';
      return 'weight-sum-warning';
    },
    
    leverageClass() {
      const leverage = this.equivalentLeverage;
      if (leverage >= 0.99 && leverage <= 1.01) return 'weight-sum-valid';
      if (leverage > 1.01 && leverage <= this.maxLeverage) return 'weight-sum-warning';
      if (leverage > this.maxLeverage) return 'weight-sum-invalid';
      return 'weight-sum-warning';
    },
    
    pendingOverrides() {
      if (!this.subjectiveOverrides) return [];
      return this.subjectiveOverrides.filter(o => o.status === 'pending');
    },
    
    historyOverrides() {
      if (!this.subjectiveOverrides) return [];
      return this.subjectiveOverrides.filter(o => o.status !== 'pending');
    },
    
    filteredHistoryOverrides() {
      if (!this.historyStatusFilter) return this.historyOverrides;
      return this.historyOverrides.filter(o => o.status === this.historyStatusFilter);
    },
    
    currentOverrideWeightsList() {
      // 使用 Vue 2 兼容写法
      if (!this.currentOverride || !this.currentOverride.weights) return [];
      return Object.entries(this.currentOverride.weights).map(([asset, weight]) => {
        const currentWeight = this.currentWeights[asset] || 0;
        const change = weight - currentWeight;
        return {
          asset,
          weight,
          currentWeight,
          change
        };
      });
    }
  },
  created() {
    this.loadData();
    this.initFormWeights();
  },
  methods: {
    async loadData() {
      this.loading = true;
      try {
        await Promise.all([
          this.$store.dispatch('monitor/fetchSubjectiveOverrides', {}),
          this.$store.dispatch('monitor/fetchMonitorState')
        ]);
      } catch (error) {
        this.$message.error('加载数据失败：' + error.message);
      } finally {
        this.loading = false;
      }
    },
    
    initFormWeights() {
      // 初始化为百分比形式（当前权重 * 100）
      const weights = {};
      this.assetList.forEach(asset => {
        const currentWeight = this.currentWeights[asset.key] || 0;
        weights[asset.key] = Math.round(currentWeight * 100 * 100) / 100;  // 保留2位小数
      });
      this.form.weights = weights;
    },
    
    getWeightCap(assetKey) {
      return this.weightCaps[assetKey] || 15;  // 默认 15%
    },
    
    getCurrentWeight(assetKey) {
      return this.currentWeights[assetKey];
    },
    
    getChangeClass(change) {
      if (change > 0.0001) return 'change-increase';
      if (change < -0.0001) return 'change-decrease';
      return 'change-none';
    },
    
    formatChange(change) {
      const percent = (change * 100).toFixed(2);
      if (change > 0.0001) return '+' + percent + '% 增持';
      if (change < -0.0001) return percent + '% 减持';
      return '不变';
    },
    
    showAddForm() {
      this.initFormWeights();
      this.form.execute_date = '';
      this.form.description = '';
      this.formVisible = true;
    },
    
    resetForm() {
      this.initFormWeights();
      this.form.execute_date = '';
      this.form.description = '';
      if (this.$refs.form) {
        this.$refs.form.clearValidate();
      }
    },
    
    async handleSubmit() {
      try {
        await this.$refs.form.validate();
      } catch {
        this.$message.warning('请检查表单填写');
        return;
      }
      
      this.submitting = true;
      try {
        // 提交时将百分比转换为小数（如 8 -> 0.08）
        const weightsAsDecimal = {};
        Object.entries(this.form.weights).forEach(([asset, percent]) => {
          weightsAsDecimal[asset] = (percent || 0) / 100;
        });
        
        await this.$store.dispatch('monitor/addSubjectiveOverrideAction', {
          weights: weightsAsDecimal,
          execute_date: this.form.execute_date,
          description: this.form.description
        });
        this.$message.success('主观调仓指令已添加');
        this.formVisible = false;
        this.resetForm();
      } catch (error) {
        // 使用 Vue 2 兼容写法
        const detail = (error.response && error.response.data && error.response.data.detail) || error.message;
        this.$message.error('添加失败：' + detail);
      } finally {
        this.submitting = false;
      }
    },
    
    handleCancel(row) {
      this.$confirm(`确定要取消指令 "${row.override_id}" 吗？`, '确认取消', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('monitor/cancelSubjectiveOverrideAction', {
            overrideId: row.override_id
          });
          this.$message.success('指令已取消');
        } catch (error) {
          // 使用 Vue 2 兼容写法
          const detail = (error.response && error.response.data && error.response.data.detail) || error.message;
          this.$message.error('取消失败：' + detail);
        }
      }).catch(() => {});
    },
    
    viewDetail(row) {
      this.currentOverride = row;
      this.detailDialogVisible = true;
    },
    
    getStatusTagType(status) {
      const map = {
        'pending': 'warning',
        'executed': 'success',
        'cancelled': 'info'
      };
      return map[status] || '';
    },
    
    getStatusLabel(status) {
      const map = {
        'pending': '待执行',
        'executed': '已执行',
        'cancelled': '已取消'
      };
      return map[status] || status;
    },
    
    formatTotalWeight(weights) {
      if (!weights) return '-';
      const sum = Object.values(weights).reduce((a, b) => a + (b || 0), 0);
      return (sum * 100).toFixed(2) + '%';
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

.override-toolbar {
  margin-bottom: 16px;
  text-align: right;
}

.page-content {
  background: #f5f7fa;
  padding: 20px;
  border-radius: 4px;
}

.info-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-title {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 10px;
}

.weights-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 15px;
}

.weight-item {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
}

.weight-label {
  display: flex;
  flex-direction: column;
  margin-bottom: 8px;
  font-size: 13px;
  color: #303133;
}

.current-weight {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.weight-sum {
  font-size: 16px;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 4px;
}

.weight-sum-valid {
  color: #67c23a;
  background: #f0f9eb;
}

.weight-sum-warning {
  color: #e6a23c;
  background: #fdf6ec;
}

.weight-sum-invalid {
  color: #f56c6c;
  background: #fef0f0;
}

.weight-stats {
  display: flex;
  gap: 20px;
}

.weight-stat-item {
  padding: 8px 16px;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 100px;
}

.stat-label {
  font-size: 12px;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 18px;
  font-weight: 600;
}

.weight-tip {
  margin-top: 8px;
  font-size: 12px;
  color: #e6a23c;
}

.weight-input-wrapper {
  display: flex;
  align-items: center;
}

.percent-sign {
  margin-left: 6px;
  font-size: 14px;
  color: #606266;
  font-weight: 500;
}

.weight-cap-hint {
  font-size: 11px;
  color: #c0c4cc;
  margin-left: 4px;
}

.change-increase {
  color: #67c23a;
  font-weight: 500;
}

.change-decrease {
  color: #f56c6c;
  font-weight: 500;
}

.change-none {
  color: #909399;
}
</style>
