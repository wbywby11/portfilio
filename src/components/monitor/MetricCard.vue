<template>
  <div class="metric-card" :class="cardClasses" :title="metric.tooltip || ''">
    <div class="metric-card__label">
      <span class="metric-card__label-text">{{ metric.label }}</span>
      <i v-if="isDanger" class="el-icon-warning-outline metric-card__warn"></i>
      <span v-if="metric.tag" class="metric-card__tag">{{ metric.tag }}</span>
    </div>

    <div class="metric-card__value" :style="valueStyle">
      <slot name="value">{{ displayValue }}</slot>
    </div>

    <div v-if="metric.sub" class="metric-card__sub">{{ metric.sub }}</div>

    <!-- 扩展区：进度条、补充说明等由使用方注入 -->
    <slot></slot>

    <!-- 多窗口数据组：风控页 22/65/130 天波动率 -->
    <div v-if="windows.length" class="metric-card__windows">
      <div
        v-for="w in windows"
        :key="w.label"
        class="metric-card__window"
        :class="w.status ? 'metric-card__window--' + w.status : ''"
        :title="w.tooltip || ''">
        <span class="metric-card__window-label">{{ w.label }}</span>
        <span class="metric-card__window-value">
          <i
            v-if="w.status === 'danger'"
            class="el-icon-warning-outline metric-card__window-warn"></i>{{ windowText(w) }}
        </span>
      </div>
    </div>
  </div>
</template>

<script>
/**
 * MetricCard —— 指标卡通用组件（纯展示，不包含业务取数）。
 *
 * 渲染内容完全由 metric 配置决定：
 *   {
 *     label: '当前净值',
 *     value: 2272.2698,
 *     display: '2272.2698',        // 可选：直接给最终文本，优先于 value + format
 *     format: 'number' | 'pointPercent' | 'signedPointPercent'
 *           | 'ratioPercent' | 'signedRatioPercent' | 'integer' | 'days' | 'text',
 *     precision: 2,
 *     size: 'lg' | 'md' | 'sm',
 *     status: 'up' | 'down' | 'danger' | 'warning' | 'success' | 'default' | 'muted',
 *     sub: '2026-10-13',
 *     windows: [{ label: '22天', value: 3.4, display: '3.40%', status: 'danger', tooltip }]
 *   }
 *
 * variant='plain' 时不渲染卡片边框，便于嵌入已有 el-card。
 */
const STATUS_COLORS = {
  up: '#F56C6C',
  danger: '#F56C6C',
  down: '#67C23A',
  success: '#67C23A',
  warning: '#E6A23C',
  primary: '#409EFF',
  muted: '#909399',
  default: '#303133'
};

export default {
  name: 'MetricCard',
  props: {
    metric: {
      type: Object,
      required: true
    },
    /** card：带边框卡片；plain：无边框，用于嵌入已有容器 */
    variant: {
      type: String,
      default: 'card'
    }
  },
  computed: {
    size() {
      return this.metric.size || 'md';
    },
    status() {
      return this.metric.status || null;
    },
    isDanger() {
      return this.status === 'danger';
    },
    cardClasses() {
      return [
        'metric-card--' + this.size,
        'metric-card--' + this.variant,
        this.status ? 'metric-card--status-' + this.status : ''
      ];
    },
    valueStyle() {
      const color = STATUS_COLORS[this.status];
      return color ? { color } : {};
    },
    displayValue() {
      if (this.metric.display !== undefined && this.metric.display !== null) {
        return this.metric.display;
      }
      return this.formatValue(this.metric.value, this.metric);
    },
    windows() {
      return Array.isArray(this.metric.windows) ? this.metric.windows : [];
    }
  },
  methods: {
    windowText(w) {
      if (w.display !== undefined && w.display !== null) return w.display;
      return this.formatValue(w.value, { format: w.format || this.metric.format, precision: w.precision });
    },
    formatValue(value, config) {
      if (value === null || value === undefined || value === '') {
        return config.placeholder || '—';
      }
      // 文本指标（日期、状态等）直接输出，不参与数值校验
      if (config.format === 'text') return String(value);
      if (Number.isNaN(Number(value))) {
        return config.placeholder || '—';
      }
      const n = Number(value);
      const p = config.precision === undefined || config.precision === null ? 2 : config.precision;
      switch (config.format) {
        case 'number':
          return n.toFixed(p);
        case 'integer':
          return String(Math.round(n));
        case 'pointPercent':
          return n.toFixed(p) + '%';
        case 'signedPointPercent':
          return (n > 0 ? '+' : '') + n.toFixed(p) + '%';
        case 'ratioPercent':
          return (n * 100).toFixed(p) + '%';
        case 'signedRatioPercent':
          return (n > 0 ? '+' : '') + (n * 100).toFixed(p) + '%';
        case 'days':
          return n + ' 天';
        case 'text':
          return String(value);
        default:
          return String(value);
      }
    }
  }
};
</script>

<style scoped>
.metric-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
  text-align: left;
  font-variant-numeric: tabular-nums;
}

.metric-card--card {
  min-height: 96px;
  padding: 14px 18px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  transition: box-shadow 0.2s;
}

.metric-card--card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.metric-card--plain {
  padding: 0;
}

.metric-card__label {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.4;
  color: #909399;
  letter-spacing: 0.02em;
}

.metric-card__label-text {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.metric-card__warn {
  flex: 0 0 auto;
  font-size: 13px;
  color: #f56c6c;
}

.metric-card__tag {
  flex: 0 0 auto;
  padding: 0 6px;
  border-radius: 3px;
  background: #f4f4f5;
  color: #909399;
  font-size: 11px;
}

.metric-card__value {
  margin-bottom: 6px;
  font-size: 26px;
  font-weight: 600;
  line-height: 1.1;
  color: #303133;
  letter-spacing: -0.01em;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.metric-card--lg .metric-card__value {
  font-size: 30px;
}

.metric-card--sm .metric-card__value {
  font-size: 22px;
}

.metric-card__sub {
  min-height: 17px;
  font-size: 12px;
  line-height: 1.4;
  color: #909399;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 多窗口组：等宽分栏，与主数值同一对齐基线 */
.metric-card__windows {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #f2f4f7;
}

.metric-card__window {
  min-width: 0;
  text-align: left;
}

.metric-card__window-label {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}

.metric-card__window-value {
  font-size: 15px;
  font-weight: 500;
  color: #303133;
  white-space: nowrap;
}

.metric-card__window--danger .metric-card__window-value {
  color: #f56c6c;
  font-weight: 600;
}

.metric-card__window--warning .metric-card__window-value {
  color: #e6a23c;
  font-weight: 600;
}

.metric-card__window--success .metric-card__window-value {
  color: #67c23a;
}

.metric-card__window-warn {
  margin-right: 3px;
  font-size: 12px;
  vertical-align: -1px;
}
</style>
