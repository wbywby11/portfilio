<template>
  <div class="page-container">
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">核算辅助</h2>
        <p class="page-desc">根据估值结果自动生成会计分录，支持日终盯市、敲出/到期结算、科目汇总与导出</p>
      </div>
      <div class="header-actions">
        <el-date-picker
          v-model="selectedDate"
          type="date"
          value-format="yyyy-MM-dd"
          placeholder="选择日期"
          style="width: 160px; margin-right: 8px;"
        />
        <el-button type="primary" icon="el-icon-document-add" @click="handleGenerate" :loading="generating">生成分录</el-button>
        <el-button icon="el-icon-download" @click="handleExport" :disabled="!entries.length">导出 Excel</el-button>
      </div>
    </div>

    <!-- 汇总卡片 -->
    <el-row :gutter="16" v-if="entries.length" class="stat-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">分录总数</div>
          <div class="stat-value">{{ entries.length }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">借方合计</div>
          <div class="stat-value">{{ formatNum(totalDebit) }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">贷方合计</div>
          <div class="stat-value">{{ formatNum(totalCredit) }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">涉及产品</div>
          <div class="stat-value">{{ productCount }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 分录表格 -->
    <vxe-table
      v-if="entries.length"
      :data="entries"
      border
      stripe
      height="400"
      :scroll-y="{enabled: true, gt: 0}"
      show-overflow="title"
    >
      <vxe-column field="date" title="日期" width="110" />
      <vxe-column field="product_id" title="产品编号" width="120" />
      <vxe-column field="entry_type" title="类型" width="120">
        <template #default="{ row }">
          <el-tag size="mini" :type="entryTypeColor(row.entry_type)">{{ entryTypeLabel(row.entry_type) }}</el-tag>
        </template>
      </vxe-column>
      <vxe-column field="debit_account" title="借方科目" width="200" />
      <vxe-column field="credit_account" title="贷方科目" width="200" />
      <vxe-column field="amount" title="金额" width="140" align="right">
        <template #default="{ row }">
          <span style="font-weight: 600;">{{ formatNum(row.amount) }}</span>
        </template>
      </vxe-column>
      <vxe-column field="description" title="摘要" min-width="200" show-overflow="title" />
    </vxe-table>

    <!-- 科目汇总 -->
    <el-collapse v-if="summary.length" style="margin-top: 16px;">
      <el-collapse-item title="按科目汇总">
        <vxe-table :data="summary" border stripe size="small" max-height="250">
          <vxe-column field="account" title="科目" width="250" />
          <vxe-column field="total_debit" title="借方合计" width="150" align="right">
            <template #default="{ row }">{{ formatNum(row.total_debit) }}</template>
          </vxe-column>
          <vxe-column field="total_credit" title="贷方合计" width="150" align="right">
            <template #default="{ row }">{{ formatNum(row.total_credit) }}</template>
          </vxe-column>
          <vxe-column field="net" title="净额" width="150" align="right">
            <template #default="{ row }">
              <span :style="{ color: row.net >= 0 ? '#67c23a' : '#f56c6c' }">{{ formatNum(row.net) }}</span>
            </template>
          </vxe-column>
          <vxe-column field="count" title="笔数" width="80" align="center" />
        </vxe-table>
      </el-collapse-item>
    </el-collapse>

    <el-empty v-if="!entries.length && !generating" description="选择日期并点击'生成分录'">
      <template slot="description">
        <p>系统将自动根据估值结果生成会计分录（日终盯市 + 事件结算）</p>
      </template>
    </el-empty>
  </div>
</template>

<script>
import { generateAccountingEntries, getAccountingEntries, getAccountingSummary, exportAccountingEntries } from '@/api/optionPricing';

const ENTRY_TYPE_MAP = {
  daily_mark: '日终盯市',
  knock_out_settlement: '敲出结算',
  maturity_settlement: '到期结算',
  coupon: '票息收入',
};

export default {
  name: 'AccountingAssist',
  data() {
    return {
      selectedDate: new Date().toISOString().slice(0, 10),
      generating: false,
      entries: [],
      summary: [],
    };
  },
  computed: {
    totalDebit() {
      return this.entries.reduce((sum, e) => sum + (e.amount || 0), 0);
    },
    totalCredit() {
      return this.entries.reduce((sum, e) => sum + (e.amount || 0), 0);
    },
    productCount() {
      return new Set(this.entries.map(e => e.product_id)).size;
    }
  },
  watch: {
    selectedDate() {
      this.loadEntries();
    }
  },
  created() {
    this.loadEntries();
  },
  methods: {
    async loadEntries() {
      if (!this.selectedDate) return;
      try {
        const res = await getAccountingEntries({ date: this.selectedDate });
        this.entries = (res.data && res.data.data) || res.data || [];
        if (this.entries.length) {
          await this.loadSummary();
        } else {
          this.summary = [];
        }
      } catch (e) {
        this.entries = [];
      }
    },
    async loadSummary() {
      try {
        const res = await getAccountingSummary(this.selectedDate);
        this.summary = (res.data && res.data.data) || res.data || [];
      } catch (e) {
        this.summary = [];
      }
    },
    async handleGenerate() {
      if (!this.selectedDate) {
        this.$message.warning('请选择日期');
        return;
      }
      this.generating = true;
      try {
        const res = await generateAccountingEntries(this.selectedDate);
        const data = (res.data && res.data.data) || res.data;
        if (data && data.error) {
          this.$message.error(data.error);
          return;
        }
        this.entries = data.entries || [];
        this.summary = data.summary || [];
        this.$message.success(`生成完成：共 ${data.total_entries} 条分录`);
      } catch (e) {
        this.$message.error('生成分录失败: ' + (e.message || e));
      } finally {
        this.generating = false;
      }
    },
    async handleExport() {
      try {
        const res = await exportAccountingEntries(this.selectedDate);
        const blob = new Blob([res.data || res], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `accounting_${this.selectedDate}.xlsx`;
        a.click();
        URL.revokeObjectURL(url);
        this.$message.success('导出成功');
      } catch (e) {
        this.$message.error('导出失败: ' + (e.message || e));
      }
    },
    entryTypeLabel(t) { return ENTRY_TYPE_MAP[t] || t; },
    entryTypeColor(t) {
      const map = { daily_mark: '', knock_out_settlement: 'warning', maturity_settlement: 'success', coupon: 'info' };
      return map[t] || '';
    },
    formatNum(n) {
      return n != null ? n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-';
    },
  }
};
</script>

<style scoped>
/* 基础样式（原第一套残留中仍被本页使用的部分；置于前，被下方同名规则覆盖，级联结果与修复前一致） */
.page-header { margin-bottom: 16px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; color: #303133; }
.page-desc { margin: 4px 0 0; color: #909399; font-size: 13px; }
.stat-card {
  background: #fff; border: 1px solid #ebeef5; border-radius: 4px;
  padding: 16px; text-align: center;
}
.stat-label { font-size: 12px; color: #909399; margin-bottom: 6px; }
.stat-value { font-size: 22px; font-weight: 600; color: #303133; }
/* 会计分录版样式（置于后，冲突时优先生效） */
.page-container { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.page-desc { margin: 4px 0 0; color: #909399; font-size: 13px; }
.stat-row { margin-bottom: 16px; }
.stat-card { text-align: center; }
.stat-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.stat-value { font-size: 20px; font-weight: 600; color: #303133; }
</style>
