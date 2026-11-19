<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import AuthShell from '../components/AuthShell.vue'
import { api, errorMessage } from '../api'

const route = useRoute()
const token = typeof route.query.token === 'string' ? route.query.token : ''

const password = ref('')
const confirm = ref('')
const showPassword = ref(false)
const showConfirm = ref(false)
const touched = ref(false)
const submitting = ref(false)
const done = ref(false)
const message = ref('')
const error = ref('')

const passwordError = computed(() => {
  if (!touched.value) return ''
  if (!password.value) return '请输入新密码'
  if (password.value.length < 8) return '密码至少 8 位'
  return ''
})

const confirmError = computed(() => {
  if (!touched.value) return ''
  if (!confirm.value) return '请再次输入新密码'
  if (confirm.value !== password.value) return '两次输入的密码不一致'
  return ''
})

async function submit() {
  touched.value = true
  error.value = ''
  if (passwordError.value || confirmError.value) return
  submitting.value = true
  try {
    const result = await api.resetPassword(token, password.value)
    message.value = result.message || '密码已重置，请使用新密码登录管理后台。'
    done.value = true
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}

function toggleIcon(visible: boolean): string {
  return visible
    ? 'M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10 10 0 0 1 12 5c5 0 9 5 9 7a12 12 0 0 1-2.1 3.1M6.2 6.2C4.2 7.6 3 9.7 3 12c0 2 4 7 9 7a9.7 9.7 0 0 0 3.2-.5'
    : 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z'
}
</script>

<template>
  <AuthShell>
    <template v-if="!token">
      <div class="auth-head">
        <div class="auth-kicker">INVALID LINK</div>
        <h2 class="auth-title">链接不完整</h2>
        <p class="auth-desc">当前地址缺少重置令牌，请从邮件中的链接重新打开，或重新申请一封重置邮件。</p>
      </div>
      <router-link class="auth-action" to="/forgot-password">重新申请</router-link>
    </template>

    <template v-else-if="done">
      <div class="auth-head">
        <div class="auth-kicker">ALL DONE</div>
        <h2 class="auth-title">密码已重置</h2>
        <p class="auth-desc">{{ message }}</p>
      </div>
      <router-link class="auth-action" to="/login">前往登录</router-link>
    </template>

    <template v-else>
      <div class="auth-head">
        <div class="auth-kicker">SET NEW PASSWORD</div>
        <h2 class="auth-title">设置新密码</h2>
        <p class="auth-desc">设置成功后，其它设备上的管理后台登录状态会失效，需要重新登录。</p>
      </div>

      <form class="auth-form" novalidate @submit.prevent="submit">
        <div class="field">
          <label for="reset-password">新密码</label>
          <div class="auth-input-wrap">
            <svg class="auth-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M5 11V8a7 7 0 0 1 14 0v3M4 11h16v10H4z" />
            </svg>
            <input
              id="reset-password"
              v-model="password"
              class="input auth-input--icon auth-input--toggle"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="new-password"
              placeholder="至少 8 位"
              :aria-invalid="!!passwordError"
              :disabled="submitting"
              @blur="touched = true"
            />
            <button
              class="auth-pwd-toggle"
              type="button"
              :disabled="submitting"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path :d="toggleIcon(showPassword)" />
                <circle v-if="!showPassword" cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
          <p v-if="passwordError" class="auth-field-error" role="alert">{{ passwordError }}</p>
        </div>

        <div class="field">
          <label for="reset-confirm">确认新密码</label>
          <div class="auth-input-wrap">
            <svg class="auth-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M5 11V8a7 7 0 0 1 14 0v3M4 11h16v10H4zM9 16l2 2 4-4" />
            </svg>
            <input
              id="reset-confirm"
              v-model="confirm"
              class="input auth-input--icon auth-input--toggle"
              :type="showConfirm ? 'text' : 'password'"
              autocomplete="new-password"
              placeholder="再输入一次"
              :aria-invalid="!!confirmError"
              :disabled="submitting"
              @blur="touched = true"
              @keyup.enter="submit"
            />
            <button
              class="auth-pwd-toggle"
              type="button"
              :disabled="submitting"
              :aria-label="showConfirm ? '隐藏密码' : '显示密码'"
              @click="showConfirm = !showConfirm"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path :d="toggleIcon(showConfirm)" />
                <circle v-if="!showConfirm" cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
          <p v-if="confirmError" class="auth-field-error" role="alert">{{ confirmError }}</p>
        </div>

        <div v-if="error" class="notice error" role="alert">{{ error }}</div>

        <button class="btn auth-submit" type="submit" :disabled="submitting">
          <span v-if="submitting" class="spinner" style="width: 15px; height: 15px" />
          {{ submitting ? '提交中…' : '保存新密码' }}
          <svg v-if="!submitting" class="auth-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>
      </form>

      <div class="auth-links">
        <router-link to="/forgot-password">链接失效了？重新申请</router-link>
      </div>
    </template>
  </AuthShell>
</template>
