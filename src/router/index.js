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
    redirect: '/dashboard',
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
        redirect: '/asset/list',
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
            meta: { title: '模型模板库' }
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
            path: 'benchmark',
            name: 'BenchmarkList',
            component: () => import('@/views/strategy/BenchmarkList.vue'),
            meta: { title: '业绩基准管理' }
          },
          {
            path: 'backtest',
            name: 'BacktestExecution',
            component: () => import('@/views/strategy/BacktestExecution.vue'),
            meta: { title: '回测执行' }
          }
        ]
      },
      // 模拟组合模块
      {
        path: 'portfolio',
        name: 'Portfolio',
        component: () => import('@/views/portfolio/Index.vue'),
        meta: { title: '模拟组合', icon: 'el-icon-s-data' },
        children: [
          {
            path: 'list',
            name: 'PortfolioList',
            component: () => import('@/views/portfolio/PortfolioList.vue'),
            meta: { title: '组合列表' }
          },
          {
            path: 'create',
            name: 'PortfolioCreate',
            component: () => import('@/views/portfolio/PortfolioCreate.vue'),
            meta: { title: '创建组合' }
          },
          {
            path: 'detail/:id',
            name: 'PortfolioDetail',
            component: () => import('@/views/portfolio/PortfolioDetail.vue'),
            meta: { title: '组合详情' }
          },
          {
            path: 'rebalance/:id',
            name: 'PortfolioRebalance',
            component: () => import('@/views/portfolio/Rebalance.vue'),
            meta: { title: '再平衡设置' }
          },
          {
            path: 'history/:id',
            name: 'PortfolioHistory',
            component: () => import('@/views/portfolio/TradeHistory.vue'),
            meta: { title: '调仓历史' }
          },
          {
            path: 'performance/:id',
            name: 'PortfolioPerformance',
            component: () => import('@/views/portfolio/Performance.vue'),
            meta: { title: '业绩分析' }
          },
          {
            path: 'benchmark/:id',
            name: 'PortfolioBenchmark',
            component: () => import('@/views/portfolio/Benchmark.vue'),
            meta: { title: '基准对比' }
          },
          {
            path: 'compare',
            name: 'PortfolioCompare',
            component: () => import('@/views/portfolio/Compare.vue'),
            meta: { title: '多组合对比' }
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
        redirect: '/agent/chat'
      },
      {
        path: 'analysis/memories',
        redirect: '/agent/memories'
      },
      {
        path: 'analysis/asset-index',
        name: 'AssetIndex',
        component: () => import('@/views/analysis/AssetIndex.vue'),
        meta: { title: '大类资产指数', icon: 'el-icon-data-line' }
      },
      {
        path: 'analysis/weight-import',
        name: 'WeightValuationImport',
        component: () => import('@/views/analysis/WeightValuationImport.vue'),
        meta: { title: '权重与持仓估值导入', icon: 'el-icon-upload2' }
      },
      {
        path: 'analysis/fx-import',
        name: 'FxImport',
        component: () => import('@/views/analysis/FxImport.vue'),
        meta: { title: '汇率与日历管理', icon: 'el-icon-upload2' }
      },
      {
        path: 'analysis/multi-asset-import',
        name: 'MultiAssetImport',
        component: () => import('@/views/analysis/MultiAssetImport.vue'),
        meta: { title: '多资产行情导入', icon: 'el-icon-upload2' }
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
        path: 'analysis/zy-data-domain',
        name: 'ZyDataDomain',
        component: () => import('@/views/analysis/ZyDataDomain/Index.vue'),
        meta: { title: 'ZY数据域管理', icon: 'el-icon-coin' }
      },
      {
        path: 'analysis/data-lineage',
        name: 'DataLineage',
        component: () => import('@/views/analysis/DataLineage/Index.vue'),
        meta: { title: '数据血缘图谱', icon: 'el-icon-connection' }
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
    redirect: '/agent/chat',
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
        path: 'history',
        name: 'AgentHistory',
        component: () => import('@/views/agent/ConversationHistory.vue'),
        meta: { title: '对话历史', icon: 'el-icon-time' }
      },
      {
        path: 'memories',
        name: 'MemoryManager',
        component: () => import('@/views/agent/MemoryManager.vue'),
        meta: { title: '知识记忆', icon: 'el-icon-notebook-2' }
      },
      {
        path: 'reports',
        name: 'ReportCenter',
        component: () => import('@/views/agent/ReportCenter.vue'),
        meta: { title: '报告中心', icon: 'el-icon-document' }
      },
      {
        path: 'templates',
        name: 'AnalysisTemplates',
        component: () => import('@/views/agent/AnalysisTemplates.vue'),
        meta: { title: '分析模板' }
      },
      {
        path: 'data-templates',
        name: 'DataTemplates',
        component: () => import('@/views/agent/DataTemplates.vue'),
        meta: { title: '数据模板', icon: 'el-icon-data-analysis' }
      },
      {
        path: 'scenes',
        name: 'AgentScenes',
        component: () => import('@/views/agent/SceneManager.vue'),
        meta: { title: '场景管理', icon: 'el-icon-setting', roles: ['admin'] }
      }
    ]
  },
  {
    path: '*',
    redirect: '/404'
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
    next('/login');
  } else if (to.path === '/login' && token) {
    next('/');
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
