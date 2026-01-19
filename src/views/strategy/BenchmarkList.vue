<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">业绩基准管理</h2>
      <div>
        <el-button type="primary" icon="el-icon-plus" @click="handleCreate">
          新增基准
        </el-button>
      </div>
    </div>

    <div class="page-content">
      <!-- 搜索栏 -->
      <el-form :inline="true" :model="searchForm" class="search-form">
        <el-form-item label="基准代码">
          <el-input v-model="searchForm.code" placeholder="请输入基准代码" clearable></el-input>
        </el-form-item>
        <el-form-item label="基准名称">
          <el-input v-model="searchForm.name" placeholder="请输入基准名称" clearable></el-input>
        </el-form-item>
        <el-form-item label="基准类型">
          <el-select v-model="searchForm.benchmark_type" placeholder="请选择基准类型" clearable>
            <el-option label="单一基准" value="单一基准"></el-option>
            <el-option label="复合基准" value="复合基准"></el-option>
            <el-option label="绝对基准" value="绝对基准"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="el-icon-search" @click="handleSearch">查询</el-button>
          <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- 基准表格 -->
      <el-table
        :data="tableData"
        v-loading="loading"
        style="width: 100%"
        stripe
      >
        <el-table-column prop="code" label="基准代码" width="150"></el-table-column>
        <el-table-column prop="name" label="基准名称" width="200"></el-table-column>
        <el-table-column prop="benchmark_type" label="基准类型" width="100">
          <template slot-scope="scope">
            <el-tag size="small">{{ scope.row.benchmark_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" show-overflow-tooltip></el-table-column>
        <el-table-column prop="is_active" label="状态" width="100">
          <template slot-scope="scope">
            <el-tag :type="scope.row.is_active ? 'success' : 'info'" size="small">
              {{ scope.row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160">
          <template slot-scope="scope">
            {{ formatDate(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="small" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button type="text" size="small" @click="handleView(scope.row)">查看</el-button>
            <el-button type="text" size="small" @click="handleDelete(scope.row)" style="color: #f56c6c;">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <el-pagination
        @size-change="handleSizeChange"
        @current-change="handleCurrentChange"
        :current-page="pagination.current"
        :page-sizes="[10, 20, 50, 100]"
        :page-size="pagination.pageSize"
        layout="total, sizes, prev, pager, next, jumper"
        :total="pagination.total"
        style="margin-top: 20px; text-align: right;"
      ></el-pagination>
    </div>

    <!-- 基准对话框 -->
    <el-dialog
      :title="dialogTitle"
      :visible.sync="dialogVisible"
      width="600px"
      :before-close="handleDialogClose"
    >
      <el-form
        ref="form"
        :model="form"
        :rules="rules"
        label-width="120px"
      >
        <el-form-item label="基准代码" prop="code">
          <el-input
            v-model="form.code"
            placeholder="请输入基准代码，如B001"
            :disabled="isEdit"
          ></el-input>
        </el-form-item>

        <el-form-item label="基准名称" prop="name">
          <el-input
            v-model="form.name"
            placeholder="请输入基准名称"
          ></el-input>
        </el-form-item>

        <el-form-item label="基准类型" prop="benchmark_type">
          <el-select v-model="form.benchmark_type" placeholder="请选择基准类型" style="width: 100%;">
            <el-option label="单一基准" value="单一基准"></el-option>
            <el-option label="复合基准" value="复合基准"></el-option>
            <el-option label="绝对基准" value="绝对基准"></el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            type="textarea"
            v-model="form.description"
            :rows="3"
            placeholder="请输入基准描述（可选）"
            maxlength="200"
            show-word-limit
          ></el-input>
        </el-form-item>

        <el-form-item label="是否启用" prop="is_active">
          <el-switch
            v-model="form.is_active"
            active-text="启用"
            inactive-text="禁用"
          ></el-switch>
        </el-form-item>

        <el-form-item label="基准成分" prop="components">
          <div class="components-container">
            <el-button size="mini" type="primary" icon="el-icon-plus" @click="addComponent" v-if="showAddComponentButton">添加成分</el-button>
            
            <!-- 绝对基准：输入单一数值 -->
            <div v-if="form.benchmark_type === '绝对基准'" class="absolute-benchmark-input">
              <el-input-number
                v-model="absoluteValue"
                :min="0"
                :max="1"
                :step="0.01"
                :precision="4"
                placeholder="请输入基准数值"
                style="width: 200px;"
              ></el-input-number>
              <p class="help-text">请输入绝对基准数值（如年化收益率）</p>
            </div>
            
            <!-- 单一基准：单选资产 -->
            <div v-else-if="form.benchmark_type === '单一基准'" class="single-benchmark-selector">
              <el-select
                v-model="singleAssetCode"
                placeholder="请选择基准资产"
                style="width: 100%;"
                filterable
              >
                <el-option
                  v-for="asset in assetOptions"
                  :key="asset.code"
                  :label="`${asset.code} - ${asset.name || '未知资产'}`"
                  :value="asset.code"
                ></el-option>
              </el-select>
              <p class="help-text">请选择作为基准的单一资产</p>
            </div>
            
            <!-- 复合基准：多选资产及权重 -->
            <div v-else-if="form.benchmark_type === '复合基准'" class="composite-benchmark-editor">
              <vxe-table
                border
                resizable
                show-overflow
                keep-source
                ref="xTable"
                size="small"
                :data="form.components"
                :edit-config="{trigger: 'click', mode: 'cell'}"
                style="margin-top: 10px;"
              >
                <vxe-column type="seq" width="60" title="序号"></vxe-column>
                <vxe-column field="asset_code" title="资产" :edit-render="{autofocus: '.el-input__inner'}" min-width="180">
                  <template #edit="scope">
                    <el-select
                      v-model="scope.row.asset_code"
                      placeholder="请选择资产"
                      style="width: 100%;"
                      filterable
                      @change="onAssetChange(scope)"
                      @visible-change="(visible) => !visible && $refs.xTable.updateStatus(scope)"
                    >
                      <el-option
                        v-for="asset in assetOptions"
                        :key="asset.code"
                        :label="`${asset.code} - ${asset.name || '未知资产'}`"
                        :value="asset.code"
                      ></el-option>
                    </el-select>
                  </template>
                  <template #default="{ row }">
                    {{ getAssetName(row.asset_code) }}
                  </template>
                </vxe-column>
                <vxe-column field="weight" title="权重" :edit-render="{}" width="150">
                  <template #edit="{ row }">
                    <el-input-number
                      v-model="row.weight"
                      :min="0"
                      :max="1"
                      :step="0.01"
                      :precision="4"
                      style="width: 100%;"
                    ></el-input-number>
                  </template>
                  <template #default="{ row }">
                    {{ row.weight != null ? (row.weight * 100).toFixed(2) + '%' : '0.00%' }}
                  </template>
                </vxe-column>
                <vxe-column title="操作" width="80">
                  <template #default="{ $rowIndex }">
                    <el-button
                      type="text"
                      size="small"
                      @click="removeComponent($rowIndex)"
                      style="color: #f56c6c;"
                    >
                      删除
                    </el-button>
                  </template>
                </vxe-column>
              </vxe-table>
              <div v-if="form.components.length > 0" class="weight-summary">
                总权重: {{ totalWeight.toFixed(4) }}
              </div>
            </div>
            
            <p v-if="form.benchmark_type" class="help-text">
              {{ benchmarkTypeHelpText }}
            </p>
          </div>
        </el-form-item>
      </el-form>

      <div slot="footer" class="dialog-footer">
        <el-button @click="handleDialogClose">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          {{ submitting ? '保存中...' : '保存' }}
        </el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import dayjs from 'dayjs';

export default {
  name: 'BenchmarkList',
  data() {
    return {
      searchForm: {
        code: '',
        name: '',
        benchmark_type: ''
      },
      tableData: [],
      loading: false,
      pagination: {
        current: 1,
        pageSize: 20,
        total: 0
      },
      dialogVisible: false,
      isEdit: false,
      currentId: null,
      form: {
        code: '',
        name: '',
        benchmark_type: '',
        description: '',
        is_active: true,
        components: []
      },
      submitting: false,
      tableKey: 0,  // 用于强制刷新表格
      rules: {
        code: [
          { required: true, message: '请输入基准代码', trigger: 'blur' },
          { min: 1, max: 20, message: '长度在 1 到 20 个字符', trigger: 'blur' }
        ],
        name: [
          { required: true, message: '请输入基准名称', trigger: 'blur' },
          { min: 1, max: 50, message: '长度在 1 到 50 个字符', trigger: 'blur' }
        ],
        benchmark_type: [
          { required: true, message: '请选择基准类型', trigger: 'change' }
        ],
        is_active: [
          { required: true, message: '请选择启用状态', trigger: 'change' }
        ]
      },
      assetOptions: [],
      absoluteValue: 0,
      singleAssetCode: ''
    };
  },
  watch: {
    'form.benchmark_type'(newVal, oldVal) {
      // 当基准类型改变时，清空相关数据
      if (newVal !== oldVal) {
        this.singleAssetCode = '';
        this.absoluteValue = 0;
        this.form.components = [];
      }
    }
  },
  computed: {
    dialogTitle() {
      return this.isEdit ? '编辑业绩基准' : '新增业绩基准';
    },
    totalWeight() {
      return this.form.components.reduce((sum, component) => sum + (component.weight || 0), 0);
    },
    showAddComponentButton() {
      return this.form.benchmark_type === '复合基准';
    },
    benchmarkTypeHelpText() {
      switch (this.form.benchmark_type) {
        case '单一基准':
          return '单一基准：基于单个资产的表现作为比较标准';
        case '复合基准':
          return '复合基准：由多个资产按特定权重组成的投资组合';
        case '绝对基准':
          return '绝对基准：设定的固定收益率标准（如年化5%）';
        default:
          return '';
      }
    }
  },
  created() {
    this.fetchData();
    this.loadAssets();
  },
  methods: {
    async fetchData() {
      this.loading = true;
      try {
        const res = await this.$store.dispatch('benchmark/fetchBenchmarkList');
        this.tableData = res;
        this.pagination.total = res.length;
      } catch (error) {
        this.$message.error('加载业绩基准列表失败');
      } finally {
        this.loading = false;
      }
    },
    handleSearch() {
      this.pagination.current = 1;
      this.fetchData();
    },
    handleReset() {
      this.searchForm = {
        code: '',
        name: '',
        benchmark_type: ''
      };
      this.fetchData();
    },
    handleCreate() {
      this.isEdit = false;
      this.currentId = null;
      this.resetForm();
      this.dialogVisible = true;
    },
    handleEdit(row) {
      this.isEdit = true;
      this.currentId = row.id;
      
      // 确保资产数据已加载
      if (this.assetOptions.length === 0) {
        this.loadAssets().then(() => {
          this.initializeEditForm(row);
          this.tableKey++;
          this.$nextTick(() => {
            this.dialogVisible = true;
          });
        });
      } else {
        this.initializeEditForm(row);
        this.tableKey++;
        this.$nextTick(() => {
          this.dialogVisible = true;
        });
      }
    },
    initializeEditForm(row) {
      this.form = {
        code: row.code,
        name: row.name,
        benchmark_type: row.benchmark_type,
        description: row.description || '',
        is_active: row.is_active !== false, // 默认为true
        components: []
      };
      
      // 根据基准类型设置特定值
      if (row.benchmark_type === '单一基准' && row.components && row.components.length > 0) {
        this.singleAssetCode = JSON.parse(JSON.stringify(row.components[0].asset_code));
        this.form.components = JSON.parse(JSON.stringify([...row.components]));
        
        // 延迟刷新单一基准的下拉框，确保正确显示值
        this.$nextTick(() => {
          setTimeout(() => {
            this.tableKey++;
          }, 100);
        });
      } else if (row.benchmark_type === '复合基准' && row.components) {
        // 复合基准：复制所有组件
        this.form.components = JSON.parse(JSON.stringify(row.components.map(comp => ({
          asset_code: comp.asset_code,
          weight: comp.weight
        }))));
        
        // 延迟刷新复合基准的表格，确保下拉框正确显示值
        this.$nextTick(() => {
          setTimeout(() => {
            this.tableKey++;
          }, 100);
        });
      } else if (row.benchmark_type === '绝对基准') {
        // 假设绝对基准值存储在第一个组件的权重中或在其他字段
        this.absoluteValue = row.absolute_value || (row.components && row.components.length > 0 ? row.components[0].weight : 0);
        this.form.components = JSON.parse(JSON.stringify([...(row.components || [])]));
      }
    },
    handleView(row) {
      // 查看功能，可以打开一个详情对话框
      this.$alert(`
        <div><strong>基准代码:</strong> ${row.code}</div>
        <div><strong>基准名称:</strong> ${row.name}</div>
        <div><strong>基准类型:</strong> ${row.benchmark_type}</div>
        <div><strong>描述:</strong> ${row.description || '-'}</div>
        <div><strong>状态:</strong> ${row.is_active ? '启用' : '禁用'}</div>
        <div><strong>创建时间:</strong> ${this.formatDate(row.created_at)}</div>
        <div><strong>更新时间:</strong> ${this.formatDate(row.updated_at)}</div>
      `, '业绩基准详情', {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '确定'
      });
    },
    handleDelete(row) {
      this.$confirm(`确定要删除基准 "${row.name}" 吗?`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('benchmark/deleteBenchmark', row.id);
          this.$message.success('删除成功');
          this.fetchData();
        } catch (error) {
          this.$message.error('删除失败：' + (error.response?.data?.detail || error.message));
        }
      }).catch(() => {});
    },
    addComponent() {
      // 只有复合基准才允许多个成分
      if (this.form.benchmark_type === '复合基准') {
        this.form.components.push({
          asset_code: '',
          weight: 0
        });
      }
    },
    removeComponent(index) {
      if (this.form.benchmark_type === '复合基准') {
        this.form.components.splice(index, 1);
      }
    },
    resetForm() {
      this.form = {
        code: '',
        name: '',
        benchmark_type: '',
        description: '',
        is_active: true,
        components: []
      };
      this.absoluteValue = 0;
      this.singleAssetCode = '';
      if (this.$refs.form) {
        this.$refs.form.clearValidate();
      }
    },
    handleDialogClose() {
      this.dialogVisible = false;
      this.resetForm();
    },
    handleSubmit() {
      this.$refs.form.validate(async (valid) => {
        if (!valid) {
          this.$message.warning('请完善必填项');
          return;
        }

        this.submitting = true;
        try {
          // 根据基准类型构造不同的components数据
          let componentsData = [];
          
          if (this.form.benchmark_type === '单一基准') {
            // 单一基准：只包含一个资产
            if (this.singleAssetCode) {
              componentsData = [{
                asset_code: this.singleAssetCode,
                weight: 1.0
              }];
            }
          } else if (this.form.benchmark_type === '复合基准') {
            // 复合基准：使用表格中的多个资产
            componentsData = this.form.components.filter(comp => comp.asset_code);
          } else if (this.form.benchmark_type === '绝对基准') {
            // 绝对基准：创建一个代表绝对值的虚拟资产
            componentsData = [{
              asset_code: 'ABSOLUTE_RETURN',
              weight: this.absoluteValue
            }];
          }
          
          const benchmarkData = {
            code: this.form.code,
            name: this.form.name,
            benchmark_type: this.form.benchmark_type,
            description: this.form.description,
            is_active: this.form.is_active,
            components: componentsData
          };

          if (this.isEdit) {
            await this.$store.dispatch('benchmark/updateBenchmark', {
              benchmarkId: this.currentId,
              data: benchmarkData
            });
            this.$message.success('更新成功');
          } else {
            await this.$store.dispatch('benchmark/createBenchmark', benchmarkData);
            this.$message.success('创建成功');
          }

          this.dialogVisible = false;
          this.fetchData();
        } catch (error) {
          this.$message.error('保存失败：' + (error.response?.data?.detail || error.message));
        } finally {
          this.submitting = false;
        }
      });
    },
    handleSizeChange(val) {
      this.pagination.pageSize = val;
      this.fetchData();
    },
    handleCurrentChange(val) {
      this.pagination.current = val;
      this.fetchData();
    },
    async loadAssets() {
      try {
        const res = await this.$store.dispatch('asset/fetchAssetOptions');
        this.assetOptions = res;
        return Promise.resolve(res);
      } catch (error) {
        console.error('加载资产数据失败:', error);
        this.$message.error('加载资产数据失败');
        return Promise.reject(error);
      }
    },
    onAssetChange(scope) {
      // 找到选中的资产对象，可以手动更新一下行数据确保响应式
      const asset = this.assetOptions.find(a => a.code === scope.row.asset_code);
      if (asset) {
        // 使用 $set 确保数据响应式更新
        this.$set(scope.row, 'asset_name', asset.name);
      }
      
      if (this.$refs.xTable) {
        this.$refs.xTable.updateStatus(scope);
      }
    },
    getAssetName(code) {
      if (!code) return '-';
      const asset = this.assetOptions.find(a => a.code === code);
      return asset ? `${asset.code} - ${asset.name || '未知资产'}` : code;
    },
    refreshComponents() {
      // 强制刷新组件
      this.tableKey++;
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-';
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

.search-form {
  background: #fff;
  padding: 20px;
  margin-bottom: 20px;
  border-radius: 4px;
}

.dialog-footer {
  text-align: right;
}

.components-container {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 15px;
}

.weight-summary {
  margin-top: 10px;
  padding: 10px;
  background-color: #f5f7fa;
  border-radius: 4px;
  text-align: right;
  font-weight: bold;
  color: #606266;
}

.help-text {
  margin-top: 10px;
  color: #909399;
  font-size: 13px;
  line-height: 1.4;
}

.absolute-benchmark-input {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.single-benchmark-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.composite-benchmark-editor {
  margin-top: 10px;
}
</style>