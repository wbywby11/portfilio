<template>
  <div class="trade-calendar-panel">
    <!-- 顶部双卡片：导入区域 + 数据统计 -->
    <div class="top-row">
      <!-- 左侧：导入与手动添加 -->
      <el-card class="panel-card import-card" shadow="hover">
        <div slot="header" class="card-header">
          <span class="card-title">
            <i class="el-icon-upload2"></i>
            交易日历导入
          </span>
        </div>

        <el-alert
          class="format-alert"
          title="支持 .xlsx/.xls 格式，文件需包含日期列（如 trade_date / date），系统将自动识别"
          type="info"
          :closable="false"
          show-icon
        />

        <div class="form-block">
          <div class="form-label">导入模式</div>
          <el-radio-group v-model="importMode" size="small">
            <el-radio-button label="replace">覆盖（replace）</el-radio-button>
            <el-radio-button label="incremental">增量（incremental）</el-radio-button>
          </el-radio-group>
          <div class="mode-hint">
            <span v-if="importMode === 'replace'">
              <i class="el-icon-warning-outline"></i>
              覆盖模式将先清空原有交易日历，再写入新数据
            </span>
            <span v-else>
              <i class="el-icon-info"></i>
              增量模式会保留已有数据并追加新增交易日
            </span>
          </div>
        </div>

        <div class="form-block">
          <el-upload
            ref="uploader"
            class="trade-uploader"
            action=""
            :auto-upload="false"
            :limit="1"
            :file-list="fileList"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :on-exceed="handleExceed"
            accept=".xlsx,.xls"
            drag
          >
            <i class="el-icon-upload"></i>
            <div class="el-upload__text">
              将文件拖到此处，或<em>点击上传</em>
            </div>
            <div class="el-upload__tip" slot="tip">
              仅支持 .xlsx / .xls 单个文件
            </div>
          </el-upload>

          <el-button
            type="primary"
            icon="el-icon-position"
            :loading="importing"
            :disabled="!fileList.length"
            class="import-btn"
            @click="handleImport"
          >
            开始导入
          </el-button>
        </div>

        <el-divider>
          <span class="divider-text">手动添加交易日</span>
        </el-divider>

        <div class="form-block manual-block">
          <div class="manual-date-section">
            <div class="date-input-row">
              <el-date-picker
                v-model="pendingDate"
                type="date"
                placeholder="选择交易日期"
                value-format="yyyy-MM-dd"
                style="flex: 1"
                :picker-options="datePickerOptions"
              />
              <el-button
                type="primary"
                icon="el-icon-plus"
                size="small"
                :disabled="!pendingDate"
                @click="addToManualList"
                style="margin-left: 8px"
              >
                加入列表
              </el-button>
            </div>
            <div
              v-if="manualDates && manualDates.length"
              class="selected-dates-tags"
            >
              <el-tag
                v-for="(date, idx) in manualDates"
                :key="idx"
                closable
                size="small"
                type="info"
                @close="removeFromManualList(idx)"
                style="margin: 4px 4px 4px 0"
              >
                {{ date }}
              </el-tag>
            </div>
            <div
              v-if="manualDates && manualDates.length"
              class="selected-summary"
            >
              已选择 {{ manualDates.length }} 个日期
            </div>
          </div>
          <el-button
            type="success"
            icon="el-icon-plus"
            :loading="adding"
            :disabled="!manualDates || !manualDates.length"
            class="add-btn"
            @click="handleAddDates"
          >
            添加交易日（{{ (manualDates && manualDates.length) || 0 }}）
          </el-button>
        </div>
      </el-card>

      <!-- 右侧：统计 -->
      <el-card class="panel-card stats-card" shadow="hover" v-loading="statsLoading">
        <div slot="header" class="card-header">
          <span class="card-title">
            <i class="el-icon-data-line"></i>
            数据统计
          </span>
          <el-button
            type="text"
            icon="el-icon-refresh"
            class="refresh-btn"
            @click="loadStats(true)"
          >
            刷新
          </el-button>
        </div>

        <div class="stats-grid">
          <div class="stat-cell stat-primary">
            <div class="stat-value">{{ formatNumber(stats.total) }}</div>
            <div class="stat-label">交易日总数</div>
          </div>

          <div class="stat-cell">
            <div class="stat-value-sm">{{ stats.startDate || '—' }}</div>
            <div class="stat-label">起始日期</div>
          </div>

          <div class="stat-cell">
            <div class="stat-value-sm">{{ stats.endDate || '—' }}</div>
            <div class="stat-label">结束日期</div>
          </div>

          <div class="stat-cell">
            <div class="stat-value-md">{{ formatNumber(stats.thisYear) }}</div>
            <div class="stat-label">本年交易日数</div>
          </div>

          <div class="stat-cell stat-wide">
            <div class="stat-value-sm muted">{{ stats.lastUpdated || '—' }}</div>
            <div class="stat-label">最近更新时间</div>
          </div>
        </div>

        <!-- 快捷删除交易日 -->
        <el-divider class="delete-divider">
          <span class="divider-text">快捷删除交易日</span>
        </el-divider>
        <div class="quick-delete-block">
          <el-date-picker
            v-model="deleteTargetDate"
            type="date"
            placeholder="选择需删除的交易日"
            value-format="yyyy-MM-dd"
            class="quick-delete-picker"
            :picker-options="deletePickerOptions"
          />
          <el-button
            type="danger"
            plain
            icon="el-icon-delete"
            size="small"
            class="quick-delete-btn"
            :loading="deletingDate === deleteTargetDate"
            :disabled="!deleteTargetDate"
            @click="handleDeleteDateByPicker"
          >
            删除该交易日
          </el-button>
        </div>
        <div class="quick-delete-hint">
          <i class="el-icon-info"></i>
          也可在下方日历中点击交易日（蓝色圆点）进行单个删除
        </div>

        <!-- 快捷批量添加交易日 -->
        <el-divider class="add-divider">
          <span class="divider-text">快捷批量添加交易日</span>
        </el-divider>
        <div class="quick-add-block">
          <el-date-picker
            v-model="rangeAddDates"
            type="daterange"
            range-separator="至"
            start-placeholder="起始日期"
            end-placeholder="结束日期"
            value-format="yyyy-MM-dd"
            class="quick-add-picker"
            :picker-options="rangeAddPickerOptions"
          />
          <el-button
            type="success"
            plain
            icon="el-icon-plus"
            size="small"
            class="quick-add-btn"
            :loading="rangeAdding"
            :disabled="!rangeAddDates || rangeAddDates.length !== 2"
            @click="handleRangeAddDates"
          >
            批量添加
          </el-button>
        </div>
        <div class="quick-add-hint">
          <i class="el-icon-info"></i>
          将区间内所有工作日（周一至周五）中尚未设为交易日的日期批量添加；也可在日历中点击非交易日（灰色）单个添加
        </div>
      </el-card>
    </div>

    <!-- 日历可视化卡片 -->
    <el-card class="panel-card calendar-card" shadow="hover" v-loading="calendarLoading">
      <div slot="header" class="card-header calendar-header">
        <span class="card-title">
          <i class="el-icon-date"></i>
          交易日历可视化
        </span>
        <div class="year-switcher">
          <el-button
            circle
            size="small"
            icon="el-icon-arrow-left"
            @click="changeYear(-1)"
          />
          <span class="year-text">{{ currentYear }} 年</span>
          <el-button
            circle
            size="small"
            icon="el-icon-arrow-right"
            @click="changeYear(1)"
          />
        </div>
      </div>

      <transition name="year-fade" mode="out-in">
        <div :key="currentYear" class="months-grid">
          <div
            v-for="month in 12"
            :key="month"
            class="month-block"
          >
            <div class="month-title">{{ currentYear }} · {{ formatMonth(month) }}</div>
            <div class="weekday-row">
              <span
                v-for="(w, idx) in weekdays"
                :key="idx"
                class="weekday-cell"
                :class="{ 'weekend-text': idx === 0 || idx === 6 }"
              >{{ w }}</span>
            </div>
            <div class="days-grid">
              <div
                v-for="(cell, idx) in monthMatrix(currentYear, month)"
                :key="idx"
                class="day-cell"
                :class="dayCellClass(cell)"
              >
                <!-- 交易日：点击弹出 popover，提供删除操作 -->
                <el-popover
                  v-if="cell.day && cell.isTrade"
                  placement="top"
                  trigger="click"
                  :open-delay="60"
                  popper-class="trade-day-popover"
                >
                  <div class="day-popover-content">
                    <div class="day-popover-title">
                      <i class="el-icon-date"></i>
                      <span>{{ cell.dateStr }}</span>
                      <el-tag size="mini" type="primary" effect="dark" class="day-popover-badge">交易日</el-tag>
                    </div>
                    <div class="day-popover-meta">
                      <span class="weekday-tip">{{ getWeekdayLabel(cell.dateStr) }}</span>
                    </div>
                    <div class="day-popover-actions">
                      <el-button
                        type="danger"
                        size="mini"
                        icon="el-icon-delete"
                        :loading="deletingDate === cell.dateStr"
                        @click="handleDeleteDate(cell.dateStr)"
                      >
                        删除该交易日
                      </el-button>
                    </div>
                  </div>
                  <span
                    slot="reference"
                    class="day-inner trade-day-clickable"
                  >{{ cell.day }}</span>
                </el-popover>
                <!-- 非交易日：点击弹出 popover，提供添加操作 -->
                <el-popover
                  v-else-if="cell.day"
                  placement="top"
                  trigger="click"
                  :open-delay="60"
                  popper-class="non-trade-day-popover"
                >
                  <div class="day-popover-content">
                    <div class="day-popover-title">
                      <i class="el-icon-date"></i>
                      <span>{{ cell.dateStr }}</span>
                      <el-tag
                        size="mini"
                        :type="cell.isWeekend ? 'info' : 'warning'"
                        effect="plain"
                        class="day-popover-badge"
                      >{{ cell.isWeekend ? '周末' : '非交易日' }}</el-tag>
                    </div>
                    <div class="day-popover-meta">
                      <span class="weekday-tip">{{ getWeekdayLabel(cell.dateStr) }}</span>
                    </div>
                    <div class="day-popover-actions">
                      <el-button
                        type="success"
                        size="mini"
                        icon="el-icon-plus"
                        :loading="addingDate === cell.dateStr"
                        @click="handleAddDate(cell.dateStr)"
                      >
                        添加为交易日
                      </el-button>
                    </div>
                  </div>
                  <span
                    slot="reference"
                    class="day-inner non-trade-day-clickable"
                  >{{ cell.day }}</span>
                </el-popover>
              </div>
            </div>
          </div>
        </div>
      </transition>

      <div class="legend-row">
        <span class="legend-item">
          <span class="legend-dot trade-dot"></span>
          交易日（点击删除）
        </span>
        <span class="legend-item">
          <span class="legend-dot weekend-dot"></span>
          周末
        </span>
        <span class="legend-item">
          <span class="legend-dot non-trade-dot"></span>
          非交易工作日（点击添加）
        </span>
        <span class="legend-tail">
          {{ currentYear }} 年共
          <strong>{{ currentYearDateSet.size }}</strong>
          个交易日
        </span>
      </div>
    </el-card>
  </div>
</template>

<script>
import {
  importTradeCalendar,
  addTradeDate,
  deleteTradeDate,
  getTradeCalendarStats,
  getTradeCalendarDates
} from '@/api/tradeCalendar';

export default {
  name: 'TradeCalendarPanel',
  data() {
    return {
      // 导入相关
      importMode: 'incremental',
      fileList: [],
      importing: false,

      // 手动添加
      manualDates: [],
      pendingDate: '',
      adding: false,
      datePickerOptions: {
        disabledDate(date) {
          // 禁止选择周末（周六、周日）
          const day = date.getDay();
          return day === 0 || day === 6;
        }
      },

      // 统计
      statsLoading: false,
      stats: {
        total: 0,
        startDate: '',
        endDate: '',
        thisYear: 0,
        lastUpdated: ''
      },

      // 日历可视化
      currentYear: new Date().getFullYear(),
      calendarLoading: false,
      dateCache: {},
      weekdays: ['日', '一', '二', '三', '四', '五', '六'],

      // 添加交易日
      addingDate: '',
      rangeAddDates: [],
      rangeAdding: false,
      rangeAddPickerOptions: {
        disabledDate(date) {
          const day = date.getDay();
          return day === 0 || day === 6;
        }
      },

      // 删除交易日
      deleteTargetDate: '',
      deletingDate: '',
      deletePickerOptions: {
        // 快捷删除仅限制为已存在的交易日（含多年）
        disabledDate: (date) => {
          if (!date) return true;
          const y = date.getFullYear();
          const m = String(date.getMonth() + 1).padStart(2, '0');
          const d = String(date.getDate()).padStart(2, '0');
          const ds = `${y}-${m}-${d}`;
          const list = this.dateCache[y] || [];
          return !list.includes(ds);
        }
      }
    };
  },
  computed: {
    currentYearDateSet() {
      const list = this.dateCache[this.currentYear] || [];
      return new Set(list);
    }
  },
  mounted() {
    this.loadStats();
    this.loadYearDates(this.currentYear);
  },
  methods: {
    /* ============== 数据加载 ============== */
    async loadStats(silent = false) {
      this.statsLoading = true;
      try {
        const res = await getTradeCalendarStats();
        const data = (res && res.data) || {};
        this.stats = {
          total: data.total || data.count || 0,
          startDate: data.startDate || data.start_date || data.min_date || '',
          endDate: data.endDate || data.end_date || data.max_date || '',
          thisYear:
            data.thisYear ||
            data.this_year ||
            data.currentYear ||
            data.current_year ||
            0,
          lastUpdated:
            data.lastUpdated ||
            data.last_updated ||
            data.updatedAt ||
            data.updated_at ||
            ''
        };
      } catch (e) {
        this.$message.error('获取交易日历统计失败');
      } finally {
        this.statsLoading = false;
      }
    },

    async loadYearDates(year, force = false) {
      if (!force && this.dateCache[year]) {
        return;
      }
      this.calendarLoading = true;
      try {
        const res = await getTradeCalendarDates({ year });
        const payload = (res && res.data) || {};
        let dates = [];
        if (Array.isArray(payload)) {
          dates = payload;
        } else if (Array.isArray(payload.dates)) {
          dates = payload.dates;
        } else if (Array.isArray(payload.data)) {
          dates = payload.data;
        } else if (Array.isArray(payload.list)) {
          dates = payload.list;
        }
        // 统一格式 YYYY-MM-DD
        const normalized = dates
          .map((d) => {
            if (!d) return '';
            if (typeof d === 'string') return d.slice(0, 10);
            if (d.date) return String(d.date).slice(0, 10);
            if (d.trade_date) return String(d.trade_date).slice(0, 10);
            return '';
          })
          .filter(Boolean);
        this.$set(this.dateCache, year, normalized);
      } catch (e) {
        this.$message.error(`加载 ${year} 年交易日数据失败`);
        this.$set(this.dateCache, year, []);
      } finally {
        this.calendarLoading = false;
      }
    },

    /* ============== 导入 ============== */
    handleFileChange(file) {
      this.fileList = [file];
    },
    handleFileRemove() {
      this.fileList = [];
    },
    handleExceed() {
      this.$message.warning('仅支持上传 1 个文件，请先移除当前文件');
    },
    async handleImport() {
      if (!this.fileList.length) {
        this.$message.warning('请先选择要导入的文件');
        return;
      }
      const modeText = this.importMode === 'replace' ? '覆盖' : '增量';
      try {
        await this.$confirm(
          `确认以${modeText}模式导入交易日历？`,
          '导入确认',
          {
            confirmButtonText: '确定导入',
            cancelButtonText: '取消',
            type: this.importMode === 'replace' ? 'warning' : 'info'
          }
        );
      } catch (e) {
        return; // 用户取消
      }

      const fileObj = this.fileList[0];
      const rawFile = fileObj.raw || fileObj;
      this.importing = true;
      try {
        const res = await importTradeCalendar(rawFile, { mode: this.importMode });
        this.$message.success((res && res.data && res.data.message) || '导入成功');
        this.fileList = [];
        if (this.$refs.uploader) {
          this.$refs.uploader.clearFiles();
        }
        await Promise.all([
          this.loadStats(true),
          this.loadYearDates(this.currentYear, true)
        ]);
      } catch (e) {
        const msg =
          (e && e.response && e.response.data && e.response.data.message) ||
          (e && e.message) ||
          '导入失败';
        this.$message.error(msg);
      } finally {
        this.importing = false;
      }
    },

    /* ============== 手动添加 ============== */
    addToManualList() {
      if (!this.pendingDate) return;
      if (this.manualDates.includes(this.pendingDate)) {
        this.$message.warning('该日期已在列表中');
        return;
      }
      this.manualDates.push(this.pendingDate);
      this.pendingDate = '';
    },
    removeFromManualList(idx) {
      this.manualDates.splice(idx, 1);
    },
    async handleAddDates() {
      if (!this.manualDates || !this.manualDates.length) {
        this.$message.warning('请至少选择一个日期');
        return;
      }
      this.adding = true;
      try {
        const dateStrings = this.manualDates.map((d) => {
          if (typeof d === 'string') return d;
          const dt = new Date(d);
          return (
            dt.getFullYear() +
            '-' +
            String(dt.getMonth() + 1).padStart(2, '0') +
            '-' +
            String(dt.getDate()).padStart(2, '0')
          );
        });
        const response = await addTradeDate({ dates: dateStrings });
        const result = (response && response.data) || {};
        const insertedCount = result.inserted_count || 0;
        const skippedCount = result.skipped_count || 0;
        this.$message.success(
          `成功添加 ${insertedCount} 个交易日` +
            (skippedCount ? `，跳过 ${skippedCount} 个已存在日期` : '')
        );
        this.manualDates = [];
        await Promise.all([
          this.loadStats(true),
          this.loadYearDates(this.currentYear, true)
        ]);
      } catch (e) {
        const msg =
          (e && e.response && e.response.data && (e.response.data.detail || e.response.data.message)) ||
          (e && e.message) ||
          '添加交易日失败';
        this.$message.error(msg);
      } finally {
        this.adding = false;
      }
    },

    /* ============== 年份切换 ============== */
    async changeYear(delta) {
      const next = this.currentYear + delta;
      this.currentYear = next;
      await this.loadYearDates(next);
    },

    /* ============== 日历矩阵计算 ============== */
    monthMatrix(year, month) {
      // month: 1-12
      const firstDay = new Date(year, month - 1, 1);
      const startWeekday = firstDay.getDay(); // 0(Sun) - 6(Sat)
      const daysInMonth = new Date(year, month, 0).getDate();
      const cells = [];
      // 占位（前导空白）
      for (let i = 0; i < startWeekday; i += 1) {
        cells.push({ day: null });
      }
      const dateSet = this.currentYearDateSet;
      for (let d = 1; d <= daysInMonth; d += 1) {
        const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const weekday = new Date(year, month - 1, d).getDay();
        const isWeekend = weekday === 0 || weekday === 6;
        const isTrade = dateSet.has(dateStr);
        cells.push({
          day: d,
          dateStr,
          isWeekend,
          isTrade
        });
      }
      // 末尾补足到 7 的整数倍，保持网格整齐
      while (cells.length % 7 !== 0) {
        cells.push({ day: null });
      }
      return cells;
    },
    dayCellClass(cell) {
      if (!cell.day) return 'is-blank';
      const cls = [];
      if (cell.isTrade) cls.push('is-trade');
      else if (cell.isWeekend) cls.push('is-weekend');
      else cls.push('is-non-trade');
      return cls.join(' ');
    },

    /* ============== 工具 ============== */
    formatMonth(m) {
      return `${String(m).padStart(2, '0')} 月`;
    },
    formatNumber(n) {
      if (n === undefined || n === null || n === '') return '0';
      const num = Number(n);
      if (Number.isNaN(num)) return '0';
      return num.toLocaleString('zh-CN');
    },
    getWeekdayLabel(dateStr) {
      if (!dateStr) return '';
      const d = new Date(dateStr);
      if (Number.isNaN(d.getTime())) return '';
      const names = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];
      return names[d.getDay()] || '';
    },

    /* ============== 添加交易日 ============== */
    async handleAddDate(dateStr) {
      if (!dateStr) return;
      try {
        await this.$confirm(
          `确认将 <strong>${dateStr}</strong> 添加为交易日？`,
          '添加确认',
          {
            confirmButtonText: '确认添加',
            cancelButtonText: '取消',
            type: 'info',
            dangerouslyUseHTMLString: true
          }
        );
      } catch (e) {
        return;
      }
      this.addingDate = dateStr;
      try {
        const response = await addTradeDate({ dates: [dateStr] });
        const result = (response && response.data) || {};
        const insertedCount = result.inserted_count || 0;
        const skippedCount = result.skipped_count || 0;
        if (insertedCount > 0) {
          this.$message.success(`已添加交易日 ${dateStr}`);
          const y = Number(String(dateStr).slice(0, 4));
          if (this.dateCache[y]) {
            const updated = [...this.dateCache[y], dateStr].sort();
            this.$set(this.dateCache, y, updated);
          }
        } else if (skippedCount > 0) {
          this.$message.warning(`${dateStr} 已是交易日`);
        }
        await Promise.all([
          this.loadStats(true),
          this.loadYearDates(this.currentYear, true)
        ]);
      } catch (err) {
        const msg =
          (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) ||
          (err && err.message) ||
          '添加交易日失败';
        this.$message.error(String(msg));
      } finally {
        this.addingDate = '';
      }
    },
    generateWeekdayDatesInRange(startStr, endStr) {
      const dates = [];
      const start = new Date(startStr);
      const end = new Date(endStr);
      if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start > end) {
        return dates;
      }
      const cursor = new Date(start);
      while (cursor <= end) {
        const day = cursor.getDay();
        if (day !== 0 && day !== 6) {
          const y = cursor.getFullYear();
          const m = String(cursor.getMonth() + 1).padStart(2, '0');
          const d = String(cursor.getDate()).padStart(2, '0');
          dates.push(`${y}-${m}-${d}`);
        }
        cursor.setDate(cursor.getDate() + 1);
      }
      return dates;
    },
    async handleRangeAddDates() {
      if (!this.rangeAddDates || this.rangeAddDates.length !== 2) return;
      const [startStr, endStr] = this.rangeAddDates;
      const dateStrings = this.generateWeekdayDatesInRange(startStr, endStr);
      if (!dateStrings.length) {
        this.$message.warning('所选区间内无有效工作日');
        return;
      }
      try {
        await this.$confirm(
          `确认将 <strong>${startStr}</strong> 至 <strong>${endStr}</strong> 区间内的 <strong>${dateStrings.length}</strong> 个工作日批量添加为交易日？<br/><span style="color:#909399;font-size:12px;">已存在的交易日将自动跳过</span>`,
          '批量添加确认',
          {
            confirmButtonText: '确认添加',
            cancelButtonText: '取消',
            type: 'info',
            dangerouslyUseHTMLString: true
          }
        );
      } catch (e) {
        return;
      }
      this.rangeAdding = true;
      try {
        const response = await addTradeDate({ dates: dateStrings });
        const result = (response && response.data) || {};
        const insertedCount = result.inserted_count || 0;
        const skippedCount = result.skipped_count || 0;
        this.$message.success(
          `成功添加 ${insertedCount} 个交易日` +
            (skippedCount ? `，跳过 ${skippedCount} 个已存在日期` : '')
        );
        this.rangeAddDates = [];
        const years = new Set(dateStrings.map((d) => Number(d.slice(0, 4))));
        await Promise.all([
          this.loadStats(true),
          ...Array.from(years).map((y) => this.loadYearDates(y, true)),
          this.loadYearDates(this.currentYear, true)
        ]);
      } catch (err) {
        const msg =
          (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) ||
          (err && err.message) ||
          '批量添加交易日失败';
        this.$message.error(String(msg));
      } finally {
        this.rangeAdding = false;
      }
    },

    /* ============== 删除交易日 ============== */
    async handleDeleteDate(dateStr) {
      if (!dateStr) return;
      try {
        await this.$confirm(
          `确认删除交易日 <strong>${dateStr}</strong>？<br/><span style="color:#909399;font-size:12px;">删除后该日将不再被视为交易日，请谨慎操作</span>`,
          '删除确认',
          {
            confirmButtonText: '确认删除',
            cancelButtonText: '取消',
            type: 'warning',
            dangerouslyUseHTMLString: true
          }
        );
      } catch (e) {
        return; // 取消
      }
      this.deletingDate = dateStr;
      try {
        await deleteTradeDate(dateStr);
        this.$message.success(`已删除交易日 ${dateStr}`);
        // 先本地调整避免闪烁
        const y = Number(String(dateStr).slice(0, 4));
        if (this.dateCache[y]) {
          this.$set(
            this.dateCache,
            y,
            this.dateCache[y].filter((d) => d !== dateStr)
          );
        }
        if (this.deleteTargetDate === dateStr) {
          this.deleteTargetDate = '';
        }
        await Promise.all([
          this.loadStats(true),
          this.loadYearDates(this.currentYear, true)
        ]);
      } catch (err) {
        const msg =
          (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) ||
          (err && err.message) ||
          '删除交易日失败';
        this.$message.error(String(msg));
      } finally {
        this.deletingDate = '';
      }
    },
    async handleDeleteDateByPicker() {
      if (!this.deleteTargetDate) return;
      await this.handleDeleteDate(this.deleteTargetDate);
    }
  }
};
</script>

<style scoped>
.trade-calendar-panel {
  width: 100%;
  font-family: 'PingFang SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont,
    'Helvetica Neue', sans-serif;
  color: #303133;
  letter-spacing: 0.2px;
}

/* ===== 布局 ===== */
.top-row {
  display: flex;
  gap: 20px;
  align-items: stretch;
}
.top-row > .panel-card {
  flex: 1;
  min-width: 0;
}
.import-card {
  flex: 0 0 calc(50% - 10px);
}
.stats-card {
  flex: 1;
}
.calendar-card {
  margin-top: 20px;
}

/* ===== 卡片头部 ===== */
.panel-card {
  border-radius: 10px;
  border: 1px solid #ebeef5;
  transition: box-shadow 0.25s ease;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  letter-spacing: 0.5px;
}
.card-title i {
  margin-right: 6px;
  color: #409eff;
}
.refresh-btn {
  padding: 4px 8px;
}

/* ===== 导入卡片 ===== */
.format-alert {
  margin-bottom: 16px;
}
.form-block {
  margin-bottom: 16px;
}
.form-label {
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
  font-weight: 500;
}
.mode-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
.mode-hint i {
  margin-right: 4px;
  color: #e6a23c;
}
.trade-uploader {
  width: 100%;
}
.trade-uploader >>> .el-upload,
.trade-uploader >>> .el-upload-dragger {
  width: 100%;
}
.import-btn,
.add-btn {
  width: 100%;
  margin-top: 12px;
  letter-spacing: 1px;
}
.divider-text {
  font-size: 12px;
  color: #909399;
  letter-spacing: 1px;
}
.manual-block .el-date-editor {
  width: 100%;
}
.manual-date-section {
  margin-top: 12px;
}
.date-input-row {
  display: flex;
  align-items: center;
}
.selected-dates-tags {
  margin-top: 10px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
  min-height: 36px;
}
.selected-summary {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}

/* ===== 统计卡片 ===== */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
.stat-cell {
  background: linear-gradient(135deg, #f8fbff 0%, #f3f7fc 100%);
  border: 1px solid #ebf2fb;
  border-radius: 8px;
  padding: 16px 18px;
  position: relative;
  overflow: hidden;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.stat-cell:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(64, 158, 255, 0.12);
}
.stat-primary {
  grid-column: 1 / span 2;
  background: linear-gradient(135deg, #ecf5ff 0%, #d9ecff 100%);
  border-color: #d9ecff;
}
.stat-wide {
  grid-column: 1 / span 2;
}
.stat-value {
  font-size: 28px;
  color: #409eff;
  font-weight: bold;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.stat-value-md {
  font-size: 22px;
  color: #303133;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.stat-value-sm {
  font-size: 16px;
  color: #303133;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.stat-value-sm.muted {
  color: #606266;
  font-weight: 500;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
  letter-spacing: 0.5px;
}

/* ===== 日历卡片 ===== */
.calendar-header .year-switcher {
  display: flex;
  align-items: center;
  gap: 12px;
}
.year-text {
  min-width: 72px;
  text-align: center;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
  letter-spacing: 1px;
}

.months-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.month-block {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 10px 14px;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.month-block:hover {
  border-color: #d9ecff;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.08);
}
.month-title {
  text-align: center;
  font-size: 14px;
  font-weight: bold;
  color: #303133;
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}
.weekday-row {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
  margin-bottom: 4px;
}
.weekday-cell {
  text-align: center;
  font-size: 11px;
  color: #909399;
  padding: 2px 0;
}
.weekday-cell.weekend-text {
  color: #c0c4cc;
}
.days-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
}
.day-cell {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto;
  border-radius: 50%;
  font-size: 12px;
  cursor: default;
  transition: transform 0.15s ease, background 0.2s ease;
  background: #fff;
  color: #606266;
}
.day-cell.is-blank {
  background: transparent;
  cursor: default;
}
.day-cell.is-trade {
  background: #409eff;
  color: #fff;
  font-weight: 600;
  box-shadow: 0 2px 4px rgba(64, 158, 255, 0.25);
}
.day-cell.is-trade:hover {
  transform: scale(1.12);
  box-shadow: 0 3px 8px rgba(64, 158, 255, 0.4);
}
.day-cell.is-weekend {
  background: #f5f7fa;
  color: #c0c4cc;
}
.day-cell.is-non-trade {
  background: #fff;
  color: #909399;
  border: 1px dashed #dcdfe6;
}
.day-cell.is-non-trade:hover {
  transform: scale(1.08);
  border-color: #67c23a;
  color: #67c23a;
  cursor: pointer;
}
.day-cell.is-weekend:hover {
  transform: scale(1.08);
  border: 1px dashed #c0c4cc;
  cursor: pointer;
}
.day-inner {
  display: inline-block;
  line-height: 1;
}

/* ===== 图例 ===== */
.legend-row {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed #ebeef5;
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #606266;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.legend-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1px solid #ebeef5;
}
.legend-dot.trade-dot {
  background: #409eff;
  border-color: #409eff;
}
.legend-dot.weekend-dot {
  background: #f5f7fa;
  border-color: #ebeef5;
}
.legend-dot.non-trade-dot {
  background: #fff;
  border-color: #dcdfe6;
}
.legend-tail {
  margin-left: auto;
  color: #909399;
}
.legend-tail strong {
  color: #409eff;
  font-size: 14px;
  margin: 0 4px;
  font-variant-numeric: tabular-nums;
}

/* ===== 年份切换过渡 ===== */
.year-fade-enter-active,
.year-fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.year-fade-enter {
  opacity: 0;
  transform: translateY(6px);
}
.year-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* ===== 快捷删除交易日 ===== */
.delete-divider {
  margin: 18px 0 10px;
}
.quick-delete-block {
  display: flex;
  align-items: center;
  gap: 10px;
}
.quick-delete-picker {
  flex: 1;
  min-width: 0;
}
.quick-delete-picker >>> .el-input__inner {
  border-color: #fde2e2;
  background: #fff8f8;
}
.quick-delete-picker >>> .el-input__inner:hover {
  border-color: #fbc4c4;
}
.quick-delete-picker >>> .el-input__inner:focus {
  border-color: #f56c6c;
}
.quick-delete-btn {
  flex-shrink: 0;
  letter-spacing: 0.5px;
}
.quick-delete-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
  display: flex;
  align-items: center;
  gap: 4px;
}
.quick-delete-hint i {
  color: #409eff;
}

/* ===== 日历单元格可点击高亮 ===== */
.day-cell.is-trade .trade-day-clickable,
.day-cell.is-non-trade .non-trade-day-clickable,
.day-cell.is-weekend .non-trade-day-clickable {
  cursor: pointer;
  user-select: none;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}
.day-cell.is-trade:hover {
  cursor: pointer;
}

/* ===== 快捷批量添加交易日 ===== */
.add-divider {
  margin: 18px 0 10px;
}
.quick-add-block {
  display: flex;
  align-items: center;
  gap: 10px;
}
.quick-add-picker {
  flex: 1;
  min-width: 0;
}
.quick-add-picker >>> .el-input__inner {
  border-color: #e1f3d8;
  background: #f9fff5;
}
.quick-add-picker >>> .el-input__inner:hover {
  border-color: #c2e7b0;
}
.quick-add-picker >>> .el-input__inner:focus {
  border-color: #67c23a;
}
.quick-add-btn {
  flex-shrink: 0;
  letter-spacing: 0.5px;
}
.quick-add-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
  display: flex;
  align-items: flex-start;
  gap: 4px;
  line-height: 1.5;
}
.quick-add-hint i {
  color: #67c23a;
  margin-top: 2px;
}

/* ===== 交易日 popover ===== */
.day-popover-content {
  min-width: 220px;
  padding: 4px 2px;
}
.day-popover-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.5px;
}
.day-popover-title i {
  color: #409eff;
  font-size: 16px;
}
.day-popover-badge {
  margin-left: auto;
}
.day-popover-meta {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  padding-left: 24px;
}
.day-popover-actions {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #ebeef5;
  display: flex;
  justify-content: flex-end;
}

/* ===== 响应式 ===== */
@media (max-width: 1200px) {
  .months-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 900px) {
  .top-row {
    flex-direction: column;
  }
  .import-card {
    flex: 1 1 auto;
  }
  .months-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 560px) {
  .months-grid {
    grid-template-columns: 1fr;
  }
  .stats-grid {
    grid-template-columns: 1fr;
  }
  .stat-primary,
  .stat-wide {
    grid-column: auto;
  }
}
</style>
