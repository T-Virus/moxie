<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { useJobQueue } from '../composables/useJobQueue'
import { jobFailed, jobStatus } from '../jobs'
import { state, store } from '../store'
import { toast } from '../ui'
import type { JobSummary } from '../types'
import Icon from './Icon.vue'

/* 全局任务速览：允许多个任务并发，这里列出所有在跑的任务与最近结果。
   队列数据与侧边栏角标、任务中心页共用 useJobQueue，不重复请求 /api/jobs。
   桌面可拖动（记住位置）、可收成角标；手机端固定为底栏上方的胶囊 + 圆角卡片。
   面板本身就是任务中心速览：行内只做展示，右侧「>」去任务中心看详情。 */
const { jobs, runningJobs } = useJobQueue()
/* 子进程任务（拆解 / 改编 / 图谱 / 批量扩写）：点进去看日志 */
const running = computed(() => runningJobs.value.filter(j => j.channel !== 'page'))
/* 页内任务（AI 审查 / 正文生成）：行内直接给「释放 / 停止」，不必先跳到页面找按钮 */
const pages = computed(() => runningJobs.value.filter(j => j.channel === 'page'))
const total = computed(() => running.value.length + pages.value.length)
const visible = computed(() => total.value > 0 || !!flash.value)

/* 刚结束的任务短暂展示结果（停止 / 释放不算成功，也不该显示成失败） */
const flash = ref<{ job: JobSummary; label: string; text: string; tone: string } | null>(null)
let flashTimer: any = null
const prev = new Map<string, JobSummary>()

/* ---------------- 折叠 / 拖动 / 位置记忆 ---------------- */
const POS_KEY = 'fw.taskfloater.pos'
const FOLD_KEY = 'fw.taskfloater.folded'

const rootEl = ref<HTMLElement | null>(null)
/* 手机端固定成一颗「任务 N」胶囊，不吃拖动位置，避免压住封面 / 正文 */
const isMobile = ref(typeof window !== 'undefined' && !!window.matchMedia
  && window.matchMedia('(max-width: 760px)').matches)
const folded = ref(localStorage.getItem(FOLD_KEY) === '1' || isMobile.value)
const pos = ref<{ x: number; y: number } | null>(isMobile.value ? null : readPos())

function readPos(): { x: number; y: number } | null {
  try {
    const raw = localStorage.getItem(POS_KEY)
    if (!raw) return null
    const p = JSON.parse(raw)
    return Number.isFinite(p?.x) && Number.isFinite(p?.y) ? { x: p.x, y: p.y } : null
  } catch { return null }
}

/* 没有记忆位置时贴右下角（默认位置用 CSS 的 right/bottom）；手机端始终贴底栏上方 */
const boxStyle = computed(() => (pos.value && !isMobile.value)
  ? { left: pos.value.x + 'px', top: pos.value.y + 'px', right: 'auto', bottom: 'auto' }
  : {})

/* 拖动：按下 → 移动超过 4px 才算拖，否则当成一次点击（折叠态轻点即展开） */
const DRAG_THRESHOLD = 4
let drag: { sx: number; sy: number; ox: number; oy: number; moved: boolean } | null = null

function clamp(x: number, y: number) {
  const el = rootEl.value
  const w = el?.offsetWidth || (folded.value ? 56 : 300)
  const h = el?.offsetHeight || (folded.value ? 56 : 90)
  return {
    x: Math.min(Math.max(4, x), Math.max(4, window.innerWidth - w - 4)),
    y: Math.min(Math.max(4, y), Math.max(4, window.innerHeight - h - 4)),
  }
}

function onDragStart(e: PointerEvent) {
  if (isMobile.value || e.button !== 0) return
  if ((e.target as HTMLElement)?.closest('.tf-fold, .tf-act, .tf-foot')) return
  const el = rootEl.value
  if (!el) return
  const r = el.getBoundingClientRect()
  drag = { sx: e.clientX, sy: e.clientY, ox: r.left, oy: r.top, moved: false }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd)
}

function onDragMove(e: PointerEvent) {
  if (!drag) return
  const dx = e.clientX - drag.sx
  const dy = e.clientY - drag.sy
  if (!drag.moved && Math.abs(dx) + Math.abs(dy) < DRAG_THRESHOLD) return
  drag.moved = true
  pos.value = clamp(drag.ox + dx, drag.oy + dy)
}

function onDragEnd() {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
  const moved = drag?.moved
  drag = null
  if (moved) {
    try { localStorage.setItem(POS_KEY, JSON.stringify(pos.value)) } catch { /* 隐私模式写不了就算了 */ }
  } else if (folded.value) {
    folded.value = false              // 折叠态轻点 = 展开
  }
}

watch(folded, async (v) => {
  try { localStorage.setItem(FOLD_KEY, v ? '1' : '0') } catch { /* 忽略 */ }
  await nextTick()
  // 展开后变宽，位置贴右边缘时往回收，避免一半跑到屏幕外
  if (pos.value && rootEl.value) pos.value = clamp(pos.value.x, pos.value.y)
})

/* 窗口变小：把面板拉回可视区 */
function onResize() { if (pos.value) pos.value = clamp(pos.value.x, pos.value.y) }
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
})

/* 行内展示：按任务阶段给图标 / 配色 / 状态文案，比统一的小圆点更好认 */
function stageIcon(j: JobSummary): string {
  if (j.stage === 'storymap') return 'graph'
  if (j.stage === 'review') return 'shield'
  if (j.stage === 'adapt') return 'movie'
  if (j.stage === 'decompose') return 'list'
  return 'pen'
}
function stageTone(j: JobSummary): string {
  if (j.stage === 'storymap') return 'purple'
  if (j.stage === 'review') return 'green'
  if (j.stage === 'adapt') return 'blue'
  if (j.stage === 'decompose') return 'gold'
  return 'blue'
}
function stageText(j: JobSummary): string {
  switch (j.stage) {
    case 'decompose': return '拆解中'
    case 'adapt': return '改编中'
    case 'storymap': return '生成图谱中'
    case 'review': return '正文审查中'
    default: return '正文生成中'
  }
}

/* 行内动作：审查「释放」（立刻解锁），正文生成「停止」（当前片段结束后退出） */
async function act(j: JobSummary) {
  try {
    if (j.stage === 'review') {
      await api.releaseReview(j.id)      // 只释放这一条，别的章还在审的任务不受影响
      toast('已释放审查：可以切章或发起别的任务了', 'ok')
    } else {
      await api.stopExpand(j.id)         // 只停这一条，别的章可以继续生成
      toast('已请求停止，当前片段结束后退出', 'ok')
    }
  } catch (e: any) { toast(e.message, 'err') }
}

/* 任务结束：只结算与「当前选中的书」相关的任务，避免并发任务互相抢选中 */
function settle(j: JobSummary) {
  if (j.channel === 'page') return     // 页内审查不产出书，不参与产出书结算
  const cur = store.curBook()
  if (!cur || (j.out_book !== cur && j.book !== cur)) return
  if (j.code === 0) store.selectOutputBook()
  else store.clearOutputBook()
}

/* 任务从「运行中」变为结束：提示结果并结算产出书（数据来自共享队列的轮询） */
watch(jobs, (list) => {
  for (const j of list) {
    const p = prev.get(j.id)
    if (p && p.running && !j.running) {
      flash.value = {
        job: j, label: j.label, text: jobStatus(j),
        tone: j.stopped ? 'mute' : (jobFailed(j) ? 'err' : 'ok'),
      }
      if (flashTimer) clearTimeout(flashTimer)
      flashTimer = setTimeout(() => { flash.value = null }, 5000)
      settle(j)
    }
  }
  prev.clear()
  for (const j of list) prev.set(j.id, j)
  /* 都跑完了还有待选中的产出书：补一次结算（覆盖「跑完才重新打开页面」） */
  if (!list.some(j => j.running) && state.outputBook) store.selectOutputBook()
})

onUnmounted(() => { if (flashTimer) clearTimeout(flashTimer) })
</script>

<template>
  <transition name="tf">
    <div v-if="visible" ref="rootEl" class="tf" :class="{ mini: folded, 'tf-mobile': isMobile }"
         :style="boxStyle">
      <!-- 收起态：桌面是一个角标图标（可拖动）；手机是贴底栏的「任务 N」胶囊 -->
      <button v-if="folded" class="tf-mini" :title="isMobile ? '任务进行中，点击查看' : '任务进行中，点击展开（可拖动）'"
              @pointerdown="onDragStart">
        <Icon name="tasks" :size="18" />
        <span v-if="isMobile && total" class="tf-mini-txt">任务 {{ total }}</span>
        <span v-if="total" class="tf-badge">{{ total }}</span>
        <span v-if="total && !isMobile" class="tf-ping"></span>
      </button>

      <template v-else>
        <div class="tf-head" title="拖动可移动面板" @pointerdown="onDragStart">
          <span class="tf-live" :class="{ off: !total }"></span>
          <b class="tf-title">{{ total ? '任务进行中' : '任务已结束' }}</b>
          <span v-if="total" class="tf-count">{{ total }}</span>
          <button class="tf-fold" title="收起" @click.stop="folded = true">
            <Icon name="close" :size="13" />
          </button>
        </div>
        <div v-if="total" class="tf-progress"><i></i></div>

        <div class="tf-list">
          <!-- 列表统一格式：任务标题 - 状态 - 日志行 -> 右侧「>」进任务中心 -->
          <div v-for="j in running" :key="j.id" class="tf-row">
            <span class="tf-ico" :class="'c-' + stageTone(j)">
              <Icon :name="stageIcon(j)" :size="14" />
            </span>
            <span class="tf-line">
              <b>{{ j.label }}</b>
              <i>·</i>
              <span>{{ stageText(j) }}</span>
              <i>·</i>
              <span>{{ j.total }} 行日志</span>
            </span>
            <RouterLink class="tf-go" to="/tasks" title="到任务中心查看">
              <Icon name="right" :size="13" />
            </RouterLink>
          </div>

          <div v-for="j in pages" :key="j.id" class="tf-row">
            <span class="tf-ico" :class="'c-' + stageTone(j)">
              <Icon :name="stageIcon(j)" :size="14" />
            </span>
            <span class="tf-line">
              <b>{{ j.label }}</b>
              <i>·</i>
              <span>{{ stageText(j) }}</span>
              <i>·</i>
              <span>{{ j.total }} 行日志</span>
            </span>
            <span class="tf-act" role="button" tabindex="0"
                  :title="j.stage === 'review' ? '立即释放：可切章 / 发起别的任务' : '停止正文生成'"
                  @click.stop="act(j)" @keydown.enter.stop="act(j)">{{ j.stage === 'review' ? '释放' : '停止' }}</span>
            <RouterLink class="tf-go" to="/tasks" title="到任务中心查看">
              <Icon name="right" :size="13" />
            </RouterLink>
          </div>

          <div v-if="flash" class="tf-row" :class="flash.tone">
            <span class="tf-ico" :class="flash.tone === 'err' ? 'c-red'
              : flash.tone === 'ok' ? 'c-green' : 'c-gray'">
              <Icon :name="flash.tone === 'err' ? 'close' : flash.tone === 'ok' ? 'check' : 'stop'" :size="14" />
            </span>
            <span class="tf-line">
              <b>{{ flash.label }}</b>
              <i>·</i>
              <span>{{ flash.text }}</span>
            </span>
            <RouterLink class="tf-go" to="/tasks" title="到任务中心查看">
              <Icon name="right" :size="13" />
            </RouterLink>
          </div>
        </div>
      </template>
    </div>
  </transition>
</template>

<style scoped>
/* 展开态：一张轻量的任务卡（头部状态 + 进度细线 + 任务行 + 底部入口） */
.tf {
  position: fixed; right: 20px; bottom: 20px; z-index: 90;
  width: min(340px, calc(100vw - 32px));
  display: flex; flex-direction: column;
  border-radius: 16px; overflow: hidden;
  background: var(--card); border: 1px solid var(--border);
  box-shadow: 0 18px 48px rgba(16, 32, 27, .18);
}
.tf-head {
  display: flex; align-items: center; gap: 9px;
  padding: 13px 14px 11px;
  background: linear-gradient(180deg, #f7faf8, #fff);
  cursor: grab; user-select: none;
}
.tf-head:active { cursor: grabbing; }
.tf-live {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: var(--primary); box-shadow: 0 0 0 4px var(--primary-bg);
  animation: tfPulse 1.4s infinite;
}
.tf-live.off { background: var(--text-3); box-shadow: none; animation: none; }
@keyframes tfPulse { 0%, 100% { opacity: 1 } 50% { opacity: .35 } }
.tf-title {
  min-width: 0; flex: 1; font-size: 13px; font-weight: 700;
  color: var(--text); letter-spacing: -.2px;
}
.tf-count {
  flex: none; min-width: 20px; height: 20px; padding: 0 6px; border-radius: 10px;
  background: var(--primary-bg); color: var(--primary);
  font-size: 11px; font-weight: 700; display: grid; place-items: center;
}
.tf-fold {
  flex: none; width: 24px; height: 24px; border: 0; border-radius: 7px;
  background: none; color: var(--text-3); cursor: pointer;
  display: grid; place-items: center;
}
.tf-fold:hover { background: var(--bg); color: var(--text); }
.tf-progress { flex: none; height: 2px; background: var(--border); overflow: hidden; }
.tf-progress i {
  display: block; width: 40%; height: 100%;
  background: linear-gradient(90deg, transparent, var(--primary), transparent);
  animation: tfSlide 1.6s ease-in-out infinite;
}
@keyframes tfSlide { 0% { transform: translateX(-100%) } 100% { transform: translateX(350%) } }
.tf-list {
  display: flex; flex-direction: column; gap: 2px;
  padding: 5px 6px; max-height: 44vh; overflow: auto;
}
/* 行只是展示，不整行可点；跳转统一走右侧「>」 */
.tf-row {
  display: flex; align-items: center; gap: 9px; width: 100%;
  padding: 8px; border: 0; border-radius: 11px; background: none;
  color: var(--text); text-align: left;
}
.tf-ico { width: 30px; height: 30px; flex: none; border-radius: 10px; display: grid; place-items: center; }
.tf-ico.c-blue { background: var(--primary-bg); color: var(--primary); }
.tf-ico.c-green { background: var(--green-bg, #e7f6ee); color: var(--green, #0ca678); }
.tf-ico.c-purple { background: rgba(140, 120, 255, .14); color: #7048e8; }
.tf-ico.c-gold { background: var(--orange-bg, #fff4e6); color: var(--orange, #e8590c); }
.tf-ico.c-red { background: var(--red-bg, #fff0f0); color: var(--red, #e03131); }
.tf-ico.c-gray { background: var(--bg); color: var(--text-3); }
/* 行内统一格式：标题 · 状态 · N 行日志，超出省略 */
.tf-line {
  flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 5px;
  white-space: nowrap; overflow: hidden; font-size: 11.5px; color: var(--text-3);
}
.tf-line b {
  min-width: 0; flex: 0 1 auto; overflow: hidden; text-overflow: ellipsis;
  font-size: 12.5px; font-weight: 600; color: var(--text);
}
.tf-line i { font-style: normal; opacity: .45; flex: none; }
.tf-line span { flex: none; }
.tf-go {
  flex: none; width: 24px; height: 24px; border-radius: 8px;
  display: grid; place-items: center; border: 0; background: none;
  color: var(--text-3); text-decoration: none; cursor: pointer;
}
.tf-go:hover { background: var(--primary-bg); color: var(--primary); }
.tf-act {
  flex: none; font-size: 11px; padding: 3px 8px; border-radius: 8px;
  border: 1px solid var(--border-strong); color: var(--text-2);
  background: var(--card); cursor: pointer;
}
.tf-act:hover { border-color: var(--red); color: var(--red); }
/* 收起态：一个小圆角图标，拖动 / 点击都直接作用在它身上 */
.tf.mini { width: auto; padding: 0; border: 0; background: transparent; box-shadow: none; overflow: visible; }
.tf-mini {
  position: relative; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center;
  border-radius: 50%; cursor: grab; color: var(--text-2);
  background: var(--card); border: 1px solid var(--border);
  box-shadow: 0 8px 22px rgba(16, 32, 27, .16);
}
.tf-mini:active { cursor: grabbing; }
.tf-mini:hover { color: var(--primary); border-color: var(--primary); }
.tf-badge {
  position: absolute; top: -4px; right: -4px; min-width: 17px; height: 17px; padding: 0 4px;
  border-radius: 9px; background: var(--orange); color: #fff; font-size: 11px; line-height: 17px;
  text-align: center; font-weight: 600;
}
.tf-ping {
  position: absolute; inset: -3px; border-radius: 50%; border: 1px solid var(--orange);
  opacity: .7; animation: tfping 1.6s ease-out infinite; pointer-events: none;
}
@keyframes tfping {
  0% { transform: scale(.9); opacity: .55; }
  100% { transform: scale(1.35); opacity: 0; }
}
.tf-mini-txt { font-size: 12px; font-weight: 650; letter-spacing: .2px; }

/* 手机端：收起态是「任务 N」胶囊，展开态是一张圆角卡片，都不再带脉冲外圈 */
@media (max-width: 760px) {
  .tf { right: 12px; bottom: calc(74px + env(safe-area-inset-bottom)); }
}
.tf.tf-mobile { right: 12px; bottom: calc(74px + env(safe-area-inset-bottom)); }
.tf.tf-mobile.mini { border-radius: 999px; }
.tf.tf-mobile .tf-mini {
  width: auto; min-width: 42px; height: 38px; padding: 0 13px; gap: 6px;
  border-radius: 999px; background: #fff;
  box-shadow: 0 6px 18px rgba(20, 30, 27, .16);
  color: var(--primary, #0f766e);
}
.tf.tf-mobile:not(.mini) { width: calc(100vw - 24px); }
/* 手机端按触控习惯放大可点区域（行、跳转、收起、行内动作都不小于 34px） */
.tf.tf-mobile .tf-head { padding: 14px 14px 12px; }
.tf.tf-mobile .tf-fold { width: 34px; height: 34px; border-radius: 10px; }
.tf.tf-mobile .tf-row { min-height: 50px; padding: 9px 10px; gap: 10px; }
.tf.tf-mobile .tf-line b { font-size: 13px; }
.tf.tf-mobile .tf-go { width: 34px; height: 34px; border-radius: 10px; }
.tf.tf-mobile .tf-act { padding: 6px 10px; font-size: 12px; border-radius: 9px; }
.tf.tf-mobile .tf-list { padding: 6px 8px 8px; }

.tf-enter-active, .tf-leave-active { transition: opacity .2s, transform .2s; }
.tf-enter-from, .tf-leave-to { opacity: 0; transform: translateY(8px); }
</style>
