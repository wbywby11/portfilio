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

        <el-form-item label="资产分类" prop="asset_type">
          <el-select v-model="form.asset_type" placeholder="请选择资产分类">
            <el-option
              v-for="item in assetCategories"
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

        <el-divider content-position="left">展期与替代信息（可选）</el-divider>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="展期天数 k" prop="rollover_days">
              <el-input-number v-model="form.rollover_days" :min="0" style="width: 100%"></el-input-number>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="持仓量阈值 th" prop="rollover_threshold">
              <el-input-number v-model="form.rollover_threshold" :min="0" style="width: 100%"></el-input-number>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="观察窗口起点 p" prop="rollover_window_p">
              <el-input-number v-model="form.rollover_window_p" :min="0" style="width: 100%"></el-input-number>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="观察窗口终点 q" prop="rollover_window_q">
              <el-input-number v-model="form.rollover_window_q" :min="0" style="width: 100%"></el-input-number>
            </el-form-item>
          </el-col>
        </el-row>

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
        asset_type: '',
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
        asset_type: [{ required: true, message: '请选择资产分类', trigger: 'change' }]
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
          code: asset.code,
          name: asset.name,
          asset_type: asset.asset_type,
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
