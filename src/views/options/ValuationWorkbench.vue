<template>
  <div class="workbench">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <div class="toolbar-field">
          <span class="toolbar-label">估值日期</span>
          <el-date-picker
            v-model="valDate"
            type="date"
            value-format="yyyy-MM-dd"
            placeholder="选择日期"
            size="small"
            style="width: 150px;"
          />
        </div>
        <div class="toolbar-field" v-if="versions.length > 0">
          <span class="toolbar-label">当前版本</span>
          <el-select v-model="selectedVersion" size="small" style="width: 130px;" @change="handleVersionChange">
            <el-option v-for="v in versions" :key="v.version" :value="v.version">
              <span>v{{ v.version }}</span>
              <el-tag v-if="v.is_final" size="mini" type="success" effect="dark" style="margin-left: 6px;">最终版</el-tag>
              <span style="float: right; color: #909399; font-size: 12px;">{{ formatTime(v.run_at) }}</span>
            </el-option>
          </el-select>
        </div>
      </div>
      <div class="toolbar-right">
        <el-button size="small" type="primary" icon="el-icon-video-play" @click="handleRun" :loading="running">运行估值</el-button>
        <el-button size="small" icon="el-icon-check" @click="handleConfirm" :disabled="!canConfirm">确认最终版</el-button>
        <el-button v-if="versions.length > 1" size="small" :type="showVersionPanel ? 'info' : 'default'" plain @click="showVersionPanel = !showVersionPanel">
          版本记录 ({{ versions.length }})
        </el-button>
      </div>
    </div>

    <!-- 警告信息 -->
    <div v-if="snapshot && snapshot.warnings && snapshot.warnings.length" class="warnings">
      <el-alert
        v-for="(w, i) in snapshot.warnings"
        :key="'w'+i"
        :title="w.product_id + ': ' + w.message"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 6px;"
      />
    </div>

    <!-- 主内容区 -->
    <div class="main-area">
      <!-- 估值结果表格 -->
      <div class="table-area">
        <vxe-table
          v-if="snapshot"
          ref="valTable"
          :data="snapshot.products || []"
          :loading="running"
          border
          stripe
          :height="tableHeight"
          :scroll-y="{enabled: true, gt: 0}"
          show-overflow="title"
          :expand-config="{trigger: 'row', accordion: true}"
          @expand-change="handleExpand"
        >
          <vxe-column type="expand" width="46">
            <template #content="{ row }">
              <div class="expand-panel">
                <div class="expand-row">
                  <div class="expand-section">
                    <div class="expand-section-title">条款参数</div>
                    <el-descriptions :column="2" border size="mini">
                      <el-descriptions-item label="本金">{{ formatNum(row.principal) }}</el-descriptions-item>
                      <el-descriptions-item label="标的">{{ row.underlying }}</el-descriptions-item>
                      <el-descriptions-item label="状态">
                        <el-tag size="mini" :type="row.status === 'active' ? 'success' : 'info'">{{ row.status }}</el-tag>
                      </el-descriptions-item>
                      <el-descriptions-item label="定价方法">{{ methodLabel(row.method) }}</el-descriptions-item>
                    </el-descriptions>
                  </div>
                  <div class="expand-section">
                    <div class="expand-section-title">市场参数</div>
                    <el-descriptions :column="3" border size="mini">
                      <el-descriptions-item label="现价">{{ row.spot ? row.spot.toFixed(2) : '-' }}</el-descriptions-item>
                      <el-descriptions-item label="波动率">{{ row.vol ? (row.vol * 100).toFixed(1) + '%' : '-' }}</el-descriptions-item>
                    </el-descriptions>
                  </div>
                </div>
                <div class="expand-row" v-if="expandScenarios[row.product_id]">
                  <div class="expand-section" style="width: 100%;">
                    <div class="expand-section-title">情景分析</div>
                    <vxe-table :data="expandScenarios[row.product_id]" border stripe size="mini" max-height="180">
                      <vxe-column field="name" title="情景" width="140" />
                      <vxe-column field="price" title="估值" width="120" align="right">
                        <template #default="{ row: s }">{{ formatNum(s.price) }}</template>
                      </vxe-column>
                      <vxe-column field="change" title="变动" width="120" align="right">
                        <template #default="{ row: s }">
                          <span :class="s.change >= 0 ? 'val-positive' : 'val-negative'">
                            {{ s.change >= 0 ? '+' : '' }}{{ formatNum(s.change) }}
                          </span>
                        </template>
                      </vxe-column>
                      <vxe-column field="change_pct" title="变动%" width="90" align="right">
                        <template #default="{ row: s }">
                          <span :class="s.change_pct >= 0 ? 'val-positive' : 'val-negative'">
                            {{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct.toFixed(2) }}%
                          </span>
                        </template>
                      </vxe-column>
                    </vxe-table>
                  </div>
                </div>
                <div class="expand-row" v-else>
                  <el-button type="text" size="small" @click="loadScenario(row)" :loading="expandLoading[row.product_id]">
                    <i class="el-icon-data-analysis"></i> 加载情景分析
                  </el-button>
                </div>
              </div>
            </template>
          </vxe-column>
          <vxe-column field="product_id" title="产品编号" width="120" />
          <vxe-column field="name" title="名称" min-width="140" />
          <vxe-column field="type" title="类型" width="80">
            <template #default="{ row }">
              <el-tag size="mini">{{ typeLabel(row.type) }}</el-tag>
            </template>
          </vxe-column>
          <vxe-column field="principal" title="本金" min-width="120" align="right">
            <template #default="{ row }">{{ formatNum(row.principal) }}</template>
          </vxe-column>
          <vxe-column field="price_total" title="估值" min-width="130" align="right">
            <template #default="{ row }">
              <span :class="['val-cell', row.error ? 'val-error' : (row.price_total >= row.principal ? 'val-positive' : 'val-warning')]">
                {{ formatNum(row.price_total) }}
              </span>
            </template>
          </vxe-column>
          <vxe-column field="fixed_part" title="固收部分" min-width="115" align="right">
            <template #default="{ row }">{{ formatNum(row.fixed_part) }}</template>
          </vxe-column>
          <vxe-column field="option_part" title="期权部分" min-width="110" align="right">
            <template #default="{ row }">{{ formatNum(row.option_part) }}</template>
          </vxe-column>
          <vxe-column field="delta" title="Delta" min-width="85" align="right">
            <template #default="{ row }">{{ row.delta ? row.delta.toFixed(4) : '-' }}</template>
          </vxe-column>
          <vxe-column field="gamma" title="Gamma" min-width="90" align="right">
            <template #default="{ row }">{{ row.gamma ? row.gamma.toFixed(6) : '-' }}</template>
          </vxe-column>
          <vxe-column field="vega" title="Vega" min-width="85" align="right">
            <template #default="{ row }">{{ row.vega ? row.vega.toFixed(4) : '-' }}</template>
          </vxe-column>
          <vxe-column field="theta" title="Theta" min-width="85" align="right">
            <template #default="{ row }">{{ row.theta ? row.theta.toFixed(4) : '-' }}</template>
          </vxe-column>
          <vxe-column field="method" title="方法" min-width="110">
            <template #default="{ row }">
              <el-tag size="mini" type="info">{{ methodLabel(row.method) }}</el-tag>
            </template>
          </vxe-column>
          <vxe-column field="error" title="状态" width="70">
            <template #default="{ row }">
              <i v-if="!row.error" class="el-icon-success" style="color: #67c23a; font-size: 16px;"></i>
              <el-tooltip v-else :content="row.error" placement="top">
                <i class="el-icon-warning" style="color: #f56c6c; font-size: 16px;"></i>
              </el-tooltip>
            </template>
          </vxe-column>
        </vxe-table>

        <!-- 空状态 -->
        <div v-if="!snapshot && !running" class="empty-state">
          <div class="empty-icon"><i class="el-icon-data-board"></i></div>
          <div class="empty-title">选择日期并运行估值</div>
          <div class="empty-hint">系统将自动对所有存续产品执行日终估值</div>
          <el-button type="primary" size="small" style="margin-top: 16px;" @click="handleRun" :loading="running">
            <i class="el-icon-video-play"></i> 运行估值
          </el-button>
        </div>
      </div>

      <!-- 版本记录面板（右侧浮层） -->
      <transition name="slide">
        <div v-if="showVersionPanel && versions.length > 1" class="version-panel">
          <div class="version-panel-header">
            <span>版本记录</span>
            <i class="el-icon-close" @click="showVersionPanel = false" style="cursor: pointer;"></i>
          </div>
          <div class="version-panel-body">
            <div
              v-for="v in versions"
              :key="v.version"
              :class="['version-item', { active: v.version === selectedVersion, final: v.is_final }]"
              @click="handleVersionChange(v.version)"
            >
              <div class="version-item-top">
                <span class="version-item-label">v{{ v.version }}</span>
                <el-tag v-if="v.is_final" size="mini" type="success" effect="dark">最终版</el-tag>
              </div>
              <div class="version-item-time">{{ formatTime(v.run_at) }}</div>
              <div class="version-item-stats">
                <span>{{ v.snapshot.total_products }} 只</span>
                <span class="version-item-value">{{ formatNum(v.snapshot.total_value) }}</span>
              </div>
              <div class="version-item-bar">
                <div class="version-item-bar-success" :style="{ width: successPct(v) + '%' }"></div>
                <div class="version-item-bar-error" :style="{ width: errorPct(v) + '%' }"></div>
              </div>
            </div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script>
import {
  runValuation, getValuationSnapshot, getValuationVersions,
  getValuationVersionDetail, confirmValuationVersion, runRiskAnalysis
} from '@/api/optionPricing';

const TYPE_MAP = {
  fixed: '固收', binary: '二元', spread: '价差', sharkfin: '鲨鱼鳍',
  snowball: '雪球', phoenix: '凤凰', double_barrier: '双鲨',
  asian: '亚式', rainbow: '彩虹', range_accrual: '区间累积',
  callable_fixed: '可赎回', digital_range: '数字区间',
  american_option: '美式期权', fd_option: 'PDE期权', local_vol_option: '局部波动率'
};
const METHOD_MAP = {
  analytic: '解析解', monte_carlo: '蒙特卡洛', fixed_income: '固收折现',
  hybrid: '混合', discount: '折现', binary_analytic: '二元解析',
  spread_analytic: '价差解析', sharkfin_analytic: '鲨鱼鳍解析',
  snowball_mc: '雪球MC', phoenix_mc: '凤凰MC', double_barrier_mc: '双鲨MC',
  asian_geometric_analytic: '亚式几何', asian_arithmetic_mc: '亚式算术MC',
  rainbow_best_of_mc: '彩虹MC', range_accrual_mc: '区间累积MC',
  callable_fixed_binomial: '可赎回二叉树', digital_range_analytic: '数字区间解析',
  knocked_out: '已敲出', matured: '已到期', skipped: '跳过', expired: '已过期',
  binomial_american_call: '二叉树美式看涨', binomial_american_put: '二叉树美式看跌',
  binomial_european_call: '二叉树欧式看涨', binomial_european_put: '二叉树欧式看跌',
  fd_crank_nicolson_european_call: 'CN欧式看涨', fd_crank_nicolson_european_put: 'CN欧式看跌',
  fd_crank_nicolson_american_call: 'CN美式看涨', fd_crank_nicolson_american_put: 'CN美式看跌',
  local_vol_fd: '局部波动率FD', local_vol_fallback_bs: '局部波动率BS回退'
};

export default {
  name: 'ValuationWorkbench',
  data() {
    return {
      valDate: new Date().toISOString().slice(0, 10),
      running: false,
      snapshot: null,
      versions: [],
      selectedVersion: null,
      expandScenarios: {},
      expandLoading: {},
      showVersionPanel: false,
    };
  },
  computed: {
    canConfirm() {
      return this.snapshot && this.selectedVersion && !this.versions.some(v => v.is_final && v.version === this.selectedVersion);
    },
    currentIsFinal() {
      return this.versions.some(v => v.is_final && v.version === this.selectedVersion);
    },
    tableHeight() {
      return 580;
    }
  },
  watch: {
    valDate() {
      this.loadVersions();
    }
  },
  created() {
    this.loadVersions();
  },
  methods: {
    async loadVersions() {
      if (!this.valDate) return;
      try {
        const res = await getValuationVersions(this.valDate);
        this.versions = (res.data && res.data.data) || res.data || [];
        if (this.versions.length > 0) {
          const finalV = this.versions.find(v => v.is_final);
          this.selectedVersion = finalV ? finalV.version : this.versions[0].version;
          await this.loadSnapshotByVersion(this.selectedVersion);
        } else {
          this.snapshot = null;
          this.selectedVersion = null;
        }
      } catch (e) {
        this.versions = [];
      }
    },
    async loadSnapshotByVersion(version) {
      try {
        const res = await getValuationVersionDetail(this.valDate, version);
        this.snapshot = (res.data && res.data.data) || res.data;
        this.expandScenarios = {};
      } catch (e) {
        this.snapshot = null;
      }
    },
    handleVersionChange(version) {
      this.selectedVersion = version;
      this.loadSnapshotByVersion(version);
    },
    async handleRun() {
      if (!this.valDate) {
        this.$message.warning('请选择估值日期');
        return;
      }
      this.running = true;
      this.snapshot = null;
      try {
        const res = await runValuation({ date: this.valDate });
        const data = (res.data && res.data.data) || res.data;
        if (data && data.error) {
          this.$message.error('估值未执行：' + data.error);
          this.snapshot = data;
          return;
        }
        this.snapshot = data;
        const s = data.success_count != null ? data.success_count : 0;
        const f = data.error_count != null ? data.error_count : 0;
        this.$message.success(`估值完成：成功 ${s}，失败 ${f}`);
        this.loadVersions();
      } catch (e) {
        this.$message.error('估值运行失败: ' + (e.message || e));
      } finally {
        this.running = false;
      }
    },
    async handleConfirm() {
      if (!this.valDate || !this.selectedVersion) return;
      try {
        await confirmValuationVersion(this.valDate, this.selectedVersion);
        this.$message.success(`已确认 v${this.selectedVersion} 为最终版`);
        this.loadVersions();
      } catch (e) {
        this.$message.error('确认失败: ' + (e.message || e));
      }
    },
    async handleExpand() {},
    async loadScenario(row) {
      this.$set(this.expandLoading, row.product_id, true);
      try {
        const res = await runRiskAnalysis({
          date: this.valDate, run_scenario: true, run_stress: false, run_pnl: false,
        });
        const data = (res.data && res.data.data) || res.data;
        if (data && data.scenario) {
          const scenarios = [];
          const keyScenarios = ['spot_+10%', 'spot_-10%', 'spot_-20%', 'vol_+20%', 'vol_-20%'];
          for (const name of keyScenarios) {
            if (data.scenario[name] && data.scenario[name][row.product_id]) {
              const s = data.scenario[name][row.product_id];
              scenarios.push({
                name: name.replace('spot_', '标的').replace('vol_', '波动率'),
                price: s.price, change: s.change, change_pct: s.change_pct,
              });
            }
          }
          this.$set(this.expandScenarios, row.product_id, scenarios);
        }
      } catch (e) {
        this.$message.error('情景分析加载失败');
      } finally {
        this.$set(this.expandLoading, row.product_id, false);
      }
    },
    successPct(v) {
      const total = v.snapshot.total_products || 1;
      return ((v.snapshot.success_count || 0) / total * 100).toFixed(0);
    },
    errorPct(v) {
      const total = v.snapshot.total_products || 1;
      return ((v.snapshot.error_count || 0) / total * 100).toFixed(0);
    },
    formatTime(t) {
      if (!t) return '-';
      return t.replace('T', ' ').slice(0, 19);
    },
    typeLabel(t) { return TYPE_MAP[t] || t; },
    methodLabel(m) { return METHOD_MAP[m] || m || '-'; },
    formatNum(n) {
      return n != null ? n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-';
    },
  }
};
</script>

<style scoped>
.workbench { display: flex; flex-direction: column; height: 100%; }

/* ── 工具栏 ── */
.toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0 0 12px 0; border-bottom: 1px solid #ebeef5; margin-bottom: 12px;
}
.toolbar-left { display: flex; align-items: center; gap: 20px; }
.toolbar-right { display: flex; align-items: center; gap: 8px; }
.toolbar-field { display: flex; align-items: center; gap: 8px; }
.toolbar-label { font-size: 13px; color: #606266; font-weight: 500; white-space: nowrap; }

/* ── 警告 ── */
.warnings { margin-bottom: 8px; }

/* ── 主内容 ── */
.main-area { position: relative; flex: 1; min-height: 0; }
.table-area { width: 100%; }

/* ── 空状态 ── */
.empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 80px 0; color: #909399;
}
.empty-icon { font-size: 48px; color: #dcdfe6; margin-bottom: 12px; }
.empty-title { font-size: 15px; color: #606266; margin-bottom: 4px; }
.empty-hint { font-size: 13px; }

/* ── 展开面板 ── */
.expand-panel { padding: 12px 16px; }
.expand-row { margin-bottom: 10px; }
.expand-row:last-child { margin-bottom: 0; }
.expand-section { margin-bottom: 10px; }
.expand-section-title {
  font-size: 12px; font-weight: 600; color: #909399;
  margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;
}

/* ── 数值颜色 ── */
.val-cell { font-weight: 600; }
.val-positive { color: #67c23a; }
.val-negative { color: #f56c6c; }
.val-warning { color: #e6a23c; }
.val-error { color: #f56c6c; }

/* ── 版本面板（浮层） ── */
.version-panel {
  position: absolute; top: 0; right: 0; z-index: 10;
  width: 280px;
  background: #fff; border: 1px solid #dcdfe6; border-radius: 4px;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.08);
  display: flex; flex-direction: column; max-height: 580px;
}
.version-panel-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; font-size: 14px; font-weight: 600; color: #303133;
  border-bottom: 1px solid #ebeef5;
}
.version-panel-body { flex: 1; overflow-y: auto; padding: 8px; }
.version-item {
  padding: 10px 12px; border-radius: 4px; cursor: pointer;
  margin-bottom: 6px; border: 1px solid #ebeef5; transition: all 0.2s;
}
.version-item:hover { border-color: #c0c4cc; }
.version-item.active { border-color: #409eff; background: #ecf5ff; }
.version-item.final { border-color: #67c23a; }
.version-item-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.version-item-label { font-weight: 600; font-size: 14px; color: #303133; }
.version-item-time { font-size: 11px; color: #909399; margin-bottom: 6px; }
.version-item-stats {
  display: flex; justify-content: space-between; font-size: 12px; color: #606266;
  margin-bottom: 6px;
}
.version-item-value { font-weight: 600; color: #303133; }
.version-item-bar {
  height: 3px; background: #f0f2f5; border-radius: 2px;
  display: flex; overflow: hidden;
}
.version-item-bar-success { background: #67c23a; transition: width 0.3s; }
.version-item-bar-error { background: #f56c6c; transition: width 0.3s; }

/* ── 滑入动画 ── */
.slide-enter-active, .slide-leave-active { transition: all 0.3s ease; }
.slide-enter, .slide-leave-to { transform: translateX(20px); opacity: 0; }
</style>