<template>
  <el-dialog
    title="回测配置"
    :visible.sync="visible"
    width="600px"
    :before-close="handleClose"
    append-to-body
  >
    <el-form
      ref="form"
      :model="form"
      :rules="rules"
      label-width="120px"
    >
      <el-form-item label="起始日期" prop="start_date">
        <el-date-picker
          v-model="form.start_date"
          type="date"
          placeholder="请选择起始日期"
          format="yyyy-MM-dd"
          value-format="yyyy-MM-dd"
          style="width: 100%;"
        ></el-date-picker>
        <el-tooltip content="回测的开始日期，系统将从该日期开始模拟交易，需要确保该日期有足够的历史数据" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-form-item>

      <el-form-item label="结束日期" prop="end_date">
        <el-date-picker
          v-model="form.end_date"
          type="date"
          placeholder="请选择结束日期"
          format="yyyy-MM-dd"
          value-format="yyyy-MM-dd"
          style="width: 100%;"
        ></el-date-picker>
        <el-tooltip content="回测的结束日期，必须大于起始日期，系统将计算该时间段内的策略表现" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-form-item>

      <el-form-item label="初始资金" prop="initial_capital">
        <el-input-number
          v-model="form.initial_capital"
          :min="10000"
          :max="100000000"
          :step="10000"
          style="width: 100%;"
        ></el-input-number>
        <el-tooltip content="回测的初始投资金额，最小1万元，用于计算组合净值和收益，调仓日当天没有收益（资金调整中）" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-form-item>

      <el-form-item label="业绩基准">
        <el-select
          v-model="form.benchmark_code"
          placeholder="请选择业绩基准（可选）"
          clearable
          style="width: 100%;"
        >
          <el-option
            v-for="benchmark in benchmarkOptions"
            :key="benchmark.code"
            :label="`${benchmark.code} - ${benchmark.name}`"
            :value="benchmark.code"
          >
            <span style="float: left">{{ benchmark.code }} - {{ benchmark.name }}</span>
            <span style="float: right; color: #8492a6; font-size: 13px">{{ benchmark.benchmark_type }}</span>
          </el-option>
        </el-select>
        <el-tooltip content="用于对比策略业绩表现的基准指数，可选，选择后会在回测结果中显示相对基准的超额收益和跟踪误差" placement="top">
          <i class="el-icon-question" style="color: #909399; margin-left: 4px; cursor: help;"></i>
        </el-tooltip>
      </el-form-item>
    </el-form>

    <div slot="footer" class="dialog-footer">
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
      required: true
    }
  },
  data() {
    return {
      form: {
        start_date: dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
        end_date: dayjs().format('YYYY-MM-DD'),
        initial_capital: 1000000,
        benchmark_code: ''
      },
      benchmarkOptions: [],
      submitting: false,
      rules: {
        start_date: [
          { required: true, message: '请选择起始日期', trigger: 'change' }
        ],
        end_date: [
          { required: true, message: '请选择结束日期', trigger: 'change' },
          {
            validator: (rule, value, callback) => {
              if (value && this.form.start_date && new Date(value) <= new Date(this.form.start_date)) {
                callback(new Error('结束日期必须大于起始日期'));
              } else {
                callback();
              }
            },
            trigger: 'change'
          }
        ],
        initial_capital: [
          { required: true, message: '请输入初始资金', trigger: 'blur' },
          { type: 'number', min: 1000, message: '初始资金至少为1000', trigger: 'blur' }
        ]
      }
    };
  },
  computed: {
    visible: {
      get() {
        return this.value;
      },
      set(val) {
        this.$emit('input', val);
      }
    }
  },
  created() {
    this.loadBenchmarkOptions();
  },
  methods: {
    async loadBenchmarkOptions() {
      try {
        const res = await this.$store.dispatch('benchmark/fetchBenchmarkList');
        this.benchmarkOptions = res.filter(b => b.is_active); // 只显示激活的基准
      } catch (error) {
        console.error('加载业绩基准失败:', error);
      }
    },
    handleClose() {
      this.$emit('input', false);
    },
    handleSubmit() {
      this.$refs.form.validate(async (valid) => {
        if (!valid) {
          this.$message.warning('请完善必填项');
          return;
        }

        this.submitting = true;
        try {
          const backtestData = {
            start_date: this.form.start_date,
            end_date: this.form.end_date,
            initial_capital: this.form.initial_capital,
            benchmark_code: this.form.benchmark_code || null
          };

          await this.$store.dispatch('strategy/runBacktest', {
            modelId: this.modelId,
            data: backtestData
          });

          this.$message.success('回测已启动');
          this.handleClose();
          this.$emit('success');
        } catch (error) {
          // 优先使用后端返回的错误信息
          const errorMsg = error.response?.data?.message || error.response?.data?.detail || error.message || '回测启动失败';
          this.$message.error('回测启动失败：' + errorMsg);
        } finally {
          this.submitting = false;
        }
      });
    }
  }
};
</script>

<style scoped>
.dialog-footer {
  text-align: right;
}
</style>