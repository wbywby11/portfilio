import * as monitorApi from '@/api/monitor';

const state = {
  monitorState: null,        // 当前监控状态
  navHistory: [],            // 净值历史
  positions: [],             // 持仓明细
  performance: null,         // 绩效指标
  signals: null,             // 信号状态
  events: [],                // 事件日志
  reportList: [],            // 日报列表
  currentReport: null,       // 当前日报
  subjectiveOverrides: [],   // 主观调仓指令列表
  assetMetrics: [],          // 资产波动率指标
  correlationMatrix: null,   // 资产相关性矩阵
  loading: false
};

const mutations = {
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
  // 获取监控状态
  async fetchMonitorState({ commit }, monitorId = 'default') {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorState(monitorId);
      const data = res.data || res;
      commit('SET_MONITOR_STATE', data);
      return data;
    } catch (error) {
      // 404 表示未初始化，不抛异常，保持 monitorState 为 null
      console.warn('获取监控状态失败（可能未初始化）:', error.message);
      commit('SET_MONITOR_STATE', null);
      return null;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  // 获取净值历史
  async fetchNavHistory({ commit }, params = {}) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getNavHistory(params);
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

  // 获取持仓明细
  async fetchPositions({ commit }, monitorId = 'default') {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorPositions(monitorId);
      const payload = res.data || res;
      // 如果 payload 是对象且包含 positions 数组，则提取
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

  // 获取绩效指标
  async fetchPerformance({ commit }, monitorId = 'default') {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorPerformance(monitorId);
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

  // 获取信号状态
  async fetchSignals({ commit }, monitorId = 'default') {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorSignals(monitorId);
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

  // 获取事件日志
  async fetchEvents({ commit }, params = {}) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorEvents(params);
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

  // 获取日报列表
  async fetchReportList({ commit }, params = {}) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorReportList(params);
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

  // 获取指定日期日报
  async fetchReport({ commit }, { date, monitorId = 'default' }) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getMonitorReport(date, monitorId);
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

  // 运行监控（单日）
  async runMonitorAction({ commit }, data) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.runMonitor(data);
      return res.data || res;
    } catch (error) {
      console.error('运行监控失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  // 初始化监控
  async initMonitorAction({ commit }, data) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.initMonitor(data);
      return res.data || res;
    } catch (error) {
      console.error('初始化监控失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  // 运行监控（日期范围）
  async runMonitorRangeAction({ commit }, data) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.runMonitorRange(data);
      return res.data || res;
    } catch (error) {
      console.error('运行监控（范围）失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  // 获取主观调仓指令列表
  async fetchSubjectiveOverrides({ commit }, params = {}) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.getSubjectiveOverrides(params);
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

  // 添加主观调仓指令
  async addSubjectiveOverrideAction({ commit, dispatch }, data) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.addSubjectiveOverride(data);
      // 重新获取列表以更新状态
      await dispatch('fetchSubjectiveOverrides', { monitor_id: data.monitor_id });
      return res.data || res;
    } catch (error) {
      console.error('添加主观调仓指令失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  // 取消主观调仓指令
  async cancelSubjectiveOverrideAction({ commit, dispatch }, { overrideId, monitorId = 'default' }) {
    try {
      commit('SET_LOADING', true);
      const res = await monitorApi.cancelSubjectiveOverride(overrideId);
      // 重新获取列表以更新状态
      await dispatch('fetchSubjectiveOverrides', { monitor_id: monitorId });
      return res.data || res;
    } catch (error) {
      console.error('取消主观调仓指令失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  // 获取资产分析数据（相关性矩阵和波动率指标）
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
      
      // 后端返回格式可能是 {code: 0, data: {...}} 或直接是数据
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
