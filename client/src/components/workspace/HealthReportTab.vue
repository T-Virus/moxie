<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { getHealthReport } from '@/services/agentApi'
import type { AgentRunHealthReport, ReviewRisk, RunDetail } from '@/types'

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

/* ---- 四维连续性核查 ------------------------------------------------------
 * continuity_check.json 的 checks 是结构化对象
 * （dimension/item/status/evidence/source）；旧数据可能是纯字符串，
 * 这里统一归一化后渲染，避免把对象直接 String() 成 [object Object]。
 */
interface ContinuityCheck {
  dimension: string
  item: string
  status: string
  evidence: string
}

const DIMENSION_LABELS: Record<string, string> = {
  character: '人物',
  foreshadow: '伏笔',
  timeline: '时间线',
  setting: '设定',
}

function dimensionLabel(value: string): string {
  return DIMENSION_LABELS[value] || value || '综合'
}

function statusMeta(status: string): { label: string; cls: string } {
  const key = String(status || '').toLowerCase()
  if (key === 'conflict') return { label: '冲突', cls: 'badge--danger' }
  if (key === 'pass') return { label: '通过', cls: 'badge--success' }
  if (key === 'unknown') return { label: '待确认', cls: 'badge--warn' }
  return { label: key || '待确认', cls: '' }
}

function normalizeCheck(raw: unknown): ContinuityCheck {
  if (typeof raw === 'string') {
    return { dimension: '', item: raw, status: '', evidence: '' }
  }
  const row = (raw || {}) as Record<string, unknown>
  const pick = (key: string): string =>
    typeof row[key] === 'string' ? (row[key] as string) : row[key] == null ? '' : String(row[key])
  return {
    dimension: pick('dimension'),
    item: pick('item') || pick('subject') || pick('message'),
    status: pick('status'),
    evidence: pick('evidence') || pick('detail'),
  }
}

const coverPlanText = computed<string>(() => {
  const plan = report.value?.cover_plan as { plan?: unknown } | null | undefined
  if (!plan) return ''
  try {
    return JSON.stringify(plan.plan ?? plan, null, 2)
  } catch {
    return ''
  }
})

// ---------- 评分环 ----------
const scoreValue = computed(() => {
  const raw = report.value?.review.score
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return 0
  return Math.max(0, Math.min(100, Math.round(raw)))
})
const scoreTone = computed<'good' | 'warn' | 'bad'>(() =>
  scoreValue.value >= 80 ? 'good' : scoreValue.value >= 60 ? 'warn' : 'bad',
)
const scoreVerdict = computed(() => {
  if (scoreValue.value >= 90) return '整体质量优秀，各维度表现稳定'
  if (scoreValue.value >= 80) return '整体质量良好，少量细节可继续优化'
  if (scoreValue.value >= 60) return '存在需要关注的问题，建议按下列建议修订'
  return '问题较多，建议先处理风险项再进入后续流程'
})
const ringStyle = computed(() => ({ '--hr-pct': String(scoreValue.value) }))

// ---------- 风险分级 ----------
interface RiskLevelMeta {
  key: 'high' | 'medium' | 'low'
  label: string
  cls: string
}
function riskMeta(level: string): RiskLevelMeta {
  const key = String(level || '').toLowerCase()
  if (key === 'high') return { key: 'high', label: '高危', cls: 'badge--danger' }
  if (key === 'medium') return { key: 'medium', label: '中等', cls: 'badge--warn' }
  if (key === 'low') return { key: 'low', label: '低', cls: 'badge--success' }
  return { key: 'low', label: key || '提示', cls: '' }
}
function riskKey(risk: ReviewRisk): 'high' | 'medium' | 'low' {
  return riskMeta(risk.level).key
}
const riskCounts = computed(() => {
  const risks = report.value?.review.risks ?? []
  return {
    high: risks.filter((r) => riskKey(r) === 'high').length,
    medium: risks.filter((r) => riskKey(r) === 'medium').length,
    low: risks.filter((r) => riskKey(r) === 'low').length,
  }
})

const continuityChecks = computed<ContinuityCheck[]>(() => {
  const raw = (report.value?.continuity || {}).checks
  if (!Array.isArray(raw)) return []
  return raw.map(normalizeCheck).filter((item) => item.item || item.evidence)
})
const continuityConflicts = computed(
  () => continuityChecks.value.filter((item) => item.status.toLowerCase() === 'conflict').length,
)

onMounted(() => void load())
watch(() => props.run?.run_id, () => void load())
</script>

<template>
  <section class="health-report">
    <div v-if="loading" class="hr-state">
      <span class="hr-state__spinner" aria-hidden="true" />
      <p>正在生成体检报告…</p>
    </div>
    <div v-else-if="error" class="alert" role="alert">{{ error }}</div>
    <div v-else-if="!report" class="hr-state">
      <span class="hr-state__icon" aria-hidden="true">✦</span>
      <p>暂无体检报告</p>
    </div>

    <template v-else>
      <!-- 评分概览 -->
      <header class="hr-hero" :class="`hr-hero--${scoreTone}`">
        <div class="hr-hero__ring-wrap">
          <div class="hr-ring" :style="ringStyle">
            <div class="hr-ring__inner">
              <strong>{{ scoreValue }}</strong>
              <span>综合评分</span>
            </div>
          </div>
        </div>
        <div class="hr-hero__main">
          <div class="hr-hero__eyebrow">CONTENT HEALTH REPORT</div>
          <h2>{{ report.title || '未命名作品' }} · 体检报告</h2>
          <p class="hr-hero__verdict">{{ scoreVerdict }}</p>
          <span class="badge" :class="report.review.high_risk ? 'badge--danger' : 'badge--success'">
            <span class="hr-dot" aria-hidden="true" />
            {{ report.review.high_risk ? '存在高危问题' : '未发现高危问题' }}
          </span>
        </div>
      </header>

      <!-- 关键指标 -->
      <div class="hr-stats">
        <div class="hr-stat">
          <span class="hr-stat__value">{{ report.summary.chapters_count }}</span>
          <span class="hr-stat__label">章节数</span>
        </div>
        <div class="hr-stat">
          <span class="hr-stat__value">{{ report.summary.word_count }}</span>
          <span class="hr-stat__label">总字数</span>
        </div>
        <div class="hr-stat">
          <span class="hr-stat__value">{{ report.summary.checks_count }}</span>
          <span class="hr-stat__label">一致性检查</span>
        </div>
        <div class="hr-stat">
          <span class="hr-stat__value">{{ report.summary.conflict_count ?? 0 }}</span>
          <span class="hr-stat__label">冲突项</span>
        </div>
        <div class="hr-stat" :class="{ 'is-alert': riskCounts.high > 0 }">
          <span class="hr-stat__value">{{ (report.review.risks ?? []).length }}</span>
          <span class="hr-stat__label">风险项</span>
        </div>
      </div>

      <!-- 风险项 -->
      <section v-if="report.review.risks?.length" class="hr-card">
        <header class="hr-card__head">
          <span class="hr-card__bar hr-card__bar--danger" aria-hidden="true" />
          <h3>风险项</h3>
          <span class="hr-card__count">{{ report.review.risks.length }}</span>
          <div class="hr-card__legend">
            <span v-if="riskCounts.high"><i class="hr-legend-dot hr-legend-dot--high" />高危 {{ riskCounts.high }}</span>
            <span v-if="riskCounts.medium"><i class="hr-legend-dot hr-legend-dot--medium" />中等 {{ riskCounts.medium }}</span>
            <span v-if="riskCounts.low"><i class="hr-legend-dot hr-legend-dot--low" />低 {{ riskCounts.low }}</span>
          </div>
        </header>
        <ul class="hr-risks">
          <li
            v-for="(risk, index) in report.review.risks"
            :key="index"
            class="hr-risk"
            :class="`hr-risk--${riskKey(risk)}`"
          >
            <span class="badge hr-risk__level" :class="riskMeta(risk.level).cls">
              {{ riskMeta(risk.level).label }}
            </span>
            <div class="hr-risk__body">
              <p class="hr-risk__msg">{{ risk.message }}</p>
              <div class="hr-risk__meta">
                <span v-if="risk.chapter" class="hr-chip">第 {{ risk.chapter }} 章</span>
                <code v-if="risk.code" class="hr-code">{{ risk.code }}</code>
              </div>
            </div>
          </li>
        </ul>
      </section>

      <!-- 修改建议 -->
      <section v-if="report.review.suggestions?.length" class="hr-card">
        <header class="hr-card__head">
          <span class="hr-card__bar hr-card__bar--brand" aria-hidden="true" />
          <h3>修改建议</h3>
          <span class="hr-card__count">{{ report.review.suggestions.length }}</span>
        </header>
        <ol class="hr-numbered">
          <li v-for="(item, index) in report.review.suggestions" :key="index">
            <span class="hr-numbered__no">{{ index + 1 }}</span>
            <span class="hr-numbered__text">{{ item }}</span>
          </li>
        </ol>
      </section>

      <!-- 一致性问题 -->
      <section v-if="report.review.consistency_issues?.length" class="hr-card">
        <header class="hr-card__head">
          <span class="hr-card__bar hr-card__bar--warn" aria-hidden="true" />
          <h3>一致性问题</h3>
          <span class="hr-card__count">{{ report.review.consistency_issues.length }}</span>
        </header>
        <ul class="hr-numbered hr-numbered--plain">
          <li v-for="(item, index) in report.review.consistency_issues" :key="index">
            <span class="hr-numbered__no hr-numbered__no--warn">{{ index + 1 }}</span>
            <span class="hr-numbered__text">{{ item }}</span>
          </li>
        </ul>
      </section>

      <!-- 四维连续性核查 -->
      <section v-if="continuityChecks.length" class="hr-card">
        <header class="hr-card__head">
          <span class="hr-card__bar hr-card__bar--violet" aria-hidden="true" />
          <h3>四维连续性核查</h3>
          <span class="hr-card__count">{{ continuityChecks.length }}</span>
          <span v-if="continuityConflicts" class="badge badge--danger">冲突 {{ continuityConflicts }}</span>
        </header>
        <ul class="hr-checks">
          <li
            v-for="(item, index) in continuityChecks"
            :key="index"
            class="hr-check"
            :class="{ 'is-conflict': item.status.toLowerCase() === 'conflict' }"
          >
            <span class="hr-numbered__no hr-numbered__no--violet">{{ index + 1 }}</span>
            <div class="hr-check__body">
              <div class="hr-check__top">
                <span class="hr-check__dim">{{ dimensionLabel(item.dimension) }}</span>
                <span class="hr-check__item">{{ item.item || '未命名检查项' }}</span>
                <span class="badge hr-check__status" :class="statusMeta(item.status).cls">
                  {{ statusMeta(item.status).label }}
                </span>
              </div>
              <p v-if="item.evidence" class="hr-check__evidence">{{ item.evidence }}</p>
            </div>
          </li>
        </ul>
      </section>

      <!-- 章节概览 -->
      <section v-if="report.chapters.length" class="hr-card">
        <header class="hr-card__head">
          <span class="hr-card__bar hr-card__bar--brand" aria-hidden="true" />
          <h3>章节概览</h3>
          <span class="hr-card__count">{{ report.chapters.length }}</span>
        </header>
        <div class="hr-chapters">
          <div v-for="chapter in report.chapters" :key="chapter.chapter || 0" class="hr-chapter">
            <span class="hr-chapter__no">{{ chapter.chapter ?? '—' }}</span>
            <span class="hr-chapter__title">{{ chapter.title || '未命名' }}</span>
            <span class="hr-chapter__words">{{ chapter.word_count }} 字</span>
          </div>
        </div>
      </section>

      <!-- 缺失交付物 -->
      <div v-if="report.missing_artifacts.length" class="hr-missing">
        <span class="hr-missing__icon" aria-hidden="true">!</span>
        <div>
          <strong>部分交付物尚未生成</strong>
          <p>{{ report.missing_artifacts.join('、') }}</p>
        </div>
      </div>

      <!-- 封面方案 -->
      <section v-if="report.cover_plan" class="hr-card">
        <header class="hr-card__head">
          <span class="hr-card__bar hr-card__bar--violet" aria-hidden="true" />
          <h3>封面方案</h3>
        </header>
        <pre class="hr-code-block">{{ coverPlanText }}</pre>
      </section>
    </template>
  </section>
</template>

<style scoped>
.health-report {
  padding: var(--space-5) var(--space-6) var(--space-8);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ---------- 加载 / 空态 ---------- */
.hr-state {
  min-height: 320px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--color-text-3);
  font-size: var(--text-sm);
}
.hr-state__icon {
  font-size: 32px;
  color: var(--color-line-strong);
}
.hr-state__spinner {
  width: 28px;
  height: 28px;
  border: 3px solid var(--color-line);
  border-top-color: var(--color-brand);
  border-radius: 50%;
  animation: hr-spin 0.8s linear infinite;
}
@keyframes hr-spin {
  to { transform: rotate(360deg); }
}

/* ---------- 评分概览 ---------- */
.hr-hero {
  --hr-tone: var(--color-success);
  --hr-tone-soft: var(--color-success-soft);
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-6);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-lg);
  background:
    linear-gradient(120deg, var(--hr-tone-soft) 0%, var(--color-bg) 62%);
  box-shadow: var(--shadow-sm);
}
.hr-hero--warn {
  --hr-tone: var(--color-warn);
  --hr-tone-soft: var(--color-warn-soft);
}
.hr-hero--bad {
  --hr-tone: var(--color-danger);
  --hr-tone-soft: var(--color-danger-soft);
}
.hr-hero__ring-wrap {
  flex: none;
}
.hr-ring {
  width: 108px;
  height: 108px;
  border-radius: 50%;
  padding: 9px;
  background: conic-gradient(
    var(--hr-tone) calc(var(--hr-pct) * 1%),
    var(--hr-tone-soft) 0
  );
  box-shadow: 0 4px 16px -8px var(--hr-tone);
}
.hr-ring__inner {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: var(--color-bg);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
}
.hr-ring__inner strong {
  font-family: var(--font-mono);
  font-size: var(--text-2xl);
  line-height: 1;
  color: var(--hr-tone);
}
.hr-ring__inner span {
  font-size: 12px;
  color: var(--color-text-3);
}
.hr-hero__main {
  min-width: 0;
}
.hr-hero__eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--hr-tone);
  margin-bottom: 6px;
}
.hr-hero__main h2 {
  margin: 0;
  font-size: var(--text-xl);
  line-height: 1.3;
  color: var(--color-text);
}
.hr-hero__verdict {
  margin: 8px 0 12px;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}
.hr-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

/* ---------- 指标条 ---------- */
.hr-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 1px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-line);
  overflow: hidden;
}
.hr-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--space-4) var(--space-2);
  background: var(--color-bg-softer);
}
.hr-stat__value {
  font-family: var(--font-mono);
  font-size: 22px;
  font-weight: 600;
  line-height: 1.1;
  color: var(--color-text);
}
.hr-stat.is-alert .hr-stat__value {
  color: var(--color-danger);
}
.hr-stat__label {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

/* ---------- 分区卡片 ---------- */
.hr-card {
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  overflow: hidden;
}
.hr-card__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px var(--space-4);
  background: var(--color-bg-softer);
  border-bottom: 1px solid var(--color-line);
}
.hr-card__bar {
  width: 3px;
  height: 15px;
  border-radius: 2px;
  flex: none;
  background: var(--color-brand);
}
.hr-card__bar--danger { background: var(--color-danger); }
.hr-card__bar--warn { background: var(--color-warn); }
.hr-card__bar--violet { background: var(--color-accent); }
.hr-card__head h3 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
}
.hr-card__count {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-3);
  background: var(--color-bg-soft);
  border-radius: var(--radius-pill);
  padding: 1px 8px;
}
.hr-card__legend {
  margin-left: auto;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}
.hr-card__legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.hr-legend-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}
.hr-legend-dot--high { background: var(--color-danger); }
.hr-legend-dot--medium { background: var(--color-warn); }
.hr-legend-dot--low { background: var(--color-success); }

/* ---------- 风险项 ---------- */
.hr-risks {
  list-style: none;
  margin: 0;
  padding: var(--space-2) var(--space-4);
}
.hr-risk {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 11px 0;
  border-bottom: 1px dashed var(--color-line);
}
.hr-risk:last-child {
  border-bottom: none;
}
.hr-risk__level {
  flex: none;
  min-width: 48px;
}
.hr-risk__body {
  min-width: 0;
  flex: 1;
}
.hr-risk__msg {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-2);
}
.hr-risk__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.hr-chip,
.hr-code {
  font-size: 12px;
}
.hr-chip {
  color: var(--color-text-3);
  background: var(--color-bg-soft);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
}
.hr-code {
  font-family: var(--font-mono);
  color: var(--color-text-3);
}

/* ---------- 编号列表 ---------- */
.hr-numbered {
  list-style: none;
  margin: 0;
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hr-numbered li {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.hr-numbered__no {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: #e6f6f4;
  color: var(--color-brand);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
}
.hr-numbered__no--warn {
  background: var(--color-warn-soft);
  color: var(--color-warn);
}
.hr-numbered__no--violet {
  background: #f2ebff;
  color: var(--color-accent);
}
.hr-numbered__text {
  font-size: var(--text-sm);
  line-height: 1.75;
  color: var(--color-text-2);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* ---------- 连续性核查 ---------- */
.hr-checks {
  list-style: none;
  margin: 0;
  padding: var(--space-2) var(--space-4);
  display: flex;
  flex-direction: column;
}
.hr-check {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 11px 0;
  border-bottom: 1px dashed var(--color-line);
}
.hr-check:last-child {
  border-bottom: none;
}
.hr-check__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.hr-check__top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.hr-check__dim {
  flex: none;
  font-size: 12px;
  color: var(--color-accent);
  background: #f2ebff;
  border-radius: var(--radius-sm);
  padding: 2px 8px;
}
.hr-check__item {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow-wrap: anywhere;
}
.hr-check__status {
  flex: none;
}
.hr-check__evidence {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-3);
  overflow-wrap: anywhere;
}

/* ---------- 章节概览 ---------- */
.hr-chapters {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
  padding: var(--space-4);
}
.hr-chapter {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-sm);
  background: var(--color-bg-softer);
  min-width: 0;
}
.hr-chapter__no {
  flex: none;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-brand);
  background: #e6f6f4;
  border-radius: var(--radius-sm);
  padding: 2px 6px;
}
.hr-chapter__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}
.hr-chapter__words {
  flex: none;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-text-3);
}

/* ---------- 缺失交付物 ---------- */
.hr-missing {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px var(--space-4);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-bg-softer);
}
.hr-missing__icon {
  flex: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--color-warn-soft);
  color: var(--color-warn);
  font-size: 12px;
  font-weight: 700;
}
.hr-missing strong {
  font-size: var(--text-sm);
  color: var(--color-text-2);
}
.hr-missing p {
  margin: 4px 0 0;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}
.hr-code-block {
  margin: 0;
  padding: var(--space-4);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--color-text-2);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 640px) {
  .health-report {
    padding: var(--space-4);
  }
  .hr-hero {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-4);
  }
  .hr-card__legend {
    width: 100%;
    margin-left: 0;
  }
}
</style>
