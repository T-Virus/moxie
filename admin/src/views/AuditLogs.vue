<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import type { AuditRow } from '../types'
import { compactJson, formatNumber, formatTime, prettyJson } from '../ui'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import Pager from '../components/Pager.vue'
import StateBlock from '../components/StateBlock.vue'

const actorId = ref('')
const action = ref('')
const targetType = ref('')
const targetId = ref('')
const startDate = ref('')
const endDate = ref('')

const rows = ref<AuditRow[]>([])
const loading = ref(false)
const error = ref('')
const page = ref(1)
const pageSize = 50
const total = ref<number | null>(null)

async function load() {
  error.value = ''
  const actorText = actorId.value.trim()
  if (actorText && !/^\d+$/.test(actorText)) {
    error.value = '操作人账号 ID 需为数字，服务端按 actor_id 精确过滤。'
    return
  }
  loading.value = true
  try {
    const query: Record<string, unknown> = { page: page.value, page_size: pageSize }
    if (actorText) query.actor_id = Number(actorText)
    if (action.value.trim()) query.action = action.value.trim()
    if (targetType.value.trim()) query.target_type = targetType.value.trim()
    if (targetId.value.trim()) query.target_id = targetId.value.trim()
    if (startDate.value) query.start_at = new Date(`${startDate.value}T00:00:00`).toISOString()
    if (endDate.value) query.end_at = new Date(`${endDate.value}T23:59:59.999`).toISOString()
    const data = await api.auditLogs(query)
    const list = normalizeList<AuditRow>(data)
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

function submit() {
  page.value = 1
  void load()
}

function setPage(next: number) {
  page.value = next
  void load()
}

function resetFilters() {
  actorId.value = ''
  action.value = ''
  targetType.value = ''
  targetId.value = ''
  startDate.value = ''
  endDate.value = ''
  submit()
}

const detailOpen = ref(false)
const detailRow = ref<AuditRow | null>(null)

function openDetail(row: AuditRow) {
  detailRow.value = row
  detailOpen.value = true
}

onMounted(load)
</script>

<template>
  <PageHeader title="审计日志" desc="按操作人、时间、对象查询管理后台的敏感操作记录。日志只读，不允许删除或修改。">
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />刷新
    </button>
  </PageHeader>

  <div class="card">
    <form class="form-grid cols-3" @submit.prevent="submit">
      <div class="field">
        <label>操作人账号 ID</label>
        <input v-model="actorId" class="input" placeholder="精确匹配，例如 42" inputmode="numeric" />
      </div>
      <div class="field">
        <label>操作类型</label>
        <input v-model="action" class="input" placeholder="精确匹配，例如 quota.adjust" />
      </div>
      <div class="field">
        <label>对象类型</label>
        <input v-model="targetType" class="input" placeholder="精确匹配，例如 account / subscription" />
      </div>
      <div class="field">
        <label>对象 ID</label>
        <input v-model="targetId" class="input" placeholder="精确匹配，例如 12" />
      </div>
      <div class="field">
        <label>开始日期</label>
        <input v-model="startDate" class="input" type="date" />
      </div>
      <div class="field">
        <label>结束日期</label>
        <input v-model="endDate" class="input" type="date" />
      </div>
      <div class="span-2" style="display: flex; gap: 8px">
        <button class="btn sm" type="submit" :disabled="loading">{{ loading ? '查询中…' : '查询' }}</button>
        <button class="btn ghost sm" type="button" :disabled="loading" @click="resetFilters">清空筛选</button>
      </div>
    </form>

    <div class="notice info" style="margin: 14px 0 0">
      <div class="notice-body">
        查询使用 <span class="inline-code">GET /v1/admin/audit-logs</span> 的服务端过滤与分页参数
        <span class="inline-code">actor_id / action / target_type / target_id / start_at / end_at / page / page_size</span>；
        其中操作类型、对象类型与对象 ID 为精确匹配。
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">操作记录<span class="sub">{{ total === null ? `${rows.length} 条` : `共 ${formatNumber(total)} 条` }}</span></div>
      <div class="spacer"></div>
      <span class="badge muted">只读</span>
    </div>

    <div v-if="loading"><StateBlock kind="loading" title="正在加载审计日志…" /></div>
    <div v-else-if="error">
      <StateBlock kind="error" title="审计日志加载失败" :message="error" retry-label="重试" @retry="load" />
    </div>
    <div v-else-if="!rows.length">
      <StateBlock kind="empty" :title="total ? '没有更多匹配的审计记录' : '暂无匹配的审计记录'"
        :message="total ? '当前页没有记录，可返回上一页。' : '尝试放宽操作类型、对象或时间条件。'" />
    </div>
    <div v-else class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th style="width: 136px">时间</th>
            <th style="width: 90px">操作人</th>
            <th>操作</th>
            <th style="width: 200px">对象</th>
            <th style="width: 120px">IP</th>
            <th>明细</th>
            <th style="width: 76px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td class="muted">{{ formatTime(row.created_at) }}</td>
            <td class="mono">{{ row.actor_id ? `#${row.actor_id}` : '—' }}</td>
            <td class="mono">{{ row.action }}</td>
            <td class="mono">
              {{ row.target_type || '—' }}<template v-if="row.target_id"> #{{ row.target_id }}</template>
            </td>
            <td class="mono muted">{{ row.ip || '—' }}</td>
            <td class="mono truncate" :title="compactJson(row.meta)">{{ compactJson(row.meta) }}</td>
            <td><button class="btn ghost sm" @click="openDetail(row)">详情</button></td>
          </tr>
        </tbody>
      </table>
      <Pager :page="page" :page-size="pageSize" :total="total" :loading="loading" @update:page="setPage" />
    </div>
  </div>

  <Modal v-if="detailOpen" title="审计记录详情" :subtitle="detailRow ? `#${detailRow.id} · ${detailRow.action}` : ''"
    @close="detailOpen = false">
    <div v-if="detailRow">
      <div class="kv-grid">
        <div class="kv"><span class="k">记录 ID</span><span class="v mono">#{{ detailRow.id }}</span></div>
        <div class="kv"><span class="k">操作时间</span><span class="v">{{ formatTime(detailRow.created_at) }}</span></div>
        <div class="kv"><span class="k">操作人</span><span class="v mono">{{ detailRow.actor_id ? `#${detailRow.actor_id}` : '—' }}</span></div>
        <div class="kv"><span class="k">操作类型</span><span class="v mono">{{ detailRow.action }}</span></div>
        <div class="kv"><span class="k">对象类型</span><span class="v mono">{{ detailRow.target_type || '—' }}</span></div>
        <div class="kv"><span class="k">对象 ID</span><span class="v mono">{{ detailRow.target_id || '—' }}</span></div>
        <div class="kv"><span class="k">来源 IP</span><span class="v mono">{{ detailRow.ip || '—' }}</span></div>
      </div>
      <div class="section-sub">明细（meta）</div>
      <div class="json-block">{{ prettyJson(detailRow.meta) }}</div>
    </div>
    <template #footer>
      <button class="btn ghost sm" @click="detailOpen = false">关闭</button>
    </template>
  </Modal>
</template>
