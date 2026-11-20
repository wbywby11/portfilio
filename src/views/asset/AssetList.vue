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
          <el-input v-model="searchForm.code" placeholder="请输入资产代码" clearable style="width: 140px;"></el-input>
        </el-form-item>
        <el-form-item label="资产名称">
          <el-input v-model="searchForm.name" placeholder="请输入资产名称" clearable style="width: 140px;"></el-input>
        </el-form-item>
        <el-form-item label="工具形态">
          <el-select v-model="searchForm.instrument_type" placeholder="请选择" clearable style="width: 120px;">
            <el-option
              v-for="item in instrumentTypes"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            ></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="资产大类">
          <el-select v-model="searchForm.asset_class" placeholder="请选择" clearable style="width: 120px;">
            <el-option
              v-for="item in assetClasses"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            ></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-select
            v-model="searchForm.tags"
            placeholder="多个取交集"
            multiple
            collapse-tags
            filterable
            allow-create
            default-first-option
            clearable
            style="width: 220px;"
          >
            <el-option
              v-for="item in tagOptions"
              :key="item.tag"
              :label="`${item.tag} (${item.count})`"
              :value="item.tag"
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
        <vxe-column field="code" title="资产代码" width="110"></vxe-column>
        <vxe-column field="name" title="资产名称" min-width="130" show-overflow="title"></vxe-column>
        <vxe-column field="instrument_type" title="工具形态" width="90">
          <template #default="{ row }">
            <el-tag size="small">{{ row.instrument_type || '-' }}</el-tag>
          </template>
        </vxe-column>
        <vxe-column field="asset_class" title="资产大类" width="90">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.asset_class || '-' }}</el-tag>
          </template>
        </vxe-column>
        <vxe-column field="security_type" title="证券细分" width="80">
          <template #default="{ row }">
            <span>{{ row.security_type || '-' }}</span>
          </template>
        </vxe-column>
        <vxe-column field="tags" title="标签" min-width="180" show-overflow="title">
          <template #default="{ row }">
            <template v-if="row.tags && row.tags.length">
              <el-tag
                v-for="tag in row.tags.slice(0, 3)"
                :key="tag"
                size="small"
                type="success"
                style="margin-right: 4px;"
              >{{ tag }}</el-tag>
              <el-tooltip v-if="row.tags.length > 3" :content="row.tags.slice(3).join('、')" placement="top">
                <el-tag size="small" type="info">+{{ row.tags.length - 3 }}</el-tag>
              </el-tooltip>
            </template>
            <span v-else style="color: #c0c4cc;">-</span>
          </template>
        </vxe-column>
        <vxe-column field="exchange" title="交易所" width="90"></vxe-column>
        <vxe-column field="substitute_code" title="替代标的" width="100">
          <template #default="{ row }">
            {{ row.substitute_code || '-' }}
          </template>
        </vxe-column>
        <vxe-column field="description" title="描述" min-width="120" show-overflow="title"></vxe-column>
        <vxe-column field="is_active" title="状态" width="70">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </vxe-column>
        <vxe-column title="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button type="text" size="small" @click="handleViewQuote(row)">行情</el-button>
            <el-button type="text" size="small" @click="handleView(row)">查看</el-button>
            <el-dropdown trigger="click" @command="cmd => handleRowCommand(cmd, row)">
              <el-button type="text" size="small">
                更多<i class="el-icon-arrow-down el-icon--right"></i>
              </el-button>
              <el-dropdown-menu slot="dropdown">
                <el-dropdown-item command="edit">编辑</el-dropdown-item>
                <el-dropdown-item command="delete" divided style="color: #f56c6c;">删除</el-dropdown-item>
              </el-dropdown-menu>
            </el-dropdown>
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
import { downloadAssetTemplate, importAssetsFromExcel, getAssetTags } from '@/api/asset';
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
        instrument_type: '',
        asset_class: '',
        tags: []
      },
      // 全部已用标签（供筛选下拉）
      tagOptions: [],
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
    ...mapState('asset', ['assetList', 'instrumentTypes', 'assetClasses', 'loading'])
  },
  created() {
    this.fetchData();
    this.fetchTagOptions();
  },
  methods: {
    async fetchTagOptions() {
      try {
        const response = await getAssetTags();
        this.tagOptions = (response && response.data) || [];
      } catch (error) {
        // 标签列表仅用于辅助筛选，取不到不阻断列表展示
        console.error('加载资产标签失败:', error);
        this.tagOptions = [];
      }
    },
    async fetchData() {
      try {
        await this.$store.dispatch('asset/fetchAssetList', {
          instrument_type: this.searchForm.instrument_type || undefined,
          asset_class: this.searchForm.asset_class || undefined,
          code: this.searchForm.code || undefined,
          name: this.searchForm.name || undefined,
          tags: this.searchForm.tags && this.searchForm.tags.length ? this.searchForm.tags : undefined,
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
        instrument_type: '',
        asset_class: '',
        tags: []
      };
      this.fetchData();
    },
    handleView(row) {
      this.currentDetailAsset = row;
      this.detailVisible = true;
    },
    handleRowCommand(cmd, row) {
      if (cmd === 'edit') this.handleEdit(row);
      else if (cmd === 'delete') this.handleDelete(row);
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
        // 后端返回 inserted_count/updated_count/error_count（无 success_count 字段）
        const inserted = data.inserted_count || 0;
        const updated = data.updated_count || 0;
        const failed = data.error_count || 0;

        if (inserted + updated > 0) {
          this.$message.success(
            `导入完成！新增: ${inserted}条，更新: ${updated}条，失败: ${failed}条`
          );
        } else {
          this.$message.warning(
            `导入未写入任何数据（失败: ${failed}条），请查看错误明细或检查文件列名`
          );
        }

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
