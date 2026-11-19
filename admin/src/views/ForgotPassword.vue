<script setup lang="ts">
import { ref } from 'vue'
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
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <div class="brand-logo">墨</div>
        <div>
          <div class="brand-name">墨写 · 管理后台</div>
          <div class="brand-sub">MOXIE OPERATIONS</div>
        </div>
      </div>

      <div class="login-title">找回密码</div>
      <p class="login-desc">输入管理账号邮箱，我们会发送一封重置密码邮件；链接 30 分钟内有效，仅在本管理后台打开。</p>

      <template v-if="sent">
        <div class="notice" style="margin-bottom: 14px">{{ message }}</div>
        <div v-if="devUrl" class="notice warn" style="margin-bottom: 14px; word-break: break-all">
          本地调试（未配置邮件服务）：<a :href="devUrl" target="_blank" rel="noopener">直接打开重置链接</a>
        </div>
        <router-link class="btn" to="/login" style="height: 38px; display: flex; align-items: center; justify-content: center">
          返回登录
        </router-link>
      </template>

      <form v-else class="login-form" @submit.prevent="submit">
        <div class="field">
          <label for="forgot-email">登录邮箱<span class="required">*</span></label>
          <input
            id="forgot-email"
            v-model="email"
            class="input"
            type="email"
            autocomplete="email"
            placeholder="you@example.com"
            :disabled="submitting"
            @keyup.enter="submit"
          />
        </div>

        <div v-if="error" class="notice error" style="margin: 0">{{ error }}</div>

        <button class="btn" type="submit" :disabled="submitting" style="height: 38px">
          <span v-if="submitting" class="spinner" style="width: 15px; height: 15px"></span>
          {{ submitting ? '发送中…' : '发送重置邮件' }}
        </button>

        <div class="login-foot" style="padding-top: 4px">
          <div><router-link to="/login">返回登录</router-link></div>
          <div>接口地址：<span class="mono">{{ apiBaseLabel() }}</span></div>
        </div>
      </form>
    </div>
  </div>
</template>
