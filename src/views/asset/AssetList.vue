<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">资产列表</h2>
      <div>
        <el-button type="primary" icon="el-icon-plus" @click="handleAdd">
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
        <el-form-item>
          <span slot="label">
            资产代码
            <el-tooltip content="从数据库中选择已有的资产代码" placement="top">
              <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
            </el-tooltip>
          </span>
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
      <vxe-table
        :data="tableData"
        :loading="loading"
        border
        stripe
        height="600"
        :scroll-y="{enabled: true, gt: 0}"
        show-overflow="title"
      >
        <vxe-column field="code" title="资产代码" width="120"></vxe-column>
        <vxe-column field="name" title="资产名称" width="150"></vxe-column>
        <vxe-column field="asset_type" title="资产分类" width="120">
          <template #default="{ row }">
            <el-tag size="small">{{ row.asset_type }}</el-tag>
          </template>
        </vxe-column>
        <vxe-column field="exchange" title="交易所" width="120"></vxe-column>
        <vxe-column field="substitute_code" title="替代标的" width="120">
          <template #default="{ row }">
            {{ row.substitute_code || '-' }}
          </template>
        </vxe-column>
        <vxe-column field="description" title="描述" min-width="150" show-overflow="title"></vxe-column>
        <vxe-column field="is_active" title="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </vxe-column>
        <vxe-column title="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button type="text" size="small" @click="handleViewQuote(row)">行情</el-button>
            <el-button type="text" size="small" @click="handleView(row)">查看</el-button>
            <el-tooltip content="后端暂未实现更新接口" placement="top">
              <el-button type="text" size="small" @click="handleEdit(row)">编辑</el-button>
            </el-tooltip>
            <el-button type="text" size="small" @click="handleDelete(row)" style="color: #f56c6c;">
              删除
            </el-button>
          </template>
        </vxe-column>
      </vxe-table>

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

    <!-- 资产表单弹窗 -->
    <el-dialog
      :title="editingAssetCode ? '编辑资产' : '新增资产'"
      :visible.sync="assetFormVisible"
      width="900px"
      :close-on-click-modal="false"
      append-to-body
    >
      <asset-form
        v-if="assetFormVisible"
        is-dialog
        :asset-code="editingAssetCode"
        @success="handleFormSuccess"
        @close="assetFormVisible = false"
      />
    </el-dialog>

    <!-- 行情查看弹窗 -->
    <el-dialog
      :title="`资产行情 - ${currentQuoteAsset ? currentQuoteAsset.name : ''}`"
      :visible.sync="quoteVisible"
      width="1200px"
      append-to-body
      top="5vh"
    >
      <asset-quote
        v-if="quoteVisible"
        is-dialog
        :asset-code="currentQuoteAsset ? currentQuoteAsset.code : ''"
      />
    </el-dialog>

    <!-- 资产详情弹窗 -->
    <el-dialog
      :title="`资产详情 - ${currentDetailAsset ? currentDetailAsset.name : ''}`"
      :visible.sync="detailVisible"
      width="900px"
      append-to-body
      top="5vh"
    >
      <asset-detail
        v-if="detailVisible && currentDetailAsset"
        is-dialog
        :asset-id="currentDetailAsset.id"
      />
    </el-dialog>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import { downloadAssetTemplate, importAssetsFromExcel } from '@/api/asset';
import AssetForm from './AssetForm.vue';
import AssetQuote from './AssetQuote.vue';
import AssetDetail from './AssetDetail.vue';

export default {
  name: 'AssetList',
  components: {
    AssetForm,
    AssetQuote,
    AssetDetail
  },
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
      },
      assetFormVisible: false,
      editingAssetCode: '',
      quoteVisible: false,
      currentQuoteAsset: null,
      detailVisible: false,
      currentDetailAsset: null
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
          code: this.searchForm.code || undefined,
          name: this.searchForm.name || undefined,
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
      this.pagination.current = 1;
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
      this.currentDetailAsset = row;
      this.detailVisible = true;
    },
    handleViewQuote(row) {
      this.currentQuoteAsset = row;
      this.quoteVisible = true;
    },
    handleAdd() {
      this.editingAssetCode = '';
      this.assetFormVisible = true;
    },
    handleEdit(row) {
      this.editingAssetCode = row.code;
      this.assetFormVisible = true;
    },
    handleFormSuccess() {
      this.assetFormVisible = false;
      this.fetchData();
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
