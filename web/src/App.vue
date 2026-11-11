<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import Toast from './components/Toast.vue'
import SettingsModal from './components/SettingsModal.vue'
import Confirm from './components/Confirm.vue'
import PasswordPrompt from './components/PasswordPrompt.vue'
import FilePreview from './components/FilePreview.vue'
import TaskFloater from './components/TaskFloater.vue'
import MobileApp from './mobile/MobileApp.vue'
import { isMobileView } from './mobile/detect'
import { store } from './store'
import { ui } from './ui'

const route = useRoute()
const router = useRouter()
/* 任意路由切换后立刻同步一次全局数据，避免「返回上一页数据不是最新」 */
router.afterEach(() => { store.loadStats().catch(() => {}) })

/* 安卓端（WebView / 手机宽度）走独立的全新界面；桌面端保持原布局。
   同时识别 Native 桥，覆盖平板横屏等宽度较大的安卓设备。 */
const mq = typeof window !== 'undefined' ? window.matchMedia('(max-width: 760px)') : null
const forceMobile = typeof window !== 'undefined'
  ? new URLSearchParams(window.location.search).get('mobile') : null
const isMobile = ref(isMobileView())
function syncMobile(e?: MediaQueryListEvent) {
  if (forceMobile === '1') { isMobile.value = true; return }
  if (forceMobile === '0') { isMobile.value = false; return }
  isMobile.value = !!(e ? e.matches : mq?.matches) || !!(window as any).Native
}

/* 移动端抽屉：页面切换后收起；同时把内容区滚回顶部 */
const viewEl = ref<HTMLElement | null>(null)
watch(() => route.path, () => {
  ui.menuOpen = false
  if (!isMobile.value) nextTick(() => { if (viewEl.value) viewEl.value.scrollTop = 0 })
})
/* 同一页面内换书也要回顶 */
watch(() => store.curBook(), () => {
  if (!isMobile.value) nextTick(() => { if (viewEl.value) viewEl.value.scrollTop = 0 })
})
function onKeydown(e: KeyboardEvent) { if (e.key === 'Escape' && ui.menuOpen) ui.menuOpen = false }
/* 桌面窗口跨过手机断点时重载一次：路由组件在进入时已按屏幕选中，重载保证外壳与页面一致 */
watch(isMobile, () => { window.location.reload() })

let timer: any = null
onMounted(async () => {
  syncMobile()
  mq?.addEventListener?.('change', syncMobile)
  await store.loadStats().catch(() => {})
  store.loadStudio().catch(() => {})
  timer = setInterval(() => { store.loadStats().catch(() => {}) }, 5000)
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  clearInterval(timer)
  mq?.removeEventListener?.('change', syncMobile)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <MobileApp v-if="isMobile" />
  <div v-else class="app" :class="{ 'menu-open': ui.menuOpen }">
    <Sidebar />
    <div class="sb-mask" @click="ui.menuOpen = false"></div>
    <div class="main">
      <TopBar />
      <main class="view" ref="viewEl"><RouterView /></main>
    </div>
    <Toast />
    <SettingsModal />
    <Confirm />
    <PasswordPrompt />
    <FilePreview />
    <TaskFloater />
  </div>
</template>
