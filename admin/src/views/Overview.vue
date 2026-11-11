<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { apiBaseLabel, getHealth, getReady, probeEndpoint, type ProbeOutcome } from '../api'
import { can, hiddenNavLabels, ROLE_LABEL, type Permission } from '../roles'
import { getAccount, getRole } from '../session'
import { formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'

interface ProbeRow {
  key: string
  label: string
  path: string
  page: string
  note: string
}

const PROBES: ProbeRow[] = [
  { key: 'users', label: '用户列表', path: '/v1/admin/users?page=1&page_size=1', page: '/users', note: '搜索 / 分页' },
  { key: 'userDetail', label: '用户详情', path: '/v1/admin/users/999999', page: '/users', note: '账号 / 设备 / 订阅 / 任务' },
  { key: 'subscriptions', label: '订阅列表', path: '/v1/admin/subscriptions?page=1&page_size=1', page: '/subscriptions', note: '套餐 / 到期时间' },
  { key: 'quota', label: '额度调整记录', path: '/v1/admin/accounts/999999/quota-adjustments?page=1&page_size=1', page: '/subscriptions', note: '手工调整 / 审计' },
  { key: 'orders', label: '订单列表', path: '/v1/admin/orders?page=1&page_size=1', page: '/orders', note: '全量订单' },
  { key: 'refunds', label: '退款列表', path: '/v1/admin/refunds', page: '/orders', note: '已有接口' },
  { key: 'invoices', label: '发票列表', path: '/v1/admin/invoices', page: '/invoices', note: '已有接口' },
  { key: 'reconcile', label: '对账报告', path: '/v1/admin/payments/reconcile', page: '/reconcile', note: '参数校验已注册' },
  { key: 'tasks', label: '任务看板', path: '/v1/admin/tasks/dashboard', page: '/tasks', note: '队列 / 运行 / 失败' },
  { key: 'alerts', label: '告警列表', path: '/v1/admin/alerts?page=1&page_size=1', page: '/alerts', note: '异常用量告警' },
  { key: 'notifications', label: '通知记录', path: '/v1/admin/notifications?page=1&page_size=1', page: '/alerts', note: '成功 / 失败 / 重试' },
  { key: 'audit', label: '审计日志', path: '/v1/admin/audit-logs?page=1&page_size=1', page: '/audit', note: '服务端过滤 / 分页' },
  { key: 'reminders', label: '续费提醒', path: '/v1/admin/renewal-reminders', page: '/subscriptions', note: '已有接口' },
]

const CAPABILITIES: { label: string; permission: Permission }[] = [
  { label: '用户查看与详情', permission: 'users:read' },
  { label: '封禁 / 解封用户', permission: 'users:write' },
  { label: '订阅与套餐调整', permission: 'subscriptions:write' },
  { label: '额度手工调整', permission: 'quota:write' },
  { label: '退款审批', permission: 'refunds:write' },
  { label: '开票 / 作废', permission: 'invoices:write' },
  { label: '对账查询与导出', permission: 'reconcile:read' },
  { label: '任务重试', permission: 'tasks:write' },
  { label: '告警与通知', permission: 'alerts:read' },
  { label: '审计日志查询', permission: 'audit:read' },
]

const account = ref(getAccount())
const role = ref(getRole())
const roleLabel = computed(() => ROLE_LABEL[role.value || ''] || '未知角色')
const hidden = computed(() => hiddenNavLabels(role.value))

type ProbeState = ProbeOutcome | { state: 'checking'; httpStatus?: number; code?: string; message?: string }
const probes = reactive<Record<string, ProbeState>>({})
for (const item of PROBES) probes[item.key] = { state: 'checking' }
const probing = ref(false)

const health = ref<{ state: 'checking' | 'ok' | 'bad'; body: any }>({ state: 'checking', body: {} })
const ready = ref<{ state: 'checking' | 'ok' | 'degraded' | 'bad'; httpStatus: number; body: any }>({
  state: 'checking', httpStatus: 0, body: {},
})

const readyCount = computed(() => PROBES.filter(item => probes[item.key]?.state === 'ready').length)
const missingCount = computed(() => PROBES.filter(item => probes[item.key]?.state === 'missing').length)

function stateText(state?: string): string {
  return {
    checking: '检测中',
    ready: '可用',
    missing: '未实现',
    forbidden: '权限不足',
    error: '异常',
  }[state || ''] || '未知'
}

function stateClass(state?: string): string {
  return {
    checking: 'checking',
    ready: 'ready',
    missing: 'missing',
    forbidden: 'forbidden',
    error: 'error',
  }[state || ''] || 'checking'
}

async function runProbes() {
  probing.value = true
  for (const item of PROBES) probes[item.key] = { state: 'checking' }
  await Promise.all(PROBES.map(async (item) => {
    probes[item.key] = await probeEndpoint(item.path)
  }))
  probing.value = false
}

async function loadService() {
  health.value = { state: 'checking', body: {} }
  ready.value = { state: 'checking', httpStatus: 0, body: {} }
  const [h, r] = await Promise.all([getHealth(), getReady()])
  health.value = { state: h.ok ? 'ok' : 'bad', body: h.body }
  const readyState = r.httpStatus === 200 ? 'ok' : r.httpStatus === 503 ? 'degraded' : 'bad'
  ready.value = { state: readyState, httpStatus: r.httpStatus, body: r.body }
}

onMounted(() => {
  void loadService()
  void runProbes()
})
</script>

<template>
  <PageHeader title="概览" desc="管理后台运行状态、当前会话权限与服务端接口就绪情况。">
    <button class="btn ghost sm" :disabled="probing" @click="runProbes">
      <Icon name="refresh" :size="14" />{{ probing ? '检测中…' : '刷新接口状态' }}
    </button>
  </PageHeader>

  <div v-if="hidden.length" class="notice warn">
    <div class="notice-body">
      <div class="notice-title">当前为 {{ roleLabel }} 角色，已隐藏权限不足的菜单</div>
      <div>{{ hidden.join('、') }}。这些页面在侧边栏不可见，直接访问会被拦截并提示所需权限。</div>
    </div>
  </div>

  <div class="overview-grid">
    <div class="card" style="margin: 0">
      <div class="card-head">
        <div class="card-title">当前会话</div>
        <div class="spacer"></div>
        <span class="role-chip" :class="role || ''">{{ roleLabel }}</span>
      </div>
      <div class="kv-grid">
        <div class="kv"><span class="k">账号</span><span class="v">{{ account?.email || account?.phone || '—' }}</span></div>
        <div class="kv"><span class="k">账号 ID</span><span class="v mono">#{{ account?.id ?? '—' }}</span></div>
        <div class="kv"><span class="k">账号状态</span><span class="v">{{ account?.status || '—' }}</span></div>
        <div class="kv"><span class="k">创建时间</span><span class="v">{{ formatTime(account?.created_at) }}</span></div>
        <div class="kv"><span class="k">接口地址</span><span class="v mono">{{ apiBaseLabel() }}</span></div>
        <div class="kv"><span class="k">会话存储</span><span class="v">浏览器 sessionStorage（不写入 URL / 日志）</span></div>
      </div>

      <div class="section-sub">服务可用性</div>
      <div class="kv-grid">
        <div class="kv">
          <span class="k">健康检查</span>
          <span class="v">
            <span class="probe-status" :class="health.state === 'ok' ? 'ready' : health.state === 'checking' ? 'checking' : 'error'">
              <i class="dot"></i>{{ health.state === 'ok' ? '正常' : health.state === 'checking' ? '检测中' : '不可用' }}
            </span>
            <span v-if="health.body?.app" class="muted" style="margin-left: 6px">{{ health.body.app }} · {{ health.body.env }}</span>
          </span>
        </div>
        <div class="kv">
          <span class="k">就绪检查</span>
          <span class="v">
            <span class="probe-status" :class="ready.state === 'ok' ? 'ready' : ready.state === 'checking' ? 'checking' : 'missing'">
              <i class="dot"></i>{{ ready.state === 'ok' ? '就绪' : ready.state === 'checking' ? '检测中' : ready.state === 'degraded' ? '降级' : '不可用' }}
            </span>
            <span class="muted" style="margin-left: 6px">DB {{ ready.body?.database ? '✓' : '—' }} / Redis {{ ready.body?.redis ? '✓' : '—' }}</span>
          </span>
        </div>
      </div>
    </div>

    <div class="card" style="margin: 0">
      <div class="card-head">
        <div class="card-title">角色能力</div>
        <div class="spacer"></div>
        <span class="badge muted">{{ roleLabel }}</span>
      </div>
      <div class="perm-list">
        <div v-for="item in CAPABILITIES" :key="item.permission" class="perm-row">
          <Icon :name="can(role, item.permission) ? 'check' : 'ban'" :size="15"
            :style="{ color: can(role, item.permission) ? 'var(--green)' : 'var(--text-3)' }" />
          <span class="name">{{ item.label }}</span>
          <span class="spacer" style="flex: 1"></span>
          <span class="badge" :class="can(role, item.permission) ? 'ok' : 'muted'">
            {{ can(role, item.permission) ? '可用' : '无权限' }}
          </span>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">服务端管理接口就绪情况<span class="sub">共 {{ PROBES.length }} 项，可用 {{ readyCount }} 项，未实现 {{ missingCount }} 项</span></div>
      <div class="spacer"></div>
      <span class="badge" :class="missingCount > 0 ? 'warn' : 'ok'">{{ missingCount > 0 ? '存在缺口' : '全部可用' }}</span>
    </div>
    <div class="table-wrap readiness-table">
      <table class="data-table">
        <thead>
          <tr>
            <th>模块</th><th>方法</th><th>接口</th><th>状态</th><th>说明</th><th style="width: 90px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in PROBES" :key="item.key">
            <td>{{ item.label }}</td>
            <td class="mono">GET</td>
            <td class="mono truncate" :title="item.path">{{ item.path }}</td>
            <td>
              <span class="probe-status" :class="stateClass(probes[item.key]?.state)">
                <i class="dot"></i>{{ stateText(probes[item.key]?.state) }}
              </span>
              <span v-if="probes[item.key]?.httpStatus" class="muted mono" style="margin-left: 6px">
                {{ probes[item.key]?.httpStatus }}
              </span>
            </td>
            <td class="muted">{{ probes[item.key]?.message || item.note }}</td>
            <td><router-link class="btn ghost sm" :to="item.page">前往</router-link></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="missingCount > 0" class="notice warn" style="margin: 14px 0 0">
      <div class="notice-body">
        <div class="notice-title">缺口说明</div>
        <div>标记为「未实现」的接口会在对应页面显示错误态；请以服务端 OpenAPI 为准检查路由与权限。</div>
      </div>
    </div>
  </div>

  <div v-if="probing && readyCount === 0 && missingCount === 0" class="card">
    <StateBlock kind="loading" title="正在检测接口状态…" message="并行探测服务端管理接口，请稍候。" />
  </div>
</template>
