const state = {
  token: localStorage.getItem('token') || '',
  userInfo: JSON.parse(localStorage.getItem('userInfo') || '{}'),
  permissions: []
};

const mutations = {
  SET_TOKEN(state, token) {
    state.token = token;
    localStorage.setItem('token', token);
  },
  SET_USER_INFO(state, userInfo) {
    state.userInfo = userInfo;
    localStorage.setItem('userInfo', JSON.stringify(userInfo));
  },
  SET_PERMISSIONS(state, permissions) {
    state.permissions = permissions;
  },
  LOGOUT(state) {
    state.token = '';
    state.userInfo = {};
    state.permissions = [];
    localStorage.removeItem('token');
    localStorage.removeItem('userInfo');
  }
};

const actions = {
  // 登录
  async login({ commit }, loginForm) {
    try {
      // 模拟登录API调用
      const response = await new Promise((resolve) => {
        setTimeout(() => {
          // 模拟不同角色的用户
          const users = {
            admin: {
              token: 'admin-token-123',
              userInfo: {
                id: 1,
                username: 'admin',
                name: '系统管理员',
                role: 'admin',
                email: 'admin@investment.com'
              },
              permissions: ['all']
            },
            manager: {
              token: 'manager-token-456',
              userInfo: {
                id: 2,
                username: 'manager',
                name: '投资经理',
                role: 'manager',
                email: 'manager@investment.com'
              },
              permissions: ['portfolio:manage', 'strategy:view', 'report:export']
            },
            researcher: {
              token: 'researcher-token-789',
              userInfo: {
                id: 3,
                username: 'researcher',
                name: '研究员',
                role: 'researcher',
                email: 'researcher@investment.com'
              },
              permissions: ['strategy:create', 'strategy:test', 'analysis:use']
            }
          };
          
          const user = users[loginForm.username] || users.researcher;
          resolve(user);
        }, 500);
      });
      
      commit('SET_TOKEN', response.token);
      commit('SET_USER_INFO', response.userInfo);
      commit('SET_PERMISSIONS', response.permissions);
      
      return { success: true };
    } catch (error) {
      return { success: false, message: error.message };
    }
  },
  
  // 登出
  logout({ commit }) {
    commit('LOGOUT');
  },
  
  // 获取用户信息
  async getUserInfo({ commit, state }) {
    if (!state.token) {
      throw new Error('未登录');
    }
    // 这里可以调用API获取最新用户信息
    return state.userInfo;
  }
};

const getters = {
  isLoggedIn: state => !!state.token,
  userRole: state => state.userInfo.role || '',
  userName: state => state.userInfo.name || '',
  hasPermission: state => permission => {
    if (state.permissions.includes('all')) return true;
    return state.permissions.includes(permission);
  }
};

export default {
  namespaced: true,
  state,
  mutations,
  actions,
  getters
};
