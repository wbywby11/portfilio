import * as portfolioApi from '@/api/portfolio';

const state = {
  portfolioList: [],
  currentPortfolio: null,
  benchmarks: [
    { code: '000300.SH', name: '沪深300' },
    { code: '000905.SH', name: '中证500' },
    { code: '000906.SH', name: '中证800' },
    { code: '881001.WI', name: '万得全A' }
  ]
};

const mutations = {
  SET_PORTFOLIO_LIST(state, list) {
    state.portfolioList = list;
  },
  ADD_PORTFOLIO(state, portfolio) {
    state.portfolioList.push(portfolio);
  },
  UPDATE_PORTFOLIO(state, portfolio) {
    const index = state.portfolioList.findIndex(p => p.id === portfolio.id);
    if (index !== -1) {
      state.portfolioList.splice(index, 1, portfolio);
    }
  },
  DELETE_PORTFOLIO(state, id) {
    const index = state.portfolioList.findIndex(p => p.id === id);
    if (index !== -1) {
      state.portfolioList.splice(index, 1);
    }
  },
  SET_CURRENT_PORTFOLIO(state, portfolio) {
    state.currentPortfolio = portfolio;
  }
};

const actions = {
  async fetchPortfolioList({ commit }) {
    try {
      const res = await portfolioApi.getPortfolioList();
      const list = res.data || [];
      commit('SET_PORTFOLIO_LIST', list);
      return list;
    } catch (error) {
      console.error('获取组合列表失败:', error);
      return [];
    }
  },

  async createPortfolio({ commit }, portfolio) {
    const res = await portfolioApi.createPortfolio(portfolio);
    // 重新获取列表
    const list = await portfolioApi.getPortfolioList();
    commit('SET_PORTFOLIO_LIST', list.data || []);
    return res.data;
  },

  async createFromModel({ commit }, data) {
    const res = await portfolioApi.createFromModel(data);
    const list = await portfolioApi.getPortfolioList();
    commit('SET_PORTFOLIO_LIST', list.data || []);
    return res.data;
  },

  async createFromPortfolioModel({ commit }, data) {
    const res = await portfolioApi.createFromPortfolioModel(data);
    const list = await portfolioApi.getPortfolioList();
    commit('SET_PORTFOLIO_LIST', list.data || []);
    return res.data;
  },

  async createFromStrategies({ commit }, data) {
    const res = await portfolioApi.createFromStrategies(data);
    const list = await portfolioApi.getPortfolioList();
    commit('SET_PORTFOLIO_LIST', list.data || []);
    return res.data;
  },

  async adjustWeights({ commit }, { portfolioId, data }) {
    const res = await portfolioApi.adjustWeights(portfolioId, data);
    const list = await portfolioApi.getPortfolioList();
    commit('SET_PORTFOLIO_LIST', list.data || []);
    return res.data;
  },

  async fetchPortfolioDetails({ commit }, id) {
    try {
      const res = await portfolioApi.getPortfolioDetails(id);
      const detail = res.data || null;
      commit('SET_CURRENT_PORTFOLIO', detail);
      return detail;
    } catch (error) {
      console.error('获取组合详情失败:', error);
      return null;
    }
  },

  async deletePortfolio({ commit }, id) {
    await portfolioApi.deletePortfolio(id);
    commit('DELETE_PORTFOLIO', id);
    return true;
  }
};

const getters = {
  getPortfolioById: state => id => {
    return state.portfolioList.find(p => p.id === id);
  },
  activePortfolios: state => {
    return state.portfolioList.filter(p => p.status === 'active');
  }
};

export default {
  namespaced: true,
  state,
  mutations,
  actions,
  getters
};
