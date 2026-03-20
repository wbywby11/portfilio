# Node.js 版本要求

## 问题说明

如果遇到 `cannot find module node:url` 错误，这是因为项目依赖的某些包（如 `@babel/core`）使用了 Node.js 的 `node:` 前缀语法。

## 解决方案

### 方案1：升级 Node.js 版本（推荐）

`node:` 前缀语法需要 Node.js >= 14.18.0 或 >= 16.0.0。

**推荐使用 Node.js 16.x 或更高版本：**

1. **使用 nvm（Node Version Manager）**：
   ```bash
   # 安装 nvm（如果还没有）
   # Windows: https://github.com/coreybutler/nvm-windows
   # Mac/Linux: https://github.com/nvm-sh/nvm
   
   # 安装 Node.js 16
   nvm install 16.20.0
   nvm use 16.20.0
   ```

2. **直接下载安装**：
   - 访问 https://nodejs.org/
   - 下载并安装 Node.js 16.x LTS 或更高版本

3. **验证版本**：
   ```bash
   node -v  # 应该显示 v16.x.x 或更高
   npm -v   # 应该显示 7.x.x 或更高
   ```

### 方案2：降级依赖版本（不推荐）

如果无法升级 Node.js，可以尝试降级 `@babel/core` 到较旧版本，但可能带来其他兼容性问题：

```bash
npm install --save-dev @babel/core@^7.20.0 @babel/preset-env@^7.20.0
```

### 方案3：使用 polyfill（复杂，不推荐）

可以配置 webpack 或 babel 来处理 `node:` 前缀，但配置复杂且可能不稳定。

## 检查当前 Node.js 版本

```bash
node -v
```

如果版本低于 16.0.0，请按照方案1升级。

## 重新安装依赖

升级 Node.js 后，建议重新安装依赖：

```bash
# 删除 node_modules 和 package-lock.json
rm -rf node_modules package-lock.json

# 重新安装
npm install
```

## 项目配置

项目已配置：
- `package.json` 中的 `engines` 字段指定了 Node.js 版本要求
- `.nvmrc` 文件指定了推荐的 Node.js 版本（如果使用 nvm）
