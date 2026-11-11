/// <reference types="vite/client" />

declare interface Window {
  /* 服务端注入的会话令牌（打包形态下写请求必须带回） */
  __mwToken?: string
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
