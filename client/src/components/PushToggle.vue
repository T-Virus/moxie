<template>
  <button
    v-if="available"
    type="button"
    class="btn btn--ghost btn--sm"
    :disabled="busy"
    :aria-pressed="enabled"
    :title="enabled ? '关闭浏览器通知' : '开启任务完成通知'"
    @click="toggle"
  >
    {{ busy ? '处理中…' : enabled ? '关闭通知' : '开启通知' }}
  </button>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { currentPushSubscription, enablePush, pushSupported } from '@/services/push'
import { removePushSubscription, reportPushSubscription } from '@/services/pushApi'

const vapidKey = String(import.meta.env.VITE_VAPID_PUBLIC_KEY || '').trim()
const available = pushSupported() && Boolean(vapidKey)
const enabled = ref(false)
const busy = ref(false)

onMounted(async () => {
  const existing = await currentPushSubscription()
  enabled.value = Boolean(existing)
  // 服务端重启/换库可能丢失订阅记录：浏览器仍订阅时静默补报一次，保持双端一致。
  if (existing) void reportPushSubscription(existing)
})

async function toggle(): Promise<void> {
  busy.value = true
  try {
    if (enabled.value) {
      const existing = await currentPushSubscription()
      if (existing) {
        enabled.value = !(await removePushSubscription(existing))
      } else {
        // 浏览器端已无订阅，直接复位开关
        enabled.value = false
      }
    } else {
      const subscription = await enablePush(vapidKey)
      if (subscription) {
        // 订阅成功即上报服务端；上报失败也保留本地开关（浏览器已订阅，下次挂载会补报）
        void reportPushSubscription(subscription)
        enabled.value = true
      } else {
        enabled.value = false
      }
    }
  } finally {
    busy.value = false
  }
}
</script>
