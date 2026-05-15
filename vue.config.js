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
}
