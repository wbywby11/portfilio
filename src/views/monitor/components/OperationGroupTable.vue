<template>
  <div class="operation-group-table">
    <div v-if="!latestOp" class="group-empty">暂无指令记录</div>

    <template v-else>
      <!-- ================= 最新指令：目标仓位（核心展示区） ================= -->
      <div v-if="showLatest" class="latest-op">
        <div class="latest-op__header">
          <span class="latest-op__title">最新指令</span>
          <el-tag :type="opTypeTagType(latestOp.op_type)" size="mini" effect="plain">
            {{ opTypeLabel(latestOp.op_type) }}
          </el-tag>
          <span class="latest-op__date">
            信号日 {{ latestOp.signal_date }}
            <template v-if="latestOp.execute_date && latestOp.execute_date !== latestOp.signal_date">
              → 执行日 {{ latestOp.execute_date }}
            </template>
          </span>
          <el-tag
            v-if="latestOp.status === 'pending' && latestOp.execute_date"
            :type="countdownTagType(latestOp.execute_date)"
            size="mini"
            class="latest-op__countdown">
            {{ countdownText(latestOp.execute_date) }}
          </el-tag>
          <el-tag :type="statusTagType(latestOp.status)" size="mini">
            {{ statusLabel(latestOp.status) }}
          </el-tag>
          <span class="latest-op__source">{{ latestOp.source === 'subjective' ? '主观' : '系统' }}</span>
          <el-button
            v-if="latestOp.status === 'pending' && latestOp.source === 'auto'"
            type="text"
            size="small"
            class="latest-op__optimize"
            @click="$emit('optimize', latestOp)">
            优化比例
          </el-button>
        </div>

        <div v-if="suggestionText(latestOp)" class="latest-op__suggestion">
          <i class="el-icon-info"></i> {{ suggestionText(latestOp) }}
        </div>

        <div v-if="latestOp.remark" class="latest-op__remark">
          <i class="el-icon-chat-dot-square"></i> {{ latestOp.remark }}
        </div>

        <!-- 计算逻辑说明：一句话说清仓位怎么来的 -->
        <div class="logic-explain">
          <template v-if="group.strategy_key === 'portfolio' && latestBreakdownOp">
            <span class="logic-explain__formula">
              组合仓位 = Σ（策略内仓位 × 策略占组合比重）
            </span>
            <span class="logic-explain__divider">|</span>
            <span class="logic-explain__label">当前策略比重：</span>
            <el-tag
              v-for="b in latestBreakdownOp.strategy_breakdown"
              :key="b.strategy_key"
              size="mini"
              effect="plain"
              class="logic-explain__tag">
              {{ b.strategy_name || b.strategy_key }} {{ formatPct(b.weight) }}
            </el-tag>
            <span class="logic-explain__total" :class="leverageWarnClass(strategyTotal(latestBreakdownOp))">
              合计 {{ formatPct(strategyTotal(latestBreakdownOp)) }}
              <template v-if="strategyTotal(latestBreakdownOp) > 1.00001">
                （等效杠杆 {{ strategyTotal(latestBreakdownOp).toFixed(2) }}x）
              </template>
            </span>
          </template>
          <template v-else-if="latestOp.source === 'subjective'">
            <span class="logic-explain__formula">目标仓位 = 人工指定权重</span>
          </template>
          <template v-else>
            <span class="logic-explain__formula">目标仓位 = 策略模型直接输出的资产目标权重</span>
          </template>
        </div>

        <!-- 组合指令看板：子策略 → 资产 两级树形，金额按模拟规模实时换算 -->
        <div class="trade-toolbar">
          <span class="trade-toolbar__label">模拟管理规模（元）</span>
          <el-input-number
            v-model="simScale"
            :min="10000"
            :step="1000000"
            :precision="0"
            size="small"
            controls-position="right"
            class="trade-toolbar__scale" />
          <el-checkbox v-model="showZeroRows" class="trade-toolbar__check">显示零仓位</el-checkbox>
          <span class="trade-toolbar__spacer"></span>
          <el-button type="text" size="small" @click="toggleAllExpand">
            {{ allExpanded ? '收起全部' : '展开全部' }}
          </el-button>
          <el-button
            type="primary"
            size="small"
            plain
            icon="el-icon-download"
            :disabled="!dashboardRows.length"
            @click="exportTradeSheet">
            导出交易单
          </el-button>
        </div>

        <StandardTable
          ref="dashboardTable"
          :data="dashboardRows"
          :columns="dashboardColumns"
          :tree-config="dashboardTreeConfig"
          row-key="rowKey">
          <template #name="{ row }">
            <div v-if="row.rowType === 'strategy'" class="tree-strategy">
              <span class="tree-strategy__name">{{ row.name }}</span>
              <el-tag v-if="row.manual" size="mini" type="danger" effect="plain">
                人工指定
              </el-tag>
            </div>
            <div v-else class="asset-cell">
              <span class="asset-cell__name">{{ row.name }}</span>
              <span v-if="row.name !== row.code" class="asset-cell__code">{{ row.code }}</span>
            </div>
          </template>
          <template #action="{ row }">
            <el-tag
              v-if="row.rowType === 'asset' && row.action"
              :type="actionTagType(row.action)"
              size="mini"
              effect="plain">
              {{ actionLabel(row.action) }}
            </el-tag>
            <span v-else class="logic-muted">--</span>
          </template>
          <template #price="{ row }">
            <span v-if="row.rowType === 'strategy'" class="logic-muted">--</span>
            <span v-else-if="row.price == null" class="logic-muted">{{ row.noPrice ? '无行情' : '--' }}</span>
            <span v-else class="price-cell">
              <span class="price-cell__value">{{ formatPrice(row.price) }}</span>
              <span class="price-cell__date">{{ row.priceDate }}</span>
            </span>
          </template>
          <template #amount="{ row }">
            <span v-if="row.changeAmount == null" class="logic-muted">--</span>
            <span v-else class="num-cell" :class="signedClass(row.changeAmount)">
              {{ formatAmount(row.changeAmount) }}
            </span>
          </template>
          <template #qty="{ row }">
            <span v-if="row.changeQty == null" class="logic-muted">--</span>
            <span v-else class="num-cell" :class="signedClass(row.changeQty)">
              {{ formatQty(row.changeQty) }}
            </span>
          </template>
        </StandardTable>

        <div class="trade-footer">
          <span class="trade-footer__item">
            总仓位 {{ formatPct(exposureTotal(latestOp)) }}
            <template v-if="exposureTotal(latestOp) > 1.00001">
              （等效杠杆 {{ exposureTotal(latestOp).toFixed(2) }}x）
            </template>
          </span>
          <span class="trade-footer__divider">|</span>
          <span class="trade-footer__item trade-footer__item--buy">买入 {{ formatAmount(tradeTotals.buy) }}</span>
          <span class="trade-footer__item trade-footer__item--sell">卖出 {{ formatAmount(-tradeTotals.sell) }}</span>
          <span class="trade-footer__item">净额 {{ formatAmount(tradeTotals.net) }}</span>
          <div class="trade-footer__hint">
            金额 = 穿透权重变动 × 模拟规模；数量按预估价格向下取整到 100 股/份
          </div>
          <div v-if="hasMissingBaseline" class="trade-footer__hint trade-footer__hint--warn">
            部分资产无法归属变动基准（旧指令未存上一调仓日拆解且资产被多个策略持有），重跑监控后补齐
          </div>
        </div>
      </div>

      <!-- ================= 历史指令（默认折叠） ================= -->
      <div v-if="showHistory && historyOps.length" class="history-section">
        <div class="history-toggle" @click="toggleHistory">
          <span class="history-toggle__title">{{ historyTitle }}</span>
          <i
            :class="historyExpanded ? 'el-icon-arrow-up' : 'el-icon-arrow-down'"
            class="history-toggle__arrow"></i>
        </div>
        <!-- 历史指令表：列定义由配置驱动，展开详情/状态列均通过插槽渲染 -->
        <StandardTable
          v-show="historyExpanded"
          ref="historyTable"
          class="history-table"
          :data="historyOps"
          :columns="historyColumns"
          row-key="_id"
          :max-height="360">
          <template #expand="{ row }">
            <OperationOpDetail
              :op="row"
              :baseline-weights="baselineWeights(row)"
              :asset-label-resolver="assetLabelResolver" />
          </template>
          <template #group="{ row }">{{ row.__groupLabel || '—' }}</template>
          <template #opType="{ row }">
            <el-tag :type="opTypeTagType(row.op_type)" size="mini" effect="plain">
              {{ opTypeLabel(row.op_type) }}
            </el-tag>
          </template>
          <template #exposure="{ row }">
            <template v-if="totalWeightInfo(row.target_weights)">
              <span>{{ totalWeightInfo(row.target_weights).pct }}%</span>
              <el-tag
                v-if="totalWeightInfo(row.target_weights).leverage"
                type="warning"
                size="mini"
                class="leverage-tag">
                ×{{ totalWeightInfo(row.target_weights).leverage }}
              </el-tag>
            </template>
            <span v-else class="logic-muted">—</span>
          </template>
          <template #status="{ row }">
            <el-tag :type="statusTagType(row.status)" size="mini">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
          <template #source="{ row }">
            <span class="logic-muted">{{ row.source === 'subjective' ? '主观' : '系统' }}</span>
          </template>
          <template #remark="{ row }">
            <span v-if="row.remark">{{ row.remark }}</span>
            <span v-else class="logic-muted">—</span>
          </template>
          <template #actions="{ row }">
            <el-button
              v-if="row.status === 'executed'"
              type="text"
              size="mini"
              @click="openRemarkDialog(row)">
              {{ row.remark ? '编辑说明' : '补充说明' }}
            </el-button>
            <span v-else class="logic-muted">—</span>
          </template>
        </StandardTable>
      </div>
    </template>

    <!-- 补充说明弹窗（仅已执行指令） -->
    <el-dialog
      title="补充说明"
      :visible.sync="remarkVisible"
      width="480px"
      append-to-body
      :close-on-click-modal="false">
      <div v-if="remarkOp" class="remark-body">
        <p class="remark-hint">
          {{ opTypeLabel(remarkOp.op_type) }} · 信号日 {{ remarkOp.signal_date }}
          → 执行日 {{ remarkOp.execute_date }}
        </p>
        <el-input
          type="textarea"
          v-model="remarkText"
          :rows="4"
          maxlength="500"
          show-word-limit
          placeholder="记录该指令的执行情况、人工干预原因或事后说明（清空可删除已有备注）" />
      </div>
      <span slot="footer">
        <el-button @click="remarkVisible = false">取消</el-button>
        <el-button type="primary" :loading="remarkSubmitting" @click="submitRemark">保存</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import dayjs from 'dayjs';
import OperationOpDetail from './OperationOpDetail.vue';
import StandardTable from '@/components/monitor/StandardTable.vue';
import { buildDashboardColumns, buildHistoryColumns } from '@/config/monitor';
import { updateOperationRemark } from '@/api/monitor';
import { buildTradeSheetRows, downloadTradeSheet } from '@/utils/tradeSheet';

export default {
  name: 'OperationGroupTable',
  components: { OperationOpDetail, StandardTable },
  props: {
    group: { type: Object, required: true },
    groupLabel: { type: String, default: '' },
    /** 策略上下文：列定义按 template_code / ui_schema 动态扩展 */
    strategyContext: { type: Object, default: null },
    /** 当前持仓目标权重（小数形式），仅作待执行指令的「调整前」基准 */
    currentWeights: { type: Object, default: () => ({}) },
    /** 资产键 → 展示名函数 */
    assetLabelResolver: { type: Function, default: c => c },
    /**
     * 资产键 → { name, price, price_date }，来自 /operations 的 asset_meta。
     * 名称全局共享一份（组合下的子策略资产名不在 strategyContext 里）；
     * 价格只作交易单预估单价，后端不落金额。
     */
    assetMeta: { type: Object, default: () => ({}) },
    /** 统一模式：历史表含多分组指令（显示「所属策略」列） */
    unified: { type: Boolean, default: false },
    /** 是否显示最新指令卡片 */
    showLatest: { type: Boolean, default: true },
    /** 是否显示历史指令区 */
    showHistory: { type: Boolean, default: true },
    /** 历史指令区标题 */
    historyTitle: { type: String, default: '历史指令' },
    maxHeight: { type: [Number, String], default: 420 }
  },
  data() {
    return {
      historyExpanded: false,
      /** 模拟管理规模（元）：金额与数量在前端按此现算，不请求后端 */
      simScale: 10000000,
      /** 目标权重与变动都为 0 的资产默认不显示，减少干扰 */
      showZeroRows: false,
      allExpanded: true,
      dashboardTreeConfig: { childrenField: 'children', expandAll: true },
      // 补充说明
      remarkVisible: false,
      remarkSubmitting: false,
      remarkOp: null,
      remarkText: ''
    };
  },
  computed: {
    /** 按执行日（无则信号日）降序排列的全部指令 */
    sortedOps() {
      return (this.group.operations || []).slice().sort((a, b) =>
        String(b.execute_date || b.signal_date || '').localeCompare(String(a.execute_date || a.signal_date || ''))
      );
    },
    /** 最新指令：目标仓位展示的基准 */
    latestOp() {
      return this.sortedOps[0] || null;
    },
    /** 历史指令：普通模式为最新一条之外；统一模式下全部行均为历史 */
    historyOps() {
      return this.unified ? this.sortedOps : this.sortedOps.slice(1);
    },
    /** 组合指令看板列：配置驱动（策略内/穿透权重、动作、金额、数量） */
    dashboardColumns() {
      return buildDashboardColumns(this.strategyContext);
    },
    /** 树形看板数据：第一层子策略，第二层资产 */
    dashboardRows() {
      return this.latestOp ? this.buildDashboardTree(this.latestOp) : [];
    },
    /** 买入/卖出总额，用于表尾汇总（金额尺度随 simScale 实时变化） */
    tradeTotals() {
      let buy = 0;
      let sell = 0;
      this.dashboardRows.forEach(group => {
        (group.children || []).forEach(asset => {
          const amount = Number(asset.changeAmount);
          if (!Number.isFinite(amount)) return;
          if (amount > 0) buy += amount;
          else if (amount < 0) sell += -amount;
        });
      });
      return { buy, sell, net: buy - sell };
    },
    /** 存在无法归属变动基准的资产（旧指令未存上一调仓日拆解且资产跨策略重叠） */
    hasMissingBaseline() {
      return this.dashboardRows.some(group =>
        (group.children || []).some(asset => asset.changeWeight == null)
      );
    },
    /** 历史指令表列：配置驱动，统一模式自动带「所属策略」列 */
    historyColumns() {
      return buildHistoryColumns(this.strategyContext, { unified: this.unified });
    },
    /** 最近一条含策略权重拆解的指令（组合层计算逻辑说明的数据来源） */
    latestBreakdownOp() {
      if (this.group.strategy_key !== 'portfolio') return null;
      return this.sortedOps.find(o => o.strategy_breakdown && o.strategy_breakdown.length) || null;
    }
  },
  methods: {
    /**
     * 组装「子策略 → 资产」两级看板树。
     *
     * 数据源是组合层指令自带的 strategy_breakdown（策略占比 × 策略内资产权重）；
     * 无拆解的指令（单策略监控、组合层人工指定）退化为单策略行，
     * 资产行的策略内权重置空（界面显示 --）。
     */
    buildDashboardTree(op) {
      const breakdown = (op.strategy_breakdown || []).filter(Boolean);
      if (!breakdown.length) {
        return this.buildSingleLayerTree(op);
      }

      const baseline = this.baselineWeights(op);
      const prevBreakdown = op.prev_strategy_breakdown || [];
      const prevByKey = {};
      prevBreakdown.forEach(b => {
        if (b && b.strategy_key) prevByKey[String(b.strategy_key)] = b;
      });

      // 同一资产可能被多个子策略持有：旧指令缺上一调仓日拆解时，
      // 穿透后的 prev_weights 无法拆回各策略，只能对这种重叠资产留空
      const assetUseCount = {};
      breakdown.forEach(b => {
        Object.keys(b.asset_weights || {}).forEach(code => {
          assetUseCount[code] = (assetUseCount[code] || 0) + 1;
        });
      });

      const groups = breakdown.map(b => {
        const key = String(b.strategy_key);
        const stratW = Number(b.weight) || 0;
        const assetWeights = b.asset_weights || {};
        const prevB = prevByKey[key];
        // 只有上一调仓日的策略内权重也有数据时才能按策略归位；
        // 空对象不等于「全部卖出」，当缺失处理，否则会把整组误报成清仓/建仓
        const prevAssetMap = prevB ? (prevB.asset_weights || {}) : {};
        const hasPrevBreakdown = Object.keys(prevAssetMap).length > 0;
        const prevAssetWeights = hasPrevBreakdown ? prevAssetMap : null;
        const prevStratW = hasPrevBreakdown ? (Number(prevB.weight) || 0) : null;

        const codes = new Set([
          ...Object.keys(assetWeights),
          ...Object.keys(prevAssetWeights || {})
        ]);

        const children = [];
        codes.forEach(code => {
          const strategyWeight = Number(assetWeights[code]) || 0;
          const targetWeight = stratW * strategyWeight;
          let prevTargetWeight = null;
          if (prevAssetWeights) {
            prevTargetWeight = (prevStratW || 0) * (Number(prevAssetWeights[code]) || 0);
          } else if (assetUseCount[code] === 1) {
            // 该资产只属于本策略，穿透后的基准可直接归过来
            prevTargetWeight = Number(baseline[code]) || 0;
          }
          children.push(this.buildAssetRow(code, key, {
            strategyWeight,
            targetWeight,
            prevTargetWeight
          }));
        });

        return {
          rowKey: `S:${key}`,
          rowType: 'strategy',
          name: b.strategy_name || key,
          manual: false,
          strategyWeight: null,
          targetWeight: stratW,
          changeWeight: null,
          action: null,
          price: null,
          priceDate: '',
          changeAmount: null,
          changeQty: null,
          children: this.filterDashboardRows(children)
        };
      });

      return groups
        .filter(g => g.children.length > 0)
        .sort((a, b) => Number(b.targetWeight) - Number(a.targetWeight));
    },
    /**
     * 无两级拆解时的退化形态：一个策略行 + 其下资产行。
     *
     * 单策略监控的 target_weights 本身就是穿透权重（组合只有这一个策略）；
     * 组合层人工指定同理，只知穿透后资产权重，无法归属到具体子策略。
     */
    buildSingleLayerTree(op) {
      const target = op.target_weights || {};
      const baseline = this.baselineWeights(op);
      const codes = new Set([...Object.keys(target), ...Object.keys(baseline)]);

      const children = [];
      codes.forEach(code => {
        children.push(this.buildAssetRow(code, '__single__', {
          strategyWeight: null,
          targetWeight: Number(target[code]) || 0,
          prevTargetWeight: Number(baseline[code]) || 0
        }));
      });

      const rows = this.filterDashboardRows(children)
        .sort((a, b) => Number(b.targetWeight) - Number(a.targetWeight));
      if (!rows.length) return [];

      return [{
        rowKey: 'S:__single__',
        rowType: 'strategy',
        name: op.source === 'subjective'
          ? '组合层（人工指定）'
          : (this.groupLabel || '当前策略'),
        manual: op.source === 'subjective',
        strategyWeight: null,
        targetWeight: this.sumWeights(target),
        changeWeight: null,
        action: null,
        price: null,
        priceDate: '',
        changeAmount: null,
        changeQty: null,
        children: rows
      }];
    },
    /** 单个资产行：权重 → 金额 → 数量（金额与数量只在前端算，后端不落库） */
    buildAssetRow(code, groupKey, { strategyWeight, targetWeight, prevTargetWeight }) {
      const changeWeight = prevTargetWeight == null
        ? null
        : targetWeight - prevTargetWeight;
      const changeAmount = changeWeight == null ? null : changeWeight * this.simScale;
      const quote = this.assetMeta[code] || {};
      const price = quote.price == null ? null : Number(quote.price);
      const changeQty = this.calcQty(changeAmount, price);

      return {
        // 同一资产可被多个子策略持有，行键必须带策略前缀，否则树形展开状态会串行
        rowKey: `A:${groupKey}:${code}`,
        rowType: 'asset',
        code,
        name: this.resolveAssetName(code),
        strategyWeight,
        targetWeight,
        changeWeight,
        action: changeWeight == null || Math.abs(changeWeight) <= 1e-9
          ? 'hold'
          : (changeWeight > 0 ? 'buy' : 'sell'),
        price,
        priceDate: quote.price_date || '',
        noPrice: price == null,
        changeAmount,
        changeQty
      };
    },
    /** 数量向下取整到 100 股/份；无行情价格时不给数量（不用 0 兜底） */
    calcQty(amount, price) {
      if (amount == null || !price || price <= 0) return null;
      const units = Math.floor(Math.abs(amount) / price / 100) * 100;
      return amount < 0 ? -units : units;
    },
    /** 零仓位且零变动默认隐藏（可在工具栏打开） */
    filterDashboardRows(rows) {
      if (this.showZeroRows) return rows;
      return rows.filter(row => {
        const tw = Math.abs(Number(row.targetWeight) || 0);
        const cw = row.changeWeight == null ? 0 : Math.abs(Number(row.changeWeight));
        return tw > 1e-9 || cw > 1e-9;
      });
    },
    /** 资产展示名：优先接口 asset_meta，回退策略上下文映射，最后用代码 */
    resolveAssetName(code) {
      const meta = this.assetMeta[code];
      if (meta && meta.name) return meta.name;
      const label = this.assetLabelResolver(code);
      return label && label !== code ? label : code;
    },
    sumWeights(weights) {
      return Object.values(weights || {}).reduce((s, v) => s + (Number(v) || 0), 0);
    },
    /** 树形表全部展开/收起 */
    toggleAllExpand() {
      this.allExpanded = !this.allExpanded;
      const table = this.$refs.dashboardTable;
      if (table && typeof table.setAllExpand === 'function') {
        table.setAllExpand(this.allExpanded);
      }
    },
    /** 导出交易单：只含资产行，金额/数量口径与页面一致 */
    exportTradeSheet() {
      const op = this.latestOp;
      if (!op || !this.dashboardRows.length) {
        this.$message.warning('当前没有可导出的指令');
        return;
      }
      try {
        const result = downloadTradeSheet({
          rows: buildTradeSheetRows(this.dashboardRows),
          strategyLabel: this.groupLabel,
          executeDate: op.execute_date || op.signal_date,
          scale: this.simScale
        });
        this.$message.success(`已导出交易单：${result.row_count} 条资产`);
      } catch (e) {
        this.$message.error('导出失败：' + e.message);
      }
    },
    actionLabel(action) {
      const map = { buy: '买入', sell: '卖出', hold: '不变' };
      return map[action] || '';
    },
    actionTagType(action) {
      const map = { buy: 'danger', sell: 'success', hold: 'info' };
      return map[action] || 'info';
    },
    signedClass(v) {
      const n = Number(v);
      if (!Number.isFinite(n) || Math.abs(n) <= 1e-9) return 'num-flat';
      return n > 0 ? 'num-up' : 'num-down';
    },
    /** 金额千分位，带正负号 */
    formatAmount(v) {
      if (v == null || !Number.isFinite(Number(v))) return '--';
      const n = Number(v);
      const sign = n > 0 ? '+' : (n < 0 ? '-' : '');
      return sign + Math.abs(n).toLocaleString('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      });
    },
    /** 数量千分位，带正负号 */
    formatQty(v) {
      if (v == null || !Number.isFinite(Number(v))) return '--';
      const n = Number(v);
      const sign = n > 0 ? '+' : (n < 0 ? '-' : '');
      return sign + Math.abs(n).toLocaleString('zh-CN');
    },
    formatPrice(v) {
      const n = Number(v);
      return Number.isFinite(n) ? n.toFixed(3) : '--';
    },
    /**
     * 指令的「调整前」基准权重：
     * 1）已执行指令取执行前实际权重 prev_weights（执行日由推演回填）；
     * 2）待执行指令取当前实际持仓；
     * 3）历史指令缺 prev_weights 时，取同策略更早一条指令的目标权重。
     */
    baselineWeights(op) {
      const prev = op.prev_weights || {};
      if (Object.keys(prev).length) return prev;
      if (op.status === 'pending') return this.currentWeights || {};
      const sameStrategy = this.sortedOps.filter(o => o.strategy_key === op.strategy_key);
      const idx = sameStrategy.indexOf(op);
      const older = idx >= 0 ? sameStrategy[idx + 1] : null;
      if (older && older.target_weights && Object.keys(older.target_weights).length) {
        return older.target_weights;
      }
      return {};
    },
    /** 策略权重合计（组合层等效杠杆） */
    strategyTotal(op) {
      return (op.strategy_breakdown || []).reduce((s, b) => s + (Number(b.weight) || 0), 0);
    },
    /** 穿透资产目标权重合计（总敞口） */
    exposureTotal(op) {
      const tw = op.target_weights || {};
      return Object.values(tw).reduce((s, v) => s + (Number(v) || 0), 0);
    },
    totalWeightInfo(weights) {
      if (!weights || !Object.keys(weights).length) return null;
      const sum = Object.values(weights).reduce((a, b) => a + (Number(b) || 0), 0);
      return {
        pct: (sum * 100).toFixed(2),
        leverage: sum > 1.00001 ? sum.toFixed(2) : null
      };
    },
    leverageWarnClass(ratio) {
      return ratio > 1.00001 ? 'sum-bar--warn' : '';
    },
    suggestionText(op) {
      const s = op.suggestion || {};
      if (s.description) return s.description;
      const parts = [];
      if (s.vol_trigger != null) parts.push(`实时波动 ${(Number(s.vol_trigger) * 100).toFixed(2)}%`);
      if (s.scale_factor != null) parts.push(`缩放系数 ${Number(s.scale_factor).toFixed(4)}`);
      return parts.join('；');
    },
    openRemarkDialog(op) {
      this.remarkOp = op;
      this.remarkText = op.remark || '';
      this.remarkVisible = true;
    },
    async submitRemark() {
      const op = this.remarkOp;
      if (!op) return;
      this.remarkSubmitting = true;
      try {
        const res = await updateOperationRemark(op._id, this.remarkText);
        const body = res && res.data !== undefined ? res.data : res;
        op.remark = (body && body.remark) || '';
        this.$message.success(op.remark ? '补充说明已保存' : '补充说明已清除');
        this.remarkVisible = false;
        this.$emit('remark-updated', op);
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.detail) || e.message;
        this.$message.error('保存失败：' + msg);
      } finally {
        this.remarkSubmitting = false;
      }
    },
    formatPct(v) {
      if (v == null) return '—';
      return (Number(v) * 100).toFixed(2) + '%';
    },
    /** 历史区展开/收起：展开后重算表格布局，避免 v-show 初渲宽度为 0 */
    toggleHistory() {
      this.historyExpanded = !this.historyExpanded;
      if (this.historyExpanded) {
        this.$nextTick(() => {
          const table = this.$refs.historyTable;
          if (table && typeof table.resize === 'function') table.resize();
        });
      }
    },
    opTypeLabel(t) {
      const map = { monthly_rebalance: '月度调仓', vol_reset: '波动率重置', subjective: '主观调仓' };
      return map[t] || t || '—';
    },
    opTypeTagType(t) {
      const map = { monthly_rebalance: 'primary', vol_reset: 'warning', subjective: 'danger' };
      return map[t] || 'info';
    },
    statusLabel(s) {
      const map = { pending: '待执行', executed: '已执行', superseded: '已替代', cancelled: '已取消' };
      return map[s] || s || '—';
    },
    statusTagType(s) {
      const map = { pending: 'warning', executed: 'success', superseded: 'info', cancelled: 'info' };
      return map[s] || '';
    },
    countdownText(executeDate) {
      const days = dayjs(executeDate).startOf('day').diff(dayjs().startOf('day'), 'day');
      if (days < 0) return '已到期';
      if (days === 0) return '今日执行';
      return `${days} 天后执行`;
    },
    countdownTagType(executeDate) {
      const days = dayjs(executeDate).startOf('day').diff(dayjs().startOf('day'), 'day');
      if (days <= 0) return 'danger';
      if (days <= 2) return 'warning';
      return 'info';
    }
  }
};
</script>

<style scoped>
.operation-group-table {
  width: 100%;
}

.group-empty {
  padding: 16px 0;
  font-size: 13px;
  color: #909399;
}

/* ---------- 最新指令卡片 ---------- */
.latest-op {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 14px;
  background: #fff;
}

.latest-op__header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.latest-op__title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.latest-op__date {
  font-size: 13px;
  color: #606266;
}

.latest-op__countdown {
  margin: 0;
}

.latest-op__source {
  font-size: 12px;
  color: #909399;
}

.latest-op__optimize {
  margin-left: auto;
  padding: 0;
}

.latest-op__suggestion {
  font-size: 12px;
  color: #e6a23c;
  margin-bottom: 8px;
}

.latest-op__remark {
  font-size: 12px;
  color: #722ed1;
  margin-bottom: 8px;
}

/* ---------- 补充说明弹窗 ---------- */
.remark-hint {
  margin: 0 0 10px 0;
  font-size: 12px;
  color: #909399;
}

/* ---------- 计算逻辑说明条 ---------- */
.logic-explain {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 10px;
  margin-bottom: 10px;
  background: #f8f9fb;
  border-radius: 4px;
  font-size: 12px;
}

.logic-explain__formula {
  color: #303133;
  font-weight: 600;
}

.logic-explain__divider {
  color: #dcdfe6;
  margin: 0 2px;
}

.logic-explain__label {
  color: #606266;
}

.logic-explain__tag {
  margin: 0;
}

.logic-explain__total {
  color: #909399;
}

/* ---------- 仓位表（表格样式由 StandardTable 统一提供） ---------- */
/* ---------- 组合指令看板 ---------- */
.trade-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 0 10px 0;
}

.trade-toolbar__label {
  font-size: 12px;
  color: #606266;
}

.trade-toolbar__scale {
  width: 170px;
}

.trade-toolbar__check {
  margin-right: 0;
  font-size: 12px;
}

.trade-toolbar__spacer {
  flex: 1 1 auto;
}

/* 第一层：子策略汇总行 */
.tree-strategy {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #303133;
}

/* 第二层：资产行 */
.price-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.25;
}

.price-cell__value {
  font-variant-numeric: tabular-nums;
  color: #303133;
}

.price-cell__date {
  font-size: 11px;
  color: #909399;
}

.num-cell {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.num-up {
  color: #f56c6c;
}

.num-down {
  color: #67c23a;
}

.num-flat {
  color: #909399;
}

.trade-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 10px 2px 0 2px;
  font-size: 12px;
  color: #606266;
}

.trade-footer__item--buy {
  color: #f56c6c;
}

.trade-footer__item--sell {
  color: #67c23a;
}

.trade-footer__divider {
  color: #dcdfe6;
}

.trade-footer__hint {
  flex: 1 1 100%;
  font-size: 11px;
  color: #909399;
}

.trade-footer__hint--warn {
  color: #e6a23c;
}

.sum-bar {
  padding: 8px 2px 0 2px;
  font-size: 12px;
  color: #606266;
}

.sum-bar--warn {
  color: #e6a23c;
  font-weight: 600;
}

.asset-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.asset-cell__name {
  color: #303133;
}

.asset-cell__code {
  font-size: 11px;
  color: #909399;
}

.derivation-formulas {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
}

.derivation-formula b {
  color: #303133;
  font-weight: 600;
}

.logic-muted {
  font-size: 12px;
  color: #909399;
}

.history-section {
  margin-top: 16px;
  padding-top: 10px;
  border-top: 1px dashed #dcdfe6;
}

.history-toggle {
  display: flex;
  align-items: center;
  cursor: pointer;
  user-select: none;
  padding: 2px 0;
}

.history-toggle__title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.history-toggle__arrow {
  margin-left: 8px;
  color: #909399;
}

.history-toggle:hover .history-toggle__title {
  color: #409eff;
}

.history-table {
  margin-top: 8px;
}

.leverage-tag {
  margin-left: 4px;
}
</style>
