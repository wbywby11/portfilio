import Vue from 'vue';
import Vuex from 'vuex';
import user from './modules/user';
import asset from './modules/asset';
import strategy from './modules/strategy';
import portfolio from './modules/portfolio';
import benchmark from './modules/benchmark';
import monitor from './modules/monitor';

Vue.use(Vuex);

export default new Vuex.Store({
  modules: {
    user,
    asset,
    strategy,
    portfolio,
    benchmark,
    monitor
  },
  state: {
    loading: false,
    collapsed: false
  },
  mutations: {
    SET_LOADING(state, loading) {
      state.loading = loading;
    },
    SET_COLLAPSED(state, collapsed) {
      state.collapsed = collapsed;
    }
  },
  actions: {
    setLoading({ commit }, loading) {
      commit('SET_LOADING', loading);
    },
    toggleCollapsed({ commit, state }) {
      commit('SET_COLLAPSED', !state.collapsed);
    }
  }
});
