import { getAssetList, createAsset, getAssetOptions, updateAsset as updateAssetApi, deleteAsset as deleteAssetApi } from '@/api/asset';

const state = {
  assetList: [],
  assetCategories: [
    { value: '指数类', label: '指数类' },
    { value: '现货类', label: '现货类' },
    { value: '期货类', label: '期货类' }
  ],
  selectedAssets: [],
  loading: false,
  total: 0
};

const mutations = {
  SET_ASSET_LIST(state, list) {
    state.assetList = list;
  },
  SET_TOTAL(state, total) {
    state.total = total;
  },
  SET_LOADING(state, loading) {
    state.loading = loading;
  },
  ADD_ASSET(state, asset) {
    state.assetList.unshift(asset);
    state.total++;
  },
  UPDATE_ASSET(state, asset) {
    const index = state.assetList.findIndex(a => a.id === asset.id);
    if (index !== -1) {
      state.assetList.splice(index, 1, asset);
    }
  },
  DELETE_ASSET(state, assetId) {
    const index = state.assetList.findIndex(a => a.id === assetId);
    if (index !== -1) {
      state.assetList.splice(index, 1);
      state.total--;
    }
  },
  SET_SELECTED_ASSETS(state, assets) {
    state.selectedAssets = assets;
  }
};

const actions = {
  // 获取资产列表
  async fetchAssetList({ commit }, params = {}) {
    commit('SET_LOADING', true);
    try {
      const response = await getAssetList({
        asset_type: params.category,
        is_active: params.status !== 'inactive',
        skip: ((params.page || 1) - 1) * (params.pageSize || 20),
        limit: params.pageSize || 20
      });
      
      // 后端返回的数据可能被包装 in data 字段中
      const rawList = Array.isArray(response) ? response : (response.data || []);
      const list = rawList.map(item => ({
        id: item.id,
        code: item.code,
        name: item.name,
        asset_type: item.asset_type,
        exchange: item.exchange,
        description: item.description,
        rollover_days: item.rollover_days,
        rollover_threshold: item.rollover_threshold,
        rollover_window_p: item.rollover_window_p,
        rollover_window_q: item.rollover_window_q,
        substitute_code: item.substitute_code,
        switch_date: item.switch_date,
        is_active: item.is_active,
        created_at: item.created_at,
        updated_at: item.updated_at
      }));
      
      commit('SET_ASSET_LIST', list);
      commit('SET_TOTAL', list.length);
      return list;
    } catch (error) {
      console.error('获取资产列表失败:', error);
      commit('SET_ASSET_LIST', []);
      throw error;
    } finally {
      commit('SET_LOADING', false);
    }
  },
  
  // 获取资产选项（用于下拉框）
  async fetchAssetOptions({ commit }, assetType) {
    try {
      const response = await getAssetOptions(assetType);
      // 后端返回的数据可能被包装在 data 字段中
      const rawList = Array.isArray(response) ? response : (response.data || []);
      return rawList.map(item => ({
        code: item.code || item.asset_code,  // 兼容两种字段名
        name: item.name || item.asset_name,  // 兼容两种字段名
        label: `${item.code || item.asset_code} ${item.name || item.asset_name}`
      }));
    } catch (error) {
      console.error('获取资产选项失败:', error);
      return [];
    }
  },
  
  // 新增资产
  async addAsset({ commit }, asset) {
    try {
      const assetCode = await createAsset(asset);
      
      // 添加到列表
      commit('ADD_ASSET', {
        ...asset,
        is_active: true
      });
      
      return assetCode;
    } catch (error) {
      console.error('新增资产失败:', error);
      throw error;
    }
  },
  
  // 更新资产
  async updateAsset({ commit }, { assetId, data }) {
    try {
      await updateAssetApi(assetId, data);
      
      // 更新 Store 中的数据
      commit('UPDATE_ASSET', {
        id: assetId,
        ...data
      });
      
      return true;
    } catch (error) {
      console.error('更新资产失败:', error);
      throw error;
    }
  },
  
  // 删除资产
  async deleteAsset({ commit }, assetId) {
    try {
      await deleteAssetApi(assetId);
      commit('DELETE_ASSET', assetId);
    } catch (error) {
      console.error('删除资产失败:', error);
      throw error;
    }
  }
};

const getters = {
  getAssetByCode: state => code => {
    return state.assetList.find(a => a.code === code);
  },
  getAssetById: state => id => {
    return state.assetList.find(a => a.id === id);
  },
  getAssetsByCategory: state => category => {
    return state.assetList.filter(a => a.asset_type === category);
  },
  activeAssets: state => {
    return state.assetList.filter(a => a.is_active);
  }
};

export default {
  namespaced: true,
  state,
  mutations,
  actions,
  getters
};
