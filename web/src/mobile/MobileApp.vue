<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import Toast from '../components/Toast.vue'
import Confirm from '../components/Confirm.vue'
import PasswordPrompt from '../components/PasswordPrompt.vue'
import FilePreview from '../components/FilePreview.vue'
import TaskFloater from '../components/TaskFloater.vue'
import MobileDrawer from './MobileDrawer.vue'
import MobileTabbar from './MobileTabbar.vue'
import BookArt from './BookArt.vue'
import { state, store } from '../store'
import { ui } from '../ui'
import './mobile.css'

const route = useRoute()
const router = useRouter()

const viewEl = ref<HTMLElement | null>(null)
const scrolled = ref(false)
/* 阅读模式：进入某一章正文时隐藏顶栏与底栏，整屏沉浸阅读 */
const immersive = computed(() => route.path === '/manuscript' && !!route.query.ch)
const MOBILE_PAGES = new Set(['/overview', '/outline', '/characters', '/factions', '/items', '/chapters',
  '/manuscript', '/world-map', '/tasks', '/outputs', '/stats', '/settings', '/upload',
  '/cover-design', '/book-review'])
const legacy = computed(() => !MOBILE_PAGES.has(route.path))
/* 二级页：顶栏换成返回 + 标题，不显示底部导航。道具功法是底栏入口，不属于二级页 */
const secondary = computed(() => ['/tasks', '/outputs', '/stats', '/settings', '/upload',
  '/cover-design', '/book-review', '/world-map'].includes(route.path))
const meta = computed(() => state.books.find(b => b.name === store.curBook()) || null)
const bookScoped = computed(() => route.meta.bookScoped !== false)
const subTitle = computed(() => {
  if (!meta.value) return 'AI 小说工作台'
  if (route.path === '/overview') return '作品封面'
  return `${meta.value.status || '连载中'} · ${meta.value.n_chapters || 0} 章`
})

/* 右上角作品切换：点开下拉直接换书，替代原来「点一下跳详情」+ 右上任务入口的重复入口 */
const bookOpen = ref(false)
function pickBook(name: string) {
  bookOpen.value = false
  if (name && name !== store.curBook()) store.setBook(name)
}
function goOverview() { bookOpen.value = false; router.push('/overview') }
function goUpload() { bookOpen.value = false; router.push('/upload') }

function onScroll() { scrolled.value = (viewEl.value?.scrollTop || 0) > 4 }
function closeMenu() { ui.menuOpen = false }
function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/overview')
}
function onKeydown(e: KeyboardEvent) { if (e.key === 'Escape' && ui.menuOpen) closeMenu() }

watch(() => route.fullPath, () => {
  ui.menuOpen = false
  bookOpen.value = false
  nextTick(() => {
    if (viewEl.value) { viewEl.value.scrollTop = 0; onScroll() }
  })
})
watch(() => store.curBook(), () => {
  nextTick(() => { if (viewEl.value) viewEl.value.scrollTop = 0 })
})

onMounted(() => {
  document.body.classList.add('m-mode')
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.body.classList.remove('m-mode')
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="app m-app" :class="{ 'menu-open': ui.menuOpen, 'm-immersive': immersive }">
    <div class="m-mask" @click="closeMenu"></div>
    <MobileDrawer />

    <header v-if="!immersive" class="m-appbar" :class="{ scrolled }">
      <template v-if="secondary">
        <button class="m-icon-btn" title="返回" @click="goBack"><Icon name="left" :size="20" /></button>
        <div class="m-page-title">
          <b>{{ String(route.meta.title || '墨写') }}</b>
          <small>墨写 · AI 小说工作台</small>
        </div>
        <span class="m-appbar-spacer"></span>
      </template>

      <template v-else>
        <button class="m-icon-btn m-menu-btn" title="打开作品与导航" @click="ui.menuOpen = true">
          <Icon name="menu" :size="20" />
        </button>
        <span class="m-appbar-spacer"></span>

        <!-- 右上角作品切换：点开下拉直接换书 -->
        <div class="m-book-switch">
          <button class="m-book-chip" :class="{ 'no-book': !meta }" @click="bookOpen = !bookOpen">
            <BookArt v-if="meta" :name="meta.name" :title="meta.title" :author="meta.author"
                     :has-cover="meta.has_cover" size="xs" />
            <img v-else class="m-brand-mini" src="/icon.png" alt="墨写" />
            <span class="m-book-chip-txt">
              <b>{{ meta ? (meta.title || meta.name)
                : (bookScoped ? '墨写' : String(route.meta.title || '墨写')) }}</b>
              <small>{{ meta ? subTitle : 'AI 小说工作台' }}</small>
            </span>
            <Icon name="down" :size="12" class="m-book-chip-arrow" />
          </button>

          <div v-if="bookOpen" class="m-book-menu">
            <button v-if="meta" class="m-book-menu-item" @click="goOverview">
              <span class="m-book-menu-ico"><Icon name="book" :size="15" /></span>
              <span class="m-book-menu-txt"><b>作品详情</b><small>封面、简介与创作进度</small></span>
            </button>
            <div class="m-book-menu-head">切换作品（{{ state.books.length }}）</div>
            <button v-for="b in state.books" :key="b.name" class="m-book-menu-item"
                    @click="pickBook(b.name)">
              <BookArt :name="b.name" :title="b.title" :author="b.author" :has-cover="b.has_cover" size="xs" />
              <span class="m-book-menu-txt">
                <b>{{ b.title || b.name }}</b>
                <small>{{ b.status || '连载中' }} · {{ b.n_chapters || 0 }} 章</small>
              </span>
              <Icon v-if="b.name === store.curBook()" name="check" :size="14" class="m-book-menu-check" />
            </button>
            <p v-if="!state.books.length" class="m-book-menu-empty">还没有作品，先新建一部</p>
            <button class="m-book-menu-foot" @click="goUpload">
              <Icon name="plus" :size="14" /> 新建作品
            </button>
          </div>
        </div>
      </template>
    </header>
    <div v-if="bookOpen" class="m-book-mask" @click="bookOpen = false"></div>

    <main ref="viewEl" class="m-view" :class="{ 'is-immersive': immersive, 'm-legacy': legacy }" @scroll.passive="onScroll">
      <RouterView v-slot="{ Component }">
        <Transition name="m-page" mode="out-in">
          <component :is="Component" :key="route.path" />
        </Transition>
      </RouterView>
    </main>

    <MobileTabbar v-if="!immersive && !secondary" />

    <Toast />
    <Confirm />
    <PasswordPrompt />
    <FilePreview />
    <TaskFloater />
  </div>
</template>
