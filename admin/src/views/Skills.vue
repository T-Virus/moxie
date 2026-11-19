<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { AdminSkillItem, SkillCoverage, SkillsCatalog } from '../types'
import { formatDate } from '../ui'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import RowActions, { type RowAction } from '../components/RowActions.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'

const canRead = computed(() => can(getRole(), 'skills:read'))
const rows = ref<AdminSkillItem[]>([])
const meta = ref<Omit<SkillsCatalog, 'items'>>({ degraded: null, schema_version: null, updated_at: null })
const loading = ref(false)
const error = ref('')

const COVERAGE: Record<SkillCoverage, string> = {
  full: '完整可用',
  partial: '部分可用',
  cloud_gap: '云端完善中',
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await api.skills()
    rows.value = Array.isArray(data.items) ? data.items : []
    meta.value = {
      degraded: data.degraded,
      schema_version: data.schema_version,
      updated_at: data.updated_at,
    }
    if (data.degraded) pushToast(`技能目录降级：${data.degraded}`, 'warn')
  } catch (err) {
    rows.value = []
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

onMounted(() => { if (canRead.value) load() })

const coverageCounts = computed(() => {
  const out = { full: 0, partial: 0, cloud_gap: 0 }
  for (const row of rows.value) out[row.coverage] = (out[row.coverage] || 0) + 1
  return out
})

const detail = ref<AdminSkillItem | null>(null)
function openDetail(row: AdminSkillItem): void {
  detail.value = row
}
function closeDetail(): void {
  detail.value = null
}
function rowActions(row: AdminSkillItem): RowAction[] {
  return [{ label: '详情', tone: 'primary', run: () => openDetail(row) }]
}
</script>

<template>
  <div class="skills-page">
    <PageHeader
      title="技能目录"
      desc="创作全链路的 10 个技能项由服务端统一清单维护；此处核对覆盖状态、缺口与实际注册情况，三端共用同一份数据。"
    >
      <span v-if="!canRead" class="badge muted">只读</span>
      <button class="btn ghost" :disabled="loading || !canRead" @click="load">
        <Icon name="refresh" :size="14" />{{ loading ? '加载中…' : '刷新' }}
      </button>
    </PageHeader>

    <div v-if="meta.degraded" class="notice warn">
      <div class="notice-body">
        <div class="notice-title">目录降级</div>
        <div>{{ meta.degraded }}</div>
      </div>
    </div>

    <template v-if="rows.length">
      <div class="stat-grid skills-stats">
        <div class="stat-card teal">
          <div class="stat-top"><span class="stat-label">技能项</span><span class="stat-ico"><Icon name="skills" :size="16" /></span></div>
          <div class="stat-value">{{ rows.length }}</div>
          <div class="stat-desc">统一清单收录总数</div>
        </div>
        <div class="stat-card green">
          <div class="stat-top"><span class="stat-label">完整可用</span><span class="stat-ico"><Icon name="check" :size="16" /></span></div>
          <div class="stat-value">{{ coverageCounts.full }}</div>
          <div class="stat-desc">云端与桌面均已覆盖</div>
        </div>
        <div class="stat-card orange">
          <div class="stat-top"><span class="stat-label">部分可用</span><span class="stat-ico"><Icon name="info" :size="16" /></span></div>
          <div class="stat-value">{{ coverageCounts.partial }}</div>
          <div class="stat-desc">存在能力缺口</div>
        </div>
        <div class="stat-card purple">
          <div class="stat-top"><span class="stat-label">云端完善中</span><span class="stat-ico"><Icon name="tasks" :size="16" /></span></div>
          <div class="stat-value">{{ coverageCounts.cloud_gap }}</div>
          <div class="stat-desc">待补齐云端能力</div>
        </div>
        <div class="stat-card blue">
          <div class="stat-top"><span class="stat-label">云端已注册</span><span class="stat-ico"><Icon name="shield" :size="16" /></span></div>
          <div class="stat-value">{{ rows.filter(r => r.registered).length }}</div>
          <div class="stat-desc">实际注册生效</div>
        </div>
      </div>

      <div class="card table-card">
        <div class="card-head">
          <div class="card-title">目录明细<span class="sub">目录版本 {{ meta.schema_version || '—' }} · 更新于 {{ formatDate(meta.updated_at) }}</span></div>
          <div class="spacer"></div>
          <span class="muted small">三端共用同一份清单</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 56px">#</th>
                <th>技能项</th>
                <th>覆盖状态</th>
                <th>云端注册</th>
                <th>入口 / 工序</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id">
                <td class="mono muted">{{ String(row.index).padStart(2, '0') }}</td>
                <td>
                  <div class="skill-name truncate" :title="`${row.name} · ${row.id} · ${row.external || '—'}`">{{ row.name }}</div>
                </td>
                <td><StatusBadge :value="row.coverage" :label="COVERAGE[row.coverage] || row.coverage" /></td>
                <td><span class="badge" :class="row.registered ? 'ok' : 'muted'">{{ row.registered ? '已注册' : '未注册' }}</span></td>
                <td>
                  <div class="mono small truncate" :title="`${row.entry.stages.join(' / ') || '—'} · ${row.entry.api.join(' · ') || (row.entry.cloud_skills.join(' · ') || '无入口')}`">
                    {{ row.entry.stages.join(' / ') || '—' }} · {{ row.entry.api.join(' · ') || (row.entry.cloud_skills.join(' · ') || '无入口') }}
                  </div>
                </td>
                <td><RowActions :actions="rowActions(row)" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <div v-else class="card empty-card">
      <StateBlock
        :kind="loading ? 'loading' : (error ? 'error' : 'empty')"
        :title="loading ? '正在加载技能目录…' : (error ? '加载失败' : '暂无技能目录')"
        :message="error"
        :retry-label="error ? '重新加载' : ''"
        @retry="load"
      >
        <button v-if="!loading && !error && canRead" class="btn sm" @click="load">刷新目录</button>
      </StateBlock>
    </div>

    <Modal v-if="detail" :title="`${detail.name} · 技能详情`" size="wide" @close="closeDetail">
      <div class="detail-grid">
        <div class="detail-section">
          <h4>能力说明</h4>
          <p>{{ detail.purpose }}</p>
        </div>
        <div class="detail-section">
          <h4>覆盖状态</h4>
          <p>
            <StatusBadge :value="detail.coverage" :label="COVERAGE[detail.coverage] || detail.coverage" />
            <span v-if="detail.gap" class="muted" style="margin-left: 8px">{{ detail.gap }}</span>
          </p>
        </div>
        <div class="detail-section">
          <h4>数据写权（SSOT）</h4>
          <p>{{ detail.ssot || '—' }}</p>
        </div>
        <div class="detail-section">
          <h4>触发词</h4>
          <p class="mono">{{ detail.trigger.join(' · ') || '—' }}</p>
        </div>
        <div class="detail-section">
          <h4>云端技能 / 桌面工序</h4>
          <p class="mono">
            {{ detail.entry.cloud_skills.join(' · ') || '—' }}
            <span v-if="detail.entry.stages.length"> ｜ {{ detail.entry.stages.join(' · ') }}</span>
          </p>
          <p class="muted small">{{ detail.cloud_note }} {{ detail.desktop_note }}</p>
        </div>
        <div class="detail-section">
          <h4>落盘字段</h4>
          <p class="mono small">{{ detail.writes.join(' · ') || '—' }}</p>
        </div>
        <div class="detail-section">
          <h4>文件引用</h4>
          <p class="mono small" style="word-break: break-all">
            {{ [...detail.cloud_files, ...detail.desktop_files].join(' · ') || '—' }}
          </p>
        </div>
        <div class="detail-section">
          <h4>参考来源</h4>
          <p class="muted small">{{ detail.reference || '—' }}</p>
        </div>
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.skills-page { display: flex; flex-direction: column; gap: 14px; flex: 1; min-height: 0; }
.skills-stats { flex: none; grid-template-columns: repeat(5, minmax(0, 1fr)); }
.stat-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.stat-ico { width: 28px; height: 28px; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; background: rgba(0,0,0,.04); }
.stat-card.teal .stat-ico { color: var(--primary); background: var(--primary-bg); }
.stat-card.green .stat-ico { color: var(--green); background: var(--green-bg); }
.stat-card.orange .stat-ico { color: var(--orange); background: var(--orange-bg); }
.stat-card.purple .stat-ico { color: var(--purple); background: var(--purple-bg); }
.stat-card.blue .stat-ico { color: var(--blue); background: var(--blue-bg); }
.stat-card .stat-value { color: var(--text); }
.table-card { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; }
.table-card .table-wrap { flex: 1 1 auto; min-height: 0; }
.empty-card { flex: 1 1 auto; display: flex; align-items: center; justify-content: center; min-height: 0; }
.skill-name { font-weight: 600; }
.detail-grid { display: grid; gap: 14px; }
.detail-section h4 { margin: 0 0 5px; font-size: 12.5px; }
.detail-section p { margin: 0; line-height: 1.65; font-size: 12.5px; }
@media (max-width: 1100px) { .skills-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
</style>
