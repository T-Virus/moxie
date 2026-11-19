<template>
  <div class="shell">
    <header class="topbar">
      <div class="topbar__inner">
        <RouterLink to="/" class="brand" aria-label="返回首页">
          <img class="brand__icon" :src="brandIcon" alt="" aria-hidden="true" />
          <span class="brand__text">墨写</span>
        </RouterLink>

        <nav class="nav" aria-label="主导航">
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="nav__link"
            :class="{ 'is-active': isActive(item.to) }"
          >
            {{ item.label }}
          </RouterLink>
        </nav>

        <div class="topbar__spacer" />

        <div v-if="session.account" class="topbar__user">
          <PushToggle />
          <div ref="userMenu" class="user-menu">
            <button
              type="button"
              class="user-menu__trigger"
              :aria-expanded="userMenuOpen"
              aria-haspopup="menu"
              @click="userMenuOpen = !userMenuOpen"
            >
              <span class="user-menu__email">{{ session.account.email }}</span>
              <svg class="user-menu__chevron" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
            <div v-if="userMenuOpen" class="user-menu__dropdown" role="menu">
              <div class="user-menu__info" role="presentation">
                <span class="user-menu__label">已登录</span>
                <span class="user-menu__email" :title="session.account.email || ''">{{ session.account.email }}</span>
              </div>
              <RouterLink to="/account" class="user-menu__item" role="menuitem" @click="userMenuOpen = false">
                账户设置
              </RouterLink>
              <button type="button" class="user-menu__item" role="menuitem" @click="onLogout">退出</button>
            </div>
          </div>
        </div>
        <RouterLink v-else to="/login" class="btn btn--sm">登录</RouterLink>
      </div>
    </header>

    <div class="shell__content">
      <RouterView v-slot="{ Component }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PushToggle from '@/components/PushToggle.vue'
import { logout } from '@/services/authApi'
import { refreshSession, resetSession, session } from '@/stores/session'
import brandIcon from '@/assets/brand-icon.png'

const navItems = computed(() =>
  session.account
    ? [
        { to: '/', label: '创作' },
        { to: '/runs', label: '我的作品' },
        { to: '/plans', label: '我的订阅' },
        { to: '/tools', label: '工具' },
      ]
    : [
        { to: '/', label: '创作' },
        { to: '/plans', label: '订阅' },
        { to: '/tools', label: '工具' },
      ],
)

const route = useRoute()
const router = useRouter()

function isActive(to: string): boolean {
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}

const userMenu = ref<HTMLElement | null>(null)
const userMenuOpen = ref(false)

function onDocumentClick(event: MouseEvent): void {
  if (userMenu.value && !userMenu.value.contains(event.target as Node)) {
    userMenuOpen.value = false
  }
}

async function onLogout(): Promise<void> {
  userMenuOpen.value = false
  await logout()
  resetSession()
  router.push('/')
}

onMounted(() => {
  void refreshSession()
  document.addEventListener('click', onDocumentClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
})
</script>

<style scoped>
.user-menu {
  position: relative;
}

.user-menu__trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  padding: 6px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-md, 8px);
  background: transparent;
  color: var(--color-text-2);
  font-size: var(--text-sm);
  cursor: pointer;
}
.user-menu__trigger:hover,
.user-menu__trigger[aria-expanded='true'] {
  border-color: var(--color-border, var(--border, #e5e7eb));
  background: var(--color-bg-soft, var(--surface-2, #fafafa));
  color: var(--color-text);
}

.user-menu__email {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-menu__chevron {
  flex: none;
  transition: transform var(--dur-fast, 0.15s) var(--ease, ease);
}
.user-menu__trigger[aria-expanded='true'] .user-menu__chevron {
  transform: rotate(180deg);
}

.user-menu__dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 50;
  min-width: 200px;
  padding: 6px;
  border: 1px solid var(--color-border, var(--border, #e5e7eb));
  border-radius: var(--radius-md, 8px);
  background: var(--color-surface, #fff);
  box-shadow: 0 8px 24px -8px rgba(15, 23, 32, 0.24);
}

.user-menu__info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px 10px;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--color-border, var(--border, #e5e7eb));
}
.user-menu__label {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}
.user-menu__info .user-menu__email {
  max-width: 180px;
  color: var(--color-text);
  font-weight: 600;
}

.user-menu__item {
  display: block;
  width: 100%;
  padding: 9px 10px;
  border: 0;
  border-radius: calc(var(--radius-md, 8px) - 2px);
  background: transparent;
  color: var(--color-text);
  font-size: var(--text-sm);
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}
.user-menu__item:hover {
  background: var(--color-bg-soft, var(--surface-2, #fafafa));
  color: var(--color-brand);
}

@media (max-width: 720px) {
  .user-menu__trigger {
    max-width: 120px;
  }
}
</style>
