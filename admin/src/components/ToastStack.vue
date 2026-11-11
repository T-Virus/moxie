<script setup lang="ts">
import { toasts, dismissToast } from '../toast'
</script>

<template>
  <Teleport to="body">
    <div v-if="toasts.length" class="toast-stack">
      <div v-for="item in toasts" :key="item.id" class="toast" :class="item.kind" @click="dismissToast(item.id)">
        {{ item.message }}
      </div>
    </div>
  </Teleport>
</template>
