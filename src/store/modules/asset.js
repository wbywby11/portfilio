import { getAssetList, createAsset, getAssetOptions, updateAsset as updateAssetApi, deleteAsset as deleteAssetApi } from '@/api/asset';

const state = {
  assetList: [],
  // 三维度正交分类（对标 Bloomberg / Wind / FactSet）
  // 详见后端 docs/DATA_ARCHITECTURE.md 第八章 8.1-8.3
  instrumentTypes: [
    { value: '指数型', label: '指数型', hint: '无特殊处理，直接使用收盘价' },
    { value: '现货型', label: '现货型', hint: '有上市切换，需配置替代标的' },
    { value: '期货型', label: '期货型', hint: '需主力合约展期，需配置展期参数' }
  ],
  assetClasses: [
    { value: '权益', label: '权益' },
    { value: '固收', label: '固收' },
    { value: '商品', label: '商品' },
    { value: '货币', label: '货币' },
    { value: '另类', label: '另类' }
  ],
  securityTypes: [
    { value: '股票', label: '股票' },
    { value: '指数', label: '指数' },
    { value: 'ETF', label: 'ETF' },
    { value: 'LOF', label: 'LOF' },
    { value: '基金', label: '基金' },
    { value: '债券', label: '债券' },
    { value: '期货', label: '期货' },
    { value: '数字货币', label: '数字货币' },
    { value: '存款', label: '存款' }
  ],
  // [已废弃] 保留供旧代码/旧视图过渡
  assetCategories: [
    { value: '指数型', label: '指数型' },
    { value: '现货型', label: '现货型' },
    { value: '期货型', label: '期货型' }
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
        // 三维度正交过滤（新字段，优先）
        instrument_type: params.instrument_type || undefined,
        asset_class: params.asset_class || undefined,
        security_type: params.security_type || undefined,
        // [已废弃] 旧字段兼容
        asset_type: params.category || undefined,
        is_active: params.status !== 'inactive',
        code: params.code || undefined,
        name: params.name || undefined,
        skip: ((params.page || 1) - 1) * (params.pageSize || 20),
        limit: params.pageSize || 20
      });
      
      // DEBUG: 诊断分页问题
      console.log('[DEBUG fetchAssetList] response keys:', Object.keys(response));
      console.log('[DEBUG fetchAssetList] response.data type:', typeof response.data, Array.isArray(response.data) ? 'ARRAY' : 'OBJECT');
      console.log('[DEBUG fetchAssetList] response.data keys:', response.data ? Object.keys(response.data) : 'null');
      
      // 后端返回 PageData：{ items: [], total, page, page_size, pages }
      const pageData = Array.isArray(response) ? null : (response.data || null);
      const rawList = pageData && pageData.items ? pageData.items
        : (Array.isArray(response) ? response : (response.data || []));
      const total = pageData && pageData.total != null ? pageData.total : rawList.length;
      const list = rawList.map(item => ({
        id: item.id,
        code: item.code,
        name: item.name,
        // 新三维度字段
        instrument_type: item.instrument_type,
        asset_class: item.asset_class,
        security_type: item.security_type,
        // [已废弃] 旧字段保留为兼容（迁移后移除）
        asset_type: item.asset_type || item.instrument_type,
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
      commit('SET_TOTAL', total);
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
  async fetchAssetOptions({ commit }, params) {
    try {
      // 支持传入对象 { instrument_type, asset_class, asset_type } 或旧的字符串
      const queryParams = typeof params === 'string'
        ? { asset_type: params }
        : (params || {});
      const response = await getAssetOptions(queryParams);
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
    // [兼容] 同时支持新旧字段过滤
    return state.assetList.filter(a =>
      a.instrument_type === category || a.asset_type === category
    );
  },
  getAssetsByClass: state => assetClass => {
    return state.assetList.filter(a => a.asset_class === assetClass);
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
