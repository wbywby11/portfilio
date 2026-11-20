<template>
  <div :class="{'page-container': !isDialog}">
    <!-- 操作栏：单行布局 -->
    <div v-if="!isDialog" class="page-header">
      <div class="header-left">
        <h2 class="page-title">策略详情</h2>
        <el-button size="small" @click="$router.back()">返回</el-button>
      </div>
      <div class="header-right">
        <el-button
          v-if="false"
          type="primary"
          size="small"
          @click="handleBacktest"
          :disabled="model.status === '已发布' || model.status === 'published' || backtestBlocked"
          :title="backtestBlocked ? backtestBlockedTip : ''"
          :loading="backtesting"
        >
          {{ backtesting ? '回测中...' : '运行回测' }}
        </el-button>
        <el-button
          v-if="isPublishedModel"
          type="warning"
          size="small"
          plain
          :disabled="isArchivedModel"
          :loading="unpublishing"
          @click="handleUnpublish"
        >
          取消发布
        </el-button>
        <el-button
          v-else
          type="success"
          size="small"
          :disabled="isArchivedModel"
          @click="handlePublish"
        >
          发布策略
        </el-button>
        <el-button
          v-if="model.live_publish_enabled"
          type="danger"
          size="small"
          plain
          icon="el-icon-close"
          :disabled="isArchivedModel"
          :loading="liveUnpublishing"
          @click="handleLiveUnpublish"
        >
          取消实盘
        </el-button>
        <el-button
          v-else
          type="primary"
          size="small"
          plain
          icon="el-icon-upload2"
          :disabled="!canOperateLivePublish"
          :loading="livePublishing"
          @click="handleLivePublish"
        >
          实盘发布
        </el-button>
        <el-button
          v-if="liveSnapshotBehind"
          type="warning"
          size="small"
          plain
          :loading="liveRepublishing"
          @click="handleLiveRepublish"
        >
          同步实盘版本
        </el-button>
      </div>
    </div>
    <!-- Dialog模式操作栏 -->
    <div v-if="isDialog" class="header-actions">
        <el-button
          v-if="false"
          type="primary"
          size="small"
          @click="handleBacktest"
          :disabled="model.status === '已发布' || model.status === 'published' || backtestBlocked"
          :title="backtestBlocked ? backtestBlockedTip : ''"
          :loading="backtesting"
        >
          {{ backtesting ? '回测中...' : '运行回测' }}
        </el-button>
        <el-button
          v-if="isPublishedModel"
          type="warning"
          size="small"
          plain
          :disabled="isArchivedModel"
          :loading="unpublishing"
          @click="handleUnpublish"
        >
          取消发布
        </el-button>
        <el-button
          v-else
          type="success"
          size="small"
          :disabled="isArchivedModel"
          @click="handlePublish"
        >
          发布策略
        </el-button>
        <el-button
          v-if="model.live_publish_enabled"
          type="danger"
          size="small"
          plain
          icon="el-icon-close"
          :disabled="isArchivedModel"
          :loading="liveUnpublishing"
          @click="handleLiveUnpublish"
        >
          取消实盘
        </el-button>
        <el-button
          v-else
          type="primary"
          size="small"
          plain
          icon="el-icon-upload2"
          :disabled="!canOperateLivePublish"
          :loading="livePublishing"
          @click="handleLivePublish"
        >
          实盘发布
        </el-button>
        <el-button
          v-if="liveSnapshotBehind"
          type="warning"
          size="small"
          plain
          :loading="liveRepublishing"
          @click="handleLiveRepublish"
        >
          同步实盘版本
        </el-button>
    </div>

    <el-alert
      v-if="!isDialog && fromMonitorHint"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px;"
      title="来自日常监控"
      description="策略发布后配置已冻结，修改需先取消发布。发布新版本后，如需实盘跟随最新逻辑，请点「同步实盘版本」以最新发布快照重建实盘快照；变更记录在实盘发布记录中。">
    </el-alert>

    <div :class="{'page-content': !isDialog}" v-loading="loading">
      <!-- 基本信息卡片 -->
      <el-card shadow="never" class="info-card">
        <div slot="header" class="card-header">
          <span>基本信息</span>
          <el-tooltip
            :content="isPublishedModel ? '已发布，配置已冻结；请先取消发布再编辑，被实盘组合引用时需先解除引用' : '编辑策略配置'"
            placement="top"
          >
            <span>
              <el-button type="text" size="small" :disabled="isPublishedModel || isArchivedModel" @click="handleEdit">编辑</el-button>
            </span>
          </el-tooltip>
        </div>
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="策略名称" :span="2">
            <span style="font-weight: 600;">{{ model.name }}</span>
            <el-tag :type="getStatusType(model.status)" size="mini" style="margin-left: 8px;">
              {{ getStatusLabel(model.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="策略模板">
            {{ model.template_name || model.template_code }}
          </el-descriptions-item>
          <el-descriptions-item label="调仓频率">{{ model.rebalance_frequency }}</el-descriptions-item>
          <el-descriptions-item label="实盘状态" :span="2">
            <el-tag :type="model.live_publish_enabled ? 'success' : 'info'" size="mini">
              {{ model.live_publish_enabled ? '已实盘发布' : '未实盘发布' }}
            </el-tag>
            <span v-if="model.live_publish_enabled && model.live_effective_date" style="margin-left: 8px; color: #67c23a; font-size: 12px;">
              生效日 {{ formatDateShort(model.live_effective_date) }}
            </span>
            <el-tag v-if="liveSnapshotBehind" type="warning" size="mini" style="margin-left: 8px;">
              实盘落后发布版本
            </el-tag>
            <span v-if="model.live_publish_enabled" style="margin-left: 12px; color: #909399; font-size: 12px;">
              可在「分析 → 日常监控」中跟踪
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="发布 / 实盘版本">
            <el-tag v-if="model.published_version" size="mini" type="info">发布 v{{ model.published_version }}</el-tag>
            <el-tag v-else size="mini">未发布</el-tag>
            <el-tag v-if="model.live_publish_enabled" size="mini" type="success" style="margin-left: 6px;">
              实盘 v{{ model.live_published_version || '—' }}
            </el-tag>
            <el-tooltip v-if="model.config_fingerprint" :content="'快照指纹：' + model.config_fingerprint" placement="top">
              <span style="margin-left: 6px; color: #909399; font-size: 12px; cursor: default;">
                {{ model.config_fingerprint.slice(0, 8) }}
              </span>
            </el-tooltip>
          </el-descriptions-item>
          <el-descriptions-item label="业绩基准" v-if="model.benchmark_name">
            {{ model.benchmark_name }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatDate(model.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="资产数量">
            <el-tag size="mini">{{ model.asset_codes && model.asset_codes.length || 0 }} 个</el-tag>
            <el-button type="text" size="mini" @click="assetListExpanded = !assetListExpanded" style="margin-left: 8px;">
              {{ assetListExpanded ? '收起' : '展开' }}
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="原型预设" :span="4" v-if="model.preset_code">
            <span>来自预设 {{ presetSourceLabel }}</span>
            <el-tag v-if="model.preset_modified" type="warning" size="mini" style="margin-left: 8px;">
              已调整
            </el-tag>
            <el-tooltip
              v-if="model.preset_outdated"
              content="预设定义已变更，当前模型仍按应用时的旧版本运行"
              placement="top"
            >
              <el-tag type="info" size="mini" style="margin-left: 8px;">基于旧版预设</el-tag>
            </el-tooltip>
            <span v-if="model.preset_applied_at" style="margin-left: 12px; color: #909399; font-size: 12px;">
              {{ formatDate(model.preset_applied_at) }} 应用
            </span>
            <span style="margin-left: 12px; color: #909399; font-size: 12px;">
              应用即快照，标签后续变更不会自动同步
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="策略描述" :span="4" v-if="model.description">
            {{ model.description }}
          </el-descriptions-item>
        </el-descriptions>
        <!-- 资产列表折叠区 -->
        <div v-show="assetListExpanded" style="margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 4px;">
          <el-tag
            v-for="code in model.asset_codes"
            :key="code"
            size="small"
            style="margin-right: 8px; margin-bottom: 8px;"
          >
            {{ code }} - {{ model.asset_names && model.asset_names[code] || '未知资产' }}
          </el-tag>
          <div v-if="!model.asset_codes || model.asset_codes.length === 0" style="color: #909399; text-align: center; font-size: 12px;">
            未选择资产
          </div>
        </div>
      </el-card>

      <el-row :gutter="20">
        <!-- 左侧：生命周期时间线 -->
        <el-col :span="14">
          <el-card shadow="never" class="lifecycle-card">
            <div slot="header" class="card-header">
              <span>策略生命周期</span>
              <span v-if="paramVersions.length > 0" style="color: #909399; font-size: 12px;">
                共 {{ paramVersions.length }} 个版本
              </span>
            </div>

            <!-- 当前版本参数（始终显示） -->
            <div class="current-params-section">
              <div class="section-label">
                <i class="el-icon-document"></i>
                当前参数
              </div>

              <!-- 分配策略区域 -->
              <div v-if="currentAllocatorParams && Object.keys(currentAllocatorParams).length > 0" class="param-group">
                <div class="param-group-label">分配策略</div>
                <el-descriptions :column="2" border size="mini">
                  <el-descriptions-item
                    v-for="(value, key) in currentAllocatorParams"
                    :key="'alloc_' + key"
                    :label="getParamLabel(key)"
                  >
                    <div style="white-space: pre-wrap;">{{ formatParamVal(value) }}</div>
                  </el-descriptions-item>
                </el-descriptions>
              </div>

              <!-- 资产选择器区域（优先 resolved_params.selector，回退到 model.enable_momentum_selection） -->
              <div v-if="(model.resolved_params && model.resolved_params.selector && model.resolved_params.selector.enabled) || (!model.resolved_params && model.enable_momentum_selection)" class="param-group">
                <div class="param-group-label">资产选择器：{{ getSelectorName(model.resolved_params && model.resolved_params.selector ? model.resolved_params.selector.type : model.selector_type) }}</div>
                <el-descriptions :column="2" border size="mini">
                  <el-descriptions-item label="选择器策略">{{ getSelectorName(effectiveSelectorType) }}</el-descriptions-item>
                  <el-descriptions-item v-if="effectiveAssetSelectionCount" label="选择资产数量">{{ effectiveAssetSelectionCount }}</el-descriptions-item>
                  <el-descriptions-item v-if="effectiveMinHistoryDays" label="最小历史">{{ effectiveMinHistoryDays }} 天</el-descriptions-item>
                  <!-- 从模板 schema 驱动展示选择器参数 -->
                  <template v-if="selectorTemplateDefs.length > 0">
                    <el-descriptions-item
                      v-for="pdef in selectorTemplateDefs"
                      :key="'sel_def_' + pdef.name"
                      :label="pdef.label || pdef.name"
                    >{{ getSelectorParamDisplay(pdef.name) }}</el-descriptions-item>
                  </template>
                  <!-- 回退：直接展示 selector_parameters 字典 -->
                  <template v-else-if="mergedSelectorParams">
                    <el-descriptions-item
                      v-for="(value, key) in mergedSelectorParams"
                      :key="'sel_' + key"
                      :label="getSelectorParamLabel(key)"
                    >{{ formatParamVal(value) }}</el-descriptions-item>
                  </template>
                </el-descriptions>
              </div>

              <!-- 风险控制区域（优先 resolved_params.controller，回退到 model.controller_code） -->
              <div v-if="(model.resolved_params && model.resolved_params.controller && model.resolved_params.controller.enabled) || (!model.resolved_params && model.controller_code)" class="param-group">
                <div class="param-group-label">风险控制：{{ getControllerName(model.resolved_params && model.resolved_params.controller ? model.resolved_params.controller.code : model.controller_code) }}</div>
                <el-descriptions :column="2" border size="mini">
                  <el-descriptions-item label="控制器策略">{{ getControllerName(effectiveControllerCode) }}</el-descriptions-item>
                  <template v-if="effectiveControllerParams && Object.keys(effectiveControllerParams).length > 0">
                    <el-descriptions-item
                      v-for="(value, key) in effectiveControllerParams"
                      :key="'ctrl_' + key"
                      :label="getControllerParamLabel(key)"
                    >
                      {{ formatParamVal(value) }}
                    </el-descriptions-item>
                  </template>
                </el-descriptions>
              </div>

              <div
                v-if="!currentAllocatorParams || Object.keys(currentAllocatorParams).length === 0"
                style="color: #909399; text-align: center; padding: 16px; font-size: 13px;"
              >暂无参数</div>
            </div>

            <!-- 历史版本时间线（始终可见） -->
            <div v-if="paramVersions.length > 0" class="history-section">
              <div class="history-header">
                <i class="el-icon-time"></i>
                <span>版本历史</span>
                <el-tag size="mini" type="info">{{ paramVersions.length }} 个版本</el-tag>
                <el-button
                  v-if="compareSelection.length === 2"
                  type="primary"
                  size="mini"
                  icon="el-icon-sort"
                  style="margin-left: auto;"
                  @click="openVersionCompare"
                >对比选中版本</el-button>
                <span v-else-if="compareSelection.length === 1" style="margin-left: auto; font-size: 12px; color: #e6a23c;">再选 1 个版本即可对比</span>
              </div>
              <el-timeline>
                  <el-timeline-item
                    v-for="ver in paramVersions"
                    :key="ver.id"
                    :timestamp="formatDate(ver.created_at)"
                    placement="top"
                  >
                    <el-card 
                      shadow="hover" 
                      class="version-card"
                      :class="[getVersionTypeClass(ver), { 'version-selected': compareSelection.includes(ver.id) }]"
                      @click.native="toggleVersionDetail(ver.id)"
                    >
                      <div class="version-header">
                        <div class="version-info">
                          <el-checkbox
                            :value="compareSelection.includes(ver.id)"
                            @change="toggleCompareSelect(ver.id)"
                            @click.native.stop
                            style="margin-right: 8px;"
                          ></el-checkbox>
                          <el-tag size="mini" :type="getVersionTagType(ver)" style="margin-right: 8px;">
                            v{{ ver.version }}
                          </el-tag>
                          <span class="version-summary">{{ ver.change_summary || '参数快照' }}</span>
                        </div>
                        <div class="version-badges">
                          <el-badge 
                            v-if="ver.backtest_count > 0" 
                            :value="ver.backtest_count" 
                            type="primary" 
                            size="mini"
                            style="margin-right: 8px;"
                          >
                            <span style="font-size: 11px; color: #909399;">回测</span>
                          </el-badge>
                          <i
                            :class="expandedVersionId === ver.id ? 'el-icon-arrow-up' : 'el-icon-arrow-down'"
                            style="color: #909399;"
                          ></i>
                        </div>
                      </div>
                      <!-- 展开后显示完整参数 -->
                      <div v-if="expandedVersionId === ver.id" class="version-detail">
                        <!-- 分配策略 -->
                        <div v-if="Object.keys(filterAllocatorParams(ver.allocator_params, ver.controller_code, ver.template_code)).length > 0" class="detail-group">
                          <div class="detail-group-label">分配策略</div>
                          <el-descriptions :column="2" border size="mini">
                            <el-descriptions-item
                              v-for="(v, k) in filterAllocatorParams(ver.allocator_params, ver.controller_code, ver.template_code)"
                              :key="'hv_alloc ' + k"
                              :label="getParamLabel(k)"
                            >{{ formatParamVal(v) }}</el-descriptions-item>
                          </el-descriptions>
                        </div>
                        <!-- 资产选择器（模板驱动标签） -->
                        <div v-if="ver.selector_enabled" class="detail-group">
                          <div class="detail-group-label">资产选择器：{{ getSelectorName(ver.selector_type) }}</div>
                          <el-descriptions :column="2" border size="mini">
                            <el-descriptions-item label="选择器策略">{{ getSelectorName(ver.selector_type) }}</el-descriptions-item>
                            <template v-if="ver.selector_params">
                              <el-descriptions-item
                                v-for="(v, k) in ver.selector_params"
                                :key="'hv sel ' + k"
                                :label="getSelectorParamLabel(k)"
                              >{{ formatParamVal(v) }}</el-descriptions-item>
                            </template>
                          </el-descriptions>
                        </div>
                        <!-- 风险控制（模板驱动标签） -->
                        <div v-if="ver.controller_code" class="detail-group">
                          <div class="detail-group-label">风险控制：{{ getControllerName(ver.controller_code) }}</div>
                          <el-descriptions :column="2" border size="mini">
                            <el-descriptions-item label="控制器策略">{{ getControllerName(ver.controller_code) }}</el-descriptions-item>
                            <template v-if="ver.controller_params">
                              <el-descriptions-item
                                v-for="(v, k) in ver.controller_params"
                                :key="'hv ctrl ' + k"
                                :label="getControllerParamLabel(k)"
                              >{{ formatParamVal(v) }}</el-descriptions-item>
                            </template>
                          </el-descriptions>
                        </div>
                        <!-- 资产列表 -->
                        <div v-if="ver.asset_codes && ver.asset_codes.length" class="detail-assets">
                          <span style="color: #909399;">资产:</span> {{ ver.asset_codes.join(', ') }}
                        </div>
                      </div>
                    </el-card>
                  </el-timeline-item>
              </el-timeline>
            </div>
            <div v-else class="empty-state" style="padding: 20px;">
              <i class="el-icon-time" style="font-size: 32px; color: #dcdfe6;"></i>
              <p style="color: #909399; font-size: 12px; margin-top: 8px;">暂无历史版本</p>
              <p style="color: #c0c4cc; font-size: 11px;">修改策略参数后将自动记录版本</p>
            </div>
          </el-card>
        </el-col>

        <!-- 右侧：回测历史 -->
        <el-col :span="10">
          <el-card shadow="never" class="history-card">
            <div slot="header" class="card-header">
              <span>历史回测</span>
              <span style="font-size: 12px; color: #909399;">
                共 {{ backtestPagination.total }} 条
              </span>
            </div>
            <el-timeline v-if="backtestHistory.length > 0">
              <el-timeline-item
                v-for="record in backtestHistory"
                :key="record.id"
                :timestamp="formatDate(record.created_at)"
                placement="top"
              >
                <el-card shadow="hover" class="backtest-card">
                  <div class="backtest-header">
                    <span class="backtest-period">
                      {{ formatDateShort(record.start_date) }} ~ {{ formatDateShort(record.end_date) }}
                    </span>
                    <el-tag v-if="record.param_version_number" size="mini" type="info">
                      v{{ record.param_version_number }}
                    </el-tag>
                  </div>
                  <div class="backtest-metrics">
                    <div class="metric-item">
                      <span class="metric-label">总收益</span>
                      <span class="metric-value" :style="{ color: getReturnColor(record.result.total_return) }">
                        {{ (record.result.total_return * 100).toFixed(2) }}%
                      </span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">年化收益（260日）</span>
                      <span class="metric-value" :style="{ color: getReturnColor(record.result.annual_return) }">
                        {{ (record.result.annual_return * 100).toFixed(2) }}%
                      </span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">年化收益（365日）</span>
                      <span class="metric-value">
                        {{ record.result.annual_return_365 != null ? (record.result.annual_return_365 * 100).toFixed(2) + '%' : '-' }}
                      </span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">夏普比率（260日）</span>
                      <span class="metric-value">{{ record.result.sharpe_ratio ? record.result.sharpe_ratio.toFixed(3) : '-' }}</span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">夏普比率（365日）</span>
                      <span class="metric-value">{{ record.result.sharpe_ratio_365 != null ? record.result.sharpe_ratio_365.toFixed(3) : '-' }}</span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">最大回撤</span>
                      <span class="metric-value" style="color: #f56c6c;">
                        {{ (record.result.max_drawdown * 100).toFixed(2) }}%
                      </span>
                    </div>
                  </div>
                  <div v-if="record.remark || editingRecordId === record.id" class="backtest-remark">
                    <span v-if="editingRecordId !== record.id">
                      <i class="el-icon-edit"></i> {{ record.remark || '-' }}
                    </span>
                    <span v-else style="display: flex; align-items: center; gap: 8px;">
                      <el-input v-model="editingRemark" size="mini" placeholder="输入备注" maxlength="200" show-word-limit style="flex: 1;"></el-input>
                      <el-button type="primary" size="mini" @click="saveRemark(record)">保存</el-button>
                      <el-button size="mini" @click="editingRecordId = null; editingRemark = ''">取消</el-button>
                    </span>
                  </div>
                  <div class="backtest-actions">
                    <el-button type="text" size="mini" @click="viewBacktestDetail(record)">查看详情</el-button>
                    <el-button type="text" size="mini" @click="editingRecordId = record.id; editingRemark = record.remark || ''">
                      {{ editingRecordId === record.id ? '' : '编辑备注' }}
                    </el-button>
                  </div>
                </el-card>
              </el-timeline-item>
            </el-timeline>
            <div v-else class="empty-state">
              <i class="el-icon-data-line" style="font-size: 40px; color: #dcdfe6;"></i>
              <p>暂无回测记录</p>
            </div>
            
            <!-- 分页 -->
            <div v-if="backtestPagination.total > backtestPagination.limit" style="text-align: center; margin-top: 16px;">
              <el-pagination
                small
                layout="prev, pager, next"
                :current-page="currentPage"
                :page-size="backtestPagination.limit"
                :total="backtestPagination.total"
                @current-change="handleBacktestPageChange"
              >
              </el-pagination>
            </div>
          </el-card>

          <!-- 策略报告 -->
          <el-card shadow="never" class="info-card" v-if="backtestHistory.length > 0" style="margin-top: 16px;">
            <div slot="header" class="card-header">
              <span>策略报告</span>
              <el-button type="primary" size="mini" :loading="reportLoading" @click="generateReport">
                {{ portfolioReport ? '重新生成' : '生成报告' }}
              </el-button>
            </div>
            <div v-if="portfolioReport" class="portfolio-report">
              <el-row :gutter="12" class="metrics-row">
                <el-col :span="6">
                  <div class="metric-card">
                    <div class="metric-label">年化收益（260日）</div>
                    <div class="metric-value" :style="{color: (portfolioReport.annual_return||0) >= 0 ? '#67c23a' : '#f56c6c'}">
                      {{ ((portfolioReport.annual_return||0)*100).toFixed(2) }}%
                    </div>
                    <div class="metric-sub">365日：{{ ((portfolioReport.annual_return_365||0)*100).toFixed(2) }}%</div>
                  </div>
                </el-col>
                <el-col :span="6">
                  <div class="metric-card">
                    <div class="metric-label">年化波动（260日）</div>
                    <div class="metric-value">{{ ((portfolioReport.annual_vol||0)*100).toFixed(2) }}%</div>
                    <div class="metric-sub">365日：{{ ((portfolioReport.annual_vol_365||0)*100).toFixed(2) }}%</div>
                  </div>
                </el-col>
                <el-col :span="6">
                  <div class="metric-card">
                    <div class="metric-label">夏普比率（260日）</div>
                    <div class="metric-value" :style="{color: (portfolioReport.sharpe||0) >= 1 ? '#67c23a' : '#e6a23c', fontWeight: 600}">
                      {{ (portfolioReport.sharpe||0).toFixed(2) }}
                    </div>
                    <div class="metric-sub">365日：{{ (portfolioReport.sharpe_365||0).toFixed(2) }}</div>
                  </div>
                </el-col>
                <el-col :span="6">
                  <div class="metric-card">
                    <div class="metric-label">最大回撤</div>
                    <div class="metric-value" style="color: #f56c6c;">{{ ((portfolioReport.max_drawdown||0)*100).toFixed(2) }}%</div>
                  </div>
                </el-col>
              </el-row>
              <!-- 子策略分解 -->
              <div v-if="portfolioReport.sub_strategy_decomposition && portfolioReport.sub_strategy_decomposition.length" style="margin-top: 16px;">
                <div style="font-size: 12px; color: #606266; font-weight: 500; margin-bottom: 8px;">子策略分解</div>
                <el-table :data="portfolioReport.sub_strategy_decomposition" size="mini" border>
                  <el-table-column prop="sub_name" label="子策略" width="100" />
                  <el-table-column prop="weight" label="权重" width="60" align="right">
                    <template slot-scope="{ row }">{{ (row.weight * 100).toFixed(0) }}%</template>
                  </el-table-column>
                  <el-table-column label="收益（260日）" width="110" align="right">
                    <template slot-scope="{ row }">
                      <span :style="{color: row.annual_return >= 0 ? '#67c23a' : '#f56c6c'}">{{ (row.annual_return * 100).toFixed(2) }}%</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="收益（365日）" width="110" align="right">
                    <template slot-scope="{ row }">{{ ((row.annual_return_365||0) * 100).toFixed(2) }}%</template>
                  </el-table-column>
                  <el-table-column label="波动（260日）" width="110" align="right">
                    <template slot-scope="{ row }">{{ (row.annual_vol * 100).toFixed(2) }}%</template>
                  </el-table-column>
                  <el-table-column label="波动（365日）" width="110" align="right">
                    <template slot-scope="{ row }">{{ ((row.annual_vol_365||0) * 100).toFixed(2) }}%</template>
                  </el-table-column>
                  <el-table-column label="夏普（260日）" width="100" align="right">
                    <template slot-scope="{ row }">{{ row.sharpe.toFixed(2) }}</template>
                  </el-table-column>
                  <el-table-column label="夏普（365日）" width="100" align="right">
                    <template slot-scope="{ row }">{{ (row.sharpe_365||0).toFixed(2) }}</template>
                  </el-table-column>
                </el-table>
              </div>
            </div>
            <div v-else-if="!reportLoading" class="empty-state">
              <i class="el-icon-document" style="font-size: 32px; color: #dcdfe6;"></i>
              <p style="color: #909399; font-size: 12px;">点击「生成报告」进行全面评估</p>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 回测详情对话框 -->
    <backtest-detail-dialog
      v-model="backtestDetailVisible"
      :record="currentBacktestRecord"
    />

    <!-- 策略编辑弹窗 -->
    <el-dialog
      title="编辑策略"
      :visible.sync="editDialogVisible"
      width="1000px"
      append-to-body
    >
      <strategy-model-form
        v-if="editDialogVisible"
        is-dialog
        :id="modelId"
        @success="handleEditSuccess"
        @close="editDialogVisible = false"
      />
    </el-dialog>

    <!-- 版本对比弹窗 -->
    <version-compare-dialog
      :visible.sync="compareDialogVisible"
      :version-a="compareVersionA"
      :version-b="compareVersionB"
      :backtest-history="backtestHistory"
      @close="compareDialogVisible = false"
    />

  </div>
</template>

<script>
import { mapState } from 'vuex';
import dayjs from 'dayjs';
import BacktestDetailDialog from '@/components/BacktestDetailDialog.vue';
import VersionCompareDialog from './components/VersionCompareDialog.vue';
import { updateBacktestRemark, generatePortfolioReport, getParamVersions, getStrategyPresets, validateStrategyConfig } from '@/api/strategy';
import {
  isRiskBudgetTargetVolTemplateCode,
  RISK_BUDGET_TARGET_VOL_HIDDEN_PARAMETER_NAMES,
  isSharpeRiskBudgetTemplateCode,
  SHARPE_RISK_BUDGET_HIDDEN_SCHEMA_PARAMETER_NAMES,
  isManualAllocationTemplateCode,
} from '@/utils/strategyTemplateFlags';

// 控制器相关参数字段（未启用控制器时不应显示）
// 包含：波动率控制参数 + 系统自动注入的固定参数（非用户配置）
const CONTROLLER_RELATED_PARAMS = [
  'enable_vol_reset',
  'vol_reset_threshold',
  'vol_trigger_threshold',
  'vol_monitor_start',
  'vol_windows',
  'monitor_start_days',
  'min_history_days',
  'tie_break_window',
  'sharp_windows',
];

export default {
  name: 'StrategyModelDetail',
  components: {
    BacktestDetailDialog,
    VersionCompareDialog,
    StrategyModelForm: () => import('./StrategyModelForm.vue')
  },
  props: {
    isDialog: {
      type: Boolean,
      default: false
    },
    id: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      modelId: null,
      model: {
        name: '',
        status: 'draft',
        template_code: '',
        description: '',
        parameters: {},
        asset_codes: [],
        rebalance_frequency: '',
        created_at: null,
        live_publish_enabled: false,
        live_snapshot_outdated: false,
        live_effective_date: null,
        selector_type: null
      },
      livePublishing: false,
      liveUnpublishing: false,
      liveRepublishing: false,
      unpublishing: false,
      backtestHistory: [],
      portfolioReport: null,
      reportLoading: false,
      backtestPagination: {
        skip: 0,
        limit: 10,
        total: 0
      },
      loading: false,
      backtesting: false,
      assetListExpanded: false,
      paramVersions: [],
      expandedVersionId: null,
      compareSelection: [],
      compareDialogVisible: false,
      backtestDetailVisible: false,
      currentBacktestRecord: {
        id: '',
        start_date: '',
        end_date: '',
        initial_capital: 0,
        result: {},
        created_at: ''
      },
      editDialogVisible: false,
      editingRecordId: null,
      editingRemark: '',
      // 原型预设：code → 预设摘要（用 name 展示，不直接露 code）
      presetNameMap: {},
      // 回测实时门禁：blocking_error / data_error 两级问题（warning 不阻断）
      backtestGateIssues: []
    };
  },
  computed: {
    currentPage() {
      return Math.floor(this.backtestPagination.skip / this.backtestPagination.limit) + 1;
    },
    isPublishedModel() {
      return this.model.status === '已发布' || this.model.status === 'published';
    },
    isArchivedModel() {
      return this.model.status === '已归档' || this.model.status === 'archived';
    },
    /** 预设来源展示名（未拉到清单时回退为预设代码） */
    presetSourceLabel() {
      if (!this.model.preset_code) return '';
      const item = this.presetNameMap[this.model.preset_code];
      return item ? item.name : this.model.preset_code;
    },
    /** 回测实时门禁：blocking 与数据缺口都禁用「运行回测」 */
    backtestBlocked() {
      return this.backtestGateIssues.length > 0;
    },
    /** 门禁提示：首条问题 + 其余条数 */
    backtestBlockedTip() {
      const first = this.backtestGateIssues[0];
      if (!first) return '';
      const prefix = first.level === 'blocking_error' ? '配置阻断' : '数据缺口';
      const rest = this.backtestGateIssues.length > 1
        ? `（另有 ${this.backtestGateIssues.length - 1} 项问题）` : '';
      return `${prefix}：${first.message}${rest}`;
    },
    canOperateLivePublish() {
      return this.isPublishedModel && !this.isArchivedModel && !this.model.live_publish_enabled;
    },
    /** 实盘快照落后于最新发布版本（需同步实盘版本才跟随新逻辑） */
    liveSnapshotBehind() {
      if (!this.model.live_publish_enabled) return false;
      const published = Number(this.model.published_version || 0);
      const live = Number(this.model.live_published_version || 0);
      return published > live;
    },
    fromMonitorHint() {
      return this.$route && this.$route.query && String(this.$route.query.fromMonitor) === '1';
    },
    /** 对比版本A（按版本号升序，先选的为A） */
    compareVersionA() {
      if (this.compareSelection.length < 2) return null;
      const vers = this.compareSelection.map(id => this.paramVersions.find(v => v.id === id)).filter(Boolean);
      return vers.sort((a, b) => a.version - b.version)[0] || null;
    },
    compareVersionB() {
      if (this.compareSelection.length < 2) return null;
      const vers = this.compareSelection.map(id => this.paramVersions.find(v => v.id === id)).filter(Boolean);
      return vers.sort((a, b) => a.version - b.version)[1] || null;
    },
    ...mapState('strategy', ['templateList']),
    isManualAllocationModel() {
      return isManualAllocationTemplateCode(this.model.template_code);
    },
    /** 有效的选择器类型（优先 resolved_params） */
    effectiveSelectorType() {
      if (this.model.resolved_params && this.model.resolved_params.selector) {
        return this.model.resolved_params.selector.type || null;
      }
      return this.model.selector_type || null;
    },
    /** 有效的选择资产数量 */
    effectiveAssetSelectionCount() {
      if (this.model.resolved_params && this.model.resolved_params.selector && this.model.resolved_params.selector.params) {
        return this.model.resolved_params.selector.params.asset_selection_count || this.model.asset_selection_count;
      }
      return this.model.asset_selection_count;
    },
    /** 有效的最小历史天数 */
    effectiveMinHistoryDays() {
      if (this.model.resolved_params && this.model.resolved_params.selector && this.model.resolved_params.selector.params) {
        return this.model.resolved_params.selector.params.min_history_days || this.model.min_history_days;
      }
      return this.model.min_history_days;
    },
    /** 有效的控制器代码（优先 resolved_params） */
    effectiveControllerCode() {
      if (this.model.resolved_params && this.model.resolved_params.controller) {
        return this.model.resolved_params.controller.code || null;
      }
      return this.model.controller_code || null;
    },
    /** 有效的控制器参数（优先 resolved_params.controller.params） */
    effectiveControllerParams() {
      if (this.model.resolved_params && this.model.resolved_params.controller && this.model.resolved_params.controller.params) {
        return this.model.resolved_params.controller.params;
      }
      return this.model.controller_parameters || {};
    },
    /** 当前选择器模板定义（从 Vuex templateList 查找，优先 effectiveSelectorType） */
    currentSelectorTemplate() {
      const selType = this.effectiveSelectorType;
      if (!selType) return null;
      const code = selType.startsWith('sel_') ? selType : 'sel_' + selType;
      return this.templateList.find(t => t.code === code) || null;
    },
    /** 当前控制器模板定义（优先 effectiveControllerCode） */
    currentControllerTemplate() {
      const ctrlCode = this.effectiveControllerCode;
      if (!ctrlCode) return null;
      return this.templateList.find(t => t.code === ctrlCode) || null;
    },
    /** 选择器模板 schema 声明的参数定义列表 */
    selectorTemplateDefs() {
      const tpl = this.currentSelectorTemplate;
      if (!tpl || !tpl.parameters) return [];
      // 排除已在顶层展示的通用参数
      const topLevel = new Set(['asset_selection_count', 'min_history_days']);
      return tpl.parameters.filter(p => !topLevel.has(p.name));
    },
    /** 合并的选择器参数值（优先 resolved_params.selector.params，回退到 model.selector_parameters 或 parameters.selector_parameters） */
    mergedSelectorParams() {
      // 优先使用 resolved_params
      if (this.model.resolved_params && this.model.resolved_params.selector && this.model.resolved_params.selector.params) {
        return this.model.resolved_params.selector.params;
      }
      if (this.model.selector_parameters && Object.keys(this.model.selector_parameters).length > 0) {
        return this.model.selector_parameters;
      }
      const nested = (this.model.parameters || {}).selector_parameters;
      if (nested && typeof nested === 'object') return nested;
      return null;
    },
    /**
     * 当前分配策略参数（优先使用 resolved_params.allocator，回退到手动过滤 model.parameters）
     * resolved_params 由后端 resolve_full_params() 生成，已去除 selector_parameters 子字典。
     * 仍需前端过滤控制器相关字段（当无控制器时），因为 allocator params 可能包含模板声明的 vol_reset 等字段。
     */
    currentAllocatorParams() {
      let raw = {};
      if (this.model.resolved_params && this.model.resolved_params.allocator) {
        raw = { ...this.model.resolved_params.allocator };
      } else {
        raw = { ...(this.model.parameters || {}) };
        delete raw.selector_parameters;
      }
      
      // 模板特定隐藏参数
      if (isRiskBudgetTargetVolTemplateCode(this.model.template_code)) {
        RISK_BUDGET_TARGET_VOL_HIDDEN_PARAMETER_NAMES.forEach(k => delete raw[k]);
      } else if (isSharpeRiskBudgetTemplateCode(this.model.template_code)) {
        SHARPE_RISK_BUDGET_HIDDEN_SCHEMA_PARAMETER_NAMES.forEach(k => delete raw[k]);
      }
      
      // 未启用控制器时，过滤掉控制器相关参数
      const noController = !(this.model.resolved_params && this.model.resolved_params.controller && this.model.resolved_params.controller.enabled) && !this.model.controller_code;
      if (noController) {
        CONTROLLER_RELATED_PARAMS.forEach(k => delete raw[k]);
      }
      
      return raw;
    }
  },
  created() {
    this.modelId = this.isDialog ? this.id : this.$route.params.id;
    this.loadData();
  },
  watch: {
    id(newVal) {
      if (this.isDialog && newVal) {
        this.modelId = newVal;
        this.loadData();
      }
    }
  },
  methods: {
    async loadData() {
      this.loading = true;
      try {
        // 确保模板列表已加载（供选择器/控制器参数标签查找）
        await this.$store.dispatch('strategy/fetchTemplateList');
        this.model = await this.$store.dispatch('strategy/fetchStrategyModel', this.modelId);
        this.loadPresetNames(this.model.template_code);
        await this.refreshBacktestGate();
        await this.loadBacktestHistory();
        await this.loadParamVersions();
      } catch (error) {
        this.$message.error('加载数据失败');
      } finally {
        this.loading = false;
      }
    },
    /** 拉取当前模板的预设清单（只用于把 preset_code 翻成可读名称） */
    async loadPresetNames(templateCode) {
      if (!templateCode) return;
      try {
        const res = await getStrategyPresets(templateCode);
        const map = {};
        ((res && res.data) || []).forEach(item => { map[item.code] = item; });
        this.presetNameMap = map;
      } catch (error) {
        console.error('加载预设清单失败:', error);
      }
    },
    /** 实时门禁：与预设 resolve 共用同一套校验；接口失败时放行（后端回测前仍 enforce_static_contract） */
    async refreshBacktestGate() {
      if (!this.model || !this.model.template_code) {
        this.backtestGateIssues = [];
        return;
      }
      try {
        const res = await validateStrategyConfig({
          template_code: this.model.template_code,
          asset_codes: this.model.asset_codes || [],
          parameters: this.model.parameters || {},
          min_history_days: this.model.min_history_days
        });
        const data = (res && res.data) || {};
        const issues = data.issues || [];
        this.backtestGateIssues = issues.filter(
          i => i.level === 'blocking_error' || i.level === 'data_error'
        );
      } catch (error) {
        console.error('回测门禁校验失败:', error);
        this.backtestGateIssues = [];
      }
    },
    async loadBacktestHistory(keepPosition = false) {
      try {
        if (!keepPosition) {
          this.backtestPagination.skip = 0;
        }
        const res = await this.$store.dispatch('strategy/fetchBacktestHistory', {
          modelId: this.modelId,
          skip: this.backtestPagination.skip,
          limit: this.backtestPagination.limit
        });
        this.backtestHistory = res;
        if (res.length === this.backtestPagination.limit) {
          this.backtestPagination.total = this.backtestPagination.skip + this.backtestPagination.limit + 1;
        } else {
          this.backtestPagination.total = this.backtestPagination.skip + res.length;
        }
      } catch (error) {
        console.error('加载回测历史失败:', error);
      }
    },
    handleBacktestPageChange(page) {
      this.backtestPagination.skip = (page - 1) * this.backtestPagination.limit;
      this.loadBacktestHistory(true);
    },
    async handlePublish() {
      this.$confirm('确定要发布该策略吗？发布后模板、资产、参数、窗口、调仓频率将全部冻结，下游组合与回测均按此版本运行；如需修改必须先取消发布。', '发布', {
        confirmButtonText: '确定发布',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await this.$store.dispatch('strategy/publishModel', this.modelId);
          this.$message.success('发布成功，配置已冻结');
          await this.loadData();
        } catch (error) {
          this.$message.error('发布失败：' + (error.response?.data?.detail || error.message));
        }
      }).catch(() => {});
    },
    async handleUnpublish() {
      const liveHint = this.model.live_publish_enabled
        ? '将先取消实盘并从日常监控下架；'
        : '';
      try {
        await this.$confirm(
          `确认取消发布「${this.model.name || this.modelId}」？${liveHint}若正被实盘组合使用，需先取消组合实盘并调整成员；模型回到草稿可编辑，版本号与历史记录保留。`,
          '取消发布',
          { type: 'warning', confirmButtonText: '确定取消发布', cancelButtonText: '保留发布' }
        );
      } catch {
        return;
      }
      this.unpublishing = true;
      try {
        await this.$store.dispatch('strategy/unpublishModel', {
          modelId: this.modelId,
          params: { source: 'strategy_model_detail', operator: this.liveOperator() }
        });
        this.$message.success('已取消发布，模型回到草稿');
        await this.loadData();
      } catch (error) {
        this.$message.error(error.response?.data?.detail || error.message || '取消发布失败');
      } finally {
        this.unpublishing = false;
      }
    },
    liveOperator() {
      return this.$store.getters['user/userName']
        || this.$store.state.user?.userInfo?.name
        || this.$store.state.user?.userInfo?.username
        || 'unknown';
    },
    async handleLivePublish() {
      if (!this.canOperateLivePublish) return;
      this.$confirm(
        '确认将该策略实盘发布？新版本将于次交易日生效；符合条件的策略可与「日常监控」关联。',
        '实盘发布',
        { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
      ).then(async () => {
        this.livePublishing = true;
        try {
          await this.$store.dispatch('strategy/livePublishModel', {
            modelId: this.modelId,
            data: { source: 'strategy_model_detail', operator: this.liveOperator() }
          });
          this.$message.success('实盘发布成功');
          await this.loadData();
        } catch (error) {
          this.$message.error(error.response?.data?.detail || error.message || '实盘发布失败');
        } finally {
          this.livePublishing = false;
        }
      }).catch(() => {});
    },
    async handleLiveUnpublish() {
      this.$confirm(`确认取消「${this.model.name || this.modelId}」的实盘？取消后将从日常监控下架，历史数据与操作记录保留。`, '取消实盘', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        this.liveUnpublishing = true;
        try {
          await this.$store.dispatch('strategy/liveUnpublishModel', {
            modelId: this.modelId,
            params: { source: 'strategy_model_detail', operator: this.liveOperator() }
          });
          this.$message.success('已取消实盘发布');
          await this.loadData();
        } catch (error) {
          this.$message.error(error.response?.data?.detail || error.message || '操作失败');
        } finally {
          this.liveUnpublishing = false;
        }
      }).catch(() => {});
    },
    async handleLiveRepublish() {
      this.$confirm('将最新发布版本同步到实盘？实盘快照将重建为当前发布快照，于次交易日生效。', '同步实盘版本', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        this.liveRepublishing = true;
        try {
          await this.$store.dispatch('strategy/livePublishModel', {
            modelId: this.modelId,
            data: {
              source: 'strategy_model_detail',
              operator: this.liveOperator(),
              rebalance_mode: this.model.live_rebalance_mode,
              volatility_threshold: this.model.live_volatility_threshold
            }
          });
          this.$message.success('已同步到最新实盘');
          await this.loadData();
        } catch (error) {
          this.$message.error(error.response?.data?.detail || error.message || '同步失败');
        } finally {
          this.liveRepublishing = false;
        }
      }).catch(() => {});
    },
    handleEdit() {
      if (this.isPublishedModel) {
        this.$message.warning('策略已发布，配置已冻结；请先取消发布再编辑');
        return;
      }
      this.editDialogVisible = true;
    },
    handleEditSuccess() {
      this.editDialogVisible = false;
      this.loadData();
    },
    viewBacktestDetail(record) {
      this.currentBacktestRecord = record;
      this.backtestDetailVisible = true;
    },
    async generateReport() {
      this.reportLoading = true;
      try {
        const res = await generatePortfolioReport({ model_id: this.modelId });
        this.portfolioReport = res.data || res;
      } catch (e) {
        const msg = e.response?.data?.detail || e.message || '生成报告失败';
        this.$message.error('组合评估报告生成失败：' + msg);
      } finally {
        this.reportLoading = false;
      }
    },
    async saveRemark(record) {
      try {
        await updateBacktestRemark(this.modelId, record.id, this.editingRemark);
        this.$message.success('备注已更新');
        this.editingRecordId = null;
        this.editingRemark = '';
        await this.loadBacktestHistory(true);
      } catch (err) {
        this.$message.error(err.response?.data?.detail || err.message || '更新失败');
      }
    },
    async loadParamVersions() {
      try {
        const res = await getParamVersions(this.modelId);
        this.paramVersions = Array.isArray(res) ? res : (res.data || []);
      } catch (e) {
        console.error('加载参数版本失败:', e);
      }
    },
    toggleVersionDetail(verId) {
      this.expandedVersionId = this.expandedVersionId === verId ? null : verId;
    },
    /** 切换版本对比选中状态（最多选2个） */
    toggleCompareSelect(verId) {
      const idx = this.compareSelection.indexOf(verId);
      if (idx > -1) {
        this.compareSelection.splice(idx, 1);
      } else {
        if (this.compareSelection.length >= 2) {
          this.compareSelection.shift();
        }
        this.compareSelection.push(verId);
      }
    },
    /** 打开版本对比弹窗 */
    openVersionCompare() {
      if (this.compareSelection.length === 2) {
        this.compareDialogVisible = true;
      }
    },
    /**
     * 过滤分配策略参数：移除不应显示的控制器相关字段和模板特定隐藏字段
     * 用于历史版本显示，与 currentAllocatorParams 逻辑一致
     */
    filterAllocatorParams(allocatorParams, controllerCode, templateCode) {
      if (!allocatorParams) return {};
      const result = { ...allocatorParams };
      
      // 模板特定隐藏参数
      if (templateCode === 'risk_budget_target_vol' || templateCode === 'vol_scaled_budget') {
        // lookback_days, min_history_days 等已固化，不展示
        ['lookback_days', 'min_history_days', 'vol_reset_threshold'].forEach(k => delete result[k]);
      } else if (templateCode === 'sharpe_risk_budget') {
        ['target_vol', 'max_leverage', 'select_count', 'vol_windows', 'sharp_windows',
         'vol_reset_threshold', 'vol_trigger_threshold', 'monitor_start_days', 'min_history_days'].forEach(k => delete result[k]);
      }
      
      // 未启用控制器时，移除所有控制器相关参数
      if (!controllerCode) {
        CONTROLLER_RELATED_PARAMS.forEach(k => delete result[k]);
      }
      
      return result;
    },
    getParamLabel(key) {
      // 优先使用后端返回的标签
      if (this.model.parameter_labels && this.model.parameter_labels[key]) {
        return this.model.parameter_labels[key];
      }
      // 与后端 schema 定义对齐的标准标签
      const map = {
        // === 通用参数 ===
        lookback_days: '历史数据回看期',
        rebalance_frequency: '调仓频率',
        
        // === 风险平价 / 均值方差 ===
        min_weight: '单资产最小权重',
        max_weight: '单资产最大权重',
        maxiter: '最大迭代次数',
        cov_method: '协方差估计方法',
        optimization_mode: '优化模式',
        target_return: '目标收益率',
        
        // === 波动率控制 ===
        target_vol: '目标年化波动率',
        vol_windows: '波动率计算窗口',
        vol_window_short: '短期窗口',
        vol_window_medium: '中期窗口',
        vol_window_long: '长期窗口',
        vol_control_type: '波动率控制器类型',
        vc_short: '波动率控制短窗口',
        vc_long: '波动率控制长窗口',
        enable_vol_reset: '启用波动率阈值重置',
        vol_reset_threshold: '波动率重置阈值',
        vol_trigger_threshold: '波动率触发阈值',
        monitor_start_days: '监控起始天数',
        
        // === 风险预算 ===
        risk_budget: '风险预算',
        budget_source: '预算来源模式',
        budget_allocation_method: '预算分配方式',
        max_total_leverage: '最大杠杆倍数',
        single_cap: '资产权重约束',
        max_weight_dict: '资产权重约束',
        weight_caps: '资产权重约束',
        
        // === 资产选择 ===
        select_count: '选择资产数量',
        
        // === 其他 ===
        manual_weight_adjustments: '手动权重调整',
        ema_halflife: 'EMA半衰期',
      };
      return map[key] || key;
    },
    getSelectorParamLabel(key) {
      // 选择器参数标签映射
      const map = {
        // sharpe 特有
        sharp_windows: '夏普率窗口',
        tie_break_window: '决胜窗口',
        // momentum_reversal 特有
        momentum_windows: '动量窗口',
        macd_windows: 'MACD窗口',
        reversal_windows: '反转窗口',
        n_momentum: '动量资产数',
        n_reversal: '反转资产数',
        // etf_rotation 特有
        sub_strategy: '子策略',
        lookback_days: '回看天数',
        return_cutoff_pct: '收益率剔除比例',
        bias_threshold: '乖离率阈值',
        risk_index_code: '风控指数代码',
        risk_drop_threshold: '风控跌幅阈值',
        // cross_sectional_momentum 特有
        momentum_window: '动量回顾窗口',
        // cross_sectional_long_short 特有
        cs_lookback_months: '截面动量窗口(月)',
        // trend_following 特有
        tf_lookback: '趋势跟踪窗口',
        tf_threshold: '趋势入场阈值',
        // 通用
        min_history_days: '最小历史数据要求',
        asset_selection_count: '选择资产数量',
      };
      return map[key] || key;
    },
    formatParamVal(value) {
      if (value === null || value === undefined) return '-';
      if (typeof value === 'boolean') return value ? '是' : '否';
      if (Array.isArray(value)) return value.join(', ');
      if (typeof value === 'object') return JSON.stringify(value, null, 2);
      return String(value);
    },
    getStatusType(status) {
      const map = {
        '草稿': 'info', '已发布': 'success', '已归档': '',
        'draft': 'info', 'published': 'success', 'archived': ''
      };
      return map[status] || 'info';
    },
    getStatusLabel(status) {
      const map = {
        '草稿': '草稿', '已发布': '已发布', '已归档': '已归档',
        'draft': '草稿', 'published': '已发布', 'archived': '已归档'
      };
      return map[status] || status;
    },
    getReturnColor(value) {
      return value >= 0 ? '#67c23a' : '#f56c6c';
    },
    getSelectorName(selectorType) {
      const map = {
        'sharpe': '夏普率综合打分',
        'momentum_reversal': '动量+反转(7+1)',
        'etf_rotation': 'ETF轮动',
        'cross_sectional_momentum': '截面动量',
        'cross_sectional_long_short': '截面多空',
        'trend_following': '趋势跟踪',
        // 兼容旧名称
        'momentum': '动量选择器',
        'hybrid': '混合动量选择器',
        'reversal': '反转选择器',
      };
      return map[selectorType] || selectorType || '未配置';
    },
    /** 获取控制器中文名称 */
    getControllerName(controllerCode) {
      if (!controllerCode) return '未配置';
      const tpl = this.templateList.find(t => t.code === controllerCode);
      if (tpl && tpl.name) return tpl.name;
      const map = {
        'ctrl_rolling_vol': '滚动波动率控制',
        'ctrl_dual_window_vol': '双窗口波动率控制',
        'rolling_vol': '滚动波动率控制',
        'dual_window_vol': '双窗口波动率控制',
      };
      return map[controllerCode] || controllerCode;
    },
    /** 获取控制器参数中文标签（从模板 schema 读取） */
    getControllerParamLabel(key) {
      const tpl = this.currentControllerTemplate;
      if (tpl && tpl.parameters) {
        const p = tpl.parameters.find(p => p.name === key);
        if (p && p.label) return p.label;
      }
      // 回退硬编码标签
      const map = {
        target_vol: '目标年化波动率',
        vol_windows: '波动率计算窗口',
        vol_trigger_threshold: '波动率触发阈值',
        vol_reset_threshold: '波动率重置阈值',
        enable_vol_reset: '启用波动率阈值重置',
        vc_short: '波动率控制短窗口',
        vc_long: '波动率控制长窗口',
        monitor_start_days: '监控起始天数',
      };
      return map[key] || key;
    },
    /** 从模板 schema 获取选择器参数值并格式化展示 */
    getSelectorParamDisplay(paramName) {
      const params = this.mergedSelectorParams || {};
      const val = params[paramName];
      return this.formatParamVal(val);
    },
    /** 获取版本类型CSS类名（用于左侧色条） */
    getVersionTypeClass(ver) {
      const summary = (ver.change_summary || '').toLowerCase();
      if (summary.includes('初始创建')) return 'version-initial';
      if (summary.includes('资产')) return 'version-asset';
      return 'version-param';
    },
    /** 获取版本tag类型 */
    getVersionTagType(ver) {
      if (ver.version === 1) return 'primary';
      const summary = (ver.change_summary || '').toLowerCase();
      if (summary.includes('资产')) return 'success';
      return 'warning';
    },
    formatDate(date) {
      return date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-';
    },
    formatDateShort(date) {
      return date ? dayjs(date).format('YYYY-MM-DD') : '-';
    }
  }
};
</script>

<style scoped>
.page-container {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #ebeef5;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-right ::v-deep .el-button + .el-button,
.header-actions ::v-deep .el-button + .el-button {
  margin-left: 0;
}

.header-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}

.info-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

/* 生命周期卡片 */
.lifecycle-card {
  margin-bottom: 16px;
}

.current-params-section {
  padding: 16px;
  background: #fafafa;
  border-radius: 6px;
  margin-bottom: 16px;
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}

.section-label i {
  margin-right: 6px;
  color: #409EFF;
}

.param-group {
  margin-bottom: 16px;
}

.param-group:last-child {
  margin-bottom: 0;
}

.param-group-label {
  font-size: 12px;
  color: #606266;
  font-weight: 500;
  margin-bottom: 8px;
  padding-left: 8px;
  border-left: 3px solid #409EFF;
}

/* 历史版本区域 */
.history-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}

.history-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}

.history-header i {
  color: #409EFF;
  font-size: 16px;
}

.version-card {
  cursor: pointer;
  transition: all 0.2s;
  border-left: 3px solid #e4e7ed;
}
.version-card.version-selected {
  border-left-color: #409eff;
  background: #ecf5ff;
}

.version-card:hover {
  transform: translateX(2px);
}

.version-card.version-initial {
  border-left-color: #409EFF;
}

.version-card.version-param {
  border-left-color: #e6a23c;
}

.version-card.version-asset {
  border-left-color: #67c23a;
}

.version-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.version-info {
  display: flex;
  align-items: center;
}

.version-summary {
  font-size: 12px;
  color: #606266;
}

.version-badges {
  display: flex;
  align-items: center;
}

.version-detail {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}

.detail-group {
  margin-bottom: 12px;
}

.detail-group-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 6px;
  font-weight: 500;
}

.detail-assets {
  font-size: 11px;
  color: #606266;
  margin-top: 8px;
}

/* 回测卡片 */
.history-card {
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}

.backtest-card {
  margin-bottom: 8px;
}

.backtest-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.backtest-period {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
}

.backtest-metrics {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}

.metric-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}

.metric-label {
  color: #909399;
}

.metric-value {
  font-weight: 500;
  color: #303133;
}

.backtest-remark {
  font-size: 11px;
  color: #606266;
  padding: 6px 10px;
  background: #f5f7fa;
  border-radius: 4px;
  margin-bottom: 8px;
}

.backtest-actions {
  display: flex;
  gap: 12px;
}

/* 策略报告 */
.metrics-row {
  margin-top: 8px;
}

.metric-card {
  text-align: center;
  padding: 12px 8px;
  background: #f5f7fa;
  border-radius: 4px;
}

.metric-card .metric-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 6px;
}

.metric-card .metric-value {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.metric-card .metric-sub {
  margin-top: 4px;
  font-size: 11px;
  color: #909399;
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: #909399;
}

.empty-state p {
  margin-top: 12px;
  font-size: 13px;
}
</style>
