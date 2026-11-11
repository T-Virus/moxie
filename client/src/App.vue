<template>
  <div class="shell">
    <header class="topbar">
      <div class="topbar__inner">
        <RouterLink to="/" class="brand" aria-label="返回首页">
          <span class="brand__mark" aria-hidden="true">墨</span>
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
          <span class="topbar__email" :title="session.account.email || ''">
            {{ session.account.email }}
          </span>
          <button type="button" class="btn btn--ghost btn--sm" @click="onLogout">退出</button>
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
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout } from '@/services/authApi'
import { refreshSession, resetSession, session } from '@/stores/session'

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

async function onLogout(): Promise<void> {
  await logout()
  resetSession()
  router.push('/')
}

onMounted(() => {
  void refreshSession()
})
</script>

<style scoped>
.topbar__email {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .topbar__email {
    display: none;
  }
}
</style>
