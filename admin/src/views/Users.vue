<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { SubscriptionRow, TaskRow, UsageMetric, UserDetail, UserRow } from '../types'
import {
  accountLabel, formatNumber, formatTime, planLabel,
} from '../ui'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import Pager from '../components/Pager.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'

const role = getRole()
const canWrite = computed(() => can(role, 'users:write'))

const q = ref('')
const status = ref('')
const page = ref(1)
const pageSize = 30
const rows = ref<UserRow[]>([])
const total = ref<number | null>(null)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.users({ q: q.value.trim(), status: status.value, page: page.value, page_size: pageSize })
    const list = normalizeList<UserRow>(data)
    rows.value = list.items
    total.value = list.total
  } catch (e) {
    rows.value = []
    total.value = null
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}

function setPage(next: number) {
  page.value = next
  void load()
}

onMounted(load)

const detailOpen = ref(false)
const detailRow = ref<UserRow | null>(null)
const detail = ref<UserDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')

const detailAccount = computed(() => detail.value?.account || detail.value?.user || detailRow.value)
const detailDevices = computed(() => detail.value?.devices || [])
const detailSubscription = computed<SubscriptionRow | null>(
  () => (detail.value?.subscription as SubscriptionRow) || detailRow.value?.subscription || null,
)
const detailTasks = computed<TaskRow[]>(
  () => (detail.value?.recent_tasks as TaskRow[]) || (detail.value?.tasks as TaskRow[]) || [],
)
const detailUsage = computed<UsageMetric[]>(
  () => (detail.value?.usage as UsageMetric[]) || (detail.value?.entitlements as UsageMetric[]) || [],
)

async function openDetail(row: UserRow) {
  detailOpen.value = true
  detailRow.value = row
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    detail.value = await api.userDetail(row.id)
  } catch (e) {
    detailError.value = errorMessage(e)
  } finally {
    detailLoading.value = false
  }
}

const banOpen = ref(false)
const banTarget = ref<UserRow | null>(null)
const banMode = ref<'ban' | 'unban'>('ban')
const banReason = ref('')
const banError = ref('')
const banSubmitting = ref(false)

function openBan(row: UserRow, mode: 'ban' | 'unban') {
  banTarget.value = row
  banMode.value = mode
  banReason.value = ''
  banError.value = ''
  banOpen.value = true
}

const deleteOpen = ref(false)
const deleteTarget = ref<UserRow | null>(null)
const deleteError = ref('')
const deleteSubmitting = ref(false)

function openDelete(row: UserRow) {
  deleteTarget.value = row
  deleteError.value = ''
  deleteOpen.value = true
}

async function submitDelete() {
  if (!deleteTarget.value) return
  deleteSubmitting.value = true
  deleteError.value = ''
  try {
    await api.deleteUser(deleteTarget.value.id)
    pushToast('用户已删除，相关数据已清理并写入审计日志')
    deleteOpen.value = false
    await load()
    if (detailOpen.value && detailRow.value?.id === deleteTarget.value.id) {
      detailOpen.value = false
    }
  } catch (e) {
    deleteError.value = errorMessage(e)
  } finally {
    deleteSubmitting.value = false
  }
}

async function submitBan() {
  if (!banTarget.value) return
  if (banReason.value.trim().length < 2) {
    banError.value = '请填写至少 2 个字的原因'
    return
  }
  banSubmitting.value = true
  banError.value = ''
  try {
    if (banMode.value === 'ban') {
      await api.banUser(banTarget.value.id, banReason.value.trim())
    } else {
      await api.unbanUser(banTarget.value.id, banReason.value.trim())
    }
    pushToast(banMode.value === 'ban' ? '用户已封禁，操作已写入审计日志' : '用户已解封，操作已写入审计日志')
    banOpen.value = false
    await load()
    if (detailOpen.value && detailRow.value?.id === banTarget.value.id) {
      detailRow.value = { ...detailRow.value, status: banMode.value === 'ban' ? 'banned' : 'active' }
    }
  } catch (e) {
    banError.value = errorMessage(e)
  } finally {
    banSubmitting.value = false
  }
}

const roleLabel: Record<string, string> = { admin: '管理员', support: '客服', user: '用户' }
</script>

<template>
  <PageHeader title="用户管理" desc="搜索账号、查看设备与订阅、封禁或解封用户。封禁与解封必须填写原因并写入审计日志。">
    <span v-if="!canWrite" class="badge muted">support 只读</span>
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />刷新
    </button>
  </PageHeader>

  <div class="card">
    <form class="toolbar" @submit.prevent="search">
      <div class="tb-group tb-search">
        <input v-model="q" class="input" placeholder="搜索邮箱 / 手机号 / 账号 ID" />
      </div>
      <select v-model="status" class="select tb-select" @change="search">
        <option value="">全部状态</option>
        <option value="active">启用</option>
        <option value="banned">已封禁</option>
        <option value="disabled">已停用</option>
      </select>
      <button class="btn sm" type="submit" :disabled="loading">查询</button>
      <div class="spacer"></div>
      <span class="muted" style="font-size: 12px">共 {{ total === null ? '—' : formatNumber(total) }} 个账号</span>
    </form>

    <div v-if="loading && !rows.length" class="state-loading">
      <StateBlock kind="loading" title="正在加载用户…" />
    </div>
    <div v-else-if="error">
      <StateBlock kind="error" title="用户列表加载失败" :message="error" retry-label="重试" @retry="load" />
    </div>
    <div v-else-if="!rows.length">
      <StateBlock kind="empty" title="没有匹配的用户" message="尝试调整搜索条件或清空状态筛选。" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 76px">ID</th>
              <th>账号</th>
              <th style="width: 90px">角色</th>
              <th style="width: 96px">状态</th>
              <th>订阅</th>
              <th style="width: 80px">设备</th>
              <th style="width: 128px">创建时间</th>
              <th style="width: 150px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td class="mono">#{{ row.id }}</td>
              <td>
                <div>{{ row.email || row.phone || '—' }}</div>
                <div v-if="row.email && row.phone" class="muted" style="font-size: 11.5px">{{ row.phone }}</div>
              </td>
              <td><span class="badge" :class="row.role === 'admin' ? 'purple' : 'muted'">{{ roleLabel[row.role] || row.role }}</span></td>
              <td><StatusBadge :value="row.status" dot /></td>
              <td>
                <template v-if="row.subscription">
                  <div>{{ planLabel(row.subscription) }}</div>
                  <div style="margin-top: 3px"><StatusBadge :value="row.subscription.status" /></div>
                </template>
                <span v-else class="muted">—</span>
              </td>
              <td class="num">{{ row.devices_count ?? '—' }}</td>
              <td class="muted">{{ formatTime(row.created_at) }}</td>
              <td>
                <div class="actions">
                  <button class="btn ghost sm" @click="openDetail(row)">详情</button>
                  <button v-if="canWrite && row.status === 'active'" class="btn danger-ghost sm" @click="openBan(row, 'ban')">封禁</button>
                  <button v-else-if="canWrite && row.status === 'banned'" class="btn ghost sm" @click="openBan(row, 'unban')">解封</button>
                  <button v-if="canWrite && row.role !== 'admin'" class="btn danger-ghost sm" @click="openDelete(row)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pager :page="page" :page-size="pageSize" :total="total" :loading="loading" @update:page="setPage" />
    </template>
  </div>

  <Modal v-if="detailOpen" title="用户详情" :subtitle="detailRow ? `#${detailRow.id} · ${accountLabel(detailRow)}` : ''"
    size="wide" @close="detailOpen = false">
    <div v-if="detailLoading"><StateBlock kind="loading" title="正在加载用户详情…" /></div>
    <div v-else-if="detailError">
      <StateBlock kind="error" title="用户详情加载失败" :message="detailError" retry-label="重试" @retry="detailRow && openDetail(detailRow)" />
    </div>
    <template v-else-if="detailAccount">
      <div class="section-sub">账号信息</div>
      <div class="kv-grid">
        <div class="kv"><span class="k">账号 ID</span><span class="v mono">#{{ detailAccount.id }}</span></div>
        <div class="kv"><span class="k">邮箱</span><span class="v">{{ detailAccount.email || '—' }}</span></div>
        <div class="kv"><span class="k">手机号</span><span class="v">{{ detailAccount.phone || '—' }}</span></div>
        <div class="kv"><span class="k">状态</span><span class="v"><StatusBadge :value="detailAccount.status" dot /></span></div>
        <div class="kv"><span class="k">角色</span><span class="v">{{ roleLabel[detailAccount.role] || detailAccount.role }}</span></div>
        <div class="kv"><span class="k">创建时间</span><span class="v">{{ formatTime(detailAccount.created_at) }}</span></div>
      </div>

      <div class="section-sub">订阅与权益</div>
      <div v-if="detailSubscription" class="kv-grid">
        <div class="kv"><span class="k">套餐</span><span class="v">{{ planLabel(detailSubscription) }}</span></div>
        <div class="kv"><span class="k">状态</span><span class="v"><StatusBadge :value="detailSubscription.status" /></span></div>
        <div class="kv"><span class="k">当前周期</span><span class="v">{{ formatTime(detailSubscription.current_start_at) }} 至 {{ formatTime(detailSubscription.current_end_at) }}</span></div>
        <div class="kv"><span class="k">席位</span><span class="v">{{ detailSubscription.seats ?? '—' }}</span></div>
      </div>
      <div v-else class="muted" style="font-size: 12.5px">暂无订阅</div>

      <div class="section-sub">设备</div>
      <div v-if="detailDevices.length" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>ID</th><th>平台</th><th>名称</th><th>状态</th><th>最后活跃</th><th>创建时间</th></tr></thead>
          <tbody>
            <tr v-for="device in detailDevices" :key="device.id">
              <td class="mono">#{{ device.id }}</td>
              <td>{{ device.platform }}</td>
              <td>{{ device.name || '—' }}</td>
              <td><StatusBadge :value="device.status" /></td>
              <td class="muted">{{ formatTime(device.last_seen_at) }}</td>
              <td class="muted">{{ formatTime(device.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="muted" style="font-size: 12.5px">暂无设备</div>

      <div class="section-sub">最近任务</div>
      <div v-if="detailTasks.length" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>任务 ID</th><th>类型</th><th>状态</th><th>进度</th><th>创建时间</th></tr></thead>
          <tbody>
            <tr v-for="task in detailTasks" :key="task.id">
              <td class="mono truncate" :title="task.id">{{ task.id }}</td>
              <td>{{ task.type || '—' }}</td>
              <td><StatusBadge :value="task.status" /></td>
              <td class="num">{{ task.progress ?? 0 }}%</td>
              <td class="muted">{{ formatTime(task.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="muted" style="font-size: 12.5px">暂无任务</div>

      <div class="section-sub">用量</div>
      <div v-if="detailUsage.length" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>指标</th><th>单位</th><th class="num">上限</th><th class="num">已用</th><th class="num">预占</th><th class="num">剩余</th></tr></thead>
          <tbody>
            <tr v-for="metric in detailUsage" :key="metric.metric">
              <td class="mono">{{ metric.metric }}</td>
              <td>{{ metric.unit || '—' }}</td>
              <td class="num">{{ formatNumber(metric.limit) }}</td>
              <td class="num">{{ formatNumber(metric.used) }}</td>
              <td class="num">{{ formatNumber(metric.reserved) }}</td>
              <td class="num">{{ formatNumber(metric.remaining) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="muted" style="font-size: 12.5px">暂无用量数据</div>
    </template>
    <template #footer>
      <button class="btn ghost sm" @click="detailOpen = false">关闭</button>
      <button v-if="canWrite && detailAccount && detailAccount.status === 'active'" class="btn danger-ghost sm"
        @click="detailRow && openBan(detailRow, 'ban'); detailOpen = false">封禁用户</button>
      <button v-else-if="canWrite && detailAccount && detailAccount.status === 'banned'" class="btn ghost sm"
        @click="detailRow && openBan(detailRow, 'unban'); detailOpen = false">解封用户</button>
      <button v-if="canWrite && detailAccount && detailAccount.role !== 'admin'" class="btn danger sm"
        @click="detailRow && openDelete(detailRow); detailOpen = false">删除用户</button>
    </template>
  </Modal>

  <Modal v-if="deleteOpen" title="删除用户"
    :subtitle="deleteTarget ? `#${deleteTarget.id} · ${accountLabel(deleteTarget)}` : ''" size="narrow" @close="deleteOpen = false">
    <div class="notice error" style="margin-bottom: 14px">
      此操作将<strong>永久删除该账号及其全部子数据</strong>（邮箱验证、设备、订阅、用量、订单、通知、任务等），且不可恢复。操作会写入审计日志。
    </div>
    <div v-if="deleteError" class="notice error" style="margin: 12px 0 0">{{ deleteError }}</div>
    <template #footer>
      <button class="btn ghost sm" :disabled="deleteSubmitting" @click="deleteOpen = false">取消</button>
      <button class="btn danger" :disabled="deleteSubmitting" @click="submitDelete">
        {{ deleteSubmitting ? '提交中…' : '确认删除' }}
      </button>
    </template>
  </Modal>

  <Modal v-if="banOpen" :title="banMode === 'ban' ? '封禁用户' : '解封用户'"
    :subtitle="banTarget ? `#${banTarget.id} · ${accountLabel(banTarget)}` : ''" size="narrow" @close="banOpen = false">
    <div class="notice warn" style="margin-bottom: 14px">
      {{ banMode === 'ban' ? '封禁后该账号的登录会话将失效，云端任务不可继续提交。' : '解封后账号恢复为启用状态。' }}
    </div>
    <div class="field">
      <label>{{ banMode === 'ban' ? '封禁原因' : '解封原因' }}<span class="required">*</span></label>
      <textarea v-model="banReason" class="textarea" placeholder="请填写原因，提交后展示在审计日志中"></textarea>
      <span class="hint">至少 2 个字，原因会写入审计日志。</span>
    </div>
    <div v-if="banError" class="notice error" style="margin: 12px 0 0">{{ banError }}</div>
    <template #footer>
      <button class="btn ghost sm" :disabled="banSubmitting" @click="banOpen = false">取消</button>
      <button class="btn" :class="banMode === 'ban' ? 'danger' : ''" :disabled="banSubmitting" @click="submitBan">
        {{ banSubmitting ? '提交中…' : (banMode === 'ban' ? '确认封禁' : '确认解封') }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.state-loading { padding: 10px 0; }
</style>
