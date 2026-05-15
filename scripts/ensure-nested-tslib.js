/**
 * echarts/zrender 会解析到各自的 node_modules/tslib/tslib.es6.js。
 * 嵌套目录缺失或 junction 失效时 Webpack 报 ENOENT。每次 postinstall
 * 从根目录 node_modules/tslib 递归复制一份到上述路径（比 junction 更稳）。
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const rootTslib = path.resolve(root, 'node_modules', 'tslib');
const marker = path.join(rootTslib, 'tslib.es6.js');

if (!fs.existsSync(marker)) {
  console.warn('[ensure-nested-tslib] 根目录未安装 tslib，跳过');
  process.exit(0);
}

for (const pkg of ['echarts', 'zrender']) {
  const base = path.join(root, 'node_modules', pkg, 'node_modules');
  const dest = path.join(base, 'tslib');
  fs.mkdirSync(base, { recursive: true });
  fs.rmSync(dest, { recursive: true, force: true });
  fs.cpSync(rootTslib, dest, { recursive: true, dereference: true });
  console.log('[ensure-nested-tslib] synced tslib ->', path.relative(root, dest));
}
