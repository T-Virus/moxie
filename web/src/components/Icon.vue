<script setup lang="ts">
import { ICONS } from '../Icons'
const props = defineProps<{ name: string; size?: number }>()
</script>

<template>
  <span class="i" :style="{ width: (props.size || 18) + 'px', height: (props.size || 18) + 'px' }"
        v-html="ICONS[name] || ''"></span>
</template>

<style scoped>
.i { display: inline-flex; flex: none; vertical-align: middle; }
.i :deep(svg) { width: 100%; height: 100%; display: block; }
</style>
