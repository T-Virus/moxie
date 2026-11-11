<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiBaseLabel } from '../api'
import { logout, notifyLoginNotice } from '../auth'
import { ROLE_LABEL, hiddenNavLabels, visibleNav } from '../roles'
import { getAccount, getRole } from '../session'
import Icon from './Icon.vue'

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
const accountText = computed(() => account.value?.email || account.value?.phone || `#${account.value?.id ?? '—'}`)
const avatarText = computed(() => (accountText.value || 'A').slice(0, 1).toUpperCase())
const roleLabel = computed(() => ROLE_LABEL[role.value || ''] || role.value || '未知角色')

async function doLogout() {
  await logout()
  notifyLoginNotice('已退出登录')
  router.replace('/login')
}
</script>

<template>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">墨</div>
        <div>
          <div class="brand-name">墨写</div>
          <div class="brand-sub">运营管理后台</div>
        </div>
      </div>

      <div class="nav">
        <template v-for="group in groups" :key="group.name">
          <div class="nav-section">{{ group.name }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path }"
          >
            <Icon class="nav-icon" :name="item.path.replace('/', '')" :size="16" />
            <span>{{ item.label }}</span>
          </router-link>
        </template>
      </div>

      <div v-if="hidden.length" class="nav-hidden-note">
        当前 {{ roleLabel }} 角色已隐藏权限不足的菜单：{{ hidden.join('、') }}。
      </div>

      <div class="sidebar-foot">
        <div class="user-card">
          <div class="avatar">{{ avatarText }}</div>
          <div class="user-main">
            <div class="user-name" :title="accountText">{{ accountText }}</div>
            <div class="user-meta">{{ roleLabel }} · ID {{ account?.id ?? '—' }}</div>
          </div>
        </div>
        <button class="logout-btn" type="button" @click="doLogout">
          <Icon name="logout" :size="14" style="vertical-align: -2px; margin-right: 4px" />退出登录
        </button>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="topbar-title">{{ title }}</div>
        <div class="topbar-spacer"></div>
        <div class="topbar-meta">
          <span class="api-chip" :title="apiBaseLabel()">
            <i class="dot"></i>
            <span class="api-text">{{ apiBaseLabel() }}</span>
          </span>
          <span class="role-chip" :class="role || ''">{{ roleLabel }}</span>
        </div>
      </header>
      <main class="view">
        <div class="view-inner">
          <router-view />
        </div>
      </main>
    </div>
  </div>
</template>
