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
    // 模拟API调用
    const mockData = [];
    commit('SET_PORTFOLIO_LIST', mockData);
    return mockData;
  },
  
  async createPortfolio({ commit }, portfolio) {
    // 模拟API调用
    const newPortfolio = {
      ...portfolio,
      id: `P${Date.now()}`,
      status: 'active',
      createTime: new Date().toISOString(),
      totalValue: portfolio.initialCapital,
      totalReturn: 0,
      holdings: portfolio.holdings || []
    };
    
    commit('ADD_PORTFOLIO', newPortfolio);
    return newPortfolio;
  },
  
  async updatePortfolio({ commit }, portfolio) {
    commit('UPDATE_PORTFOLIO', portfolio);
    return portfolio;
  },
  
  async deletePortfolio({ commit }, id) {
    commit('DELETE_PORTFOLIO', id);
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
