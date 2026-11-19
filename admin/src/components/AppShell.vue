<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiBaseLabel, errorMessage } from '../api'
import { changePassword, logout, notifyLoginNotice } from '../auth'
import { ROLE_LABEL, hiddenNavLabels, visibleNav } from '../roles'
import { getAccount, getRole } from '../session'
import { pushToast } from '../toast'
import brandIcon from '../assets/brand-icon.png'
import Icon from './Icon.vue'
import Modal from './Modal.vue'

const route = useRoute()
const router = useRouter()
const account = ref(getAccount())
const role = ref(getRole())

const nav = computed(() => visibleNav(role.value))
const groups = computed(() => {
  const map = new Map<string, typeof nav.value>()
  for (const item of nav.value) {
    const list = map.get(item.group) || []
    list.push(item)
    map.set(item.group, list)
  }
  return Array.from(map.entries()).map(([name, items]) => ({ name, items }))
})
const hidden = computed(() => hiddenNavLabels(role.value))
const title = computed(() => (route.meta.title as string) || '管理后台')
const currentGroup = computed(() => nav.value.find(item => item.path === route.path)?.group || '工作台')
const accountText = computed(() => account.value?.email || account.value?.phone || `#${account.value?.id ?? '—'}`)
const avatarText = computed(() => (accountText.value || 'A').slice(0, 1).toUpperCase())
const roleLabel = computed(() => ROLE_LABEL[role.value || ''] || role.value || '未知角色')

const collapsed = ref(localStorage.getItem('moxie-admin-sidebar-collapsed') === '1')
function toggleSidebar() {
  collapsed.value = !collapsed.value
  localStorage.setItem('moxie-admin-sidebar-collapsed', collapsed.value ? '1' : '0')
}

const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)
function onDocClick(event: MouseEvent) {
  if (userMenuRef.value && !userMenuRef.value.contains(event.target as Node)) userMenuOpen.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

const pwdOpen = ref(false)
const pwdSubmitting = ref(false)
const pwdError = ref('')
const pwdForm = ref({ current: '', next: '', confirm: '' })
/** 三个密码框各自独立控制明文/密文 */
const pwdShow = ref({ current: false, next: false, confirm: false })

function togglePwd(field: 'current' | 'next' | 'confirm') {
  pwdShow.value[field] = !pwdShow.value[field]
}

function openPassword() {
  userMenuOpen.value = false
  pwdForm.value = { current: '', next: '', confirm: '' }
  pwdShow.value = { current: false, next: false, confirm: false }
  pwdError.value = ''
  pwdOpen.value = true
}

async function submitPassword() {
  const form = pwdForm.value
  pwdError.value = ''
  if (!form.current) {
    pwdError.value = '请输入当前密码'
    return
  }
  if (form.next.length < 8) {
    pwdError.value = '新密码至少 8 位'
    return
  }
  if (form.next !== form.confirm) {
    pwdError.value = '两次输入的新密码不一致'
    return
  }
  if (form.next === form.current) {
    pwdError.value = '新密码不能与当前密码相同'
    return
  }
  pwdSubmitting.value = true
  try {
    const message = await changePassword(form.current, form.next)
    pwdOpen.value = false
    pushToast(message)
  } catch (e) {
    pwdError.value = errorMessage(e)
  } finally {
    pwdSubmitting.value = false
  }
}

async function doLogout() {
  userMenuOpen.value = false
  await logout()
  notifyLoginNotice('已退出登录')
  router.replace('/login')
}
</script>

<template>
  <div class="app" :class="{ 'is-collapsed': collapsed }">
    <aside class="sidebar">
      <div class="brand">
        <img class="brand-logo" :src="brandIcon" alt="墨写" />
        <div v-if="!collapsed" class="brand-text">
          <div class="brand-name">墨写</div>
          <div class="brand-sub">运营管理后台</div>
        </div>
        <button class="sidebar-toggle" type="button" :title="collapsed ? '展开侧边栏' : '收起侧边栏'" @click="toggleSidebar">
          <Icon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="14" />
        </button>
      </div>

      <nav class="nav">
        <template v-for="group in groups" :key="group.name">
          <div v-if="!collapsed" class="nav-section">{{ group.name }}</div>
          <div v-else class="nav-divider"></div>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path }"
            :title="collapsed ? item.label : ''"
          >
            <Icon class="nav-icon" :name="item.path.replace('/', '')" :size="17" />
            <span v-if="!collapsed">{{ item.label }}</span>
          </router-link>
        </template>
      </nav>

      <div v-if="hidden.length && !collapsed" class="nav-hidden-note">
        当前 {{ roleLabel }} 角色已隐藏 {{ hidden.length }} 个无权限菜单。
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="breadcrumb">
          <span>{{ currentGroup }}</span>
          <i>/</i>
          <strong>{{ title }}</strong>
        </div>
        <div class="topbar-spacer"></div>
        <div class="topbar-meta">
          <span class="api-chip" :title="apiBaseLabel()">
            <i class="dot"></i>
            <span class="api-text">{{ apiBaseLabel() }}</span>
          </span>
          <button class="icon-btn" type="button" title="刷新当前页" @click="router.go(0)">
            <Icon name="refresh" :size="16" />
          </button>
          <div ref="userMenuRef" class="user-menu-wrap">
            <button class="top-user" type="button" @click="userMenuOpen = !userMenuOpen">
              <span class="top-avatar">{{ avatarText }}</span>
              <span class="top-user-name">{{ accountText }}</span>
              <span class="top-role">{{ roleLabel }}</span>
              <span class="caret" aria-hidden="true"></span>
            </button>
            <div v-if="userMenuOpen" class="user-dropdown">
              <div class="dropdown-head">
                <div class="dropdown-name">{{ accountText }}</div>
                <div class="dropdown-meta">{{ roleLabel }} · ID {{ account?.id ?? '—' }}</div>
              </div>
              <button type="button" @click="openPassword">
                <Icon name="unlock" :size="15" />修改密码
              </button>
              <button type="button" class="danger" @click="doLogout">
                <Icon name="logout" :size="15" />退出登录
              </button>
            </div>
          </div>
        </div>
      </header>
      <main class="view" :data-route="route.path">
        <div class="view-inner">
          <router-view />
        </div>
      </main>
    </div>

    <Modal v-if="pwdOpen" title="修改密码" subtitle="修改后其它设备需要重新登录，当前浏览器保持登录" size="narrow"
      @close="pwdOpen = false">
      <div class="form-grid single-col">
        <div class="field">
          <label>当前密码<span class="required">*</span></label>
          <div class="pwd-input">
            <input v-model="pwdForm.current" class="input" :type="pwdShow.current ? 'text' : 'password'"
              autocomplete="current-password" placeholder="请输入当前密码" />
            <button type="button" class="pwd-eye" :aria-label="pwdShow.current ? '隐藏密码' : '显示密码'"
              @click="togglePwd('current')">
              <svg v-if="pwdShow.current" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10 10 0 0 1 12 5c5 0 9 5 9 7a12 12 0 0 1-2.1 3.1M6.2 6.2C4.2 7.6 3 9.7 3 12c0 2 4 7 9 7a9.7 9.7 0 0 0 3.2-.5" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
        </div>
        <div class="field">
          <label>新密码<span class="required">*</span></label>
          <div class="pwd-input">
            <input v-model="pwdForm.next" class="input" :type="pwdShow.next ? 'text' : 'password'"
              autocomplete="new-password" placeholder="至少 8 位" />
            <button type="button" class="pwd-eye" :aria-label="pwdShow.next ? '隐藏密码' : '显示密码'"
              @click="togglePwd('next')">
              <svg v-if="pwdShow.next" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10 10 0 0 1 12 5c5 0 9 5 9 7a12 12 0 0 1-2.1 3.1M6.2 6.2C4.2 7.6 3 9.7 3 12c0 2 4 7 9 7a9.7 9.7 0 0 0 3.2-.5" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
          <span class="hint">至少 8 位，建议字母与数字组合。</span>
        </div>
        <div class="field">
          <label>确认新密码<span class="required">*</span></label>
          <div class="pwd-input">
            <input v-model="pwdForm.confirm" class="input" :type="pwdShow.confirm ? 'text' : 'password'"
              autocomplete="new-password" placeholder="再输入一次" @keyup.enter="submitPassword" />
            <button type="button" class="pwd-eye" :aria-label="pwdShow.confirm ? '隐藏密码' : '显示密码'"
              @click="togglePwd('confirm')">
              <svg v-if="pwdShow.confirm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10 10 0 0 1 12 5c5 0 9 5 9 7a12 12 0 0 1-2.1 3.1M6.2 6.2C4.2 7.6 3 9.7 3 12c0 2 4 7 9 7a9.7 9.7 0 0 0 3.2-.5" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
        </div>
        <div v-if="pwdError" class="notice error">{{ pwdError }}</div>
      </div>
      <template #footer>
        <button class="btn ghost sm" :disabled="pwdSubmitting" @click="pwdOpen = false">取消</button>
        <button class="btn" :disabled="pwdSubmitting" @click="submitPassword">
          {{ pwdSubmitting ? '保存中…' : '保存' }}
        </button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
/* 修改密码：右侧明文切换，字段间距交给 form-grid */
.pwd-input { position: relative; display: flex; }
.pwd-input .input { flex: 1 1 auto; padding-right: 36px; }
.pwd-eye {
  position: absolute; top: 50%; right: 6px; transform: translateY(-50%);
  width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center;
  border: none; border-radius: 6px; background: none; color: var(--text-3); cursor: pointer;
}
.pwd-eye:hover { background: #f1f5f4; color: var(--text); }
.pwd-eye svg { width: 16px; height: 16px; }
</style>
