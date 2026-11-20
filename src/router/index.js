import Vue from 'vue';
import VueRouter from 'vue-router';
import store from '@/store';

Vue.use(VueRouter);

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', requiresAuth: false }
  },
  {
    path: '/',
    component: () => import('@/layout/MainLayout.vue'),
    redirect: { name: 'Dashboard' },
    meta: { requiresAuth: true },
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '工作台', icon: 'el-icon-s-home' }
      },
      // 大类资产配置模块
      {
        path: 'asset',
        name: 'Asset',
        redirect: { name: 'AssetList' },
        component: () => import('@/views/asset/Index.vue'),
        meta: { title: '资产库管理', icon: 'el-icon-coin' },
        children: [
          {
            path: 'list',
            name: 'AssetList',
            component: () => import('@/views/asset/AssetList.vue'),
            meta: { title: '资产列表' }
          },
          {
            path: 'add',
            name: 'AssetAdd',
            component: () => import('@/views/asset/AssetForm.vue'),
            meta: { title: '新增资产' }
          },
          {
            path: 'edit/:id',
            name: 'AssetEdit',
            component: () => import('@/views/asset/AssetForm.vue'),
            meta: { title: '编辑资产' }
          },
          {
            path: 'quote',
            name: 'AssetQuote',
            component: () => import('@/views/asset/AssetQuote.vue'),
            meta: { title: '资产行情' }
          }
        ]
      },
      // 策略模块
      {
        path: 'strategy',
        name: 'Strategy',
        component: () => import('@/views/strategy/Index.vue'),
        meta: { title: '策略管理', icon: 'el-icon-data-analysis' },
        children: [
          {
            path: 'template',
            name: 'StrategyTemplate',
            component: () => import('@/views/strategy/TemplateList.vue'),
            meta: { title: '策略库' }
          },
          {
            path: 'template/add',
            name: 'TemplateAdd',
            component: () => import('@/views/strategy/TemplateForm.vue'),
            meta: { title: '新增模板', hidden: true }
          },
          {
            path: 'template/edit/:id',
            name: 'TemplateEdit',
            component: () => import('@/views/strategy/TemplateForm.vue'),
            meta: { title: '编辑模板', hidden: true }
          },
          {
            path: 'model',
            name: 'StrategyModelList',
            component: () => import('@/views/strategy/StrategyModelList.vue'),
            meta: { title: '策略模型' }
          },
          {
            path: 'model/add',
            name: 'StrategyModelAdd',
            component: () => import('@/views/strategy/StrategyModelForm.vue'),
            meta: { title: '创建策略', hidden: true }
          },
          {
            path: 'model/edit/:id',
            name: 'StrategyModelEdit',
            component: () => import('@/views/strategy/StrategyModelForm.vue'),
            meta: { title: '编辑策略', hidden: true }
          },
          {
            path: 'model/detail/:id',
            name: 'StrategyModelDetail',
            component: () => import('@/views/strategy/StrategyModelDetail.vue'),
            meta: { title: '策略详情', hidden: true }
          },
          {
            path: 'backtest',
            name: 'BacktestExecution',
            component: () => import('@/views/strategy/BacktestExecution.vue'),
            meta: { title: '回测执行' }
          },
          // 组合管理（二级功能）
          {
            path: 'portfolio',
            name: 'PortfolioList',
            component: () => import('@/views/portfolio/PortfolioList.vue'),
            meta: { title: '组合管理' }
          },
          {
            path: 'portfolio/create',
            name: 'PortfolioCreate',
            component: () => import('@/views/portfolio/PortfolioCreate.vue'),
            meta: { title: '创建组合', hidden: true }
          },
          {
            path: 'portfolio/edit/:id',
            name: 'PortfolioEdit',
            component: () => import('@/views/portfolio/PortfolioCreate.vue'),
            meta: { title: '编辑组合', hidden: true }
          },
          {
            path: 'portfolio/detail/:id',
            name: 'PortfolioDetail',
            component: () => import('@/views/portfolio/PortfolioDetail.vue'),
            meta: { title: '组合详情', hidden: true }
          },
          {
            path: 'portfolio/sim-trade',
            name: 'SimTradeSelector',
            component: () => import('@/views/portfolio/SimTradeSelector.vue'),
            meta: { title: '模拟交易', hidden: true }
          },
          {
            path: 'portfolio/sim-trade/:id',
            name: 'SimTradeDashboard',
            component: () => import('@/views/portfolio/SimTradeDashboard.vue'),
            meta: { title: '模拟交易', hidden: true }
          }
        ]
      },
      // 数据分析模块
      {
        path: 'analysis',
        name: 'Analysis',
        component: () => import('@/views/analysis/AssetAnalysis.vue'),
        meta: { title: '资产分析', icon: 'el-icon-data-analysis' }
      },
      {
        path: 'analysis/agent',
        redirect: { name: 'AgentWorkspace' }
      },
      {
        path: 'analysis/fx-import',
        name: 'FxImport',
        component: () => import('@/views/analysis/FxImport.vue'),
        meta: { title: '汇率与日历管理', icon: 'el-icon-upload2' }
      },
      {
        path: 'analysis/data-hub',
        name: 'DataHubCenter',
        component: () => import('@/views/analysis/DataHub/Index.vue'),
        meta: { title: '数据接入中心', icon: 'el-icon-connection' }
      },
      {
        path: 'analysis/data-assets',
        name: 'DataAssets',
        component: () => import('@/views/analysis/DataAsset/Index.vue'),
        meta: { title: '数据资产管理', icon: 'el-icon-folder-opened' }
      },
      {
        path: 'analysis/factor-panel',
        name: 'FactorPanelImport',
        component: () => import('@/views/analysis/FactorPanelImport.vue'),
        meta: { title: '因子截面数据', icon: 'el-icon-s-grid' }
      },
      {
        path: 'analysis/macro-series',
        name: 'MacroSeriesImport',
        component: () => import('@/views/analysis/MacroImport.vue'),
        meta: { title: '宏观与估值序列', icon: 'el-icon-odometer' }
      },
      {
        path: 'analysis/subject-risk',
        redirect: { name: 'DataHubCenter', query: { connector: 'subject_opinion_risk' } }
      },
      {
        path: 'analysis/monitor',
        name: 'MonitorCenter',
        component: () => import('@/views/monitor/MonitorCenter.vue'),
        meta: { title: '日常监控', icon: 'el-icon-monitor' }
      },
      // 收益凭证估值模块
      {
        path: 'options',
        name: 'Options',
        component: () => import('@/views/options/Index.vue'),
        redirect: { name: 'ValuationWorkbench' },
        meta: { title: '收益凭证估值', icon: 'el-icon-trophy' },
        children: [
          {
            path: 'workbench',
            name: 'ValuationWorkbench',
            component: () => import('@/views/options/ValuationWorkbench.vue'),
            meta: { title: '估值工作台' }
          },
          {
            path: 'history',
            name: 'ValuationHistory',
            component: () => import('@/views/options/ValuationHistory.vue'),
            meta: { title: '估值历史' }
          },
          {
            path: 'accounting',
            name: 'AccountingAssist',
            component: () => import('@/views/options/AccountingAssist.vue'),
            meta: { title: '核算辅助' }
          },
          {
            path: 'products',
            name: 'OptionsProducts',
            component: () => import('@/views/options/OptionsProductList.vue'),
            meta: { title: '产品管理' }
          },
          {
            path: 'valuation-data',
            name: 'ValuationDataManage',
            component: () => import('@/views/options/ValuationDataManage.vue'),
            meta: { title: '估值数据' }
          }
        ]
      },
      // 系统管理
      {
        path: 'system',
        name: 'System',
        component: () => import('@/views/system/Index.vue'),
        meta: { title: '系统管理', icon: 'el-icon-setting', roles: ['admin'] },
        children: [
          {
            path: 'user',
            name: 'UserManage',
            component: () => import('@/views/system/UserManage.vue'),
            meta: { title: '用户管理', roles: ['admin'] }
          },
          {
            path: 'role',
            name: 'RoleManage',
            component: () => import('@/views/system/RoleManage.vue'),
            meta: { title: '角色管理', roles: ['admin'] }
          },
          {
            path: 'log',
            name: 'SystemLog',
            component: () => import('@/views/system/SystemLog.vue'),
            meta: { title: '操作日志', roles: ['admin'] }
          }
        ]
      }
    ]
  },
  // 数智平台AI助手 — 顶级路由组
  {
    path: '/agent',
    component: () => import('@/layout/MainLayout.vue'),
    meta: { title: '数智平台AI助手', icon: 'el-icon-s-opportunity', requiresAuth: true },
    redirect: { name: 'AgentWorkspace' },
    children: [
      {
        path: 'chat',
        name: 'AgentWorkspace',
        component: () => import('@/views/agent/AgentWorkspace.vue'),
        meta: { title: '智能对话', icon: 'el-icon-chat-dot-round' }
      },
      {
        path: 'chat/:scene',
        name: 'AgentSceneChat',
        component: () => import('@/views/agent/AgentWorkspace.vue'),
        meta: { title: '场景对话', hidden: true },
        props: true
      },
      {
        path: 'knowledge',
        name: 'KnowledgeBase',
        component: () => import('@/views/agent/KnowledgeBase.vue'),
        meta: { title: '知识库', icon: 'el-icon-reading' }
      }
    ]
  },
  {
    path: '*',
    redirect: { name: 'NotFound' }
  },
  {
    path: '/404',
    name: 'NotFound',
    component: () => import('@/views/404.vue'),
    meta: { title: '页面未找到' }
  }
];

const router = new VueRouter({
  mode: 'hash',
  routes
});

// 路由守卫
router.beforeEach((to, from, next) => {
  document.title = to.meta.title ? `${to.meta.title} - 智能投研系统` : '智能投研系统';
  
  const requiresAuth = to.matched.some(record => record.meta.requiresAuth !== false);
  const token = store.state.user.token;
  
  if (requiresAuth && !token) {
    next({ name: 'Login' });
  } else if (to.path === '/login' && token) {
    next({ name: 'Dashboard' });
  } else {
    // 检查角色权限
    if (to.meta.roles) {
      const userRole = store.state.user.userInfo.role;
      if (to.meta.roles.includes(userRole)) {
        next();
      } else {
        next('/403');
      }
    } else {
      next();
    }
  }
});

export default router;
