const path = require('path')

const tslibRoot = path.resolve(__dirname, 'node_modules/tslib')

module.exports = {
  chainWebpack(config) {
    config.resolve.alias.set('tslib', tslibRoot)
  },
  configureWebpack: {
    resolve: {
      alias: {
        tslib: tslibRoot,
      },
    },
  },
  devServer: {
    client: {
      overlay: {
        runtimeErrors: (error) => {
          // 屏蔽 ResizeObserver 误报（vxe-table 展开行时的正常浏览器通知）
          if (error.message && error.message.includes('ResizeObserver loop')) {
            return false
          }
          return true
        },
      },
    },
  },
}
