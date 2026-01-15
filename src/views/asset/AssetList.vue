<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">资产列表</h2>
      <div>
        <el-button type="primary" icon="el-icon-plus" @click="$router.push('/asset/add')">
          新增资产
        </el-button>
        <el-button icon="el-icon-upload2">批量导入</el-button>
      </div>
    </div>

    <div class="page-content">
      <!-- 搜索栏 -->
      <el-form :inline="true" :model="searchForm" class="search-form">
        <el-form-item label="资产代码">
          <el-input v-model="searchForm.code" placeholder="请输入资产代码" clearable></el-input>
        </el-form-item>
        <el-form-item label="资产名称">
          <el-input v-model="searchForm.name" placeholder="请输入资产名称" clearable></el-input>
        </el-form-item>
        <el-form-item label="资产分类">
          <el-select v-model="searchForm.category" placeholder="请选择" clearable>
            <el-option
              v-for="item in assetCategories"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            ></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="el-icon-search" @click="handleSearch">查询</el-button>
          <el-button icon="el-icon-refresh" @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- 资产表格 -->
      <el-table
        :data="tableData"
        v-loading="loading"
        style="width: 100%"
        stripe
      >
        <el-table-column prop="asset_code" label="资产代码" width="120"></el-table-column>
        <el-table-column prop="asset_name" label="资产名称" width="150"></el-table-column>
        <el-table-column prop="asset_type" label="资产分类" width="120">
          <template slot-scope="scope">
            <el-tag size="small">{{ getCategoryLabel(scope.row.asset_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="expected_return" label="预期收益率" width="120" align="right">
          <template slot-scope="scope">
            {{ formatPercent(scope.row.expected_return) }}
          </template>
        </el-table-column>
        <el-table-column prop="volatility" label="波动率" width="100" align="right">
          <template slot-scope="scope">
            {{ formatPercent(scope.row.volatility) }}
          </template>
        </el-table-column>
        <el-table-column prop="data_source" label="数据源" width="100">
          <template slot-scope="scope">
            <el-tag size="small" type="info">{{ scope.row.data_source || 'MANUAL' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="100">
          <template slot-scope="scope">
            <el-tag :type="scope.row.is_active ? 'success' : 'info'" size="small">
              {{ scope.row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="small" @click="handleView(scope.row)">查看</el-button>
            <el-tooltip content="后端暂未实现更新接口" placement="top">
              <el-button type="text" size="small" @click="handleEdit(scope.row)">编辑</el-button>
            </el-tooltip>
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
  </div>
</template>

<script>
import { mapState } from 'vuex';

export default {
  name: 'AssetList',
  data() {
    return {
      searchForm: {
        code: '',
        name: '',
        category: ''
      },
      loading: false,
      tableData: [],
      pagination: {
        current: 1,
        pageSize: 20,
        total: 0
      }
    };
  },
  computed: {
    ...mapState('asset', ['assetList', 'assetCategories', 'loading'])
  },
  created() {
    this.fetchData();
  },
  methods: {
    async fetchData() {
      try {
        await this.$store.dispatch('asset/fetchAssetList', {
          category: this.searchForm.category,
          page: this.pagination.current,
          pageSize: this.pagination.pageSize
        });
        this.tableData = this.assetList;
        this.pagination.total = this.$store.state.asset.total;
      } catch (error) {
        this.$message.error('加载资产列表失败');
      }
    },
    handleSearch() {
      this.fetchData();
    },
    handleReset() {
      this.searchForm = {
        code: '',
        name: '',
        category: ''
      };
      this.fetchData();
    },
    handleView(row) {
      this.$message.info('查看资产详情：' + row.name);
    },
    handleEdit(row) {
      this.$router.push(`/asset/edit/${row.asset_code}`);
    },
    handleDelete(row) {
      this.$confirm(`确定要删除资产 "${row.asset_name}" 吗?`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('asset/deleteAsset', row.id);
          this.$message.success('删除成功');
          this.fetchData();
        } catch (error) {
          this.$message.error('删除失败：' + (error.response?.data?.detail || error.message));
        }
      }).catch(() => {});
    },
    handleSizeChange(val) {
      this.pagination.pageSize = val;
      this.fetchData();
    },
    handleCurrentChange(val) {
      this.pagination.current = val;
      this.fetchData();
    },
    getCategoryLabel(value) {
      const item = this.assetCategories.find(c => c.value === value);
      return item ? item.label : value;
    },
    formatPercent(num) {
      return (num * 100).toFixed(2) + '%';
    }
  }
};
</script>

<style scoped>
.search-form {
  margin-bottom: 20px;
}
</style>
