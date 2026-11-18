import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { setSessionLostHandler } from './auth'
import { installErrorReporter } from './errorReporter'
import './style.css'

installErrorReporter()

setSessionLostHandler(() => {
  if (router.currentRoute.value.path !== '/login') {
    router.replace('/login')
  }
})

createApp(App).use(router).mount('#app')
