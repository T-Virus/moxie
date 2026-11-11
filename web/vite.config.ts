import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import JavaScriptObfuscator from 'javascript-obfuscator'
import { fileURLToPath, URL } from 'node:url'

// 自研代码混淆：只处理业务 chunk，第三方库（vendor）保持原样——
// 库代码本来公开，混淆它们只会拖慢构建、放大体积，还容易引入难查的运行问题。
const OBFUSCATOR_OPTIONS: any = {
  compact: true,
  target: 'browser',
  identifierNamesGenerator: 'hexadecimal',
  renameGlobals: false,
  controlFlowFlattening: true,
  controlFlowFlatteningThreshold: 0.35,
  deadCodeInjection: false,
  debugProtection: false,
  disableConsoleOutput: false,
  numbersToExpressions: true,
  simplify: true,
  splitStrings: true,
  splitStringsChunkLength: 10,
  stringArray: true,
  stringArrayCallsTransform: true,
  stringArrayEncoding: ['base64'],
  stringArrayIndexShift: true,
  stringArrayRotate: true,
  stringArrayShuffle: true,
  stringArrayWrappersCount: 2,
  stringArrayWrappersType: 'function',
  stringArrayThreshold: 0.75,
  transformObjectKeys: false,
  unicodeEscapeSequence: false,
}

function hardenBundle(): Plugin {
  return {
    name: 'mw-harden-bundle',
    apply: 'build',
    enforce: 'post',
    generateBundle(_options, bundle) {
      for (const item of Object.values(bundle)) {
        if (item.type !== 'chunk' || item.name === 'vendor') continue
        item.code = JavaScriptObfuscator
          .obfuscate(item.code, OBFUSCATOR_OPTIONS)
          .getObfuscatedCode()
        item.map = null
      }
    },
  }
}

// 开发期把 /api 与 /static 代理到本机 Python 控制台（src/webapp.py，端口 8765）。
// 打包后由 Python 直接托管 dist/，无需代理。
export default defineConfig({
  plugins: [vue(), hardenBundle()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/static': 'http://127.0.0.1:8765',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // 生产包不出 sourcemap：否则还原源码比反编译还省事
    sourcemap: false,
    // 不拆路由级 CSS：混淆后的按需加载逻辑一旦出岔子，页面会静默丢样式。
    // 本地应用一次性加载全部样式（约 200KB）没有任何压力，换取确定性。
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        manualChunks: (id) => (id.includes('node_modules') ? 'vendor' : undefined),
      },
    },
  },
  esbuild: {
    drop: ['debugger'],
  },
})
