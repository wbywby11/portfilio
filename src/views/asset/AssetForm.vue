<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑资产' : '新增资产' }}</h2>
    </div>

    <div class="page-content">
      <el-form :model="form" :rules="rules" ref="form" label-width="120px" style="max-width: 800px;">
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

        <el-form-item label="资产分类" prop="category">
          <el-select v-model="form.category" placeholder="请选择资产分类">
            <el-option
              v-for="item in assetCategories"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            ></el-option>
          </el-select>
        </el-form-item>

        <el-divider content-position="left">风险收益特征</el-divider>

        <el-form-item label="预期收益率" prop="expectedReturn">
          <el-input-number
            v-model="form.expectedReturn"
            :min="-1"
            :max="2"
            :step="0.01"
            :precision="4"
          ></el-input-number>
          <span style="margin-left: 10px; color: #909399;">年化收益率（小数形式，如0.08表示8%）</span>
        </el-form-item>

        <el-form-item label="波动率" prop="volatility">
          <el-input-number
            v-model="form.volatility"
            :min="0"
            :max="2"
            :step="0.01"
            :precision="4"
          ></el-input-number>
          <span style="margin-left: 10px; color: #909399;">年化波动率（小数形式）</span>
        </el-form-item>

        <el-form-item label="数据源" prop="dataSource">
          <el-select v-model="form.dataSource" placeholder="请选择数据源">
            <el-option label="手动录入" value="MANUAL"></el-option>
            <el-option label="Wind" value="WIND"></el-option>
            <el-option label="通达信" value="TDX"></el-option>
            <el-option label="东方财富" value="EASTMONEY"></el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="请输入资产描述（可选）"
          ></el-input>
        </el-form-item>

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

export default {
  name: 'AssetForm',
  data() {
    return {
      form: {
        code: '',
        name: '',
        category: '',
        expectedReturn: 0.08,
        volatility: 0.15,
        dataSource: 'MANUAL',
        description: ''
      },
      currentAssetId: null,  // 保存当前编辑的资产 ID
      rules: {
        code: [{ required: true, message: '请输入资产代码', trigger: 'blur' }],
        name: [{ required: true, message: '请输入资产名称', trigger: 'blur' }],
        category: [{ required: true, message: '请选择资产分类', trigger: 'change' }]
      },
      submitting: false,
      isEdit: false
    };
  },
  computed: {
    ...mapState('asset', ['assetCategories'])
  },
  created() {
    if (this.$route.params.id) {
      this.isEdit = true;
      this.loadAsset();
    }
  },
  methods: {
    async loadAsset() {
      const assetCode = this.$route.params.id;
      
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
          code: asset.asset_code,
          name: asset.asset_name,
          category: asset.asset_type,
          expectedReturn: asset.expected_return,
          volatility: asset.volatility,
          dataSource: asset.data_source || 'MANUAL',
          description: asset.description || ''
        };
      } else {
        this.$message.error('找不到资产信息');
        this.$router.push('/asset/list');
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
                this.$router.push('/asset/list');
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
              this.$router.push('/asset/list');
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
      this.$router.back();
    }
  }
};
</script>
