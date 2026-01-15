import { getAssetList, createAsset, getAssetOptions, updateAsset as updateAssetApi, deleteAsset as deleteAssetApi } from '@/api/asset';

const state = {
  assetList: [],
  assetCategories: [
    { value: '股票', label: '股票' },
    { value: '债券', label: '债券' },
    { value: '基金', label: '基金' },
    { value: '商品', label: '商品' },
    { value: '货币', label: '货币' },
    { value: '指数', label: '指数' },
    { value: '数字货币', label: '数字货币' }
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
      
      // 后端返回的数据可能被包装在 data 字段中
      const rawList = Array.isArray(response) ? response : (response.data || []);
      const list = rawList.map(item => ({
        id: item.id,                  // 保存 id 用于更新和删除
        asset_code: item.code,        // 后端 code -> 前端 asset_code
        asset_name: item.name,        // 后端 name -> 前端 asset_name
        asset_type: item.asset_type,
        expected_return: item.expected_return || 0,
        volatility: item.volatility || 0,
        is_active: item.is_active,
        data_source: item.data_source,
        description: item.description,
        exchange: item.exchange,
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
      // 转换字段名称以匹配后端 API
      const assetData = {
        code: asset.code,  // 后端期望 code 而不是 asset_code
        name: asset.name,  // 后端期望 name 而不是 asset_name
        asset_type: asset.category,  // 使用中文枚举值
        expected_return: asset.expectedReturn,
        volatility: asset.volatility,
        data_source: asset.dataSource || 'MANUAL',
        description: asset.description || ''
      };
      
      const assetCode = await createAsset(assetData);
      
      // 添加到列表
      commit('ADD_ASSET', {
        asset_code: assetCode,
        asset_name: asset.name,
        asset_type: asset.category,
        expected_return: asset.expectedReturn,
        volatility: asset.volatility,
        data_source: asset.dataSource || 'MANUAL',
        description: asset.description || '',
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
      // 转换字段名称以匹配后端 API
      const assetData = {
        name: data.name,  // 后端期望 name
        asset_type: data.category,  // 使用中文枚举值
        expected_return: data.expectedReturn,
        volatility: data.volatility,
        data_source: data.dataSource || 'MANUAL',
        description: data.description || ''
      };
      
      await updateAssetApi(assetId, assetData);
      
      // 更新 Store 中的数据
      commit('UPDATE_ASSET', {
        id: assetId,
        asset_code: data.code,
        asset_name: data.name,
        asset_type: data.category,
        expected_return: data.expectedReturn,
        volatility: data.volatility,
        data_source: data.dataSource || 'MANUAL',
        description: data.description || ''
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
    return state.assetList.find(a => a.asset_code === code);
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
