<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">资产列表</h2>
      <div>
        <el-button type="primary" icon="el-icon-plus" @click="$router.push('/asset/add')">
          新增资产
        </el-button>
        <el-button icon="el-icon-download" @click="handleDownloadTemplate">下载资产模板</el-button>
        <el-upload
          ref="assetUpload"
          action=""
          :auto-upload="false"
          :show-file-list="false"
          :on-change="handleAssetFileChange"
          accept=".xlsx,.xls"
          style="display: inline-block; margin-left: 10px;"
        >
          <el-button icon="el-icon-upload2">批量导入资产</el-button>
        </el-upload>
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
        <el-table-column prop="code" label="资产代码" width="120"></el-table-column>
        <el-table-column prop="name" label="资产名称" width="150"></el-table-column>
        <el-table-column prop="asset_type" label="资产分类" width="120">
          <template slot-scope="scope">
            <el-tag size="small">{{ scope.row.asset_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="exchange" label="交易所" width="120"></el-table-column>
        <el-table-column prop="substitute_code" label="替代标的" width="120">
          <template slot-scope="scope">
            {{ scope.row.substitute_code || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="150" show-overflow-tooltip></el-table-column>
        <el-table-column prop="is_active" label="状态" width="100">
          <template slot-scope="scope">
            <el-tag :type="scope.row.is_active ? 'success' : 'info'" size="small">
              {{ scope.row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template slot-scope="scope">
            <el-button type="text" size="small" @click="handleViewQuote(scope.row)">行情</el-button>
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
import { downloadAssetTemplate, importAssetsFromExcel } from '@/api/asset';

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
    handleViewQuote(row) {
      this.$router.push({
        name: 'AssetQuote',
        query: { code: row.code }
      });
    },
    handleEdit(row) {
      this.$router.push(`/asset/edit/${row.id}`);
    },
    handleDelete(row) {
      this.$confirm(`确定要删除资产 "${row.name}" 吗?`, '提示', {
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
    },
    // 下载资产导入模板
    async handleDownloadTemplate() {
      try {
        const blob = await downloadAssetTemplate();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = '资产导入模板.xlsx';
        link.click();
        window.URL.revokeObjectURL(url);
        this.$message.success('模板下载成功');
      } catch (error) {
        this.$message.error('模板下载失败');
      }
    },
    // 处理资产文件选择
    async handleAssetFileChange(file) {
      const loading = this.$loading({
        lock: true,
        text: '正在导入资产数据...',
        spinner: 'el-icon-loading'
      });
      
      try {
        const result = await importAssetsFromExcel(file.raw);
        const data = result.data || result;
        
        this.$message.success(
          `导入完成！成功: ${data.success_count || 0}条，失败: ${data.error_count || 0}条`
        );
        
        if (data.errors && data.errors.length > 0) {
          this.$alert(
            data.errors.join('\n'),
            '导入错误详情',
            {
              confirmButtonText: '确定',
              type: 'warning'
            }
          );
        }
        
        // 刷新列表
        this.fetchData();
      } catch (error) {
        const errorMsg = error.response?.data?.detail || error.message || '导入失败';
        this.$message.error('导入失败：' + errorMsg);
      } finally {
        loading.close();
        // 清空文件选择
        if (this.$refs.assetUpload) {
          this.$refs.assetUpload.clearFiles();
        }
      }
    }
  }
};
</script>

<style scoped>
.search-form {
  margin-bottom: 20px;
}
</style>
