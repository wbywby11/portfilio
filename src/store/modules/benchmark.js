import {
  getBenchmarkList,
  getBenchmark,
  getBenchmarkByCode,
  createBenchmark,
  updateBenchmark,
  deleteBenchmark
} from '@/api/strategy';

const state = {
  benchmarkList: [],
  currentBenchmark: null,
  loading: false
};

const mutations = {
  SET_BENCHMARK_LIST(state, list) {
    state.benchmarkList = list;
  },
  SET_CURRENT_BENCHMARK(state, benchmark) {
    state.currentBenchmark = benchmark;
  },
  SET_LOADING(state, loading) {
    state.loading = loading;
  },
  ADD_BENCHMARK(state, benchmark) {
    state.benchmarkList.unshift(benchmark);
  },
  UPDATE_BENCHMARK(state, benchmark) {
    const index = state.benchmarkList.findIndex(b => b.id === benchmark.id);
    if (index !== -1) {
      state.benchmarkList.splice(index, 1, benchmark);
    }
  },
  DELETE_BENCHMARK(state, id) {
    const index = state.benchmarkList.findIndex(b => b.id === id);
    if (index !== -1) {
      state.benchmarkList.splice(index, 1);
    }
  }
};

const actions = {
  // 获取业绩基准列表
  async fetchBenchmarkList({ commit }) {
    try {
      commit('SET_LOADING', true);
      const res = await getBenchmarkList();
      const list = Array.isArray(res) ? res : (res.data || []);
      commit('SET_BENCHMARK_LIST', list);
      return list;
    } catch (error) {
      console.error('获取业绩基准列表失败:', error);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },

  // 获取单个业绩基准
  async fetchBenchmark({ commit }, benchmarkId) {
    try {
      const res = await getBenchmark(benchmarkId);
      const benchmark = res.data || res;
      commit('SET_CURRENT_BENCHMARK', benchmark);
      return benchmark;
    } catch (error) {
      console.error('获取业绩基准失败:', error);
      throw error;
    }
  },

  // 根据代码获取业绩基准
  async fetchBenchmarkByCode({ commit }, code) {
    try {
      const res = await getBenchmarkByCode(code);
      const benchmark = res.data || res;
      return benchmark;
    } catch (error) {
      console.error('根据代码获取业绩基准失败:', error);
      throw error;
    }
  },

  // 创建业绩基准
  async createBenchmark({ commit }, data) {
    try {
      const res = await createBenchmark(data);
      const benchmark = res.data || res;
      commit('ADD_BENCHMARK', benchmark);
      return benchmark;
    } catch (error) {
      console.error('创建业绩基准失败:', error);
      throw error;
    }
  },

  // 更新业绩基准
  async updateBenchmark({ commit }, { benchmarkId, data }) {
    try {
      const res = await updateBenchmark(benchmarkId, data);
      const benchmark = res.data || res;
      commit('UPDATE_BENCHMARK', benchmark);
      return benchmark;
    } catch (error) {
      console.error('更新业绩基准失败:', error);
      throw error;
    }
  },

  // 删除业绩基准
  async deleteBenchmark({ commit }, benchmarkId) {
    try {
      await deleteBenchmark(benchmarkId);
      commit('DELETE_BENCHMARK', benchmarkId);
    } catch (error) {
      console.error('删除业绩基准失败:', error);
      throw error;
    }
  }
};

const getters = {
  getBenchmarkById: state => id => {
    return state.benchmarkList.find(b => b.id === id);
  },
  getActiveBenchmarks: state => {
    return state.benchmarkList.filter(b => b.is_active !== false);
  }
};

export default {
  namespaced: true,
  state,
  mutations,
  actions,
  getters
};