import axios from 'axios';
import store from '@/store';
import { Message } from 'element-ui';

// 创建axios实例（默认 60s 超时，避免行情/列表等请求超时；单次可覆盖 timeout）
const service = axios.create({
  baseURL: process.env.VUE_APP_BASE_URL || 'http://127.0.0.1:8000',
  timeout: 60000
});

// 请求拦截器
service.interceptors.request.use(
  config => {
    // 添加token
    const token = store.state.user.token;
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
  },
  error => {
    console.error('请求错误:', error);
    return Promise.reject(error);
  }
);

// 响应拦截器
service.interceptors.response.use(
  response => {
    const res = response.data;
    return res;
  },
  error => {
    console.error('响应错误:', error);

    // 处理不同的错误状态码
    if (error.response) {
      const { status, data } = error.response;

      switch (status) {
        case 401:
          Message.error('未授权，请重新登录');
          store.dispatch('user/logout');
          break;
        case 403: {
          const detail = data && (data.detail || data.message);
          Message.error(detail ? String(detail) : '拒绝访问');
          break;
        }
        case 404:
          if (error.config && error.config.skipGlobal404Message) {
            break;
          }
          Message.error('请求的资源不存在');
          break;
        // 500 和其他业务错误由组件级 catch 处理
      }
    } else if (error.request) {
      // 无 response：连接失败、超时、跨域、后端未启动等
      const msg = (error.message || '').toLowerCase();
      const isTimeout = msg.includes('timeout') || error.code === 'ECONNABORTED';
      const isNetwork = msg.includes('network') || msg.includes('failed to fetch') || msg.includes('load failed');
      if (isTimeout || isNetwork) {
        const cfg = error.config || {};
        const reqUrl = String(cfg.url || '');
        const base = String(cfg.baseURL || process.env.VUE_APP_BASE_URL || '');
        const isStrategyLight =
          reqUrl.includes('live-publish') ||
          reqUrl.includes('live-unpublish') ||
          reqUrl.includes('/publish') && reqUrl.includes('strategy-models');
        const tip = isTimeout
          ? (isStrategyLight
            ? `请求超时。实盘/发布类接口通常几秒内完成，若持续超时请检查：① portfilio-end 是否已启动 ② 前端环境变量 VUE_APP_BASE_URL 是否指向正确 API（当前 ${base || '(默认 127.0.0.1:8000)'}）③ MongoDB 是否可连`
            : '请求超时，请检查后端是否已启动、网络是否正常；若为大量数据可缩小日期范围或使用「同步行情」')
          : '连接失败，请检查：① 后端服务是否已启动 ② 网络是否正常';
        Message.error({
          message: tip,
          duration: 6000,
          showClose: true
        });
      } else {
        Message.error('网络错误，请检查网络连接');
      }
    } else {
      Message.error('请求配置错误');
    }

    return Promise.reject(error);
  }
);

export default service;
