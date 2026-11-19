<script setup lang="ts">
import { ref } from 'vue'
import AuthShell from '../components/AuthShell.vue'
import { api, apiBaseLabel, errorMessage } from '../api'

const email = ref('')
const submitting = ref(false)
const error = ref('')
const sent = ref(false)
const message = ref('')
const devUrl = ref('')

async function submit() {
  error.value = ''
  const value = email.value.trim()
  if (!value) {
    error.value = '请输入登录邮箱'
    return
  }
  submitting.value = true
  try {
    const result = await api.forgotPassword(value)
    message.value = result.message
    devUrl.value = result.reset_url || ''
    sent.value = true
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
      <div class="auth-kicker">ACCOUNT RECOVERY</div>
      <h2 class="auth-title">找回密码</h2>
      <p class="auth-desc">输入管理账号邮箱，我们会发送一封重置密码邮件；链接 30 分钟内有效，仅在本管理后台打开。</p>
    </div>

    <template v-if="sent">
      <div class="notice info">{{ message }}</div>
      <div v-if="devUrl" class="notice warn auth-dev-link" style="margin-top: 12px">
        本地调试（未配置邮件服务）：<a :href="devUrl" target="_blank" rel="noopener">直接打开重置链接</a>
      </div>
      <router-link class="auth-action" to="/login">返回登录</router-link>
    </template>

    <form v-else class="auth-form" @submit.prevent="submit">
      <div class="field">
        <label for="forgot-email">登录邮箱</label>
        <div class="auth-input-wrap">
          <svg class="auth-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M4 6h16v12H4zM4 7l8 6 8-6" />
          </svg>
          <input
            id="forgot-email"
            v-model="email"
            class="input auth-input--icon"
            type="email"
            autocomplete="email"
            placeholder="you@example.com"
            :disabled="submitting"
          />
        </div>
      </div>

      <div v-if="error" class="notice error" role="alert">{{ error }}</div>

      <button class="btn auth-submit" type="submit" :disabled="submitting">
        <span v-if="submitting" class="spinner" style="width: 15px; height: 15px" />
        {{ submitting ? '发送中…' : '发送重置邮件' }}
        <svg v-if="!submitting" class="auth-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </button>
    </form>

    <div class="auth-links">
      <router-link to="/login">返回登录</router-link>
    </div>

    <div class="auth-foot">
      <div class="auth-foot-row"><span>接口地址</span><code class="mono">{{ apiBaseLabel() }}</code></div>
      <div class="auth-foot-hint">重置链接仅发送至已注册的管理员或客服邮箱。</div>
    </div>
  </AuthShell>
</template>
