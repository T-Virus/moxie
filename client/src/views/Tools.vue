<template>
  <main class="page tools">
    <div class="page-head">
      <h1 class="page-title">工具下载</h1>
      <p class="page-sub">
        离线版安装后无需联网即可创作，作品与素材全部保存在本机。安装包仅向注册登录用户开放。
      </p>
    </div>

    <section v-if="!session.account" class="card tools__gate">
      <div class="tools__gate-main">
        <h2 class="tools__gate-title">登录后下载离线版</h2>
        <p class="tools__gate-text">
          Windows 与 Android 安装包需要注册登录后才能获取；登录成功会自动回到本页。
        </p>
      </div>
      <div class="tools__gate-actions">
        <RouterLink :to="{ name: 'login', query: { next: '/tools' } }" class="btn">登录</RouterLink>
        <RouterLink
          :to="{ name: 'login', query: { next: '/tools', tab: 'register' } }"
          class="btn btn--brand"
        >
          注册
        </RouterLink>
      </div>
    </section>

    <div v-if="loadError" class="alert tools__error" role="alert">
      <span>{{ loadError }}</span>
      <button type="button" class="btn btn--sm" @click="load">重试</button>
    </div>

    <div v-if="downloadError" class="alert tools__error" role="alert">
      <span>{{ downloadError }}</span>
      <button type="button" class="btn btn--sm" @click="downloadError = ''">关闭</button>
    </div>

    <div class="tools__grid">
      <article v-for="card in CARDS" :key="card.platform" class="card tool">
        <header class="tool__head">
          <span class="tool__icon" :class="`tool__icon--${card.platform}`" aria-hidden="true">
            <svg v-if="card.platform === 'windows'" viewBox="0 0 24 24">
              <path
                d="M3 5.6l7.4-1v7.1H3V5.6zm0 12.8l7.4 1v-7.1H3v6.1zm8.3 1.1L21 21v-8.6h-9.7v7.1zm0-15.1v7.2H21V3l-9.7 1.4z"
                fill="currentColor"
              />
            </svg>
            <svg v-else viewBox="0 0 24 24">
              <path
                d="M6.4 9.2h11.2v8.1a1.7 1.7 0 0 1-1.7 1.7h-1.2v2.3a1.1 1.1 0 0 1-2.2 0v-2.3h-1v2.3a1.1 1.1 0 0 1-2.2 0v-2.3H8.1a1.7 1.7 0 0 1-1.7-1.7V9.2z"
                fill="currentColor"
              />
              <path
                d="M5 9.4a1.3 1.3 0 0 1 2.6 0v4.4a1.3 1.3 0 0 1-2.6 0V9.4zm11.4 0a1.3 1.3 0 0 1 2.6 0v4.4a1.3 1.3 0 0 1-2.6 0V9.4z"
                fill="currentColor"
              />
              <path
                d="M7 7.9c.5-1.7 2.2-2.9 4.2-2.9 1.5 0 2.9.7 3.7 1.9l1.2-.8-.6 1.6c.4.6.6 1.3.7 2H7.1l-.1-1.8z"
                fill="currentColor"
              />
              <circle cx="9.4" cy="7.5" r=".8" fill="#fff" />
              <circle cx="13.4" cy="7.5" r=".8" fill="#fff" />
            </svg>
          </span>
          <div class="tool__heading">
            <h2 class="tool__title">{{ card.title }}</h2>
            <p class="tool__require">{{ card.requirement }}</p>
          </div>
          <span class="badge tool__badge">{{ session.account ? '已登录' : '需登录' }}</span>
        </header>

        <!-- <p class="tool__desc">{{ card.desc }}</p> -->

        <dl class="tool__meta">
          <div class="tool__meta-item">
            <dt>版本</dt>
            <dd>{{ loading ? '获取中…' : versionText(card.platform) }}</dd>
          </div>
          <div class="tool__meta-item">
            <dt>大小</dt>
            <dd>{{ loading ? '获取中…' : sizeText(card.platform) }}</dd>
          </div>
          <div class="tool__meta-item">
            <dt>更新</dt>
            <dd>{{ loading ? '获取中…' : updatedText(card.platform) }}</dd>
          </div>
        </dl>

        <ul class="tool__features">
          <li v-for="feature in card.features" :key="feature">{{ feature }}</li>
        </ul>

        <button
          type="button"
          class="btn tool__download"
          :class="{ 'btn--brand': session.account && available(card.platform) }"
          :disabled="!available(card.platform) || downloading === card.platform"
          @click="onDownload(card)"
        >
          {{ buttonText(card) }}
        </button>
        <p class="tool__hint">
          {{ session.account ? '下载即表示同意离线版使用许可。' : '登录或注册后即可下载。' }}
        </p>
      </article>
    </div>

    <section class="tools__notes">
      <h2 class="tools__notes-title">使用说明</h2>
      <ul class="tools__notes-list">
        <li>离线版与在线版数据相互独立，作品不会自动同步到账号。</li>
        <li>Windows 版为免安装可执行文件；Android 版首次安装需允许「安装未知来源应用」。</li>
        <li>安装包会持续更新，下载页展示的是当前最新构建版本。</li>
      </ul>
    </section>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, apiDownload, apiFetch } from '@/services/http'
import { session } from '@/stores/session'
import { saveFile } from '@/utils/download'
import { formatBytes, formatDateTime } from '@/utils/format'

interface DownloadMeta {
  platform: string
  label: string
  available: boolean
  version?: string
  size?: number
  updated_at?: string
}

interface PlatformCard {
  platform: 'windows' | 'android'
  title: string
  requirement: string
  desc: string
  file: string
  features: string[]
}

const CARDS: PlatformCard[] = [
  {
    platform: 'windows',
    title: 'Windows 离线版',
    requirement: 'Windows 10 / 11 · x64',
    desc: '桌面端完整创作能力，断网也能生成、改稿与导出。',
    file: '墨写-Windows离线版.exe',
    features: ['本地保存作品与素材', '内置完整创作流程', '支持导出章节与大纲'],
  },
  {
    platform: 'android',
    title: 'Android 离线版',
    requirement: 'Android 8.0 及以上',
    desc: '手机端随时续写，离线打开本地作品，灵感来了就能写。',
    file: '墨写-Android离线版.apk',
    features: ['手机随时续写与导出', '离线访问本地作品', '轻量安装包'],
  },
]

const router = useRouter()
const items = ref<Record<string, DownloadMeta>>({})
const loading = ref(true)
const loadError = ref('')
const downloading = ref('')
const downloadError = ref('')

function applyMeta(list: DownloadMeta[]): void {
  const next: Record<string, DownloadMeta> = {}
  for (const item of list) next[item.platform] = item
  items.value = next
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const data = await apiFetch<{ items: DownloadMeta[] }>('/downloads', { anonymous: true })
    applyMeta(data.items)
  } catch (err) {
    loadError.value = err instanceof ApiError ? err.message : '暂时无法获取安装包信息'
  } finally {
    loading.value = false
  }
}

function available(platform: string): boolean {
  return !!items.value[platform]?.available
}

function versionText(platform: string): string {
  const version = items.value[platform]?.version
  return version ? `v${version}` : '最新构建'
}

function sizeText(platform: string): string {
  const size = items.value[platform]?.size
  return size ? formatBytes(size) : '—'
}

function updatedText(platform: string): string {
  return formatDateTime(items.value[platform]?.updated_at)
}

function buttonText(card: PlatformCard): string {
  if (loading.value) return '正在获取安装包…'
  if (!available(card.platform)) return '暂未发布'
  if (!session.account) return '登录后下载'
  if (downloading.value === card.platform) return '正在下载…'
  return '下载安装包'
}

async function onDownload(card: PlatformCard): Promise<void> {
  downloadError.value = ''
  if (!session.account) {
    void router.push({ name: 'login', query: { next: '/tools' } })
    return
  }
  if (!available(card.platform) || downloading.value) return
  downloading.value = card.platform
  try {
    const file = await apiDownload(`/downloads/${card.platform}`, card.file)
    saveFile(file)
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      void router.push({ name: 'login', query: { next: '/tools' } })
      return
    }
    downloadError.value = err instanceof ApiError ? err.message : '下载失败，请稍后重试'
  } finally {
    downloading.value = ''
  }
}

onMounted(load)
</script>

<style scoped>
.tools {
  max-width: 1020px;
}

.tools__gate {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  padding: var(--space-5) var(--space-6);
  margin-bottom: var(--space-5);
  background: linear-gradient(135deg, #f2fbfa, #ffffff 62%);
  border-color: #cdece8;
}

.tools__gate-title {
  font-size: var(--text-md);
  font-weight: 700;
}

.tools__gate-text {
  margin-top: 4px;
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

.tools__gate-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: none;
}

.tools__error {
  margin-bottom: var(--space-5);
  align-items: center;
  justify-content: space-between;
}

.tools__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-5);
}

.tool {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6) var(--space-6);
}

.tool__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.tool__icon {
  width: 42px;
  height: 42px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--radius-md);
  color: #fff;
}

.tool__icon--windows {
  background: linear-gradient(135deg, #2563eb, #0ea5e9);
}

.tool__icon--android {
  background: linear-gradient(135deg, #16a34a, #65a30d);
}

.tool__icon svg {
  width: 24px;
  height: 24px;
}

.tool__heading {
  min-width: 0;
  flex: 1;
}

.tool__title {
  font-size: var(--text-md);
  font-weight: 700;
}

.tool__require {
  margin-top: 2px;
  color: var(--color-text-3);
  font-size: var(--text-xs);
}

.tool__badge {
  flex: none;
}

.tool__desc {
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

.tool__meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-bg-softer);
}

.tool__meta-item dt {
  color: var(--color-text-3);
  font-size: var(--text-xs);
}

.tool__meta-item dd {
  margin: 2px 0 0;
  font-weight: 600;
  font-size: var(--text-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tool__features {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

.tool__features li {
  position: relative;
  padding-left: 18px;
}

.tool__features li::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 8px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-brand);
}

.tool__download {
  width: 100%;
  margin-top: auto;
}

.tool__hint {
  color: var(--color-text-3);
  font-size: var(--text-xs);
  text-align: center;
}

.tools__notes {
  margin-top: var(--space-8);
  padding-top: var(--space-5);
  border-top: 1px solid var(--color-line);
}

.tools__notes-title {
  font-size: var(--text-md);
  font-weight: 700;
}

.tools__notes-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: var(--space-3);
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

.tools__notes-list li {
  position: relative;
  padding-left: 16px;
}

.tools__notes-list li::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 9px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-line-strong);
}

@media (max-width: 760px) {
  .tools__gate {
    flex-direction: column;
    align-items: flex-start;
  }

  .tools__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .tool__meta {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
