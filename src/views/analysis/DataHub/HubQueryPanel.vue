<template>
  <div class="hub-query-panel">
    <el-card class="filter-card" shadow="never">
      <el-form :model="filter" size="small" label-width="96px" class="filter-form" @submit.native.prevent="handleSearch">
        <template v-if="importParamStyle === 'date_range'">
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="关键字">
                <el-input v-model="filter.keyword" clearable placeholder="多字段模糊" prefix-icon="el-icon-search"
                  @keyup.enter.native="handleSearch" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="风险等级">
                <el-select v-model="filter.risk_signal_level" multiple collapse-tags clearable placeholder="全部" style="width: 100%;">
                  <el-option v-for="lv in levelOptions" :key="lv.value" :label="lv.label" :value="lv.value" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="业务日期">
                <el-date-picker v-model="dateRange" type="daterange" range-separator="至" start-placeholder="起始"
                  end-placeholder="结束" value-format="yyyy-MM-dd" style="width: 100%;" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="所属省份">
                <el-select v-model="filter.affiliated_province" clearable filterable placeholder="全部" style="width: 100%;">
                  <el-option v-for="p in provinceOptions" :key="p" :label="p" :value="p" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="企业性质">
                <el-select v-model="filter.enterprise_nature" clearable filterable placeholder="全部" style="width: 100%;">
                  <el-option v-for="n in natureOptions" :key="n" :label="n" :value="n" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="统一信用代码">
                <el-input v-model="filter.unified_social_credit_code" clearable placeholder="模糊匹配"
                  @keyup.enter.native="handleSearch" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>
        <template v-else-if="importParamStyle === 'ptl_param_maps'">
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="关键字">
                <el-input v-model="filter.keyword" clearable placeholder="多字段模糊" prefix-icon="el-icon-search"
                  @keyup.enter.native="handleSearch" />
              </el-form-item>
            </el-col>
            <el-col v-for="uf in ptlFieldsNoKeyword" :key="uf.key" :span="8">
              <el-form-item :label="uf.label">
                <el-select
                  v-if="uf.component === 'enum_multi'"
                  v-model="dynFilterValues[uf.key]"
                  multiple
                  collapse-tags
                  clearable
                  filterable
                  placeholder="全部"
                  style="width: 100%;"
                >
                  <el-option v-for="opt in enumOptionsDynamic[uf.key] || []" :key="String(opt)" :label="opt" :value="opt" />
                </el-select>
                <el-select
                  v-else-if="uf.component === 'enum'"
                  v-model="dynFilterValues[uf.key]"
                  clearable
                  filterable
                  placeholder="全部"
                  style="width: 100%;"
                >
                  <el-option v-for="opt in enumOptionsDynamic[uf.key] || []" :key="String(opt)" :label="opt" :value="opt" />
                </el-select>
                <el-date-picker
                  v-else-if="uf.component === 'daterange'"
                  v-model="dateRanges[uf.key]"
                  type="daterange"
                  range-separator="至"
                  start-placeholder="起始"
                  end-placeholder="结束"
                  value-format="yyyy-MM-dd"
                  style="width: 100%;"
                />
                <el-input
                  v-else
                  v-model="dynFilterValues[uf.key]"
                  clearable
                  placeholder="精确匹配"
                  @keyup.enter.native="handleSearch"
                />
              </el-form-item>
            </el-col>
          </el-row>
        </template>
        <el-row :gutter="16" v-if="filter.batch_id">
          <el-col :span="24">
            <el-alert type="info" :closable="false" show-icon style="margin-bottom: 10px;">
              当前仅显示批次 <code>{{ filter.batch_id }}</code>
              <el-button type="text" size="mini" @click="clearBatchFilter">清除批次筛选</el-button>
            </el-alert>
          </el-col>
        </el-row>
        <el-row>
          <el-col :span="24" class="filter-actions">
            <el-button type="primary" icon="el-icon-search" @click="handleSearch" :loading="loading">查询</el-button>
            <el-button icon="el-icon-refresh-left" @click="handleReset">重置</el-button>
            <el-button type="text" icon="el-icon-download" @click="exportCurrentPage" :disabled="!rows.length">导出当前页 CSV</el-button>
            <span class="total-badge" v-if="total">共 <strong>{{ total }}</strong> 条</span>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <chart-grid v-if="overview && overview.charts" :charts="overview.charts" />

    <el-card class="table-card" shadow="never">
      <div slot="header"><span><i class="el-icon-tickets"></i> 记录列表</span></div>
      <el-table v-loading="loading" :data="rows" border stripe size="mini" height="520" style="width: 100%"
        :row-class-name="rowClassName">
        <el-table-column
          v-if="badgeField"
          :prop="badgeField"
          label="标记"
          width="100"
          fixed
        >
          <template v-slot="{ row }">
            <el-tag :type="levelTagType(rowRiskLevel(row))" size="mini" effect="dark">{{ rowRiskLevel(row) || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column
          v-if="hasSubjectName"
          prop="subject_name"
          label="主体名称"
          min-width="200"
          fixed
          show-overflow-tooltip
        >
          <template v-slot="{ row }">
            <span>{{ rowSubjectName(row) || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column
          v-if="hasPinnedProductCode"
          prop="产品代码"
          label="产品代码"
          min-width="140"
          fixed
          show-overflow-tooltip
        />
        <el-table-column
          v-if="hasProductShortName"
          prop="产品简称"
          label="产品简称"
          min-width="160"
          fixed
          show-overflow-tooltip
        />
        <el-table-column
          v-for="col in visibleCols"
          :key="col"
          :prop="col"
          :label="columnLabel(col)"
          min-width="120"
          show-overflow-tooltip
        />
        <el-table-column label="操作" width="80" fixed="right">
          <template v-slot="{ row }">
            <el-button type="text" size="mini" icon="el-icon-view" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template slot="empty">
          <div class="empty"><span class="muted">暂无数据，请先导入</span></div>
        </template>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination background layout="total, sizes, prev, pager, next, jumper" :current-page.sync="page"
          :page-size.sync="pageSize" :page-sizes="[20, 50, 100, 200]" :total="total" @size-change="reload"
          @current-change="reload" />
      </div>
    </el-card>

    <el-drawer :visible.sync="detailVisible" :title="detailTitle" size="46%" direction="rtl">
      <div v-if="detailRow" class="detail-content">
        <pre class="json-block">{{ detailJson }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import ChartGrid from './ChartGrid.vue';
import {
  queryDataHubRecords,
  getDataHubStats,
  getDataHubDistinct,
  getDataHubFields
} from '@/api/dataHub';

const LEVEL_TYPE_MAP = { 红: 'danger', 橙: 'warning', 黄: 'warning', 蓝: 'info', 绿: 'success', 信息提示类: 'info' };

const PTL_COL_ORDER = ['产品代码', '产品简称', '产品名称', '风险等级', '产品性质', '币种', '管理人', '数据日期', '数据来源'];

export default {
  name: 'DataHubQueryPanel',
  components: { ChartGrid },
  props: {
    connectorId: { type: String, required: true },
    connector: { type: Object, default: () => ({}) },
    overview: { type: Object, default: () => ({}) },
    badgeField: { type: String, default: '' }
  },
  data() {
    return {
      filter: {
        keyword: '',
        risk_signal_level: [],
        unified_social_credit_code: '',
        affiliated_province: '',
        enterprise_nature: '',
        batch_id: ''
      },
      dateRange: [],
      dynFilterValues: {},
      dateRanges: {},
      enumOptionsDynamic: {},
      rows: [],
      total: 0,
      page: 1,
      pageSize: 20,
      loading: false,
      detailVisible: false,
      detailRow: null,
      levelOptions: [],
      provinceOptions: [],
      natureOptions: [],
      indNameMeta: [],
      dynCols: []
    };
  },
  computed: {
    importParamStyle() {
      return (this.connector && this.connector.import_param_style) || 'date_range';
    },
    ptlFieldsNoKeyword() {
      const ufs = (this.connector && this.connector.ui_filter_fields) || [];
      return ufs.filter(function (f) { return f.component !== 'keyword'; });
    },
    detailTitle() {
      if (!this.detailRow) return '记录详情';
      if (this.connectorId === 'zysc_dwd_ptl_holder_summary') {
        var parts = [this.detailRow['产品代码'], this.detailRow['生效日期']].filter(Boolean);
        return parts.length ? String(parts.join(' · ')) : '记录详情';
      }
      if (this.connectorId === 'zysc_dwd_ptl_info' && this.importParamStyle === 'ptl_param_maps') {
        return String(
          this.detailRow['产品简称'] || this.detailRow['产品名称'] || this.detailRow['产品代码'] ||
            this.detailRow[this.badgeField] || this.connectorId || '记录详情'
        );
      }
      if (this.importParamStyle === 'ptl_param_maps') {
        return String(
          this.detailRow['产品代码'] || this.detailRow[this.badgeField] || this.connectorId || '记录详情'
        );
      }
      return String(this.detailRow.subject_name || this.detailRow[this.badgeField] || this.connectorId || '记录详情');
    },
    detailJson() {
      return this.detailRow ? JSON.stringify(this.detailRow, null, 2) : '';
    },
    hasSubjectName() {
      if (this.importParamStyle !== 'date_range' || !this.rows.length) return false;
      const r = this.rows[0];
      return (
        Object.prototype.hasOwnProperty.call(r, 'subject_name') ||
        Object.prototype.hasOwnProperty.call(r, '主体名称') ||
        Object.prototype.hasOwnProperty.call(r, 'SUBJECT_NAME') ||
        Object.prototype.hasOwnProperty.call(r, 'subjectName')
      );
    },
    hasPinnedProductCode() {
      return this.connectorId === 'zysc_dwd_ptl_holder_summary' && this.rows.length &&
        Object.prototype.hasOwnProperty.call(this.rows[0], '产品代码');
    },
    hasProductShortName() {
      return this.connectorId === 'zysc_dwd_ptl_info' && this.importParamStyle === 'ptl_param_maps' &&
        this.rows.length &&
        Object.prototype.hasOwnProperty.call(this.rows[0], '产品简称');
    },
    visibleCols() {
      var bf = this.badgeField || '';
      var vm = this;
      if (this.dynCols && this.dynCols.length) {
        const skip = ['subject_name', '产品简称'];
        return this.dynCols.filter(function (k) {
          if (skip.indexOf(k) >= 0) return false;
          if (bf && k === bf) return false;
          if (vm.hasPinnedProductCode && k === '产品代码') return false;
          return true;
        });
      }
      const r = this.rows[0];
      if (!r) return [];
      return Object.keys(r).filter(
        k => k.indexOf('_') !== 0 && k !== bf && k !== 'subject_name' && k !== '产品简称' &&
          !(vm.hasPinnedProductCode && k === '产品代码')
      ).slice(0, 16);
    }
  },
  watch: {
    connectorId() {
      var vm = this;
      this.$nextTick(function () {
        vm.handleReset();
        vm.fetchEnums();
        vm.fetchIndMeta();
        vm.reload();
        vm.refreshCharts();
      });
    },
    overview: {
      handler() {
        this.$nextTick(() => {
          try {
            this.$children.forEach(ch => ch.$forceUpdate && ch.$forceUpdate());
          } catch (e) { /* noop */ }
        });
      },
      deep: true
    }
  },
  mounted() {
    this.initDynFilters();
    this.fetchEnums();
    this.fetchIndMeta();
    this.reload();
    this.refreshCharts();
  },
  methods: {
    initDynFilters() {
      this.dynFilterValues = {};
      this.dateRanges = {};
      if (this.importParamStyle !== 'ptl_param_maps') return;
      const ufs = (this.connector && this.connector.ui_filter_fields) || [];
      var vm = this;
      ufs.forEach(function (uf) {
        if (uf.component === 'keyword') return;
        if (uf.component === 'enum_multi') {
          vm.$set(vm.dynFilterValues, uf.key, []);
        } else if (uf.component === 'daterange') {
          vm.$set(vm.dateRanges, uf.key, []);
        } else if (uf.component === 'enum') {
          vm.$set(vm.dynFilterValues, uf.key, '');
        } else {
          vm.$set(vm.dynFilterValues, uf.key, '');
        }
      });
    },
    columnLabel(code) {
      const m = this.indNameMeta.find(x => (x.ind_code || '').toUpperCase() === String(code).toUpperCase());
      return (m && m.ind_name) || code;
    },
    async fetchIndMeta() {
      try {
        const res = await getDataHubFields(this.connectorId);
        const d = res && res.data !== undefined ? res.data : res;
        const list = (d && d.ind_name_list) ? d.ind_name_list : [];
        this.indNameMeta = list;
      } catch (e) {
        this.indNameMeta = [];
      }
    },
    async fetchEnums() {
      if (this.importParamStyle === 'ptl_param_maps') {
        await this.fetchEnumOptionsProduct();
        return;
      }
      try {
        const [lv, prov, nat] = await Promise.all([
          getDataHubDistinct(this.connectorId, 'risk_signal_level'),
          getDataHubDistinct(this.connectorId, 'affiliated_province'),
          getDataHubDistinct(this.connectorId, 'enterprise_nature')
        ]);
        const pickVals = (r) => {
          const d = r && r.data !== undefined ? r.data : r;
          return (d && d.values) ? d.values : [];
        };
        const lvVals = pickVals(lv);
        const pVals = pickVals(prov);
        const nVals = pickVals(nat);
        this.levelOptions = lvVals.map(v => ({ value: v, label: v }));
        this.provinceOptions = pVals;
        this.natureOptions = nVals;
      } catch (e) {
        // 静默
      }
    },
    async fetchEnumOptionsProduct() {
      const vm = this;
      const ufs = (this.connector && this.connector.ui_filter_fields) || [];
      const pickVals = function (r) {
        const d = r && r.data !== undefined ? r.data : r;
        return (d && d.values) ? d.values : [];
      };
      const opts = {};
      for (let i = 0; i < ufs.length; i++) {
        const uf = ufs[i];
        if (uf.enum_source !== 'distinct' || !uf.mongo_field) continue;
        try {
          var res = await getDataHubDistinct(this.connectorId, uf.mongo_field);
          vm.$set(opts, uf.key, pickVals(res));
        } catch (e) {
          vm.$set(opts, uf.key, []);
        }
      }
      this.enumOptionsDynamic = opts;
    },
    levelTagType(level) {
      if (!level) return 'info';
      var s = String(level);
      var keys = Object.keys(LEVEL_TYPE_MAP);
      for (var i = 0; i < keys.length; i++) {
        if (s.indexOf(keys[i]) >= 0) return LEVEL_TYPE_MAP[keys[i]];
      }
      return 'info';
    },
    rowSubjectName(row) {
      if (!row) return '';
      var v = row.subject_name || row['主体名称'] || row.SUBJECT_NAME || row.subjectName || row['客户名称'];
      return v != null && String(v).trim() ? String(v).trim() : '';
    },
    rowRiskLevel(row) {
      if (!row) return '';
      var bf = this.badgeField || 'risk_signal_level';
      var v = row[bf] || row.risk_signal_level || row['风险等级'] || row.RISK_SIGNAL_LEVEL;
      return v != null && String(v).trim() ? String(v).trim() : '';
    },
    rowClassName(arg) {
      var row = arg.row;
      var lv = this.rowRiskLevel(row) || (this.badgeField ? row[this.badgeField] : '') || '';
      var s = String(lv);
      if (s.indexOf('红') >= 0) return 'row-level-red';
      if (s.indexOf('橙') >= 0) return 'row-level-orange';
      if (s.indexOf('黄') >= 0) return 'row-level-yellow';
      return '';
    },
    buildFiltersPtl() {
      var clauses = [];
      const ufs = (this.connector && this.connector.ui_filter_fields) || [];
      var vm = this;
      ufs.forEach(function (uf) {
        if (uf.component === 'keyword') return;
        var mf = uf.mongo_field || uf.key;
        if (uf.component === 'text') {
          var tv = vm.dynFilterValues[uf.key];
          if (tv && String(tv).trim()) {
            clauses.push({ field: mf, op: 'eq', value: String(tv).trim() });
          }
        } else if (uf.component === 'enum_multi') {
          var arr = vm.dynFilterValues[uf.key];
          if (arr && arr.length) {
            clauses.push({ field: mf, op: 'in', value: arr.slice() });
          }
        } else if (uf.component === 'enum') {
          var ev = vm.dynFilterValues[uf.key];
          if (ev && String(ev).trim()) {
            clauses.push({ field: mf, op: 'eq', value: String(ev).trim() });
          }
        } else if (uf.component === 'daterange') {
          var dr = vm.dateRanges[uf.key] || [];
          if (dr[0]) clauses.push({ field: mf, op: 'gte', value: dr[0] });
          if (dr[1]) clauses.push({ field: mf, op: 'lte', value: dr[1] });
        }
      });
      return clauses;
    },
    buildFilters() {
      if (this.importParamStyle === 'ptl_param_maps') {
        return this.buildFiltersPtl();
      }
      var clauses = [];
      if (this.filter.risk_signal_level && this.filter.risk_signal_level.length) {
        clauses.push({ field: 'risk_signal_level', op: 'in', value: this.filter.risk_signal_level.slice() });
      }
      if (this.filter.unified_social_credit_code && this.filter.unified_social_credit_code.trim()) {
        clauses.push({
          field: 'unified_social_credit_code',
          op: 'eq',
          value: this.filter.unified_social_credit_code.trim()
        });
      }
      if (this.filter.affiliated_province && this.filter.affiliated_province.trim()) {
        clauses.push({
          field: 'affiliated_province',
          op: 'eq',
          value: this.filter.affiliated_province.trim()
        });
      }
      if (this.filter.enterprise_nature && this.filter.enterprise_nature.trim()) {
        clauses.push({ field: 'enterprise_nature', op: 'eq', value: this.filter.enterprise_nature.trim() });
      }
      var dr = this.dateRange || [];
      if (dr[0]) clauses.push({ field: 'biz_date', op: 'gte', value: dr[0] });
      if (dr[1]) clauses.push({ field: 'biz_date', op: 'lte', value: dr[1] });
      return clauses;
    },
    buildPayload() {
      var kw = this.filter.keyword ? this.filter.keyword.trim() : '';
      return {
        page: this.page,
        page_size: this.pageSize,
        sort_by: '_imported_at',
        sort_desc: true,
        batch_id: this.filter.batch_id || null,
        keyword: kw ? kw : null,
        filters: this.buildFilters()
      };
    },
    async reload() {
      if (!this.connectorId) return;
      this.loading = true;
      try {
        var payload = this.buildPayload();
        var res = await queryDataHubRecords(this.connectorId, payload);
        var data = res && res.data !== undefined ? res.data : res;
        this.rows = (data && data.items) ? data.items : [];
        this.total = (data && data.total) ? data.total : 0;
        if (this.rows.length) {
          if (this.importParamStyle === 'ptl_param_maps') {
            var order = [];
            var prio = this.connector && this.connector.column_display_priority;
            if (prio && prio.length) {
              order = prio.slice();
            } else if (this.connectorId === 'zysc_dwd_ptl_info') {
              order = PTL_COL_ORDER.slice();
            }
            var firstP = Object.keys(this.rows[0]).filter(function (k) { return k.indexOf('_') !== 0; });
            if (order.length) {
              this.dynCols = order.filter(function (k) { return firstP.indexOf(k) >= 0; }).concat(
                firstP.filter(function (k) { return order.indexOf(k) < 0; })
              );
            } else {
              this.dynCols = firstP.slice();
            }
          } else {
            const keys = ['subject_name', 'unified_social_credit_code', 'risk_signal_level', 'biz_date', 'affiliated_province', 'enterprise_nature'];
            var first = Object.keys(this.rows[0]).filter(function (k) { return k.indexOf('_') !== 0; });
            this.dynCols = keys.filter(k => first.indexOf(k) >= 0).concat(first.filter(function (k) { return keys.indexOf(k) < 0; }));
          }
        }
      } catch (e) {
        this.rows = [];
        this.total = 0;
      } finally {
        this.loading = false;
      }
    },
    async refreshCharts() {
      if (!this.connectorId) return;
      try {
        const res = await getDataHubStats(this.connectorId);
        var data = res && res.data !== undefined ? res.data : res;
        this.$emit('overview-update', data);
      } catch (e) {}
    },
    handleSearch() {
      this.page = 1;
      this.reload();
      this.refreshCharts();
    },
    handleReset() {
      this.filter = {
        keyword: '',
        risk_signal_level: [],
        unified_social_credit_code: '',
        affiliated_province: '',
        enterprise_nature: '',
        batch_id: ''
      };
      this.dateRange = [];
      this.initDynFilters();
      this.page = 1;
      this.reload();
    },
    openDetail(row) {
      this.detailRow = row;
      this.detailVisible = true;
    },
    applyBatchFilter(batchId) {
      this.filter.batch_id = batchId;
      this.page = 1;
      this.reload();
    },
    clearBatchFilter() {
      this.filter.batch_id = '';
      this.page = 1;
      this.reload();
    },
    exportCurrentPage() {
      if (!this.rows.length) {
        this.$message.warning('当前页无数据');
        return;
      }
      var headCols;
      if (this.importParamStyle === 'ptl_param_maps') {
        if (this.connectorId === 'zysc_dwd_ptl_holder_summary') {
          var hdrPrio = this.connector && this.connector.column_display_priority;
          headCols = hdrPrio && hdrPrio.length
            ? hdrPrio.slice().concat(['_batch_id'])
            : ['产品代码', '生效日期', '数据日期', '_batch_id'];
        } else if (this.connectorId === 'zysc_dwd_ptl_info') {
          headCols = ['产品代码', '产品简称', '产品名称', '风险等级', '_batch_id'];
        } else {
          headCols = ['_batch_id'];
        }
      } else {
        headCols = ['risk_signal_level', 'subject_name', 'risk_id', 'biz_date', '_batch_id'];
      }
      const cols = headCols.concat(this.visibleCols);
      var uniq = [];
      cols.forEach(function (c) { if (uniq.indexOf(c) < 0) uniq.push(c); });
      var escape = function (v) {
        if (v == null) return '';
        var s = String(v);
        if (s.indexOf(',') >= 0 || s.indexOf('"') >= 0 || s.indexOf('\n') >= 0) {
          return '"' + s.replace(/"/g, '""') + '"';
        }
        return s;
      };
      var lines = [uniq.join(',')];
      this.rows.forEach(function (row) {
        lines.push(uniq.map(function (k) { return escape(row[k]); }).join(','));
      });
      var blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `data_hub_${this.connectorId}_page_${this.page}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    },
    exposeBatchFilter(batchId) {
      this.applyBatchFilter(batchId);
    }
  }
};
</script>

<style scoped>
.filter-card {
  margin-bottom: 14px;
  border: 1px solid #ebeef5;
}
.filter-actions {
  margin-top: 6px;
}
.total-badge {
  margin-left: 12px;
  color: #606266;
}
.table-card {
  border: 1px solid #ebeef5;
}
.pagination-wrap {
  margin-top: 12px;
  text-align: right;
}
.detail-content {
  padding: 12px 16px;
}
.json-block {
  background: #f7f9fc;
  padding: 12px;
  font-size: 12px;
  font-family: Menlo, Monaco, Consolas, monospace;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}
.muted {
  color: #909399;
}
</style>

<style>
.hub-query-panel .el-table .row-level-red { background: #fff5f5 !important; }
.hub-query-panel .el-table .row-level-orange { background: #fff9f0 !important; }
.hub-query-panel .el-table .row-level-yellow { background: #fffef5 !important; }
</style>
