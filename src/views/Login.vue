<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-header">
        <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 24 24'%3E%3Cpath fill='%23409EFF' d='M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z'/%3E%3C/svg%3E" alt="logo">
        <h1>智能投研系统</h1>
        <p>Investment Research System</p>
      </div>
      
      <el-form :model="loginForm" :rules="rules" ref="loginForm" class="login-form">
        <el-form-item prop="username">
          <el-input
            v-model="loginForm.username"
            placeholder="请输入用户名"
            prefix-icon="el-icon-user"
            @keyup.enter.native="handleLogin"
          ></el-input>
        </el-form-item>
        
        <el-form-item prop="password">
          <el-input
            v-model="loginForm.password"
            type="password"
            placeholder="请输入密码"
            prefix-icon="el-icon-lock"
            @keyup.enter.native="handleLogin"
            show-password
          ></el-input>
        </el-form-item>
        
        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            @click="handleLogin"
            class="login-button"
          >
            {{ loading ? '登录中...' : '登 录' }}
          </el-button>
        </el-form-item>
      </el-form>
      
      <div class="login-tip">
        <el-divider>测试账号</el-divider>
        <div class="tip-content">
          <p><strong>系统管理员：</strong>admin / admin</p>
          <p><strong>投资经理：</strong>manager / manager</p>
          <p><strong>研究员：</strong>researcher / researcher</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Login',
  data() {
    return {
      loginForm: {
        username: 'admin',
        password: 'admin'
      },
      rules: {
        username: [
          { required: true, message: '请输入用户名', trigger: 'blur' }
        ],
        password: [
          { required: true, message: '请输入密码', trigger: 'blur' },
          { min: 3, message: '密码长度不能少于3位', trigger: 'blur' }
        ]
      },
      loading: false
    };
  },
  methods: {
    handleLogin() {
      this.$refs.loginForm.validate(async (valid) => {
        if (valid) {
          this.loading = true;
          try {
            const result = await this.$store.dispatch('user/login', this.loginForm);
            if (result.success) {
              this.$message.success('登录成功');
              this.$router.push({ name: 'Dashboard' });
            } else {
              this.$message.error(result.message || '登录失败');
            }
          } catch (error) {
            this.$message.error('登录失败：' + error.message);
          } finally {
            this.loading = false;
          }
        }
      });
    }
  }
};
</script>

<style scoped>
.login-container {
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  justify-content: center;
  align-items: center;
}

.login-box {
  width: 400px;
  padding: 40px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
}

.login-header {
  text-align: center;
  margin-bottom: 30px;
}

.login-header img {
  width: 48px;
  height: 48px;
  margin-bottom: 10px;
}

.login-header h1 {
  font-size: 24px;
  color: #303133;
  margin-bottom: 5px;
}

.login-header p {
  font-size: 14px;
  color: #909399;
}

.login-form {
  margin-top: 30px;
}

.login-button {
  width: 100%;
  height: 42px;
  font-size: 16px;
}

.login-tip {
  margin-top: 20px;
}

.tip-content {
  font-size: 12px;
  color: #909399;
  line-height: 1.8;
}

.tip-content p {
  margin: 5px 0;
}
</style>
