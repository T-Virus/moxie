<template>
  <main class="page skills">
    <header class="skills__head">
      <h1 class="page-title">创作技能</h1>
      <p class="skills__lead">
        从选题到封面，完整创作链路的加工能力。技能的可用状态与说明由服务端统一维护，
        在这里查看每一项能做什么、从哪里进入。
      </p>
      <p v-if="catalog.degraded" class="skills__degraded" role="status">
        目录数据暂不可用（{{ catalog.degraded }}），以下为降级展示。
      </p>
    </header>

    <div v-if="loading" class="skills__loading" role="status">正在加载技能目录…</div>
    <div v-else-if="loadError" class="skills__error" role="alert">
      <span>{{ loadError }}</span>
      <button type="button" class="btn btn--sm" @click="load">重试</button>
    </div>

    <ol v-else class="skills__list">
      <li
        v-for="item in catalog.items"
        :key="item.id"
        class="card skill"
        :class="{ 'skill--off': !item.available }"
      >
        <div class="skill__index" aria-hidden="true">{{ String(item.index).padStart(2, '0') }}</div>
        <div class="skill__body">
          <div class="skill__title-row">
            <h2 class="skill__title">{{ item.name }}</h2>
            <span class="skill__badge" :class="`skill__badge--${item.coverage}`">
              {{ coverageLabel(item.coverage) }}
            </span>
          </div>
          <p class="skill__purpose">{{ item.purpose }}</p>
          <div class="skill__meta">
            <div v-if="item.trigger.length" class="skill__triggers">
              <span v-for="t in item.trigger" :key="t" class="skill__tag">{{ t }}</span>
            </div>
            <div v-if="item.entry.api.length" class="skill__entries">
              <span class="skill__entries-label">入口</span>
              <code v-for="api in item.entry.api" :key="api" class="skill__code">{{ api }}</code>
            </div>
          </div>
        </div>
      </li>
    </ol>

    <footer v-if="!loading && !loadError" class="skills__foot">
      <span v-if="catalog.updated_at">目录版本 {{ catalog.schema_version || '—' }} · 更新于 {{ catalog.updated_at }}</span>
      <span v-else>目录版本 {{ catalog.schema_version || '—' }}</span>
    </footer>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { fetchSkills } from '@/services/agentApi'
import { ApiError } from '@/services/http'
import type { SkillCoverage, SkillsCatalog } from '@/types'

const catalog = reactive<SkillsCatalog>({ items: [], degraded: null, schema_version: null, updated_at: null })
const loading = ref(true)
const loadError = ref('')

const COVERAGE_LABEL: Record<SkillCoverage, string> = {
  full: '完整可用',
  partial: '部分可用',
  cloud_gap: '云端完善中',
}

function coverageLabel(coverage: SkillCoverage): string {
  return COVERAGE_LABEL[coverage] || coverage
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchSkills()
    catalog.items = data.items
    catalog.degraded = data.degraded
    catalog.schema_version = data.schema_version
    catalog.updated_at = data.updated_at
  } catch (err) {
    catalog.items = []
    loadError.value = err instanceof ApiError ? err.message : '暂时无法获取技能目录'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.skills {
  max-width: 960px;
  margin: 0 auto;
  padding: 32px 20px 64px;
}
.skills__head {
  margin-bottom: 28px;
}
.skills__lead {
  margin: 10px 0 0;
  color: var(--muted, #667085);
  line-height: 1.7;
  max-width: 720px;
}
.skills__degraded {
  margin: 12px 0 0;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(234, 179, 8, 0.12);
  color: var(--warn, #b45309);
  font-size: 13px;
}
.skills__loading,
.skills__error {
  padding: 40px;
  text-align: center;
  color: var(--muted, #667085);
}
.skills__error {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: center;
}
.skills__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 14px;
  counter-reset: skill;
}
.skill {
  display: flex;
  gap: 18px;
  padding: 20px;
  align-items: flex-start;
}
.skill--off {
  opacity: 0.82;
}
.skill__index {
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 18px;
  font-weight: 700;
  background: var(--accent-soft, rgba(79, 70, 229, 0.1));
  color: var(--accent, #4f46e5);
}
.skill__body {
  flex: 1 1 auto;
  min-width: 0;
}
.skill__title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.skill__title {
  margin: 0;
  font-size: 17px;
}
.skill__badge {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--badge-bg, #eef2ff);
  color: var(--badge-fg, #4338ca);
}
.skill__badge--partial {
  background: rgba(234, 179, 8, 0.16);
  color: var(--warn, #b45309);
}
.skill__badge--cloud_gap {
  background: rgba(148, 163, 184, 0.2);
  color: var(--muted, #64748b);
}
.skill__purpose {
  margin: 8px 0 0;
  line-height: 1.65;
  color: var(--text, #1f2937);
}
.skill__meta {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.skill__triggers {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.skill__tag {
  font-size: 12px;
  padding: 2px 8px;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  color: var(--muted, #64748b);
}
.skill__entries {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.skill__entries-label {
  font-size: 12px;
  color: var(--muted, #64748b);
}
.skill__code {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--code-bg, #f3f4f6);
  color: var(--code-fg, #374151);
}
.skills__foot {
  margin-top: 24px;
  text-align: center;
  font-size: 12px;
  color: var(--muted, #94a3b8);
}
</style>
