<template>
  <div class="query-panel">
    <!-- 筛选栏 -->
    <el-card class="filter-card" shadow="never">
      <el-form
        :model="filter"
        size="small"
        label-width="96px"
        class="filter-form"
        @submit.native.prevent="handleSearch"
      >
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="关键字">
              <el-input
                v-model="filter.keyword"
                clearable
                placeholder="主体名称 / 描述 / risk_id"
                prefix-icon="el-icon-search"
                @keyup.enter.native="handleSearch"
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="风险等级">
              <el-select
                v-model="filter.risk_signal_level"
                multiple
                collapse-tags
                clearable
                placeholder="全部"
                style="width: 100%;"
              >
                <el-option
                  v-for="lv in levelOptions"
                  :key="lv.value"
                  :label="lv.label"
                  :value="lv.value"
                >
                  <el-tag :type="levelTagType(lv.value)" size="mini" effect="dark">
                    {{ lv.label }}
                  </el-tag>
                </el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="业务日期">
              <el-date-picker
                v-model="dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="起始"
                end-placeholder="结束"
                value-format="yyyy-MM-dd"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="所属省份">
              <el-select
                v-model="filter.affiliated_province"
                clearable
                filterable
                placeholder="全部"
                style="width: 100%;"
              >
                <el-option
                  v-for="p in provinceOptions"
                  :key="p"
                  :label="p"
                  :value="p"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="企业性质">
              <el-select
                v-model="filter.enterprise_nature"
                clearable
                filterable
                placeholder="全部"
                style="width: 100%;"
              >
                <el-option
                  v-for="n in natureOptions"
                  :key="n"
                  :label="n"
                  :value="n"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="统一信用代码">
              <el-input
                v-model="filter.unified_social_credit_code"
                clearable
                placeholder="精确匹配"
                @keyup.enter.native="handleSearch"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16" v-if="filter.batch_id">
          <el-col :span="24">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              style="margin-bottom: 10px;"
            >
              当前仅显示批次
              <code style="background:#eef2f7;padding:1px 6px;border-radius:3px;">{{ filter.batch_id }}</code>
              的记录
              <el-button type="text" size="mini" @click="clearBatchFilter">清除批次筛选</el-button>
            </el-alert>
          </el-col>
        </el-row>

        <el-row>
          <el-col :span="24" class="filter-actions">
            <el-button
              type="primary"
              icon="el-icon-search"
              @click="handleSearch"
              :loading="loading"
            >查询</el-button>
            <el-button icon="el-icon-refresh-left" @click="handleReset">重置</el-button>
            <el-button
              type="text"
              icon="el-icon-download"
              @click="exportCurrentPage"
              :disabled="!rows.length"
            >导出当前页 CSV</el-button>
            <span class="total-badge" v-if="total">
              共 <strong>{{ total }}</strong> 条
            </span>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <!-- 图表统计 -->
    <el-row :gutter="16" class="charts-row">
      <el-col :span="10">
        <el-card class="chart-card" shadow="never">
          <div slot="header" class="clearfix">
            <span><i class="el-icon-pie-chart"></i> 风险等级分布</span>
          </div>
          <div ref="levelChart" class="chart"></div>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card class="chart-card" shadow="never">
          <div slot="header" class="clearfix">
            <span><i class="el-icon-s-data"></i> 省份 Top10</span>
          </div>
          <div ref="provinceChart" class="chart"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 数据表 -->
    <el-card class="table-card" shadow="never">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-tickets"></i> 记录列表</span>
      </div>
      <el-table
        v-loading="loading"
        :data="rows"
        border
        stripe
        size="mini"
        height="520"
        style="width: 100%;"
        :row-class-name="rowClassName"
      >
        <el-table-column
          prop="risk_signal_level"
          label="等级"
          width="90"
          fixed
        >
          <template v-slot="{ row }">
            <el-tag
              :type="levelTagType(rowRiskLevel(row))"
              size="mini"
              effect="dark"
            >
              {{ rowRiskLevel(row) || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          prop="subject_name"
          label="主体名称"
          min-width="220"
          show-overflow-tooltip
          fixed
        >
          <template v-slot="{ row }">
            <el-link
              type="primary"
              :underline="false"
              @click="openDetail(row)"
            >{{ rowSubjectName(row) || '-' }}</el-link>
          </template>
        </el-table-column>
        <el-table-column
          prop="unified_social_credit_code"
          label="统一信用代码"
          width="180"
          show-overflow-tooltip
        />
        <el-table-column
          prop="subject_type"
          label="主体类型"
          width="160"
          show-overflow-tooltip
        />
        <el-table-column
          prop="enterprise_nature"
          label="企业性质"
          width="110"
          show-overflow-tooltip
        />
        <el-table-column
          prop="industry_classification_gb"
          label="行业分类"
          min-width="240"
          show-overflow-tooltip
        />
        <el-table-column
          prop="rule_large"
          label="大类规则"
          width="130"
          show-overflow-tooltip
        />
        <el-table-column
          prop="rule_medium"
          label="中类规则"
          width="140"
          show-overflow-tooltip
        />
        <el-table-column
          prop="rule_small"
          label="小类规则"
          min-width="160"
          show-overflow-tooltip
        />
        <el-table-column
          prop="signal_dascribe"
          label="信号描述"
          min-width="320"
          show-overflow-tooltip
        />
        <el-table-column
          prop="affiliated_province"
          label="省份"
          width="100"
        />
        <el-table-column
          prop="affiliated_city"
          label="地市"
          width="110"
        />
        <el-table-column
          prop="biz_date"
          label="业务日期"
          width="110"
        />
        <el-table-column
          prop="sign_date"
          label="签署日期"
          width="110"
        />
        <el-table-column
          label="操作"
          width="80"
          fixed="right"
        >
          <template v-slot="{ row }">
            <el-button
              type="text"
              size="mini"
              icon="el-icon-view"
              @click="openDetail(row)"
            >详情</el-button>
          </template>
        </el-table-column>
        <template slot="empty">
          <div class="empty">
            <i class="el-icon-document" style="font-size: 32px; color: #c0c4cc;"></i>
            <div class="muted" style="margin-top: 8px;">暂无数据，请先在「数据导入」页拉取</div>
          </div>
        </template>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next, jumper"
          :current-page.sync="page"
          :page-size.sync="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="total"
          @size-change="reload"
          @current-change="reload"
        />
      </div>
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer
      :visible.sync="detailVisible"
      :title="detailRow ? (rowSubjectName(detailRow) || '记录详情') : '记录详情'"
      size="46%"
      direction="rtl"
    >
      <div v-if="detailRow" class="detail-content">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="风险等级">
            <el-tag
              :type="levelTagType(detailRow.risk_signal_level)"
              size="mini"
              effect="dark"
            >{{ detailRow.risk_signal_level || '-' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="risk_id">{{ detailRow.risk_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="主体名称">{{ rowSubjectName(detailRow) || '-' }}</el-descriptions-item>
          <el-descriptions-item label="主体类型">{{ detailRow.subject_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="统一信用代码">{{ detailRow.unified_social_credit_code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="企业性质">{{ detailRow.enterprise_nature || '-' }}</el-descriptions-item>
          <el-descriptions-item label="行业分类" :span="2">{{ detailRow.industry_classification_gb || '-' }}</el-descriptions-item>
          <el-descriptions-item label="省份">{{ detailRow.affiliated_province || '-' }}</el-descriptions-item>
          <el-descriptions-item label="地市">{{ detailRow.affiliated_city || '-' }}</el-descriptions-item>
          <el-descriptions-item label="区县">{{ detailRow.affiliated_county_town || '-' }}</el-descriptions-item>
          <el-descriptions-item label="业务日期">{{ detailRow.biz_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="数据日期">{{ detailRow.data_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="签署日期">{{ detailRow.sign_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="大类规则">{{ detailRow.rule_large || '-' }}</el-descriptions-item>
          <el-descriptions-item label="中类规则">{{ detailRow.rule_medium || '-' }}</el-descriptions-item>
          <el-descriptions-item label="小类规则">{{ detailRow.rule_small || '-' }}</el-descriptions-item>
          <el-descriptions-item label="母行分类" :span="2">{{ detailRow.parent_bank_classify_queue_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="母行管户">{{ detailRow.parent_bank_monitor_manager_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="财子管户">{{ detailRow.wealth_child_monitor_manager_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="金租管户" :span="2">{{ detailRow.financial_lease_monitor_manager_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="投资额度">{{ detailRow.is_approved_investment_quota_client || '-' }}</el-descriptions-item>
          <el-descriptions-item label="合作准入">{{ detailRow.is_partner_access_client || '-' }}</el-descriptions-item>
          <el-descriptions-item label="母行否决">{{ detailRow.is_parent_bank_veto_client || '-' }}</el-descriptions-item>
          <el-descriptions-item label="批次 ID">
            <code>{{ detailRow._batch_id || '-' }}</code>
            <el-button
              v-if="detailRow._batch_id"
              type="text"
              size="mini"
              @click="applyBatchFilter(detailRow._batch_id); detailVisible = false;"
            >仅看此批次</el-button>
          </el-descriptions-item>
          <el-descriptions-item label="导入时间">{{ detailRow._imported_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="信号描述" :span="2">
            <div class="signal-text">{{ detailRow.signal_dascribe || '-' }}</div>
          </el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">完整 JSON</el-divider>
        <pre class="json-block">{{ detailJson }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import * as echarts from 'echarts';
import {
  querySubjectRiskRecords,
  getSubjectRiskStats,
  getSubjectRiskDistinct
} from '@/api/subjectRisk';

const LEVEL_TYPE_MAP = {
  红: 'danger',
  橙: 'warning',
  黄: 'warning',
  蓝: 'info',
  绿: 'success',
  信息提示类: 'info'
};

export default {
  name: 'SubjectRiskQueryPanel',
  props: {
    overview: { type: Object, default: () => ({}) }
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
      levelChart: null,
      provinceChart: null
    };
  },
  computed: {
    detailJson() {
      return this.detailRow ? JSON.stringify(this.detailRow, null, 2) : '';
    }
  },
  watch: {
    overview: {
      handler() {
        this.$nextTick(() => this.renderCharts());
      },
      deep: true
    }
  },
  async mounted() {
    this.fetchEnumOptions();
    await this.reload();
    window.addEventListener('resize', this.handleResize);
    this.$nextTick(() => this.renderCharts());
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.handleResize);
    this.disposeCharts();
  },
  activated() {
    this.$nextTick(() => {
      if (this.levelChart) this.levelChart.resize();
      if (this.provinceChart) this.provinceChart.resize();
    });
  },
  methods: {
    levelTagType(level) {
      if (!level) return 'info';
      for (const key of Object.keys(LEVEL_TYPE_MAP)) {
        if (String(level).includes(key)) return LEVEL_TYPE_MAP[key];
      }
      return 'info';
    },
    /** 风险等级：兼容别名键 */
    rowRiskLevel(row) {
      if (!row) return '';
      const v =
        row.risk_signal_level ||
        row['风险等级'] ||
        row.RISK_SIGNAL_LEVEL ||
        row.signal_level;
      return v != null && String(v).trim() ? String(v).trim() : '';
    },
    rowSubjectName(row) {
      if (!row) return '';
      const v =
        row.subject_name ||
        row['主体名称'] ||
        row.SUBJECT_NAME ||
        row.subjectName ||
        row['客户名称'];
      return v != null && String(v).trim() ? String(v).trim() : '';
    },
    rowClassName({ row }) {
      const lv = this.rowRiskLevel(row) || '';
      if (lv.includes('红')) return 'row-level-red';
      if (lv.includes('橙')) return 'row-level-orange';
      if (lv.includes('黄')) return 'row-level-yellow';
      return '';
    },
    async fetchEnumOptions() {
      try {
        const [lv, prov, nat] = await Promise.all([
          getSubjectRiskDistinct('risk_signal_level'),
          getSubjectRiskDistinct('affiliated_province'),
          getSubjectRiskDistinct('enterprise_nature')
        ]);
        const levelVals = (lv.data || lv || {}).values || [];
        this.levelOptions = levelVals.map(v => ({ value: v, label: v }));
        this.provinceOptions = (prov.data || prov || {}).values || [];
        this.natureOptions = (nat.data || nat || {}).values || [];
      } catch (e) {
        // 静默
      }
    },
    buildQueryPayload() {
      const [bs, be] = this.dateRange || [];
      return {
        page: this.page,
        page_size: this.pageSize,
        keyword: this.filter.keyword?.trim() || null,
        risk_signal_level: this.filter.risk_signal_level?.length
          ? this.filter.risk_signal_level
          : null,
        unified_social_credit_code:
          this.filter.unified_social_credit_code?.trim() || null,
        affiliated_province: this.filter.affiliated_province || null,
        enterprise_nature: this.filter.enterprise_nature || null,
        batch_id: this.filter.batch_id || null,
        biz_date_start: bs || null,
        biz_date_end: be || null,
        sort_by: '_imported_at',
        sort_desc: true
      };
    },
    async reload() {
      this.loading = true;
      try {
        const payload = this.buildQueryPayload();
        Object.keys(payload).forEach(k => {
          if (payload[k] === null || payload[k] === '') delete payload[k];
        });
        const res = await querySubjectRiskRecords(payload);
        const data = res.data || res || {};
        this.rows = data.items || [];
        this.total = data.total || 0;
      } catch (e) {
        this.rows = [];
        this.total = 0;
      } finally {
        this.loading = false;
      }
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
    async refreshCharts() {
      try {
        const res = await getSubjectRiskStats();
        const data = res.data || res || {};
        this.$emit('overview-update', data);
        this.renderCharts(data);
      } catch (e) {
        // 静默
      }
    },
    renderCharts(overrideData) {
      const data = overrideData || this.overview || {};
      this.renderLevelChart(data.risk_signal_level || []);
      this.renderProvinceChart(data.affiliated_province_top10 || []);
    },
    disposeCharts() {
      if (this.levelChart && !this.levelChart.isDisposed()) this.levelChart.dispose();
      if (this.provinceChart && !this.provinceChart.isDisposed()) this.provinceChart.dispose();
      this.levelChart = null;
      this.provinceChart = null;
    },
    renderLevelChart(items) {
      const dom = this.$refs.levelChart;
      if (!dom) return;
      if (!this.levelChart) this.levelChart = echarts.init(dom);
      const colors = items.map(i => {
        const lv = i.label || '';
        if (lv.includes('红')) return '#F56C6C';
        if (lv.includes('橙')) return '#E6A23C';
        if (lv.includes('黄')) return '#F7D257';
        if (lv.includes('蓝') || lv.includes('信息')) return '#409EFF';
        if (lv.includes('绿')) return '#67C23A';
        return '#909399';
      });
      this.levelChart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { bottom: 4, type: 'scroll' },
        series: [
          {
            name: '风险等级',
            type: 'pie',
            radius: ['38%', '68%'],
            center: ['50%', '45%'],
            avoidLabelOverlap: true,
            itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
            label: { show: true, formatter: '{b}\n{c}' },
            data: items.map((it, idx) => ({
              name: it.label,
              value: it.value,
              itemStyle: { color: colors[idx] }
            }))
          }
        ]
      }, true);
      this.levelChart.resize();
    },
    renderProvinceChart(items) {
      const dom = this.$refs.provinceChart;
      if (!dom) return;
      if (!this.provinceChart) this.provinceChart = echarts.init(dom);
      const labels = items.map(i => i.label);
      const values = items.map(i => i.value);
      this.provinceChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { top: 20, bottom: 24, left: 80, right: 16 },
        xAxis: { type: 'value' },
        yAxis: {
          type: 'category',
          data: labels,
          inverse: true,
          axisLabel: { interval: 0, fontSize: 11 }
        },
        series: [
          {
            type: 'bar',
            data: values,
            itemStyle: {
              color: {
                type: 'linear',
                x: 0, y: 0, x2: 1, y2: 0,
                colorStops: [
                  { offset: 0, color: '#3a7bd5' },
                  { offset: 1, color: '#00d2ff' }
                ]
              },
              borderRadius: [0, 4, 4, 0]
            },
            label: { show: true, position: 'right', fontSize: 11 },
            barWidth: 14
          }
        ]
      }, true);
      this.provinceChart.resize();
    },
    handleResize() {
      if (this.levelChart && !this.levelChart.isDisposed()) this.levelChart.resize();
      if (this.provinceChart && !this.provinceChart.isDisposed()) this.provinceChart.resize();
    },
    exportCurrentPage() {
      if (!this.rows.length) {
        this.$message.warning('当前页无数据');
        return;
      }
      const cols = [
        'risk_signal_level', 'subject_name', 'unified_social_credit_code',
        'subject_type', 'enterprise_nature', 'industry_classification_gb',
        'rule_large', 'rule_medium', 'rule_small', 'signal_dascribe',
        'affiliated_province', 'affiliated_city', 'affiliated_county_town',
        'biz_date', 'sign_date', 'risk_id', '_batch_id'
      ];
      const escape = v => {
        if (v == null) return '';
        const s = String(v);
        if (s.includes(',') || s.includes('"') || s.includes('\n')) {
          return '"' + s.replace(/"/g, '""') + '"';
        }
        return s;
      };
      const lines = [cols.join(',')];
      this.rows.forEach(r => {
        lines.push(cols.map(c => escape(r[c])).join(','));
      });
      const blob = new Blob(['\ufeff' + lines.join('\n')], {
        type: 'text/csv;charset=utf-8;'
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `subject_risk_page${this.page}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  }
};
</script>

<style scoped>
.query-panel {
  padding: 4px;
}
.filter-card,
.chart-card,
.table-card {
  border: 1px solid #ebeef5;
  margin-bottom: 16px;
}
.filter-form .el-form-item {
  margin-bottom: 12px;
}
.filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.total-badge {
  margin-left: auto;
  font-size: 13px;
  color: #606266;
}
.total-badge strong {
  color: #409EFF;
  font-weight: 600;
}
.charts-row {
  margin-bottom: 0;
}
.chart {
  width: 100%;
  height: 280px;
}
.pagination-wrap {
  margin-top: 14px;
  text-align: right;
}
.empty {
  padding: 30px 0;
  text-align: center;
}
.muted { color: #909399; }
.row-level-red { background-color: rgba(245, 108, 108, 0.08) !important; }
.row-level-orange { background-color: rgba(230, 162, 60, 0.08) !important; }
.row-level-yellow { background-color: rgba(247, 210, 87, 0.12) !important; }
.detail-content {
  padding: 16px;
  max-height: calc(100vh - 80px);
  overflow: auto;
}
.json-block {
  background: #f7f9fc;
  padding: 12px;
  font-size: 12px;
  font-family: Menlo, Monaco, Consolas, monospace;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 360px;
  overflow: auto;
}
.signal-text {
  white-space: pre-wrap;
  line-height: 1.6;
}
</style>
