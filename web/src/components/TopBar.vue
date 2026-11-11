<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from './Icon.vue'
import { state, store } from '../store'
import { api } from '../api'
import { toast, ui } from '../ui'

const route = useRoute()
const router = useRouter()

/* 非作品维度页面（任务中心 / 产出文件 / 用量统计等）：头部不回显作品信息 */
const bookScoped = computed(() => route.meta.bookScoped !== false)
const curBook = computed(() => (bookScoped.value
  ? state.books.find(b => b.name === store.curBook()) || null
  : null))
/* 非作品页在窄屏显示页面名，避免顶栏只剩一个搜索框、看不出在哪 */
const pageTitle = computed(() => String(route.meta.title || '工作台'))

/* 搜索作品 */
const search = ref('')
const showDrop = ref(false)
const searchOpen = ref(false)
const searchInput = ref<HTMLInputElement | null>(null)
const hits = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return []
  return state.books.filter(b => (b.title || b.name).toLowerCase().includes(q) || b.name.toLowerCase().includes(q))
})
function hideDrop() { setTimeout(() => (showDrop.value = false), 150) }
function go(b: any) {
  store.setBook(b.name)
  router.push('/overview')
  search.value = ''
  showDrop.value = false
  searchOpen.value = false
  toast('已打开《' + (b.title || b.name) + '》', 'ok')
}
/* 窄屏：点放大镜展开搜索面板，聚焦输入框；切页自动收起 */
function toggleSearch() {
  searchOpen.value = !searchOpen.value
  if (searchOpen.value) nextTick(() => searchInput.value?.focus())
  else { search.value = ''; showDrop.value = false }
}
/* 点面板以外的区域收起（移动端没有 hover，必须给一个明确的退出方式） */
function onDocClick(e: MouseEvent) {
  const t = e.target as HTMLElement | null
  if (!t) return
  if (t.closest('.tb-search-sheet') || t.closest('.tb-search-btn')) return
  toggleSearch()
}
watch(searchOpen, (v) => {
  if (v) setTimeout(() => document.addEventListener('click', onDocClick), 0)
  else document.removeEventListener('click', onDocClick)
})
/* 打开侧栏抽屉时收起搜索面板，避免两层浮层叠在一起 */
watch(() => ui.menuOpen, (v) => { if (v && searchOpen.value) toggleSearch() })
watch(() => route.fullPath, () => { if (searchOpen.value) toggleSearch() })
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <header class="topbar">
    <!-- 移动端抽屉开关（≤1024px 显示，桌面端隐藏） -->
    <button class="icon-btn menu-btn" title="打开导航菜单" @click="ui.menuOpen = true">
      <Icon name="menu" :size="18" />
    </button>
    <!-- 只有选中了具体作品才回显书信息；没有书（书单为空 / 非作品维度页面）
         左侧一律留白，不用页面标题顶替。 -->
    <template v-if="curBook">
      <img v-if="curBook.has_cover" class="tb-cover" :src="api.coverUrl(curBook.name)" alt="" />
      <span v-else class="tb-cover tb-cover-ph">{{ (curBook.title || curBook.name).slice(0, 1) }}</span>
      <div class="tb-meta">
        <div class="tb-name">{{ curBook.title || curBook.name }}</div>
        <div class="tb-sub">
          <span class="tag" :class="curBook.status === '已完结' ? 'gray' : 'green'">
            {{ curBook.status || (curBook.has_chapters ? '连载中' : '大纲阶段') }}
          </span>
          <span v-if="curBook.last_chapter_title">最新章节：{{ curBook.last_chapter_title }}</span>
          <span>更新时间：{{ curBook.mtime_text }}</span>
        </div>
      </div>
    </template>
    <div v-else class="tb-page">
      <b>{{ pageTitle }}</b>
      <small>墨写 · AI 小说工作台</small>
    </div>

    <span class="topbar-spacer"></span>

    <!-- 桌面：常驻搜索框 -->
    <div class="topbar-search">
      <Icon name="search" :size="15" />
      <input v-model="search" @focus="showDrop = true" @blur="hideDrop"
             placeholder="搜索作品" />
      <div v-if="showDrop && hits.length" class="search-drop">
        <button v-for="b in hits" :key="b.name" class="sd-item" @mousedown.prevent="go(b)">
          {{ b.title || b.name }}
        </button>
      </div>
    </div>
    <!-- 窄屏：放大镜 → 搜索面板 -->
    <button class="icon-btn tb-search-btn" title="搜索作品" @click="toggleSearch">
      <Icon name="search" :size="18" />
    </button>
    <transition name="fade">
      <div v-if="searchOpen" class="tb-search-sheet">
        <div class="tbs-row">
          <div class="tbs-field">
            <Icon name="search" :size="16" />
            <input ref="searchInput" v-model="search" placeholder="搜索作品"
                   @focus="showDrop = true" @blur="hideDrop" />
          </div>
          <button class="link-btn" @click="toggleSearch">取消</button>
        </div>
        <div v-if="showDrop && hits.length" class="tbs-list">
          <button v-for="b in hits" :key="b.name" class="tbs-item"
                  @mousedown.prevent="go(b)">{{ b.title || b.name }}</button>
        </div>
      </div>
    </transition>
  </header>
</template>
