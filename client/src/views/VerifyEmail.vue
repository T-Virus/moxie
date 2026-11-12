<template>
  <main class="page page--narrow verify">
    <div class="card verify__card">
      <span v-if="state.kind === 'pending'" class="verify__spinner" aria-hidden="true" />
      <h1 class="page-title">{{ state.title }}</h1>
      <p class="verify__msg">{{ state.message }}</p>

      <div v-if="state.kind === 'success'" class="verify__actions">
        <RouterLink class="btn btn--brand" to="/">进入创作</RouterLink>
      </div>
      <div v-else-if="state.kind === 'error'" class="verify__actions">
        <RouterLink class="btn btn--brand" to="/login">去登录 / 重发验证</RouterLink>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { verifyEmail, authErrorMessage } from '@/services/authApi'
import { ApiError } from '@/services/http'
import { session, setAccount } from '@/stores/session'

const route = useRoute()
const router = useRouter()

const state = reactive({
  kind: 'pending' as 'pending' | 'success' | 'error',
  title: '正在验证邮箱…',
  message: '请稍候，正在为你激活账号。',
})

onMounted(async () => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  if (!token) {
    state.kind = 'error'
    state.title = '链接不完整'
    state.message = '验证链接缺少必要参数，请重新获取验证邮件。'
    return
  }
  try {
    const auth = await verifyEmail(token)
    setAccount(auth.account)
    session.ready = true
    state.kind = 'success'
    state.title = '邮箱验证成功'
    state.message = '账号已激活，正在进入创作页…'
    window.setTimeout(() => router.replace('/'), 1200)
  } catch (err) {
    state.kind = 'error'
    state.title = '验证失败'
    state.message =
      err instanceof ApiError
        ? authErrorMessage(err.status, err.code, err.message)
        : '网络异常，请稍后重试'
  }
})
</script>

<style scoped>
.verify__card {
  padding: var(--space-8);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  text-align: center;
}

.verify__msg {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
  max-width: 420px;
}

.verify__actions {
  margin-top: var(--space-2);
}

.verify__spinner {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: var(--color-brand);
  animation: verify-spin 0.7s linear infinite;
}

@keyframes verify-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
