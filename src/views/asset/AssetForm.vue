<template>
  <div :class="{'page-container': !isDialog}">
    <div v-if="!isDialog" class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑资产' : '新增资产' }}</h2>
    </div>

    <div :class="{'page-content': !isDialog}">
      <el-form :model="form" :rules="rules" ref="form" label-width="120px" style="max-width: 800px; margin: 0 auto;">
        <el-divider content-position="left">基本信息</el-divider>
        
        <el-form-item label="资产代码" prop="code">
          <el-input 
            v-model="form.code" 
            placeholder="请输入资产代码，如：000300.SH"
            :disabled="isEdit"
          ></el-input>
          <span v-if="isEdit" style="color: #909399; font-size: 12px;">编辑模式下不可修改资产代码</span>
        </el-form-item>

        <el-form-item label="资产名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入资产名称"></el-input>
        </el-form-item>

        <el-form-item label="工具形态" prop="instrument_type">
          <el-select v-model="form.instrument_type" placeholder="请选择工具形态" style="width: 100%">
            <el-option
              v-for="item in instrumentTypes"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            >
              <span>{{ item.label }}</span>
              <span style="color: #909399; font-size: 12px; margin-left: 8px;">{{ item.hint }}</span>
            </el-option>
          </el-select>
          <div style="color: #909399; font-size: 12px; line-height: 1.4; margin-top: 4px;">
            决定 TR 计算方式：指数型（直接收盘价）/ 现货型（上市前替代）/ 期货型（主力展期）
          </div>
        </el-form-item>

        <el-form-item label="资产大类" prop="asset_class">
          <el-select v-model="form.asset_class" placeholder="请选择资产大类" style="width: 100%">
            <el-option
              v-for="item in assetClasses"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            ></el-option>
          </el-select>
          <div style="color: #909399; font-size: 12px; line-height: 1.4; margin-top: 4px;">
            用于资产过滤、报告分组、风控分类
          </div>
        </el-form-item>

        <el-form-item label="证券细分" prop="security_type">
          <el-select
            v-model="form.security_type"
            placeholder="可选，用于细粒度筛选"
            clearable
            style="width: 100%"
          >
            <el-option
              v-for="item in securityTypes"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            ></el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="交易所" prop="exchange">
          <el-input v-model="form.exchange" placeholder="请输入交易所名称（可选）"></el-input>
        </el-form-item>

        <el-form-item label="描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="请输入资产描述（可选）"
          ></el-input>
        </el-form-item>

        <!-- 展期信息：仅当选择期货型时显示 -->
        <template v-if="form.instrument_type === '期货型'">
          <el-divider content-position="left">展期信息（可选）</el-divider>

          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="展期天数 k" prop="rollover_days">
                <el-input-number 
                  v-model="form.rollover_days" 
                  :min="0" 
                  :max="365"
                  :step="1"
                  style="width: 100%"
                ></el-input-number>
                <span style="margin-left: 8px; color: #909399; font-size: 12px;">天（范围：0-365）</span>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="持仓量阈值 th" prop="rollover_threshold">
                <el-input-number 
                  v-model="form.rollover_threshold" 
                  :min="0" 
                  :max="1000000"
                  :step="1000"
                  style="width: 100%"
                ></el-input-number>
                <span style="margin-left: 8px; color: #909399; font-size: 12px;">（范围：≥0，步长：1000）</span>
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="观察窗口起点 p" prop="rollover_window_p">
                <el-input-number 
                  v-model="form.rollover_window_p" 
                  :min="0" 
                  :max="365"
                  :step="1"
                  style="width: 100%"
                ></el-input-number>
                <span style="margin-left: 8px; color: #909399; font-size: 12px;">天（范围：0-365）</span>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="观察窗口终点 q" prop="rollover_window_q">
                <el-input-number 
                  v-model="form.rollover_window_q" 
                  :min="0" 
                  :max="365"
                  :step="1"
                  style="width: 100%"
                ></el-input-number>
                <span style="margin-left: 8px; color: #909399; font-size: 12px;">天（范围：0-365）</span>
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <!-- 替代信息：仅当选择现货型时显示 -->
        <template v-if="form.instrument_type === '现货型'">
          <el-divider content-position="left">替代信息（可选）</el-divider>

          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="替代标的代码" prop="substitute_code">
                <el-input v-model="form.substitute_code" placeholder="请输入替代标的代码"></el-input>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="切换日期" prop="switch_date">
                <el-date-picker
                  v-model="form.switch_date"
                  type="date"
                  placeholder="选择日期"
                  format="yyyy-MM-dd"
                  value-format="yyyyMMdd"
                  style="width: 100%"
                ></el-date-picker>
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-form-item>
          <el-button type="primary" @click="handleSubmit" :loading="submitting">
            {{ submitting ? '提交中...' : '提 交' }}
          </el-button>
          <el-button @click="handleCancel">取 消</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script>
import { mapState } from 'vuex';

// 旧 → 新 兼容映射（迁移完成后删除）
function _legacyToInstrument(old) {
  if (!old) return '';
  if (old === '指数类' || old === '指数型') return '指数型';
  if (old === '现货类' || old === '现货型') return '现货型';
  if (old === '期货类' || old === '期货型') return '期货型';
  // 基础类型映射（股票/债券/基金按现货型，其他按指数型）
  if (['股票', '债券', '基金', '货币'].includes(old)) return '现货型';
  return '指数型';
}
function _legacyToClass(old, name) {
  if (!old && !name) return '';
  const n = (name || '') + ' ' + (old || '');
  if (n.includes('债')) return '固收';
  if (['黄金', '白银', '原油', '螺纹', '铁矿', '有色', '豆粕', '棉花', '沪'].some(k => n.includes(k))) return '商品';
  if (n.includes('货币')) return '货币';
  if (['BTC', 'ETH', '加密'].some(k => n.includes(k))) return '另类';
  if (old === '债券') return '固收';
  if (old === '商品') return '商品';
  if (old === '货币') return '货币';
  if (old === '数字货币') return '另类';
  return '权益';
}

export default {
  name: 'AssetForm',
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    assetCode: {
      type: String,
      default: ''
    },
    /** 弹窗内「从多资产导入新建」时预填代码/名称（与 assetCode 互斥） */
    presetCreate: {
      type: Object,
      default: null
    }
  },
  data() {
    return {
      form: {
        code: '',
        name: '',
        instrument_type: '',
        asset_class: '',
        security_type: '',
        exchange: '',
        description: '',
        rollover_days: null,
        rollover_threshold: null,
        rollover_window_p: null,
        rollover_window_q: null,
        substitute_code: '',
        switch_date: ''
      },
      currentAssetId: null,  // 保存当前编辑的资产 ID
      rules: {
        code: [{ required: true, message: '请输入资产代码', trigger: 'blur' }],
        name: [{ required: true, message: '请输入资产名称', trigger: 'blur' }],
        instrument_type: [{ required: true, message: '请选择工具形态', trigger: 'change' }],
        asset_class: [{ required: true, message: '请选择资产大类', trigger: 'change' }]
      },
      submitting: false,
      isEdit: false
    };
  },
  computed: {
    ...mapState('asset', ['instrumentTypes', 'assetClasses', 'securityTypes'])
  },
  created() {
    if (this.isDialog) {
      if (this.assetCode) {
        this.isEdit = true;
        this.loadAsset(this.assetCode);
      } else if (this.presetCreate && (this.presetCreate.code || this.presetCreate.name)) {
        this.isEdit = false;
        this.currentAssetId = null;
        this.form.code = this.presetCreate.code || '';
        this.form.name = this.presetCreate.name || '';
      }
    } else if (this.$route.params.id) {
      this.isEdit = true;
      this.loadAsset(this.$route.params.id);
    }
  },
  watch: {
    assetCode(newVal) {
      if (this.isDialog && newVal) {
        this.isEdit = true;
        this.loadAsset(newVal);
      } else {
        this.resetForm();
      }
    },
    // 监听工具形态变化，根据类型清空对应字段
    'form.instrument_type'(newVal) {
      if (newVal !== '期货型') {
        // 不是期货型，清空展期相关字段
        this.form.rollover_days = null;
        this.form.rollover_threshold = null;
        this.form.rollover_window_p = null;
        this.form.rollover_window_q = null;
      }
      if (newVal !== '现货型') {
        // 不是现货型，清空替代相关字段
        this.form.substitute_code = '';
        this.form.switch_date = '';
      }
    }
  },
  methods: {
    resetForm() {
      this.isEdit = false;
      this.currentAssetId = null;
      this.form = {
        code: '',
        name: '',
        instrument_type: '',
        asset_class: '',
        security_type: '',
        exchange: '',
        description: '',
        rollover_days: null,
        rollover_threshold: null,
        rollover_window_p: null,
        rollover_window_q: null,
        substitute_code: '',
        switch_date: ''
      };
      if (this.$refs.form) {
        this.$refs.form.resetFields();
      }
    },
    async loadAsset(code) {
      const assetCode = code || (this.isDialog ? this.assetCode : this.$route.params.id);
      
      // 先尝试从 Store 中获取
      let asset = this.$store.getters['asset/getAssetByCode'](assetCode);
      
      // 如果 Store 中没有，则加载列表
      if (!asset) {
        try {
          await this.$store.dispatch('asset/fetchAssetList', {});
          asset = this.$store.getters['asset/getAssetByCode'](assetCode);
        } catch (error) {
          console.error('加载资产数据失败:', error);
          this.$message.error('加载资产数据失败');
          return;
        }
      }
      
      if (asset) {
        this.currentAssetId = asset.id;  // 保存 ID
        this.form = {
          code: asset.code,
          name: asset.name,
          // 新字段（优先） + 旧字段兼容（迁移后 asset_type 会移除）
          instrument_type: asset.instrument_type || _legacyToInstrument(asset.asset_type),
          asset_class: asset.asset_class || _legacyToClass(asset.asset_type, asset.name),
          security_type: asset.security_type || '',
          exchange: asset.exchange || '',
          description: asset.description || '',
          rollover_days: asset.rollover_days,
          rollover_threshold: asset.rollover_threshold,
          rollover_window_p: asset.rollover_window_p,
          rollover_window_q: asset.rollover_window_q,
          substitute_code: asset.substitute_code || '',
          switch_date: asset.switch_date || ''
        };
      } else {
        this.$message.error('找不到资产信息');
        if (!this.isDialog) {
          this.$router.push({ name: 'AssetList' });
        }
      }
    },
    handleSubmit() {
      this.$refs.form.validate(async (valid) => {
        if (valid) {
          this.submitting = true;
          try {
            if (this.isEdit) {
              // 检查后端是否支持更新接口
              try {
                await this.$store.dispatch('asset/updateAsset', {
                  assetId: this.currentAssetId,  // 使用保存的 ID
                  data: this.form
                });
                this.$message.success('更新成功');
                if (this.isDialog) {
                  this.$emit('success');
                } else {
                  this.$router.push({ name: 'AssetList' });
                }
              } catch (error) {
                // 如果是 404 错误，说明后端暂不支持更新
                if (error.response && error.response.status === 404) {
                  this.$confirm(
                    '后端暂未实现资产更新接口，是否需要：<br/>'
                    + '1. 联系后端开发人员实现 PUT /api/v1/assets/{id} 接口<br/>'
                    + '2. 或者删除旧资产后重新创建',
                    '接口未实现',
                    {
                      dangerouslyUseHTMLString: true,
                      confirmButtonText: '知道了',
                      showCancelButton: false,
                      type: 'warning'
                    }
                  );
                } else {
                  throw error;
                }
              }
            } else {
              // 调用创建接口
              await this.$store.dispatch('asset/addAsset', this.form);
              this.$message.success('添加成功');
              if (this.isDialog) {
                this.$emit('success');
              } else {
                this.$router.push({ name: 'AssetList' });
              }
            }
          } catch (error) {
            const errorMsg = error.response?.data?.detail || error.message || '请检查网络连接';
            this.$message.error('操作失败：' + errorMsg);
          } finally {
            this.submitting = false;
          }
        }
      });
    },
    handleCancel() {
      if (this.isDialog) {
        this.$emit('close');
      } else {
        this.$router.back();
      }
    }
  }
};
</script>
