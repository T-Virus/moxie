<template>
  <main class="page page--narrow forgot">
    <div class="forgot__head">
      <h1 class="forgot__title">忘记密码</h1>
      <p class="forgot__desc">输入注册邮箱，我们将发送重置链接到你的邮箱，30 分钟内有效。</p>
    </div>

    <!-- 已发送态 -->
    <div v-if="sent" class="card forgot__card">
      <div class="forgot__icon" aria-hidden="true">✉️</div>
      <h2 class="forgot__card-title">重置邮件已发送</h2>
      <p class="forgot__card-text">
        若 <strong>{{ sentEmail }}</strong> 已注册，邮件将在一分钟内送达。<br />
        请点击邮件中的链接设置新密码。
      </p>
      <p v-if="message" class="forgot__info" role="status">{{ message }}</p>
      <p v-if="devUrl" class="forgot__info">
        本地调试：
        <a :href="devUrl" class="forgot__link">直接打开重置链接</a>
      </p>
      <RouterLink class="btn btn--brand forgot__btn" to="/login">返回登录</RouterLink>
    </div>

    <!-- 输入态 -->
    <form v-else class="card forgot__card" novalidate @submit.prevent="submit">
      <div class="field">
        <label class="field__label" for="forgot-email">注册邮箱</label>
        <input
          id="forgot-email"
          v-model="email"
          class="input"
          type="email"
          autocomplete="email"
          placeholder="you@example.com"
          :aria-invalid="!!emailError"
          @blur="touched = true"
        />
        <p v-if="emailError" class="forgot__error" role="alert">{{ emailError }}</p>
      </div>

      <p v-if="error" class="alert" role="alert">{{ error }}</p>

      <button class="btn btn--brand forgot__btn" type="submit" :disabled="submitting">
        <span v-if="submitting" class="forgot__spinner" aria-hidden="true" />
        {{ submitting ? '发送中…' : '发送重置邮件' }}
      </button>

      <p class="forgot__foot">
        想起密码了？<RouterLink class="forgot__link" to="/login">返回登录</RouterLink>
      </p>
    </form>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { authErrorMessage, forgotPassword } from '@/services/authApi'
import { ApiError } from '@/services/http'

const email = ref('')
const touched = ref(false)
const submitting = ref(false)
const sent = ref(false)
const sentEmail = ref('')
const message = ref('')
const devUrl = ref('')
const error = ref('')

const emailError = computed(() => {
  if (!touched.value) return ''
  const value = email.value.trim()
  if (!value) return '请输入邮箱'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return '邮箱格式不正确'
  return ''
})

async function submit(): Promise<void> {
  touched.value = true
  error.value = ''
  if (emailError.value) return
  submitting.value = true
  try {
    const result = await forgotPassword(email.value.trim())
    sentEmail.value = result.email
    message.value = result.message
    devUrl.value = result.reset_url || ''
    sent.value = true
  } catch (err) {
    error.value =
      err instanceof ApiError
        ? authErrorMessage(err.status, err.code, err.message)
        : '发送失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.forgot {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 48px;
  min-height: 60vh;
}

.forgot__head {
  text-align: center;
  margin-bottom: 24px;
}

.forgot__title {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0 0 8px;
}

.forgot__desc {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.6;
  margin: 0;
}

.forgot__card {
  width: 100%;
  max-width: 400px;
  padding: 32px 28px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.forgot__icon {
  text-align: center;
  font-size: 36px;
  margin-bottom: 4px;
}

.forgot__card-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text);
  text-align: center;
  margin: 0;
}

.forgot__card-text {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
  text-align: center;
  margin: 0;
}

.forgot__info {
  font-size: var(--text-xs);
  color: var(--color-success, #1a9c6b);
  text-align: center;
}

.forgot__error {
  font-size: var(--text-xs);
  color: var(--color-danger);
}

.forgot__btn {
  height: 44px;
  width: 100%;
  margin-top: 4px;
}

.forgot__spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  animation: forgot-spin 0.7s linear infinite;
}

@keyframes forgot-spin {
  to {
    transform: rotate(360deg);
  }
}

.forgot__foot {
  font-size: var(--text-sm);
  color: var(--color-text-3);
  text-align: center;
  margin: 0;
}

.forgot__link {
  color: var(--color-brand);
  font-weight: 600;
}

.forgot__link:hover {
  text-decoration: underline;
}
</style>
