<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../api'

const route = useRoute()
const token = typeof route.query.token === 'string' ? route.query.token : ''

const password = ref('')
const confirm = ref('')
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

      <template v-if="!token">
        <div class="login-title">链接不完整</div>
        <p class="login-desc">当前地址缺少重置令牌，请从邮件中的链接重新打开，或重新申请一封重置邮件。</p>
        <router-link class="btn" to="/forgot-password" style="height: 38px; display: flex; align-items: center; justify-content: center">
          重新申请
        </router-link>
      </template>

      <template v-else-if="done">
        <div class="login-title">密码已重置</div>
        <p class="login-desc">{{ message }}</p>
        <router-link class="btn" to="/login" style="height: 38px; display: flex; align-items: center; justify-content: center">
          前往登录
        </router-link>
      </template>

      <template v-else>
        <div class="login-title">设置新密码</div>
        <p class="login-desc">设置成功后，其它设备上的管理后台登录状态会失效，需要重新登录。</p>

        <form class="login-form" novalidate @submit.prevent="submit">
          <div class="field">
            <label for="reset-password">新密码<span class="required">*</span></label>
            <input
              id="reset-password"
              v-model="password"
              class="input"
              type="password"
              autocomplete="new-password"
              placeholder="至少 8 位"
              :aria-invalid="!!passwordError"
              :disabled="submitting"
              @blur="touched = true"
            />
            <p v-if="passwordError" class="notice error" style="margin: 4px 0 0" role="alert">{{ passwordError }}</p>
          </div>

          <div class="field">
            <label for="reset-confirm">确认新密码<span class="required">*</span></label>
            <input
              id="reset-confirm"
              v-model="confirm"
              class="input"
              type="password"
              autocomplete="new-password"
              placeholder="再输入一次"
              :aria-invalid="!!confirmError"
              :disabled="submitting"
              @blur="touched = true"
              @keyup.enter="submit"
            />
            <p v-if="confirmError" class="notice error" style="margin: 4px 0 0" role="alert">{{ confirmError }}</p>
          </div>

          <div v-if="error" class="notice error" style="margin: 0" role="alert">{{ error }}</div>

          <button class="btn" type="submit" :disabled="submitting" style="height: 38px">
            <span v-if="submitting" class="spinner" style="width: 15px; height: 15px"></span>
            {{ submitting ? '提交中…' : '保存新密码' }}
          </button>
        </form>

        <div class="login-foot">
          <div>链接失效了？<router-link to="/forgot-password">重新申请</router-link></div>
        </div>
      </template>
    </div>
  </div>
</template>
