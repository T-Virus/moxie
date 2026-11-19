<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import { apiBaseLabel, errorMessage } from '../api'
import { consumeLoginNotice, login } from '../auth'

const route = useRoute()
const router = useRouter()
const identity = ref('')
const password = ref('')
const showPassword = ref(false)
const submitting = ref(false)
const error = ref('')
const notice = ref(consumeLoginNotice())

const apiLabel = computed(() => apiBaseLabel())

function targetPath(): string {
  const raw = route.query.redirect
  if (typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//')) return raw
  return '/overview'
}

async function submit() {
  error.value = ''
  if (!identity.value.trim()) {
    error.value = '请输入邮箱或手机号'
    return
  }
  if (!password.value) {
    error.value = '请输入密码'
    return
  }
  submitting.value = true
  try {
    await login(identity.value.trim(), password.value)
    router.replace(targetPath())
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AuthShell>
    <div class="auth-head">
      <div class="auth-kicker">WELCOME BACK</div>
      <h2 class="auth-title">登录运营后台</h2>
      <p class="auth-desc">请使用管理员或客服账号登录</p>
    </div>

    <div v-if="notice" class="notice warn">{{ notice }}</div>

    <form class="auth-form" @submit.prevent="submit">
      <div class="field">
        <label for="identity">邮箱或手机号</label>
        <div class="auth-input-wrap">
          <svg class="auth-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M20 21a8 8 0 0 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />
          </svg>
          <input
            id="identity"
            v-model="identity"
            class="input auth-input--icon"
            autocomplete="username"
            placeholder="you@example.com"
            :disabled="submitting"
          />
        </div>
      </div>

      <div class="field">
        <label for="password">密码</label>
        <div class="auth-input-wrap">
          <svg class="auth-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M5 11V8a7 7 0 0 1 14 0v3M4 11h16v10H4z" />
          </svg>
          <input
            id="password"
            v-model="password"
            class="input auth-input--icon auth-input--toggle"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            placeholder="请输入密码"
            :disabled="submitting"
          />
          <button
            class="auth-pwd-toggle"
            type="button"
            :disabled="submitting"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            <svg v-if="showPassword" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10 10 0 0 1 12 5c5 0 9 5 9 7a12 12 0 0 1-2.1 3.1M6.2 6.2C4.2 7.6 3 9.7 3 12c0 2 4 7 9 7a9.7 9.7 0 0 0 3.2-.5" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>
      </div>

      <div v-if="error" class="notice error" role="alert">{{ error }}</div>

      <button class="btn auth-submit" type="submit" :disabled="submitting">
        <span v-if="submitting" class="spinner" style="width: 15px; height: 15px" />
        {{ submitting ? '正在登录…' : '登录' }}
        <svg v-if="!submitting" class="auth-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </button>
    </form>

    <div class="auth-links">
      <router-link to="/forgot-password">忘记密码？</router-link>
    </div>

    <div class="auth-foot">
      <div class="auth-foot-row"><span>接口地址</span><code class="mono">{{ apiLabel }}</code></div>
      <div class="auth-foot-hint">仅 admin / support 角色可登录，其他账号将被拒绝。</div>
    </div>
  </AuthShell>
</template>
