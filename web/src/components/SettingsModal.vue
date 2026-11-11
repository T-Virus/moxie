<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import Modal from './Modal.vue'
import SelectBox from './SelectBox.vue'
import Icon from './Icon.vue'
import { ui, toast, confirmBox, passwordBox, copyText as writeClipboard } from '../ui'
import { state, store } from '../store'
import { api } from '../api'
import type { ModelProfile, PromptItem, ProviderPreset } from '../api'

type ProfileRow = ModelProfile & { pid: string; key: string }

const tab = ref<'profiles' | 'bindings' | 'prompts' | 'data' | 'general'>('profiles')
const loading = ref(false)
const saving = ref(false)

/* ---- 草稿：打开时从服务端载入，保存时整体写回 ---- */
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
/* 旧版「临时全局凭据」：没给工序绑档案时的兜底（保持向后兼容） */
const key0 = ref(state.key)
const model0 = ref(state.model)
const baseUrl0 = ref(state.baseUrl)

/* ---- 提示词库 ---- */
const prompts = ref<PromptItem[]>([])
const promptOpen = ref('')
const promptDraft = ref('')
const promptSaving = ref(false)

const editingPid = ref('')   // 正在编辑哪条档案（空 = 都不展开）

watch(() => ui.settingsOpen, async v => { if (v) await load() })

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
      key: store.profileKey(pid),   // Key 只从本机 localStorage 读，永不来自服务端
    }))
    bindings.value = { ...(d.bindings || {}) }
    dailyGoal.value = d.daily_goal ?? 3000
    memEnabled.value = d.memory?.enabled !== false
    memTopK.value = d.memory?.top_k ?? 3
    memMaxChars.value = d.memory?.max_chars ?? 1600
    priceIn.value = d.prices?.in ?? 2
    priceOut.value = d.prices?.out ?? 8
  } catch (e: any) {
    toast('设置载入失败：' + (e.message || e), 'err')
  } finally {
    loading.value = false
  }
  api.getPrompts().then(r => { prompts.value = r.items || [] }).catch(() => {})
}

/* ---- 档案操作 ---- */
function addProfile() {
  const pid = 'p_' + Date.now().toString(36)
  profiles.value.push({
    pid, name: '', provider: '', base_url: '', model: '',
    temperature: null, price_in: 0, price_out: 0, key: '',
  })
  editingPid.value = pid
}
async function delProfile(row: ProfileRow) {
  const used = usesOf(row.pid)
  const name = row.name || '（未命名）'
  const msg = used.length
    ? `档案「${name}」正被 ${used.length} 道工序使用：${used.join('、')}。\n`
      + '删除后这些工序会解除绑定、改用全局兜底凭据（点「保存设置」后生效）。'
    : `确定删除档案「${name}」？`
  if (!await confirmBox(msg, { danger: true, ok: '删除' })) return
  profiles.value = profiles.value.filter(p => p.pid !== row.pid)
  for (const k of Object.keys(bindings.value)) {
    if (bindings.value[k] === row.pid) bindings.value[k] = ''
  }
  store.setProfileKey(row.pid, '')   // 本机 Key 一并清掉
  if (editingPid.value === row.pid) editingPid.value = ''
}
function applyPreset(row: ProfileRow, provider: string) {
  row.provider = provider
  const p = presets.value.find(x => x.provider === provider)
  if (!p) return
  row.base_url = p.base_url
  row.model = p.models[0] || ''
  row.price_in = p.price_in
  row.price_out = p.price_out
  if (!row.name) row.name = p.provider
}
/* 服务商下拉：选中预设就带出端点 / 模型 / 单价；选「自定义」只清掉预设标记 */
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
function presetOf(row: ProfileRow): ProviderPreset | undefined {
  return presets.value.find(p => p.provider === row.provider)
}
function modelOptions(row: ProfileRow): string[] {
  return presetOf(row)?.models || []
}

/* ---- 档案 ↔ 工序 关联：绑定表按档案反查，档案列表直接回显「谁在用我」 ---- */
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

/* ---- 保存（档案 + 绑定 + 通用一次写回；Key 只写 localStorage） ---- */
async function save() {
  for (const p of profiles.value) {
    if (!p.name.trim()) { toast('有档案没填名称', 'err'); tab.value = 'profiles'; return }
    if (!p.model.trim()) { toast(`档案「${p.name}」没填模型`, 'err'); tab.value = 'profiles'; return }
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
      store.setProfileKey(p.pid, p.key)   // Key 只落本机
    }
    const d = await store.loadStudio().catch(() => state.studio as any)
    // 绑定只保留指向「现存档案」的记录：档案被删后残留的 pid 不写回，避免出现空绑定
    const pids = new Set(profiles.value.map(p => p.pid))
    await store.saveStudio({
      ...(d || {}),
      profiles: rec,
      bindings: Object.fromEntries(
        Object.entries(bindings.value).filter(([, v]) => v && pids.has(v))),
      daily_goal: Math.max(0, Math.round(dailyGoal.value) || 0),
      memory: { enabled: memEnabled.value, top_k: memTopK.value, max_chars: memMaxChars.value },
      prices: { in: Number(priceIn.value) || 0, out: Number(priceOut.value) || 0 },
    })
    /* 旧版兜底凭据（没绑档案的工printf 序用） */
    state.key = key0.value.trim()
    state.model = model0.value.trim()
    state.baseUrl = baseUrl0.value.trim()
    store.saveSettings()
    toast('设置已保存', 'ok')
    ui.settingsOpen = false
  } catch (e: any) {
    toast('保存失败：' + (e.message || e), 'err')
  } finally {
    saving.value = false
  }
}

/* ---- 提示词覆盖 ---- */
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

/* 有效绑定数：只数指向「现存档案」的工序，页签角标与绑定页计数共用 */
const boundCount = computed(() =>
  Object.values(bindings.value).filter(pid => pid && profileOf(pid)).length)

/* ---------------- 数据同步（zip） ---------------- */
const syncBusy = ref(false)
const syncMsg = ref('')
const syncDetail = ref('')
/* 桌面端导出落盘后的完整路径：用于「打开目录」按钮 */
const exportPath = ref('')
/* 只有桌面壳（pywebview）能打开资源管理器；浏览器里不显示这个按钮。
   pywebview 的对象可能晚于页面脚本注入，监听一次 ready 事件兜底。 */
const isDesktopApp = ref(!!(window as any).pywebview)
if (!isDesktopApp.value) {
  window.addEventListener('pywebviewready', () => { isDesktopApp.value = true }, { once: true })
}

async function openExportDir() {
  const p = exportPath.value
  const cut = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/'))
  try {
    // 还没导出过就打开默认的 exports/（后端会顺手建目录）
    await api.openPath(p && cut > 0 ? p.slice(0, cut) : '')
    toast('已在资源管理器打开导出目录', 'ok')
  } catch (e: any) {
    toast(e.message || '打开目录失败', 'err')
  }
}
const replaceFirst = ref(false)
const zipInput = ref<HTMLInputElement | null>(null)

/* 自动备份：每次保存前服务端快照 chapters.json，最多 20 份，可一键回退 */
const backups = ref<{ file: string; size: number; mtime: string }[]>([])
const backupsBusy = ref(false)
async function loadBackups() {
  const book = store.curBook()
  if (!book) { backups.value = []; return }
  try { backups.value = (await api.listBackups(book)).files || [] }
  catch { backups.value = [] }
}
async function restoreBackup(file: string) {
  const book = store.curBook()
  if (!book) return
  if (!await confirmBox(`恢复 ${file}？\n当前版本会先自动再备份一份，恢复后可在列表里找到。`, { ok: '恢复' })) return
  backupsBusy.value = true
  try {
    await api.restoreBackup(book, file)
    toast('已恢复该备份', 'ok')
    window.dispatchEvent(new Event('mowrite:data-changed'))
    await loadBackups()
  } catch (e: any) { toast(e.message, 'err') }
  finally { backupsBusy.value = false }
}
watch(tab, v => { if (v === 'data') loadBackups() })
watch(() => ui.settingsOpen, v => { if (v && tab.value === 'data') loadBackups() })

async function exportZip() {
  if (syncBusy.value) return
  const pwd = await passwordBox('设置导出口令',
    '导出的作品数据会用这个口令加密（AES-256-GCM）。\n口令不会保存，忘记后这个导出包将无法恢复，请自行记牢。')
  if (!pwd) return
  syncBusy.value = true
  syncMsg.value = '正在打包作品数据…'
  syncDetail.value = ''
  try {
    const st = await api.dataSyncStatus().catch(() => null)
    if (st?.busy) {
      syncMsg.value = '暂时不能导出'
      syncDetail.value = '有任务正在运行，等任务结束后再导出，避免打到写了一半的文件。'
      toast(syncDetail.value, 'err')
      return
    }
    /* 桌面客户端（pywebview）没有浏览器下载目录：让服务端加密后存到 exe 同级 exports/ 并回显路径 */
    if ((window as any).pywebview) {
      const r = await api.exportDataSave(pwd)
      exportPath.value = r.path
      syncMsg.value = '已导出到本机（加密包）'
      syncDetail.value = `${r.path}（${(r.bytes / 1024 / 1024).toFixed(1)} MB · ${r.books} 部作品）`
      toast('已导出到 exports 目录', 'ok')
      return
    }
    /* 口令先换票据，下载地址里只出现票据，不出现口令 */
    const { ticket } = await api.prepareExport(pwd)
    const blob = await api.exportDataZip(ticket)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'mowrite-data-' + new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '') + '.mwen'
    a.click()
    URL.revokeObjectURL(url)
    syncMsg.value = '已导出（加密包）'
    syncDetail.value = `加密包 ${(blob.size / 1024 / 1024).toFixed(1)} MB，包含全部作品：设定、章节、正文、审查报告。导入时需要同一口令。`
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

/* 加密包头是 MWSEC1：读 base64 前 12 个字符即可判断，不用把整个包解出来 */
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
  const b64 = await new Promise<string>((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result || '').split(',')[1] || '')
    r.onerror = () => reject(new Error('读取数据包失败'))
    r.readAsDataURL(f)
  }).catch((err: any) => { toast(err.message || '读取失败', 'err'); return '' })
  if (!b64) return
  let pwd = ''
  if (isEncryptedB64(b64)) {
    const v = await passwordBox('导入加密包',
      '这个数据包已加密，请输入导出时设置的口令。\n口令不正确将无法导入。')
    if (!v) return
    pwd = v
  }
  const mode = replaceFirst.value ? '「先清空本地作品，再用数据包完全对齐」' : '「同名作品整体覆盖，其他作品保留」'
  if (!await confirmBox(`导入 ${f.name}？\n导入方式：${mode}`, { ok: '开始导入' })) return
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
  <Modal :open="ui.settingsOpen" title="工作台设置" wide
         @update:open="v => (ui.settingsOpen = v)">
    <div class="seg" style="margin-bottom: 14px">
      <button :class="{ on: tab === 'profiles' }" @click="tab = 'profiles'">模型档案</button>
      <button :class="{ on: tab === 'bindings' }" @click="tab = 'bindings'">
        工序绑定<span v-if="boundCount" class="tag blue" style="margin-left:6px">{{ boundCount }}</span>
      </button>
      <!-- 提示词库入口按需求屏蔽（后端 /api/prompts 保留，已有覆盖继续生效） -->
      <button :class="{ on: tab === 'data' }" @click="tab = 'data'">数据同步</button>
      <button :class="{ on: tab === 'general' }" @click="tab = 'general'">通用</button>
    </div>

    <div v-if="loading" class="hint">载入中…</div>

    <!-- ============ 模型档案 ============ -->
    <template v-else-if="tab === 'profiles'">
      <div class="hint" style="margin:0 0 10px">
        每家服务商建一条档案（端点 + 模型 + 刊例单价），再到「工序绑定」里指派各道工序用谁。
        <b>API Key 只保存在本机浏览器</b>，不写服务端、不进任何文件。
        成本统计按「模型名」归集：多条档案用同一个模型名时会算到第一条，建议给不同用途的档案区分模型名。
      </div>
      <div class="table-wrap" v-if="profiles.length">
      <table class="table">
        <thead>
          <tr><th>名称</th><th>服务商</th><th>模型</th><th>Key</th><th>使用工序</th><th style="text-align:right;white-space:nowrap">操作</th></tr>
        </thead>
        <tbody>
          <template v-for="p in profiles" :key="p.pid">
            <tr>
              <td><b>{{ p.name || '（未命名）' }}</b></td>
              <td><span class="tag gray">{{ p.provider || '自定义' }}</span></td>
              <td style="font-family:monospace;font-size:12px;white-space:nowrap">{{ p.model }}</td>
              <td>
                <span class="tag" :class="p.key ? 'green' : 'orange'">{{ p.key ? '已存本机' : '未设置' }}</span>
              </td>
              <td>
                <span v-if="!usesOf(p.pid).length" class="hint" style="font-size:12px">未绑定</span>
                <template v-else>
                  <span class="tag green" :title="usesOf(p.pid).join('、')">
                    {{ usesOf(p.pid).length }} 道工序
                  </span>
                  <div class="hint" style="font-size:12px;margin-top:2px" :title="usesOf(p.pid).join('、')">
                    {{ usesOf(p.pid).slice(0, 2).join('、') }}{{ usesOf(p.pid).length > 2 ? ' 等' : '' }}
                  </div>
                </template>
              </td>
              <td style="white-space:nowrap">
                <div class="ops">
                  <button class="link-btn" @click="editingPid = editingPid === p.pid ? '' : p.pid">
                    {{ editingPid === p.pid ? '收起' : '编辑' }}
                  </button>
                  <button class="link-btn red" @click="delProfile(p)">删除</button>
                </div>
              </td>
            </tr>
            <tr v-if="editingPid === p.pid">
              <td colspan="6" style="background:#fafbfc">
                <div class="form-grid">
                  <div class="field">
                    <label>档案名称</label>
                    <input class="input" v-model="p.name" placeholder="如：DeepSeek 初稿" />
                  </div>
                  <div class="field">
                    <label>服务商预设（选了自动带端点 / 模型 / 刊例价）</label>
                    <SelectBox :model-value="p.provider" :options="providerOptions"
                               placeholder="自定义（不套用预设）"
                               @update:model-value="v => applyPreset(p, v)" />
                    <div class="hint" v-if="presetOf(p)?.note">{{ presetOf(p)?.note }}</div>
                  </div>
                  <div class="field">
                    <label>Base URL</label>
                    <input class="input" v-model="p.base_url" placeholder="https://…" />
                  </div>
                  <div class="field">
                    <label>模型</label>
                    <SelectBox v-model="p.model" :options="modelOptions(p)" allow-custom
                               placeholder="点选预设，或直接输入模型名" />
                  </div>
                  <div class="field">
                    <label>API Key（仅存本机浏览器）</label>
                    <input class="input" type="password" v-model="p.key"
                           :placeholder="p.key ? '已保存，输入以更换' : 'sk-…'" />
                  </div>
                  <div class="field">
                    <label>温度（留空用默认）</label>
                    <input class="input" type="number" step="0.1" min="0" max="2" v-model="p.temperature" />
                  </div>
                  <div class="field">
                    <label>输入单价（元 / 百万 tokens）</label>
                    <input class="input" type="number" step="0.1" min="0" v-model="p.price_in" />
                  </div>
                  <div class="field">
                    <label>输出单价（元 / 百万 tokens）</label>
                    <input class="input" type="number" step="0.1" min="0" v-model="p.price_out" />
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      </div>
      <div v-else class="hint" style="padding:18px 0;text-align:center">还没有模型档案，先加一条</div>
      <button class="btn ghost" style="margin-top:10px" @click="addProfile">+ 新建档案</button>
    </template>

    <!-- ============ 工序绑定 ============ -->
    <template v-else-if="tab === 'bindings'">
      <div class="hint" style="margin:0 0 10px">
        给每道工序指派一个模型档案：拆解 / 改编用长上下文强的（如 Kimi），初稿用性价比高的（如 DeepSeek），
        正文改写扩写用文风顺的（如豆包），选区小动作用便宜快的（如千问 turbo），审查用逻辑强的（如 ChatGPT）。
        各工序的 Token 成本与耗时会按档案分开统计。
        <b>已绑定 {{ boundCount }} / {{ Object.keys(stageLabel).length }} 道工序</b>，未绑定的工序走「通用」里的兜底凭据。
      </div>
      <div class="table-wrap">
      <table class="table">
        <thead><tr><th>工序</th><th>绑定档案</th></tr></thead>
        <tbody>
          <tr v-for="(label, key) in stageLabel" :key="key">
            <td>{{ label }}</td>
            <td>
              <div style="max-width:360px">
                <SelectBox v-model="bindings[key]" :options="bindingOptions" allow-empty
                           empty-label="未绑定（用全局兜底）" placeholder="选择模型档案" />
              </div>
              <div class="hint" style="margin-top:4px" v-if="bindings[key] && profileOf(bindings[key])">
                <span v-if="profileOf(bindings[key])!.base_url" style="font-family:monospace">
                  {{ profileOf(bindings[key])!.base_url }} ·
                </span>
                <span :style="{ color: profileOf(bindings[key])!.key ? 'var(--text-3)' : 'var(--orange)' }">
                  {{ profileOf(bindings[key])!.key ? 'Key 已配置' : '未配置 Key，调用会降级为本地骨架' }}
                </span>
              </div>
              <div class="hint" style="margin-top:4px;color:var(--orange)"
                   v-else-if="bindings[key]">该档案已不存在，请重新选择</div>
              <div class="hint" style="margin-top:4px" v-else>使用兜底凭据（默认 deepseek-v4-flash）</div>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <div class="hint" v-if="!profiles.length" style="color:var(--orange)">
        还没有档案可绑——先去「模型档案」页签建一条。
      </div>
    </template>

    <!-- ============ 提示词库 ============ -->
    <template v-else-if="tab === 'prompts'">
      <div class="hint" style="margin:0 0 10px">
        影响生成质量的提示词都在这里。覆盖只保存在本机设置里，随时可恢复默认。
      </div>
      <div v-if="!prompts.length" class="hint">暂无可编辑的提示词条目</div>
      <div v-for="it in prompts" :key="it.key" class="prompt-item">
        <div class="prompt-head" role="button" tabindex="0" @click="openPrompt(it)"
             @keydown.enter="openPrompt(it)">
          <span class="tag gray">{{ it.stage }}</span>
          <b>{{ it.label }}</b>
          <span v-if="it.overridden" class="tag orange">已覆盖</span>
          <span style="flex:1"></span>
          <button class="link-btn prompt-copy" title="复制生效提示词" @click.stop="copyPrompt(it)">
            <Icon name="copy" :size="12" /> 复制
          </button>
          <span style="color:var(--text-3);font-size:12px">{{ promptOpen === it.key ? '收起 ▲' : '展开 ▼' }}</span>
        </div>
        <div v-if="promptOpen === it.key" class="prompt-body">
          <div class="hint" v-if="it.note">{{ it.note }}</div>
          <details v-if="it.default">
            <summary class="link-btn" style="display:inline-block">查看内置默认（{{ it.default.length }} 字）</summary>
            <pre class="prompt-pre">{{ it.default }}</pre>
          </details>
          <template v-if="it.editable">
            <textarea class="input textarea" rows="6" v-model="promptDraft"
                      placeholder="留空 = 使用内置默认；填入文本 = 覆盖默认"></textarea>
            <div style="display:flex;gap:8px;margin-top:8px">
              <button class="btn" :disabled="promptSaving" @click="savePrompt(it)">保存覆盖</button>
              <button class="btn ghost" :disabled="promptSaving || !it.overridden"
                      @click="savePrompt(it, true)">恢复默认</button>
            </div>
          </template>
          <div v-else class="hint">该条目只读（来源见上方说明）。</div>
        </div>
      </div>
    </template>

    <!-- ============ 数据同步 ============ -->
    <template v-else-if="tab === 'data'">
      <div class="form-grid">
        <div class="form-sec"><span class="n">1</span>导出：把本机作品数据加密打包带走</div>
        <div class="field full">
          <label>导出全部作品（加密包 .mwen）</label>
          <div class="hint">
            包含 data/&lt;书名&gt;/ 下的全部产出：全书设定、角色 / 势力 / 道具、章节数据、正文、审查报告、设定图谱、封面。
            任务记录、用量统计等「本机状态」不导出。导出时设置的口令请自行记牢，忘记后无法恢复。
          </div>
          <div style="margin-top:10px">
            <button class="btn" :disabled="syncBusy" @click="exportZip">
              <Icon name="download" :size="15" /> {{ syncBusy ? '处理中…' : '导出并加密' }}
            </button>
            <button v-if="isDesktopApp" class="btn ghost" style="margin-left:8px" @click="openExportDir">
              <Icon name="folder" :size="15" /> 打开导出目录
            </button>
          </div>
        </div>

        <div class="form-sec"><span class="n">2</span>导入：用另一端的数据包对齐数据</div>
        <div class="field full">
          <label>选择数据包导入（.mwen / .zip）</label>
          <div class="hint">
            按「作品」为单位整体覆盖：同一个作品名会用数据包里的版本完整替换，其他作品不受影响。
            加密包需要输入导出时的口令；旧版明文 zip 仍可直接导入。
          </div>
          <label class="check" style="margin-top:8px">
            <input type="checkbox" v-model="replaceFirst" :disabled="syncBusy" />
            先清空本机全部作品，再按数据包完全对齐（旧数据会自动备份到 data-backup-时间/）
          </label>
          <div style="margin-top:10px">
            <button class="btn ghost" :disabled="syncBusy" @click="pickZip">
              <Icon name="upload" :size="15" /> {{ syncBusy ? '处理中…' : '选择数据包并导入' }}
            </button>
            <input ref="zipInput" type="file" accept=".mwen,.zip,application/zip,application/octet-stream"
                   hidden @change="onZipFile" />
          </div>
          <div v-if="syncMsg" class="hint" style="margin-top:10px">
            <b style="color:var(--text)">{{ syncMsg }}</b>
            <div v-if="syncDetail" style="word-break:break-all">{{ syncDetail }}</div>
          </div>
        </div>

        <div class="form-sec"><span class="n">3</span>自动备份：误改 / 误删可回退</div>
        <div class="field full">
          <label>《{{ store.curBook() || '未选作品' }}》最近备份</label>
          <div class="hint">
            每次保存章节数据前自动快照，最多保留 20 份；备份只留在本机，不进入数据同步包。
          </div>
          <div v-if="backups.length" class="bk-list">
            <div v-for="b in backups" :key="b.file" class="bk-row">
              <span class="bk-time">{{ b.mtime }}</span>
              <span class="bk-size">{{ (b.size / 1024).toFixed(0) }} KB</span>
              <button class="btn sm ghost" :disabled="backupsBusy" @click="restoreBackup(b.file)">恢复</button>
            </div>
          </div>
          <div v-else class="hint">还没有备份；保存一次章节数据后会自动生成。</div>
          <button class="btn sm ghost" style="margin-top:8px" :disabled="backupsBusy" @click="loadBackups">
            <Icon name="refresh" :size="13" /> 刷新备份列表
          </button>
        </div>
      </div>
    </template>

    <!-- ============ 通用 ============ -->
    <template v-else>
      <div class="form-grid">
        <div class="form-sec"><span class="n">1</span>码字与记忆</div>
        <div class="field">
          <label>日更码字目标（字）</label>
          <input class="input" type="number" min="0" step="500" v-model="dailyGoal" />
        </div>
        <div class="field">
          <label>跨章记忆检索</label>
          <label class="check"><input type="checkbox" v-model="memEnabled" /> 生成正文时注入「前文记忆」</label>
          <div class="hint">减少吃设定、忘伏笔；索引完全在本地构建，不消耗 Token。</div>
        </div>
        <div class="field">
          <label>记忆检索章节数（top_k）</label>
          <input class="input" type="number" min="1" max="8" v-model="memTopK" />
        </div>
        <div class="field">
          <label>记忆块最大长度（字）</label>
          <input class="input" type="number" min="400" max="6000" step="200" v-model="memMaxChars" />
        </div>
        <div class="form-sec"><span class="n">2</span>成本兜底单价（档案没填单价时用）</div>
        <div class="field">
          <label>输入（元 / 百万 tokens）</label>
          <input class="input" type="number" step="0.1" min="0" v-model="priceIn" />
        </div>
        <div class="field">
          <label>输出（元 / 百万 tokens）</label>
          <input class="input" type="number" step="0.1" min="0" v-model="priceOut" />
        </div>
        <div class="form-sec"><span class="n">3</span>全局兜底凭据（没绑档案的工序用）</div>
        <div class="field full">
          <label>API Key</label>
          <input class="input" type="password" v-model="key0" placeholder="sk-…" />
          <div class="hint">仅保存在本机浏览器；建议改用「模型档案 + 工序绑定」，这里留作兼容。</div>
        </div>
        <div class="field">
          <label>模型（留空用服务端默认）</label>
          <input class="input" v-model="model0" placeholder="deepseek-v4-flash" />
        </div>
        <div class="field">
          <label>Base URL（留空用官方地址）</label>
          <input class="input" v-model="baseUrl0" placeholder="https://api.deepseek.com" />
        </div>
      </div>
    </template>

    <template #footer>
      <button class="btn ghost" @click="ui.settingsOpen = false">{{ tab === 'data' ? '关闭' : '取消' }}</button>
      <button v-if="tab !== 'data'" class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存设置' }}</button>
    </template>
  </Modal>
</template>

<style scoped>
.prompt-item { border: 1px solid var(--border); border-radius: var(--radius-sm); margin-bottom: 8px; overflow: hidden; }
.prompt-head { display: flex; align-items: center; gap: 8px; width: 100%; border: none; background: none;
  padding: 10px 12px; font-size: 13px; color: var(--text); cursor: pointer; text-align: left; }
.prompt-copy { flex: none; font-size: 11.5px; }
.prompt-head:hover { background: #fafbfc; }
.prompt-body { padding: 10px 12px; border-top: 1px solid var(--border); background: #fafbfc; }
.prompt-pre { max-height: 200px; overflow: auto; background: var(--card); border: 1px solid var(--border);
  border-radius: 6px; padding: 10px; font-size: 12px; line-height: 1.7; white-space: pre-wrap; margin: 8px 0; }
.bk-list { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; max-height: 190px; overflow-y: auto; }
.bk-row { display: flex; align-items: center; gap: 10px; padding: 6px 9px; border: 1px solid var(--border);
  border-radius: 7px; font-size: 11.5px; }
.bk-time { flex: 1; min-width: 0; color: var(--text-2); font-variant-numeric: tabular-nums; }
.bk-size { flex: none; color: var(--text-3); }
</style>
