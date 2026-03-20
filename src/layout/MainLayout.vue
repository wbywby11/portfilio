<template>
  <div class="main-layout">
    <el-container>
      <!-- 侧边栏 -->
      <el-aside :width="collapsed ? '64px' : '200px'" class="sidebar">
        <div class="logo">
          <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 24 24'%3E%3Cpath fill='%23409EFF' d='M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z'/%3E%3C/svg%3E" alt="logo" v-if="!collapsed">
          <span v-if="!collapsed" class="logo-text">智能投研系统</span>
        </div>
        
        <el-menu
          :default-active="activeMenu"
          :default-openeds="defaultOpeneds"
          :collapse="collapsed"
          background-color="#304156"
          text-color="#bfcbd9"
          active-text-color="#409EFF"
          :unique-opened="true"
          router
        >
          <el-menu-item index="/dashboard">
            <i class="el-icon-s-home"></i>
            <span slot="title">工作台</span>
          </el-menu-item>

          <el-submenu index="asset">
            <template slot="title">
              <i class="el-icon-coin"></i>
              <span>资产库管理</span>
            </template>
            <el-menu-item index="/asset/list">资产列表</el-menu-item>
            <el-menu-item index="/asset/add">新增资产</el-menu-item>
            <el-menu-item index="/asset/quote">资产行情</el-menu-item>
          </el-submenu>

          <el-submenu index="strategy">
            <template slot="title">
              <i class="el-icon-data-analysis"></i>
              <span>策略管理</span>
            </template>
            <el-menu-item index="/strategy/template">算法模板库</el-menu-item>
            <el-menu-item index="/strategy/model">我的策略</el-menu-item>
            <el-menu-item index="/strategy/backtest">回测执行</el-menu-item>
            <el-menu-item index="/strategy/benchmark">业绩基准管理</el-menu-item>
          </el-submenu>

          <el-submenu index="portfolio">
            <template slot="title">
              <i class="el-icon-s-data"></i>
              <span>模拟组合</span>
            </template>
            <el-menu-item index="/portfolio/list">组合列表</el-menu-item>
            <el-menu-item index="/portfolio/create">创建组合</el-menu-item>
            <el-menu-item index="/portfolio/compare">多组合对比</el-menu-item>
          </el-submenu>

          <el-submenu index="analysis">
            <template slot="title">
              <i class="el-icon-data-line"></i>
              <span>数据分析</span>
            </template>
            <el-menu-item index="/analysis">资产分析</el-menu-item>
            <el-menu-item index="/analysis/asset-index">大类资产指数</el-menu-item>
            <el-menu-item index="/analysis/monitor">日常监控</el-menu-item>
            <el-menu-item index="/analysis/weight-import">权重与持仓估值导入</el-menu-item>
            <el-menu-item index="/analysis/fx-import">汇率数据导入</el-menu-item>
            <el-menu-item index="/analysis/multi-asset-import">多资产行情导入</el-menu-item>
          </el-submenu>

          <el-submenu index="system" v-if="isAdmin">
            <template slot="title">
              <i class="el-icon-setting"></i>
              <span>系统管理</span>
            </template>
            <el-menu-item index="/system/user">用户管理</el-menu-item>
            <el-menu-item index="/system/role">角色管理</el-menu-item>
            <el-menu-item index="/system/log">操作日志</el-menu-item>
          </el-submenu>
        </el-menu>
      </el-aside>

      <el-container>
        <!-- 顶部导航栏 -->
        <el-header class="header">
          <div class="header-left">
            <i 
              :class="collapsed ? 'el-icon-s-unfold' : 'el-icon-s-fold'" 
              class="collapse-icon"
              @click="toggleCollapse"
            ></i>
            <el-breadcrumb separator="/" class="breadcrumb">
              <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
              <el-breadcrumb-item v-for="item in breadcrumbs" :key="item.path">
                {{ item.meta.title }}
              </el-breadcrumb-item>
            </el-breadcrumb>
          </div>
          
          <div class="header-right">
            <el-dropdown @command="handleCommand">
              <span class="user-info">
                <el-avatar :size="32" icon="el-icon-user-solid"></el-avatar>
                <span class="user-name">{{ userName }}</span>
                <i class="el-icon-arrow-down"></i>
              </span>
              <el-dropdown-menu slot="dropdown">
                <el-dropdown-item disabled>{{ userRole }}</el-dropdown-item>
                <el-dropdown-item divided command="profile">个人中心</el-dropdown-item>
                <el-dropdown-item command="password">修改密码</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </el-dropdown>
          </div>
        </el-header>

        <!-- 主内容区 -->
        <el-main class="main-content">
          <transition name="fade-transform" mode="out-in">
            <router-view :key="$route.fullPath" />
          </transition>
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script>
import { mapState, mapGetters, mapActions } from 'vuex';

export default {
  name: 'MainLayout',
  data() {
    return {
      activeMenu: '/dashboard'
    };
  },
  computed: {
    ...mapState(['collapsed']),
    defaultOpeneds() {
      const p = this.$route.path;
      if (p.startsWith('/asset')) return ['asset'];
      if (p.startsWith('/strategy')) return ['strategy'];
      if (p.startsWith('/portfolio')) return ['portfolio'];
      if (p.startsWith('/analysis')) return ['analysis'];
      if (p.startsWith('/system')) return ['system'];
      return [];
    },
    ...mapGetters('user', ['userName', 'userRole']),
    isAdmin() {
      return this.$store.state.user.userInfo.role === 'admin';
    },
    breadcrumbs() {
      return this.$route.matched.filter(item => item.meta && item.meta.title);
    }
  },
  watch: {
    $route: {
      handler(route) {
        this.activeMenu = route.path;
      },
      immediate: true
    }
  },
  methods: {
    ...mapActions(['toggleCollapsed']),
    toggleCollapse() {
      this.toggleCollapsed();
    },
    handleCommand(command) {
      switch (command) {
        case 'logout':
          this.logout();
          break;
        case 'profile':
          this.$message.info('个人中心功能开发中');
          break;
        case 'password':
          this.$message.info('修改密码功能开发中');
          break;
      }
    },
    logout() {
      this.$confirm('确定要退出登录吗?', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(() => {
        this.$store.dispatch('user/logout');
        this.$router.push('/login');
        this.$message.success('已退出登录');
      }).catch(() => {});
    }
  }
};
</script>

<style scoped>
.main-layout {
  width: 100%;
  height: 100%;
}

.el-container {
  height: 100%;
}

/* 侧边栏 */
.sidebar {
  background-color: #304156;
  transition: width 0.3s;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #2b3a4a;
  color: #fff;
}

.logo img {
  width: 32px;
  height: 32px;
  margin-right: 8px;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
}

.el-menu {
  border-right: none;
}

/* 顶部导航栏 */
.header {
  background-color: #fff;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px;
}

.header-left {
  display: flex;
  align-items: center;
}

.collapse-icon {
  font-size: 20px;
  cursor: pointer;
  margin-right: 20px;
  transition: color 0.3s;
}

.collapse-icon:hover {
  color: #409EFF;
}

.breadcrumb {
  line-height: 60px;
}

.header-right {
  display: flex;
  align-items: center;
}

.user-info {
  display: flex;
  align-items: center;
  cursor: pointer;
  padding: 0 10px;
}

.user-name {
  margin: 0 8px;
  font-size: 14px;
}

/* 主内容区 */
.main-content {
  background-color: #f0f2f5;
  padding: 20px;
  overflow-y: auto;
}

/* 页面切换动画 */
.fade-transform-leave-active,
.fade-transform-enter-active {
  transition: all 0.3s;
}

.fade-transform-enter {
  opacity: 0;
  transform: translateX(-30px);
}

.fade-transform-leave-to {
  opacity: 0;
  transform: translateX(30px);
}
</style>
