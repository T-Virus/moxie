<template>
  <main class="page notif">
    <header class="page-head notif__head">
      <div>
        <h1 class="page-title">消息中心</h1>
        <p class="page-sub">订阅、支付、额度与任务提醒都会汇总在这里。</p>
      </div>
      <button
        type="button"
        class="btn btn--sm"
        :disabled="busy || !unreadCount"
        @click="markAllRead"
      >
        {{ busy ? '处理中…' : '全部已读' }}
      </button>
    </header>

    <SegmentedTabs v-model="filter" :tabs="FILTER_TABS" />

    <p v-if="error" class="alert alert--warn notif__error" role="alert">{{ error }}</p>

    <div v-if="loading" class="empty notif__state">正在加载消息…</div>
    <div v-else-if="!items.length" class="empty notif__state">
      <h2 class="empty__title">{{ filter === 'unread' ? '没有未读消息' : '暂无消息' }}</h2>
      <p class="empty__text">订阅到期、支付结果与额度提醒会在这里通知你。</p>
    </div>

    <ul v-else class="notif__list">
      <li v-for="item in items" :key="item.id">
        <button
          type="button"
          class="notif__item"
          :class="{ 'is-unread': !item.read_at }"
          @click="openItem(item)"
        >
          <span class="notif__dot" :class="{ 'is-on': !item.read_at }" aria-hidden="true" />
          <span class="notif__main">
            <span class="notif__meta">
              <span class="badge" :class="notificationTone(item.level)">
                {{ notificationMeta(item.category).label }}
              </span>
              <time :datetime="item.created_at || undefined">{{ formatDateTime(item.created_at) }}</time>
              <span v-if="!item.read_at" class="notif__unread">未读</span>
            </span>
            <span class="notif__title">{{ item.title }}</span>
            <span class="notif__body">{{ item.body }}</span>
          </span>
        </button>
      </li>
    </ul>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import SegmentedTabs from '@/components/SegmentedTabs.vue'
import { ApiError, friendlyMessage } from '@/services/http'
import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notificationMeta,
  notificationTone,
  type NotificationItem,
} from '@/services/notificationsApi'
import { refreshUnreadCount, unreadCount } from '@/stores/notifications'
import { formatDateTime } from '@/utils/format'

const FILTER_TABS = [
  { id: 'all', label: '全部' },
  { id: 'unread', label: '未读' },
]

const router = useRouter()
const filter = ref('all')
const items = ref<NotificationItem[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')

function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message || friendlyMessage(err.status)
  return '加载消息失败，请稍后重试'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchNotifications({ limit: 100, unreadOnly: filter.value === 'unread' })
    items.value = data.items
    unreadCount.value = data.unread_count
  } catch (err) {
    error.value = errorText(err)
    items.value = []
  } finally {
    loading.value = false
  }
}

async function openItem(item: NotificationItem): Promise<void> {
  // 跳转为主、已读为辅：标记失败由轮询兜底，不阻塞导航
  const target = notificationMeta(item.category).to
  if (!item.read_at) {
    item.read_at = new Date().toISOString()
    unreadCount.value = Math.max(0, unreadCount.value - 1)
    void markNotificationRead(item.id)
      .then(() => refreshUnreadCount())
      .catch(() => undefined)
  }
  void router.push(target)
}

async function markAllRead(): Promise<void> {
  if (busy.value || !unreadCount.value) return
  busy.value = true
  error.value = ''
  try {
    await markAllNotificationsRead()
    unreadCount.value = 0
    if (filter.value === 'unread') {
      await load()
    } else {
      const now = new Date().toISOString()
      items.value = items.value.map((item) => (item.read_at ? item : { ...item, read_at: now }))
    }
  } catch (err) {
    error.value = errorText(err)
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.notif__head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  justify-content: space-between;
}

.notif__error {
  margin-top: var(--space-4);
}

.notif__state {
  margin-top: var(--space-6);
}

.notif__list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: var(--space-4);
}

.notif__item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
  padding: 14px 16px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  text-align: left;
  transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}

.notif__item:hover {
  border-color: var(--color-line-strong);
  background: var(--color-bg-softer);
}

.notif__item.is-unread {
  border-color: rgba(13, 148, 136, 0.35);
  background: #f6fdfc;
}

.notif__dot {
  flex: none;
  width: 7px;
  height: 7px;
  margin-top: 8px;
  border-radius: 50%;
  background: transparent;
}

.notif__dot.is-on {
  background: var(--color-brand);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.14);
}

.notif__main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.notif__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.notif__unread {
  color: var(--color-brand);
  font-weight: 600;
}

.notif__title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--color-text);
}

.notif__body {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
  overflow-wrap: anywhere;
}
</style>
