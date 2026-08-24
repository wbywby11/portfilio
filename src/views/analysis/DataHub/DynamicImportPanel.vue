<template>
  <div class="import-panel dyn-import-panel">
    <el-popover placement="bottom-start" width="460" trigger="click">
      <div class="hint-body" style="line-height: 1.7;">
        由后端按所选连接器调用上游，
        <span v-if="connector && connector.primary_key">以 <strong>{{ connector.primary_key }}</strong> 为唯一键 upsert。</span>
        <span v-else>按要求写入 Mongo。</span>
        {{ connector && connector.description ? connector.description : '' }}
        <br v-if="connector && connector.default_upstream_url" />
        <template v-if="connector && connector.default_upstream_url">
          连接器默认 upstream：
          <code>{{ connector.default_upstream_url }}</code>
        </template>
      </div>
      <el-button slot="reference" type="text" icon="el-icon-question" class="hint-trigger">导入说明</el-button>
    </el-popover>

    <el-card class="param-card" shadow="never">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-s-tools"></i> 导入参数</span>
      </div>
      <el-form
        ref="form"
        :model="form"
        :rules="activeRules"
        label-width="120px"
        size="small"
      >
        <template v-if="importParamStyle === 'date_range'">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="日期区间" prop="dateRange">
                <el-date-picker
                  v-model="form.dateRange"
                  type="daterange"
                  range-separator="至"
                  start-placeholder="起始日期"
                  end-placeholder="结束日期"
                  value-format="yyyy-MM-dd"
                  :picker-options="pickerOptions"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="最大行数" prop="rownum">
                <el-input-number
                  v-model="form.rownum"
                  :min="1"
                  :max="1000000"
                  :step="10000"
                  controls-position="right"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="起始行" prop="startrow">
                <el-input-number
                  v-model="form.startrow"
                  :min="1"
                  :step="1"
                  controls-position="right"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="资源标识" prop="resource">
              <el-input v-model="form.resource" readonly>
                <template slot="prepend">resource</template>
              </el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item>
              <el-switch
                v-model="showAdvanced"
                active-text="高级选项"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <transition name="fade">
          <el-row v-if="showAdvanced" :gutter="20">
            <el-col :span="8">
              <el-form-item label="请求超时(秒)" prop="timeout">
                <el-input-number
                  v-model="form.timeout"
                  :min="5"
                  :max="600"
                  :step="5"
                  controls-position="right"
                  style="width: 100%;"
                />
              </el-form-item>
            </el-col>
            <el-col :span="16">
              <el-form-item label="自定义上游 URL">
                <el-input
                  v-model="form.upstream_url"
                  placeholder="留空则使用连接器默认 upstream"
                  clearable
                />
              </el-form-item>
            </el-col>
          </el-row>
        </transition>

        <el-form-item>
          <el-button
            type="primary"
            icon="el-icon-download"
            :loading="submitting"
            @click="submit"
          >
            开始导入
          </el-button>
          <el-button icon="el-icon-refresh-left" @click="resetForm">重置</el-button>
          <el-button
            v-if="lastResult"
            icon="el-icon-view"
            @click="detailDrawer = true"
          >
            查看本次完整 JSON
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="progress-card" shadow="never">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-odometer"></i> 导入进度</span>
      </div>
      <el-steps :active="stepActive" :status="stepStatus" finish-status="success" align-center>
        <el-step title="提交请求" description="构造参数" icon="el-icon-edit-outline" />
        <el-step title="请求上游" description="后端代理 POST" icon="el-icon-connection" />
        <el-step title="解析数据" description="字段归一" icon="el-icon-data-line" />
        <el-step :title="'写入 Mongo'" :description="stepWriteMongoDesc" icon="el-icon-coin" />
        <el-step title="完成" description="写入批次快照" icon="el-icon-circle-check" />
      </el-steps>
    </el-card>

    <el-card v-if="lastResult" class="result-card" shadow="never">
      <div slot="header" class="clearfix">
        <span>
          <i class="el-icon-document-checked"></i> 本次结果
          <el-tag :type="statusElType" size="small" style="margin-left: 8px">{{ statusZh }}</el-tag>
          <span class="muted muted-inline">
            batch_id: {{ lastResult.batch_id }} · 耗时 {{ (lastResult.duration_ms || 0) }}ms
          </span>
        </span>
      </div>

      <el-row :gutter="12" class="summary-row">
        <el-col :span="4">
          <div class="metric">
            <div class="metric-num">{{ lastResult.total_returned || 0 }}</div>
            <div class="metric-label">上游返回</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="metric success">
            <div class="metric-num">{{ lastResult.inserted || 0 }}</div>
            <div class="metric-label">新增</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="metric primary">
            <div class="metric-num">{{ lastResult.updated || 0 }}</div>
            <div class="metric-label">更新</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="metric warn">
            <div class="metric-num">{{ lastResult.skipped_no_key || 0 }}</div>
            <div class="metric-label">{{ skippedLabel }}</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="metric danger">
            <div class="metric-num">{{ lastResult.failed || 0 }}</div>
            <div class="metric-label">失败</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="metric info">
            <div class="metric-num">{{ (lastResult.msg_list || []).length }}</div>
            <div class="metric-label">告警数</div>
          </div>
        </el-col>
      </el-row>

      <el-alert
        v-if="lastResult.upstream_page_msg || lastResult.upstream_records_count != null"
        type="warning"
        :closable="false"
        show-icon
        class="upstream-hint-alert"
      >
        <template v-if="lastResult.upstream_page_msg">
          <div><strong>上游 pageMsg：</strong>{{ lastResult.upstream_page_msg }}</div>
        </template>
        <div v-if="lastResult.upstream_records_count != null" class="muted" style="margin-top: 6px;">
          上游记录数提示：{{ lastResult.upstream_records_count }}
          <template v-if="lastResult.upstream_total_hint != null"> · total：{{ lastResult.upstream_total_hint }}</template>
        </div>
      </el-alert>

      <el-divider v-if="lastResult.msg_list && lastResult.msg_list.length" content-position="left">
        上游校验告警
      </el-divider>
      <div v-if="lastResult.msg_list && lastResult.msg_list.length" class="msg-list">
        <el-tag
          v-for="(m, i) in lastResult.msg_list"
          :key="i"
          :type="msgTagTypeFor(m.message_type)"
          size="medium"
          class="msg-tag"
          effect="light"
        >
          <span class="msg-code">[{{ m.message_code || '?' }}]</span>
          {{ m.message_content || m.message_type || '告警' }}
        </el-tag>
      </div>

      <el-divider v-if="lastResult.error" content-position="left">错误详情</el-divider>
      <el-alert v-if="lastResult.error" :title="lastResult.error" type="error" :closable="false" />

      <el-divider v-if="lastResult.sample_errors && lastResult.sample_errors.length" content-position="left">
        样例失败
      </el-divider>
      <ul v-if="lastResult.sample_errors && lastResult.sample_errors.length" class="sample-errors">
        <li v-for="(s, i) in lastResult.sample_errors" :key="i">{{ s }}</li>
      </ul>
    </el-card>

    <el-drawer
      :visible.sync="detailDrawer"
      title="本次导入完整详情（JSON）"
      size="40%"
      direction="rtl"
      append-to-body
    >
      <div class="drawer-content">
        <pre>{{ lastResultJson }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import { importDataHub } from '@/api/dataHub';

const STATUS_TYPE = {
  success: 'success',
  partial: 'warning',
  failed_network: 'danger',
  failed_upstream: 'danger',
  failed_unknown: 'danger',
  running: 'info'
};
const STATUS_LABEL = {
  success: '全部成功',
  partial: '部分完成',
  failed_network: '网络失败',
  failed_upstream: '上游异常',
  failed_unknown: '未知失败',
  running: '进行中'
};

function defaultRange() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  const fmt = function (d) {
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  };
  return [fmt(start), fmt(end)];
}

export default {
  name: 'DataHubDynamicImportPanel',
  props: {
    connector: { type: Object, default: null },
    connectorId: { type: String, required: true }
  },
  data() {
    return {
      showAdvanced: false,
      submitting: false,
      stepActive: 0,
      stepStatus: 'process',
      lastResult: null,
      detailDrawer: false,
      form: {
        dateRange: defaultRange(),
        rownum: 100000,
        startrow: 1,
        resource: '',
        timeout: 180,
        upstream_url: ''
      },
      rulesDateRange: {
        dateRange: [{ required: true, message: '请选择日期区间', trigger: 'change' }],
        rownum: [{ required: true, type: 'number', message: '请输入行数' }],
        startrow: [{ required: true, type: 'number', message: '请输入起始行' }]
      },
      pickerOptions: {
        shortcuts: [
          {
            text: '最近 7 天',
            onClick(picker) {
              const end = new Date();
              const start = new Date();
              start.setDate(start.getDate() - 7);
              picker.$emit('pick', [start, end]);
            }
          },
          {
            text: '最近 30 天',
            onClick(picker) {
              const end = new Date();
              const start = new Date();
              start.setDate(start.getDate() - 30);
              picker.$emit('pick', [start, end]);
            }
          },
          {
            text: '最近 90 天',
            onClick(picker) {
              const end = new Date();
              const start = new Date();
              start.setDate(start.getDate() - 90);
              picker.$emit('pick', [start, end]);
            }
          }
        ]
      }
    };
  },
  computed: {
    importParamStyle() {
      return (this.connector && this.connector.import_param_style) || 'date_range';
    },
    activeRules() {
      return this.rulesDateRange;
    },
    stepWriteMongoDesc() {
      var pk = (this.connector && this.connector.primary_key) || 'risk_id';
      return '按 ' + pk + ' upsert';
    },
    skippedLabel() {
      var pk = (this.connector && this.connector.primary_key) || 'risk_id';
      return '无 ' + pk;
    },
    statusElType() {
      if (!this.lastResult || !this.lastResult.status) return 'info';
      return STATUS_TYPE[this.lastResult.status] || 'info';
    },
    statusZh() {
      if (!this.lastResult || !this.lastResult.status) return '-';
      return STATUS_LABEL[this.lastResult.status] || this.lastResult.status || '-';
    },
    lastResultJson() {
      return this.lastResult ? JSON.stringify(this.lastResult, null, 2) : '';
    }
  },
  watch: {
    connector: {
      handler(c, prev) {
        if (c && c.resource_default) this.form.resource = c.resource_default;
        if (prev && c && prev.connector_id !== c.connector_id) {
          this.resetForm();
        }
      },
      immediate: true
    }
  },
  methods: {
    msgTagTypeFor(t) {
      if (!t) return 'info';
      var lower = String(t).toLowerCase();
      if (lower.indexOf('error') >= 0) return 'danger';
      if (lower.indexOf('warn') >= 0) return 'warning';
      if (lower.indexOf('success') >= 0) return 'success';
      return 'info';
    },
    resetForm() {
      this.form.dateRange = defaultRange();
      this.form.rownum = 100000;
      this.form.startrow = 1;
      if (this.connector && this.connector.resource_default) this.form.resource = this.connector.resource_default;
      this.form.timeout = 180;
      this.form.upstream_url = '';
      this.stepActive = 0;
      this.stepStatus = 'process';
      this.lastResult = null;
    },
    /**
     * 与 subjectRisk/import 一致：axios 已将 response.data 解包为 ApiResponse { code, message, data }
     */
    parseImportEnvelope(raw) {
      if (!raw || typeof raw !== 'object') return { code: 200, batch: {}, message: '' };
      if (raw.data !== undefined && raw.code !== undefined) {
        return { code: raw.code, message: raw.message || '', batch: raw.data || {} };
      }
      return { code: 200, message: '', batch: raw };
    },
    async submit() {
      if (!this.connectorId) return;
      try {
        await this.$refs.form.validate();
      } catch (e) {
        return;
      }
      var vm = this;
      var payload;
      var range = this.form.dateRange || [];
      var startDate = range[0];
      var endDate = range[1];
      if (!startDate || !endDate) {
        this.$message.warning('请选择完整的日期区间');
        return;
      }
      payload = {
        startDate: startDate,
        endDate: endDate,
        rownum: Number(this.form.rownum) || 100000,
        startrow: Number(this.form.startrow) || 1,
        resource: this.form.resource || (this.connector && this.connector.resource_default) || '',
        timeout: Number(this.form.timeout) || 180
      };
      if (this.form.upstream_url && this.form.upstream_url.trim()) {
        payload.upstream_url = this.form.upstream_url.trim();
      }

      this.submitting = true;
      this.stepActive = 1;
      this.stepStatus = 'process';
      this.lastResult = null;

      var tick = setInterval(function () {
        if (vm.stepActive < 4) vm.stepActive += 1;
      }, 700);

      try {
        var raw = await importDataHub(this.connectorId, payload);
        clearInterval(tick);
        var env = vm.parseImportEnvelope(raw);
        var batch = env.batch || {};
        var st = batch.status;

        if (typeof env.code === 'number' && env.code !== 200) {
          if (batch && batch.batch_id) vm.lastResult = batch;
          vm.stepActive = Math.max(1, vm.stepActive);
          vm.stepStatus = 'error';
          vm.$notify.error({
            title: '导入未完成',
            message: env.message || (batch && batch.error) || '请查看日志',
            duration: 6000
          });
          vm.$emit('imported', batch);
          return;
        }

        vm.lastResult = batch;

        if (st === 'success') {
          vm.stepActive = 5;
          vm.stepStatus = 'success';
          vm.$notify.success({
            title: '导入成功',
            message: '共处理 ' + (batch.total_returned || 0) + ' 条，新增 ' + (batch.inserted || 0) + '，更新 ' + (batch.updated || 0),
            duration: 4000
          });
        } else if (st === 'partial') {
          vm.stepActive = 5;
          vm.stepStatus = 'warning';
          var warnMsg =
            batch.total_returned === 0 && batch.upstream_page_msg
              ? String(batch.upstream_page_msg)
              : '失败 ' + (batch.failed || 0) + '，跳过 ' + (batch.skipped_no_key || 0) + '，请查看详情';
          vm.$notify.warning({
            title: '部分完成',
            message: warnMsg,
            duration: 5000
          });
        } else if (st && st.indexOf('failed') === 0) {
          vm.stepActive = Math.max(1, vm.stepActive);
          vm.stepStatus = 'error';
          vm.$notify.error({
            title: STATUS_LABEL[st] || '导入失败',
            message: batch.error || env.message || '请查看日志',
            duration: 6000
          });
        }

        vm.$emit('imported', batch);
      } catch (err) {
        clearInterval(tick);
        var rsp = err && err.response && err.response.data;
        var innerFail = rsp && rsp.data;
        if (innerFail && innerFail.batch_id) {
          vm.lastResult = innerFail;
        }
        vm.stepStatus = 'error';
        var detail =
          rsp && (rsp.detail || rsp.message);
        if (!detail && err && err.message) detail = err.message;
        var msg =
          typeof detail === 'string'
            ? detail
            : JSON.stringify(detail || '导入失败');
        vm.$notify.error({ title: '导入失败', message: msg, duration: 6000 });
      } finally {
        vm.submitting = false;
      }
    }
  }
};
</script>

<style scoped>
.import-panel {
  padding: 4px;
}
.import-panel code {
  background: #f2f6fc;
  color: #409eff;
  padding: 1px 6px;
  border-radius: 4px;
  font-family: Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}
.hint-trigger {
  padding: 0;
  margin-bottom: 8px;
}
.hint-body {
  line-height: 1.7;
}
.param-card,
.progress-card,
.result-card {
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}

.summary-row .metric {
  background: #f7f9fc;
  border-radius: 6px;
  padding: 14px 0;
  text-align: center;
  border: 1px solid #ebeef5;
  transition: transform 0.2s;
}
.summary-row .metric:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}
.summary-row .metric-num {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.4;
  color: #303133;
}
.summary-row .metric-label {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
.summary-row + .upstream-hint-alert {
  margin: 12px 0 0 0;
}
.summary-row .metric.success .metric-num { color: #67c23a; }
.summary-row .metric.primary .metric-num { color: #409eff; }
.summary-row .metric.warn .metric-num { color: #e6a23c; }
.summary-row .metric.danger .metric-num { color: #f56c6c; }
.summary-row .metric.info .metric-num { color: #909399; }

.msg-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.msg-tag {
  max-width: 100%;
  white-space: normal;
  height: auto;
  line-height: 1.6;
  padding: 6px 10px;
}
.msg-code {
  font-weight: 600;
  margin-right: 6px;
}
.sample-errors {
  margin: 0;
  padding-left: 20px;
  color: #606266;
  font-size: 12px;
  line-height: 1.8;
}
.muted {
  color: #909399;
}
.muted-inline {
  margin-left: 10px;
  font-size: 12px;
}
.drawer-content {
  padding: 16px;
  max-height: calc(100vh - 80px);
  overflow: auto;
}
.drawer-content pre {
  font-family: Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  background: #f7f9fc;
  padding: 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s;
}
.fade-enter,
.fade-leave-to {
  opacity: 0;
}
</style>
