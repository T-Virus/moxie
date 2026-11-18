import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { installErrorReporter } from './services/errorReporter'
import './styles/tokens.css'
import './styles/base.css'

installErrorReporter()

// PWA：仅生产注册 SW（开发期注册会缓存 HMR 资源导致调试陈旧）；失败静默不影响启动。
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}

createApp(App).use(router).mount('#app')
