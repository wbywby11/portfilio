<template>
  <div class="import-panel">
    <el-alert
      title="导入说明"
      type="info"
      :closable="false"
      style="margin-bottom: 16px;"
    >
      <div style="line-height: 1.7;">
        由后端代理调用上游 <code>getPyResult</code> 拉取指定日期区间内的主体观点风险数据，
        以 <strong>risk_id</strong> 为唯一键 upsert 到 MongoDB，并记录本次批次快照。
        <br />
        上游接口地址：
        <code>POST http://zylcorms.wmverify.com:8080/jxdatamid/apiManage/getPyResult</code>
      </div>
    </el-alert>

    <el-card class="param-card" shadow="never">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-s-tools"></i> 导入参数</span>
      </div>
      <el-form
        ref="form"
        :model="form"
        :rules="rules"
        label-width="120px"
        size="small"
      >
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
                inactive-text=""
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
                  placeholder="留空则使用默认 http://zylcorms.wmverify.com:8080/..."
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
            查看最近批次详情
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="progress-card" shadow="never">
      <div slot="header" class="clearfix">
        <span><i class="el-icon-odometer"></i> 导入进度</span>
      </div>
      <el-steps :active="stepActive" :status="stepStatus" finish-status="success" align-center>
        <el-step title="提交请求" description="构造参数" icon="el-icon-edit-outline"></el-step>
        <el-step title="请求上游" description="httpx POST" icon="el-icon-connection"></el-step>
        <el-step title="解析数据" description="字段归一" icon="el-icon-data-line"></el-step>
        <el-step title="写入 Mongo" description="按 risk_id upsert" icon="el-icon-coin"></el-step>
        <el-step title="完成" description="写入批次快照" icon="el-icon-circle-check"></el-step>
      </el-steps>
    </el-card>

    <el-card v-if="lastResult" class="result-card" shadow="never">
      <div slot="header" class="clearfix">
        <span>
          <i class="el-icon-document-checked"></i> 本次结果
          <el-tag
            :type="statusType"
            size="small"
            style="margin-left: 8px;"
          >{{ statusLabel }}</el-tag>
          <span class="muted" style="margin-left: 10px; font-size: 12px;">
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
            <div class="metric-label">无 risk_id</div>
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

      <el-divider v-if="lastResult.msg_list && lastResult.msg_list.length" content-position="left">
        上游校验告警
      </el-divider>
      <div v-if="lastResult.msg_list && lastResult.msg_list.length" class="msg-list">
        <el-tag
          v-for="(m, i) in lastResult.msg_list"
          :key="i"
          :type="msgType(m.message_type)"
          size="medium"
          class="msg-tag"
          effect="light"
        >
          <span class="msg-code">[{{ m.message_code || '?' }}]</span>
          {{ m.message_content || m.message_type || '告警' }}
        </el-tag>
      </div>

      <el-divider v-if="lastResult.error" content-position="left">错误详情</el-divider>
      <el-alert
        v-if="lastResult.error"
        :title="lastResult.error"
        type="error"
        :closable="false"
      />

      <el-divider v-if="lastResult.sample_errors && lastResult.sample_errors.length" content-position="left">
        样例失败
      </el-divider>
      <ul v-if="lastResult.sample_errors && lastResult.sample_errors.length" class="sample-errors">
        <li v-for="(s, i) in lastResult.sample_errors" :key="i">{{ s }}</li>
      </ul>
    </el-card>

    <!-- 批次详情抽屉 -->
    <el-drawer
      :visible.sync="detailDrawer"
      title="最近批次完整详情"
      size="40%"
      direction="rtl"
    >
      <div class="drawer-content">
        <pre>{{ lastResultJson }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import { importSubjectRisk } from '@/api/subjectRisk';

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
  const fmt = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return [fmt(start), fmt(end)];
}

export default {
  name: 'SubjectRiskImportPanel',
  data() {
    return {
      form: {
        dateRange: defaultRange(),
        rownum: 100000,
        startrow: 1,
        resource: 'adm_subject_opinion_risk_stats',
        timeout: 180,
        upstream_url: ''
      },
      rules: {
        dateRange: [
          { required: true, message: '请选择日期区间', trigger: 'change' }
        ],
        rownum: [{ required: true, type: 'number', message: '请输入行数' }],
        startrow: [{ required: true, type: 'number', message: '请输入起始行' }]
      },
      showAdvanced: false,
      submitting: false,
      stepActive: 0,
      stepStatus: 'process',
      lastResult: null,
      detailDrawer: false,
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
    statusType() {
      return STATUS_TYPE[this.lastResult?.status] || 'info';
    },
    statusLabel() {
      return STATUS_LABEL[this.lastResult?.status] || this.lastResult?.status || '-';
    },
    lastResultJson() {
      return this.lastResult ? JSON.stringify(this.lastResult, null, 2) : '';
    }
  },
  methods: {
    msgType(t) {
      if (!t) return 'info';
      const lower = String(t).toLowerCase();
      if (lower.includes('error')) return 'danger';
      if (lower.includes('warn')) return 'warning';
      if (lower.includes('success')) return 'success';
      return 'info';
    },
    resetForm() {
      this.form.dateRange = defaultRange();
      this.form.rownum = 100000;
      this.form.startrow = 1;
      this.form.timeout = 180;
      this.form.upstream_url = '';
      this.stepActive = 0;
      this.stepStatus = 'process';
      this.lastResult = null;
    },
    async submit() {
      try {
        await this.$refs.form.validate();
      } catch (e) {
        return;
      }
      const [startDate, endDate] = this.form.dateRange || [];
      if (!startDate || !endDate) {
        this.$message.warning('请选择完整的日期区间');
        return;
      }
      const payload = {
        startDate,
        endDate,
        rownum: Number(this.form.rownum) || 100000,
        startrow: Number(this.form.startrow) || 1,
        resource: this.form.resource || 'adm_subject_opinion_risk_stats',
        timeout: Number(this.form.timeout) || 180
      };
      if (this.form.upstream_url && this.form.upstream_url.trim()) {
        payload.upstream_url = this.form.upstream_url.trim();
      }
      this.submitting = true;
      this.stepActive = 1;
      this.stepStatus = 'process';
      this.lastResult = null;

      // 视觉上模拟逐步推进（真实进度由后端一次性返回）
      const tick = setInterval(() => {
        if (this.stepActive < 4) this.stepActive += 1;
      }, 700);

      try {
        const res = await importSubjectRisk(payload);
        clearInterval(tick);
        const body = res.data || res || {};
        this.lastResult = body;
        const status = body.status;
        if (status === 'success') {
          this.stepActive = 5;
          this.stepStatus = 'success';
          this.$notify.success({
            title: '导入成功',
            message: `共处理 ${body.total_returned || 0} 条，新增 ${body.inserted || 0}，更新 ${body.updated || 0}`,
            duration: 4000
          });
        } else if (status === 'partial') {
          this.stepActive = 5;
          this.stepStatus = 'warning';
          this.$notify.warning({
            title: '部分完成',
            message: `失败 ${body.failed || 0}，跳过 ${body.skipped_no_key || 0}，请查看详情`,
            duration: 5000
          });
        } else {
          this.stepActive = Math.max(1, this.stepActive);
          this.stepStatus = 'error';
          this.$notify.error({
            title: STATUS_LABEL[status] || '导入失败',
            message: body.error || '请查看日志',
            duration: 6000
          });
        }
        this.$emit('imported', body);
      } catch (err) {
        clearInterval(tick);
        this.stepStatus = 'error';
        let body = err?.response?.data;
        // Response model 返回 {code, message, data}；检查是否有可用结果
        if (body && body.data && body.data.batch_id) {
          this.lastResult = body.data;
        }
        const detail = body?.detail || body?.message || err?.message || '导入失败';
        const msg = Array.isArray(detail)
          ? detail.map(d => d.msg || JSON.stringify(d)).join('; ')
          : typeof detail === 'string'
            ? detail
            : JSON.stringify(detail);
        this.$notify.error({
          title: '导入失败',
          message: msg,
          duration: 6000
        });
      } finally {
        this.submitting = false;
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
  color: #409EFF;
  padding: 1px 6px;
  border-radius: 4px;
  font-family: Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
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
.summary-row .metric.success .metric-num { color: #67C23A; }
.summary-row .metric.primary .metric-num { color: #409EFF; }
.summary-row .metric.warn .metric-num { color: #E6A23C; }
.summary-row .metric.danger .metric-num { color: #F56C6C; }
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
