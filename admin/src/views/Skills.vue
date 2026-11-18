<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { AdminSkillItem, SkillCoverage, SkillsCatalog } from '../types'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
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
</script>

<template>
  <PageHeader
    title="技能目录"
    desc="创作全链路的 10 个技能项由服务端统一清单维护；此处核对覆盖状态、缺口与实际注册情况，三端共用同一份数据。"
  >
    <span v-if="!canRead" class="badge muted">只读</span>
    <button class="btn ghost sm" :disabled="loading || !canRead" @click="load">
      <Icon name="refresh" :size="14" />刷新
    </button>
  </PageHeader>

  <div v-if="meta.degraded" class="card" style="margin-bottom: 16px">
    <span class="badge warn">降级</span>
    <span style="margin-left: 8px">{{ meta.degraded }}</span>
  </div>

  <div class="summary-grid">
    <div class="card summary">
      <div class="summary__num">{{ rows.length }}</div>
      <div class="summary__label">技能项</div>
    </div>
    <div class="card summary">
      <div class="summary__num">{{ coverageCounts.full }}</div>
      <div class="summary__label">完整可用</div>
    </div>
    <div class="card summary">
      <div class="summary__num">{{ coverageCounts.partial }}</div>
      <div class="summary__label">部分可用</div>
    </div>
    <div class="card summary">
      <div class="summary__num">{{ coverageCounts.cloud_gap }}</div>
      <div class="summary__label">云端完善中</div>
    </div>
    <div class="card summary">
      <div class="summary__num">{{ rows.filter(r => r.registered).length }}</div>
      <div class="summary__label">云端已注册</div>
    </div>
  </div>

  <div class="card">
    <div v-if="loading && !rows.length" class="state-loading">
      <StateBlock kind="loading" title="正在加载技能目录…" />
    </div>
    <div v-else-if="error">
      <StateBlock kind="error" :title="error" retry-label="重试" @retry="load" />
    </div>
    <div v-else-if="!rows.length">
      <StateBlock kind="empty" title="暂无技能目录" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 48px">#</th>
              <th>技能项</th>
              <th>覆盖状态</th>
              <th>云端注册</th>
              <th>入口 / 工序</th>
              <th style="width: 90px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td class="mono muted">{{ String(row.index).padStart(2, '0') }}</td>
              <td>
                <div>{{ row.name }}</div>
                <div class="muted" style="font-size: 11.5px">{{ row.id }} · {{ row.external || '—' }}</div>
              </td>
              <td>
                <StatusBadge :value="row.coverage" :label="COVERAGE[row.coverage] || row.coverage" />
              </td>
              <td>
                <span class="badge" :class="row.registered ? '' : 'muted'">
                  {{ row.registered ? '已注册' : '未注册' }}
                </span>
              </td>
              <td>
                <div class="mono" style="font-size: 12px">
                  {{ row.entry.stages.join(' / ') || '—' }}
                </div>
                <div class="muted" style="font-size: 11.5px">
                  {{ row.entry.api.join(' · ') || (row.entry.cloud_skills.join(' · ') || '无入口') }}
                </div>
              </td>
              <td>
                <button class="btn ghost sm" @click="openDetail(row)">详情</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-foot muted" style="font-size: 12px">
        目录版本 {{ meta.schema_version || '—' }} · 更新于 {{ meta.updated_at || '—' }}
      </div>
    </template>
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
          <p class="muted" style="font-size: 12px">{{ detail.cloud_note }} {{ detail.desktop_note }}</p>
        </div>
        <div class="detail-section">
          <h4>落盘字段</h4>
          <p class="mono" style="font-size: 12px">{{ detail.writes.join(' · ') || '—' }}</p>
        </div>
        <div class="detail-section">
          <h4>文件引用</h4>
          <p class="mono" style="font-size: 12px; word-break: break-all">
            {{ [...detail.cloud_files, ...detail.desktop_files].join(' · ') || '—' }}
          </p>
        </div>
        <div class="detail-section">
          <h4>参考来源</h4>
          <p class="muted" style="font-size: 12px">{{ detail.reference || '—' }}</p>
        </div>
      </div>
  </Modal>
</template>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.summary {
  padding: 16px 18px;
  text-align: center;
}
.summary__num {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
}
.summary__label {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted, #64748b);
}
.table-wrap {
  overflow-x: auto;
}
.table-foot {
  padding: 12px 16px;
  border-top: 1px solid var(--border, #e5e7eb);
}
.detail-grid {
  display: grid;
  gap: 16px;
}
.detail-section h4 {
  margin: 0 0 6px;
  font-size: 13px;
}
.detail-section p {
  margin: 0;
  line-height: 1.6;
  font-size: 13.5px;
}
</style>
