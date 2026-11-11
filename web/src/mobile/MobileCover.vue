<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import BookArt from './BookArt.vue'
import MobilePicker from './MobilePicker.vue'
import { api } from '../api'
import { state, store } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { confirmBox, toast } from '../ui'
import { fmtNum } from '../utils'

const router = useRouter()
const meta = computed(() => state.books.find(b => b.name === store.curBook()) || null)
/* 作品状态存在 chapters.json 顶层：这里复用文档 composable 读写，改完立即落盘 */
const { raw, load: loadDoc, save } = useBookDoc()
const tick = ref(Date.now())
const synOpen = ref(false)
const fileRef = ref<HTMLInputElement | null>(null)

const title = computed(() => meta.value?.title || meta.value?.name || '')
const synopsis = computed(() => (meta.value?.synopsis || '').trim())

/* 状态：文档里的值优先（刚改过），其次作品摘要 */
const STATUS_OPTIONS = ['连载中', '已完结']
const curStatus = computed(() => {
  const s = String((raw.value as any)?.status || '').trim()
  return s || meta.value?.status || '连载中'
})
const statusOptions = computed(() =>
  STATUS_OPTIONS.includes(curStatus.value) ? STATUS_OPTIONS : [curStatus.value, ...STATUS_OPTIONS])
const isFinished = computed(() => curStatus.value === '已完结')

/* 审查入口的显示条件：全书体检只在完结后出现，签约预检只在成稿满 2 万字后出现 */
const canBatchReview = computed(() => isFinished.value)
const canSigningReview = computed(() => (meta.value?.manuscript_chars || 0) >= 20000)
const showReview = computed(() => canBatchReview.value || canSigningReview.value)

async function setStatus(v: string) {
  if (!v || v === curStatus.value) return
  if (!raw.value) {
    toast('作品数据还在载入，请稍后再试', 'err')
    return
  }
  ;(raw.value as any).status = v
  const ok = await save(true)
  if (!ok) { loadDoc(); return }
  toast('作品状态已改为「' + v + '」', 'ok')
  store.loadStats().catch(() => {})
}

/* 已有成稿：按章号倒序取最近三章 */
const recent = computed(() => {
  const map = meta.value?.ms_by_no || {}
  return Object.entries(map)
    .map(([no, v]: [string, any]) => ({ no: Number(no) || 0, ...v }))
    .filter(x => x.no > 0)
    .sort((a, b) => b.no - a.no)
    .slice(0, 3)
})

/* 继续写作：优先最近成稿，其次最后一章，最后第一章 */
const continueNo = computed(() => {
  if (recent.value.length) return recent.value[0].no
  return Number(meta.value?.last_chapter_no) || 1
})

const modules = computed(() => [
  { key: 'outline', t: '作品大纲', d: '题材、世界观、主线与人物设定', icon: 'list', color: 'blue', n: '21 项要素', path: '/outline' },
  { key: 'characters', t: '角色卡', d: '人物身份、性格、目标与关系', icon: 'user', color: 'green', n: `${meta.value?.n_cards || 0} 张`, path: '/characters' },
  { key: 'factions', t: '势力表', d: '门派、组织、阵营与相互关系', icon: 'flag', color: 'purple', n: `${meta.value?.n_factions || 0} 个`, path: '/factions' },
  { key: 'items', t: '道具功法', d: '剧情道具、武学功法与战技', icon: 'shield', color: 'teal', n: `${meta.value?.n_items || 0} 件`, path: '/items' },
  { key: 'chapters', t: '章节概括', d: '逐章摘要、事件与情绪节奏', icon: 'file', color: 'gold', n: `${meta.value?.n_chapters || 0} 章`, path: '/chapters' },
  { key: 'manuscript', t: '正文', d: '成稿阅读与逐章写作', icon: 'book', color: 'teal', n: `${meta.value?.n_manuscripts || 0} 章成稿`, path: '/manuscript' },
])

function go(path: string) { router.push(path) }
function goReview(kind: 'batch' | 'signing') {
  router.push({ path: '/book-review', query: { tab: kind } })
}
function write() { router.push({ path: '/manuscript', query: { ch: String(continueNo.value) } }) }
function openChapter(no: number) { router.push({ path: '/manuscript', query: { ch: String(no) } }) }

function pickCover(f?: File | null) {
  if (!f || !meta.value) return
  if (!/^image\/(png|jpe?g|webp)$/.test(f.type)) return toast('仅支持 png / jpg / webp 图片', 'err')
  if (f.size > 5 * 1024 * 1024) return toast('图片过大（>5MB）', 'err')
  const reader = new FileReader()
  reader.onload = async () => {
    const b64 = (reader.result as string).split(',')[1]
    const ext = f.type === 'image/png' ? 'png' : f.type === 'image/webp' ? 'webp' : 'jpg'
    try {
      await api.uploadCover(store.curBook(), b64, ext)
      toast('封面已更新', 'ok')
      tick.value = Date.now()
      store.loadStats().catch(() => {})
    } catch (e: any) { toast(e.message, 'err') }
  }
  reader.readAsDataURL(f)
}
async function removeCover() {
  if (!meta.value) return
  if (!await confirmBox('移除当前封面？', { danger: true, ok: '移除' })) return
  try {
    await api.deleteCover(store.curBook())
    toast('已移除封面', 'ok')
    tick.value = Date.now()
    store.loadStats().catch(() => {})
  } catch (e: any) { toast(e.message, 'err') }
}
</script>

<template>
  <div class="m-page">
    <!-- 没有作品 -->
    <div v-if="!state.books.length" class="m-empty" style="padding-top:90px">
      <span class="m-empty-ico"><Icon name="book" :size="30" /></span>
      <b>还没有作品</b>
      <p>新建一部作品，上传全本或大纲，开始你的 AI 写作流程。</p>
      <button class="m-btn" @click="go('/upload')"><Icon name="plus" :size="16" /> 新建作品</button>
    </div>

    <template v-else-if="meta">
      <!-- 书本封面 -->
      <section class="m-cover-hero">
        <img v-if="meta.has_cover" class="m-cover-blur" :src="api.coverUrl(meta.name, tick)" alt="" />
        <div class="m-cover-main">
          <div class="m-cover-book" @click="fileRef?.click()">
            <BookArt :name="meta.name" :title="meta.title" :author="meta.author"
                     :has-cover="meta.has_cover" size="lg" :tick="tick" />
            <span class="m-cover-cam"><Icon name="upload" :size="14" /></span>
          </div>
          <input ref="fileRef" type="file" accept="image/png,image/jpeg,image/webp" hidden
                 @change="e => { pickCover((e.target as HTMLInputElement).files?.[0]); (e.target as HTMLInputElement).value = '' }" />

          <div class="m-cover-info">
            <span class="m-cover-status" :class="{ done: isFinished }">
              <i></i>
              <MobilePicker chip :model-value="curStatus" :options="statusOptions"
                            :allow-empty="false" title="作品状态"
                            @update:model-value="setStatus" />
            </span>
            <h1 class="m-cover-title">{{ title }}</h1>
            <div class="m-cover-author">{{ meta.author ? meta.author + ' 著' : '作者未署名' }}</div>
            <p v-if="synopsis" class="m-cover-syn">{{ synopsis }}</p>
            <div class="m-cover-badges">
              <span>{{ meta.n_chapters || 0 }} 章</span>
              <span>{{ fmtNum(meta.manuscript_chars || 0) }} 字</span>
              <span>{{ meta.mtime_text || '刚刚更新' }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 数据概览 -->
      <div class="m-cover-stats">
        <div class="m-cstat"><b>{{ fmtNum(meta.manuscript_chars || 0) }}</b><small>累计字数</small></div>
        <div class="m-cstat"><b>{{ meta.n_chapters || 0 }}</b><small>总章节</small></div>
        <div class="m-cstat"><b>{{ meta.n_manuscripts || 0 }}</b><small>已成稿</small></div>
        <div class="m-cstat"><b>{{ meta.n_cards || 0 }}</b><small>角色卡</small></div>
      </div>

      <!-- 主操作 -->
      <div class="m-cover-actions">
        <button class="m-btn" style="grid-column:1/-1" @click="write">
          <Icon name="pen" :size="16" /> {{ meta.n_manuscripts ? '继续写作' : '开始写第一章' }}
        </button>
        <button class="m-btn ghost" @click="fileRef?.click()">
          <Icon name="upload" :size="15" /> 更换封面
        </button>
        <button class="m-btn ghost" @click="go('/cover-design')">
          <Icon name="edit" :size="15" /> AI 生成封面
        </button>
      </div>
      <div v-if="meta.has_cover" style="text-align:center;margin-top:8px">
        <button class="m-link" style="color:var(--m-text3);font-weight:500" @click="removeCover">移除当前封面</button>
      </div>

      <!-- 作品审查：完结后才出全书体检，成稿满 2 万字才出签约预检 -->
      <template v-if="showReview">
        <div class="m-sec-title">作品审查</div>
        <div class="m-card m-cover-review">
          <button v-if="canBatchReview" class="m-review-entry" @click="goReview('batch')">
            <span class="m-module-ico blue"><Icon name="shield" :size="18" /></span>
            <span class="m-module-txt"><b>全书体检</b><small>逐章检查问题与高危项</small></span>
            <Icon name="right" :size="14" class="m-row-arrow" />
          </button>
          <button v-if="canSigningReview" class="m-review-entry" @click="goReview('signing')">
            <span class="m-module-ico gold"><Icon name="flag" :size="18" /></span>
            <span class="m-module-txt"><b>签约预检</b><small>前 2 万字的开篇质量</small></span>
            <Icon name="right" :size="14" class="m-row-arrow" />
          </button>
        </div>
      </template>

      <!-- 内容模块 -->
      <div class="m-sec-title">创作内容<span class="m-spacer"></span></div>
      <div class="m-card m-modules">
        <button v-for="m in modules" :key="m.key" class="m-module" @click="go(m.path)">
          <span class="m-module-ico" :class="m.color"><Icon :name="m.icon" :size="18" /></span>
          <span class="m-module-txt"><b>{{ m.t }}</b><small>{{ m.d }}</small></span>
          <span class="m-module-n">{{ m.n }}</span>
          <Icon name="right" :size="14" class="m-row-arrow" />
        </button>
      </div>

      <!-- 作品简介 -->
      <div class="m-sec-title">作品简介</div>
      <div class="m-card">
        <p v-if="synopsis" class="m-cover-intro" :class="{ clamp: !synOpen }">{{ synopsis }}</p>
        <p v-else class="m-hint">还没有简介。可以先到「作品大纲」填写作品简介与核心卖点。</p>
        <button v-if="synopsis.length > 80" class="m-link" style="margin-top:6px" @click="synOpen = !synOpen">
          {{ synOpen ? '收起' : '展开全文' }} <Icon :name="synOpen ? 'down' : 'right'" :size="12" />
        </button>
        <button v-if="!synopsis" class="m-link" style="margin-top:4px" @click="go('/outline')">
          去填写大纲 <Icon name="right" :size="12" />
        </button>
      </div>

      <!-- 最近成稿 -->
      <div class="m-sec-title">
        最近成稿<span class="m-spacer"></span>
        <button v-if="recent.length" class="m-link" @click="go('/manuscript')">全部正文</button>
      </div>
      <div class="m-card m-card-tight">
        <template v-if="recent.length">
          <button v-for="r in recent" :key="r.no" class="m-ms-row" @click="openChapter(r.no)">
            <span class="m-ms-no">第<b>{{ r.no }}</b>章</span>
            <span class="m-ms-body">
              <b>{{ r.title || '未命名' }}</b>
              <small>{{ fmtNum(r.chars || 0) }} 字 · {{ r.mtime || '已保存' }}</small>
            </span>
            <Icon name="right" :size="14" class="m-row-arrow" />
          </button>
        </template>
        <button v-else class="m-empty" style="padding:26px 12px" @click="write">
          <span class="m-empty-ico" style="width:52px;height:52px;border-radius:18px"><Icon name="pen" :size="24" /></span>
          <b>还没有正文</b>
          <p>第 {{ continueNo }} 章正等着你落笔</p>
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.m-cover-intro { font-size: 13px; line-height: 1.8; color: var(--m-text2); white-space: pre-wrap; }
.m-cover-review { padding: 6px; }
.m-review-entry {
  display: flex; align-items: center; gap: 11px; width: 100%;
  padding: 10px; border: 0; border-radius: 14px; background: none;
  color: var(--m-text); text-align: left;
}
.m-review-entry + .m-review-entry { border-top: 1px solid #f2f4f0; }
.m-review-entry:active { background: #f6f8f4; }
.m-cover-intro.clamp {
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
}
</style>
