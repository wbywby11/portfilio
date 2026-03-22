import * as monitorApi from '@/api/monitor';

function resolveMonitorId(state, explicit) {
  if (explicit !== undefined && explicit !== null && String(explicit).length > 0) {
    return explicit;
  }
  return state.activeMonitorId;
}

const state = {
  activeMonitorId: null,
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
  loading: false
};

const mutations = {
  SET_ACTIVE_MONITOR_ID(state, id) {
    state.activeMonitorId = id || null;
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
  SET_LOADING(state, loading) {
    state.loading = loading;
  }
};

const actions = {
  setActiveMonitorContext({ commit }, { monitorId }) {
    commit('SET_ACTIVE_MONITOR_ID', monitorId);
    commit('RESET_MONITOR_VIEW');
  },

  async fetchMonitorState({ commit, state }, monitorId) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) {
      commit('SET_MONITOR_STATE', null);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorState(id);
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
      const res = await monitorApi.getNavHistory({ ...params, monitor_id: id });
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
      const res = await monitorApi.getMonitorPositions(id);
      const payload = res.data || res;
      const positions = payload.positions || (Array.isArray(payload) ? payload : []);
      commit('SET_POSITIONS', positions);
      return payload;
    } catch (error) {
      console.error('获取持仓明细失败:', error);
      return null;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async fetchPerformance({ commit, state }, monitorId) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) {
      commit('SET_PERFORMANCE', null);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorPerformance(id);
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
      const res = await monitorApi.getMonitorSignals(id);
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
      const res = await monitorApi.getMonitorEvents({ ...params, monitor_id: id });
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
      const res = await monitorApi.getMonitorReportList({ ...params, monitor_id: id });
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

  async fetchReport({ commit, state }, { date, monitorId }) {
    const id = resolveMonitorId(state, monitorId);
    if (!id) {
      commit('SET_CURRENT_REPORT', null);
      return null;
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorReport(date, id);
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

  async runMonitorAction({ commit, state }, data = {}) {
    const id = resolveMonitorId(state, data.monitor_id);
    if (!id) {
      throw new Error('未选择监控策略，无法运行日常监控');
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.runMonitor({ ...data, monitor_id: id });
      return res.data || res;
    } catch (error) {
      console.error('运行监控失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async initMonitorAction({ commit, state }, data = {}) {
    const id = resolveMonitorId(state, data.monitor_id);
    if (!id) {
      throw new Error('未选择监控策略，无法初始化监控');
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.initMonitor({ ...data, monitor_id: id });
      return res.data || res;
    } catch (error) {
      console.error('初始化监控失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  async runMonitorRangeAction({ commit, state }, data = {}) {
    const id = resolveMonitorId(state, data.monitor_id);
    if (!id) {
      throw new Error('未选择监控策略，无法运行监控');
    }
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.runMonitorRange({ ...data, monitor_id: id });
      return res.data || res;
    } catch (error) {
      console.error('运行监控（范围）失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
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
      const res = await monitorApi.getSubjectiveOverrides({ ...params, monitor_id: id });
      const data = Array.isArray(res) ? res : (res.data || []);
      commit('SET_SUBJECTIVE_OVERRIDES', data);
      return data;
    } catch (error) {
      console.error('获取主观调仓指令失败:', error);
      throw error;
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
      await dispatch('fetchSubjectiveOverrides', { monitor_id: id });
      return res.data || res;
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
