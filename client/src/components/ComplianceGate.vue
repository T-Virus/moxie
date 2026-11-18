<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div v-if="open" class="dialog__mask" @click.self="cancel">
        <div class="dialog" role="dialog" aria-modal="true" aria-label="创作合规确认">
          <header class="dialog__head">
            <h2 class="dialog__title">创作合规确认</h2>
            <button ref="closeBtn" type="button" class="dialog__close" aria-label="关闭弹窗" @click="cancel">
              <svg viewBox="0 0 14 14" aria-hidden="true">
                <path d="M3 3l8 8M11 3l-8 8" fill="none" stroke="currentColor" stroke-width="1.4" />
              </svg>
            </button>
          </header>

          <div class="dialog__body">
            <p class="cg-lead">参考改编前，请确认作品权利来源与 AI 使用方式。</p>

            <div class="cg-note">
              <p><b>只处理你有权使用的作品。</b>改编会读取源作品的结构与情节，未经授权的改编可能构成侵权，风险由使用者承担。</p>
              <p><b>AI 是辅助，不是代写。</b>产出内容须人工改写，并按发布平台要求披露 AI 参与程度。</p>
              <p v-if="source" class="cg-src">本次素材：{{ source }}</p>
            </div>

            <div class="cg-field">
              <div class="cg-label-row">
                <label class="cg-label">作品权利来源</label>
                <span v-if="basis !== 'own'" class="cg-remember">已记住上次选择，可点击更改</span>
              </div>
              <div class="cg-bases" role="radiogroup" aria-label="作品权利来源">
                <button
                  v-for="b in BASES"
                  :key="b.key"
                  type="button"
                  class="cg-base"
                  :class="{ 'is-on': basis === b.key }"
                  :aria-pressed="basis === b.key"
                  @click="basis = b.key"
                >
                  <b>{{ b.label }}</b>
                  <small>{{ b.desc }}</small>
                </button>
              </div>
            </div>

            <label class="cg-check">
              <input v-model="rights" type="checkbox" />
              <span>我确认对该作品拥有著作权、已获得改编授权，或该作品属于公有领域；如有争议由我自行承担。</span>
            </label>
            <label class="cg-check">
              <input v-model="aiAck" type="checkbox" />
              <span>我知悉产出为 AI 辅助内容，会人工改写并按平台要求披露，不用于洗稿、抄袭或绕过检测。</span>
            </label>

            <div class="cg-field">
              <label class="cg-label" for="cg-note">授权凭证 / 备注（选填）</label>
              <input
                id="cg-note"
                v-model="note"
                class="cg-input"
                type="text"
                maxlength="300"
                placeholder="如：合同编号、授权方、公版依据，便于日后追溯"
              />
            </div>
          </div>

          <footer class="dialog__footer">
            <span class="cg-hint">确认将被加密记录，用于合规审计</span>
            <button type="button" class="btn btn--ghost" @click="cancel">取消</button>
            <button type="button" class="btn btn--primary" :disabled="!canConfirm" @click="confirm">
              确认并继续
            </button>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { lockPageScroll, unlockPageScroll } from '@/utils/scrollLock'
import {
  buildRightsDeclaration,
  canConfirmRights,
  readRememberedBasis,
  rememberBasis,
  RIGHTS_BASES,
} from '@/utils/rightsDeclaration'
import type { RightsDeclaration } from '@/types'

withDefaults(defineProps<{ source?: string }>(), { source: '' })

type Basis = RightsDeclaration['basis']
type Ack = RightsDeclaration

const BASES = RIGHTS_BASES

const open = ref(false)
const basis = ref<Basis>('own')
const rights = ref(false)
const aiAck = ref(false)
const note = ref('')
const closeBtn = ref<HTMLButtonElement | null>(null)
const canConfirm = computed(() => canConfirmRights(rights.value, aiAck.value))

let resolver: ((v: Ack | null) => void) | null = null
let pageLocked = false

/** 打开合规确认弹窗；用户确认返回声明，取消返回 null。 */
function ask(): Promise<Ack | null> {
  // 权利来源记住上次确认值；两个合规勾选与备注每次必须重新填写/确认，绝不预填
  basis.value = readRememberedBasis()
  rights.value = false
  aiAck.value = false
  note.value = ''
  open.value = true
  return new Promise((resolve) => {
    resolver = resolve
  })
}

function settle(v: Ack | null): void {
  open.value = false
  if (resolver) {
    resolver(v)
    resolver = null
  }
}

function cancel(): void {
  settle(null)
}

function confirm(): void {
  const declaration = buildRightsDeclaration({
    basis: basis.value,
    rightsConfirmed: rights.value,
    aiNoticeAck: aiAck.value,
    note: note.value,
  })
  if (!declaration) return
  rememberBasis(declaration.basis)
  settle(declaration)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && open.value) cancel()
}

watch(open, async (isOpen) => {
  if (isOpen && !pageLocked) {
    pageLocked = true
    lockPageScroll()
    await nextTick()
    closeBtn.value?.focus()
  } else if (!isOpen && pageLocked) {
    pageLocked = false
    unlockPageScroll()
  }
})

window.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (pageLocked) unlockPageScroll()
  // 组件卸载时释放等待中的 Promise，避免调用方永久挂起
  if (resolver) {
    resolver(null)
    resolver = null
  }
})

defineExpose({ ask })
</script>

<style scoped>
.dialog__mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
  overflow: hidden;
  overscroll-behavior: contain;
  background: rgba(9, 16, 24, 0.45);
  backdrop-filter: blur(3px);
}

.dialog {
  width: 100%;
  max-width: 560px;
  max-height: calc(100dvh - 48px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--color-line);
}

.dialog__head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6) var(--space-3);
}

.dialog__title {
  font-size: var(--text-md);
  font-weight: 700;
}

.dialog__close {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: var(--color-text-3);
  cursor: pointer;
}

.dialog__close:hover {
  background: var(--color-bg-soft);
  color: var(--color-text);
}

.dialog__close svg {
  width: 12px;
  height: 12px;
}

.dialog__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 var(--space-6) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.dialog__footer {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--color-line);
  background: var(--color-bg-softer);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
}

.cg-lead {
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.cg-note {
  background: var(--color-bg-soft);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--color-text-2);
}

.cg-note p + p {
  margin-top: var(--space-2);
}

.cg-note b {
  color: var(--color-text);
}

.cg-src {
  font-size: var(--text-xs);
  color: var(--color-text-3);
  word-break: break-all;
}

.cg-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.cg-label {
  font-size: var(--text-sm);
  font-weight: 650;
}

.cg-label-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}

.cg-remember {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-3);
}

.cg-bases {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
}

.cg-base {
  text-align: left;
  border: 1px solid var(--color-line);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  color: var(--color-text);
}

.cg-base b {
  display: block;
  font-size: var(--text-sm);
}

.cg-base small {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--color-text-3);
}

.cg-base.is-on {
  border-color: var(--color-brand);
  background: var(--color-success-soft);
}

.cg-check {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--color-text-2);
  cursor: pointer;
}

.cg-check input {
  margin-top: 3px;
  flex: none;
  accent-color: var(--color-brand);
}

.cg-input {
  width: 100%;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  outline: none;
  background: var(--color-surface);
  color: var(--color-text);
}

.cg-input:focus {
  border-color: var(--color-brand);
}

.cg-hint {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: var(--color-text-3);
}

.dialog-enter-active,
.dialog-leave-active {
  transition: opacity var(--dur) var(--ease);
}

.dialog-enter-active .dialog,
.dialog-leave-active .dialog {
  transition: transform var(--dur) var(--ease);
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}

.dialog-enter-from .dialog,
.dialog-leave-to .dialog {
  transform: translateY(10px) scale(0.98);
}

@media (max-width: 620px) {
  .dialog__mask {
    padding: 0;
    align-items: flex-end;
  }

  .dialog {
    max-width: 100%;
    max-height: 92dvh;
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  }

  .cg-bases {
    grid-template-columns: 1fr;
  }

  .cg-hint {
    display: none;
  }
}
</style>
