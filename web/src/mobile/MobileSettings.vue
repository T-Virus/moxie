<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import Icon from '../components/Icon.vue'
import MobilePicker from './MobilePicker.vue'
import { api } from '../api'
import type { ModelProfile, PromptItem, ProviderPreset } from '../api'
import { state, store } from '../store'
import { confirmBox, passwordBox, toast, copyText as writeClipboard } from '../ui'

type ProfileRow = ModelProfile & { pid: string; key: string }

const tab = ref<'profiles' | 'bindings' | 'prompts' | 'data' | 'general'>('profiles')
const loading = ref(true)
const saving = ref(false)
const dirty = ref(false)
const editingPid = ref('')

const profiles = ref<ProfileRow[]>([])
const bindings = ref<Record<string, string>>({})
const stageLabel = ref<Record<string, string>>({})
const presets = ref<ProviderPreset[]>([])
const dailyGoal = ref(3000)
const memEnabled = ref(true)
const memTopK = ref(3)
const memMaxChars = ref(1600)
const priceIn = ref(2)
const priceOut = ref(8)
const key0 = ref(state.key)
const model0 = ref(state.model)
const baseUrl0 = ref(state.baseUrl)

const prompts = ref<PromptItem[]>([])
const promptOpen = ref('')
const promptDraft = ref('')
const promptSaving = ref(false)

const TABS = [
  { key: 'profiles', name: '模型档案' },
  { key: 'bindings', name: '工序绑定' },
  /* 提示词入口按需求屏蔽：后端 /api/prompts 保留，已有覆盖继续生效 */
  { key: 'data', name: '数据同步' },
  { key: 'general', name: '通用' },
] as const

async function load() {
  loading.value = true
  try {
    const d = await store.loadStudio()
    stageLabel.value = d.stage_label || {}
    presets.value = d.provider_presets || []
    profiles.value = Object.entries(d.profiles || {}).map(([pid, p]) => ({
      pid, name: p.name || '', provider: p.provider || '', base_url: p.base_url || '',
      model: p.model || '', temperature: p.temperature ?? null,
      price_in: p.price_in ?? 0, price_out: p.price_out ?? 0,
      key: store.profileKey(pid),
    }))
    bindings.value = { ...(d.bindings || {}) }
    dailyGoal.value = d.daily_goal ?? 3000
    memEnabled.value = d.memory?.enabled !== false
    memTopK.value = d.memory?.top_k ?? 3
    memMaxChars.value = d.memory?.max_chars ?? 1600
    priceIn.value = d.prices?.in ?? 2
    priceOut.value = d.prices?.out ?? 8
    key0.value = state.key
    model0.value = state.model
    baseUrl0.value = state.baseUrl
    dirty.value = false
  } catch (e: any) {
    toast('设置载入失败：' + (e.message || e), 'err')
  } finally {
    loading.value = false
  }
  api.getPrompts().then(r => { prompts.value = r.items || [] }).catch(() => {})
}
onMounted(load)

function touch() { dirty.value = true }

/* ---------------- 模型档案 ---------------- */
function addProfile() {
  const pid = 'p_' + Date.now().toString(36)
  profiles.value.push({
    pid, name: '', provider: '', base_url: '', model: '',
    temperature: null, price_in: 0, price_out: 0, key: '',
  })
  editingPid.value = pid
  tab.value = 'profiles'
  touch()
}
async function delProfile(row: ProfileRow) {
  const used = usesOf(row.pid)
  const name = row.name || '（未命名）'
  const msg = used.length
    ? `档案「${name}」正被 ${used.length} 道工序使用：${used.join('、')}。删除后会解除绑定。`
    : `确定删除档案「${name}」？`
  if (!await confirmBox(msg, { danger: true, ok: '删除' })) return
  profiles.value = profiles.value.filter(p => p.pid !== row.pid)
  for (const k of Object.keys(bindings.value)) {
    if (bindings.value[k] === row.pid) bindings.value[k] = ''
  }
  store.setProfileKey(row.pid, '')
  if (editingPid.value === row.pid) editingPid.value = ''
  touch()
}
function applyPreset(row: ProfileRow, provider: string) {
  const p = presets.value.find(x => x.provider === provider)
  if (!p) { row.provider = provider; return }
  row.provider = p.provider
  row.base_url = p.base_url
  row.model = p.models[0] || ''
  row.price_in = p.price_in
  row.price_out = p.price_out
  if (!row.name) row.name = p.provider
  touch()
}
function presetOf(row: ProfileRow): ProviderPreset | undefined {
  return presets.value.find(p => p.provider === row.provider)
}
/* 与桌面端同一套下拉：服务商预设 + 模型档案绑定都用 MobilePicker */
const providerOptions = computed(() => [
  { label: '自定义（不套用预设）', value: '' },
  ...presets.value.map(pr => ({ label: pr.provider, value: pr.provider })),
])
const bindingOptions = computed(() => [
  { label: '未绑定（用全局兜底）', value: '' },
  ...profiles.value.map(p => ({
    label: `${p.name || '（未命名）'} — ${p.model}${p.provider ? ' · ' + p.provider : ''}`,
    value: p.pid,
  })),
])
function modelOptions(row: ProfileRow): string[] {
  return presetOf(row)?.models || []
}

const stageUses = computed(() => {
  const m: Record<string, string[]> = {}
  for (const [k, pid] of Object.entries(bindings.value)) {
    if (!pid) continue
    ;(m[pid] || (m[pid] = [])).push(stageLabel.value[k] || k)
  }
  return m
})
function usesOf(pid: string): string[] {
  return stageUses.value[pid] || []
}
function profileOf(pid: string): ProfileRow | undefined {
  return profiles.value.find(p => p.pid === pid)
}
const boundCount = computed(() =>
  Object.values(bindings.value).filter(pid => pid && profileOf(pid)).length)
const stageKeys = computed(() => Object.keys(stageLabel.value))

/* ---------------- 保存 ---------------- */
async function save(silent = false) {
  for (const p of profiles.value) {
    if (!p.name.trim()) { toast('有档案没填名称', 'err'); tab.value = 'profiles'; return false }
    if (!p.model.trim()) { toast(`档案「${p.name}」没填模型`, 'err'); tab.value = 'profiles'; return false }
  }
  saving.value = true
  try {
    const rec: Record<string, ModelProfile> = {}
    for (const p of profiles.value) {
      rec[p.pid] = {
        name: p.name.trim(), provider: p.provider, base_url: p.base_url.trim(),
        model: p.model.trim(),
        temperature: (p.temperature === null || p.temperature === undefined || (p.temperature as any) === '')
          ? null : Number(p.temperature),
        price_in: Number(p.price_in) || 0, price_out: Number(p.price_out) || 0,
      }
      store.setProfileKey(p.pid, p.key)
    }
    const d = await store.loadStudio().catch(() => state.studio as any)
    const pids = new Set(profiles.value.map(p => p.pid))
    await store.saveStudio({
      ...(d || {}),
      profiles: rec,
      bindings: Object.fromEntries(Object.entries(bindings.value).filter(([, v]) => v && pids.has(v))),
      daily_goal: Math.max(0, Math.round(dailyGoal.value) || 0),
      memory: { enabled: memEnabled.value, top_k: memTopK.value, max_chars: memMaxChars.value },
      prices: { in: Number(priceIn.value) || 0, out: Number(priceOut.value) || 0 },
    })
    state.key = key0.value.trim()
    state.model = model0.value.trim()
    state.baseUrl = baseUrl0.value.trim()
    store.saveSettings()
    dirty.value = false
    if (!silent) toast('设置已保存', 'ok')
    return true
  } catch (e: any) {
    toast('保存失败：' + (e.message || e), 'err')
    return false
  } finally {
    saving.value = false
  }
}

onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  if (await confirmBox('设置尚未保存，仍要离开？', { danger: true, ok: '离开' })) return true
  return false
})

/* ---------------- 提示词 ---------------- */
function openPrompt(it: PromptItem) {
  if (promptOpen.value === it.key) { promptOpen.value = ''; return }
  promptOpen.value = it.key
  promptDraft.value = it.override || ''
}
async function savePrompt(it: PromptItem, reset = false) {
  promptSaving.value = true
  try {
    await api.putPrompt(it.key, reset ? '' : promptDraft.value)
    const r = await api.getPrompts()
    prompts.value = r.items || []
    if (reset) promptDraft.value = ''
    toast(reset ? '已恢复默认' : '覆盖已保存', 'ok')
  } catch (e: any) {
    toast('保存失败：' + (e.message || e), 'err')
  } finally {
    promptSaving.value = false
  }
}
async function copyPrompt(it: PromptItem) {
  const text = it.effective || it.default || ''
  if (!text) return toast('该提示词没有可复制的内容', 'err')
  const ok = await writeClipboard(text)
  toast(ok ? '已复制「' + it.label + '」' : '复制失败，请长按选择文本复制', ok ? 'ok' : 'err')
}
watch(tab, () => { if (tab.value === 'prompts') editingPid.value = '' })

/* ---------------- 数据同步（zip）：与桌面端同一套接口 ---------------- */
const syncBusy = ref(false)
const syncMsg = ref('')
const syncDetail = ref('')
const replaceFirst = ref(false)
const zipInput = ref<HTMLInputElement | null>(null)

async function exportZip() {
  if (syncBusy.value) return
  const pwd = await passwordBox('设置导出口令',
    '导出的作品数据会用这个口令加密。\n口令不会保存，忘记后这个导出包将无法恢复，请自行记牢。')
  if (!pwd) return
  syncBusy.value = true
  syncMsg.value = '正在打包作品数据…'
  syncDetail.value = ''
  try {
    const st = await api.dataSyncStatus().catch(() => null)
    if (st?.busy) {
      syncMsg.value = '暂时不能导出'
      syncDetail.value = '有任务正在运行，等任务结束后再导出。'
      toast(syncDetail.value, 'err')
      return
    }
    /* 口令先换一次性票据：下载地址里只出现票据，不出现口令 */
    const { ticket } = await api.prepareExport(pwd)
    /* App 内 WebView 不支持 blob 下载：直接跳转票据地址，由原生下载器存进「下载/墨写」 */
    if ((window as any).Native) {
      const a = document.createElement('a')
      a.href = '/api/data/export?ticket=' + encodeURIComponent(ticket)
      document.body.appendChild(a)
      a.click()
      a.remove()
      syncMsg.value = '已开始导出'
      syncDetail.value = '下载完成后在手机「下载 / 墨写」目录里取 .mwen 加密包；导入时需要同一口令。'
      toast('已开始导出，请稍候', 'ok')
      return
    }
    const blob = await api.exportDataZip(ticket)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'mowrite-data-' + new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '') + '.mwen'
    a.click()
    URL.revokeObjectURL(url)
    syncMsg.value = '已导出（加密包）'
    syncDetail.value = `${(blob.size / 1024 / 1024).toFixed(1)} MB · 含全部作品的设定、章节、正文与报告；导入时需要同一口令`
    toast('数据已导出', 'ok')
  } catch (e: any) {
    syncMsg.value = '导出失败'
    syncDetail.value = e?.message || String(e)
    toast('导出失败：' + syncDetail.value, 'err')
  } finally {
    syncBusy.value = false
  }
}

function pickZip() { zipInput.value?.click() }

/* 加密包头是 MWSEC1：读 base64 前 12 个字符即可判断 */
function isEncryptedB64(b64: string) {
  try { return atob(b64.slice(0, 12)).startsWith('MWSEC1') } catch { return false }
}

async function onZipFile(e: Event) {
  const el = e.target as HTMLInputElement
  const f = el.files?.[0]
  el.value = ''
  if (!f) return
  if (!/\.(zip|mwen)$/i.test(f.name)) { toast('请选择 .zip 或 .mwen 数据包', 'err'); return }
  if (f.size > 30 * 1024 * 1024) { toast('数据包过大（>30MB）：请先删掉不需要的作品再导出', 'err'); return }
  let b64 = ''
  try {
    b64 = await new Promise<string>((resolve, reject) => {
      const r = new FileReader()
      r.onload = () => resolve(String(r.result || '').split(',')[1] || '')
      r.onerror = () => reject(new Error('读取数据包失败'))
      r.readAsDataURL(f)
    })
  } catch (e: any) {
    toast(e?.message || '读取数据包失败', 'err')
    return
  }
  if (!b64) return
  let pwd = ''
  if (isEncryptedB64(b64)) {
    const v = await passwordBox('导入加密包',
      '这个数据包已加密，请输入导出时设置的口令。\n口令不正确将无法导入。')
    if (!v) return
    pwd = v
  }
  const mode = replaceFirst.value ? '「清空本地后完全对齐」' : '「同名作品整体覆盖」'
  if (!await confirmBox(`导入 ${f.name}？\n方式：${mode}`, { ok: '开始导入' })) return
  syncBusy.value = true
  syncMsg.value = '正在导入…'
  syncDetail.value = ''
  try {
    const res = await api.importDataZip(b64, replaceFirst.value, pwd)
    syncMsg.value = '导入完成'
    syncDetail.value = `作品 ${res.books?.length || 0} 部 · 文件 ${res.files || 0} 个 · ${((res.bytes || 0) / 1024 / 1024).toFixed(1)} MB`
      + (res.backup ? `；旧数据已备份到 ${res.backup}` : '')
    toast('数据已导入', 'ok')
    await store.loadStats().catch(() => {})
    window.dispatchEvent(new Event('mowrite:data-changed'))
  } catch (e: any) {
    syncMsg.value = '导入失败'
    syncDetail.value = e?.message || String(e)
    toast('导入失败：' + syncDetail.value, 'err')
  } finally {
    syncBusy.value = false
  }
}
</script>

<template>
  <div class="m-page m-secondary-page" :class="{ 'm-settings-page': tab !== 'prompts' && tab !== 'data' }">
    <div class="m-sec-head">
      <div class="m-sec-head-txt">模型档案、工序绑定与生成偏好</div>
      <div class="m-sec-head-act">
        <button class="m-icon-btn" title="刷新" @click="load"><Icon name="refresh" :size="18" /></button>
      </div>
    </div>

    <div class="m-chips" style="margin-bottom:12px">
      <button v-for="t in TABS" :key="t.key" class="m-chip" :class="{ on: tab === t.key }"
              @click="tab = t.key">{{ t.name }}</button>
    </div>

    <div v-if="loading" class="m-empty" style="padding-top:50px">
      <span class="m-empty-ico"><Icon name="settings" :size="26" /></span>
      <b>正在载入设置</b>
      <p>读取模型档案与工序绑定…</p>
    </div>

    <!-- 模型档案 -->
    <template v-else-if="tab === 'profiles'">
      <div class="m-settings-tip">
        <Icon name="shield" :size="15" />
        <span>API Key 只保存在这台手机，不上传服务端。成本统计按模型名归集。</span>
      </div>

      <div v-if="profiles.length" class="m-rows" style="margin-top:10px">
        <div v-for="p in profiles" :key="p.pid" class="m-profile-card" @input="touch" @change="touch">
          <button class="m-profile-head" @click="editingPid = editingPid === p.pid ? '' : p.pid">
            <span class="m-profile-avatar">{{ (p.name || p.provider || '模').slice(0, 1) }}</span>
            <span class="m-profile-title">
              <b>{{ p.name || '未命名档案' }}</b>
              <small>{{ p.provider || '自定义' }} · {{ p.model || '未设置模型' }}</small>
            </span>
            <span class="m-tag" :class="p.key ? 'green' : 'gold'">{{ p.key ? 'Key 已存' : '未设 Key' }}</span>
            <Icon :name="editingPid === p.pid ? 'down' : 'right'" :size="14" class="m-row-arrow" />
          </button>

          <div class="m-profile-meta">
            <span v-if="usesOf(p.pid).length" class="m-tag blue">{{ usesOf(p.pid).length }} 道工序</span>
            <span v-else class="m-tag gray">未绑定</span>
            <span v-if="usesOf(p.pid).length" class="m-profile-uses">
              {{ usesOf(p.pid).slice(0, 2).join('、') }}{{ usesOf(p.pid).length > 2 ? ' 等' : '' }}
            </span>
            <span class="m-spacer"></span>
            <button class="m-link" style="color:var(--m-red)" @click.stop="delProfile(p)">删除</button>
          </div>

          <div v-if="editingPid === p.pid" class="m-form" style="margin-top:12px">
            <div class="m-field">
              <label>档案名称</label>
              <input class="m-input" v-model="p.name" placeholder="如：DeepSeek 初稿" />
            </div>
            <div class="m-field">
              <label>服务商预设<em>自动带端点 / 模型 / 单价</em></label>
              <MobilePicker :model-value="p.provider" :options="providerOptions" title="选择服务商预设"
                            placeholder="自定义（不套用预设）"
                            @update:model-value="v => applyPreset(p, v)" />
              <p v-if="presetOf(p)?.note" class="m-hint">{{ presetOf(p)?.note }}</p>
            </div>
            <div class="m-field">
              <label>Base URL</label>
              <input class="m-input" v-model="p.base_url" placeholder="https://…" inputmode="url" />
            </div>
            <div class="m-field">
              <label>模型</label>
              <input class="m-input" v-model="p.model" :list="'models-' + p.pid" placeholder="模型名，可自定义" />
              <datalist :id="'models-' + p.pid">
                <option v-for="m in modelOptions(p)" :key="m" :value="m" />
              </datalist>
            </div>
            <div class="m-field">
              <label>API Key<em>仅存本机</em></label>
              <input class="m-input" type="password" v-model="p.key"
                     :placeholder="p.key ? '已保存，输入以更换' : 'sk-…'" />
            </div>
            <div class="m-form-2">
              <div class="m-field">
                <label>温度<em>留空用默认</em></label>
                <input class="m-input" type="number" step="0.1" min="0" max="2" v-model="p.temperature" />
              </div>
              <div class="m-field">
                <label>输入单价<em>元 / 百万 tokens</em></label>
                <input class="m-input" type="number" step="0.1" min="0" v-model="p.price_in" />
              </div>
            </div>
            <div class="m-field">
              <label>输出单价<em>元 / 百万 tokens</em></label>
              <input class="m-input" type="number" step="0.1" min="0" v-model="p.price_out" />
            </div>
          </div>
        </div>

        <button class="m-btn ghost block" @click="addProfile"><Icon name="plus" :size="15" /> 新建模型档案</button>

        <div class="m-card" style="margin-top:2px">
          <div class="m-card-head"><b>配置建议</b></div>
          <p class="m-hint">
            拆解 / 改编用长上下文强的模型；初稿用性价比高的；正文改写用文风顺的；审查用逻辑强的。
            每条档案填好端点、模型与单价后，到「工序绑定」指派具体工序。
          </p>
        </div>
      </div>

      <div v-else class="m-empty">
        <span class="m-empty-ico"><Icon name="settings" :size="28" /></span>
        <b>还没有模型档案</b>
        <p>为每家服务商建一条档案，再到「工序绑定」指派各道工序。</p>
        <button class="m-btn" @click="addProfile"><Icon name="plus" :size="15" /> 新建档案</button>
      </div>
    </template>

    <!-- 工序绑定 -->
    <template v-else-if="tab === 'bindings'">
      <div class="m-settings-tip">
        <Icon name="tasks" :size="15" />
        <span>已绑定 {{ boundCount }} / {{ stageKeys.length }} 道工序；未绑定的工序使用通用兜底凭据。</span>
      </div>

      <div class="m-rows" style="margin-top:10px">
        <div v-for="(label, key) in stageLabel" :key="key" class="m-bind-card">
          <div class="m-bind-head">
            <b>{{ label }}</b>
            <span class="m-tag" :class="bindings[key] ? 'green' : 'gray'">
              {{ bindings[key] ? '已绑定' : '未绑定' }}
            </span>
          </div>
          <MobilePicker v-model="bindings[key]" :options="bindingOptions" title="绑定模型档案"
                        allow-empty empty-label="未绑定（用全局兜底）" placeholder="选择模型档案"
                        @update:model-value="touch" />
          <p v-if="bindings[key] && profileOf(bindings[key])" class="m-hint">
            {{ profileOf(bindings[key])!.model }}
            · {{ profileOf(bindings[key])!.key ? 'Key 已配置' : '未配置 Key，调用会降级' }}
          </p>
          <p v-else-if="bindings[key]" class="m-hint" style="color:var(--m-red)">该档案已不存在，请重新选择</p>
          <p v-else class="m-hint">默认使用通用兜底凭据</p>
        </div>
        <p v-if="!profiles.length" class="m-hint" style="color:var(--m-red)">
          还没有档案可绑，先去「模型档案」建一条。
        </p>
      </div>
    </template>

    <!-- 提示词 -->
    <template v-else-if="tab === 'prompts'">
      <div class="m-settings-tip">
        <Icon name="file" :size="15" />
        <span>覆盖只保存在本机，随时可恢复默认。</span>
      </div>

      <div class="m-rows" style="margin-top:10px">
        <div v-for="it in prompts" :key="it.key" class="m-prompt-card">
          <div class="m-prompt-head">
            <button class="m-prompt-toggle" @click="openPrompt(it)">
              <span class="m-tag gray">{{ it.stage }}</span>
              <b>{{ it.label }}</b>
              <span v-if="it.overridden" class="m-tag gold">已覆盖</span>
              <span class="m-spacer"></span>
              <Icon :name="promptOpen === it.key ? 'down' : 'right'" :size="14" class="m-row-arrow" />
            </button>
            <button class="m-prompt-copy" title="复制生效提示词" @click="copyPrompt(it)">
              <Icon name="copy" :size="13" />
            </button>
          </div>
          <div v-if="promptOpen === it.key" class="m-prompt-body">
            <p v-if="it.note" class="m-hint">{{ it.note }}</p>
            <details v-if="it.default" class="m-prompt-default">
              <summary>查看内置默认（{{ it.default.length }} 字）</summary>
              <pre>{{ it.default }}</pre>
            </details>
            <template v-if="it.editable">
              <textarea class="m-textarea" rows="6" v-model="promptDraft"
                        placeholder="留空 = 使用内置默认；填入文本 = 覆盖默认"></textarea>
              <div class="m-prompt-acts">
                <button class="m-btn sm" :disabled="promptSaving" @click="savePrompt(it)">保存覆盖</button>
                <button class="m-btn sm ghost" :disabled="promptSaving || !it.overridden"
                        @click="savePrompt(it, true)">恢复默认</button>
              </div>
            </template>
            <p v-else class="m-hint">该条目只读。</p>
          </div>
        </div>
        <p v-if="!prompts.length" class="m-hint">暂无可编辑的提示词条目。</p>
      </div>
    </template>

    <!-- 数据同步 -->
    <template v-else-if="tab === 'data'">
      <div class="m-settings-tip">
        <Icon name="cloud" :size="15" />
        <span>用加密包在电脑与手机之间搬作品数据：导出时设口令，导入时输入同一口令；同名作品整体覆盖。</span>
      </div>

      <div class="m-card m-settings-section" style="margin-top:12px">
        <div class="m-card-head"><b>导出</b><span class="m-sub">加密打包全部作品</span></div>
        <p class="m-hint">包含全书设定、角色 / 势力 / 道具、章节数据、正文、审查报告、设定图谱与封面。口令请自行记牢，忘记后无法恢复。</p>
        <button class="m-btn block" style="margin-top:10px" :disabled="syncBusy" @click="exportZip">
          <Icon name="download" :size="15" /> {{ syncBusy ? '处理中…' : '导出并加密' }}
        </button>
      </div>

      <div class="m-card m-settings-section">
        <div class="m-card-head"><b>导入</b><span class="m-sub">覆盖同名作品</span></div>
        <p class="m-hint">
          选择另一端导出的 .mwen 加密包（旧版 zip 仍可导入）。勾选「完全对齐」会先清空本机作品再导入，旧数据自动备份为 data-backup-时间。
        </p>
        <button class="m-toggle-row" style="margin-top:8px" @click="replaceFirst = !replaceFirst">
          <span>
            <b>完全对齐</b>
            <small>{{ replaceFirst ? '会清空本机全部作品后再导入' : '仅覆盖 zip 里出现的同名作品' }}</small>
          </span>
          <i class="m-toggle" :class="{ on: replaceFirst }"><em></em></i>
        </button>
        <button class="m-btn ghost block" style="margin-top:10px" :disabled="syncBusy" @click="pickZip">
          <Icon name="upload" :size="15" /> {{ syncBusy ? '处理中…' : '选择数据包并导入' }}
        </button>
        <input ref="zipInput" type="file" accept=".mwen,.zip,application/zip,application/octet-stream"
               hidden @change="onZipFile" />
        <p v-if="syncMsg" class="m-hint" style="margin-top:10px">
          <b style="color:var(--m-text)">{{ syncMsg }}</b>
          <span v-if="syncDetail" style="display:block;margin-top:3px;word-break:break-all">{{ syncDetail }}</span>
        </p>
      </div>
    </template>

    <!-- 通用 -->
    <template v-else>
      <div class="m-card m-settings-section" @input="touch" @change="touch">
        <div class="m-card-head"><b>码字与记忆</b></div>
        <div class="m-form">
          <div class="m-field">
            <label>日更码字目标<em>字 / 天</em></label>
            <input class="m-input" type="number" min="0" step="500" v-model="dailyGoal" />
          </div>
          <div class="m-field">
            <label>跨章记忆</label>
            <button class="m-toggle-row" @click="memEnabled = !memEnabled; touch()">
              <span>
                <b>生成正文时注入前文记忆</b>
                <small>减少吃设定、忘伏笔，本地索引不消耗 Token</small>
              </span>
              <i class="m-toggle" :class="{ on: memEnabled }"><em></em></i>
            </button>
          </div>
          <div class="m-form-2">
            <div class="m-field">
              <label>检索章节数<em>top_k</em></label>
              <input class="m-input" type="number" min="1" max="8" v-model="memTopK" />
            </div>
            <div class="m-field">
              <label>记忆块长度<em>字</em></label>
              <input class="m-input" type="number" min="400" max="6000" step="200" v-model="memMaxChars" />
            </div>
          </div>
        </div>
      </div>

      <div class="m-card m-settings-section" @input="touch" @change="touch">
        <div class="m-card-head"><b>成本兜底单价</b><span class="m-sub">档案没填单价时使用</span></div>
        <div class="m-form-2">
          <div class="m-field">
            <label>输入<em>元 / 百万 tokens</em></label>
            <input class="m-input" type="number" step="0.1" min="0" v-model="priceIn" />
          </div>
          <div class="m-field">
            <label>输出<em>元 / 百万 tokens</em></label>
            <input class="m-input" type="number" step="0.1" min="0" v-model="priceOut" />
          </div>
        </div>
      </div>

      <div class="m-card m-settings-section" @input="touch" @change="touch">
        <div class="m-card-head"><b>全局兜底凭据</b><span class="m-sub">未绑定档案的工序使用</span></div>
        <div class="m-form">
          <div class="m-field">
            <label>API Key<em>仅存本机</em></label>
            <input class="m-input" type="password" v-model="key0" placeholder="sk-…" />
          </div>
          <div class="m-field">
            <label>模型<em>留空用服务端默认</em></label>
            <input class="m-input" v-model="model0" placeholder="deepseek-v4-flash" />
          </div>
          <div class="m-field">
            <label>Base URL<em>留空用官方地址</em></label>
            <input class="m-input" v-model="baseUrl0" placeholder="https://api.deepseek.com" inputmode="url" />
          </div>
        </div>
      </div>

    </template>

    <Transition name="m-save">
      <div v-if="tab !== 'prompts' && tab !== 'data' && !loading" class="m-settings-savebar">
        <span v-if="dirty" class="m-tag gold">有未保存修改</span>
        <span v-else class="m-hint">修改后点击保存</span>
        <span class="m-spacer"></span>
        <button class="m-btn" :disabled="saving" @click="save()">
          <Icon name="check" :size="15" /> {{ saving ? '保存中…' : '保存设置' }}
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.m-spacer { flex: 1; }
.m-settings-page { padding-bottom: calc(96px + env(safe-area-inset-bottom)) !important; }
.m-settings-tip {
  display: flex; gap: 8px; align-items: flex-start;
  padding: 11px 13px; border-radius: 14px;
  background: var(--m-primary-soft); color: var(--m-primary);
  font-size: 11.5px; line-height: 1.55;
}
.m-settings-section + .m-settings-section { margin-top: 12px; }
.m-profile-card, .m-bind-card, .m-prompt-card {
  padding: 13px 14px; background: #fff;
  border: 1px solid var(--m-line); border-radius: 17px;
  box-shadow: 0 1px 2px rgba(20, 30, 27, .03);
}
.m-profile-head {
  display: flex; align-items: center; gap: 10px; width: 100%; padding: 0;
  border: 0; background: none; text-align: left; color: var(--m-text);
}
.m-profile-avatar {
  width: 38px; height: 38px; flex: none; border-radius: 12px;
  display: grid; place-items: center;
  background: linear-gradient(140deg, #eaf4f0, #f7f1e4);
  color: var(--m-primary); font-size: 16px; font-weight: 700;
}
.m-profile-title { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.m-profile-title b { font-size: 14px; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.m-profile-title small { font-size: 10.5px; color: var(--m-text3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.m-profile-meta { display: flex; align-items: center; gap: 7px; margin-top: 9px; }
.m-profile-uses { font-size: 10.5px; color: var(--m-text3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.m-bind-head { display: flex; align-items: center; gap: 8px; margin-bottom: 9px; }
.m-bind-head b { flex: 1; font-size: 13.5px; font-weight: 600; }
.m-prompt-head {
  display: flex; align-items: center; gap: 8px; width: 100%;
}
.m-prompt-toggle {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: 7px; padding: 0;
  border: 0; background: none; color: var(--m-text); text-align: left;
}
.m-prompt-toggle b { font-size: 13.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.m-prompt-copy {
  width: 32px; height: 32px; flex: none; border: 0; border-radius: 9px;
  background: #f4f6f2; color: var(--m-text2);
  display: grid; place-items: center;
}
.m-prompt-copy:active { background: var(--m-primary-soft); color: var(--m-primary); }
.m-prompt-body { margin-top: 11px; padding-top: 11px; border-top: 1px solid #f2f4f0; }
.m-prompt-default { margin: 8px 0; }
.m-prompt-default summary { font-size: 11.5px; color: var(--m-primary); }
.m-prompt-default pre {
  max-height: 180px; overflow: auto; margin: 8px 0 0; padding: 10px;
  border-radius: 10px; background: #f7f9f5; font-size: 11px; line-height: 1.65;
  white-space: pre-wrap; color: var(--m-text2);
}
.m-prompt-acts { display: flex; gap: 8px; margin-top: 9px; }
.m-toggle-row {
  display: flex; align-items: center; gap: 10px; width: 100%; padding: 11px 12px;
  border: 1px solid var(--m-line); border-radius: 13px; background: #fafbf8;
  text-align: left; color: var(--m-text);
}
.m-toggle-row > span { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.m-toggle-row b { font-size: 12.5px; font-weight: 600; }
.m-toggle-row small { font-size: 10.5px; line-height: 1.5; color: var(--m-text3); }
.m-toggle {
  width: 42px; height: 25px; flex: none; border-radius: 13px;
  background: #d9ded8; position: relative; transition: background .18s;
}
.m-toggle em {
  position: absolute; top: 3px; left: 3px; width: 19px; height: 19px;
  border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, .2);
  transition: transform .18s;
}
.m-toggle.on { background: var(--m-primary); }
.m-toggle.on em { transform: translateX(17px); }
.m-settings-savebar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 46;
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, .96);
  -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);
  border-top: 1px solid var(--m-line);
  box-shadow: 0 -10px 28px rgba(20, 30, 27, .06);
}
.m-settings-savebar .m-btn { height: 42px; padding: 0 16px; }
.m-save-enter-active, .m-save-leave-active { transition: opacity .18s, transform .18s; }
.m-save-enter-from, .m-save-leave-to { opacity: 0; transform: translateY(8px); }
</style>
