<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiBaseLabel, errorMessage } from '../api'
import { consumeLoginNotice, login } from '../auth'

const route = useRoute()
const router = useRouter()
const identity = ref('')
const password = ref('')
const submitting = ref(false)
const error = ref('')
const notice = ref(consumeLoginNotice())

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
  if (!password.value.trim()) {
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
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <div class="brand-logo">墨</div>
        <div>
          <div class="brand-name">墨写 · 管理后台</div>
          <div class="brand-sub">MOXIE OPERATIONS</div>
        </div>
      </div>

      <div class="login-title">登录运营后台</div>
      <p class="login-desc">支持管理员（admin）与客服（support）角色。Token 仅保存在当前浏览器会话中，不写入 URL 或日志。</p>

      <div v-if="notice" class="notice warn">{{ notice }}</div>

      <form class="login-form" @submit.prevent="submit">
        <div class="field">
          <label for="identity">账号<span class="required">*</span></label>
          <input id="identity" v-model="identity" class="input" autocomplete="username"
            placeholder="邮箱或手机号" :disabled="submitting" />
        </div>
        <div class="field">
          <label for="password">密码<span class="required">*</span></label>
          <input id="password" v-model="password" class="input" type="password" autocomplete="current-password"
            placeholder="至少 8 位" :disabled="submitting" @keyup.enter="submit" />
        </div>

        <div v-if="error" class="notice error" style="margin: 0">{{ error }}</div>

        <button class="btn" type="submit" :disabled="submitting" style="height: 38px">
          <span v-if="submitting" class="spinner" style="width: 15px; height: 15px"></span>
          {{ submitting ? '正在登录…' : '登录' }}
        </button>
      </form>

      <div class="login-foot">
        <div>接口地址：<span class="mono">{{ apiBaseLabel() }}</span></div>
        <div>仅允许 admin / support 角色登录；无权限账号将被拒绝。</div>
      </div>
    </div>
  </div>
</template>
