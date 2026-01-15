<template>
  <el-dialog
    :title="title"
    :visible.sync="visible"
    width="600px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <el-form
      ref="form"
      :model="form"
      :rules="rules"
      label-width="120px"
    >
      <el-form-item label="回测区间" prop="dateRange">
        <el-date-picker
          v-model="form.dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="yyyy-MM-dd"
          :picker-options="pickerOptions"
          style="width: 100%;"
        ></el-date-picker>
      </el-form-item>

      <el-form-item label="初始资金" prop="initial_capital">
        <el-input-number
          v-model="form.initial_capital"
          :min="10000"
          :max="100000000"
          :step="10000"
          :precision="2"
          style="width: 100%;"
        ></el-input-number>
        <div style="color: #909399; font-size: 12px; margin-top: 5px;">
          默认: 1,000,000 元
        </div>
      </el-form-item>

      <el-alert
        title="回测说明"
        type="info"
        :closable="false"
        style="margin-bottom: 20px;"
      >
        <div style="font-size: 13px; line-height: 1.6;">
          <p style="margin: 5px 0;">• 回测将基于历史数据模拟策略的实际表现</p>
          <p style="margin: 5px 0;">• 回测时间不宜过长,建议选择1-3年</p>
          <p style="margin: 5px 0;">• 回测结果仅供参考,不代表未来实际收益</p>
        </div>
      </el-alert>
    </el-form>

    <div slot="footer">
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" @click="handleSubmit" :loading="submitting">
        {{ submitting ? '回测中...' : '开始回测' }}
      </el-button>
    </div>
  </el-dialog>
</template>

<script>
import dayjs from 'dayjs';

export default {
  name: 'BacktestDialog',
  props: {
    value: {
      type: Boolean,
      default: false
    },
    modelId: {
      type: String,
      default: ''
    },
    title: {
      type: String,
      default: '回测配置'
    }
  },
  data() {
    return {
      visible: this.value,
      submitting: false,
      form: {
        dateRange: [],
        initial_capital: 1000000
      },
      rules: {
        dateRange: [
          { required: true, message: '请选择回测区间', trigger: 'change' }
        ],
        initial_capital: [
          { required: true, message: '请输入初始资金', trigger: 'blur' }
        ]
      },
      pickerOptions: {
        disabledDate(time) {
          // 禁用未来日期
          return time.getTime() > Date.now();
        },
        shortcuts: [
          {
            text: '最近1年',
            onClick(picker) {
              const end = new Date();
              const start = new Date();
              start.setTime(start.getTime() - 3600 * 1000 * 24 * 365);
              picker.$emit('pick', [start, end]);
            }
          },
          {
            text: '最近2年',
            onClick(picker) {
              const end = new Date();
              const start = new Date();
              start.setTime(start.getTime() - 3600 * 1000 * 24 * 730);
              picker.$emit('pick', [start, end]);
            }
          },
          {
            text: '最近3年',
            onClick(picker) {
              const end = new Date();
              const start = new Date();
              start.setTime(start.getTime() - 3600 * 1000 * 24 * 1095);
              picker.$emit('pick', [start, end]);
            }
          }
        ]
      }
    };
  },
  watch: {
    value(val) {
      this.visible = val;
      if (val) {
        this.initForm();
      }
    },
    visible(val) {
      this.$emit('input', val);
    }
  },
  methods: {
    initForm() {
      // 默认最近1年
      const end = dayjs().format('YYYY-MM-DD');
      const start = dayjs().subtract(1, 'year').format('YYYY-MM-DD');
      this.form.dateRange = [start, end];
      this.form.initial_capital = 1000000;
    },
    handleSubmit() {
      this.$refs.form.validate(async (valid) => {
        if (!valid) {
          return;
        }

        if (!this.modelId) {
          this.$message.error('策略模型ID不能为空');
          return;
        }

        this.submitting = true;
        try {
          const [startDate, endDate] = this.form.dateRange;
          
          // 转换为年月日格式（不包含时分秒）
          const backtestData = {
            start_date: dayjs(startDate).format('YYYY-MM-DD'),
            end_date: dayjs(endDate).format('YYYY-MM-DD'),
            initial_capital: this.form.initial_capital
          };

          const result = await this.$store.dispatch('strategy/runBacktest', {
            modelId: this.modelId,
            data: backtestData
          });

          this.$message.success('回测完成');
          this.$emit('success', result);
          this.handleClose();
        } catch (error) {
          console.error('回测失败:', error);
          this.$message.error('回测失败：' + (error.response?.data?.message || error.message));
        } finally {
          this.submitting = false;
        }
      });
    },
    handleClose() {
      this.visible = false;
      this.$refs.form.resetFields();
    }
  }
};
</script>

<style scoped>
</style>
