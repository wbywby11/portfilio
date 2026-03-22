import {
  getTemplateList,
  getTemplate,
  createTemplate,
  updateTemplate,
  createStrategyModel,
  getStrategyModelList,
  getStrategyModel,
  runBacktest,
  publishModel,
  livePublishModel as livePublishModelApi,
  liveUnpublishModel as liveUnpublishModelApi,
  updateLiveConfig as updateLiveConfigApi,
  getLivePublishedModelList,
  getLiveMonitoring as getLiveMonitoringApi,
  getLiveConfig as getLiveConfigApi,
  confirmManualRebalance as confirmManualRebalanceApi,
  getLiveChangeLogs as getLiveChangeLogsApi,
  deleteStrategyModel as deleteStrategyModelApi,
  updateStrategyModel as updateStrategyModelApi
} from '@/api/strategy';
import request from '@/utils/request';

const state = {
  templateList: [],
  strategyModelList: [],
  currentTemplate: null,
  currentModel: null,
  loading: false
};

const mutations = {
  SET_TEMPLATE_LIST(state, list) {
    state.templateList = list;
  },
  SET_STRATEGY_MODEL_LIST(state, list) {
    state.strategyModelList = list;
  },
  SET_CURRENT_TEMPLATE(state, template) {
    state.currentTemplate = template;
  },
  SET_CURRENT_MODEL(state, model) {
    state.currentModel = model;
  },
  SET_LOADING(state, loading) {
    state.loading = loading;
  },
  ADD_STRATEGY_MODEL(state, model) {
    state.strategyModelList.unshift(model);
  },
  UPDATE_STRATEGY_MODEL(state, model) {
    const index = state.strategyModelList.findIndex(m => m.id === model.id);
    if (index !== -1) {
      state.strategyModelList.splice(index, 1, model);
    }
  },
  DELETE_STRATEGY_MODEL(state, id) {
    const index = state.strategyModelList.findIndex(m => m.id === id);
    if (index !== -1) {
      state.strategyModelList.splice(index, 1);
    }
  },
  DELETE_TEMPLATE(state, id) {
    const index = state.templateList.findIndex(t => t.id === id);
    if (index !== -1) {
      state.templateList.splice(index, 1);
    }
  }
};

const actions = {
  // 获取模型模板列表
  async fetchTemplateList({ commit }) {
    try {
      const res = await getTemplateList();
      // 后端返回的数据可能被包装在 data 字段中
      const list = Array.isArray(res) ? res : (res.data || []);
      commit('SET_TEMPLATE_LIST', list);
      return list;
    } catch (error) {
      console.error('获取模板列表失败:', error);
      throw error;
    }
  },

  // 获取单个模板
  async fetchTemplate({ commit }, code) {
    try {
      const res = await getTemplate(code);
      const template = res.data || res;
      commit('SET_CURRENT_TEMPLATE', template);
      return template;
    } catch (error) {
      console.error('获取模板失败:', error);
      throw error;
    }
  },

  // 创建模板
  async createTemplate({ commit }, data) {
    try {
      const res = await createTemplate(data);
      const templateCode = res.data || res;
      return templateCode;
    } catch (error) {
      console.error('创建模板失败:', error);
      throw error;
    }
  },

  // 更新模板
  async updateTemplate({ commit }, { templateId, data }) {
    try {
      const res = await updateTemplate(templateId, data);
      const result = res.data || res;
      return result;
    } catch (error) {
      console.error('更新模板失败:', error);
      throw error;
    }
  },

  // 删除模板
  async deleteTemplate({ commit }, templateId) {
    try {
      // 调用后端删除接口
      await request({
        url: `/api/v1/model-templates/${templateId}`,
        method: 'delete'
      });
      commit('DELETE_TEMPLATE', templateId);
    } catch (error) {
      console.error('删除模板失败:', error);
      throw error;
    }
  },

  // 获取策略模型列表
  async fetchStrategyModelList({ commit }, params) {
    try {
      const res = await getStrategyModelList(params);
      const list = Array.isArray(res) ? res : (res.data || []);
      commit('SET_STRATEGY_MODEL_LIST', list);
      return list;
    } catch (error) {
      console.error('获取策略模型列表失败:', error);
      throw error;
    }
  },

  // 获取单个策略模型
  async fetchStrategyModel({ commit }, modelId) {
    try {
      const res = await getStrategyModel(modelId);
      const model = res.data || res;
      commit('SET_CURRENT_MODEL', model);
      return model;
    } catch (error) {
      console.error('获取策略模型失败:', error);
      throw error;
    }
  },

  // 创建策略模型
  async createStrategyModel({ commit }, data) {
    try {
      const res = await createStrategyModel(data);
      const modelId = res.data || res;
      return modelId;
    } catch (error) {
      console.error('创建策略模型失败:', error);
      throw error;
    }
  },

  // 运行回测（返回完整响应 { code, data, message }，便于组件统一从 result.data 取 payload 含 record_id）
  async runBacktest({ commit }, { modelId, data }) {
    try {
      const res = await runBacktest(modelId, data);
      return res;
    } catch (error) {
      console.error('运行回测失败:', error);
      throw error;
    }
  },

  // 获取回测历史
  async fetchBacktestHistory({ commit }, { modelId, skip = 0, limit = 100 }) {
    try {
      const res = await request({
        url: `/api/v1/strategy-models/${modelId}/backtests`,
        method: 'get',
        params: {
          skip,
          limit
        }
      });
      const history = Array.isArray(res) ? res : (res.data || []);
      return history;
    } catch (error) {
      console.error('获取回测历史失败:', error);
      // 如果后端没有这个接口，返回空数组
      return [];
    }
  },

  // 发布模型
  async publishModel({ commit, state }, modelId) {
    try {
      const res = await publishModel(modelId);
      const result = res.data || res;
      
      // 更新 store 中对应策略的状态
      const model = state.strategyModelList.find(m => m.id === modelId);
      if (model) {
        commit('UPDATE_STRATEGY_MODEL', {
          ...model,
          status: '已发布',
          published_at: new Date().toISOString()
        });
      }
      
      return result;
    } catch (error) {
      console.error('发布模型失败:', error);
      throw error;
    }
  },

  // 实盘发布（与普通发布不冲突）
  async livePublishModel({ commit, state }, { modelId, data }) {
    try {
      const res = await livePublishModelApi(modelId, data || {});
      if (res && res.code !== undefined && res.code !== 200) {
        throw new Error(res.message || '实盘发布失败');
      }
      const result = res.data !== undefined ? res.data : res;
      if (result === false) {
        throw new Error('实盘发布未生效：数据库未更新（模型不存在或状态不允许）');
      }

      const model = state.strategyModelList.find(m => m.id === modelId);
      if (model) {
        commit('UPDATE_STRATEGY_MODEL', {
          ...model,
          live_publish_enabled: true,
          live_snapshot_outdated: false,
          live_published_at: new Date().toISOString()
        });
      }
      return result;
    } catch (error) {
      console.error('实盘发布失败:', error);
      throw error;
    }
  },

  async liveUnpublishModel({ commit, state }, { modelId, params }) {
    try {
      const res = await liveUnpublishModelApi(modelId, params || {});
      if (res && res.code !== undefined && res.code !== 200) {
        throw new Error(res.message || '取消实盘发布失败');
      }
      const result = res.data !== undefined ? res.data : res;
      if (result === false) {
        throw new Error('取消实盘发布未生效：数据库未更新');
      }
      const model = state.strategyModelList.find(m => m.id === modelId);
      if (model) {
        commit('UPDATE_STRATEGY_MODEL', {
          ...model,
          live_publish_enabled: false
        });
      }
      return result;
    } catch (error) {
      console.error('取消实盘发布失败:', error);
      throw error;
    }
  },

  async updateLiveConfig({ commit, state }, { modelId, data }) {
    try {
      const res = await updateLiveConfigApi(modelId, data);
      const result = res.data || res;
      const model = state.strategyModelList.find(m => m.id === modelId);
      if (model) {
        commit('UPDATE_STRATEGY_MODEL', {
          ...model,
          live_rebalance_mode: data.rebalance_mode || model.live_rebalance_mode,
          live_volatility_threshold: Object.prototype.hasOwnProperty.call(data, 'volatility_threshold')
            ? data.volatility_threshold
            : model.live_volatility_threshold
        });
      }
      return result;
    } catch (error) {
      console.error('更新实盘配置失败:', error);
      throw error;
    }
  },

  async fetchLivePublishedModelList({ commit }, params) {
    try {
      const res = await getLivePublishedModelList(params);
      return Array.isArray(res) ? res : (res.data || []);
    } catch (error) {
      console.error('获取实盘发布列表失败:', error);
      throw error;
    }
  },

  async fetchLiveMonitoring({ commit }, modelId) {
    try {
      const res = await getLiveMonitoringApi(modelId);
      return res.data || res;
    } catch (error) {
      console.error('获取实盘监控失败:', error);
      throw error;
    }
  },

  async fetchLiveConfig({ commit }, modelId) {
    try {
      const res = await getLiveConfigApi(modelId);
      return res.data || res;
    } catch (error) {
      console.error('获取实盘配置失败:', error);
      throw error;
    }
  },

  async confirmManualRebalance({ commit }, { modelId, data }) {
    try {
      const res = await confirmManualRebalanceApi(modelId, data);
      return res.data || res;
    } catch (error) {
      console.error('手动调仓确认失败:', error);
      throw error;
    }
  },

  async fetchLiveChangeLogs({ commit }, { modelId, params }) {
    try {
      const res = await getLiveChangeLogsApi(modelId, params);
      return Array.isArray(res) ? res : (res.data || []);
    } catch (error) {
      console.error('获取实盘变更日志失败:', error);
      throw error;
    }
  },

  // 删除策略模型
  async deleteStrategyModel({ commit }, modelId) {
    try {
      await deleteStrategyModelApi(modelId);
      commit('DELETE_STRATEGY_MODEL', modelId);
      return true;
    } catch (error) {
      console.error('删除策略模型失败:', error);
      throw error;
    }
  },

  // 计算策略（策略开发页面使用）
  // 注意：后端没有独立的计算接口，这里使用创建策略模型接口
  // 创建时后端会自动执行算法计算并返回结果
  async calculateStrategy({ commit }, { assets, template, parameters }) {
    try {
      // 构建临时策略模型数据
      const tempModelData = {
        name: `临时计算_${Date.now()}`,
        template_id: template,
        asset_codes: assets.map(a => a.asset_code),
        parameters: parameters,
        is_temp: true  // 标记为临时模型
      };

      // 使用创建策略模型接口，后端会自动计算并返回结果
      const res = await createStrategyModel(tempModelData);
      const result = res.data || res;
      
      // 如果返回的是模型ID，需要再次获取模型详情来获取计算结果
      if (typeof result === 'string') {
        const modelRes = await getStrategyModel(result);
        const model = modelRes.data || modelRes;
        return {
          expectedReturn: model.expected_return || 0,
          expectedRisk: model.expected_risk || 0,
          sharpeRatio: model.sharpe_ratio || 0,
          weights: model.weights || {}
        };
      }
      
      return result;
    } catch (error) {
      console.error('计算策略失败:', error);
      throw error;
    }
  },

  // 保存策略（将计算结果保存为策略模型）
  async saveStrategy({ commit }, strategyData) {
    try {
      // 构建策略模型数据
      const modelData = {
        name: strategyData.name,
        template_id: strategyData.templateId,
        asset_codes: strategyData.assets.map(a => a.asset_code),
        parameters: strategyData.parameters,
        calculation_result: strategyData.result
      };

      const res = await createStrategyModel(modelData);
      const modelId = res.data || res;
      
      commit('ADD_STRATEGY_MODEL', {
        id: modelId,
        ...modelData,
        status: 'draft',
        created_at: new Date().toISOString()
      });

      return modelId;
    } catch (error) {
      console.error('保存策略失败:', error);
      throw error;
    }
  },

  // 更新策略模型
  async updateStrategyModel({ commit }, { modelId, data }) {
    try {
      const res = await updateStrategyModelApi(modelId, data);
      const model = res.data || res;
      
      commit('UPDATE_STRATEGY_MODEL', {
        id: modelId,
        ...model
      });

      return model;
    } catch (error) {
      console.error('更新策略模型失败:', error);
      throw error;
    }
  }
};

const getters = {
  getTemplateById: state => id => {
    return state.templateList.find(t => t.id === id);
  },
  getStrategyModelById: state => id => {
    return state.strategyModelList.find(m => m.id === id);
  },
  // 为了兼容性，提供 strategyList 作为 strategyModelList 的别名
  strategyList: state => state.strategyModelList
};

export default {
  namespaced: true,
  state,
  mutations,
  actions,
  getters
};
