<template>
  <div :class="{'asset-quote-container': !isDialog}">
    <el-card class="filter-card">
      <el-form :inline="true" :model="filterForm" size="small">
        <el-form-item label="选择资产">
          <el-select 
            v-model="selectedAsset" 
            filterable 
            placeholder="请选择资产" 
            @change="handleAssetChange"
            style="width: 250px"
          >
            <el-option
              v-for="(item, idx) in assetOptions"
              :key="'opt-' + idx + '-' + (item.id || '') + '-' + (item.code || '')"
              :label="`${item.name} (${item.code})`"
              :value="item.code"
            >
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="yyyy-MM-dd"
            @change="handleDateChange"
          >
          </el-date-picker>
        </el-form-item>
        <el-form-item label="价格精度">
          <el-select v-model="pricePrecision" placeholder="请选择" style="width: 120px">
            <el-option label="2位" :value="2"></el-option>
            <el-option label="4位" :value="4"></el-option>
            <el-option label="6位" :value="6"></el-option>
            <el-option label="8位" :value="8"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="Excel仅导入日">
          <el-date-picker
            v-model="excelOnlyDate"
            type="date"
            value-format="yyyy-MM-dd"
            placeholder="不选则导入全部行"
            clearable
            style="width: 160px;"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="el-icon-search" @click="fetchData">查询</el-button>
          <el-button type="success" icon="el-icon-refresh" @click="handleSyncToday">同步行情</el-button>
          <el-dropdown trigger="click" @command="handlePriceTemplateCommand">
            <el-button icon="el-icon-download">
              下载行情模板<i class="el-icon-arrow-down el-icon--right"></i>
            </el-button>
            <el-dropdown-menu slot="dropdown">
              <el-dropdown-item command="single_full">单资产：全列（含规模）</el-dropdown-item>
              <el-dropdown-item command="single_close">单资产：仅收盘价</el-dropdown-item>
              <el-dropdown-item command="single_open">单资产：仅开盘价</el-dropdown-item>
              <el-dropdown-item command="single_high">单资产：仅最高价</el-dropdown-item>
              <el-dropdown-item command="single_low">单资产：仅最低价</el-dropdown-item>
              <el-dropdown-item command="single_amount">单资产：仅成交额</el-dropdown-item>
              <el-dropdown-item command="single_volume">单资产：仅成交量</el-dropdown-item>
              <el-dropdown-item command="single_scale">单资产：仅规模</el-dropdown-item>
              <el-dropdown-item divided command="multi_close">多资产宽表：收盘价</el-dropdown-item>
              <el-dropdown-item command="multi_open">多资产宽表：开盘价</el-dropdown-item>
              <el-dropdown-item command="multi_high">多资产宽表：最高价</el-dropdown-item>
              <el-dropdown-item command="multi_low">多资产宽表：最低价</el-dropdown-item>
              <el-dropdown-item command="multi_amount">多资产宽表：成交额</el-dropdown-item>
              <el-dropdown-item command="multi_volume">多资产宽表：成交量</el-dropdown-item>
              <el-dropdown-item command="multi_scale">多资产宽表：规模</el-dropdown-item>
            </el-dropdown-menu>
          </el-dropdown>
          <el-upload
            ref="priceUpload"
            action=""
            :auto-upload="false"
            :show-file-list="false"
            :on-change="handlePriceFileChange"
            accept=".xlsx,.xls"
            style="display: inline-block; margin-left: 10px;"
          >
            <el-button icon="el-icon-upload2">批量导入行情</el-button>
          </el-upload>
          <el-form-item label="宽表列含义" class="multi-metric-form-item">
            <el-tooltip
              content="与「多资产Excel导入」解析一致：数值列写入该字段（按日合并）。非收盘价时须库中或本行已有有效收盘价，详见多资产弹窗说明。"
              placement="top"
            >
              <el-select v-model="multiImportMetric" size="small" style="width: 118px">
                <el-option label="收盘价" value="close" />
                <el-option label="开盘价" value="open" />
                <el-option label="最高价" value="high" />
                <el-option label="最低价" value="low" />
                <el-option label="成交额" value="amount" />
                <el-option label="成交量" value="volume" />
                <el-option label="规模" value="scale" />
              </el-select>
            </el-tooltip>
          </el-form-item>
          <el-upload
            ref="multiAssetUpload"
            action=""
            :auto-upload="false"
            :show-file-list="false"
            :on-change="handleMultiAssetFileChange"
            accept=".xlsx,.xls"
            style="display: inline-block; margin-left: 10px;"
          >
            <el-button type="warning" plain icon="el-icon-folder-add">多资产Excel导入</el-button>
          </el-upload>
        </el-form-item>
      </el-form>
    </el-card>

    <el-alert
      v-if="priceCoverage && priceCoverage.missing_dates && priceCoverage.missing_dates.length"
      type="warning"
      :closable="false"
      show-icon
      class="coverage-alert"
      style="margin-bottom: 16px;">
      <template slot="title">
        <span>区间内缺失 <strong>{{ priceCoverage.missing_dates.length }}</strong> 个交易日行情</span>
        <span class="coverage-meta">（日历：{{ priceCoverage.calendar_mode === 'trade_calendar' ? 'trade_dates.xlsx' : '工作日近似' }}）</span>
      </template>
      <div class="coverage-body">
        <span>应有交易日 {{ priceCoverage.expected_trade_days }} 天，库中已有 {{ priceCoverage.existing_days }} 天。</span>
        <span v-if="recentMissingDate" class="coverage-first">
          最近缺失：<el-button type="text" @click="applyMissingToManual(recentMissingDate)">{{ recentMissingDate }}</el-button>
        </span>
        <span v-if="priceCoverage.first_missing && priceCoverage.first_missing !== recentMissingDate" class="coverage-first">
          最早缺失：<el-button type="text" @click="applyMissingToManual(priceCoverage.first_missing)">{{ priceCoverage.first_missing }}</el-button>
        </span>
        <div class="coverage-dates">{{ missingDatesPreview }}</div>
      </div>
    </el-alert>

    <el-card v-if="selectedAsset" class="manual-import-card" shadow="never">
      <div slot="header" class="manual-import-header">
        <span>手动录入行情</span>
        <span class="manual-import-hint">
          <strong>收盘价</strong>为<strong class="manual-required-text">必填</strong>项，须填写且<strong>不可为 0 或留空</strong>；填写后开盘、最高、最低默认与收盘价一致，可单独修改。
        </span>
      </div>
      <el-form :inline="true" size="small" @submit.native.prevent="submitManualImport">
        <el-form-item label="日期" required>
          <el-date-picker
            v-model="manualForm.date"
            type="date"
            value-format="yyyy-MM-dd"
            placeholder="请选择交易日"
            style="width: 150px;"
          />
        </el-form-item>
        <el-form-item class="manual-close-form-item">
          <span slot="label" class="manual-close-label">
            收盘价
            <span class="manual-close-required-mark" title="必填，须大于 0">*</span>
          </span>
          <el-input-number
            v-model="manualForm.close"
            :precision="pricePrecision"
            :step="priceStep"
            controls-position="right"
            class="manual-price-input"
            placeholder="必填，大于 0"
            @change="onManualCloseChange"
          />
        </el-form-item>
        <el-form-item label="开盘">
          <el-input-number
            v-model="manualForm.open"
            :precision="pricePrecision"
            :step="priceStep"
            :min="0"
            controls-position="right"
            class="manual-price-input narrow"
            @change="markManualOpenEdited"
          />
        </el-form-item>
        <el-form-item label="最高">
          <el-input-number
            v-model="manualForm.high"
            :precision="pricePrecision"
            :step="priceStep"
            :min="0"
            controls-position="right"
            class="manual-price-input narrow"
            @change="markManualHighEdited"
          />
        </el-form-item>
        <el-form-item label="最低">
          <el-input-number
            v-model="manualForm.low"
            :precision="pricePrecision"
            :step="priceStep"
            :min="0"
            controls-position="right"
            class="manual-price-input narrow"
            @change="markManualLowEdited"
          />
        </el-form-item>
        <el-form-item label="成交量">
          <el-input-number
            v-model="manualForm.volume"
            :precision="0"
            :step="1"
            :min="0"
            controls-position="right"
            class="manual-vol-input"
          />
        </el-form-item>
        <el-form-item label="成交额">
          <el-input-number
            v-model="manualForm.amount"
            :precision="2"
            :step="0.01"
            :min="0"
            controls-position="right"
            class="manual-vol-input"
          />
        </el-form-item>
        <el-form-item label="规模">
          <el-input-number
            v-model="manualForm.scale"
            :precision="2"
            :step="0.01"
            :min="0"
            controls-position="right"
            class="manual-vol-input"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="manualSubmitting" @click="submitManualImport">保存该日行情</el-button>
          <el-button type="text" @click="setManualDateToday">设为今日</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 快捷删除某日行情 -->
    <el-card v-if="selectedAsset" class="manual-delete-card" shadow="never">
      <div class="delete-card-header">
        <div class="delete-card-title">
          <i class="el-icon-delete"></i>
          <span>删除某日 K 线行情</span>
          <span class="delete-card-hint">选择一个日期，删除该日该资产的单条行情记录</span>
        </div>
      </div>
      <div class="delete-card-body">
        <el-date-picker
          v-model="deletePriceDate"
          type="date"
          placeholder="选择需删除的日期"
          value-format="yyyy-MM-dd"
          class="delete-date-picker"
          :picker-options="deletePricePickerOptions"
          clearable
        />
        <el-button
          type="danger"
          icon="el-icon-delete"
          plain
          :loading="singleDeletingPrice"
          :disabled="!deletePriceDate"
          class="delete-confirm-btn"
          @click="handleDeletePriceByPicker"
        >
          删除该日行情
        </el-button>
        <el-tooltip content="跳到「行情明细」表可多选批量删除" placement="top">
          <el-button
            type="text"
            icon="el-icon-s-grid"
            @click="activeTab = 'table'"
          >
            表格批量删除
          </el-button>
        </el-tooltip>
      </div>
      <div class="delete-card-tip">
        <i class="el-icon-warning-outline"></i>
        提示：仅可选择当前表格中已存在的日期；删除后不可恢复，请谨慎操作
      </div>
    </el-card>

    <el-tabs v-model="activeTab" style="margin-top: 20px;" type="border-card">
      <el-tab-pane label="K线图" name="chart">
        <div ref="klineChart" style="width: 100%; height: 500px;" v-loading="loading"></div>
      </el-tab-pane>
      <el-tab-pane label="行情明细" name="table">
        <div class="quote-table-toolbar">
          <div class="toolbar-left">
            <el-tag size="medium" type="info" effect="plain">
              <i class="el-icon-document"></i>
              共 {{ quoteData.length }} 条
            </el-tag>
            <el-tag
              v-if="selectedQuoteRows.length"
              size="medium"
              type="warning"
              effect="plain"
              style="margin-left: 8px;"
            >
              <i class="el-icon-finished"></i>
              已选 {{ selectedQuoteRows.length }} 条
            </el-tag>
          </div>
          <div class="toolbar-right">
            <el-button
              size="small"
              type="danger"
              plain
              icon="el-icon-delete"
              :disabled="!selectedQuoteRows.length || !selectedAsset"
              :loading="batchDeleting"
              @click="handleBatchDeletePrices"
            >
              批量删除选中日期
            </el-button>
          </div>
        </div>
        <vxe-table
          ref="quoteTable"
          border
          stripe
          height="500"
          :loading="loading"
          :data="quoteData"
          :scroll-y="{enabled: true, gt: 0}"
          show-overflow="title"
          :checkbox-config="{ trigger: 'row', highlight: true, range: true }"
          @checkbox-all="handleQuoteSelectionChange"
          @checkbox-change="handleQuoteSelectionChange"
        >
          <vxe-column type="checkbox" width="46" align="center" fixed="left"></vxe-column>
          <vxe-column field="date" title="日期" sortable width="140" fixed="left"></vxe-column>
          <vxe-column field="open" title="开盘价" width="120">
            <template #default="{ row }">
              {{ row.open != null ? formatPrice(row.open) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="high" title="最高价" width="120">
            <template #default="{ row }">
              {{ row.high != null ? formatPrice(row.high) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="low" title="最低价" width="120">
            <template #default="{ row }">
              {{ row.low != null ? formatPrice(row.low) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="close" title="收盘价" width="120">
            <template #default="{ row }">
              <span :class="getPriceClass(row)">
                {{ row.close != null ? formatPrice(row.close) : '-' }}
              </span>
            </template>
          </vxe-column>
          <vxe-column field="volume" title="成交量" width="150">
            <template #default="{ row }">
              {{ row.volume != null ? formatVolume(row.volume) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="amount" title="成交额" width="150">
            <template #default="{ row }">
              {{ row.amount != null ? formatAmount(row.amount) : '-' }}
            </template>
          </vxe-column>
          <vxe-column field="scale" title="规模" width="150">
            <template #default="{ row }">
              {{ row.scale != null && row.scale !== '' ? formatAmount(row.scale) : '-' }}
            </template>
          </vxe-column>
          <vxe-column title="操作" width="110" fixed="right" align="center">
            <template #default="{ row }">
              <el-popconfirm
                :title="`确认删除 ${row.date} 的行情记录？`"
                confirm-button-text="确认删除"
                cancel-button-text="取消"
                confirm-button-type="danger"
                icon="el-icon-warning"
                icon-color="#f56c6c"
                @confirm="handleDeletePrice(row)"
              >
                <el-button
                  slot="reference"
                  type="text"
                  size="mini"
                  icon="el-icon-delete"
                  class="row-delete-btn"
                >
                  删除
                </el-button>
              </el-popconfirm>
            </template>
          </vxe-column>
        </vxe-table>
      </el-tab-pane>
    </el-tabs>

    <sync-progress-dialog ref="syncProgressDialog" @sync-success="handleSyncSuccess" />

    <el-dialog
      title="多资产行情导入"
      :visible.sync="multiAssetDialogVisible"
      width="95%"
      top="3vh"
      append-to-body
      :close-on-click-modal="false"
      @closed="onMultiAssetDialogClosed"
    >
      <div v-loading="multiAssetLoading" class="multi-asset-import-body">
        <p class="multi-asset-hint">
          支持两种宽表：<strong>Wind 类</strong>（约第 4 行名称、第 5 行代码、第 6 行起日期+数值）；
          <strong>基金/证券类</strong>（第 1 行「基金代码」+ 各列代码、第 2 行「基金名称」+ 各列名称、第 3 行起日期+数值）。
          另支持按 A 列连续日期自动对齐表头。请先选择「宽表列含义」再选文件，勾选资产并确认匹配后导入。
          「系统中无匹配」的资产可在导入时<strong>自动新建</strong>（与文件代码、名称一致）并写入行情；亦可先「批量新建所选无匹配资产」再导入。
          「仅代码一致」时可选择沿用已有（可选覆盖名称）或填写<strong>新资产代码</strong>新建一条并导入行情。
        </p>
        <el-form :inline="true" size="small" class="multi-asset-toolbar">
          <el-form-item label="导入模式">
            <el-radio-group v-model="multiImportMode" size="small">
              <el-radio-button label="merge">按日合并（重叠日更新 + 新日插入）</el-radio-button>
              <el-radio-button label="only_new">仅新增缺日（已有日期跳过）</el-radio-button>
              <el-radio-button label="replace">全量覆盖（先删该资产全部行情）</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="multiImportSubmitting" :disabled="!multiAssetRows.length" @click="submitMultiAssetImport">
              执行导入
            </el-button>
            <el-button
              type="success"
              plain
              :loading="multiBatchCreateLoading"
              :disabled="!multiAssetRows.length"
              @click="batchCreateSelectedNewAssets"
            >
              批量新建所选无匹配资产
            </el-button>
            <el-button @click="multiAssetDialogVisible = false">关 闭</el-button>
          </el-form-item>
        </el-form>
        <p class="multi-asset-mode-hint">
          <template v-if="multiImportMode === 'merge'">
            当前为<strong>按日合并</strong>：与库内同一交易日则更新该行，库中没有的日期则新增。下表「本次导入影响」按按日合并估算。
          </template>
          <template v-else-if="multiImportMode === 'only_new'">
            当前为<strong>仅新增缺日</strong>：库中<strong>已有</strong>的交易日整行跳过（不更新）；仅对<strong>尚无</strong>行情的日期插入。下表中「更新」类提示表示这些日在按日合并下会改库，本模式下将<strong>全部跳过</strong>。
          </template>
          <template v-else>
            当前为<strong>全量覆盖</strong>：会先删除该资产在库中的全部行情，再写入本次文件中的全部行。
          </template>
        </p>
        <p v-if="multiImportProgressLine" class="multi-import-live-progress">
          {{ multiImportProgressLine }}
        </p>
        <el-alert
          v-if="multiImportMetric !== 'close'"
          type="warning"
          :closable="false"
          show-icon
          class="multi-metric-anchor-alert"
          title="当前为「收盘价之外」的宽表列（补充字段）"
          description="须先完成对应交易日的收盘价导入：新日期必须在文件中提供大于 0 的收盘价才会入库；仅规模/成交额/成交量/OHLC 等时，对应日期在库中须已有有效收盘价，否则该行会被拒绝。缺少有效资产代码或名称的列不会出现在表中、也不会导入。"
        />
        <el-table
          :data="multiAssetRows"
          border
          stripe
          max-height="420"
          size="small"
          :row-key="multiAssetTableRowKey"
        >
          <el-table-column width="64" align="center">
            <template slot="header">
              <div class="multi-import-th" title="全选 / 取消全选">
                <el-checkbox
                  v-model="multiImportHeaderCheckModel"
                  :indeterminate="multiImportHeaderSelect.indeterminate"
                  :disabled="multiImportSubmitting"
                />
                <span class="multi-import-header-label">导入</span>
              </div>
            </template>
            <template slot-scope="{ row }">
              <el-checkbox v-model="row.selected" />
            </template>
          </el-table-column>
          <el-table-column prop="file_code" label="文件代码" min-width="110" show-overflow-tooltip />
          <el-table-column prop="file_name" label="文件名称" min-width="120" show-overflow-tooltip />
          <el-table-column label="匹配情况" min-width="200">
            <template slot-scope="{ row }">
              <el-tag :type="multiMatchTagType(row.match_kind)" size="mini">{{ multiMatchLabel(row.match_kind) }}</el-tag>
              <div v-if="row.match_kind === 'code_name_diff'" class="multi-asset-cell-sub">
                系统中名称：{{ row.system_name || '—' }}
              </div>
              <div v-if="row.match_kind === 'name_code_diff'" class="multi-asset-cell-sub">
                系统代码 {{ row.system_code }}（与文件代码不一致）
              </div>
              <div v-if="row.match_kind === 'name_ambiguous'" class="multi-asset-cell-sub warn">
                同名资产多条，请在下栏选择导入目标代码
              </div>
            </template>
          </el-table-column>
          <el-table-column label="将导入至" min-width="130">
            <template slot-scope="{ row }">
              <span v-if="row.match_kind === 'exact' || row.match_kind === 'new_asset'">
                {{ row.file_code }}
              </span>
              <span v-else-if="row.match_kind === 'code_name_diff'">
                <template v-if="row.codeDiffMode === 'new'">{{ (row.newAssetCode || '').trim() || '（请填写新代码）' }}</template>
                <template v-else>{{ row.file_code }}</template>
              </span>
              <template v-else-if="row.match_kind === 'name_code_diff'">
                <span>{{ row.importAsCode }}</span>
              </template>
              <el-select
                v-else-if="row.match_kind === 'name_ambiguous'"
                v-model="row.importAsCode"
                filterable
                size="mini"
                style="width: 100%"
                placeholder="选择系统代码"
                @change="onMultiImportTargetChange(row)"
              >
                <el-option
                  v-for="(c, cidx) in row.name_match_candidates"
                  :key="(row.file_code || '') + '-cand-' + cidx + '-' + (c.code || '')"
                  :label="`${c.name} (${c.code})`"
                  :value="c.code"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="文件行数" width="88" align="center">
            <template slot-scope="{ row }">{{ row.price_count }}</template>
          </el-table-column>
          <el-table-column label="文件日期范围" min-width="158">
            <template slot-scope="{ row }">
              <span v-if="row.date_min && row.date_max">{{ row.date_min }} ~ {{ row.date_max }}</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="库内已有行情" min-width="168">
            <template slot-scope="{ row }">
              <template v-if="row.import_preview && row.import_preview.existing_price_count">
                <div>{{ row.import_preview.existing_date_min }} ~ {{ row.import_preview.existing_date_max }}</div>
                <div class="multi-asset-cell-sub">共 {{ row.import_preview.existing_price_count }} 条</div>
              </template>
              <span v-else>无</span>
            </template>
          </el-table-column>
          <el-table-column label="本次导入影响" min-width="280">
            <template slot-scope="{ row }">
              <span class="multi-import-effect">{{ formatMultiImportEffect(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="仅代码一致时" min-width="220" align="left">
            <template slot-scope="{ row }">
              <template v-if="row.match_kind === 'code_name_diff'">
                <el-radio-group v-model="row.codeDiffMode" size="mini" class="multi-code-diff-rg">
                  <el-radio label="keep">沿用已有</el-radio>
                  <el-radio label="new">新建资产</el-radio>
                </el-radio-group>
                <div v-if="row.codeDiffMode === 'keep'" class="multi-asset-cell-sub">
                  <el-checkbox v-model="row.overwriteName">用文件名称覆盖系统名称</el-checkbox>
                </div>
                <div v-else class="multi-asset-cell-sub">
                  <el-input
                    v-model="row.newAssetCode"
                    size="mini"
                    clearable
                    placeholder="新资产代码（须不与已有重复）"
                  />
                </div>
              </template>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="确认绑定" width="100" align="center">
            <template slot-scope="{ row }">
              <el-checkbox
                v-if="row.match_kind === 'name_code_diff'"
                v-model="row.bindConfirmed"
              />
              <span v-else-if="row.match_kind === 'name_ambiguous'">{{ row.importAsCode ? '已选' : '—' }}</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" align="center" fixed="right">
            <template slot-scope="{ row, $index }">
              <el-button
                v-if="row.match_kind === 'new_asset'"
                type="text"
                size="mini"
                @click="openMultiAssetCreate($index)"
              >
                新建资产
              </el-button>
              <span v-else>—</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <el-dialog
      title="新建资产（多资产导入）"
      :visible.sync="multiAssetCreateVisible"
      width="640px"
      append-to-body
      :close-on-click-modal="false"
      @closed="multiAssetCreatePreset = null"
    >
      <asset-form
        v-if="multiAssetCreateVisible"
        :key="multiAssetFormKey"
        is-dialog
        :preset-create="multiAssetCreatePreset"
        @success="onMultiAssetCreateSuccess"
        @close="multiAssetCreateVisible = false"
      />
    </el-dialog>
  </div>
</template>

<script>
import {
  getAssetOptions,
  getAssetKline,
  downloadPriceTemplate,
  downloadMultiAssetPriceTemplate,
  importPricesFromExcel,
  importPricesJson,
  getPriceCoverageGaps,
  analyzeMultiAssetImport,
  importSingleAssetFromMulti,
  getPriceImportProgress,
  getMultiAssetRowPreviewStats,
  createAsset,
  deleteAssetPrice,
  deleteAssetPricesBatch
} from '@/api/asset';
import SyncProgressDialog from '@/components/SyncProgressDialog.vue';
import AssetForm from '@/views/asset/AssetForm.vue';
import {
  unwrapPriceImportProgressPayload,
  formatPriceImportProgressLine,
  PRICE_IMPORT_PROGRESS_POLL_MS
} from '@/utils/priceImportProgress';
import * as echarts from 'echarts';

export default {
  name: 'AssetQuote',
  components: { SyncProgressDialog, AssetForm },
  beforeDestroy() {
    this.stopMultiImportProgressPoll();
  },
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    assetCode: {
      type: String,
      default: ''
    },
    /** 外部传入的起始日期（YYYY-MM-DD）：仅在 isDialog 模式下生效，用于与调用方表格同源区间 */
    startDate: {
      type: String,
      default: ''
    },
    /** 外部传入的结束日期 */
    endDate: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      selectedAsset: '',
      assetOptions: [],
      dateRange: [],
      filterForm: {},
      activeTab: 'chart',
      loading: false,
      quoteData: [],
      chartInstance: null,
      pricePrecision: 2, // 价格精度，默认2位小数
      priceCoverage: null,
      excelOnlyDate: null,
      manualForm: {
        date: '',
        open: null,
        high: null,
        low: null,
        close: null,
        volume: null,
        amount: null,
        scale: null
      },
      manualSubmitting: false,
      /** 用户是否曾单独改过开/高/低；改过则不再随收盘价联动 */
      manualOhlcEdited: {
        open: false,
        high: false,
        low: false
      },
      multiAssetDialogVisible: false,
      multiAssetLoading: false,
      multiAssetRows: [],
      /** merge | only_new | replace */
      multiImportMode: 'merge',
      multiImportSubmitting: false,
      multiAssetCreateVisible: false,
      multiAssetCreatePreset: null,
      multiAssetFormKey: 0,
      multiAssetCreateRowIndex: -1,
      /** 多资产宽表每列数值映射到行情字段，与后端 metric 一致 */
      multiImportMetric: 'close',
      multiBatchCreateLoading: false,
      /** 当前单资产导入时由后端进度接口填充 */
      multiImportProgressLine: '',
      _multiImportProgressTimer: null,
      /** 进度轮询与当前导入请求绑定，忽略过期响应 */
      _multiImportPollProgressId: null,
      /** 行情明细表多选选中行（用于批量删除） */
      selectedQuoteRows: [],
      /** 单条/批量删除中状态标识 */
      batchDeleting: false,
      /** 快捷删除：选中的待删除日期 */
      deletePriceDate: '',
      /** 单日快捷删除中标识 */
      singleDeletingPrice: false
    };
  },
  computed: {
    missingDatesPreview() {
      const m = this.priceCoverage && this.priceCoverage.missing_dates;
      if (!m || !m.length) return '';
      const head = m.slice(0, 12);
      const tail = m.length > 12 ? ` … 共 ${m.length} 天` : '';
      return head.join('、') + tail;
    },
    /** 与「价格精度」联动，便于输入小数 */
    priceStep() {
      const p = Number(this.pricePrecision);
      const prec = Number.isFinite(p) ? Math.min(Math.max(p, 0), 8) : 2;
      return Math.pow(10, -prec);
    },
    /** 区间内时间顺序最后一个缺失日（与后端 last_missing 一致；兼容旧接口无该字段时从 missing_dates 推算） */
    recentMissingDate() {
      const p = this.priceCoverage;
      if (!p || !p.missing_dates || !p.missing_dates.length) return null;
      return p.last_missing || p.missing_dates[p.missing_dates.length - 1];
    },
    multiImportMetricLabel() {
      const m = {
        close: '收盘价',
        open: '开盘价',
        high: '最高价',
        low: '最低价',
        amount: '成交额',
        volume: '成交量',
        scale: '规模'
      };
      return m[this.multiImportMetric] || '收盘价';
    },
    /** 快捷删除日期选择器：仅允许当前 quoteData 中存在的日期 */
    deletePricePickerOptions() {
      const dateSet = new Set((this.quoteData || []).map((it) => it.date));
      return {
        disabledDate(date) {
          if (!date) return true;
          const y = date.getFullYear();
          const m = String(date.getMonth() + 1).padStart(2, '0');
          const d = String(date.getDate()).padStart(2, '0');
          return !dateSet.has(`${y}-${m}-${d}`);
        }
      };
    },
    /** 多资产表「导入」列表头：与明细勾选联动（双向绑定为三态） */
    multiImportHeaderSelect() {
      const rows = this.multiAssetRows || [];
      const n = rows.length;
      if (!n) return { checked: false, indeterminate: false };
      let sel = 0;
      for (let i = 0; i < n; i++) {
        if (rows[i].selected) sel++;
      }
      return {
        checked: sel === n && n > 0,
        indeterminate: sel > 0 && sel < n
      };
    },
    /** Element UI 2 单选框须 v-model；与表头三态、行 selected 同步 */
    multiImportHeaderCheckModel: {
      get() {
        return this.multiImportHeaderSelect.checked;
      },
      set(val) {
        const on = !!val;
        const rows = this.multiAssetRows || [];
        for (let i = 0; i < rows.length; i++) {
          this.$set(rows[i], 'selected', on);
        }
      }
    }
  },
  mounted() {
    this.initDateRange();
    this.fetchAssetOptions();
    // 弹窗模式：若调用方传入了 startDate/endDate，覆盖默认区间，使默认展示与调用方（如聊天表格）同源区间
    if (this.isDialog && this.startDate && this.endDate) {
      this.dateRange = [this.startDate, this.endDate];
    }
  },
  watch: {
    assetCode(newVal) {
      if (this.isDialog && newVal) {
        this.selectedAsset = newVal;
        this.manualForm.date = '';
        this.resetManualOhlcEdited();
        // 切换到新资产时，若仍携带外部区间则按该区间拉取，保证表格与弹窗区间一致
        if (this.startDate && this.endDate) {
          this.dateRange = [this.startDate, this.endDate];
        }
        this.fetchData();
      }
    },
    activeTab(val) {
      if (val === 'chart') {
        this.$nextTick(() => {
          if (this.chartInstance) {
            this.chartInstance.resize();
          }
        });
      }
    },
    'manualForm.date'(newVal, oldVal) {
      if (newVal === oldVal) return;
      this.resetManualOhlcEdited();
      this.$nextTick(() => this.syncOhlcFromClose());
    }
  },
  methods: {
    initDateRange() {
      const end = new Date();
      const start = new Date();
      start.setMonth(start.getMonth() - 6); // 默认看半年
      this.dateRange = [this.formatDate(start), this.formatDate(end)];
    },
    formatDate(date) {
      const y = date.getFullYear();
      let m = date.getMonth() + 1;
      m = m < 10 ? '0' + m : m;
      let d = date.getDate();
      d = d < 10 ? '0' + d : d;
      return `${y}-${m}-${d}`;
    },
    /** el-table 行唯一键：避免 file_code 重复或同代码多行时 DOM 复用错乱 */
    multiAssetTableRowKey(row) {
      const fc = (row && row.file_code) || '';
      const fn = (row && row.file_name) || '';
      const mk = (row && row.match_kind) || '';
      return `${fc}__${fn}__${mk}`;
    },
    async fetchAssetOptions() {
      try {
        const res = await getAssetOptions();
        const raw = res.data || res;
        const list = Array.isArray(raw) ? raw : [];
        const seen = new Set();
        this.assetOptions = list.filter((item) => {
          const c = item && String(item.code || '').trim();
          if (!c || seen.has(c)) return false;
          seen.add(c);
          return true;
        });
        
        // 优先使用 props 的 assetCode
        if (this.isDialog && this.assetCode) {
          this.selectedAsset = this.assetCode;
        } else {
          // 优先从路由参数获取 code，否则默认选第一个
          const queryCode = this.$route.query.code;
          if (queryCode && this.assetOptions.some(item => item.code === queryCode)) {
            this.selectedAsset = queryCode;
          } else if (this.assetOptions.length > 0) {
            this.selectedAsset = this.assetOptions[0].code;
          }
        }
        
        if (this.selectedAsset) {
          this.fetchData();
        }
      } catch (error) {
        this.$message.error('获取资产列表失败');
      }
    },
    handleAssetChange() {
      this.manualForm.date = '';
      this.resetManualOhlcEdited();
      this.fetchData();
    },
    handleDateChange() {
      this.fetchData();
    },
    handleSyncToday() {
      this.$refs.syncProgressDialog.openSyncToday();
    },
    handleSyncSuccess() {
      this.fetchData();
    },
    async fetchData() {
      if (!this.selectedAsset) return;
      this.loading = true;
      try {
        const params = {
          start_date: this.dateRange ? this.dateRange[0] : '',
          end_date: this.dateRange ? this.dateRange[1] : ''
        };
        const res = await getAssetKline(this.selectedAsset, params);
        const rawData = res.data || res;
        
        // 数据标准化：如果缺少 open/high/low，用 close 填充
        this.quoteData = rawData.map(item => ({
          date: item.date,
          open: item.open ?? item.close ?? 0,
          high: item.high ?? item.close ?? 0,
          low: item.low ?? item.close ?? 0,
          close: item.close ?? 0,
          volume: item.volume ?? 0,
          amount: item.amount ?? 0,
          scale: item.scale != null ? item.scale : null
        }));
        // 数据刷新后清空多选选中记录
        this.selectedQuoteRows = [];
        if (this.$refs.quoteTable && typeof this.$refs.quoteTable.clearCheckboxRow === 'function') {
          try { this.$refs.quoteTable.clearCheckboxRow(); } catch (e) { /* ignore */ }
        }
        
        this.renderChart();
        await this.fetchCoverageGaps();
      } catch (error) {
        this.$message.error('获取行情数据失败');
      } finally {
        this.loading = false;
      }
    },
    async fetchCoverageGaps() {
      if (!this.selectedAsset || !this.dateRange || this.dateRange.length !== 2) {
        this.priceCoverage = null;
        return;
      }
      try {
        const res = await getPriceCoverageGaps({
          asset_code: this.selectedAsset,
          start_date: this.dateRange[0],
          end_date: this.dateRange[1]
        });
        const body = res.data !== undefined ? res.data : res;
        this.priceCoverage = body || null;
        // 默认日期：区间内按 trade_dates（或工作日近似）得到的缺失日中，时间最晚的一天
        if (body && body.missing_dates && body.missing_dates.length && !this.manualForm.date) {
          const last =
            body.last_missing ||
            body.missing_dates[body.missing_dates.length - 1];
          if (last) this.manualForm.date = last;
        }
      } catch (e) {
        this.priceCoverage = null;
      }
    },
    applyMissingToManual(d) {
      this.manualForm.date = d;
      this.$message.success('已填入手动录入日期：' + d);
    },
    setManualDateToday() {
      const t = new Date();
      const y = t.getFullYear();
      const m = String(t.getMonth() + 1).padStart(2, '0');
      const da = String(t.getDate()).padStart(2, '0');
      this.manualForm.date = `${y}-${m}-${da}`;
    },
    resetManualOhlcEdited() {
      this.manualOhlcEdited = { open: false, high: false, low: false };
    },
    markManualOpenEdited() {
      if (this._syncingOhlcFromClose) return;
      this.manualOhlcEdited.open = true;
    },
    markManualHighEdited() {
      if (this._syncingOhlcFromClose) return;
      this.manualOhlcEdited.high = true;
    },
    markManualLowEdited() {
      if (this._syncingOhlcFromClose) return;
      this.manualOhlcEdited.low = true;
    },
    /** 收盘价变化时：未单独编辑过的开/高/低与收盘价保持一致 */
    onManualCloseChange(val) {
      if (val === null || val === undefined || val === '' || Number.isNaN(Number(val))) {
        return;
      }
      const c = Number(val);
      if (!Number.isFinite(c)) return;
      this._syncingOhlcFromClose = true;
      try {
        if (!this.manualOhlcEdited.open) this.$set(this.manualForm, 'open', c);
        if (!this.manualOhlcEdited.high) this.$set(this.manualForm, 'high', c);
        if (!this.manualOhlcEdited.low) this.$set(this.manualForm, 'low', c);
      } finally {
        this.$nextTick(() => {
          this._syncingOhlcFromClose = false;
        });
      }
    },
    syncOhlcFromClose() {
      const c = this.manualForm.close;
      if (c === null || c === undefined || c === '' || Number.isNaN(Number(c))) return;
      const n = Number(c);
      if (!Number.isFinite(n)) return;
      this._syncingOhlcFromClose = true;
      try {
        if (!this.manualOhlcEdited.open) this.$set(this.manualForm, 'open', n);
        if (!this.manualOhlcEdited.high) this.$set(this.manualForm, 'high', n);
        if (!this.manualOhlcEdited.low) this.$set(this.manualForm, 'low', n);
      } finally {
        this.$nextTick(() => {
          this._syncingOhlcFromClose = false;
        });
      }
    },
    async submitManualImport() {
      if (!this.selectedAsset) {
        this.$message.warning('请先选择资产');
        return;
      }
      if (!this.manualForm.date) {
        this.$message.warning('请选择日期');
        return;
      }
      const c = this.manualForm.close;
      if (c === null || c === undefined || c === '' || Number.isNaN(Number(c))) {
        this.$message.warning('请填写收盘价（不能为空）');
        return;
      }
      const close = Number(c);
      if (!Number.isFinite(close)) {
        this.$message.warning('收盘价格式不正确');
        return;
      }
      if (!(close > 0)) {
        this.$message.warning('收盘价须大于 0，不能为 0 或负数');
        return;
      }
      let open = this.manualForm.open;
      let high = this.manualForm.high;
      let low = this.manualForm.low;
      if (open === null || open === undefined || open === '') open = close;
      if (high === null || high === undefined || high === '') high = Math.max(close, Number(open));
      if (low === null || low === undefined || low === '') low = Math.min(close, Number(open));
      open = Number(open);
      high = Number(high);
      low = Number(low);
      const row = {
        date: this.manualForm.date,
        open,
        high,
        low,
        close,
        volume: this.manualForm.volume !== null && this.manualForm.volume !== '' ? Number(this.manualForm.volume) : undefined,
        amount: this.manualForm.amount !== null && this.manualForm.amount !== '' ? Number(this.manualForm.amount) : undefined,
        scale: this.manualForm.scale !== null && this.manualForm.scale !== '' ? Number(this.manualForm.scale) : undefined
      };
      this.manualSubmitting = true;
      try {
        const res = await importPricesJson({
          asset_code: this.selectedAsset,
          replace_existing: false,
          prices: [row]
        });
        const data = res && res.data !== undefined ? res.data : res;
        const inserted = data && data.inserted_count != null ? data.inserted_count : 0;
        const updated = data && data.updated_count != null ? data.updated_count : 0;
        const errCount = data && data.error_count != null ? data.error_count : 0;
        const errMsgs = (data && data.errors) || [];

        // 价格导入不再按交易日历过滤：非交易日行情同样会落库。
        // 仅在确实未写入任何数据时如实反馈，避免「未写入却提示已保存」的假成功。
        if (inserted + updated === 0) {
          if (errCount > 0) {
            this.$message.error(String(errMsgs[0] || '保存失败：数据校验未通过'));
          } else {
            this.$message.warning('未录入任何数据：该日行情可能已存在或本次无有效变更');
          }
          return;
        }

        this.$message.success(
          inserted > 0 ? `已保存 ${row.date} 的行情` : `已更新 ${row.date} 的行情`
        );
        this.resetManualOhlcEdited();
        this.manualForm.date = '';
        await this.fetchData();
      } catch (err) {
        const msg = (err.response && err.response.data && err.response.data.detail) || err.message || '保存失败';
        this.$message.error(String(msg));
      } finally {
        this.manualSubmitting = false;
      }
    },
    /* ================= 行情 K 线删除 ================= */
    handleQuoteSelectionChange(payload) {
      // vxe-table 多选事件返回 { records, ... }
      const rows = (payload && payload.records) || [];
      this.selectedQuoteRows = rows;
    },
    async handleDeletePrice(row) {
      if (!this.selectedAsset || !row || !row.date) return;
      this.batchDeleting = true;
      try {
        await deleteAssetPrice(this.selectedAsset, row.date);
        this.$message.success(`已删除 ${row.date} 的行情记录`);
        // 先在本地移除以避免闪烁，随后拉取最新数据
        const idx = this.quoteData.findIndex((it) => it.date === row.date);
        if (idx >= 0) this.quoteData.splice(idx, 1);
        await this.fetchData();
      } catch (err) {
        const msg = (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) || (err && err.message) || '删除失败';
        this.$message.error(String(msg));
      } finally {
        this.batchDeleting = false;
      }
    },
    async handleDeletePriceByPicker() {
      if (!this.selectedAsset || !this.deletePriceDate) return;
      const date = this.deletePriceDate;
      try {
        await this.$confirm(
          `确认删除 <strong>${date}</strong> 的行情记录？<br/><span style="color:#909399;font-size:12px;">删除后不可恢复，请谨慎操作</span>`,
          '删除确认',
          {
            confirmButtonText: '确认删除',
            cancelButtonText: '取消',
            type: 'warning',
            dangerouslyUseHTMLString: true
          }
        );
      } catch (e) {
        return;
      }
      this.singleDeletingPrice = true;
      try {
        await deleteAssetPrice(this.selectedAsset, date);
        this.$message.success(`已删除 ${date} 的行情记录`);
        this.deletePriceDate = '';
        const idx = this.quoteData.findIndex((it) => it.date === date);
        if (idx >= 0) this.quoteData.splice(idx, 1);
        await this.fetchData();
      } catch (err) {
        const msg = (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) || (err && err.message) || '删除失败';
        this.$message.error(String(msg));
      } finally {
        this.singleDeletingPrice = false;
      }
    },
    async handleBatchDeletePrices() {
      if (!this.selectedAsset || !this.selectedQuoteRows.length) return;
      const dates = this.selectedQuoteRows.map((r) => r.date).filter(Boolean);
      if (!dates.length) return;
      const previewDates = dates.slice(0, 5).join('、') + (dates.length > 5 ? ` 等共 ${dates.length} 个日期` : '');
      try {
        await this.$confirm(
          `确认删除选中的 ${dates.length} 条行情记录？<br/><span style="color:#909399;font-size:12px;">${previewDates}</span>`,
          '批量删除确认',
          {
            confirmButtonText: '确认删除',
            cancelButtonText: '取消',
            type: 'warning',
            dangerouslyUseHTMLString: true
          }
        );
      } catch (e) {
        return; // 用户取消
      }
      this.batchDeleting = true;
      try {
        // 优先尝试批量接口；后端未实现时退化为逐条调用
        let useFallback = false;
        try {
          await deleteAssetPricesBatch(this.selectedAsset, dates);
        } catch (err) {
          const status = err && err.response && err.response.status;
          if (status === 404 || status === 405 || status === 501) {
            useFallback = true;
          } else {
            throw err;
          }
        }
        if (useFallback) {
          for (const d of dates) {
            // eslint-disable-next-line no-await-in-loop
            await deleteAssetPrice(this.selectedAsset, d);
          }
        }
        this.$message.success(`已删除 ${dates.length} 条行情记录`);
        this.selectedQuoteRows = [];
        await this.fetchData();
      } catch (err) {
        const msg = (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) || (err && err.message) || '批量删除失败';
        this.$message.error(String(msg));
      } finally {
        this.batchDeleting = false;
      }
    },
    /**
     * 绘图时跳过占位/异常行（折线与 K 线共用）：
     * 开、高、低均为 0 时，无论收盘是否为 0，多为非交易日占位或仅补了收盘价的不完整数据，避免拖到 0 或畸变 K 线。
     */
    isZeroOhlcChartPlaceholder(row) {
      const n = (v) => {
        if (v == null || v === '') return 0;
        const x = Number(v);
        return Number.isFinite(x) ? x : NaN;
      };
      const o = n(row.open);
      const c = n(row.close);
      const h = n(row.high);
      const l = n(row.low);
      if (!Number.isFinite(o) || !Number.isFinite(c) || !Number.isFinite(h) || !Number.isFinite(l)) {
        return false;
      }
      return o === 0 && h === 0 && l === 0;
    },
    renderChart() {
      this.$nextTick(() => {
        if (!this.$refs.klineChart) return;
        
        if (!this.chartInstance) {
          this.chartInstance = echarts.init(this.$refs.klineChart);
        }

        if (this.quoteData.length === 0) {
          this.chartInstance.clear();
          this.chartInstance.setOption({
            title: {
              text: this.getAssetName(this.selectedAsset) + ' K线图',
              left: 0,
              subtext: '暂无数据',
              subtextStyle: { color: '#999' }
            },
            xAxis: { type: 'category', data: [] },
            yAxis: { type: 'value' },
            series: []
          });
          return;
        }

        const chartRows = this.quoteData.filter((row) => !this.isZeroOhlcChartPlaceholder(row));
        if (chartRows.length === 0) {
          this.chartInstance.clear();
          this.chartInstance.setOption({
            title: {
              text: this.getAssetName(this.selectedAsset) + ' K线图',
              left: 0,
              subtext: '无有效K线数据（已跳过开高低为0的占位行情）',
              subtextStyle: { color: '#999' }
            },
            xAxis: { type: 'category', data: [] },
            yAxis: { type: 'value' },
            series: []
          });
          return;
        }

        const dates = chartRows.map(item => item.date);
        const closeData = chartRows.map(item => item.close);
        const klineData = chartRows.map(item => [item.open, item.close, item.low, item.high]);
        
        // 检测是否所有数据都只有收盘价（open=high=low=close）
        const hasOnlyClose = chartRows.every(item => 
          item.open === item.close && item.high === item.close && item.low === item.close
        );

        const quoteData = chartRows;
        const option = {
          title: {
            text: this.getAssetName(this.selectedAsset) + (hasOnlyClose ? ' 收盘价走势' : ' K线图'),
            left: 0
          },
          tooltip: {
            trigger: 'axis',
            axisPointer: {
              type: 'cross'
            },
            formatter: (params) => {
              if (!params || !params.length) return '';
              const idx = params[0].dataIndex;
              const row = quoteData[idx];
              if (!row) return params[0].name || '';
              const lines = [row.date || params[0].name];
              if (hasOnlyClose) {
                lines.push(`收盘: ${this.formatPrice(row.close)}`);
              } else {
                const o = row.open, c = row.close, h = row.high, l = row.low;
                lines.push(`开盘: ${this.formatPrice(o)}  收盘: ${this.formatPrice(c)}`);
                lines.push(`最高: ${this.formatPrice(h)}  最低: ${this.formatPrice(l)}`);
                if (o != null && o !== 0 && c != null) {
                  const pct = (((c - o) / o) * 100).toFixed(2);
                  lines.push(`涨跌幅: ${pct}%`);
                }
              }
              if (row.volume != null && row.volume !== 0) lines.push(`成交量: ${this.formatVolume(row.volume)}`);
              if (row.amount != null && row.amount !== 0) lines.push(`成交额: ${this.formatAmount(row.amount)}`);
              return lines.join('<br/>');
            }
          },
          grid: {
            left: '3%',
            right: '3%',
            bottom: '10%'
          },
          xAxis: {
            type: 'category',
            data: dates,
            scale: true,
            boundaryGap: hasOnlyClose ? false : true,
            axisLine: { onZero: false },
            splitLine: { show: false }
          },
          yAxis: {
            scale: true,
            splitArea: {
              show: true
            }
          },
          dataZoom: [
            {
              type: 'inside',
              start: 50,
              end: 100
            },
            {
              show: true,
              type: 'slider',
              top: '90%',
              start: 50,
              end: 100
            }
          ],
          series: hasOnlyClose ? [
            {
              name: '收盘',
              type: 'line',
              data: closeData,
              smooth: false,
              symbol: 'circle',
              symbolSize: 6,
              itemStyle: {
                color: '#5470c6'
              },
              lineStyle: {
                width: 2
              }
            }
          ] : [
            {
              name: '日K',
              type: 'candlestick',
              data: klineData,
              itemStyle: {
                color: '#ec0000',
                color0: '#00da3c',
                borderColor: '#8A0000',
                borderColor0: '#008F28'
              }
            }
          ],
          legend: {
            data: hasOnlyClose ? ['收盘'] : ['日K'],
            bottom: '2%'
          }
        };

        this.chartInstance.setOption(option, true);
      });
    },
    getAssetName(code) {
      const asset = this.assetOptions.find(item => item.code === code);
      return asset ? asset.name : code;
    },
    formatPrice(price) {
      if (price == null) return '-';
      return price.toFixed(this.pricePrecision);
    },
    getPriceClass(row) {
      if (row.close == null || row.open == null) return '';
      return row.close >= row.open ? 'price-up' : 'price-down';
    },
    formatVolume(v) {
      if (v == null || v === 0) return '-';
      if (v >= 100000000) return (v / 100000000).toFixed(2) + '亿';
      if (v >= 10000) return (v / 10000).toFixed(2) + '万';
      return v.toString();
    },
    formatAmount(v) {
      if (v == null || v === 0) return '-';
      const n = Number(v);
      if (n >= 100000000) return (n / 100000000).toFixed(2) + '亿';
      if (n >= 10000) return (n / 10000).toFixed(2) + '万';
      return n.toLocaleString();
    },
    async handlePriceTemplateCommand(cmd) {
      try {
        let blob;
        let filename;
        if (String(cmd).startsWith('single_')) {
          const kind = String(cmd).slice('single_'.length) || 'full';
          blob = await downloadPriceTemplate(kind);
          filename =
            kind === 'full'
              ? '行情导入模板-单资产-全列.xlsx'
              : `行情导入模板-单资产-${kind}.xlsx`;
        } else if (String(cmd).startsWith('multi_')) {
          const metric = String(cmd).slice('multi_'.length) || 'close';
          blob = await downloadMultiAssetPriceTemplate(metric);
          filename = `行情导入模板-多资产宽表-${metric}.xlsx`;
        } else {
          return;
        }
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        link.click();
        window.URL.revokeObjectURL(url);
        this.$message.success('模板下载成功');
      } catch (error) {
        this.$message.error('模板下载失败');
      }
    },
    formatMultiImportEffect(row) {
      const p = row.import_preview;
      if (!p) return '—';
      if (this.multiImportMode === 'replace') {
        const fr = p.full_replace || {};
        const delc = fr.will_delete_count != null ? fr.will_delete_count : 0;
        const ins = fr.will_insert_count != null ? fr.will_insert_count : 0;
        let tail = '';
        if (fr.result_date_min && fr.result_date_max) {
          tail = `写入后日期约 ${fr.result_date_min}～${fr.result_date_max}（以文件为准）。`;
        }
        return `将删除库内全部 ${delc} 条，再写入文件 ${ins} 行。${tail}`;
      }
      const m = p.merge_import || {};
      if (this.multiImportMode === 'only_new') {
        const ins = m.will_insert_count != null ? m.will_insert_count : 0;
        const skip = m.will_update_count != null ? m.will_update_count : 0;
        const rg =
          m.new_dates_min && m.new_dates_max
            ? ` 新增区间约 ${m.new_dates_min}～${m.new_dates_max}。`
            : '';
        if (!ins && !skip) {
          return p.file_unique_date_count ? '按合并估算无可插入新日（或文件无有效新日）' : '无';
        }
        return `仅新增：预计插入 ${ins} 个交易日；${skip} 个与库重叠的交易日将跳过不更新。${rg}`.trim();
      }
      const parts = [];
      if (m.will_insert_count) {
        const rg =
          m.new_dates_min && m.new_dates_max
            ? `，日期约 ${m.new_dates_min}～${m.new_dates_max}`
            : '';
        parts.push(`新增 ${m.will_insert_count} 个交易日${rg}`);
      }
      if (m.will_update_count) {
        const rg =
          m.overlap_dates_min && m.overlap_dates_max
            ? `，日期约 ${m.overlap_dates_min}～${m.overlap_dates_max}`
            : '';
        parts.push(`更新 ${m.will_update_count} 个交易日${rg}`);
      }
      if (!parts.length) {
        return p.file_unique_date_count ? '无有效可导入日期' : '无';
      }
      return parts.join('；') + '。';
    },
    async onMultiImportTargetChange(row) {
      if (row) {
        this.$set(row, 'bindConfirmed', true);
      }
      if (!row || !row.importAsCode || !row.prices || !row.prices.length) return;
      try {
        const res = await getMultiAssetRowPreviewStats({
          target_code: row.importAsCode,
          prices: row.prices
        });
        const inner = res && res.data !== undefined ? res.data : res;
        if (inner && typeof inner === 'object') {
          this.$set(row, 'import_preview', inner);
        }
      } catch (e) {
        this.$message.warning('刷新导入预览失败，仍以默认目标估算');
      }
    },
    // 处理行情文件选择
    async handlePriceFileChange(file) {
      if (!this.selectedAsset) {
        this.$message.warning('请先选择资产');
        return;
      }
      
      try {
        await this.$confirm(
          '「确定」= 全量覆盖：删除该资产全部历史行情后写入 Excel 全部行；「取消」进入非全量（按日合并或仅新增缺日）。',
          '单资产 Excel 导入',
          {
            confirmButtonText: '全量覆盖',
            cancelButtonText: '非全量',
            distinguishCancelAndClose: true,
            type: 'warning'
          }
        );
        await this.importPriceData(file.raw, true, false);
        return;
      } catch (e) {
        if (e === 'close') return;
        if (e !== 'cancel') return;
      }
      try {
        await this.$confirm(
          '「确定」= 仅新增缺日：库中已有日期跳过；「取消」= 按日合并（重叠日更新、新日插入）。',
          '非全量导入',
          {
            confirmButtonText: '仅新增缺日',
            cancelButtonText: '按日合并',
            distinguishCancelAndClose: true,
            type: 'info'
          }
        );
        await this.importPriceData(file.raw, false, true);
      } catch (e2) {
        if (e2 === 'close') return;
        if (e2 === 'cancel') {
          await this.importPriceData(file.raw, false, false);
        }
      }
    },
    multiMatchLabel(kind) {
      const m = {
        exact: '代码与名称均一致',
        code_name_diff: '仅代码一致',
        name_code_diff: '仅名称一致',
        name_ambiguous: '名称多条',
        new_asset: '系统中无匹配'
      };
      return m[kind] || kind || '—';
    },
    multiMatchTagType(kind) {
      const m = {
        exact: 'success',
        code_name_diff: 'warning',
        name_code_diff: 'warning',
        name_ambiguous: 'danger',
        new_asset: 'info'
      };
      return m[kind] || '';
    },
    /** 行情页用 options 接口拉全量代码，与 store.assetList（分页）解耦 */
    hasAssetCodeInOptions(code) {
      return this.assetOptions.some((a) => a.code === code);
    },
    /** 与后端 asset_service._infer_asset_type 规则对齐，供批量新建前端调用 */
    inferAssetTypeForBatchCreate(name, code) {
      const n = String(name || '');
      const c = String(code || '').toUpperCase();
      if (n.includes('债') || c.includes('.CS')) return '债券';
      if (n.includes('质押') || n.includes('DR007') || c.includes('.IB')) return '货币';
      if (
        n.includes('商品') ||
        n.includes('黄金') ||
        n.includes('有色') ||
        n.includes('化工') ||
        n.includes('能源') ||
        n.includes('贵金属') ||
        n.includes('原油') ||
        n.includes('豆粕')
      ) {
        return '商品';
      }
      if (
        n.includes('ETF') ||
        n.includes('LOF') ||
        c.includes('518') ||
        c.includes('159') ||
        c.includes('501') ||
        c.includes('160') ||
        c.includes('164') ||
        c.includes('161')
      ) {
        return '基金';
      }
      if (n.includes('指数') || c.includes('300') || c.includes('.WI') || c.includes('000300')) return '指数';
      if (c.includes('.SH') || c.includes('.SZ')) {
        return n.includes('ETF') || n.includes('LOF') ? '基金' : '指数';
      }
      return '指数';
    },
    /** 与后端 _infer_exchange 对齐 */
    inferExchangeForBatchCreate(code) {
      const c = String(code || '').toUpperCase();
      if (c.includes('.SH') || c.endsWith('SH')) return 'SSE';
      if (c.includes('.SZ') || c.endsWith('SZ')) return 'SZSE';
      if (c.includes('.CS')) return 'CBB';
      if (c.includes('.IB')) return 'IB';
      if (c.includes('.WI')) return 'Wind';
      return null;
    },
    /** 对勾选的「系统中无匹配」且库中尚无代码的行，批量调用创建资产（类型/交易所与导入逻辑推断一致） */
    async batchCreateSelectedNewAssets() {
      await this.fetchAssetOptions();
      const targets = this.multiAssetRows.filter(
        (r) => r.selected && r.match_kind === 'new_asset' && !this.hasAssetCodeInOptions(r.file_code)
      );
      if (!targets.length) {
        this.$message.info('当前勾选中没有「系统中无匹配」且尚未建立的资产，无需批量新建。');
        return;
      }
      try {
        await this.$confirm(
          `将为 ${targets.length} 个所选资产创建记录（代码、名称与文件一致；资产类型与交易所按规则推断）。是否继续？`,
          '批量新建',
          { type: 'warning' }
        );
      } catch (e) {
        return;
      }
      this.multiBatchCreateLoading = true;
      const errs = [];
      let ok = 0;
      try {
        for (let i = 0; i < targets.length; i++) {
          const row = targets[i];
          const ex = this.inferExchangeForBatchCreate(row.file_code);
          const body = {
            code: row.file_code,
            name: row.file_name,
            asset_type: this.inferAssetTypeForBatchCreate(row.file_name, row.file_code)
          };
          if (ex) body.exchange = ex;
          try {
            await createAsset(body);
            ok += 1;
          } catch (err) {
            const msg =
              (err.response && err.response.data && err.response.data.detail) || err.message || '失败';
            errs.push(`${row.file_code}: ${msg}`);
          }
        }
        await this.fetchAssetOptions();
        this.$message.success(`批量新建结束：成功 ${ok} 个，失败 ${errs.length} 个`);
        if (errs.length) {
          this.$alert(errs.slice(0, 12).join('\n') + (errs.length > 12 ? '\n…' : ''), '失败明细', {
            type: 'error'
          });
        }
      } finally {
        this.multiBatchCreateLoading = false;
      }
    },
    onMultiAssetDialogClosed() {
      this.stopMultiImportProgressPoll();
      this.multiImportProgressLine = '';
      this.multiAssetRows = [];
      this.multiImportSubmitting = false;
      this.multiImportMode = 'merge';
    },
    newPriceImportProgressId() {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
      }
      return `p-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
    },
    stopMultiImportProgressPoll() {
      this._multiImportPollProgressId = null;
      if (this._multiImportProgressTimer) {
        clearInterval(this._multiImportProgressTimer);
        this._multiImportProgressTimer = null;
      }
    },
    startMultiImportProgressPoll(progressId) {
      this.stopMultiImportProgressPoll();
      if (!progressId) return;
      this._multiImportPollProgressId = progressId;
      let hadSnap = false;
      const tick = () => {
        const id = this._multiImportPollProgressId;
        if (!id) return;
        getPriceImportProgress(id)
          .then((res) => {
            if (this._multiImportPollProgressId !== id) return;
            const snap = unwrapPriceImportProgressPayload(res);
            if (snap) {
              hadSnap = true;
              this.multiImportProgressLine = formatPriceImportProgressLine(snap);
            } else if (!hadSnap) {
              this.multiImportProgressLine = '正在连接导入任务，等待服务端进度…';
            }
          })
          .catch(() => {
            if (this._multiImportPollProgressId !== id) return;
            if (!hadSnap) {
              this.multiImportProgressLine = '无法拉取进度（请检查网络或登录态）';
            }
          });
      };
      tick();
      this._multiImportProgressTimer = setInterval(tick, PRICE_IMPORT_PROGRESS_POLL_MS);
    },
    openMultiAssetCreate(rowIndex) {
      const row = this.multiAssetRows[rowIndex];
      if (!row) return;
      this.multiAssetCreateRowIndex = rowIndex;
      this.multiAssetCreatePreset = { code: row.file_code, name: row.file_name };
      this.multiAssetFormKey += 1;
      this.multiAssetCreateVisible = true;
    },
    async onMultiAssetCreateSuccess() {
      this.multiAssetCreateVisible = false;
      await this.fetchAssetOptions();
      const row = this.multiAssetRows[this.multiAssetCreateRowIndex];
      if (row && row.match_kind === 'new_asset') {
        if (this.hasAssetCodeInOptions(row.file_code)) {
          this.$set(row, 'selected', true);
          this.$message.success('已创建资产，可勾选并导入行情');
        }
      }
      this.multiAssetCreateRowIndex = -1;
    },
    normalizeMultiAssetResponse(res) {
      const body = res && res.data !== undefined ? res.data : res;
      return (body && body.assets) || [];
    },
    async handleMultiAssetFileChange(file) {
      if (!file || !file.raw) return;
      this.multiAssetLoading = true;
      this.multiAssetDialogVisible = true;
      try {
        await this.fetchAssetOptions();
        const res = await analyzeMultiAssetImport(file.raw, this.multiImportMetric);
        const assets = this.normalizeMultiAssetResponse(res);
        if (!assets.length) {
          this.$message.warning(
            `未解析到任何资产列，请确认宽表布局及工具栏「宽表列含义」与文件一致（当前：${this.multiImportMetricLabel}）`
          );
          this.multiAssetDialogVisible = false;
          return;
        }
        this.multiAssetRows = assets.map((a) => {
          const kind = a.match_kind;
          const base = {
            ...a,
            selected: kind !== 'name_code_diff' && kind !== 'name_ambiguous',
            overwriteName: false,
            codeDiffMode: 'keep',
            newAssetCode: '',
            importAsCode: a.suggested_import_code || a.file_code,
            bindConfirmed:
              kind === 'exact' ||
              kind === 'code_name_diff' ||
              kind === 'new_asset' ||
              kind === 'name_ambiguous'
          };
          if (kind === 'name_code_diff') {
            base.bindConfirmed = false;
            base.importAsCode = a.system_code || a.suggested_import_code;
          }
          return base;
        });
        this.multiImportMode = 'merge';
        if (this.multiImportMetric !== 'close') {
          this.$message.warning(
            '当前为收盘价之外的补充字段：请先确保各交易日已导入有效收盘价；无收盘价锚点的日期将无法写入。'
          );
        }
      } catch (err) {
        const msg = (err.response && err.response.data && err.response.data.detail) || err.message || '解析失败';
        this.$message.error(String(msg));
        this.multiAssetDialogVisible = false;
      } finally {
        this.multiAssetLoading = false;
        if (this.$refs.multiAssetUpload) {
          this.$refs.multiAssetUpload.clearFiles();
        }
      }
    },
    async submitMultiAssetImport() {
      await this.fetchAssetOptions();
      const rows = this.multiAssetRows.filter((r) => r.selected);
      if (!rows.length) {
        this.$message.warning('请至少勾选一条要导入的资产');
        return;
      }
      if (this.multiImportMetric !== 'close') {
        try {
          await this.$confirm(
            `当前宽表列为「${this.multiImportMetricLabel}」（非收盘价）。规则：① 库中尚无该日的行情时，本行必须含大于 0 的收盘价才会新建该日；② 库中已有该日行情时，须该日已有有效收盘价，或本行提供大于 0 的收盘价；③ 缺少有效代码或名称的列不会出现在表中。是否继续导入？`,
            '补充行情导入确认',
            { type: 'warning', confirmButtonText: '继续导入', cancelButtonText: '取消' }
          );
        } catch (e) {
          return;
        }
      }

      for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        if (row.match_kind === 'code_name_diff' && row.codeDiffMode === 'new') {
          const nc = (row.newAssetCode || '').trim();
          if (!nc) {
            this.$message.warning(`「仅代码一致」选择新建资产时，请填写新资产代码：${row.file_code}`);
            return;
          }
          if (this.hasAssetCodeInOptions(nc)) {
            this.$message.warning(`新资产代码已在系统中存在：${nc}`);
            return;
          }
        }
        if (row.match_kind === 'name_code_diff' && !row.bindConfirmed) {
          this.$message.warning(`请勾选「确认绑定」：${row.file_name} 将导入到系统代码 ${row.importAsCode}`);
          return;
        }
        if (row.match_kind === 'name_ambiguous') {
          if (!row.importAsCode) {
            this.$message.warning(`请为「${row.file_name}」选择导入目标代码`);
            return;
          }
        }
      }

      const nameBindLines = rows
        .filter((r) => r.match_kind === 'name_code_diff')
        .map((r) => `• ${r.file_name}：文件代码 ${r.file_code} → 行情写入 ${r.importAsCode}`);
      if (nameBindLines.length) {
        try {
          await this.$confirm(
            `以下资产仅名称与系统一致，行情将写入「系统代码」而非文件代码：\n${nameBindLines.join('\n')}`,
            '确认导入目标',
            { type: 'warning', confirmButtonText: '确认导入', cancelButtonText: '取消' }
          );
        } catch (e) {
          return;
        }
      }

      const ambiguous = rows.filter((r) => r.match_kind === 'name_ambiguous');
      for (let i = 0; i < ambiguous.length; i++) {
        const r = ambiguous[i];
        try {
          await this.$confirm(
            `「${r.file_name}」在系统中存在多条同名资产，您已选择将行情导入至 ${r.importAsCode}，是否继续？`,
            '确认同名资产',
            { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' }
          );
        } catch (e) {
          return;
        }
      }

      const newRows = rows.filter((r) => r.match_kind === 'new_asset');
      if (newRows.length) {
        try {
          await this.$confirm(
            `将导入 ${newRows.length} 条「系统中无匹配」资产：若代码尚不存在将自动新建（名称、代码与文件一致），并写入行情。是否继续？`,
            '确认导入',
            { type: 'warning' }
          );
        } catch (e) {
          return;
        }
      }

      const createNewByCodeDiff = rows.filter(
        (r) => r.match_kind === 'code_name_diff' && r.codeDiffMode === 'new'
      );
      if (createNewByCodeDiff.length) {
        const lines = createNewByCodeDiff.map(
          (r) => `• 文件代码 ${r.file_code} → 新建 ${(r.newAssetCode || '').trim()} 并导入行情（不修改原代码资产）`
        );
        try {
          await this.$confirm(
            `以下将新建资产并导入行情：\n${lines.join('\n')}`,
            '确认新建资产',
            { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' }
          );
        } catch (e) {
          return;
        }
      }

      this.multiImportSubmitting = true;
      this.multiImportProgressLine = '';
      let ok = 0;
      let fail = 0;
      const errs = [];
      try {
        for (let i = 0; i < rows.length; i++) {
          const row = rows[i];
          const useBind = row.match_kind === 'name_code_diff' || row.match_kind === 'name_ambiguous';
          const importAs = useBind ? row.importAsCode : null;
          const createNew =
            row.match_kind === 'code_name_diff' && row.codeDiffMode === 'new';
          const progressId = this.newPriceImportProgressId();
          const payload = {
            code: row.file_code,
            name: row.file_name,
            prices: row.prices || [],
            overwrite_name: row.match_kind === 'code_name_diff' && !createNew ? !!row.overwriteName : false,
            replace_existing: this.multiImportMode === 'replace',
            only_missing_dates: this.multiImportMode === 'only_new',
            import_as_code: importAs || undefined,
            create_new_asset: !!createNew,
            new_asset_code: createNew ? (row.newAssetCode || '').trim() : undefined,
            progress_id: progressId,
            import_metric: this.multiImportMetric
          };
          this.startMultiImportProgressPoll(progressId);
          try {
            await importSingleAssetFromMulti(payload);
            ok += 1;
          } catch (err) {
            fail += 1;
            const msg = (err.response && err.response.data && err.response.data.detail) || err.message || '失败';
            errs.push(`${row.file_code}: ${msg}`);
          } finally {
            this.stopMultiImportProgressPoll();
          }
        }
        this.$message.success(`导入结束：成功 ${ok} 个，失败 ${fail} 个`);
        if (errs.length) {
          this.$alert(errs.slice(0, 8).join('\n') + (errs.length > 8 ? '\n…' : ''), '失败明细', { type: 'error' });
        }
        this.multiAssetDialogVisible = false;
        await this.fetchAssetOptions();
        if (this.selectedAsset) {
          this.fetchData();
        }
      } finally {
        this.multiImportSubmitting = false;
      }
    },
    // 导入行情数据
    async importPriceData(file, replaceExisting, onlyMissingDates = false) {
      const loading = this.$loading({
        lock: true,
        text: '正在导入行情数据...',
        spinner: 'el-icon-loading'
      });
      
      try {
        const result = await importPricesFromExcel(
          this.selectedAsset,
          file,
          replaceExisting,
          this.excelOnlyDate || null,
          onlyMissingDates
        );
        const data = result.data || result;
        const sk = data.skipped_count != null ? data.skipped_count : 0;
        this.$message.success(
          `导入完成！新增 ${data.inserted_count != null ? data.inserted_count : 0} 条，更新 ${data.updated_count != null ? data.updated_count : 0} 条，跳过 ${sk} 条，失败 ${data.error_count != null ? data.error_count : 0} 条`
        );
        
        if (data.errors && data.errors.length > 0) {
          this.$alert(
            data.errors.slice(0, 10).join('\n') + (data.errors.length > 10 ? '\n...' : ''),
            '导入错误详情（最多显示10条）',
            {
              confirmButtonText: '确定',
              type: 'warning'
            }
          );
        }
        
        // 刷新行情数据
        this.fetchData();
      } catch (error) {
        const errorMsg = error.response?.data?.detail || error.message || '导入失败';
        this.$message.error('导入失败：' + errorMsg);
      } finally {
        loading.close();
        // 清空文件选择
        if (this.$refs.priceUpload) {
          this.$refs.priceUpload.clearFiles();
        }
      }
    }
  }
};
</script>

<style scoped>
.coverage-alert .coverage-meta {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}
.coverage-body {
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}
.coverage-first {
  margin-left: 12px;
}
.coverage-dates {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  word-break: break-all;
}
/* 行情明细表顶部工具栏 */
.quote-table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px 12px;
  border-bottom: 1px dashed #ebeef5;
  margin-bottom: 8px;
}
.quote-table-toolbar .toolbar-left {
  display: flex;
  align-items: center;
  gap: 4px;
}
.quote-table-toolbar .toolbar-left i {
  margin-right: 4px;
}
.quote-table-toolbar .toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.row-delete-btn {
  color: #f56c6c;
  padding: 4px 8px;
}
.row-delete-btn:hover {
  color: #fff;
  background: #f56c6c;
  border-radius: 4px;
}
.row-delete-btn:focus {
  color: #f56c6c;
}
/* 快捷删除某日行情卡片 */
.manual-delete-card {
  margin-bottom: 16px;
  border: 1px solid #fde2e2;
  background: linear-gradient(135deg, #fff8f8 0%, #fff5f5 100%);
  border-radius: 8px;
}
.manual-delete-card >>> .el-card__body {
  padding: 14px 18px;
}
.delete-card-header {
  margin-bottom: 12px;
}
.delete-card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  letter-spacing: 0.4px;
}
.delete-card-title i {
  color: #f56c6c;
  font-size: 18px;
}
.delete-card-hint {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
  margin-left: 4px;
}
.delete-card-body {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.delete-date-picker {
  width: 220px;
}
.delete-date-picker >>> .el-input__inner {
  border-color: #fbc4c4;
  background: #fff;
}
.delete-date-picker >>> .el-input__inner:hover {
  border-color: #f89898;
}
.delete-date-picker >>> .el-input__inner:focus {
  border-color: #f56c6c;
}
.delete-confirm-btn {
  letter-spacing: 0.5px;
}
.delete-card-tip {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed #fde2e2;
  font-size: 12px;
  color: #909399;
  display: flex;
  align-items: center;
  gap: 4px;
}
.delete-card-tip i {
  color: #e6a23c;
}
.manual-import-card {
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}
.manual-import-header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
}
.manual-import-hint {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}
.manual-required-text {
  color: #f56c6c;
}
.manual-close-label {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.manual-close-required-mark {
  color: #f56c6c;
  font-weight: 600;
  margin-left: 2px;
}
.manual-import-card .manual-price-input {
  width: 140px;
}
.manual-import-card .manual-price-input.narrow {
  width: 128px;
}
.manual-import-card .manual-vol-input {
  width: 140px;
}
.multi-metric-form-item {
  margin-bottom: 0;
}

.multi-asset-import-body {
  min-height: 120px;
}
.multi-asset-hint {
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
  margin: 0 0 12px;
}
.multi-asset-mode-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin: 0 0 12px;
}
.multi-import-live-progress {
  font-size: 13px;
  color: #303133;
  line-height: 1.5;
  margin: 0 0 12px;
  padding: 8px 10px;
  background: #f4f4f5;
  border-radius: 4px;
  font-family: Consolas, 'Courier New', monospace;
  word-break: break-all;
}
.multi-import-th {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  line-height: 1;
  padding: 2px 0;
}
.multi-import-header-label {
  font-size: 12px;
  font-weight: 500;
  color: #909399;
}
.multi-asset-toolbar {
  margin-bottom: 12px;
}
.multi-import-effect {
  font-size: 12px;
  line-height: 1.45;
  white-space: normal;
  word-break: break-word;
}
.multi-asset-cell-sub {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.multi-asset-cell-sub.warn {
  color: #e6a23c;
}
.multi-metric-anchor-alert {
  margin-bottom: 12px;
}
.multi-code-diff-rg {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}
.asset-quote-container {
  padding: 10px;
}
.price-up {
  color: #f56c6c;
}
.price-down {
  color: #67c23a;
}
</style>
