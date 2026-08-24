<template>
  <div class="product-page">
    <!-- 顶部标题 -->
    <div class="page-header">
      <h2 class="page-title">产品管理</h2>
      <p class="page-desc">收益凭证产品条款配置与生命周期管理</p>
    </div>

    <!-- 筛选 + 操作 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-select v-model="filterType" placeholder="全部类型" clearable size="small" @change="loadProducts" style="width: 150px;">
          <el-option v-for="t in productTypes" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="全部状态" clearable size="small" @change="loadProducts" style="width: 120px;">
          <el-option v-for="s in productStatuses" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <el-button type="primary" icon="el-icon-plus" size="small" @click="showCreateDialog">新增产品</el-button>
        <el-button icon="el-icon-refresh" size="small" @click="loadProducts" :loading="loading">刷新</el-button>
      </div>
    </div>

    <!-- 产品表格 -->
    <div class="table-area">
      <vxe-table
        :data="products"
        :loading="loading"
        border
        stripe
        height="520"
        :scroll-y="{enabled: true, gt: 0}"
        show-overflow="title"
      >
        <vxe-column field="product_id" title="产品编号" width="120" />
        <vxe-column field="name" title="产品名称" min-width="150" />
        <vxe-column field="type" title="结构类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTagColor(row.type)" effect="plain">{{ typeLabel(row.type) }}</el-tag>
          </template>
        </vxe-column>
        <vxe-column field="underlying" title="挂钩标的" min-width="110" />
        <vxe-column field="principal" title="名义本金" min-width="130" align="right">
          <template #default="{ row }">{{ formatNum(row.principal) }}</template>
        </vxe-column>
        <vxe-column field="maturity_date" title="到期日" width="110" />
        <vxe-column field="status" title="存续状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagColor(row.status)" effect="dark">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </vxe-column>
        <vxe-column title="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button type="text" size="small" @click="showDetailDialog(row)">条款</el-button>
            <el-button type="text" size="small" @click="showEditDialog(row)">编辑</el-button>
            <el-button type="text" size="small" style="color: #f56c6c;" @click="handleDelete(row)">删除</el-button>
          </template>
        </vxe-column>
        <template #empty>
          <el-empty description="暂无产品，点击右上角“新增产品”创建首个收益凭证" :image-size="90">
            <el-button type="primary" size="small" icon="el-icon-plus" @click="showCreateDialog">新增产品</el-button>
          </el-empty>
        </template>
      </vxe-table>
    </div>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      :title="editMode ? '编辑产品条款' : '新增收益凭证'"
      :visible.sync="formVisible"
      width="820px"
      :close-on-click-modal="false"
      top="4vh"
      custom-class="product-dialog"
    >
      <el-form ref="productFormRef" :model="form" :rules="formRules" label-width="110px" size="small" class="product-form">
        <!-- 表单提示 -->
        <div class="form-hint">
          <i class="el-icon-info"></i>
          <span>带 <span class="required-star">*</span> 的字段为必填项。选择结构类型后，将显示对应的产品条款参数。</span>
        </div>
        <!-- 基本信息 -->
        <div class="form-section">
          <div class="form-section-header">
            <i class="el-icon-document"></i>
            <span>基本信息</span>
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="产品编号" prop="product_id" required>
                <el-input v-model="form.product_id" :disabled="editMode" placeholder="如 SNOW_001" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="产品名称" prop="name" required>
                <el-input v-model="form.name" placeholder="如 沪深300雪球1号" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="结构类型" prop="type" required>
                <el-select v-model="form.type" placeholder="选择产品结构" style="width: 100%;">
                  <el-option-group v-for="g in typeGroups" :key="g.label" :label="g.label">
                    <el-option v-for="t in g.items" :key="t.value" :label="t.label" :value="t.value" />
                  </el-option-group>
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="挂钩标的" prop="underlying" required>
                <el-select v-model="form.underlying" filterable placeholder="选择标的资产" style="width: 100%;">
                  <el-option v-for="a in availableAssets" :key="a.asset_code" :value="a.asset_code"
                    :label="`${a.asset_code} (${a.count}条行情)`" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="名义本金(元)" prop="principal" required>
                <el-input-number v-model="form.principal" :min="10000" :step="100000" :precision="0" style="width: 100%;" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="发行日" prop="issue_date" required>
                <el-date-picker v-model="form.issue_date" type="date" value-format="yyyy-MM-dd" style="width: 100%;" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="到期日" prop="maturity_date" required>
                <el-date-picker v-model="form.maturity_date" type="date" value-format="yyyy-MM-dd" style="width: 100%;" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 产品条款参数 -->
        <template v-if="form.type && hasParams(form.type)">
          <!-- 障碍类共享参数 -->
          <div class="form-section" v-if="isBarrierType(form.type)">
            <div class="form-section-header">
              <i class="el-icon-aim"></i>
              <span>标的基准参数</span>
              <el-tooltip content="期初参考价为产品发行日的标的收盘价，是所有障碍水平和行权条件的计算基准" placement="top">
                <i class="el-icon-question" style="margin-left: 6px; color: #909399; cursor: help;"></i>
              </el-tooltip>
            </div>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item required>
                  <template #label>
                    <span>期初价 S₀</span>
                  </template>
                  <el-input-number v-model="form.params.spot_ref" :min="0.01" :precision="4" :step="100" style="width: 100%;" placeholder="发行日收盘价" />
                </el-form-item>
              </el-col>
              <el-col :span="12" v-if="hasObsFreq(form.type)">
                <el-form-item label="观察频率">
                  <el-select v-model="form.params.obs_freq" style="width: 100%;">
                    <el-option label="每日观察 (Daily)" value="daily" />
                    <el-option label="周度观察 (Weekly)" value="weekly" />
                    <el-option label="月度观察 (Monthly)" value="monthly" />
                    <el-option label="季度观察 (Quarterly)" value="quarterly" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 雪球 Snowball ===== -->
          <div class="form-section" v-if="form.type === 'snowball'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>雪球条款 (Snowball / Autocall)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>敲出水平</span>
                    <el-tooltip content="相对期初价的比例。标的涨至此水平产品提前终止并获得票息" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.knock_out" :min="0.80" :max="2.0" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ pctHint(form.params.knock_out) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>敲入水平</span>
                    <el-tooltip content="相对期初价的比例。标的跌至此水平将触发敲入，本金面临亏损风险" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.knock_in" :min="0.30" :max="1.0" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ pctHint(form.params.knock_in) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>年化票息</span>
                    <el-tooltip content="未敲入且到期或敲出时，投资者获得的年化收益率" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.coupon_year" :min="0" :max="0.5" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.coupon_year) }}</div>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>恢复票息</span>
                    <el-tooltip content="敲入后标的恢复至敲出水平时的年化票息（降敲雪球常用）" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.recovery_coupon_rate" :min="0" :max="0.5" :step="0.01" :precision="4" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="控制变量法">
                  <el-switch v-model="form.params.use_control_variate" active-text="启用" inactive-text="关闭" />
                  <div class="param-hint">MC方差缩减技术</div>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 凤凰 Phoenix ===== -->
          <div class="form-section" v-if="form.type === 'phoenix'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>凤凰条款 (Phoenix / Autocallable Coupon)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>敲出水平</span>
                    <el-tooltip content="标的涨至此水平产品提前终止" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.knock_out" :min="0.80" :max="2.0" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ pctHint(form.params.knock_out) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>敲入水平</span>
                    <el-tooltip content="标的跌至此水平触发敲入" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.knock_in" :min="0.30" :max="1.0" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ pctHint(form.params.knock_in) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>每期票息</span>
                    <el-tooltip content="每个观察期如未敲入则派发的票息（占本金比例）" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.coupon_per_period" :min="0" :max="0.1" :step="0.001" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.coupon_per_period) }} /期</div>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item label="记忆票息">
                  <el-switch v-model="form.params.memory_flag" active-text="启用" inactive-text="关闭" />
                  <div class="param-hint">未派发票息在后续期追补</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="控制变量法">
                  <el-switch v-model="form.params.use_control_variate" active-text="启用" inactive-text="关闭" />
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 鲨鱼鳍 Sharkfin ===== -->
          <div class="form-section" v-if="form.type === 'sharkfin'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>鲨鱼鳍条款 (Sharkfin / KO Call)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>敲出比例</span>
                    <el-tooltip content="向上敲出障碍水平 = 期初价 × 敲出比例。标的突破此水平则看涨期权失效" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.knock_out_ratio" :min="1.0" :max="2.0" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ pctHint(form.params.knock_out_ratio) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>参与率</span>
                    <el-tooltip content="投资者参与标的涨幅的比例。80%表示标的涨10%时投资者获得8%" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.participation" :min="0" :max="3.0" :step="0.05" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.participation) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>保底比例</span>
                    <el-tooltip content="最低保障的本金比例。1.0 = 100%保本，0.95 = 最多亏5%" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.guaranteed" :min="0" :max="1.1" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.guaranteed) }}</div>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 双鲨 Double Barrier ===== -->
          <div class="form-section" v-if="form.type === 'double_barrier'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>双鲨条款 (Double Barrier / DKO)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>下界比例</span>
                    <el-tooltip content="向下敲出障碍 = 期初价 × 下界比例" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.barrier_low" :min="0.3" :max="1.0" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ pctHint(form.params.barrier_low) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>上界比例</span>
                    <el-tooltip content="向上敲出障碍 = 期初价 × 上界比例" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.barrier_high" :min="1.0" :max="2.0" :step="0.01" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ pctHint(form.params.barrier_high) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>参与率</span>
                    <el-tooltip content="存活期间投资者对标的涨幅的参与比例" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.participation" :min="0" :max="3.0" :step="0.05" :precision="4" style="width: 100%;" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>保底比例</span>
                    <el-tooltip content="本金保障比例" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.guaranteed" :min="0" :max="1.1" :step="0.01" :precision="4" style="width: 100%;" />
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 二元 Binary ===== -->
          <div class="form-section" v-if="form.type === 'binary'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>二元条款 (Binary / Digital)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>行权价 K</span>
                    <el-tooltip content="到期时标的价格高于K获得高收益，否则获得低收益" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.strike" :min="0" :precision="4" style="width: 100%;" placeholder="默认=期初价" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>高收益率</span>
                    <el-tooltip content="标的高于行权价时的年化收益率" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.high_return" :min="0" :max="1" :step="0.005" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.high_return) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>低收益率</span>
                    <el-tooltip content="标的低于行权价时的保底年化收益率" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.low_return" :min="0" :max="0.2" :step="0.001" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.low_return) }}</div>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 价差 Spread ===== -->
          <div class="form-section" v-if="form.type === 'spread'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>价差条款 (Bull/Bear Spread)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>下限行权价</span>
                    <el-tooltip content="看涨价差的买入Call行权价 / 看跌价差的买入Put行权价" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.strike_low" :min="0" :precision="4" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>上限行权价</span>
                    <el-tooltip content="看涨价差的卖出Call行权价 / 看跌价差的卖出Put行权价" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.strike_high" :min="0" :precision="4" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="策略方向">
                  <el-select v-model="form.params.direction" style="width: 100%;">
                    <el-option label="看涨价差 (Bull)" value="bull" />
                    <el-option label="看跌价差 (Bear)" value="bear" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 固定收益 Fixed ===== -->
          <div class="form-section" v-if="form.type === 'fixed'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>固收条款 (Fixed Income)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>年化票息率</span>
                    <el-tooltip content="持有期间的年化固定收益率，按实际天数计息" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.coupon_rate" :min="0" :max="0.2" :step="0.005" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.coupon_rate) }}</div>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 亚式 Asian ===== -->
          <div class="form-section" v-if="form.type === 'asian'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>亚式条款 (Asian Option)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>行权价 K</span>
                    <el-tooltip content="期权行权价格。到期时比较的是标的路径均价与K" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.strike" :min="0" :precision="4" style="width: 100%;" placeholder="默认=期初价" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="均价类型">
                  <el-select v-model="form.params.avg_type" style="width: 100%;">
                    <el-option label="算术平均 (Arithmetic)" value="arithmetic" />
                    <el-option label="几何平均 (Geometric)" value="geometric" />
                  </el-select>
                  <div class="param-hint">算术平均无解析解，使用MC</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>保底比例</span>
                    <el-tooltip content="本金保障比例，1.0=100%保本" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.guaranteed" :min="0" :max="1.1" :step="0.01" :precision="4" style="width: 100%;" />
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 区间累积 Range Accrual ===== -->
          <div class="form-section" v-if="form.type === 'range_accrual'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>区间累积条款 (Range Accrual)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>区间下界</span>
                    <el-tooltip content="累积计息区间的下界绝对值" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.lower_barrier" :min="0" :precision="4" style="width: 100%;" placeholder="S₀×0.95" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>区间上界</span>
                    <el-tooltip content="累积计息区间的上界绝对值" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.upper_barrier" :min="0" :precision="4" style="width: 100%;" placeholder="S₀×1.05" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>年化票息</span>
                    <el-tooltip content="标的在区间内的每日按年化票息累积计息" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.coupon_rate" :min="0" :max="0.2" :step="0.005" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.coupon_rate) }}</div>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 可赎回固收 Callable Fixed ===== -->
          <div class="form-section" v-if="form.type === 'callable_fixed'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>可赎回固收条款 (Callable Bond)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>年化票息</span>
                    <el-tooltip content="固定年化票息率" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.coupon_rate" :min="0" :max="0.2" :step="0.005" :precision="4" style="width: 100%;" />
                  <div class="param-hint">{{ annualPctHint(form.params.coupon_rate) }}</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>首次可赎回</span>
                    <el-tooltip content="发行后经过多少年发行方可行使赎回权" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.call_date" :min="0.25" :max="10" :precision="2" :step="0.25" style="width: 100%;" />
                  <div class="param-hint">单位: 年</div>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>赎回价格</span>
                    <el-tooltip content="发行方赎回时支付的金额（含应计利息），空=本金面值" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.call_price" :min="0" :precision="0" style="width: 100%;" placeholder="默认=本金" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>利率波动率</span>
                    <el-tooltip content="用于赎回期权定价的利率波动率参数(Hull-White模型)" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.rate_vol" :min="0.001" :max="0.1" :step="0.005" :precision="4" style="width: 100%;" />
                  <div class="param-hint">典型值: 0.5%~2%</div>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- ===== 数字区间 Digital Range ===== -->
          <div class="form-section" v-if="form.type === 'digital_range'">
            <div class="form-section-header">
              <i class="el-icon-s-flag"></i>
              <span>数字区间条款 (Digital Range)</span>
            </div>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>区间下界</span>
                    <el-tooltip content="到期时标的价格在[下界,上界]内则获得固定收益" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.lower" :min="0" :precision="4" style="width: 100%;" placeholder="S₀×0.95" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>区间上界</span>
                    <el-tooltip content="到期时标的价格需低于此值" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.upper" :min="0" :precision="4" style="width: 100%;" placeholder="S₀×1.05" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>固定收益(元)</span>
                    <el-tooltip content="标的价格落在区间内时的额外固定收益金额" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.payoff" :min="0" :precision="0" style="width: 100%;" placeholder="默认=本金×10%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item>
                  <template #label>
                    <span>保底比例</span>
                    <el-tooltip content="本金保障比例，1.0=100%保本" placement="top">
                      <i class="el-icon-question q-icon"></i>
                    </el-tooltip>
                  </template>
                  <el-input-number v-model="form.params.guaranteed" :min="0" :max="1.1" :step="0.01" :precision="4" style="width: 100%;" />
                </el-form-item>
              </el-col>
            </el-row>
          </div>
        </template>
      </el-form>
      <div slot="footer" class="dialog-footer">
        <el-button size="small" @click="formVisible = false">取 消</el-button>
        <el-button size="small" type="primary" @click="handleSubmit" :loading="submitting">
          {{ editMode ? '保存修改' : '确认创建' }}
        </el-button>
      </div>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog title="产品条款详情" :visible.sync="detailVisible" width="640px">
      <template v-if="detailProduct">
        <el-descriptions title="基本信息" :column="2" border size="small">
          <el-descriptions-item label="产品编号">{{ detailProduct.product_id }}</el-descriptions-item>
          <el-descriptions-item label="产品名称">{{ detailProduct.name }}</el-descriptions-item>
          <el-descriptions-item label="结构类型">
            <el-tag size="small" :type="typeTagColor(detailProduct.type)" effect="plain">{{ typeLabel(detailProduct.type) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="挂钩标的">{{ detailProduct.underlying }}</el-descriptions-item>
          <el-descriptions-item label="名义本金">{{ formatNum(detailProduct.principal) }} 元</el-descriptions-item>
          <el-descriptions-item label="发行日">{{ detailProduct.issue_date }}</el-descriptions-item>
          <el-descriptions-item label="到期日">{{ detailProduct.maturity_date }}</el-descriptions-item>
          <el-descriptions-item label="存续状态">
            <el-tag size="small" :type="statusTagColor(detailProduct.status)" effect="dark">{{ statusLabel(detailProduct.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="敲出日期" v-if="detailProduct.knock_out_date">{{ detailProduct.knock_out_date }}</el-descriptions-item>
        </el-descriptions>
        <el-descriptions v-if="detailProduct.params && Object.keys(detailProduct.params).length"
          title="产品条款参数" :column="3" border size="small" style="margin-top: 16px;">
          <el-descriptions-item v-for="(val, key) in detailProduct.params" :key="key" :label="paramLabel(key)">
            <span class="param-value">{{ formatParamValue(key, val) }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { listOptionProducts, createOptionProduct, updateOptionProduct, deleteOptionProduct, getValuationDataAssets } from '@/api/optionPricing';

const TYPE_MAP = {
  fixed: '固定收益', binary: '二元结构', spread: '价差结构',
  sharkfin: '鲨鱼鳍', snowball: '雪球', phoenix: '凤凰', double_barrier: '双鲨',
  asian: '亚式期权', rainbow: '彩虹期权', range_accrual: '区间累积',
  callable_fixed: '可赎回固收', digital_range: '数字区间',
};
const STATUS_MAP = {
  active: '存续中', pending: '待生效', knocked_out: '已敲出', knocked_in: '已敲入', matured: '已到期'
};
const PARAM_LABELS = {
  spot_ref: '期初参考价 S₀', obs_freq: '观察频率', knock_out: '敲出水平 (KO/S₀)', knock_in: '敲入水平 (KI/S₀)',
  coupon_year: '年化票息', coupon_rate: '年化票息率', recovery_coupon_rate: '恢复票息率',
  coupon_per_period: '每期票息', memory_flag: '记忆票息', use_control_variate: 'MC控制变量',
  knock_out_ratio: '敲出比例 (B/S₀)', participation: '参与率', guaranteed: '本金保障比例',
  barrier_low: '下界比例 (L/S₀)', barrier_high: '上界比例 (H/S₀)',
  strike: '行权价 K', strike_low: '下限行权价 K₁', strike_high: '上限行权价 K₂', direction: '策略方向',
  high_return: '高收益率', low_return: '低收益率(保底)',
  avg_type: '均价类型', lower_barrier: '区间下界', upper_barrier: '区间上界',
  call_date: '首次可赎回(年)', call_price: '赎回价格', rate_vol: '利率波动率',
  lower: '区间下界', upper: '区间上界',
  payoff: '区间内固定收益', payoff_type: '收益类型',
};
const OBS_FREQ_MAP = { daily: '每日', weekly: '周度', monthly: '月度', quarterly: '季度' };
const AVG_TYPE_MAP = { arithmetic: '算术平均', geometric: '几何平均' };
const DIR_MAP = { bull: '看涨价差', bear: '看跌价差' };

export default {
  name: 'OptionsProductList',
  data() {
    return {
      loading: false, submitting: false,
      products: [], availableAssets: [],
      filterType: '', filterStatus: '',
      productTypes: Object.entries(TYPE_MAP).map(([value, label]) => ({ value, label })),
      productStatuses: Object.entries(STATUS_MAP).map(([value, label]) => ({ value, label })),
      typeGroups: [
        { label: '障碍类 (Autocall)', items: [
          { value: 'snowball', label: '雪球 (Snowball)' },
          { value: 'phoenix', label: '凤凰 (Phoenix)' },
          { value: 'sharkfin', label: '鲨鱼鳍 (Sharkfin)' },
          { value: 'double_barrier', label: '双鲨 (Double Barrier)' },
        ]},
        { label: '路径依赖', items: [
          { value: 'asian', label: '亚式期权 (Asian)' },
          { value: 'range_accrual', label: '区间累积 (Range Accrual)' },
        ]},
        { label: '固收增强', items: [
          { value: 'fixed', label: '固定收益 (Fixed)' },
          { value: 'callable_fixed', label: '可赎回固收 (Callable)' },
          { value: 'binary', label: '二元结构 (Binary)' },
          { value: 'digital_range', label: '数字区间 (Digital)' },
        ]},
        { label: '组合策略', items: [
          { value: 'spread', label: '价差结构 (Spread)' },
          { value: 'rainbow', label: '彩虹期权 (Rainbow)' },
        ]},
      ],
      formVisible: false, editMode: false, editId: null,
      detailVisible: false, detailProduct: null,
      form: this.defaultForm(),
      formRules: {
        product_id: [{ required: true, message: '请输入产品编号', trigger: 'blur' }],
        name: [{ required: true, message: '请输入产品名称', trigger: 'blur' }],
        type: [{ required: true, message: '请选择结构类型', trigger: 'change' }],
        underlying: [{ required: true, message: '请选择挂钩标的', trigger: 'change' }],
        principal: [{ required: true, message: '请输入名义本金', trigger: 'blur' }],
        issue_date: [{ required: true, message: '请选择发行日', trigger: 'change' }],
        maturity_date: [{ required: true, message: '请选择到期日', trigger: 'change' }],
      },
    };
  },
  watch: {
    'form.type'(newType) {
      if (this.formVisible && !this.editMode) {
        this.form.params = { ...this.defaultParamsForType(newType) };
      }
    }
  },
  created() {
    this.loadProducts();
    this.loadAvailableAssets();
  },
  methods: {
    defaultForm() {
      return {
        product_id: '', name: '', type: 'snowball', issuer: '', underlying: '',
        principal: 10000000, issue_date: '', maturity_date: '', status: 'active',
        params: { spot_ref: null, obs_freq: 'monthly', knock_out: 1.03, knock_in: 0.78, coupon_year: 0.20, recovery_coupon_rate: 0.0, use_control_variate: true }
      };
    },
    defaultParamsForType(type) {
      const d = {
        snowball: { spot_ref: null, obs_freq: 'monthly', knock_out: 1.03, knock_in: 0.78, coupon_year: 0.20, recovery_coupon_rate: 0.0, use_control_variate: true },
        phoenix: { spot_ref: null, obs_freq: 'monthly', knock_out: 1.03, knock_in: 0.78, coupon_per_period: 0.015, memory_flag: true, use_control_variate: true },
        sharkfin: { spot_ref: null, obs_freq: 'daily', knock_out_ratio: 1.10, participation: 0.80, guaranteed: 1.0 },
        double_barrier: { spot_ref: null, obs_freq: 'daily', barrier_low: 0.80, barrier_high: 1.20, participation: 1.0, guaranteed: 1.0 },
        binary: { strike: null, high_return: 0.05, low_return: 0.005 },
        spread: { strike_low: null, strike_high: null, direction: 'bull' },
        fixed: { coupon_rate: 0.03 },
        asian: { spot_ref: null, obs_freq: 'daily', strike: null, avg_type: 'arithmetic', guaranteed: 1.0 },
        range_accrual: { spot_ref: null, lower_barrier: null, upper_barrier: null, coupon_rate: 0.05, obs_freq: 'daily' },
        callable_fixed: { coupon_rate: 0.04, call_date: 1.0, call_price: null, rate_vol: 0.01 },
        digital_range: { lower: null, upper: null, payoff: null, guaranteed: 1.0 },
      };
      return d[type] || {};
    },
    hasParams(type) { return Object.keys(this.defaultParamsForType(type)).length > 0; },
    isBarrierType(type) { return ['snowball', 'phoenix', 'sharkfin', 'double_barrier', 'asian', 'range_accrual'].includes(type); },
    hasObsFreq(type) { return ['snowball', 'phoenix', 'sharkfin', 'double_barrier', 'asian'].includes(type); },
    pctHint(val) { return val != null ? `= ${(val * 100).toFixed(1)}%` : ''; },
    annualPctHint(val) { return val != null ? `${(val * 100).toFixed(2)}%` : ''; },
    async loadAvailableAssets() {
      try {
        const res = await getValuationDataAssets();
        this.availableAssets = (res.data && res.data.data) || res.data || [];
      } catch (e) { /* fallback empty */ }
    },
    async loadProducts() {
      this.loading = true;
      try {
        const res = await listOptionProducts({ type: this.filterType, status: this.filterStatus });
        this.products = (res.data && res.data.data) || res.data || [];
      } catch (e) {
        this.$message.error('加载产品列表失败');
      } finally { this.loading = false; }
    },
    showCreateDialog() {
      this.editMode = false; this.editId = null;
      this.form = this.defaultForm();
      this.formVisible = true;
      this.$nextTick(() => { if (this.$refs.productFormRef) this.$refs.productFormRef.clearValidate(); });
    },
    showEditDialog(row) {
      this.editMode = true; this.editId = row._id;
      this.form = {
        product_id: row.product_id, name: row.name, type: row.type, issuer: row.issuer,
        underlying: row.underlying, principal: row.principal, issue_date: row.issue_date,
        maturity_date: row.maturity_date, status: row.status, params: { ...row.params }
      };
      this.formVisible = true;
      this.$nextTick(() => { if (this.$refs.productFormRef) this.$refs.productFormRef.clearValidate(); });
    },
    showDetailDialog(row) { this.detailProduct = row; this.detailVisible = true; },
    async handleSubmit() {
      try {
        await this.$refs.productFormRef.validate();
      } catch (e) {
        this.$message.warning('请填写必填项'); return;
      }
      if (this.isBarrierType(this.form.type) && !this.form.params.spot_ref) {
        this.$message.warning('请填写期初参考价 S\u2080（发行日标的收盘价）'); return;
      }
      this.submitting = true;
      try {
        if (this.editMode) {
          await updateOptionProduct(this.editId, this.form);
          this.$message.success('条款更新成功');
        } else {
          await createOptionProduct(this.form);
          this.$message.success('产品创建成功');
        }
        this.formVisible = false; this.loadProducts();
      } catch (e) {
        this.$message.error(this.editMode ? '更新失败' : '创建失败');
      } finally { this.submitting = false; }
    },
    async handleDelete(row) {
      try {
        await this.$confirm(`确定删除产品 ${row.name}（${row.product_id}）？此操作不可恢复。`, '确认删除', { type: 'warning' });
        await deleteOptionProduct(row._id);
        this.$message.success('删除成功'); this.loadProducts();
      } catch (e) { if (e !== 'cancel') this.$message.error('删除失败'); }
    },
    formatParamValue(key, val) {
      if (key === 'obs_freq') return OBS_FREQ_MAP[val] || val;
      if (key === 'avg_type') return AVG_TYPE_MAP[val] || val;
      if (key === 'direction') return DIR_MAP[val] || val;
      if (key === 'memory_flag' || key === 'use_control_variate') return val ? '是' : '否';
      if (['knock_out', 'knock_in', 'knock_out_ratio', 'barrier_low', 'barrier_high', 'guaranteed', 'participation', 'coupon_year', 'coupon_rate', 'coupon_per_period', 'high_return', 'low_return', 'recovery_coupon_rate', 'rate_vol'].includes(key)) {
        return val != null ? `${(val * 100).toFixed(2)}%` : '-';
      }
      if (typeof val === 'number') return val.toLocaleString('zh-CN', { maximumFractionDigits: 4 });
      return val != null ? String(val) : '-';
    },
    paramLabel(key) { return PARAM_LABELS[key] || key; },
    typeLabel(t) { return TYPE_MAP[t] || t; },
    statusLabel(s) { return STATUS_MAP[s] || s; },
    typeTagColor(t) {
      const m = { fixed: '', binary: 'warning', spread: 'info', sharkfin: 'success', snowball: 'danger', phoenix: 'danger', double_barrier: 'warning', asian: '', range_accrual: 'info', callable_fixed: '', digital_range: 'warning' };
      return m[t] || '';
    },
    statusTagColor(s) {
      const m = { active: 'success', pending: 'info', knocked_out: 'warning', knocked_in: 'danger', matured: '' };
      return m[s] || 'info';
    },
    formatNum(n) { return n != null ? n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }) : '-'; },
  }
};
</script>

<style scoped>
/* -- page layout -- */
.product-page { padding: 0; }
.page-header { margin-bottom: 16px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; color: #1a1a2e; letter-spacing: 0.5px; }
.page-desc { margin: 4px 0 0; color: #909399; font-size: 13px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.toolbar-left { display: flex; gap: 8px; }
.toolbar-right { display: flex; gap: 8px; }
.table-area { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 12px; }

/* -- dialog -- */
::v-deep .product-dialog .el-dialog__header {
  padding: 16px 24px 14px;
  border-bottom: 1px solid #f0f2f5;
}
::v-deep .product-dialog .el-dialog__title {
  font-size: 16px;
  font-weight: 600;
  color: #1a1a2e;
}
::v-deep .product-dialog .el-dialog__body {
  padding: 20px 24px 8px;
}
::v-deep .product-dialog .el-dialog__footer {
  padding: 12px 24px 16px;
  border-top: 1px solid #f0f2f5;
}

/* -- form scroll area -- */
.product-form {
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 4px;
}

/* -- section card -- */
.form-section {
  margin-bottom: 20px;
  padding: 16px 18px 12px;
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.form-section:last-child { margin-bottom: 8px; }

/* -- section header with left accent -- */
.form-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin: -4px 0 16px;
  padding: 8px 12px;
  background: #fff;
  border-left: 3px solid #409eff;
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.form-section-header i:first-child {
  color: #409eff;
  font-size: 15px;
}

/* -- product-type sections use orange accent -- */
.form-section:nth-child(n+2) .form-section-header {
  border-left-color: #e6a23c;
}
.form-section:nth-child(n+2) .form-section-header i:first-child {
  color: #e6a23c;
}

/* -- form items -- */
::v-deep .product-form .el-form-item {
  margin-bottom: 16px;
}
::v-deep .product-form .el-form-item__label {
  color: #606266;
  font-size: 13px;
}
::v-deep .product-form .el-input-number {
  width: 100%;
}
::v-deep .product-form .el-select {
  width: 100%;
}

/* -- tooltip icon -- */
.q-icon {
  margin-left: 4px;
  color: #c0c4cc;
  cursor: help;
  font-size: 12px;
}

/* -- param hint -- */
.param-hint {
  font-size: 11px;
  color: #909399;
  margin-top: 3px;
  line-height: 1.4;
  padding-left: 2px;
}

/* -- detail dialog -- */
.param-value {
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  font-size: 12px;
  color: #303133;
}

/* -- dialog footer -- */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

/* -- form hint bar -- */
.form-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  margin-bottom: 16px;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  border-radius: 6px;
  font-size: 12px;
  color: #409eff;
}
.form-hint i {
  font-size: 14px;
  color: #409eff;
}
.required-star {
  color: #f56c6c;
  font-weight: 700;
}
</style>
