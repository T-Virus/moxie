<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from './Icon.vue'
import { state, store } from '../store'
import { api } from '../api'
import { useJobQueue } from '../composables/useJobQueue'
import { toast, confirmBox, openSettings, ui } from '../ui'

const route = useRoute()
const router = useRouter()
/* 任务中心入口角标：显示当前正在运行的任务数（与任务中心页共用同一份轮询） */
const { running } = useJobQueue()
/* 新建作品等创建流程不属于任何既有作品：此时不高亮任何作品，避免误以为正在给旧作品建内容 */
const curBook = computed(() => (route.meta.bookScoped === false ? '' : store.curBook()))

/* AI 服务状态：档案绑定优先，其次旧版全局兜底 Key。
   只看 state.key 会导致「已经给工序绑好档案且档案有 Key」时仍显示未配置。 */
const aiState = computed(() => {
  const s = state.studio
  const binds = s?.bindings || {}
  const profiles = s?.profiles || {}
  const bound = Object.entries(binds).filter(([, pid]) => pid && profiles[pid])
  if (bound.length) {
    const ready = bound.filter(([, pid]) => store.profileKey(pid))
    const model = profiles[bound[0][1]]?.model || ''
    if (ready.length) {
      return { ok: true, model, desc: `已就绪 · ${ready.length}/${bound.length} 个工序有 Key · 点击修改` }
    }
    return { ok: false, model, desc: '已绑定档案但未填 Key · 点击设置' }
  }
  if (state.key) {
    return { ok: true, model: state.model, desc: 'API Key 已配置 · 点击修改' }
  }
  return { ok: false, model: state.model, desc: '未配置 API Key · 点击设置' }
})

function selectBook(name: string) {
  store.setBook(name)
  router.push('/overview')
}
async function delBook(name: string) {
  if (!await confirmBox(`确定删除《${name}》的全部产出（拆解数据、正文、报告）？此操作不可恢复。`, { danger: true, ok: '删除' })) return
  try {
    await api.deleteBook(name)
    toast('已删除《' + name + '》', 'ok')
    await store.loadStats()
  } catch (e: any) { toast(e.message, 'err') }
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
        <img class="brand-logo" src="/icon.png" alt="墨写" />
      <div>
        <div class="brand-name">墨写</div>
        <div class="brand-sub">AI 小说工作台</div>
      </div>
      <!-- 移动端抽屉关闭：桌面端隐藏（CSS 控制） -->
      <button class="icon-btn drawer-x" title="关闭菜单" @click="ui.menuOpen = false">
        <Icon name="close" :size="18" />
      </button>
    </div>

    <button class="btn new-work-btn" @click="router.push('/upload')">
      <Icon name="plus" :size="15" /> 新建作品
    </button>

    <div class="nav-section">作品集合</div>
    <div class="lib">
      <div v-for="b in state.books" :key="b.name" class="work-item"
           :class="{ active: b.name === curBook }" role="button" tabindex="0"
           @click="selectBook(b.name)"
           @keydown.enter="selectBook(b.name)"
           @keydown.space.prevent="selectBook(b.name)">
        <img v-if="b.has_cover" class="wi-cover-img" :src="api.coverUrl(b.name)" alt="" />
        <span v-else class="wi-cover">{{ (b.title || b.name).slice(0, 1) }}</span>
        <span class="wi-body">
          <span class="wi-title">{{ b.title || b.name }}<i v-if="b.status === '已完结'" class="wi-done">完结</i></span>
          <span class="wi-meta">
            <i class="dot" :class="b.status === '已完结' ? 'gray' : 'green'"></i>
            {{ b.status || (b.has_chapters ? (b.n_chapters || 0) + ' 章' : '大纲阶段') }}
          </span>
        </span>
        <button class="wi-del" title="删除作品" @click.stop="delBook(b.name)">
          <Icon name="trash" :size="13" />
        </button>
      </div>
      <div v-if="!state.books.length" class="lib-empty" @click="router.push('/upload')">
        <Icon name="cloud" :size="20" />
        <span>还没有作品，点击新建</span>
      </div>
    </div>

    <div class="sidebar-foot">
      <div class="foot-row">
        <RouterLink class="foot-icon" to="/tasks" title="任务中心">
          <Icon name="tasks" :size="17" />
          <i v-if="running" class="foot-badge">{{ running > 9 ? '9+' : running }}</i>
        </RouterLink>
        <RouterLink class="foot-icon" to="/outputs" title="产出文件"><Icon name="folder" :size="17" /></RouterLink>
        <RouterLink class="foot-icon" to="/stats" title="用量与成本统计"><Icon name="dashboard" :size="17" /></RouterLink>
        <button class="foot-icon" title="AI 服务设置" @click="openSettings"><Icon name="settings" :size="17" /></button>
      </div>
      <div class="quota-card" @click="openSettings">
        <div class="quota-title">
          <b>AI 服务状态</b><span>{{ aiState.model || 'DeepSeek 默认' }}</span>
        </div>
        <div class="quota-bar"><i :style="{ width: aiState.ok ? '100%' : '8%' }"></i></div>
        <div class="quota-desc">{{ aiState.desc }}</div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* 抽屉关闭按钮：侧栏默认收起，任何宽度都显示 */
.drawer-x { display: flex; margin-left: auto; flex: none; }

/* 任务中心入口：运行中任务数角标 + 当前页高亮 */
.foot-icon { position: relative; }
.foot-icon.router-link-active { background: #f2f3f5; color: var(--primary); }
.foot-badge {
  position: absolute; top: 1px; right: 4px; min-width: 15px; height: 15px; padding: 0 3px;
  border-radius: 8px; background: var(--orange); color: #fff;
  font-size: 9.5px; font-style: normal; font-weight: 700; line-height: 15px; text-align: center;
  box-shadow: 0 0 0 2px var(--card);
}
</style>
