<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { getHealthReport } from '@/services/agentApi'
import type { AgentRunHealthReport, RunDetail } from '@/types'

const props = defineProps<{ run: RunDetail | null }>()
const report = ref<AgentRunHealthReport | null>(null)
const loading = ref(false)
const error = ref('')

async function load(): Promise<void> {
  if (!props.run?.run_id) return
  loading.value = true
  error.value = ''
  try {
    report.value = await getHealthReport(props.run.run_id)
  } catch (e) {
    report.value = null
    error.value = e instanceof Error ? e.message : '体检报告加载失败'
  } finally {
    loading.value = false
  }
}

function list(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item))
  return []
}

const coverPlanText = computed<string>(() => {
  const plan = report.value?.cover_plan as { plan?: unknown } | null | undefined
  if (!plan) return ''
  try {
    return JSON.stringify(plan.plan ?? plan)
  } catch {
    return ''
  }
})

onMounted(() => void load())
watch(() => props.run?.run_id, () => void load())
</script>

<template>
  <section class="health-report">
    <div v-if="loading" class="muted">正在生成体检报告…</div>
    <div v-else-if="error" class="alert" role="alert">{{ error }}</div>
    <div v-else-if="!report" class="muted">暂无体检报告。</div>

    <template v-else>
      <header class="health-report__head">
        <div>
          <h3>{{ report.title || '未命名作品' }} · 体检报告</h3>
          <p class="muted">
            {{ report.summary.chapters_count }} 章 / {{ report.summary.word_count }} 字 ·
            一致性检查 {{ report.summary.checks_count }} 项 · 冲突 {{ report.summary.conflict_count }}
          </p>
        </div>
        <span class="badge" :class="report.review.high_risk ? 'danger' : 'ok'">
          {{ report.review.high_risk ? '存在高危问题' : '未发现高危问题' }}
        </span>
      </header>

      <div v-if="typeof report.review.score === 'number'" class="health-report__score">
        <span>综合评分</span>
        <strong>{{ report.review.score }}</strong>
      </div>

      <div v-if="report.review.risks?.length" class="health-report__section">
        <h4>风险项</h4>
        <ul>
          <li v-for="(risk, index) in report.review.risks" :key="index">
            <span class="badge" :class="risk.level === 'high' ? 'danger' : 'warn'">{{ risk.level }}</span>
            {{ risk.message }}
            <span v-if="risk.chapter" class="muted">（第 {{ risk.chapter }} 章）</span>
          </li>
        </ul>
      </div>

      <div v-if="report.review.suggestions?.length" class="health-report__section">
        <h4>修改建议</h4>
        <ol>
          <li v-for="(item, index) in report.review.suggestions" :key="index">{{ item }}</li>
        </ol>
      </div>

      <div v-if="report.review.consistency_issues?.length" class="health-report__section">
        <h4>一致性问题</h4>
        <ul>
          <li v-for="(item, index) in report.review.consistency_issues" :key="index">{{ item }}</li>
        </ul>
      </div>

      <div v-if="list((report.continuity || {}).checks).length" class="health-report__section">
        <h4>四维连续性核查</h4>
        <ul>
          <li v-for="(item, index) in list((report.continuity || {}).checks)" :key="index">
            {{ typeof item === 'string' ? item : JSON.stringify(item) }}
          </li>
        </ul>
      </div>

      <div v-if="report.chapters.length" class="health-report__section">
        <h4>章节概览</h4>
        <div class="health-report__chapters">
          <span v-for="chapter in report.chapters" :key="chapter.chapter || 0">
            第 {{ chapter.chapter }} 章 · {{ chapter.title || '未命名' }} · {{ chapter.word_count }} 字
          </span>
        </div>
      </div>

      <div v-if="report.missing_artifacts.length" class="health-report__section muted">
        尚未生成：{{ report.missing_artifacts.join('、') }}
      </div>

      <div v-if="report.cover_plan" class="health-report__section">
        <h4>封面方案</h4>
        <p class="muted">{{ coverPlanText }}</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.health-report__head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}
.health-report__head h3 {
  margin: 0 0 6px;
}
.health-report__score {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}
.health-report__score strong {
  font-size: 32px;
}
.health-report__section {
  margin: 16px 0;
}
.health-report__section h4 {
  margin: 0 0 8px;
}
.health-report__section ul,
.health-report__section ol {
  margin: 0;
  padding-left: 20px;
}
.health-report__chapters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.health-report__chapters span {
  border: 1px solid var(--border, #ddd);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
}
</style>
