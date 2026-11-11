<script setup lang="ts">
import Icon from './Icon.vue'
defineProps<{ title: string; desc?: string }>()
</script>

<template>
  <div class="empty">
    <Icon name="file" :size="44" />
    <b>{{ title }}</b>
    <span>{{ desc || '' }}</span>
  </div>
</template>
