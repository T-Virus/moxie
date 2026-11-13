<template>
  <div ref="root" class="genre">
    <button
      type="button"
      class="genre__trigger"
      :class="{ 'is-active': menuOpen || !!modelValue.name }"
      aria-haspopup="menu"
      :aria-expanded="menuOpen"
      @click="toggle"
      @keydown.esc="close"
    >
      <span class="genre__label">{{ modelValue.name || '题材' }}</span>
      <svg class="genre__caret" viewBox="0 0 12 12" aria-hidden="true">
        <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.4" />
      </svg>
    </button>

    <div
      v-if="menuOpen"
      class="genre__menu"
      :class="{ 'is-up': menuUp }"
      :style="menuMax ? { maxHeight: `${menuMax}px` } : undefined"
      role="menu"
      aria-label="选择题材"
      @keydown.esc="close"
    >
      <input
        ref="searchInput"
        v-model="query"
        class="genre__search"
        type="search"
        placeholder="搜索题材或标签"
        aria-label="搜索题材"
        @keydown.esc.stop="close"
        @keydown.enter.prevent="pickFirst"
      />
      <p class="genre__caption">预设题材（{{ filtered.length }}）</p>
      <div class="genre__list">
        <button
          v-for="item in filtered"
          :key="item.id"
          type="button"
          role="menuitem"
          class="genre__item"
          :class="{ 'is-selected': item.id === modelValue.id }"
          @click="pick(item)"
        >
          <span class="genre__name">{{ item.name }}</span>
          <span class="genre__tags">{{ item.tags.slice(0, 2).join(' · ') }}</span>
          <span v-if="item.id === modelValue.id" class="genre__check" aria-hidden="true">✓</span>
        </button>
        <p v-if="!filtered.length" class="genre__none">没有匹配的题材，可在下方自定义</p>
      </div>

      <div v-if="customAllowed" class="genre__custom">
        <label class="genre__caption" :for="inputId">自定义题材</label>
        <div class="genre__custom-row">
          <input
            :id="inputId"
            ref="customInput"
            v-model="customText"
            class="genre__input"
            type="text"
            maxlength="20"
            placeholder="如：赛博修仙"
            @keydown.enter.prevent="applyCustom"
          />
          <button type="button" class="genre__apply" :disabled="!customText.trim()" @click="applyCustom">
            使用
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Audience, GenreItem, GenreSelection } from '@/types'

const props = defineProps<{
  options: GenreItem[]
  audience: Audience
  modelValue: GenreSelection
  customAllowed: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: GenreSelection): void
}>()

const root = ref<HTMLElement | null>(null)
const customInput = ref<HTMLInputElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const menuOpen = ref(false)
const menuUp = ref(false)
const menuMax = ref(0)
const customText = ref('')
const query = ref('')
const inputId = 'genre-custom-input'

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return props.options.filter((item) => {
    if (!(item.audience.includes(props.audience) || item.audience.includes('all'))) return false
    if (!keyword) return true
    return (
      item.name.toLowerCase().includes(keyword) ||
      item.tags.some((tag) => tag.toLowerCase().includes(keyword))
    )
  })
})

function toggle(): void {
  menuOpen.value = !menuOpen.value
}

function close(): void {
  menuOpen.value = false
}

function pick(item: GenreItem): void {
  emit('update:modelValue', { id: item.id, name: item.name })
  close()
}

function pickFirst(): void {
  const first = filtered.value[0]
  if (first) pick(first)
}

function applyCustom(): void {
  const name = customText.value.trim()
  if (!name) return
  emit('update:modelValue', { id: null, name })
  close()
}

function onDocumentClick(event: MouseEvent): void {
  if (!menuOpen.value) return
  if (root.value && !root.value.contains(event.target as Node)) close()
}

/* 面板在首屏垂直居中，下拉可能顶到视口底部：按上下可用空间决定方向并限高 */
function updatePlacement(): void {
  const trigger = root.value?.querySelector<HTMLElement>('.genre__trigger')
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const headerBottom = document.querySelector('.topbar')?.getBoundingClientRect().bottom ?? 0
  const below = window.innerHeight - rect.bottom - 16
  const above = rect.top - headerBottom - 16
  menuUp.value = below < 320 && above > below
  // 下限 220：保证搜索框、标题与列表首行都可见，不会被压成一条缝
  menuMax.value = Math.max(220, Math.min(420, menuUp.value ? above : below))
}

watch(menuOpen, async (open) => {
  if (open) {
    query.value = ''
    customText.value = props.modelValue.id ? '' : props.modelValue.name
    updatePlacement()
    await nextTick()
    // 先聚焦再测：聚焦可能引发滚动，改变上下可用空间，测两次保证 menuMax 与最终布局一致
    searchInput.value?.focus()
    updatePlacement()
  }
})

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<style scoped>
.genre {
  position: relative;
}

.genre__trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 12px;
  border-radius: var(--radius-md, 8px);
  border: 1px solid var(--color-line, #e2e6ec);
  background: #fff;
  color: var(--color-text-2, #2b313a);
  font-size: 14px;
  transition: border-color var(--dur-fast) ease, box-shadow var(--dur-fast) ease;
}

.genre__trigger:hover {
  border-color: var(--color-line-strong, #c7ced6);
}

.genre__trigger.is-active {
  border-color: var(--color-brand, #0d9488);
  color: var(--color-text, #2b313a);
}

.genre__label {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.genre__caret {
  width: 12px;
  height: 12px;
  opacity: 0.8;
}

.genre__menu {
  position: absolute;
  left: 0;
  top: calc(100% + 10px);
  z-index: 30;
  display: flex;
  flex-direction: column;
  width: 288px;
  padding: 12px;
  border-radius: var(--radius-md);
  background: #fff;
  border: 1px solid var(--color-line);
  box-shadow: var(--shadow-lg);
  color: var(--color-text);
}

.genre__menu.is-up {
  top: auto;
  bottom: calc(100% + 10px);
}

/* 面板被 maxHeight 约束时只允许列表伸缩，搜索框等固定件不参与压缩，
   否则空态（列表项多）会把搜索框压瘪、输入态又恢复，高度忽高忽低 */
.genre__search {
  flex: none;
  width: 100%;
  height: 34px;
  margin-bottom: 8px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--color-line-strong);
  font-size: var(--text-sm);
}

.genre__search:focus {
  outline: none;
  border-color: var(--color-brand);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
}

.genre__caption {
  flex: none;
  display: inline-block;
  font-size: var(--text-xs);
  color: var(--color-text-3);
  margin-bottom: 5px;
}

.genre__list {
  flex: 1;
  min-height: 64px;
  max-height: 244px;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 10px;
}

.genre__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 9px;
  border-radius: 8px;
  font-size: var(--text-sm);
  text-align: left;
  color: var(--color-text-2);
}

.genre__name {
  flex: none;
  min-width: 64px;
}

.genre__tags {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.genre__item.is-selected .genre__tags {
  color: var(--color-brand);
  opacity: 0.7;
}

.genre__item:hover {
  background: var(--color-bg-soft);
  color: var(--color-text);
}

.genre__item.is-selected {
  background: #eef7f6;
  color: var(--color-brand);
  font-weight: 600;
}

.genre__none {
  padding: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.genre__check {
  font-size: var(--text-xs);
}

.genre__custom {
  flex: none;
  border-top: 1px solid var(--color-line);
  padding: 5px 0 10px 0;
}

.genre__custom-row {
  display: flex;
  gap: 8px;
}

.genre__input {
  flex: 1;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--color-line-strong);
  font-size: var(--text-sm);
}

.genre__input:focus {
  outline: none;
  border-color: var(--color-brand);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
}

.genre__apply {
  height: 34px;
  padding: 0 12px;
  border-radius: 8px;
  background: var(--color-brand);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: 600;
}

.genre__apply:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
