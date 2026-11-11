<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import BookArt from './BookArt.vue'
import { api } from '../api'
import { state, store } from '../store'
import { useJobQueue } from '../composables/useJobQueue'
import { confirmBox, toast, ui } from '../ui'
import { fmtNum } from '../utils'

const router = useRouter()
const { running } = useJobQueue()
const kw = ref('')

const books = computed(() => {
  const q = kw.value.trim().toLowerCase()
  if (!q) return state.books
  return state.books.filter(b =>
    (b.title || b.name).toLowerCase().includes(q) || b.name.toLowerCase().includes(q))
})
const cur = computed(() => store.curBook())

const aiState = computed(() => {
  const s = state.studio
  const binds = s?.bindings || {}
  const profiles = s?.profiles || {}
  const bound = Object.entries(binds).filter(([, pid]) => pid && profiles[pid])
  if (bound.length) {
    const ready = bound.filter(([, pid]) => store.profileKey(pid))
    return {
      ok: ready.length > 0,
      model: profiles[bound[0][1]]?.model || '',
      desc: ready.length ? `${ready.length}/${bound.length} 个工序已配置` : '已绑定档案但未填 Key',
    }
  }
  if (state.key) return { ok: true, model: state.model, desc: 'API Key 已配置' }
  return { ok: false, model: state.model, desc: '未配置 API Key' }
})

function close() { ui.menuOpen = false }
function go(path: string) { close(); router.push(path) }
function selectBook(name: string) {
  store.setBook(name)
  close()
  router.push('/overview')
}
async function delBook(name: string) {
  if (!await confirmBox(`确定删除《${name}》的全部产出？此操作不可恢复。`, { danger: true, ok: '删除' })) return
  try {
    await api.deleteBook(name)
    toast('已删除《' + name + '》', 'ok')
    await store.loadStats()
  } catch (e: any) { toast(e.message, 'err') }
}
function settings() { close(); router.push('/settings') }
</script>

<template>
  <aside class="m-drawer" role="dialog" aria-label="作品与导航">
    <div class="m-drawer-top">
      <div class="m-brand">
        <img class="m-brand-logo" src="/icon.png" alt="墨写" />
        <span class="m-brand-txt">
          <b>墨写</b>
          <small>AI 小说工作台</small>
        </span>
      </div>
      <button class="m-icon-btn" title="收起" @click="close"><Icon name="close" :size="18" /></button>
    </div>

    <button class="m-new-book" @click="go('/upload')">
      <Icon name="plus" :size="16" /> 新建作品
    </button>

    <div class="m-drawer-search">
      <Icon name="search" :size="15" />
      <input v-model="kw" placeholder="搜索作品" />
      <button v-if="kw" class="m-clear" @click="kw = ''"><Icon name="close" :size="13" /></button>
    </div>

    <div class="m-drawer-label">
      <span>作品集合</span>
      <span>{{ books.length }}</span>
    </div>

    <div class="m-book-list">
      <div v-for="b in books" :key="b.name" class="m-book-item" :class="{ on: b.name === cur }"
           @click="selectBook(b.name)">
        <BookArt :name="b.name" :title="b.title" :author="b.author" :has-cover="b.has_cover" size="sm" />
        <div class="m-book-meta">
          <b>{{ b.title || b.name }}</b>
          <small>
            <i class="m-dot" :class="b.status === '已完结' ? 'gray' : 'green'"></i>
            {{ b.status || (b.has_chapters ? '连载中' : '大纲阶段') }}
            <em v-if="b.n_chapters">· {{ b.n_chapters }} 章</em>
            <em v-if="b.manuscript_chars">· {{ fmtNum(b.manuscript_chars) }}字</em>
          </small>
        </div>
        <button class="m-book-del" title="删除作品" @click.stop="delBook(b.name)">
          <Icon name="trash" :size="14" />
        </button>
      </div>

      <button v-if="!books.length" class="m-drawer-empty" @click="go('/upload')">
        <Icon name="cloud" :size="22" />
        <span>{{ kw ? '没有匹配的作品' : '还没有作品，点击新建' }}</span>
      </button>
    </div>

    <div class="m-drawer-foot">
      <button class="m-ai-status" @click="settings">
        <span class="m-ai-dot" :class="{ ok: aiState.ok }"></span>
        <span class="m-ai-main">
          <b>AI 服务</b>
          <small>{{ aiState.model || 'DeepSeek 默认' }}</small>
        </span>
        <span class="m-ai-desc">{{ aiState.desc }}</span>
        <Icon name="right" :size="14" />
      </button>

      <div class="m-drawer-actions">
        <button @click="go('/world-map')">
          <span class="m-da-ico"><Icon name="map" :size="19" /></span>
          <span>地图</span>
        </button>
        <button @click="go('/tasks')">
          <span class="m-da-ico"><Icon name="tasks" :size="19" />
            <i v-if="running" class="m-da-badge">{{ running > 9 ? '9+' : running }}</i>
          </span>
          <span>任务</span>
        </button>
        <button @click="go('/outputs')">
          <span class="m-da-ico"><Icon name="folder" :size="19" /></span>
          <span>产出</span>
        </button>
        <button @click="go('/stats')">
          <span class="m-da-ico"><Icon name="dashboard" :size="19" /></span>
          <span>统计</span>
        </button>
        <button @click="settings">
          <span class="m-da-ico"><Icon name="settings" :size="19" /></span>
          <span>设置</span>
        </button>
      </div>
    </div>
  </aside>
</template>
