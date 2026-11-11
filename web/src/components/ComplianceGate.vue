<script setup lang="ts">
/* 创作合规确认（拆解 / 改编前必过）
   版权与平台规则是本产品最大的商业风险：这里把「权利来源 + 权利确认 + AI 使用知情」
   做成一次显式确认，提交给服务端留痕；不勾选就不能开跑。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from './Icon.vue'

const props = withDefaults(defineProps<{
  stage?: 'decompose' | 'adapt'
  source?: string
  outBook?: string
}>(), { stage: 'decompose', source: '', outBook: '' })

type Ack = {
  basis: 'own' | 'authorized' | 'public'
  rights_confirmed: boolean
  ai_notice_ack: boolean
  note: string
}

const open = ref(false)
const basis = ref<Ack['basis']>('own')
const rights = ref(false)
const aiAck = ref(false)
const note = ref('')
let resolver: ((v: Ack | null) => void) | null = null

const BASES: { key: Ack['basis']; label: string; desc: string }[] = [
  { key: 'own', label: '自有作品', desc: '本人创作，或已取得完整著作权' },
  { key: 'authorized', label: '已获授权', desc: '有书面授权 / 合同，允许改编' },
  { key: 'public', label: '公有领域', desc: '作者逝世满 50 年等可自由改编' },
]

function ask(): Promise<Ack | null> {
  basis.value = 'own'
  rights.value = false
  aiAck.value = false
  note.value = ''
  open.value = true
  return new Promise(resolve => { resolver = resolve })
}
defineExpose({ ask })

function close(v: Ack | null) {
  open.value = false
  if (resolver) { resolver(v); resolver = null }
}
function confirm() {
  if (!rights.value || !aiAck.value) return
  close({ basis: basis.value, rights_confirmed: true, ai_notice_ack: true, note: note.value.trim() })
}
function onKey(e: KeyboardEvent) {
  if (open.value && e.key === 'Escape') close(null)
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  if (resolver) { resolver(null); resolver = null }
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="cg-mask" @click.self="close(null)">
      <div class="cg-card" role="dialog" aria-modal="true" aria-label="创作合规确认">
        <div class="cg-head">
          <span class="cg-ico"><Icon name="shield" :size="18" /></span>
          <div>
            <b>创作合规确认</b>
            <p>{{ stage === 'adapt' ? '改编前' : '拆解前' }}请确认作品权利来源与 AI 使用方式</p>
          </div>
          <button class="cg-x" title="取消" @click="close(null)"><Icon name="close" :size="16" /></button>
        </div>

        <div class="cg-body">
          <div class="cg-note">
            <p><b>只处理你有权使用的作品。</b>拆解与改编会读取源作品的结构与情节；未经授权的改编可能构成侵权，风险由使用者承担。</p>
            <p><b>AI 是辅助，不是代写。</b>产出的内容必须人工改写，并按发布平台要求披露 AI 参与程度；本工具不提供绕过平台检测的功能。</p>
            <p v-if="source" class="cg-src">本次素材：{{ source }}<span v-if="outBook"> → 《{{ outBook }}》</span></p>
          </div>

          <div class="cg-field">
            <label>作品权利来源</label>
            <div class="cg-bases">
              <button v-for="b in BASES" :key="b.key" type="button" class="cg-base"
                      :class="{ on: basis === b.key }" @click="basis = b.key">
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
            <span>我知悉产出为 AI 辅助内容，会进行人工改写并按平台要求披露，不将本工具用于洗稿、抄袭或绕过检测。</span>
          </label>

          <div class="cg-field">
            <label>授权凭证 / 备注（选填）</label>
            <input v-model="note" class="cg-input" maxlength="200"
                   placeholder="如：合同编号、授权方、公版依据，便于日后追溯" />
          </div>
        </div>

        <div class="cg-foot">
          <span class="cg-hint">确认记录仅保存在本机 data/_system/compliance.jsonl</span>
          <button class="cg-btn ghost" type="button" @click="close(null)">取消</button>
          <button class="cg-btn" type="button" :disabled="!rights || !aiAck" @click="confirm">
            确认并继续
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.cg-mask {
  position: fixed; inset: 0; z-index: 3000; background: rgba(18, 28, 23, .45);
  display: flex; align-items: center; justify-content: center; padding: 20px;
  backdrop-filter: blur(2px);
}
.cg-card {
  width: min(560px, 100%); max-height: 90vh; overflow: auto;
  background: var(--card, #fff); color: var(--text, #1f2329);
  border-radius: 16px; box-shadow: 0 24px 70px rgba(15, 30, 22, .28);
  display: flex; flex-direction: column;
}
.cg-head { display: flex; align-items: flex-start; gap: 10px; padding: 18px 18px 12px; border-bottom: 1px solid var(--border, #edf0ec); }
.cg-ico { width: 36px; height: 36px; flex: none; border-radius: 10px; display: grid; place-items: center;
  background: var(--primary-bg, #e7f4f0); color: var(--primary, #0f766e); }
.cg-head b { display: block; font-size: 16px; }
.cg-head p { margin-top: 3px; font-size: 12px; color: var(--text-3, #8f959e); }
.cg-x { margin-left: auto; border: 0; background: none; color: var(--text-3, #8f959e); cursor: pointer; padding: 4px; }
.cg-body { padding: 14px 18px; display: flex; flex-direction: column; gap: 12px; }
.cg-note { background: var(--bg, #f7f9f6); border-radius: 10px; padding: 11px 12px; font-size: 12px; line-height: 1.7; color: var(--text-2, #4e5969); }
.cg-note p + p { margin-top: 6px; }
.cg-note b { color: var(--text, #1f2329); }
.cg-src { font-size: 11.5px; color: var(--text-3, #8f959e); word-break: break-all; }
.cg-field > label { display: block; font-size: 12px; font-weight: 650; margin-bottom: 6px; }
.cg-bases { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.cg-base {
  text-align: left; border: 1px solid var(--border, #e5e7eb); background: var(--panel, #fff);
  border-radius: 9px; padding: 8px 10px; cursor: pointer; color: var(--text, #1f2329);
}
.cg-base b { display: block; font-size: 12.5px; }
.cg-base small { display: block; margin-top: 3px; font-size: 10.5px; line-height: 1.45; color: var(--text-3, #8f959e); }
.cg-base.on { border-color: var(--primary, #0f766e); background: var(--primary-bg, #e7f4f0); }
.cg-check { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; line-height: 1.6; color: var(--text-2, #4e5969); cursor: pointer; }
.cg-check input { margin-top: 3px; flex: none; accent-color: var(--primary, #0f766e); }
.cg-input { width: 100%; border: 1px solid var(--border, #e5e7eb); border-radius: 8px; padding: 8px 10px; font-size: 12px; outline: none; background: var(--panel, #fff); color: var(--text, #1f2329); }
.cg-input:focus { border-color: var(--primary, #0f766e); }
.cg-foot { display: flex; align-items: center; gap: 8px; padding: 12px 18px 16px; border-top: 1px solid var(--border, #edf0ec); }
.cg-hint { flex: 1; min-width: 0; font-size: 10.5px; color: var(--text-3, #8f959e); }
.cg-btn { border: 1px solid var(--primary, #0f766e); background: var(--primary, #0f766e); color: #fff;
  border-radius: 8px; padding: 8px 16px; font-size: 13px; cursor: pointer; }
.cg-btn:disabled { opacity: .45; cursor: not-allowed; }
.cg-btn.ghost { background: none; border-color: var(--border, #e5e7eb); color: var(--text-3, #8f959e); }

@media (max-width: 620px) {
  .cg-mask { padding: 0; align-items: flex-end; }
  .cg-card { width: 100%; max-height: 92vh; border-radius: 18px 18px 0 0; }
  .cg-bases { grid-template-columns: 1fr; }
  .cg-base { padding: 10px 12px; }
  .cg-btn { padding: 10px 18px; font-size: 14px; }
  .cg-hint { display: none; }
}
</style>
