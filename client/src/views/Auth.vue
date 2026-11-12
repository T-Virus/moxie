<template>
  <main class="page page--narrow auth">
    <div class="auth__head">
      <h1 class="page-title">{{ tab === 'login' ? '登录墨写' : '注册墨写' }}</h1>
      <p class="page-sub">
        {{ tab === 'login' ? '登录后可创建任务、查看额度与历史作品。' : '邮箱注册，注册后请查收验证邮件完成激活。' }}
      </p>
    </div>

    <div class="auth__tabs">
      <SegmentedTabs v-model="tab" :tabs="tabs" />
    </div>

    <!-- 待验证：注册成功但邮箱尚未激活 -->
    <div v-if="mode === 'sent'" class="card auth__card auth__sent">
      <h2 class="auth__sent-title">验证邮件已发送</h2>
      <p class="auth__sent-text">
        我们已向 <strong>{{ pendingEmail }}</strong> 发送了一封验证邮件，请点击邮件中的链接完成激活后再登录。
      </p>
      <p v-if="sentInfo" class="auth__info" role="status">{{ sentInfo }}</p>
      <p v-if="error" class="alert" role="alert">{{ error }}</p>
      <button class="btn btn--brand auth__submit" type="button" :disabled="resending" @click="resend">
        <span v-if="resending" class="auth__spinner" aria-hidden="true" />
        {{ resending ? '发送中…' : '重新发送验证邮件' }}
      </button>
      <p class="auth__switch">
        已完成验证？<button type="button" class="auth__link" @click="toLogin">去登录</button>
      </p>
    </div>

    <form v-else class="card auth__card" novalidate @submit.prevent="submit">
      <div class="field">
        <label class="field__label" for="auth-email">邮箱</label>
        <input
          id="auth-email"
          v-model="email"
          class="input"
          type="email"
          autocomplete="email"
          placeholder="you@example.com"
          :aria-invalid="!!emailError"
          @blur="touched = true"
        />
        <p v-if="emailError" class="auth__error" role="alert">{{ emailError }}</p>
      </div>

      <div class="field">
        <label class="field__label" for="auth-password">密码</label>
        <input
          id="auth-password"
          v-model="password"
          class="input"
          type="password"
          :autocomplete="tab === 'login' ? 'current-password' : 'new-password'"
          placeholder="至少 8 位"
          :aria-invalid="!!passwordError"
          @blur="touched = true"
          @keydown.enter.prevent="submit"
        />
        <p v-if="passwordError" class="auth__error" role="alert">{{ passwordError }}</p>
      </div>

      <div v-if="tab === 'register'" class="auth__consent">
        <label class="auth__consent-row">
          <input v-model="consented" type="checkbox" class="auth__check" />
          <span>
            我已阅读并同意
            <RouterLink class="auth__doc" to="/legal?doc=terms" target="_blank">《用户协议》</RouterLink>
            与
            <RouterLink class="auth__doc" to="/legal?doc=privacy" target="_blank">《隐私政策》</RouterLink>
          </span>
        </label>
        <p v-if="consentError" class="auth__error" role="alert">{{ consentError }}</p>
      </div>

      <div v-if="error" class="alert" role="alert">
        <span>{{ error }}</span>
      </div>

      <button class="btn btn--brand auth__submit" type="submit" :disabled="submitting">
        <span v-if="submitting" class="auth__spinner" aria-hidden="true" />
        {{ submitting ? '提交中…' : tab === 'login' ? '登录' : '注册' }}
      </button>

      <p class="auth__switch">
        <template v-if="tab === 'login'">
          还没有账号？<button type="button" class="auth__link" @click="switchTab('register')">去注册</button>
        </template>
        <template v-else>
          已有账号？<button type="button" class="auth__link" @click="switchTab('login')">去登录</button>
        </template>
      </p>
    </form>

    <p class="auth__back">
      <RouterLink to="/">先随便看看，返回创作页</RouterLink>
    </p>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SegmentedTabs, { type SegmentedTab } from '@/components/SegmentedTabs.vue'
import {
  login,
  register,
  resendVerification,
  authErrorMessage,
  LEGAL_VERSION,
  type PendingVerification,
} from '@/services/authApi'
import { ApiError } from '@/services/http'
import { session, setAccount } from '@/stores/session'
import type { AuthResponse } from '@/types'

const tabs: SegmentedTab[] = [
  { id: 'login', label: '登录' },
  { id: 'register', label: '注册' },
]

const route = useRoute()
const router = useRouter()

const tab = ref<'login' | 'register'>(route.query.tab === 'register' ? 'register' : 'login')
const mode = ref<'form' | 'sent'>('form')
const email = ref('')
const password = ref('')
const consented = ref(false)
const touched = ref(false)
const submitting = ref(false)
const resending = ref(false)
const error = ref('')
const sentInfo = ref('')
const pendingEmail = ref('')

const emailError = computed(() => {
  if (!touched.value) return ''
  if (!email.value.trim()) return '请输入邮箱'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) return '邮箱格式不正确'
  return ''
})

const passwordError = computed(() => {
  if (!touched.value) return ''
  if (!password.value) return '请输入密码'
  if (password.value.length < 8) return '密码至少 8 位'
  return ''
})

const consentError = computed(() => {
  if (!touched.value || tab.value !== 'register') return ''
  return consented.value ? '' : '请先阅读并同意用户协议与隐私政策'
})

function switchTab(next: 'login' | 'register'): void {
  tab.value = next
  mode.value = 'form'
  error.value = ''
  sentInfo.value = ''
  touched.value = false
  consented.value = false
}

function toLogin(): void {
  switchTab('login')
}

function nextPath(): string {
  const raw = route.query.next
  return typeof raw === 'string' && raw.startsWith('/') ? raw : '/'
}

function finishLogin(auth: AuthResponse): void {
  setAccount(auth.account)
  session.ready = true
  void router.replace(nextPath())
}

async function submit(): Promise<void> {
  touched.value = true
  error.value = ''
  sentInfo.value = ''
  if (emailError.value || passwordError.value || consentError.value || submitting.value) return

  submitting.value = true
  try {
    if (tab.value === 'login') {
      const auth = await login(email.value.trim(), password.value)
      finishLogin(auth)
      return
    }
    const result = await register(email.value.trim(), password.value, {
      terms: { version: LEGAL_VERSION, accepted: true },
      privacy: { version: LEGAL_VERSION, accepted: true },
    })
    // 邮箱验证开启时，注册只返回待验证状态，不登录
    if (result && 'access_token' in result && result.access_token) {
      finishLogin(result)
    } else {
      const pending = result as PendingVerification
      mode.value = 'sent'
      pendingEmail.value = pending.email || email.value.trim()
    }
  } catch (err) {
    if (err instanceof ApiError) {
      error.value = authErrorMessage(err.status, err.code, err.message)
    } else {
      error.value = '网络异常，请检查连接后重试'
    }
  } finally {
    submitting.value = false
  }
}

async function resend(): Promise<void> {
  resending.value = true
  error.value = ''
  sentInfo.value = ''
  try {
    await resendVerification(pendingEmail.value.trim())
    sentInfo.value = '验证邮件已重新发送，请查收。'
  } catch (err) {
    if (err instanceof ApiError) {
      error.value = authErrorMessage(err.status, err.code, err.message)
    } else {
      error.value = '网络异常，请稍后重试'
    }
  } finally {
    resending.value = false
  }
}
</script>

<style scoped>
.auth__head {
  text-align: center;
}

.auth__tabs {
  display: flex;
  justify-content: center;
  margin: var(--space-6) 0 var(--space-6);
}

.auth__card {
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.auth__error {
  font-size: var(--text-xs);
  color: var(--color-danger);
}

.auth__info {
  font-size: var(--text-xs);
  color: var(--color-success, #1a9c6b);
}

.auth__sent {
  align-items: flex-start;
  text-align: left;
}

.auth__sent-title {
  font-size: var(--text-lg);
  color: var(--color-text-1);
}

.auth__sent-text {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
}

.auth__consent {
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.auth__consent-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  cursor: pointer;
}

.auth__check {
  margin-top: 3px;
  accent-color: var(--color-brand);
}

.auth__doc {
  color: var(--color-brand);
  font-weight: 600;
}

.auth__doc:hover {
  text-decoration: underline;
}

.auth__submit {
  height: 44px;
  margin-top: var(--space-2);
}

.auth__spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  animation: auth-spin 0.7s linear infinite;
}

@keyframes auth-spin {
  to {
    transform: rotate(360deg);
  }
}

.auth__switch {
  font-size: var(--text-sm);
  color: var(--color-text-3);
  text-align: center;
}

.auth__link {
  color: var(--color-brand);
  font-weight: 600;
  padding: 0 2px;
}

.auth__back {
  margin-top: var(--space-6);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-3);
}

.auth__back a:hover {
  color: var(--color-brand);
}
</style>
