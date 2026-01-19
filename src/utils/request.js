import axios from 'axios';
import store from '@/store';
import { Message } from 'element-ui';

// 创建axios实例
const service = axios.create({
  baseURL: 'http://127.0.0.1:8000',
  timeout: 15000
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
        case 403:
          Message.error('拒绝访问');
          break;
        case 404:
          Message.error('请求的资源不存在');
          break;
        // 500和其他业务错误不在这里显示，由组件级catch处理
        // 这样可以提供更友好的上下文相关错误提示
      }
    } else if (error.request) {
      Message.error('网络错误，请检查网络连接');
    } else {
      Message.error('请求配置错误');
    }
    
    return Promise.reject(error);
  }
);

export default service;
