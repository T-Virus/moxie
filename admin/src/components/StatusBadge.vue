<script setup lang="ts">
import { computed } from 'vue'
import { statusClass, statusLabel } from '../ui'

const props = defineProps<{ value?: string | null; label?: string; dot?: boolean }>()
const cls = computed(() => statusClass(props.value))
const text = computed(() => props.label || statusLabel(props.value))
</script>

<template>
  <span class="badge" :class="cls">
    <i v-if="dot" class="dot"></i>
    {{ text }}
  </span>
</template>
