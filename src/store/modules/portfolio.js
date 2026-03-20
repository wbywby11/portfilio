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

import * as portfolioApi from '@/api/portfolio';

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
    try {
      const res = await portfolioApi.createPortfolio(portfolio);
      // 重新获取列表以更新状态
      const list = await portfolioApi.getPortfolioList();
      commit('SET_PORTFOLIO_LIST', list.data || []);
      return res.data;
    } catch (error) {
      console.error('创建组合失败:', error);
      throw error;
    }
  },
  
  async updatePortfolio({ commit }, portfolio) {
    commit('UPDATE_PORTFOLIO', portfolio);
    return portfolio;
  },
  
  async deletePortfolio({ commit }, id) {
    try {
      await portfolioApi.deletePortfolio(id);
      commit('DELETE_PORTFOLIO', id);
      return true;
    } catch (error) {
      console.error('删除组合失败:', error);
      throw error;
    }
  },
  
  async fetchPortfolioDetail({ commit }, id) {
    // 模拟API调用获取详细信息
    const portfolio = state.portfolioList.find(p => p.id === id);
    if (portfolio) {
      commit('SET_CURRENT_PORTFOLIO', portfolio);
    }
    return portfolio;
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
