import * as monitorApi from '@/api/monitor';

function resolveMonitorId(state, explicit) {
  if (explicit !== undefined && explicit !== null && String(explicit).length > 0) {
    return explicit;
  }
  return state.activeMonitorId;
}

/**
 * 批次口径解析：调用方显式传了 batch_id 就用它，否则回落到 store 里的当前批次。
 * 返回 undefined 时 axios 不会把该参数拼进 query，等价于后端「读最新 completed 批次」。
 */
function resolveBatchId(state, explicit) {
  if (explicit !== undefined && explicit !== null && String(explicit).length > 0) {
    return explicit;
  }
  return state.currentBatchId || undefined;
}

/** 后台任务是否仍在推进：paused 是「等用户点继续步进」的停顿，同样停轮询 */
const ACTIVE_TASK_STATUS = ['pending', 'running'];
const POLL_INTERVAL_MS = 2000;

/** 任务类型 → 提交用的 API（与后端 TASK_KIND_* 常量一一对应） */
const TASK_SUBMIT_API = {
  monitor_init: monitorApi.initMonitor,
  monitor_run: monitorApi.runMonitor,
  monitor_range: monitorApi.runMonitorRange
};

// 轮询定时器与并发闸有意不放进响应式 state：定时器句柄没有渲染意义，
// 放进 state 只会让每次 tick 触发无谓的依赖收集。
let pollTimer = null;
let pollBusy = false;

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  pollBusy = false;
}

const state = {
  activeMonitorId: null,
  /** 当前展示批次号：null 表示跟随最新 completed 批次（由后端解析） */
  currentBatchId: null,
  /** 批次切换器的候选列表（创建时间倒序） */
  batchList: [],
  batchesLoading: false,
  /** 当前实例的后台任务快照（init / run / run-range 共用一个槽位，后端保证同实例串行） */
  runTask: null,
  /** 最近一次到达终态的任务；taskFinishedAt 用于让组件感知「重复完成」 */
  lastFinishedTask: null,
  taskFinishedAt: 0,
  monitorState: null,
  navHistory: [],
  positions: [],
  performance: null,
  signals: null,
  events: [],
  reportList: [],
  currentReport: null,
  subjectiveOverrides: [],
  assetMetrics: [],
  correlationMatrix: null,
  // 绩效页统一数据（预计算缓存）与页面级统一周期
  performancePanel: null,
  performanceRange: { start: null, end: null },
  loading: false
};

const mutations = {
  SET_ACTIVE_MONITOR_ID(state, id) {
    state.activeMonitorId = id || null;
  },
  SET_CURRENT_BATCH_ID(state, batchId) {
    state.currentBatchId = batchId || null;
  },
  SET_BATCH_LIST(state, items) {
    state.batchList = Array.isArray(items) ? items : [];
  },
  SET_BATCHES_LOADING(state, loading) {
    state.batchesLoading = !!loading;
  },
  SET_RUN_TASK(state, task) {
    state.runTask = task || null;
  },
  /** 任务到达终态：时间戳一并刷新，连续两次 completed 也能触发组件刷新 */
  SET_TASK_FINISHED(state, task) {
    state.lastFinishedTask = task || null;
    state.taskFinishedAt = Date.now();
  },
  RESET_MONITOR_VIEW(state) {
    state.monitorState = null;
    state.navHistory = [];
    state.positions = [];
    state.performance = null;
    state.signals = null;
    state.events = [];
    state.reportList = [];
    state.currentReport = null;
    state.subjectiveOverrides = [];
    state.assetMetrics = [];
    state.correlationMatrix = null;
    state.performancePanel = null;
    state.performanceRange = { start: null, end: null };
    // 批次上下文属于「某个实例的某一次运行」，切实例必须一并清掉
    state.currentBatchId = null;
    state.batchList = [];
    state.runTask = null;
    state.lastFinishedTask = null;
    state.taskFinishedAt = 0;
  },
  SET_MONITOR_STATE(state, data) {
    state.monitorState = data;
  },
  SET_NAV_HISTORY(state, data) {
    state.navHistory = data;
  },
  SET_POSITIONS(state, data) {
    state.positions = data;
  },
  SET_PERFORMANCE(state, data) {
    state.performance = data;
  },
  SET_SIGNALS(state, data) {
    state.signals = data;
  },
  SET_EVENTS(state, data) {
    state.events = data;
  },
  SET_REPORT_LIST(state, data) {
    state.reportList = data;
  },
  SET_CURRENT_REPORT(state, data) {
    state.currentReport = data;
  },
  SET_SUBJECTIVE_OVERRIDES(state, data) {
    state.subjectiveOverrides = data;
  },
  SET_ASSET_METRICS(state, data) {
    state.assetMetrics = data;
  },
  SET_CORRELATION_MATRIX(state, data) {
    state.correlationMatrix = data;
  },
  SET_PERFORMANCE_PANEL(state, data) {
    state.performancePanel = data;
  },
  SET_PERFORMANCE_RANGE(state, range) {
    state.performanceRange = {
      start: (range && range.start) || null,
      end: (range && range.end) || null
    };
  },
  SET_LOADING(state, loading) {
    state.loading = loading;
  }
};

const actions = {
  /**
   * 切换监控实例：清掉展示数据与批次上下文，停掉上一个实例的轮询，
   * 再拉新实例的批次列表（列表接口同时给出后端认定的 current_batch_id）。
   */
  async setActiveMonitorContext({ commit, dispatch }, { monitorId }) {
    stopPolling();
    commit('SET_ACTIVE_MONITOR_ID', monitorId);
    commit('RESET_MONITOR_VIEW');
    if (!monitorId) return;
    await dispatch('fetchBatches', { monitor_id: monitorId });
  },

  // ========== 运行批次 ==========

  /**
   * 拉批次列表，并把展示批次对齐到后端认定的 current_batch_id。
   * 用户已手动选过批次（state.currentBatchId 非空）时尊重用户选择，
   * 除非那个批次已不在列表里（被软删或已翻页）才回落默认。
   */
  async fetchBatches({ commit, state }, params = {}) {
    const id = resolveMonitorId(state, params.monitor_id);
    if (!id) {
      commit('SET_BATCH_LIST', []);
      return [];
    }
    try {
      commit('SET_BATCHES_LOADING', true);
      const res = await monitorApi.getMonitorBatches({
        monitor_id: id,
        limit: params.limit || 50,
        skip: params.skip || 0,
        status: params.status,
        include_deleted: params.include_deleted
      });
      const data = res.data || res || {};
      const items = Array.isArray(data.items) ? data.items : [];
      commit('SET_BATCH_LIST', items);
      const selected = state.currentBatchId;
      const stillListed = selected && items.some(b => b.batch_id === selected);
      commit('SET_CURRENT_BATCH_ID', stillListed ? selected : (data.current_batch_id || null));
      return items;
    } catch (error) {
      console.warn('获取运行批次列表失败:', error.message);
      commit('SET_BATCH_LIST', []);
      return [];
    } finally {
      commit('SET_BATCHES_LOADING', false);
    }
  },

  /** 批次切换器：选定某个历史批次作为展示口径（传 null 回到最新 completed） */
  setCurrentBatchId({ commit }, batchId) {
    commit('SET_CURRENT_BATCH_ID', batchId || null);
  },

  async fetchMonitorState({ commit, state }, monitorId) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) {
      commit('SET_MONITOR_STATE', null);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorState(id, resolveBatchId(state));
      const data = res.data || res;
      commit('SET_MONITOR_STATE', data);
      return data;
    } catch (error) {
      console.warn('获取监控状态失败（可能未初始化）:', error.message);
      commit('SET_MONITOR_STATE', null);
      return null;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchNavHistory({ commit, state }, params = {}) {
    const id = resolveMonitorId(state, params.monitor_id);
    if (!id) {
      commit('SET_NAV_HISTORY', []);
      return [];
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getNavHistory({
        ...params,
        monitor_id: id,
        batch_id: resolveBatchId(state, params.batch_id)
      });
      const data = Array.isArray(res) ? res : (res.data || []);
      commit('SET_NAV_HISTORY', data);
      return data;
    } catch (error) {
      console.warn('获取净值历史失败（可能未初始化）:', error.message);
      commit('SET_NAV_HISTORY', []);
      return [];
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchPositions({ commit, state }, monitorId) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) {
      commit('SET_POSITIONS', []);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorPositions(id, resolveBatchId(state));
      const payload = res.data || res;
      const positions = payload.positions || (Array.isArray(payload) ? payload : []);
      commit('SET_POSITIONS', positions);
      return payload;
    } catch (error) {
      console.warn('获取持仓明细失败（可能未初始化）:', error.message);
      commit('SET_POSITIONS', []);
      return null;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchPerformance({ commit, state }, params = {}) {
    const id = resolveMonitorId(state, params.monitor_id);
    if (!id) {
      commit('SET_PERFORMANCE', null);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorPerformance(id, {
        start: params.start,
        end: params.end,
        batch_id: resolveBatchId(state, params.batch_id)
      });
      const data = res.data || res;
      commit('SET_PERFORMANCE', data);
      return data;
    } catch (error) {
      console.warn('获取绩效指标失败（可能未初始化）:', error.message);
      commit('SET_PERFORMANCE', null);
      return null;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchSignals({ commit, state }, monitorId) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) {
      commit('SET_SIGNALS', null);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorSignals(id, resolveBatchId(state));
      const data = res.data || res;
      commit('SET_SIGNALS', data);
      return data;
    } catch (error) {
      console.warn('获取信号状态失败（可能未初始化）:', error.message);
      commit('SET_SIGNALS', null);
      return null;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchEvents({ commit, state }, params = {}) {
    const id = resolveMonitorId(state, params.monitor_id);
    if (!id) {
      commit('SET_EVENTS', []);
      return [];
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorEvents({
        ...params,
        monitor_id: id,
        batch_id: resolveBatchId(state, params.batch_id)
      });
      const data = Array.isArray(res) ? res : (res.data || []);
      commit('SET_EVENTS', data);
      return data;
    } catch (error) {
      console.warn('获取事件日志失败（可能未初始化）:', error.message);
      commit('SET_EVENTS', []);
      return [];
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchReportList({ commit, state }, params = {}) {
    const id = resolveMonitorId(state, params.monitor_id);
    if (!id) {
      commit('SET_REPORT_LIST', []);
      return [];
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorReportList({
        ...params,
        monitor_id: id,
        batch_id: resolveBatchId(state, params.batch_id)
      });
      const data = Array.isArray(res) ? res : (res.data || []);
      commit('SET_REPORT_LIST', data);
      return data;
    } catch (error) {
      console.error('获取日报列表失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchReport({ commit, state }, { date, monitorId, batchId }) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) {
      commit('SET_CURRENT_REPORT', null);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorReport(date, id, resolveBatchId(state, batchId));
      const data = res.data || res;
      commit('SET_CURRENT_REPORT', data);
      return data;
    } catch (error) {
      console.error('获取日报失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  // ========== 运行触发（统一为后台任务提交 + 轮询）==========

  /**
   * 提交运行任务：init / run / run-range 三类端点共用。
   * 拿到句柄后把任务快照记进 store 并启动轮询，页面因此可以随意切走；
   * 同实例已有活跃任务时后端返回 409，原样抛给调用方提示。
   */
  async submitRunTask({ commit, dispatch }, { kind, params = {} }) {
    const submit = TASK_SUBMIT_API[kind];
    if (!submit) {
      throw new Error(`未知的监控任务类型: ${kind}`);
    }
    const res = await submit(params);
    const handle = res.data || res;
    if (!handle || !handle.task_id) {
      // 后端 async_mode=false 的同步兜底：返回的就是运行结果，没任务可轮询
      commit('SET_RUN_TASK', null);
      return handle;
    }
    commit('SET_RUN_TASK', handle);
    dispatch('startTaskPolling', handle.task_id);
    return handle;
  },

  async runMonitorAction({ commit, dispatch, state }, data = {}) {
    const id = resolveMonitorId(state, data.monitor_id);
    if (!id) {
      throw new Error('未选择监控策略，无法运行日常监控');
    }
    try {
      commit('SET_LOADING', true);
      return await dispatch('submitRunTask', {
        kind: 'monitor_run',
        params: { ...data, monitor_id: id }
      });
    } catch (error) {
      console.error('提交监控运行任务失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async initMonitorAction({ commit, dispatch, state }, data = {}) {
    const id = resolveMonitorId(state, data.monitor_id);
    if (!id) {
      throw new Error('未选择监控策略，无法初始化监控');
    }
    try {
      commit('SET_LOADING', true);
      return await dispatch('submitRunTask', {
        kind: 'monitor_init',
        params: { ...data, monitor_id: id }
      });
    } catch (error) {
      console.error('提交初始化任务失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async runMonitorRangeAction({ commit, dispatch, state }, data = {}) {
    const id = resolveMonitorId(state, data.monitor_id);
    if (!id) {
      throw new Error('未选择监控策略，无法运行监控');
    }
    try {
      commit('SET_LOADING', true);
      return await dispatch('submitRunTask', {
        kind: 'monitor_range',
        params: { ...data, monitor_id: id }
      });
    } catch (error) {
      console.error('提交补算任务失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  /** 轮询任务进度：不切全局 loading，避免每 2 秒闪一次 */
  startTaskPolling({ commit, dispatch }, taskId) {
    stopPolling();
    if (!taskId) return;
    pollTimer = setInterval(async () => {
      if (pollBusy) return;
      pollBusy = true;
      try {
        const res = await monitorApi.getMonitorTask(taskId);
        const task = res.data || res;
        if (!task || !task.task_id) return;
        commit('SET_RUN_TASK', task);
        if (ACTIVE_TASK_STATUS.indexOf(task.status) < 0) {
          stopPolling();
          await dispatch('handleTaskFinished', task);
        }
      } catch (e) {
        // 单次轮询失败保留上一次状态，下一轮继续
      } finally {
        pollBusy = false;
      }
    }, POLL_INTERVAL_MS);
  },

  stopTaskPolling() {
    stopPolling();
  },

  /**
   * 任务到达终态：完成的批次立即成为展示口径，随后刷新批次列表，
   * 最后打上 finishedAt 时间戳让页面组件去重载各展示区。
   * 顺序不可颠倒——组件的刷新依赖 currentBatchId 已指向新批次。
   */
  async handleTaskFinished({ commit, dispatch, state }, task) {
    if (task && task.status === 'completed' && task.batch_id) {
      commit('SET_CURRENT_BATCH_ID', task.batch_id);
    }
    if (state.activeMonitorId) {
      await dispatch('fetchBatches', { monitor_id: state.activeMonitorId });
    }
    commit('SET_TASK_FINISHED', task);
  },

  /** 页面刷新/切换策略后恢复进行中的任务（init / run / run-range 均适用） */
  async resumeActiveTaskAction({ commit, dispatch, state }, monitorId) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) return null;
    try {
      const res = await monitorApi.getActiveMonitorTask(id);
      const task = res.data || res;
      if (!task || !task.task_id) {
        commit('SET_RUN_TASK', null);
        return null;
      }
      commit('SET_RUN_TASK', task);
      if (ACTIVE_TASK_STATUS.indexOf(task.status) >= 0) {
        dispatch('startTaskPolling', task.task_id);
      }
      return task;
    } catch (e) {
      // 恢复失败静默：不影响页面其他功能
      return null;
    }
  },

  async fetchSubjectiveOverrides({ commit, state }, params = {}) {
    const id = resolveMonitorId(state, params.monitor_id);
    if (!id) {
      commit('SET_SUBJECTIVE_OVERRIDES', []);
      return [];
    }
    try {
      commit('SET_LOADING', true);
      const payload = { ...params, monitor_id: id };
      // 不默认锁展示批次：已执行调整需要跨批次带上，
      // 否则补录重算换批次后，补录记录会从列表里消失
      if (params.batch_id) {
        payload.batch_id = params.batch_id;
      } else {
        delete payload.batch_id;
      }
      const res = await monitorApi.getSubjectiveOverrides(payload);
      const data = Array.isArray(res) ? res : (res.data || []);
      commit('SET_SUBJECTIVE_OVERRIDES', data);
      return data;
    } catch (error) {
      console.warn('获取主观调仓指令失败（可能未初始化）:', error.message);
      commit('SET_SUBJECTIVE_OVERRIDES', []);
      return [];
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async addSubjectiveOverrideAction({ commit, dispatch, state }, data) {
    const id = resolveMonitorId(state, data.monitor_id);
    if (!id) {
      throw new Error('未选择监控策略，无法提交主观调仓');
    }
    const payload = { ...data, monitor_id: id };
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.addSubjectiveOverride(payload);
      const handle = res.data || res;
      // 补录模式后端已提交净值重算任务：接管任务快照并轮询，完成后页面自动刷新
      if (handle && handle.task && handle.task.task_id) {
        commit('SET_RUN_TASK', handle.task);
        dispatch('startTaskPolling', handle.task.task_id);
      }
      await dispatch('fetchSubjectiveOverrides', { monitor_id: id });
      return handle;
    } catch (error) {
      console.error('添加主观调仓指令失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async cancelSubjectiveOverrideAction({ commit, dispatch, state }, { overrideId, monitorId }) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) {
      throw new Error('未选择监控策略，无法取消指令');
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.cancelSubjectiveOverride(overrideId);
      await dispatch('fetchSubjectiveOverrides', { monitor_id: id });
      return res.data || res;
    } catch (error) {
      console.error('取消主观调仓指令失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchPerformancePanel({ commit, state }, params = {}) {
    const id = resolveMonitorId(state, params.monitor_id);
    if (!id) {
      commit('SET_PERFORMANCE_PANEL', null);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getPerformancePanel({
        monitor_id: id,
        start: params.start || undefined,
        end: params.end || undefined,
        batch_id: resolveBatchId(state, params.batch_id)
      });
      const data = res.data || res;
      commit('SET_PERFORMANCE_PANEL', data);
      return data;
    } catch (error) {
      console.warn('获取绩效页数据失败（可能未初始化）:', error.message);
      commit('SET_PERFORMANCE_PANEL', null);
      return null;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchAssetAnalysis({ commit }, { thscodes, startDate, endDate }) {
    try {
      var start = startDate.replace(/-/g, '');
      var end = endDate.replace(/-/g, '');

      var results = await Promise.all([
        monitorApi.getPositionsCorrelationMatrix({
          thscodes: thscodes,
          start_date: start,
          end_date: end
        }),
        monitorApi.getPositionsAssetMetrics({
          thscodes: thscodes,
          start_date: start,
          end_date: end
        })
      ]);

      var correlationRes = results[0];
      var metricsRes = results[1];

      var correlationData = (correlationRes && correlationRes.data) ? correlationRes.data : correlationRes;
      var metricsData = (metricsRes && metricsRes.data) ? metricsRes.data : metricsRes;

      commit('SET_CORRELATION_MATRIX', correlationData);
      commit('SET_ASSET_METRICS', Array.isArray(metricsData) ? metricsData : []);

      return { correlationData: correlationData, metricsData: metricsData };
    } catch (error) {
      console.warn('获取资产分析数据失败:', error);
      commit('SET_CORRELATION_MATRIX', null);
      commit('SET_ASSET_METRICS', []);
      return null;
    }
  }
};

const getters = {
  monitorState: state => state.monitorState,
  activeMonitorId: state => state.activeMonitorId,
  isLoading: state => state.loading,
  latestNav: state => state.monitorState && state.monitorState.nav,
  /** 当前展示批次（null = 跟随最新 completed 批次） */
  currentBatchId: state => state.currentBatchId,
  batchList: state => state.batchList,
  runTask: state => state.runTask,
  lastFinishedTask: state => state.lastFinishedTask,
  /** 任务进行中：运行按钮与批次切换器在此期间置灰 */
  isTaskActive: state => !!(state.runTask && ACTIVE_TASK_STATUS.indexOf(state.runTask.status) >= 0),
  hasActiveSignals: state => {
    if (!state.signals) return false;
    return state.signals.has_rebalance_signal || state.signals.has_subjective_pending;
  }
};

export default {
  namespaced: true,
  state,
  mutations,
  actions,
  getters
};
