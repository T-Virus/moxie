<script setup lang="ts">
import { computed } from 'vue'
import { formatNumber } from '../ui'

const props = withDefaults(defineProps<{
  page: number
  pageSize: number
  total: number | null
  loading?: boolean
}>(), { loading: false })

const emit = defineEmits<{ (e: 'update:page', value: number): void }>()

const totalPages = computed(() =>
  props.total !== null ? Math.max(Math.ceil(props.total / Math.max(props.pageSize, 1)), 1) : null,
)
const canPrev = computed(() => props.page > 1 && !props.loading)
const canNext = computed(() => {
  if (props.loading) return false
  return totalPages.value === null ? true : props.page < totalPages.value
})
</script>

<template>
  <div class="pager">
    <span class="hint">
      每页 {{ pageSize }} 条<span v-if="total !== null"> · 共 {{ formatNumber(total) }} 条</span>
    </span>
    <button class="btn ghost sm" :disabled="!canPrev" @click="emit('update:page', page - 1)">上一页</button>
    <span class="page-no">第 {{ page }} 页<span v-if="totalPages"> / {{ totalPages }}</span></span>
    <button class="btn ghost sm" :disabled="!canNext" @click="emit('update:page', page + 1)">下一页</button>
  </div>
</template>
