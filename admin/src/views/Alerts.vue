<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { AlertRow, NotificationRow } from '../types'
import { accountLabel, formatNumber, formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import Pager from '../components/Pager.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'

const role = getRole()
const canRetry = computed(() => can(role, 'notifications:write'))

const alertRows = ref<AlertRow[]>([])
const alertsLoading = ref(false)
const alertsError = ref('')
const alertPage = ref(1)
const alertPageSize = 30
const alertTotal = ref<number | null>(null)

async function loadAlerts() {
  alertsLoading.value = true
  alertsError.value = ''
  try {
    const data = await api.alerts({ page: alertPage.value, page_size: alertPageSize })
    const list = normalizeList<AlertRow>(data)
    alertRows.value = list.items
    alertTotal.value = list.total
  } catch (e) {
    alertRows.value = []
    alertTotal.value = null
    alertsError.value = errorMessage(e)
  } finally {
    alertsLoading.value = false
  }
}

function setAlertPage(next: number) {
  alertPage.value = next
  void loadAlerts()
}

const notifStatus = ref('')
const notifPage = ref(1)
const notifPageSize = 30
const notificationRows = ref<NotificationRow[]>([])
const notifTotal = ref<number | null>(null)
const notifLoading = ref(false)
const notifError = ref('')
const retryingId = ref<number | null>(null)

async function loadNotifications() {
  notifLoading.value = true
  notifError.value = ''
  try {
    const data = await api.notifications({ status: notifStatus.value, page: notifPage.value, page_size: notifPageSize })
    const list = normalizeList<NotificationRow>(data)
    notificationRows.value = list.items
    notifTotal.value = list.total
  } catch (e) {
    notificationRows.value = []
    notifTotal.value = null
    notifError.value = errorMessage(e)
  } finally {
    notifLoading.value = false
  }
}

function changeNotifStatus() {
  notifPage.value = 1
  void loadNotifications()
}

function setNotifPage(next: number) {
  notifPage.value = next
  void loadNotifications()
}

async function retryNotification(row: NotificationRow) {
  retryingId.value = row.id
  try {
    await api.retryNotification(row.id)
    pushToast(`通知 ${row.id} 已重新发送`)
    await loadNotifications()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    retryingId.value = null
  }
}

onMounted(() => {
  void loadAlerts()
  void loadNotifications()
})
</script>

<template>
  <PageHeader title="告警与通知" desc="查看异常用量告警与通知发送记录（成功 / 失败 / 重试）。">
    <span v-if="!canRetry" class="badge muted">support 只读</span>
    <button class="btn ghost sm" :disabled="alertsLoading || notifLoading"
      @click="loadAlerts(); loadNotifications()">
      <Icon name="refresh" :size="14" />刷新全部
    </button>
  </PageHeader>

  <div v-if="!canRetry" class="notice info">
    <div class="notice-body">
      <div class="notice-title">只读模式</div>
      <div>当前角色可查看异常用量告警与通知发送记录；通知重试需要管理员（admin）权限。</div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">异常用量告警<span class="sub">{{ alertTotal === null ? `${alertRows.length} 条` : `${formatNumber(alertTotal)} 条` }}</span></div>
      <div class="spacer"></div>
      <button class="btn ghost sm" :disabled="alertsLoading" @click="loadAlerts">
        <Icon name="refresh" :size="14" />刷新
      </button>
    </div>

    <div v-if="alertsLoading && !alertRows.length"><StateBlock kind="loading" title="正在加载告警…" /></div>
    <div v-else-if="alertsError">
      <StateBlock kind="error" title="告警加载失败" :message="alertsError" retry-label="重试" @retry="loadAlerts" />
    </div>
    <div v-else-if="!alertRows.length">
      <StateBlock kind="empty" title="暂无异常用量告警" message="当前没有超过阈值的用量记录。" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr><th style="width: 96px">级别</th><th>账号</th><th>指标</th><th class="num">用量</th><th class="num">阈值</th><th>说明</th><th style="width: 96px">状态</th><th style="width: 132px">触发时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in alertRows" :key="item.id ?? index">
              <td><StatusBadge :value="item.level || 'info'" /></td>
              <td>
                <div>{{ accountLabel(item) }}</div>
                <div v-if="item.account_id" class="muted mono" style="font-size: 11.5px">账号 #{{ item.account_id }}</div>
              </td>
              <td class="mono">{{ item.metric || '—' }}</td>
              <td class="num">{{ formatNumber(item.quantity) }}</td>
              <td class="num">{{ formatNumber(item.threshold) }}</td>
              <td class="truncate" :title="item.message || ''">{{ item.message || '—' }}</td>
              <td><StatusBadge :value="item.status || 'pending'" /></td>
              <td class="muted">{{ formatTime(item.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pager :page="alertPage" :page-size="alertPageSize" :total="alertTotal" :loading="alertsLoading" @update:page="setAlertPage" />
    </template>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">通知发送记录<span class="sub">{{ notifTotal === null ? '' : `${formatNumber(notifTotal)} 条` }}</span></div>
      <div class="spacer"></div>
      <select v-model="notifStatus" class="select tb-select" style="height: 32px" @change="changeNotifStatus">
        <option value="">全部状态</option>
        <option value="queued">待发送</option>
        <option value="sent">已发送</option>
        <option value="failed">失败</option>
        <option value="skipped">已跳过</option>
      </select>
      <button class="btn ghost sm" :disabled="notifLoading" @click="loadNotifications">
        <Icon name="refresh" :size="14" />刷新
      </button>
    </div>

    <div v-if="notifLoading && !notificationRows.length"><StateBlock kind="loading" title="正在加载通知记录…" /></div>
    <div v-else-if="notifError">
      <StateBlock kind="error" title="通知记录加载失败" :message="notifError" retry-label="重试" @retry="loadNotifications" />
    </div>
    <div v-else-if="!notificationRows.length">
      <StateBlock kind="empty" title="暂无通知记录" message="当前筛选条件下没有发送记录。" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 72px">ID</th>
              <th style="width: 92px">渠道</th>
              <th>接收方</th>
              <th>主题 / 模板</th>
              <th style="width: 96px">状态</th>
              <th class="num" style="width: 64px">尝试</th>
              <th>最后错误</th>
              <th style="width: 132px">创建时间</th>
              <th style="width: 90px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in notificationRows" :key="row.id">
              <td class="mono">#{{ row.id }}</td>
              <td>{{ row.channel || '—' }}</td>
              <td>{{ row.recipient || '—' }}</td>
              <td>
                <div>{{ row.subject || row.template || '—' }}</div>
                <div v-if="row.template && row.subject" class="muted" style="font-size: 11.5px">{{ row.template }}</div>
              </td>
              <td><StatusBadge :value="row.status" dot /></td>
              <td class="num">{{ row.attempts ?? '—' }}</td>
              <td class="truncate" :title="row.last_error || ''">{{ row.last_error || '—' }}</td>
              <td class="muted">{{ formatTime(row.created_at) }}</td>
              <td>
                <button v-if="canRetry && ['failed', 'skipped'].includes(row.status)" class="btn ghost sm"
                  :disabled="retryingId === row.id" @click="retryNotification(row)">
                  {{ retryingId === row.id ? '提交中…' : '重试' }}
                </button>
                <span v-else class="muted" style="font-size: 12px">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pager :page="notifPage" :page-size="notifPageSize" :total="notifTotal" :loading="notifLoading" @update:page="setNotifPage" />
    </template>
  </div>
</template>
