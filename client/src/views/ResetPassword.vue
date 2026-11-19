<template>
  <main class="page page--narrow reset">
    <div class="reset__head">
      <h1 class="reset__title">设置新密码</h1>
      <p class="reset__desc">设置成功后，其它设备上的登录状态会失效，需要重新登录。</p>
    </div>

    <!-- 链接不完整 -->
    <div v-if="!token" class="card reset__card">
      <div class="reset__icon reset__icon--warn" aria-hidden="true">⚠️</div>
      <h2 class="reset__card-title">链接不完整</h2>
      <p class="reset__card-text">当前地址缺少重置令牌，请从邮件中的链接重新打开，或重新申请一封重置邮件。</p>
      <RouterLink class="btn btn--brand reset__btn" to="/forgot-password">重新申请</RouterLink>
    </div>

    <!-- 重置成功 -->
    <div v-else-if="done" class="card reset__card">
      <div class="reset__icon reset__icon--ok" aria-hidden="true">✓</div>
      <h2 class="reset__card-title">密码已重置</h2>
      <p class="reset__card-text">{{ message }}</p>
      <RouterLink class="btn btn--brand reset__btn" to="/login">去登录</RouterLink>
    </div>

    <!-- 输入新密码 -->
    <form v-else class="card reset__card" novalidate @submit.prevent="submit">
      <div class="field">
        <label class="field__label" for="reset-password">新密码</label>
        <input
          id="reset-password"
          v-model="password"
          class="input"
          type="password"
          autocomplete="new-password"
          placeholder="至少 8 位"
          :aria-invalid="!!passwordError"
          @blur="touched = true"
        />
        <p v-if="passwordError" class="reset__error" role="alert">{{ passwordError }}</p>
      </div>

      <div class="field">
        <label class="field__label" for="reset-confirm">确认新密码</label>
        <input
          id="reset-confirm"
          v-model="confirm"
          class="input"
          type="password"
          autocomplete="new-password"
          placeholder="再输入一次"
          :aria-invalid="!!confirmError"
          @blur="touched = true"
        />
        <p v-if="confirmError" class="reset__error" role="alert">{{ confirmError }}</p>
      </div>

      <p v-if="error" class="alert" role="alert">{{ error }}</p>

      <button class="btn btn--brand reset__btn" type="submit" :disabled="submitting">
        <span v-if="submitting" class="reset__spinner" aria-hidden="true" />
        {{ submitting ? '提交中…' : '保存新密码' }}
      </button>

      <p class="reset__foot">
        链接失效了？<RouterLink class="reset__link" to="/forgot-password">重新申请</RouterLink>
      </p>
    </form>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { authErrorMessage, resetPassword } from '@/services/authApi'
import { ApiError } from '@/services/http'

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

async function submit(): Promise<void> {
  touched.value = true
  error.value = ''
  if (passwordError.value || confirmError.value) return
  submitting.value = true
  try {
    const result = await resetPassword(token, password.value)
    message.value = result.message || '密码已重置，请使用新密码登录。'
    done.value = true
  } catch (err) {
    error.value =
      err instanceof ApiError
        ? authErrorMessage(err.status, err.code, err.message)
        : '重置失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.reset {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 48px;
  min-height: 60vh;
}

.reset__head {
  text-align: center;
  margin-bottom: 24px;
}

.reset__title {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0 0 8px;
}

.reset__desc {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.6;
  margin: 0;
}

.reset__card {
  width: 100%;
  max-width: 400px;
  padding: 32px 28px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.reset__icon {
  text-align: center;
  font-size: 36px;
  line-height: 1;
  margin-bottom: 4px;
}

.reset__icon--ok {
  color: var(--color-success, #1a9c6b);
  font-weight: 700;
}

.reset__card-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text);
  text-align: center;
  margin: 0;
}

.reset__card-text {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
  text-align: center;
  margin: 0;
}

.reset__error {
  font-size: var(--text-xs);
  color: var(--color-danger);
}

.reset__btn {
  height: 44px;
  width: 100%;
  margin-top: 4px;
}

.reset__spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  animation: reset-spin 0.7s linear infinite;
}

@keyframes reset-spin {
  to {
    transform: rotate(360deg);
  }
}

.reset__foot {
  font-size: var(--text-sm);
  color: var(--color-text-3);
  text-align: center;
  margin: 0;
}

.reset__link {
  color: var(--color-brand);
  font-weight: 600;
}

.reset__link:hover {
  text-decoration: underline;
}
</style>
